"""Fuse per-tool evidence into a single profile.

Two problems get solved here:

1. **Identity of accounts.** Sherlock's "GitHub", Maigret's "GitHub" and
   user-scanner's "Github" are the same account. We key on a normalised
   platform name and, where available, the canonical profile URL.

2. **Confidence.** Independent tools agreeing is real evidence; one tool's
   status-code guess is not. We combine per-source weights with a noisy-OR,
   which rewards corroboration without ever reaching certainty.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .models import Account, Evidence, IdType, Profile, Status

_IDENTITY_FIELDS = {"fullname", "full_name", "name", "displayname"}
_LOCATION_FIELDS = {"location", "city", "country"}
_BIO_FIELDS = {"bio", "about", "description", "status"}

# Different tools name the same field differently. Folding them here stops
# the dump showing "followers: 317788" next to "follower_count: 317788".
_METADATA_ALIASES = {
    "name": "fullname", "full_name": "fullname", "displayname": "fullname",
    "display_name": "fullname",
    "follower_count": "followers", "followers_count": "followers",
    "following_count": "following", "followings": "following",
    "public_repos_count": "public_repos", "public_gists_count": "public_gists",
    "id": "uid", "user_id": "uid", "userid": "uid",
    "is_verified": "verified", "is_private": "private",
    "about": "bio", "description": "bio", "aboutme": "bio",
    "joined": "created_at", "registration_date": "created_at",
    "date_joined": "created_at", "city": "location", "country": "location",
    "image": "avatar", "avatar_url": "avatar", "profile_pic": "avatar",
}


def canonical_key(key: str) -> str:
    k = key.strip().lower().replace(" ", "_")
    return _METADATA_ALIASES.get(k, k)


_PLATFORM_ALIASES = {
    "githubgist": "github",
    "twitterx": "twitter",
    "x": "twitter",
    "xtwitter": "twitter",
}


def normalize_platform(name: str) -> str:
    """Collapse cosmetic naming differences between tools."""
    base = name.strip().lower()
    # Tools annotate derived/renamed sites: "GitHubGist [GitHub]", "X (twitter)".
    base = re.sub(r"\s*[\[(].*?[\])]\s*", "", base)
    base = re.sub(r"[^a-z0-9]", "", base)
    return _PLATFORM_ALIASES.get(base, base)


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    host = (parsed.netloc or "").lower().removeprefix("www.")
    path = (parsed.path or "").rstrip("/")
    if not host:
        return url
    return f"{host}{path}".lower()


def _account_key(platform: str, url: str | None) -> str:
    canon = canonical_url(url)
    # Prefer the URL: it distinguishes two accounts on the same platform,
    # which matters once pivoting brings in a second username.
    return canon or normalize_platform(platform)


def combine(weights: list[float]) -> float:
    """Combine several sources' confidence into one score.

    A plain noisy-OR would treat the tools as independent, which they are
    not: most of them decide "exists" from an HTTP status code, so they tend
    to share their false positives. We therefore discount each additional
    source geometrically — agreement still helps, but three tools guessing
    the same way never becomes certainty.
    """
    product = 1.0
    for i, w in enumerate(sorted(weights, reverse=True)):
        effective = max(0.0, min(w, 0.95)) * (0.55 ** i)
        product *= (1.0 - effective)
    return 1.0 - product


def merge_evidence(profile: Profile, identifier: str, evidence: list[Evidence]) -> None:
    for ev in evidence:
        if ev.status is not Status.FOUND:
            # A site we could not get a verdict on is a hole in coverage, not
            # a negative result. Aggregate by reason so 116 rate-limited
            # probes read as one honest sentence instead of 116 lines.
            if ev.status is Status.INCONCLUSIVE:
                reason = (ev.note or "no verdict").split("(")[0].strip()[:80]
                profile.gaps.setdefault(ev.source, {})
                profile.gaps[ev.source][reason] = (
                    profile.gaps[ev.source].get(reason, 0) + 1
                )
            continue

        key = _account_key(ev.platform, ev.url)
        acct = profile.accounts.get(key)
        if acct is None:
            acct = Account(
                platform=ev.platform.split("[")[0].strip(),
                url=ev.url,
                identifier=identifier,
                category=ev.note if ev.note and " " not in (ev.note or "") else None,
            )
            profile.accounts[key] = acct

        acct.url = acct.url or ev.url
        acct.sources.add(ev.source)
        acct.evidence.append(ev)

        for k, v in (ev.metadata or {}).items():
            if v in (None, "", []):
                continue
            key = canonical_key(k)
            if key == "avatar":
                acct.avatar = acct.avatar or str(v)
            existing = acct.metadata.get(key)
            if existing is None:
                acct.metadata[key] = v
            elif str(existing) != str(v):
                # Two tools disagree about the same field. Keep both rather
                # than silently picking one — the conflict is information.
                acct.metadata[key] = existing
                acct.metadata.setdefault(f"{key}[{ev.source}]", v)


def score_accounts(profile: Profile) -> None:
    """Score existence only. Attribution is decided by cluster_personas."""
    for acct in profile.accounts.values():
        weights = [e.weight for e in acct.evidence if e.status is Status.FOUND]
        score = combine(weights)
        if acct.metadata:
            # Parsed profile fields prove something is actually rendered
            # there, which a bare status code does not.
            score = min(0.97, score + 0.06)
        acct.confidence = round(min(score, 0.97), 3)


def harvest_identity(profile: Profile) -> None:
    """Roll per-account metadata up into person-level attributes.

    Uses the same noise filter as persona clustering: a scraped page title
    or the handle echoed back is not a name, and listing it as one makes the
    summary look like corroborated identity data when it is not.
    """
    # A NAME the operator supplied must NOT go in here: an account whose name
    # matches it is the signal we are looking for, and treating it as "the
    # identifier echoed back" would delete the evidence.
    _all = list(profile.seeds) + list(profile.identifiers.values())
    handles = {i.value for i in _all
               if i.type not in (IdType.NAME, IdType.EMAIL)}
    email_locals = {i.value.split("@")[0] for i in _all if i.type is IdType.EMAIL}
    for acct in profile.accounts.values():
        if acct.confidence < 0.35:
            continue
        label = acct.platform
        for k, v in acct.metadata.items():
            key = k.lower()
            text = str(v).strip()
            if not text or len(text) > 400:
                continue
            if key in _IDENTITY_FIELDS:
                if (_norm_name(text) in _NOISE_NAMES
                        or len(_norm_name(text)) < 3
                        or _is_handle_echo(text, handles, email_locals)
                        or _looks_like_page_title(text, acct.platform)):
                    continue
                profile.names.setdefault(text, set()).add(label)
            elif key in _LOCATION_FIELDS:
                profile.locations.setdefault(text, set()).add(label)
            elif key in _BIO_FIELDS:
                profile.bios.setdefault(text, set()).add(label)
        if acct.avatar:
            profile.avatars.setdefault(acct.avatar, set()).add(label)


def corroborated_names(profile: Profile) -> list[tuple[str, list[str]]]:
    """Names seen on more than one platform, most-corroborated first."""
    return sorted(
        ((n, sorted(s)) for n, s in profile.names.items()),
        key=lambda item: (-len(item[1]), item[0].lower()),
    )


# --------------------------------------------------------------------------
# Persona disambiguation
# --------------------------------------------------------------------------
# The hardest problem in username OSINT is that a username is not a person.
# `riverdale` on GitHub may be your subject while `riverdale` on Instagram
# is an unrelated person who happened to like the handle. Every tool in this stack answers
# "does this handle exist here?" and none of them answer "is it your
# subject?". We answer the second question separately, and we never let a
# high existence score masquerade as an identification.

_NOISE_NAMES = {
    "none", "null", "user", "unknown", "private", "deleted", "anonymous",
    "n/a", "-", "profile", "home", "vk", "patreon",
}


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _is_handle_echo(name: str, handles: set[str],
                    email_locals: set[str] | None = None) -> bool:
    """True when a 'name' is just an identifier repeated back at us.

    A scraped name field that only echoes the handle carries no identity
    signal. But an email local part that matches a real name is the
    opposite — `alex.rivera@` alongside "Alex Rivera" is corroboration, not
    noise. So multi-word names are compared against handles only; email
    local parts are used only to filter single-token echoes.
    """
    flat = re.sub(r"[^a-z0-9]", "", name.lower())
    if not flat:
        return True

    tokens = {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}
    candidates = set(handles)
    if len(tokens) < 2:
        candidates |= set(email_locals or ())

    for ident in candidates:
        base = re.sub(r"[^a-z0-9]", "", ident.lower().split("@")[0])
        if not base:
            continue
        if flat == base or flat == base * 2 or flat.replace(base, "", 1) == base:
            return True
    return False


def _looks_like_page_title(raw: str, platform: str) -> bool:
    """Scrapers sometimes hand back the page <title> instead of a name."""
    if "|" in raw or "·" in raw or " - " in raw:
        return True
    flat = _norm_name(raw).replace(" ", "")
    return flat == _norm_name(platform).replace(" ", "")


def cluster_personas(profile: Profile) -> None:
    """Split accounts into distinct people who share the identifier."""
    # A NAME the operator supplied must NOT go in here: an account whose name
    # matches it is the signal we are looking for, and treating it as "the
    # identifier echoed back" would delete the evidence.
    _all = list(profile.seeds) + list(profile.identifiers.values())
    handles = {i.value for i in _all
               if i.type not in (IdType.NAME, IdType.EMAIL)}
    email_locals = {i.value.split("@")[0] for i in _all if i.type is IdType.EMAIL}

    # Gather the real names each account exposes.
    named: dict[str, list] = {}   # normalised name -> [Account, …]
    display: dict[str, str] = {}
    for acct in profile.accounts.values():
        for k, v in acct.metadata.items():
            if k.lower() not in _IDENTITY_FIELDS:
                continue
            raw = str(v).strip()
            norm = _norm_name(raw)
            if (not norm or norm in _NOISE_NAMES or len(norm) < 3
                    or _is_handle_echo(raw, handles, email_locals)
                    or _looks_like_page_title(raw, acct.platform)):
                continue
            named.setdefault(norm, []).append(acct)
            display.setdefault(norm, raw)
            break

    if not named:
        # Nothing to disambiguate: every account stays "unknown" attribution.
        for acct in profile.accounts.values():
            acct.attribution = 0.5
        return

    # The primary persona is the name corroborated across the most platforms;
    # ties break toward the one seen on higher-confidence accounts.
    def rank(item):
        norm, accts = item
        return (len({a.platform.lower() for a in accts}),
                sum(a.confidence for a in accts))

    ordered = sorted(named.items(), key=rank, reverse=True)

    # Pick the primary identity from the strongest evidence available, in
    # descending order of trustworthiness:
    #   1. an account matched a secondary term you supplied (independent fact)
    #   2. an account's name matches a name you supplied
    #   3. one name is corroborated across more platforms than any other
    # If none of those hold, we decline to pick one rather than guessing.
    from .names import similarity as _name_similarity

    primary_norm = None
    anchor_reason = None

    corroborated_norms = {
        norm for norm, accts in named.items() if any(a.corroborated for a in accts)
    }
    if corroborated_norms:
        primary_norm = max(
            corroborated_norms,
            key=lambda n: sum(len(a.corroborated) for a in named[n]))
        anchor_reason = (
            f"its accounts matched the secondary term(s) you supplied")

    if primary_norm is None:
        known = [s.value for s in profile.seeds if s.type is IdType.NAME]
        if known:
            best_score, best_norm = max(
                (max(_name_similarity(k, display[norm]) for k in known), norm)
                for norm, _ in ordered)
            if best_score >= 0.5:
                primary_norm = best_norm
                anchor_reason = "it matches the name you supplied"

    if primary_norm is None:
        top = len({a.platform.lower() for a in ordered[0][1]})
        runner_up = (len({a.platform.lower() for a in ordered[1][1]})
                     if len(ordered) > 1 else 0)
        if top > runner_up:
            primary_norm = ordered[0][0]
            anchor_reason = "it is corroborated on more platforms than any other"

    if primary_norm is not None:
        ordered.sort(key=lambda kv: kv[0] != primary_norm)
        profile.warnings.append(
            f"identity: primary set to '{display[primary_norm]}' because "
            f"{anchor_reason}.")

    for norm, accts in ordered:
        is_primary = primary_norm is not None and norm == primary_norm
        platforms = sorted({a.platform for a in accts})
        if primary_norm is None:
            note = ("competing identity — no name is better corroborated than "
                    "the others, so attribution is unresolved")
        elif is_primary:
            note = "best-corroborated identity for this handle"
        else:
            note = ("different name on the same handle — probably an "
                    "unrelated person, verify before linking")
        profile.personas.append({
            "name": display[norm],
            "platforms": platforms,
            "account_count": len(accts),
            "primary": is_primary,
            "note": note,
        })
        for acct in accts:
            acct.persona = display[norm]
            if acct.corroborated:
                # A secondary-term match is direct evidence about this
                # account; persona bookkeeping must not talk it back down.
                continue
            if primary_norm is None:
                # Genuinely unknown, so it must land in the neutral band —
                # not below it, which would read as "different person" and
                # assert more than the evidence supports.
                acct.attribution = 0.5
                acct.persona_note = "competing identity, unresolved"
            elif is_primary:
                # Corroboration across platforms strengthens attribution.
                acct.attribution = min(0.95, 0.55 + 0.1 * len(platforms))
                acct.persona_note = "matches primary identity"
            else:
                acct.attribution = 0.2
                acct.persona_note = (
                    f"name '{display[norm]}' conflicts with primary identity "
                    f"'{display[primary_norm]}'"
                )

    for acct in profile.accounts.values():
        if acct.persona is None and not acct.corroborated:
            # Exists, but exposes nothing that ties it to anyone.
            acct.attribution = 0.5
            acct.persona_note = "no identifying data — attribution unresolved"

    if primary_norm is None and len(profile.personas) > 1:
        profile.warnings.insert(0, (
            f"identity: {len(profile.personas)} different names appear under "
            "this handle and none is better corroborated than the others. No "
            "primary identity was assigned. Widen the scan (--deep, more "
            "tools) or supply a second identifier before drawing conclusions."
        ))
    elif len(profile.personas) > 1:
        others = len(profile.personas) - 1
        profile.warnings.insert(0, (
            f"identity: {len(profile.personas)} distinct names appear under this "
            f"handle. {others} of them probably belong to different people. "
            "Existence and attribution are scored separately below — do not "
            "read a high confidence score as an identification."
        ))


def summarize_gaps(profile: Profile) -> None:
    """Turn per-site coverage holes into a few readable sentences.

    A tool that answered "don't know" for every site has told you nothing.
    Left unsaid, that silence reads as "clean" — which is the most dangerous
    way for an OSINT report to be wrong.
    """
    for run in profile.runs:
        reasons = profile.gaps.get(run.adapter)
        if not reasons:
            continue
        total = sum(reasons.values())
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:3]
        detail = "; ".join(f"{reason} ×{count}" for reason, count in top)
        if run.found == 0:
            profile.warnings.insert(0, (
                f"{run.adapter}: NO USABLE SIGNAL — {total} site(s) returned no "
                f"verdict and nothing was found ({detail}). Treat this tool as "
                "having not run: absence here is not evidence of absence."
            ))
        else:
            profile.warnings.append(
                f"{run.adapter}: {total} site(s) gave no verdict ({detail}). "
                "Those sites are unchecked, not clear."
            )


# --------------------------------------------------------------------------
# Secondary-term corroboration
# --------------------------------------------------------------------------
# Secondary terms are things you know *about* the subject rather than
# identifiers for them: an employer, a school, a city, a band. Searching
# "Acme Corp" across 3000 username databases is worthless, but finding it in
# the bio of an account already surfaced by a username is decisive. So these
# are never queried on their own — they are only ever matched against data
# the primary identifiers brought back.

def _term_matches(term: str, haystack: str) -> bool:
    t = re.sub(r"[^a-z0-9 ]", " ", term.lower()).strip()
    h = re.sub(r"[^a-z0-9 ]", " ", haystack.lower())
    h = re.sub(r"\s+", " ", h)
    if not t:
        return False
    if " " in t:
        # Multi-word terms must appear as a phrase; matching the words
        # separately would let "New York" hit on "new" plus "york" anywhere.
        return t in h
    return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", h) is not None


def apply_corroboration(profile: Profile) -> None:
    """Match secondary terms against everything the primaries returned."""
    terms = [t.strip() for t in profile.secondary if t.strip()]
    if not terms:
        return

    hits = 0
    for acct in profile.accounts.values():
        blob = " ".join(str(v) for k, v in acct.metadata.items() if k != "avatar")
        blob = f"{blob} {acct.platform} {acct.url or ''}"
        matched = [t for t in terms if _term_matches(t, blob)]
        if not matched:
            continue
        acct.corroborated = matched
        hits += 1
        # An independent fact about the subject turning up in the account's
        # own data is the strongest attribution signal short of a match on a
        # name you supplied.
        acct.attribution = max(acct.attribution, 0.88)
        acct.persona_note = (
            f"corroborated by secondary term(s): {', '.join(matched)}")

    if hits:
        profile.warnings.append(
            f"identity: {hits} account(s) matched the secondary term(s) you "
            f"supplied ({', '.join(terms)}). Those are the strongest links to "
            "your subject in this report."
        )
    else:
        profile.warnings.append(
            f"identity: none of your secondary terms ({', '.join(terms)}) "
            "appeared in any account's data. That is not evidence against a "
            "match — most platforms expose no bio or employer field at all."
        )
