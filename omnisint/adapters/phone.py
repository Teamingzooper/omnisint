"""Phone number intelligence.

Two layers, deliberately separated:

* :class:`PhoneAdapter` is entirely offline. It parses the number against
  Google's libphonenumber metadata to establish country, carrier, line type
  and plausible timezones. Nothing leaves the machine, so it cannot tip off
  anyone and cannot be rate-limited.
* :class:`ToutatisAdapter` and the email-linkage layer only run when the
  operator has supplied credentials, because they query live services.

Phone numbers were previously detected and then silently dropped — the type
was recognised but no adapter accepted it, so a scan produced zero tasks.
"""
from __future__ import annotations

import re

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult

_LINE_TYPES = {
    0: "fixed line", 1: "mobile", 2: "fixed line or mobile", 3: "toll free",
    4: "premium rate", 5: "shared cost", 6: "VoIP", 7: "personal number",
    8: "pager", 9: "UAN", 10: "voicemail", 27: "unknown",
}


class PhoneAdapter(Adapter):
    """Offline number metadata: country, carrier, line type, timezones."""
    name = "phone"
    binary = None
    accepts = (IdType.PHONE,)
    base_weight = 0.0   # produces context, not accounts
    install = "pip install phonenumbers"
    homepage = "https://github.com/daviddrysdale/python-phonenumbers"
    description = "offline number parsing: country, carrier, line type"

    @classmethod
    def available(cls) -> bool:
        try:
            import phonenumbers  # noqa: F401
            return True
        except ImportError:
            return False

    def run(self, ident, workdir) -> AdapterResult:
        import phonenumbers
        from phonenumbers import carrier, geocoder, timezone

        res = AdapterResult()
        raw = ident.value.strip()
        # Without a leading +, libphonenumber needs a region hint; assume the
        # number is already international rather than guessing a country.
        parsed = None
        for region in (None, "US"):
            try:
                parsed = phonenumbers.parse(raw, region)
                if phonenumbers.is_possible_number(parsed):
                    break
            except phonenumbers.NumberParseException:
                continue
        if parsed is None:
            res.warnings.append(f"phone: could not parse {raw!r}")
            return res

        valid = phonenumbers.is_valid_number(parsed)
        info = {
            "input": raw,
            "e164": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164),
            "international": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
            "national": phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.NATIONAL),
            "country_code": parsed.country_code,
            "region": phonenumbers.region_code_for_number(parsed) or "unknown",
            "location": geocoder.description_for_number(parsed, "en") or "unknown",
            "carrier": carrier.name_for_number(parsed, "en") or "unknown",
            "line_type": _LINE_TYPES.get(
                phonenumbers.number_type(parsed), "unknown"),
            "timezones": list(timezone.time_zones_for_number(parsed)),
            "valid": valid,
            "possible": phonenumbers.is_possible_number(parsed),
        }
        res.extras["phones"] = {info["e164"]: info}

        if not valid:
            res.warnings.append(
                f"phone {raw}: parses but is not a valid number for "
                f"{info['region']} — check the country code before relying on it"
            )
        # A carrier lookup is a snapshot: number portability means the
        # carrier on record may not be the carrier in use.
        if info["carrier"] != "unknown":
            res.extras.setdefault("notes", []).append(
                f"phone {info['e164']}: carrier '{info['carrier']}' is from "
                "static metadata; number portability makes this unreliable."
            )
        return res


class ToutatisAdapter(Adapter):
    """Instagram account detail via toutatis.

    Instagram exposes an obfuscated recovery email and phone on many
    accounts, which is often the bridge between a handle and a real
    identity. It requires a logged-in session cookie, so it stays inert
    unless the operator sets TOUTATIS_SESSION_ID themselves — this uses
    *your* Instagram session against Instagram's terms, and that has to be
    a deliberate choice, not a default.
    """
    name = "toutatis"
    binary = "toutatis"
    accepts = (IdType.USERNAME,)
    base_weight = 0.85
    max_seconds = 120
    install = "pip install toutatis"
    install_note = "then: export TOUTATIS_SESSION_ID=<your Instagram sessionid cookie>"
    homepage = "https://github.com/megadose/toutatis"
    description = "Instagram detail incl. obfuscated email/phone (needs session)"

    @classmethod
    def available(cls) -> bool:
        import os
        import shutil
        return bool(os.environ.get("TOUTATIS_SESSION_ID")) and bool(
            shutil.which("toutatis"))

    def run(self, ident, workdir) -> AdapterResult:
        import os

        res = AdapterResult()
        session = os.environ.get("TOUTATIS_SESSION_ID")
        if not session:
            return res

        proc = self._sh([self.locate(), "-u", ident.value, "-s", session])
        text = proc.stdout or ""
        if "not found" in text.lower() or not text.strip():
            return res

        meta: dict[str, str] = {}
        for line in text.splitlines():
            m = re.match(r"\s*(?:\[\+\]\s*)?([A-Za-z ]+?)\s*:\s*(.+?)\s*$", line)
            if not m:
                continue
            key = m.group(1).strip().lower().replace(" ", "_")
            value = m.group(2).strip()
            if value and value.lower() not in {"none", "null", "n/a"}:
                meta[key] = value

        if not meta:
            return res

        res.evidence.append(
            Evidence(
                source=self.name, platform="Instagram",
                url=f"https://www.instagram.com/{ident.value}/",
                status=Status.FOUND, weight=self.base_weight,
                metadata=meta, note="authenticated lookup",
            )
        )
        # Obfuscated hints (j***@gmail.com) are leads, not addresses; only
        # pivot on something that actually parses as an email.
        for key in ("email", "public_email", "obfuscated_email"):
            value = meta.get(key, "")
            cand = Identifier.parse(value, origin="toutatis", depth=ident.depth + 1)
            if cand.type is IdType.EMAIL and "*" not in value:
                res.pivots.append(cand)
        return res
