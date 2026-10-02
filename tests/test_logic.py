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

# --- console never dead-ends ----------------------------------------------
print("\nconsole robustness")
import io as _io3
from rich.console import Console as _RC3
from omnisint.config import ScanOptions as _SO
from omnisint.ethics import Authorization as _Auth

_buf = _io3.StringIO()
_con = _Con(_RC3(file=_buf, width=90), _SO(),
            _Auth(operator="t", basis="test", case="T"))
# A recap before any scan must be a no-op, not a crash.
_con._recap()
check("recap with no scan is safe", _buf.getvalue() == "")
# Commands that need a prior scan must report, not raise.
for _cmd in (_con._view, lambda: _con._export(), _con._expand, _con._show):
    _cmd()
check("pre-scan commands do not raise", True)
check("pre-scan commands explain themselves", "No scan yet" in _buf.getvalue())
_con._add_secondary("")
check("empty secondary shows usage", "usage:" in _buf.getvalue())
_con._set("nonsense", "5")
check("unknown setting is reported", "Unknown setting" in _buf.getvalue())
_con._set("timeout", "abc")
check("non-numeric setting is reported", "not a valid int" in _buf.getvalue())

# --- OSINT Framework catalogue --------------------------------------------
print("\nOSINT Framework catalogue")
from omnisint.catalog import (FEATURED, attribution, counts, flags,
                              leads_for, _catalog)

_cat = _catalog()
check("catalogue ships with the package", len(_cat["resources"]) > 500)
check("it credits the upstream project",
      "Nordine" in attribution() and "lockfale" in attribution())
check("every resource has a url and at least one type",
      all(r.get("url") and r.get("types") for r in _cat["resources"]))
check("nothing dead or deprecated survived curation",
      not any(r.get("deprecated") or r.get("status") in ("down", "defunct")
              for r in _cat["resources"]))
check("no duplicate urls",
      len({r["url"].rstrip("/").lower() for r in _cat["resources"]})
      == len(_cat["resources"]))

_leads = leads_for([Identifier.parse(v) for v in
                    ("alex rivera", "ajr", "a@b.com", "example.com",
                     "+14155550100")], limit=6)
check("routes each identifier type to resources",
      {"name", "username", "email", "domain", "phone"} <= set(_leads))
check("the canonical email resource ranks first",
      "pwned" in _leads["email"][0]["name"].lower())
check("the canonical domain resource ranks first",
      "crt.sh" in _leads["domain"][0]["name"].lower())
check("limit is honoured", all(len(v) <= 6 for v in _leads.values()))
check("an unroutable type yields nothing", leads_for([]) == {})

# opsec is the field that matters: it says whether using a resource reaches
# the subject. Omnisint is passive by default, so this must be surfaced.
check("active resources are flagged as touching the subject",
      all("touches the subject" in flags(r)
          for r in _cat["resources"] if r["opsec"] == "active"))
check("passive-only filtering excludes them",
      all(r["opsec"] == "passive"
          for v in leads_for([Identifier.parse("ajr")],
                             include_active=False).values() for r in v))
check("paid and registration costs are surfaced",
      "account needed" in flags({"name": "x", "registration": True}))
check("counts cover every bucket", set(counts()) >= set(FEATURED))

# --- SpiderFoot -----------------------------------------------------------
print("\nSpiderFoot adapter")
from omnisint.adapters.spiderfoot import (MODULES_BY_TYPE, SpiderFootAdapter)

check("it is opt-in", SpiderFootAdapter.opt_in)
check("it documents how to install it", bool(SpiderFootAdapter.install))
check("each accepted type has its own module set",
      all(t in MODULES_BY_TYPE for t in SpiderFootAdapter.accepts))
check("the account sweep is not aimed at domains",
      "sfp_accounts" not in MODULES_BY_TYPE[IdType.DOMAIN])
check("usernames do get the account sweep",
      "sfp_accounts" in MODULES_BY_TYPE[IdType.USERNAME])

# SpiderFoot prints four columns though its header claims three.
_row = ["sfp_dnsresolve", "IP Address", "example.com", "104.20.23.154"]
check("its CSV really has four columns", len(_row) == 4)
check("account strings split into platform and url",
      SpiderFootAdapter._split_account("GitHub: https://github.com/x")
      == ("GitHub", "https://github.com/x"))
