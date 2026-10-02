"""The OSINT Framework catalogue: where to look by hand.

Omnisint automates the tools it can drive. Most of what the OSINT Framework
indexes cannot be automated honestly — the resources are web forms, paywalls,
captchas and services whose terms forbid scraping — so this is a *launcher*,
not a scraper. Nothing here is ever queried; it tells you which resources
accept the identifier you have, and what each one costs you to use.

The field that earns its place is `opsec`. A resource marked *active* reaches
out to the subject's own infrastructure when you query it, which is exactly
the thing Omnisint avoids by default. Those are listed separately so you
choose them deliberately.

Data: github.com/lockfale/OSINT-Framework (MIT, Justin Nordine).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from .models import Identifier, IdType

DATA = Path(__file__).parent / "data" / "osint-framework.json"

#: Our identifier types onto the catalogue's buckets.
TYPE_MAP = {
    IdType.USERNAME: "username",
    IdType.EMAIL: "email",
    IdType.DOMAIN: "domain",
    IdType.URL: "domain",
    IdType.PHONE: "phone",
    IdType.NAME: "name",
}


@lru_cache(maxsize=1)
def _catalog() -> dict:
    try:
        return json.loads(DATA.read_text())
    except (OSError, json.JSONDecodeError):
        return {"resources": [], "attribution": "", "source": ""}


def attribution() -> str:
    c = _catalog()
    return f"{c.get('attribution', '')} — {c.get('source', '')}".strip(" —")


#: Editorial ordering. Sorting the free/passive tier alphabetically puts
#: "AnnualReports.com" above Have I Been Pwned, which is useless as an answer
#: to "what should I try first". These are the standard first stops, in the
#: order an investigator would actually reach for them.
FEATURED: dict[str, tuple[str, ...]] = {
    "username": ("whatsmyname web", "namechk", "sherlock", "social searcher",
                 "whatsmyname (t)"),
    "email": ("have i been pwned", "epieos", "hunter", "holehe", "dehashed",
              "breach"),
    "domain": ("crt.sh", "urlscan.io", "viewdns", "shodan", "censys",
               "wayback machine", "whois"),
    "phone": ("phoneinfoga", "truecaller", "whitepages reverse phone"),
    "name": ("thatsthem", "whitepages", "anywho", "black book online"),
    "ip": ("shodan", "censys", "urlscan.io", "viewdns"),
    "crypto": ("blockchain", "etherscan", "blockchair"),
    "media": ("exiftool", "tineye", "google reverse", "yandex"),
}


def _featured_rank(entry: dict, bucket: str) -> int:
    name = entry["name"].lower()
    for i, frag in enumerate(FEATURED.get(bucket, ())):
        if frag in name:
            return i
    return 99


def _rank(entry: dict) -> tuple:
    """Cheapest and least intrusive first; that is what you try first."""
    return (
        entry.get("opsec") != "passive",        # passive before active
        entry.get("pricing") not in ("free", "free/freemium"),
        bool(entry.get("registration")),        # no account needed first
        bool(entry.get("local_install")),       # nothing to install first
        bool(entry.get("degraded")),
        entry["name"].lower(),
    )


def leads_for(identifiers, limit: int = 10, include_active: bool = True) -> dict:
    """Resources that accept the identifier types we are holding.

    Returns {bucket: [entry, …]} ordered by what is cheapest to try.
    """
    wanted: set[str] = set()
    for ident in identifiers:
        bucket = TYPE_MAP.get(getattr(ident, "type", ident))
        if bucket:
            wanted.add(bucket)
    if not wanted:
        return {}

    out: dict[str, list[dict]] = {}
    for bucket in sorted(wanted):
        hits = [e for e in _catalog()["resources"] if bucket in e.get("types", [])]
        if not include_active:
            hits = [e for e in hits if e.get("opsec") == "passive"]
        out[bucket] = sorted(
            hits, key=lambda e: (_featured_rank(e, bucket), *_rank(e)))[:limit]
    return {k: v for k, v in out.items() if v}


def counts() -> dict:
    """How many resources we hold per bucket, for the UI badges."""
    totals: dict[str, int] = {}
    for entry in _catalog()["resources"]:
        for t in entry.get("types", []):
            totals[t] = totals.get(t, 0) + 1
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def flags(entry: dict) -> list[str]:
    """Short, honest warnings about what using this resource costs you."""
    out = []
    if entry.get("opsec") == "active":
        out.append("touches the subject")
    elif entry.get("opsec") == "unknown":
        out.append("opsec unknown")
    if entry.get("registration"):
        out.append("account needed")
    if entry.get("pricing") == "paid":
        out.append("paid")
    elif entry.get("pricing") == "freemium":
        out.append("freemium")
    if entry.get("local_install"):
        out.append("install required")
    if entry.get("google_dork"):
        out.append("search dork")
    if entry.get("api"):
        out.append("has API")
    if entry.get("degraded"):
        out.append("flaky")
    return out
