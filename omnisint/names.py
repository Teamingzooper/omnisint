"""Turning a person's name into something the tools can actually search.

None of the backends accept "Alex Rivera" — they want a handle. A
name is still worth having, for two reasons:

1. It is the best *anchor* we have for attribution. If you tell us who you
   are looking for, persona clustering can pick the primary identity by
   matching that name instead of guessing from corroboration counts.
2. It can be expanded into the handles people actually pick.

The expansion is speculative by construction, so it is opt-in and every
identifier it produces is labelled with where it came from.
"""
from __future__ import annotations

import re
import unicodedata


def normalize(name: str) -> str:
    """Fold accents and punctuation so 'José Núñez' matches 'jose nunez'."""
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", stripped.lower()).strip()


def parts(name: str) -> list[str]:
    return [p for p in normalize(name).split() if len(p) > 1]


def similarity(a: str, b: str) -> float:
    """How much two names overlap, by shared word tokens.

    Deliberately token-based rather than fuzzy string distance: 'Alex
    Rivera' and 'Jordan Rivera' share a surname but are different
    people, and edit distance would rate them far too close.
    """
    ta, tb = set(parts(a)), set(parts(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def candidates(name: str, limit: int = 12) -> list[str]:
    """Handles a person plausibly derives from their name."""
    tokens = parts(name)
    if not tokens:
        return []
    if len(tokens) == 1:
        return tokens[:limit]

    first, last = tokens[0], tokens[-1]
    fi, li = first[0], last[0]
    middle = tokens[1:-1]

    out = [
        f"{first}{last}", f"{first}.{last}", f"{first}_{last}", f"{first}-{last}",
        f"{fi}{last}", f"{fi}.{last}", f"{first}{li}", f"{last}{first}",
        f"{last}.{first}", first, last,
    ]
    if middle:
        mi = "".join(t[0] for t in middle)
        out += [f"{first}{mi}{last}", f"{fi}{mi}{li}"]

    seen, unique = set(), []
    for c in out:
        c = c.strip("._-")
        # Most sites reject handles under three characters anyway.
        if len(c) < 3 or c in seen:
            continue
        seen.add(c)
        unique.append(c)
    return unique[:limit]