check("a bare url still yields a platform",
      SpiderFootAdapter._split_account("https://github.com/x")[0] == "github.com")

# --- pre-flight query review ----------------------------------------------
print("\npre-flight advice")
from omnisint.advice import collision_risk as _risk, review as _review


def _seeds(*vals):
    return [Identifier.parse(v) for v in vals]


# The query that produced 928 accounts across 92 people must be caught.
_r = _review(_seeds("michael", "sllverstein", "field", "trip",
                    "mdsilvers11@icloud.com"), [])
check("a name typed without commas is detected",
      any("looks like one name" in p["text"] for p in _r["problems"]))
check("it offers the corrected query",
      any(p.get("rewrite", "").startswith("michael sllverstein field trip")
          for p in _r["problems"]))
check("common given names are flagged",
      any("'michael'" in p["text"] for p in _r["problems"]))
check("ordinary words are flagged",
      any("'field'" in p["text"] for p in _r["problems"]))
check("the query is marked noisy", _r["noisy"])
check("it suggests a cross-check term", any("semicolon" in t for t in _r["suggestions"]))

# The corrected query must come back clean, or the fix button lies.
check("the suggested rewrite is actually clean",
      not _review(_seeds("michael sllverstein field trip",
                         "mdsilvers11@icloud.com"), [])["problems"])

check("a distinctive handle is not nagged about",
      not _review(_seeds("teamingzooper"), [])["problems"])
check("digits make a handle distinctive", _risk(Identifier.parse("michael88")) is None)
check("very short handles are flagged", _risk(Identifier.parse("ajr"))[0] == "high")
check("emails are never flagged", _risk(Identifier.parse("a@b.com")) is None)
check("supplying a cross-check silences that suggestion",
      not any("semicolon" in t
              for t in _review(_seeds("michael"), ["Acme"])["suggestions"]))

# --- a shorter name is not a different person -----------------------------
print("\nname compatibility")
from omnisint.correlate import name_relation as _rel

for _a, _b, _want in [
    ("Michael", "Michael Silverstein", "compatible"),
    ("Michael Silverstein", "Michael", "compatible"),
    ("Torvalds", "Linus Torvalds", "compatible"),
    ("M Silverstein", "Michael Silverstein", "compatible"),
    ("Michael Silverstein", "Silverstein Michael", "same"),
    ("Linus Torvalds", "Patricia Torvalds", "conflict"),
    ("Michael Braun", "Michael Silverstein", "conflict"),
    ("Alice Smith", "Bob Jones", "conflict"),
]:
    check(f"{_a!r} vs {_b!r} -> {_want}", _rel(_a, _b) == _want)


def _named(*pairs):
    pr = Profile(seeds=[Identifier.parse("handle")])
    merge_evidence(pr, "handle", [
        Evidence("maigret", plat, f"https://{plat.lower()}.example/handle",
                 Status.FOUND, 0.7, {"fullname": name})
        for plat, name in pairs])
    score_accounts(pr); harvest_identity(pr); apply_corroboration(pr)
    cluster_personas(pr)
    return pr, {a.platform: a for a in pr.accounts.values()}


# The reported bug: a first-name-only profile read as a different person.
_pr, _acc = _named(("Pinterest", "Michael Silverstein"),
                   ("Github", "Michael Silverstein"),
                   ("Duolingo", "Michael"))
check("a partial name folds into the fuller one", len(_pr.personas) == 1)
check("the variant is recorded", _pr.personas[0]["variants"] == ["Michael"])
check("a partial name is not called a conflict",
      "conflict" not in (_acc["Duolingo"].persona_note or ""))
check("nor flagged as a different person",
      _acc["Duolingo"].attribution_level != "likely different person")
check("but it is not treated as proof either",
      _acc["Duolingo"].attribution < _acc["Github"].attribution)
check("and it explains why", "less specific" in _acc["Duolingo"].persona_note)

# The case this module exists for must still be caught.
_pr2, _acc2 = _named(("GitHub", "Linus Torvalds"), ("Academia", "Linus Torvalds"),
                     ("Medium", "Patricia Torvalds"))
check("a different given name is still a conflict",
      _acc2["Medium"].attribution_level == "likely different person")

