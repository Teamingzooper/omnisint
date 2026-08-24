"""Pre-flight checks on what the operator is about to search for.

The most expensive mistake this tool allows is a bad query. Searching
`michael`, `field` and `trip` as three separate handles takes ninety seconds
and returns nine hundred accounts belonging to ninety different people —
technically correct, practically useless, and the operator only finds out
afterwards.

Everything here runs before a single request goes out. It never blocks a
scan; it says what is likely to happen and offers a better query.
"""
from __future__ import annotations

import re

from .models import Identifier, IdType

#: Handles that thousands of people hold. Not exhaustive — it does not need
#: to be, because the point is to catch the obvious cases early.
COMMON_WORDS = set("""
about admin all and any app art back bad best big blue book box boy business
buy car card cat change check city class club code cool cop copy cost create
dark data day dead deal dev die dog down draw dream drive drop early east easy
eat end enjoy event eye face fact fall family fast field fight file film find
fire first fish fit fix flow food foot force free friend fun future game girl
give glass go gold good great green group grow guy hand happy hard head health
help hero hi high hit home hope hot hour house how ice idea image info inside
job join joy jump keep key kid kind king land last late law learn left level
life light like line list live local long look lost love low luck mail main
make man map market master max media meet mind mine money moon more move music
name near need net new news next nice night north note now ocean off office
one only open order other out page paper park part party pass past path pay
peace people phone photo pick picture place plan play point post power press
price project public pure push put queen quick rain read real red rest ride
right river road rock room root run safe sale save school sea search season
see send service set shadow share ship shop short show side sign silver simple
site sky sleep small smart smile snow social soft sound south space speak
sport spring staff star start state stay step stone stop store storm story
street strong study style sun super support sure sweet swim system table take
talk tank team tech test text thing think time today top total touch tour town
track trade train travel tree trip true trust try turn type under unit up use
user value video view voice walk wall want war watch water wave way web week
west white wild win wind wine wish wolf wonder wood word work world write year
young zone
""".split())

COMMON_NAMES = set("""
aaron adam alan alex alexander alice amanda amy andrew angela ann anna anthony
ashley barbara ben benjamin betty bill bob brandon brian bruce carl carol
charles chris christian christina christopher cindy claire dan daniel dave
david dean debbie dennis diana don donald donna doug edward eric erica emily
emma frank gary george grace greg hannah harry heather helen henry ian jack
jackson jacob james jamie jane janet jason jean jeff jennifer jeremy jerry
jessica jim joan joe john jon jonathan jordan jose joseph josh joshua juan
judy julia julie justin karen kate katherine kathy keith kelly ken kenneth
kevin kim kyle larry laura lauren lee linda lisa liz logan lori louis lucas
luke mandy marc marcus margaret maria marie mark martin mary matt matthew max
megan melissa michael michelle mike nancy nathan neil nick nicholas nicole
noah oliver oscar pat patricia patrick paul peter phil philip rachel ralph
ray raymond rebecca richard rick rob robert roger ron ronald rose roy ruth
ryan sam samuel sandra sara sarah scott sean sharon sophia stephanie stephen
steve steven sue susan tammy taylor terry theresa thomas tim timothy tina tom
tony tracy travis tyler victor victoria vincent walter wayne wendy will
william zach zachary
""".split())


def _flat(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def collision_risk(ident: Identifier) -> tuple[str, str] | None:
    """How crowded is this identifier likely to be? (level, reason)."""
    if ident.type is not IdType.USERNAME:
        return None
    flat = _flat(ident.value)
    if not flat or any(c.isdigit() for c in flat):
        return None          # digits make a handle far more distinctive
    if flat in COMMON_NAMES:
        return ("high", "a common given name — thousands of people hold this handle")
    if flat in COMMON_WORDS:
        return ("high", "an ordinary English word — held on most platforms already")
    if len(flat) <= 4:
        return ("high", "a very short handle — taken on almost every platform")
    if len(flat) <= 6:
        return ("medium", "a short handle — these collide often")
    return None


def _looks_like_split_name(seeds: list[Identifier]) -> list[str] | None:
    """Detect a person's name typed without commas, so it split into words."""
    words = [s for s in seeds
             if s.type is IdType.USERNAME and s.value.isalpha() and len(s.value) > 1]
    if len(words) < 2:
        return None
    namey = [w for w in words if _flat(w.value) in COMMON_NAMES]
    # At least one recognisable given name and no digits anywhere: this reads
    # as "alex rivera" rather than as two separate handles.
    if namey and all(not any(c.isdigit() for c in w.value) for w in words):
        return [w.value for w in words]
    return None


def review(seeds: list[Identifier], secondary: list[str]) -> dict:
    """What is likely to go wrong with this query, and what would fix it."""
    problems: list[dict] = []
    suggestions: list[str] = []

    split = _looks_like_split_name(seeds)
    if split:
        joined = " ".join(split)
        problems.append({
            "level": "high",
            "text": f"{len(split)} separate handles were read from what looks "
                    f"like one name: {', '.join(repr(w) for w in split)}.",
            "fix": f"Use commas so it stays together: {joined}",
            "rewrite": ", ".join([joined] + [s.value for s in seeds
                                             if s.value not in split]),
        })

    risky = []
    for s in seeds:
        risk = collision_risk(s)
        if risk:
            risky.append((s.value, *risk))
    for value, level, reason in risky:
        problems.append({
            "level": level,
            "text": f"'{value}' is {reason}.",
            "fix": "Expect many unrelated people. Add a name or a secondary "
                   "term so the results can be told apart.",
        })

    if not secondary and (risky or len(seeds) > 2):
        suggestions.append(
            "Add something you know about them after a semicolon — employer, "
            "school, city. It is never searched, only used to tell the real "
            "accounts from the coincidences.")
    if not any(s.type is IdType.NAME for s in seeds) and risky:
        suggestions.append(
            "Add their real name. It is what decides which of the matching "
            "accounts is actually your subject.")

    est = sum({IdType.USERNAME: 120, IdType.EMAIL: 15}.get(s.type, 2) for s in seeds)
    for value, level, _ in risky:
        if level == "high":
            est *= 3

    return {
        "problems": problems,
        "suggestions": suggestions,
        "expected_hits": est,
        "noisy": any(p["level"] == "high" for p in problems),
    }
