"""Offline checks for the parts that decide what the operator believes."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from omnisint.correlate import (_is_handle_echo, _looks_like_page_title,
                                   canonical_url, combine, normalize_platform)
from omnisint.models import IdType, detect_type


def check(label, cond):
    assert cond, label
    print(f"  ok  {label}")


print("identifier detection")
check("email", detect_type("john@example.com") is IdType.EMAIL)
check("domain", detect_type("example.com") is IdType.DOMAIN)
check("username", detect_type("johndoe") is IdType.USERNAME)
check("url", detect_type("https://x.com/j") is IdType.URL)
check("name", detect_type("John Doe") is IdType.NAME)
check("phone", detect_type("+1 415 555 0100") is IdType.PHONE)
check("email beats domain", detect_type("a@b.co") is IdType.EMAIL)

print("platform normalisation")
check("case", normalize_platform("Github") == normalize_platform("GitHub"))
check("annotation", normalize_platform("GitHubGist [GitHub]") == "github")
check("x==twitter", normalize_platform("X (twitter)") == normalize_platform("Twitter"))
check("url canon", canonical_url("https://www.GitHub.com/u/") == "github.com/u")

print("confidence combination")
one, two, three = combine([0.45]), combine([0.45, 0.68]), combine([0.45, 0.68, 0.70])
check("single weak source stays weak", abs(one - 0.45) < 1e-9)
check("agreement raises confidence", two > one)
check("two sources are not certainty", two < 0.80)
check("three sources still bounded", three < 0.90)
check("monotonic", three > two)
print(f"      1 src={one:.3f}  2 src={two:.3f}  3 src={three:.3f}")

print("name noise filtering")
check("page title", _looks_like_page_title("VK | VK", "VK"))
check("platform echo", _looks_like_page_title("Patreon", "Patreon"))
check("real name kept", not _looks_like_page_title("Alex Rivera", "GitHub"))
check("handle echo", _is_handle_echo("riverdale", {"riverdale"}))
check("doubled handle", _is_handle_echo("Riverdale Riverdale", {"riverdale"}))
check("mixed case handle", _is_handle_echo("RiVerDaLe", {"riverdale"}))
check("email local part", _is_handle_echo("jdoe", {"jdoe@example.com"}))
check("real name is not an echo", not _is_handle_echo("Alex Rivera", {"riverdale"}))
# A name-derived email corroborates the name; it must not delete it.
check("name matching an email local part survives",
      not _is_handle_echo("Alex Rivera", {"riverdale"}, {"alex.rivera"}))
check("single-token echo of an email local is still filtered",
      _is_handle_echo("jdoe", set(), {"jdoe"}))

print("\nALL CHECKS PASS")


# --- attribution bands must agree with the persona labels ------------------
from omnisint.models import Account

print("\nattribution bands")
for score, expected in ((0.95, "same person"), (0.75, "same person"),
                        (0.5, "unknown"), (0.45, "unknown"),
                        (0.44, "likely different person"), (0.2, "likely different person")):
    a = Account(platform="X", url=None, identifier="u", attribution=score)
    check(f"{score:.2f} -> {expected}", a.attribution_level == expected)

# The score used for "unresolved" must land in the neutral band, or an
# unresolved tie would be reported as a positive exclusion.
a = Account(platform="X", url=None, identifier="u", attribution=0.5)
check("unresolved reads as unknown", a.attribution_level == "unknown")
print("\nALL CHECKS PASS")


print("\nmetadata key canonicalisation")
from omnisint.correlate import canonical_key, merge_evidence
from omnisint.models import Evidence, Profile, Status

for raw, want in (("follower_count", "followers"), ("name", "fullname"),
                  ("Display_Name", "fullname"), ("is_verified", "verified"),
                  ("id", "uid"), ("company", "company")):
    check(f"{raw} -> {want}", canonical_key(raw) == want)

# Agreeing tools collapse to one field; disagreeing tools keep both.
pr = Profile()
merge_evidence(pr, "u", [
    Evidence("maigret", "GitHub", "https://github.com/u", Status.FOUND, 0.7,
             {"fullname": "A Person", "follower_count": "10"}),
    Evidence("user-scanner", "Github", "https://github.com/u", Status.FOUND, 0.68,
             {"name": "A Person", "followers": "10", "company": "Acme"}),
])
acct = list(pr.accounts.values())[0]
check("one account after merge", len(pr.accounts) == 1)
check("no duplicate name field", "name" not in acct.metadata)
check("no duplicate follower field", "follower_count" not in acct.metadata)
check("agreeing values collapse", acct.metadata["followers"] == "10")
check("unique field kept", acct.metadata["company"] == "Acme")

pr2 = Profile()
merge_evidence(pr2, "u", [
    Evidence("maigret", "X", "https://x.com/u", Status.FOUND, 0.7, {"fullname": "A"}),
    Evidence("sherlock", "X", "https://x.com/u", Status.FOUND, 0.45, {"name": "B"}),
])
a2 = list(pr2.accounts.values())[0]
check("conflicting values both kept",
      a2.metadata["fullname"] == "A" and a2.metadata["fullname[sherlock]"] == "B")

print("\nALL CHECKS PASS")


# --- input splitting -------------------------------------------------------
print("\ninput splitting")
from omnisint.console import Console as _Con

for line, want in [
    ("alex rivera, jdoe, a@b.com",
     ["alex rivera", "jdoe", "a@b.com"]),
    ("jdoe jdoe@example.com", ["jdoe", "jdoe@example.com"]),
    ("alex rivera", ["alex rivera"]),
    ("Mary-Jane O'Brien", ["Mary-Jane O'Brien"]),
    ('"alex rivera" jdoe', ["alex rivera", "jdoe"]),
    (" a , b ,, c ", ["a", "b", "c"]),
    ("user1 user2 user3", ["user1", "user2", "user3"]),
]:
    got = _Con.split_input(line)
    check(f"{line!r} -> {len(want)} part(s)", got == want)

# The regression that started this: a 4-word name plus an email.
check("comma keeps multi-word names intact",
      _Con.split_input("alex riveria, field trip, a@b.com")
      == ["alex riveria", "field trip", "a@b.com"])

# --- semicolon splits primary from secondary -------------------------------
print("\nsemicolon primary/secondary split")
for line, want_p, want_s in [
    ("Alex Rivera, the man zooper; youtube, field trip",
     ["Alex Rivera", "the man zooper"], ["youtube", "field trip"]),
    ("jdoe; acme corp", ["jdoe"], ["acme corp"]),
    ("alex rivera, mjs@x.com; MIT; Portland",
     ["alex rivera", "mjs@x.com"], ["MIT", "Portland"]),
    ("no semicolon, jdoe", ["no semicolon", "jdoe"], []),
]:
    got_p, got_s = _Con.parse_line(line)
    check(f"{line[:38]!r}…", (got_p, got_s) == (want_p, want_s))

# --- flags are recognised anywhere on an input line ------------------------
print("\ninline flags")
for line, want_flags, want_unknown, want_primary, want_secondary in [
    ("alex@example.com -v", ["verbose"], [], ["alex@example.com"], []),
    ("jdoe -q", ["quick"], [], ["jdoe"], []),
    ("alex rivera, jdoe -d; acme corp", ["deep"], [],
     ["alex rivera", "jdoe"], ["acme corp"]),
    ("jdoe --pivot 2 --case OPS-9", ["pivot", "case"], [], ["jdoe"], []),
    ("jdoe --top-sites=80", ["top-sites"], [], ["jdoe"], []),
    ("jdoe -x", [], ["-x"], ["jdoe"], []),
    ("+14155550100 -v", ["verbose"], [], ["+14155550100"], []),
    ("jdoe", [], [], ["jdoe"], []),
]:
    clean, flags, unknown = _Con.extract_flags(line)
    pri, sec = _Con.parse_line(clean)
    check(f"{line!r}", ([f[0] for f in flags], unknown, pri, sec)
          == (want_flags, want_unknown, want_primary, want_secondary))

# A flag must never be mistaken for something to search for.
_, _, unk = _Con.extract_flags("jdoe -v")
check("a flag is never classified as a username",
      "-v" not in _Con.parse_line(_Con.extract_flags("jdoe -v")[0])[0])
# Separators glued to a flag must survive, or the secondary half is lost.
check("separator attached to a flag survives",
      _Con.parse_line(_Con.extract_flags("jdoe -q; work")[0]) == (["jdoe"], ["work"]))
check("separator attached to a flag value survives",
      _Con.parse_line(_Con.extract_flags("jdoe --pivot 2, mjs")[0])
      == (["jdoe", "mjs"], []))

# --- every backend documents how to install it -----------------------------
print("\nbackend install metadata")
from omnisint.registry import adapter_status as _status
for _row in _status():
    check(f"{_row['name']} has an install command", bool(_row["install"]))
check("sherlock points at the right PyPI package",
      any(r["name"] == "sherlock" and r["install"] == "pip install sherlock-project"
          for r in _status()))
check("credentialed backends say what else is needed",
      all(r["install_note"] for r in _status()
          if r["name"] in ("toutatis", "hibp", "darkweb")))

# --- dotted handles are not domains ---------------------------------------
print("\ndomain vs dotted handle")
for value, want in [("alex.rivera", "username"), ("john.doe", "username"),
                    ("example.com", "domain"), ("sub.example.co.uk", "domain"),
                    ("foo.website", "domain"), ("x.tv", "domain")]:
    check(f"{value} -> {want}", detect_type(value).value == want)

# --- secondary-term corroboration -----------------------------------------
print("\nsecondary terms")
from omnisint.correlate import (_term_matches, apply_corroboration,
                                   cluster_personas, harvest_identity,
                                   score_accounts)
from omnisint.models import Evidence, Identifier, IdType, Profile, Status

for term, hay, want in [("Acme Corp", "Engineer at Acme Corp", True),
                        ("acme", "I work at ACME!", True),
                        ("New York", "new and york apart", False),
                        ("MIT", "MIT alum", True),
                        ("MIT", "transMITter", False)]:
    check(f"{term!r} in {hay!r} -> {want}", _term_matches(term, hay) == want)


def _fixture(secondary=None, seeds=None):
    pr = Profile(seeds=seeds or [Identifier.parse("jdoe")], secondary=secondary or [])
    merge_evidence(pr, "jdoe", [
        Evidence("maigret", "GitHub", "https://github.com/jdoe", Status.FOUND, 0.7,
                 {"fullname": "Alice Smith", "company": "Acme Corp"}),
        Evidence("maigret", "Instagram", "https://instagram.com/jdoe", Status.FOUND,
                 0.7, {"fullname": "Bob Jones"}),
        Evidence("maigret", "Medium", "https://medium.com/@jdoe", Status.FOUND, 0.7,
                 {"fullname": "Bob Jones"}),
    ])
    score_accounts(pr); harvest_identity(pr); apply_corroboration(pr)
    cluster_personas(pr)
    return [p["name"] for p in pr.personas if p["primary"]], pr


check("no hints: most-corroborated name wins", _fixture()[0] == ["Bob Jones"])
check("secondary term outranks platform count",
      _fixture(secondary=["Acme Corp"])[0] == ["Alice Smith"])
check("supplied name anchors identity",
      _fixture(seeds=[Identifier.parse("jdoe"),
                      Identifier("Alice Smith", IdType.NAME)])[0] == ["Alice Smith"])
check("secondary term outranks a supplied name",
      _fixture(secondary=["Acme Corp"],
               seeds=[Identifier.parse("jdoe"),
                      Identifier("Bob Jones", IdType.NAME)])[0] == ["Alice Smith"])

_, pr = _fixture(secondary=["Acme Corp"])
gh = [a for a in pr.accounts.values() if a.platform == "GitHub"][0]
check("corroborated account reads as same person",
      gh.attribution >= 0.88 and gh.attribution_level == "same person")
check("corroboration is recorded on the account", gh.corroborated == ["Acme Corp"])

# --- viewer renders every section -----------------------------------------
print("\nviewer")
from rich.console import Console as _RC
from omnisint.viewer import _ESCAPE_MAP, DOWN, LEFT, RIGHT, UP, Viewer

_, pr = _fixture(secondary=["Acme Corp"])
import io as _io
v = Viewer(pr, _RC(width=100, file=_io.StringIO()))
check("arrow keys map correctly",
      (_ESCAPE_MAP["A"], _ESCAPE_MAP["B"], _ESCAPE_MAP["C"], _ESCAPE_MAP["D"])
      == (UP, DOWN, RIGHT, LEFT))

from omnisint.viewer import _LETTER_KEYS
check("ijkl navigates",
      (_LETTER_KEYS["i"], _LETTER_KEYS["k"], _LETTER_KEYS["j"], _LETTER_KEYS["l"])
      == (UP, DOWN, LEFT, RIGHT))
check("wasd also navigates",
      (_LETTER_KEYS["w"], _LETTER_KEYS["s"], _LETTER_KEYS["a"], _LETTER_KEYS["d"])
      == (UP, DOWN, LEFT, RIGHT))
check("letter keys are case-insensitive",
      _LETTER_KEYS["L"] == RIGHT and _LETTER_KEYS["I"] == UP)
# Navigation keys must not collide with the command keys.
check("nav keys do not shadow quit/export",
      not ({"q", "Q", "e", "E"} & set(_LETTER_KEYS)))

# The screen clear must reach stdout directly: rich reads square brackets as
# markup and silently swallows an ANSI sequence passed to console.print.
import io as _io2
import contextlib as _ctx
_cap = _io2.StringIO()
with _ctx.redirect_stdout(_cap):
    Viewer._clear()
check("screen clear emits raw ANSI to stdout",
      _cap.getvalue() == "\x1b[H\x1b[2J")
check("every section renders non-empty",
      all(any(l.strip() for l in v._lines(i)) for i in range(len(v.sections))))
v.index, v.offset = 1, 10_000
v._draw(10)
check("scroll offset is clamped", v.offset >= 0)

# --- opt-in adapters stay out of the default set --------------------------
print("\nadapter gating")
from omnisint.registry import ALL_ADAPTERS, available_adapters

_optin = {c.name for c in ALL_ADAPTERS if c.opt_in}
check("darkweb is opt-in", "darkweb" in _optin)
check("opt-in excluded by default",
      not ({c.name for c in available_adapters()} & _optin))
check("opt-in included when named",
      "darkweb" in {c.name for c in available_adapters(only={"darkweb"})}
      or not any(c.name == "darkweb" and c.available() for c in ALL_ADAPTERS))
check("phone type has an adapter",
      any(IdType.PHONE in c.accepts for c in available_adapters()))

print("\nALL CHECKS PASS")
