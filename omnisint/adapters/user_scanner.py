"""user-scanner (kaifcodec): 400+ vectors across usernames and emails,
plus Hudson Rock infostealer-breach lookups."""
from __future__ import annotations

import json

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult

_META_SKIP = {"url", "site_name", "username", "status", "reason"}


class UserScannerAdapter(Adapter):
    name = "user-scanner"
    binary = "user-scanner"
    accepts = (IdType.USERNAME, IdType.EMAIL)
    #: Observed 8-32s for a username and ~27s for an email; the spread is
    #: rate limiting, not progress, so three minutes is already generous.
    max_seconds = 180
    base_weight = 0.68
    install = "pip install user-scanner"
    homepage = "https://github.com/kaifcodec/user-scanner"
    description = "400+ username/email vectors with profile metadata"

    def run(self, ident, workdir) -> AdapterResult:
        out = workdir / f"userscanner_{ident.type.value}_{ident.value}.json"
        flag = "-e" if ident.type is IdType.EMAIL else "-u"
        cmd = [
            self.locate(), flag, ident.value,
            "-f", "json", "-o", str(out),
            "-t", str(self.opts.request_timeout),
        ]
        if not self.opts.nsfw:
            cmd.append("--no-nsfw")
        if self.opts.delay:
            cmd += ["-d", str(self.opts.delay)]

        proc = self._sh(cmd, cwd=workdir)
        res = AdapterResult()

        if not out.exists():
            res.warnings.append(
                f"user-scanner produced no JSON "
                f"({proc.stderr.strip()[:200] or proc.stdout.strip()[-200:]})"
            )
            return res

        try:
            rows = json.loads(out.read_text() or "[]")
        except json.JSONDecodeError as exc:
            res.warnings.append(f"user-scanner JSON unparseable: {exc}")
            return res

        if isinstance(rows, dict):
            rows = rows.get("results", [])

        for row in rows:
            if not isinstance(row, dict):
                continue
            status_raw = str(row.get("status", "")).strip().lower()
            site = row.get("site_name") or row.get("module") or "unknown"

            if status_raw in {"found", "registered", "exists"}:
                status = Status.FOUND
            elif status_raw in {"not found", "not registered", "available"}:
                continue
            else:
                res.evidence.append(
                    Evidence(
                        source=self.name, platform=site, url=row.get("url"),
                        status=Status.INCONCLUSIVE, weight=0.0,
                        note=row.get("reason") or status_raw or "unknown",
                    )
                )
                continue

            meta = dict(row.get("extra") or {})
            media = row.get("media") or {}
            if media.get("avatar"):
                meta["avatar"] = media["avatar"]
            for k, v in row.items():
                if k not in _META_SKIP and k not in {"extra", "media", "category"} and v:
                    meta.setdefault(k, v)

            res.evidence.append(
                Evidence(
                    source=self.name, platform=site, url=row.get("url"),
                    status=status,
                    weight=min(0.88, self.base_weight + (0.15 if meta else 0.0)),
                    metadata=meta,
                    note=row.get("category"),
                )
            )

            for key in ("email", "emails", "linked_email"):
                if row.get(key) or meta.get(key):
                    raw = str(row.get(key) or meta.get(key))
                    for piece in raw.replace(";", ",").split(","):
                        cand = Identifier.parse(
                            piece, origin=f"user-scanner:{site}", depth=ident.depth + 1
                        )
                        if cand.type is IdType.EMAIL:
                            res.pivots.append(cand)
        return res


class HudsonRockAdapter(Adapter):
    """Infostealer-breach exposure via user-scanner's Hudson Rock module.

    A hit means the identifier appeared in malware-stealer logs — i.e. a
    machine belonging to, or used by, the subject was compromised. This is
    exposure intelligence: useful defensively, and never a credential source.
    """
    name = "hudsonrock"
    binary = "user-scanner"
    accepts = (IdType.USERNAME, IdType.EMAIL)
    base_weight = 0.8
    # `user-scanner --hudson` runs a full sweep rather than a single lookup,
    # so in practice this always hits the timeout and returns nothing while
    # adding 90s to every scan. Opt-in until that changes: ask for it with
    # --hudson when you actually want breach exposure.
    max_seconds = 60
    opt_in = True
    install = "pip install user-scanner"
    homepage = "https://github.com/kaifcodec/user-scanner"
    description = "infostealer breach exposure (Hudson Rock)"

    def run(self, ident, workdir) -> AdapterResult:
        out = workdir / f"hudson_{ident.value}.json"
        flag = "-e" if ident.type is IdType.EMAIL else "-u"
        proc = self._sh(
            [self.locate(), flag, ident.value, "--hudson",
             "-f", "json", "-o", str(out)],
            cwd=workdir,
        )
        res = AdapterResult()
        payload = None
        if out.exists():
            try:
                payload = json.loads(out.read_text() or "null")
            except json.JSONDecodeError:
                payload = None

        text = proc.stdout
        compromised = bool(payload) or "compromised" in text.lower()
        if not compromised:
            return res

        res.extras["breaches"] = [{
            "source": "Hudson Rock (infostealer logs)",
            "identifier": ident.value,
            "detail": payload if payload else text.strip()[-1500:],
            "meaning": "identifier seen in stealer-malware logs; treat as a "
                       "credential-hygiene warning for the subject",
        }]
        return res