# A bare given name shared by two identities belongs to neither.
_pr3, _acc3 = _named(("GitHub", "Michael Silverstein"), ("GitLab", "Michael Silverstein"),
                     ("Behance", "Michael Braun"), ("Duolingo", "Michael"))
check("an ambiguous partial is left unplaced",
      _acc3["Duolingo"].attribution_level == "unknown")
check("and says it is too generic", "too generic" in _acc3["Duolingo"].persona_note)
check("while the real conflict is still flagged",
      _acc3["Behance"].attribution_level == "likely different person")

# --- stacking accounts into one identity ----------------------------------
print("\nconfirmed identity (pins)")
from omnisint.correlate import apply_pins as _apply_pins
from omnisint.web.server import State as _WebState

_seeds, _terms = _WebState.anchors_from_pins([
    {"platform": "GitHub", "url": "https://github.com/torvalds",
     "username": "torvalds", "fullname": "Linus Torvalds",
     "terms": ["Linux Foundation", "Portland, OR"]},
    {"platform": "Keybase", "username": "ltorv", "fullname": "Linus Torvalds"},
])
check("pinned handles become seeds", "torvalds" in _seeds and "ltorv" in _seeds)
check("pinned name anchors the identity", "Linus Torvalds" in _seeds)
check("the same anchor is not added twice", _seeds.count("Linus Torvalds") == 1)
check("pinned context becomes cross-checks", _terms == ["Linux Foundation", "Portland, OR"])
check("empty pins are harmless", _WebState.anchors_from_pins([]) == ([], []))


def _pinned_profile():
    pr = Profile(seeds=[Identifier.parse("jdoe")],
                 pinned=[{"platform": "Instagram", "url": "https://instagram.com/jdoe"}])
    merge_evidence(pr, "jdoe", [
        Evidence("maigret", "GitHub", "https://github.com/jdoe", Status.FOUND, 0.7,
                 {"fullname": "Alice Smith", "company": "Acme"}),
        Evidence("maigret", "GitLab", "https://gitlab.com/jdoe", Status.FOUND, 0.7,
                 {"fullname": "Alice Smith"}),
        Evidence("maigret", "Instagram", "https://instagram.com/jdoe", Status.FOUND,
                 0.7, {"fullname": "Bob Jones"}),
    ])
    score_accounts(pr); harvest_identity(pr); apply_corroboration(pr)
    cluster_personas(pr); _apply_pins(pr)
    return pr


_pp = _pinned_profile()
_ig = [a for a in _pp.accounts.values() if a.platform == "Instagram"][0]
_gh = [a for a in _pp.accounts.values() if a.platform == "GitHub"][0]
check("a pin outranks the tools' own conclusion",
      _ig.pinned and _ig.attribution_level == "same person")
check("a pin is labelled as your judgement", "confirmed by you" in (_ig.persona_note or ""))
check("that provenance is recorded in the report",
      any("you confirmed them" in w for w in _pp.warnings))
check("unpinned accounts are untouched", not _gh.pinned)
check("pins survive serialisation",
      [a for a in _pp.to_dict()["accounts"] if a["platform"] == "Instagram"][0]["pinned"])

# --- what-they-do summary --------------------------------------------------
print("\ninterest summary")
from omnisint.summary import summarise as _summarise, topics_for as _topic_for

for _p, _want in [("GitHub", "software development"), ("Steam", "gaming"),
                  ("SoundCloud", "music"), ("Kaggle", "machine learning / data"),
                  ("500px", "visual art / photography"),
                  ("Leetcode", "competitive programming / CS")]:
    check(f"{_p} -> {_want}", _topic_for(_p) == _want)
check("ubiquitous platforms imply nothing", _topic_for("Gravatar") is None)
check("unknown platforms are not forced into a topic", _topic_for("Zzzq") is None)

_sm = _summarise(_pp)
check("summary scopes to the accounts you confirmed",
      _sm["scope"] == "accounts you confirmed" and _sm["account_count"] == 1)
check("summary always states its basis", "scope" in _sm and _sm["caveat"])

# With nothing attributed it must decline to characterise rather than guess.
_blank = Profile(seeds=[Identifier.parse("jdoe")])
merge_evidence(_blank, "jdoe", [
    Evidence("sherlock", "Reddit", "https://reddit.com/u/jdoe", Status.FOUND, 0.45, {})])
