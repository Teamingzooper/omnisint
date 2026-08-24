"""Adapters implemented in-process rather than by shelling out.

These fill gaps the installed CLI tools leave: avatar/profile lookup for an
email, mail and DNS infrastructure, and (opt-in, key-gated) breach exposure.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult

_UA = "omnisint/1.0 (+research; contact: local operator)"


def _get_json(url: str, timeout: int, headers: dict | None = None):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace")), resp.status


class GravatarAdapter(Adapter):
    """Gravatar exposes a public profile JSON keyed by the MD5 of an email.

    A hit proves the address exists and often carries a real name, bio and a
    list of self-declared accounts — high-quality, subject-published data.
    """
    name = "gravatar"
    binary = None
    accepts = (IdType.EMAIL,)
    base_weight = 0.9
    install = "built in"
    description = "Gravatar public profile by email hash"

    def run(self, ident, workdir) -> AdapterResult:
        res = AdapterResult()
        digest = hashlib.md5(ident.value.strip().lower().encode()).hexdigest()
        try:
            data, _ = _get_json(
                f"https://gravatar.com/{digest}.json", self.opts.request_timeout
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return res  # no Gravatar; genuinely absent, not an error
            res.warnings.append(f"gravatar: HTTP {exc.code}")
            return res
        except Exception as exc:
            res.warnings.append(f"gravatar: {exc}")
            return res

        entries = (data or {}).get("entry") or []
        for entry in entries:
            meta = {}
            if entry.get("displayName"):
                meta["fullname"] = entry["displayName"]
            name_blk = entry.get("name") or {}
            if isinstance(name_blk, dict) and name_blk.get("formatted"):
                meta["fullname"] = name_blk["formatted"]
            if entry.get("aboutMe"):
                meta["bio"] = entry["aboutMe"]
            if entry.get("currentLocation"):
                meta["location"] = entry["currentLocation"]
            if entry.get("thumbnailUrl"):
                meta["avatar"] = entry["thumbnailUrl"]

            res.evidence.append(
                Evidence(
                    source=self.name, platform="Gravatar",
                    url=entry.get("profileUrl"),
                    status=Status.FOUND, weight=self.base_weight,
                    metadata=meta, note="subject-published profile",
                )
            )

            # Gravatar profiles list accounts the subject linked themselves.
            for acct in entry.get("accounts") or []:
                if not isinstance(acct, dict):
                    continue
                res.evidence.append(
                    Evidence(
                        source=self.name,
                        platform=acct.get("shortname") or acct.get("domain") or "linked",
                        url=acct.get("url"),
                        status=Status.FOUND, weight=0.9,
                        metadata={"username": acct.get("username")} if acct.get("username") else {},
                        note="self-declared on Gravatar",
                    )
                )
                if acct.get("username"):
                    cand = Identifier.parse(
                        acct["username"], origin="gravatar", depth=ident.depth + 1
                    )
                    if cand.type is IdType.USERNAME:
                        res.pivots.append(cand)

            for name in (entry.get("preferredUsername"), entry.get("username")):
                cand = Identifier.parse(str(name or ""), origin="gravatar", depth=ident.depth + 1)
                if cand.type is IdType.USERNAME:
                    res.pivots.append(cand)
        return res


class InfrastructureAdapter(Adapter):
    """WHOIS + DNS for a domain, or for the domain half of an email.

    Tells you whether an address is a throwaway/provider mailbox or sits on
    a domain the subject controls — which changes what the rest means.
    """
    name = "infrastructure"
    binary = None
    accepts = (IdType.EMAIL, IdType.DOMAIN, IdType.URL)
    base_weight = 0.0  # produces context, not accounts
    install = "built in"
    install_note = "DNS records need: pip install dnspython (a dependency, normally present)"
    description = "WHOIS, MX and DNS context for a domain"

    FREEMAIL = {
        "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
        "live.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
        "gmx.com", "mail.com", "yandex.ru", "zoho.com", "tutanota.com", "fastmail.com",
    }

    def _domain_of(self, ident) -> str | None:
        if ident.type is IdType.EMAIL:
            return ident.value.rsplit("@", 1)[-1].lower()
        if ident.type is IdType.DOMAIN:
            return ident.value.lower()
        if ident.type is IdType.URL:
            m = re.match(r"https?://([^/:]+)", ident.value, re.I)
            return m.group(1).lower() if m else None
        return None

    def run(self, ident, workdir) -> AdapterResult:
        res = AdapterResult()
        domain = self._domain_of(ident)
        if not domain:
            return res

        info: dict = {"domain": domain, "freemail_provider": domain in self.FREEMAIL}

        try:
            import dns.resolver  # type: ignore

            resolver = dns.resolver.Resolver()
            resolver.lifetime = min(self.opts.request_timeout, 10)
            for rtype in ("A", "AAAA", "MX", "NS", "TXT"):
                try:
                    answers = resolver.resolve(domain, rtype)
                    info[rtype.lower()] = sorted(
                        r.to_text().strip('"') for r in answers
                    )[:10]
                except Exception:
                    continue
            spf = [t for t in info.get("txt", []) if t.lower().startswith("v=spf1")]
            if spf:
                info["spf"] = spf
        except ImportError:
            res.warnings.append("dnspython not installed; DNS context skipped")

        if not info.get("freemail_provider"):
            proc = self._sh(["whois", domain], timeout=min(self.opts.request_timeout, 30))
            if proc.returncode == 0 and proc.stdout:
                wanted = (
                    "registrar", "creation date", "created", "registered on",
                    "updated date", "expiry", "expiration", "registrant",
                    "org", "name server", "country",
                )
                lines = []
                for line in proc.stdout.splitlines():
                    low = line.strip().lower()
                    if any(low.startswith(w) for w in wanted) and "redacted" not in low:
                        lines.append(line.strip())
                info["whois"] = lines[:25]

        res.extras["infrastructure"] = {domain: info}

        if info.get("mx") and info["freemail_provider"]:
            res.extras.setdefault("notes", []).append(
                f"{domain} is a consumer mail provider — the address says "
                "nothing about infrastructure the subject controls."
            )
        return res


class BreachAdapter(Adapter):
    """Have I Been Pwned, opt-in via HIBP_API_KEY.

    Breach membership is defensive intelligence: which of the subject's
    accounts are exposed. It never yields passwords, and this adapter is
    inert unless the operator supplies their own paid API key.
    """
    name = "hibp"
    binary = None
    accepts = (IdType.EMAIL,)
    base_weight = 0.0
    install = "built in"
    install_note = "needs a paid key: export HIBP_API_KEY=... (haveibeenpwned.com/API/Key)"
    homepage = "https://haveibeenpwned.com/API/v3"
    description = "Have I Been Pwned breach exposure (needs HIBP_API_KEY)"

    @classmethod
    def available(cls) -> bool:
        return bool(os.environ.get("HIBP_API_KEY"))

    def run(self, ident, workdir) -> AdapterResult:
        res = AdapterResult()
        key = os.environ.get("HIBP_API_KEY")
        if not key:
            return res
        url = (
            "https://haveibeenpwned.com/api/v3/breachedaccount/"
            f"{urllib.parse.quote(ident.value)}?truncateResponse=false"
        )
        try:
            data, _ = _get_json(
                url, self.opts.request_timeout,
                headers={"hibp-api-key": key},
            )
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                res.extras["notes"] = [f"{ident.value}: no HIBP breaches on record"]
                return res
            res.warnings.append(f"hibp: HTTP {exc.code}")
            return res
        except Exception as exc:
            res.warnings.append(f"hibp: {exc}")
            return res

        res.extras["breaches"] = [
            {
                "source": "Have I Been Pwned",
                "identifier": ident.value,
                "name": b.get("Name"),
                "domain": b.get("Domain"),
                "date": b.get("BreachDate"),
                "accounts": b.get("PwnCount"),
                "data": b.get("DataClasses"),
                "meaning": "account exposed in this breach; subject should "
                           "rotate credentials and enable MFA",
            }
            for b in (data or [])
        ]
        return res
