"""Confirmed accounts: the operator's own judgement, shared by both UIs.

Pressing + in the browser and `pin 3` in the console must mean exactly the
same thing, so the logic for what a pin *is* — and what a rescan should do
with one — lives here rather than in either front-end.
"""
from __future__ import annotations

from .models import Account

#: Fields worth carrying from a confirmed account into the next scan as
#: cross-check terms. An employer or a city separates a real match from a
#: coincidence; a follower count does not.
CONTEXT_FIELDS = ("company", "employer", "organization", "school",
                  "university", "location", "clan", "job_title", "headline")

#: Where a handle might be hiding in a platform's metadata.
HANDLE_FIELDS = ("username", "login", "handle", "screen_name")


def pin_from_account(account: Account) -> dict:
    """What a confirmed account contributes to the next scan."""
    meta = account.metadata or {}
    terms: list[str] = []
    for key in CONTEXT_FIELDS:
        value = str(meta.get(key) or "").strip()
        if value and value not in terms and len(terms) < 6:
            terms.append(value)
    handle = ""
    for key in HANDLE_FIELDS:
        if str(meta.get(key) or "").strip():
            handle = str(meta[key]).strip()
            break
    return {
        "platform": account.platform,
        "url": account.url or "",
        "username": handle,
        "fullname": str(meta.get("fullname") or "").strip(),
        "terms": terms,
    }


def anchors_from_pins(pinned: list[dict]) -> tuple[list[str], list[str]]:
    """Turn confirmed accounts into things worth searching and matching.

    A confirmed account is the richest anchor an operator can give us: its
    handle becomes a target in its own right, its real name anchors persona
    clustering, and its employer, school or city become cross-checks. This
    is what makes "confirm these, then rescan" better than re-running the
    same query.
    """
    seeds: list[str] = []
    terms: list[str] = []
    for pin in pinned:
        for key in ("username", "handle", "login"):
            value = str(pin.get(key) or "").strip()
            if value and value not in seeds:
                seeds.append(value)
        name = str(pin.get("fullname") or "").strip()
        if name and name not in seeds:
            seeds.append(name)
        for term in pin.get("terms") or []:
            term = str(term).strip()
            if term and term not in terms:
                terms.append(term)
    return seeds, terms


def key_for(account: Account) -> str:
    """Stable identity for a pin, matching how correlate resolves them."""
    return (account.url or account.platform or "").lower()