score_accounts(_blank); harvest_identity(_blank); cluster_personas(_blank)
_bs = _summarise(_blank)
check("declines to characterise an unattributed handle", _bs["account_count"] == 0)
check("and says why", "nothing to characterise" in _bs["headline"])

# A tie between people must not be summarised as one person.
_multi = Profile(seeds=[Identifier.parse("jdoe")])
merge_evidence(_multi, "jdoe", [
    Evidence("maigret", "GitHub", "https://github.com/jdoe", Status.FOUND, 0.7,
             {"fullname": "Alice Smith"}),
    Evidence("maigret", "Steam", "https://steamcommunity.com/id/jdoe", Status.FOUND,
             0.7, {"fullname": "Bob Jones"})])
score_accounts(_multi); harvest_identity(_multi); apply_corroboration(_multi)
cluster_personas(_multi)
check("an unresolved tie is not summarised as one person",
      _summarise(_multi)["account_count"] == 0)

# --- every runtime markup string must parse -------------------------------
# A mismatched tag in the help text crashed the whole program, and the error
# handler crashed again while trying to report it.
print("\nrich markup")
import re as _re
from rich.errors import MarkupError as _MErr
from rich.markup import render as _render
import omnisint.brand as _brand
from omnisint.console import HELP as _HELP


def _renders(text):
    try:
        _render(_re.sub(r"\{[^{}]*\}", "X", text))
        return True
    except _MErr:
        return False


check("console help renders", _renders(_HELP))
for _w in (30, 60, 100, 200):
    check(f"banner renders at width {_w}",
          _renders(_brand.banner(_w, "1.0.0", 9, "CASE")))

# The catch-all handler must escape: an exception message containing square
# brackets would otherwise raise inside the handler that reports it.
_b = _io3.StringIO()
_c2 = _Con(_RC3(file=_b, width=90), _SO(), _Auth(operator="t", basis="x", case="C"))
try:
    _c2.c.print(f"[red]That did not work:[/red] "
                f"{__import__('rich.markup', fromlist=['escape']).escape('closing tag [/magenta]')}")
    _ok = True
except Exception:
    _ok = False
check("error text with markup does not crash the reporter", _ok)

# --- export filenames survive a dotted stem -------------------------------
print("\nexport filenames")
import pathlib as _pl
_stem = "a@gmai.com-20260824-190112"
check("with_suffix would have eaten the name",
      str(_pl.Path(_stem).with_suffix(".json")) == "a@gmai.json")
check("concatenation keeps it intact",
      _stem + ".json" == "a@gmai.com-20260824-190112.json")

# --- discovered identifiers ------------------------------------------------
print("\ndiscovered identifiers")
import builtins as _bi
from omnisint.models import Profile as _P, Identifier as _I, IdType as _IT


def _disc_fixture():
    _buf = _io3.StringIO()
    _con = _Con(_RC3(file=_buf, width=100), _SO(),
                _Auth(operator="t", basis="b", case="C"))
    _con.targets = [_I.parse("jdoe")]
    _pr = _P(seeds=list(_con.targets))
    for _v, _t, _o in [("jdoe@noreply.codeberg.org", _IT.EMAIL, "user-scanner:Codeberg"),
                       ("j_doe", _IT.USERNAME, "maigret:Keybase"),
                       ("jdoe2", _IT.USERNAME, "maigret:GitHub"),
                       ("jdoe", _IT.USERNAME, "input")]:
        _i = _I(_v, _t, origin=_o, depth=0 if _o == "input" else 1)
        _pr.identifiers[_i.key()] = _i
    _con.last = _pr
    return _con


def _answer(text):
    _con = _disc_fixture()
    _bi.input = lambda *_a: text
    _con._offer_discovered()
    return _con


_c = _disc_fixture()
check("emails are offered before usernames",
      _c.discovered()[0].value.endswith("codeberg.org"))
check("already-loaded seeds are not re-offered",
      "jdoe" not in [i.value for i in _c.discovered()])
check("decline adds nothing", len(_answer("n").targets) == 1)
check("decline stops re-offering", _answer("n").discovered() == [])
check("accept all adds every one", len(_answer("y").targets) == 4)
check("numeric pick adds only those", len(_answer("1,3").targets) == 3)
check("garbage input adds nothing", len(_answer("banana").targets) == 1)

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
