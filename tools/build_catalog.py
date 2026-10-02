"""Curate the OSINT Framework catalogue into the subset Omnisint ships.

Source: https://github.com/lockfale/OSINT-Framework (MIT, Justin Nordine).

The upstream file is ~1.1 MB of 1,168 resources, most of which Omnisint has
no way to route to an identifier. This keeps the ones that take an input we
actually recognise, drops anything dead or deprecated, trims the prose, and
normalises the free-text `input` field onto our identifier types.

    python3 tools/build_catalog.py        # refresh omnisint/data/osint-framework.json
"""
from __future__ import annotations

import json
import pathlib
import urllib.request

SRC = ("https://raw.githubusercontent.com/lockfale/OSINT-Framework"
       "/master/public/arf.json")
OUT = pathlib.Path(__file__).resolve().parents[1] / "omnisint/data/osint-framework.json"

# Free-text `input` values are inconsistent ("Domain", "Domain name",
# "URL or domain"), so match on keywords, most specific first.
INPUT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("username", "handle", "nickname", "screen name", "user name"), "username"),
    (("email",), "email"),
    (("phone", "telephone", "msisdn"), "phone"),
    (("ip address", "ip range", "asn", "netblock", "cidr", "mac"), "ip"),
    (("domain", "hostname", "website", "url", "subdomain", "dns"), "domain"),
    (("full name", "person", "people", "name of", "real name",
      "first name", "last name"), "name"),
    (("image", "photo", "picture", "video", "document", "file"), "media"),
    (("wallet", "crypto", "bitcoin", "ethereum", "transaction hash"), "crypto"),
]

# Where `input` is absent or unhelpful, the section it lives in is the hint.
CATEGORY_TYPES = {
    "Username": ["username"],
    "Email Address": ["email"],
    "Domain Name": ["domain"],
    "IP & MAC Address": ["ip"],
    "Telephone Numbers": ["phone"],
    "People Search Engines": ["name"],
    "Public Records": ["name"],
    "Business Records": ["name"],
    "Social Networks": ["username", "name"],
    "Dating": ["username", "name"],
    "Instant Messaging": ["username", "phone"],
    "Images / Videos / Docs": ["media"],
    "Blockchain & Cryptocurrency": ["crypto"],
    "Dark Web": ["username", "email"],
    "Archives": ["domain"],
    "Search Engines": ["name", "username"],
    "Cloud Infrastructure": ["domain"],
}
KEEP_TYPES = {"username", "email", "domain", "phone", "name", "ip", "crypto", "media"}


def classify(leaf: dict, category: str) -> list[str]:
    text = f"{leaf.get('input') or ''} {leaf.get('bestFor') or ''}".lower()
    found = [t for keys, t in INPUT_RULES if any(k in text for k in keys)]
    if not found:
        found = CATEGORY_TYPES.get(category, [])
    # Preserve rule order, drop duplicates.
    seen, out = set(), []
    for t in found:
        if t in KEEP_TYPES and t not in seen:
            seen.add(t); out.append(t)
    return out[:3]


def trim(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip(" ,;.") + "…"


def main() -> None:
    with urllib.request.urlopen(SRC, timeout=60) as r:
        root = json.loads(r.read())

    leaves: list[tuple[str, dict]] = []

    def walk(node, category=None):
        for child in node.get("children", []):
            cat = child["name"] if category is None else category
            if "url" in child:
                leaves.append((cat, child))
            walk(child, cat)

    walk(root)

    out, skipped = [], {"dead": 0, "unroutable": 0}
    for category, leaf in leaves:
        if leaf.get("deprecated") or leaf.get("status") in {"down", "defunct"}:
            skipped["dead"] += 1
            continue
        types = classify(leaf, category)
        if not types:
            skipped["unroutable"] += 1
            continue
        entry = {
            "name": leaf["name"],
            "url": leaf["url"],
            "category": category,
            "types": types,
            # 'active' means querying it reaches out to the subject's own
            # infrastructure — the single most important field here, because
            # Omnisint is passive by default and this is how that leaks.
            "opsec": (leaf.get("opsec") or "unknown").lower(),
            "pricing": leaf.get("pricing") or "unknown",
            "desc": trim(leaf.get("description"), 150),
            "best_for": trim(leaf.get("bestFor"), 110),
        }
        for flag in ("registration", "localInstall", "api", "googleDork"):
            if leaf.get(flag):
                entry[{"localInstall": "local_install",
                       "googleDork": "google_dork"}.get(flag, flag)] = True
        if leaf.get("status") == "degraded":
            entry["degraded"] = True
        if leaf.get("opsecNote"):
            entry["opsec_note"] = trim(leaf["opsecNote"], 160)
        out.append(entry)

    # The upstream file lists some resources under several sections, so the
    # same URL arrives more than once. Keep the richest copy of each.
    best: dict[str, dict] = {}
    for entry in out:
        key = entry["url"].rstrip("/").lower().replace("://www.", "://")
        kept = best.get(key)
        if kept is None:
            best[key] = entry
        else:
            kept["types"] = sorted(set(kept["types"]) | set(entry["types"]))[:3]
            if len(entry.get("desc", "")) > len(kept.get("desc", "")):
                kept["desc"] = entry["desc"]
    duplicates = len(out) - len(best)
    out = sorted(best.values(),
                 key=lambda e: (e["types"][0], e["pricing"] != "free", e["name"].lower()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "https://github.com/lockfale/OSINT-Framework",
        "license": "MIT",
        "attribution": "OSINT Framework by Justin Nordine (@jnordine)",
        "note": "Curated subset. Omnisint never queries these; it points you "
                "at them. Regenerate with tools/build_catalog.py.",
        "resources": out,
    }, indent=1, ensure_ascii=False))

    from collections import Counter
    per = Counter(t for e in out for t in e["types"])
    print(f"kept {len(out)} of {len(leaves)} (dropped {skipped['dead']} dead, "
          f"{skipped['unroutable']} unroutable, {duplicates} duplicate)")
    print("  by type:", dict(per.most_common()))
    print("  opsec  :", dict(Counter(e['opsec'] for e in out)))
    print(f"  {OUT} — {OUT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
