"""Core data model for Omnisint.

Everything the engine collects is normalised into these structures so that
reports, correlation and pivoting never need to know which upstream tool a
piece of evidence came from.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class IdType(str, Enum):
    USERNAME = "username"
    EMAIL = "email"
    PHONE = "phone"
    DOMAIN = "domain"
    URL = "url"
    NAME = "name"
    UNKNOWN = "unknown"


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
_PHONE_RE = re.compile(r"^\+?[0-9][0-9\-\s().]{6,}[0-9]$")
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)([a-z0-9-]+\.)+[a-z]{2,}$", re.I)
# A dotted handle like `alex.rivera` matches the domain shape, so the
# last label has to look like a real TLD before we call it a domain.
_COMMON_TLDS = {
    "com", "org", "net", "edu", "gov", "mil", "int", "io", "co", "us", "uk",
    "ca", "de", "fr", "es", "it", "nl", "se", "no", "fi", "dk", "pl", "ru",
    "jp", "cn", "kr", "in", "au", "nz", "br", "mx", "ar", "za", "ch", "at",
    "be", "cz", "gr", "pt", "ie", "il", "tr", "ua", "info", "biz", "name",
    "pro", "app", "dev", "xyz", "online", "site", "tech", "store", "blog",
    "cloud", "ai", "me", "tv", "cc", "gg", "sh", "to", "ly", "im", "fm",
    "eu", "asia", "club", "live", "news", "wiki", "space", "website", "link",
    "hu", "ro", "bg", "hr", "rs", "sk", "si", "lt", "lv", "ee", "is", "lu",
    "id", "my", "sg", "th", "vn", "ph", "hk", "tw", "pk", "bd", "ir", "sa",
    "ae", "eg", "ma", "ng", "ke", "cl", "pe", "ve", "uy", "cr", "gt", "do",
    "network", "systems", "solutions", "digital", "agency", "studio", "team",
    "email", "chat", "social", "media", "group", "world", "life", "today",
}


def _is_domain(value: str) -> bool:
    if not _DOMAIN_RE.match(value):
        return False
    # Membership only — no length fallback, because `john.doe` and
    # `alex.rivera` are handles, not hosts, and a wrong guess here
    # sends the identifier to entirely the wrong set of tools.
    return value.rsplit(".", 1)[-1].lower() in _COMMON_TLDS
_URL_RE = re.compile(r"^https?://", re.I)
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._\-]{2,64}$")


def detect_type(value: str) -> IdType:
    """Classify a raw identifier the user typed in."""
    v = value.strip()
    if not v:
        return IdType.UNKNOWN
    if _URL_RE.match(v):
        return IdType.URL
    if _EMAIL_RE.match(v):
        return IdType.EMAIL
    if _is_domain(v):
        return IdType.DOMAIN
    # Phones: strip formatting first, require enough digits.
    digits = re.sub(r"\D", "", v)
    if _PHONE_RE.match(v) and 7 <= len(digits) <= 15:
        return IdType.PHONE
    if " " in v:
        return IdType.NAME
    if _USERNAME_RE.match(v):
        return IdType.USERNAME
    return IdType.UNKNOWN


@dataclass(frozen=True)
class Identifier:
    """A single thing we can search on."""
    value: str
    type: IdType
    # How we learned about it: "input" for user-supplied, otherwise the
    # adapter + account that produced it during pivoting.
    origin: str = "input"
    depth: int = 0

    @staticmethod
    def parse(value: str, origin: str = "input", depth: int = 0) -> "Identifier":
        return Identifier(value.strip(), detect_type(value), origin, depth)

    def key(self) -> str:
        return f"{self.type.value}:{self.value.lower()}"


class Status(str, Enum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    # Distinct from NOT_FOUND on purpose: a rate limit or captcha means we
    # learned nothing, and reporting it as "not found" would be a lie.
    INCONCLUSIVE = "inconclusive"
    ERROR = "error"


@dataclass
class Evidence:
    """One tool's opinion about one account."""
    source: str          # adapter name, e.g. "maigret"
    platform: str        # e.g. "GitHub"
    url: str | None
    status: Status
    weight: float        # source reliability for this observation, 0..1
    metadata: dict[str, Any] = field(default_factory=dict)
    note: str | None = None


@dataclass
class Account:
    """A correlated account: everything all tools said about one platform."""
    platform: str
    url: str | None
    identifier: str
    category: str | None = None
    sources: set[str] = field(default_factory=set)
    evidence: list[Evidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    avatar: str | None = None
    #: P(an account with this identifier exists on this platform).
    confidence: float = 0.0
    #: P(it belongs to the *same person* as the other accounts). These are
    #: different questions and conflating them is how OSINT gets people hurt.
    attribution: float = 0.5
    persona: str | None = None
    persona_note: str | None = None
    #: Secondary terms (employer, school …) found in this account's data.
    corroborated: list[str] = field(default_factory=list)
    #: The operator asserted this account belongs to the subject. That is a
    #: human judgement, not tool evidence, and is labelled as such everywhere.
    pinned: bool = False

    @property
    def level(self) -> str:
        if self.confidence >= 0.85:
            return "confirmed"
        if self.confidence >= 0.60:
            return "probable"
        if self.confidence >= 0.35:
            return "possible"
        return "weak"

    @property
    def attribution_level(self) -> str:
        if self.attribution >= 0.75:
            return "same person"
        if self.attribution >= 0.45:
            return "unknown"
        return "likely different person"

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "url": self.url,
            "identifier": self.identifier,
            "category": self.category,
            "sources": sorted(self.sources),
            "confidence": round(self.confidence, 3),
            "level": self.level,
            "attribution": round(self.attribution, 3),
            "attribution_level": self.attribution_level,
            "persona": self.persona,
            "persona_note": self.persona_note,
            "corroborated_by": self.corroborated,
            "pinned": self.pinned,
            "avatar": self.avatar,
            "metadata": self.metadata,
            "corroboration": [
                {"source": e.source, "status": e.status.value, "note": e.note}
                for e in self.evidence
            ],
        }


@dataclass
class ToolRun:
    """Bookkeeping for one adapter execution: what ran, how it went."""
    adapter: str
    identifier: str
    ok: bool
    duration: float
    found: int = 0
    inconclusive: int = 0
    error: str | None = None
    command: str | None = None


@dataclass
class Profile:
    """The merged dossier the user actually sees."""
    seeds: list[Identifier] = field(default_factory=list)
    #: Context terms used only to confirm identity, never searched alone.
    secondary: list[str] = field(default_factory=list)
    #: Accounts the operator stacked into one identity, as {platform, url, …}.
    pinned: list[dict[str, Any]] = field(default_factory=list)
    accounts: dict[str, Account] = field(default_factory=dict)  # keyed platform|url
    identifiers: dict[str, Identifier] = field(default_factory=dict)
    names: dict[str, set[str]] = field(default_factory=dict)      # name -> sources
    locations: dict[str, set[str]] = field(default_factory=dict)
    bios: dict[str, set[str]] = field(default_factory=dict)
    avatars: dict[str, set[str]] = field(default_factory=dict)
    personas: list[dict[str, Any]] = field(default_factory=list)
    phones: dict[str, Any] = field(default_factory=dict)
    infrastructure: dict[str, Any] = field(default_factory=dict)  # dns/whois
    breaches: list[dict[str, Any]] = field(default_factory=list)
    runs: list[ToolRun] = field(default_factory=list)
    #: source -> reason -> count. Sites a tool could not get a verdict on.
    gaps: dict[str, dict[str, int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """What the attributed accounts suggest about the person."""
        from .summary import summarise
        return summarise(self)

    def sorted_accounts(self) -> list[Account]:
        return sorted(
            self.accounts.values(),
            key=lambda a: (-a.confidence, a.platform.lower()),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": [asdict(s) for s in self.seeds],
            "secondary_terms": self.secondary,
            "pinned": self.pinned,
            "identity": {
                "names": {k: sorted(v) for k, v in self.names.items()},
                "locations": {k: sorted(v) for k, v in self.locations.items()},
                "bios": {k: sorted(v) for k, v in self.bios.items()},
                "avatars": {k: sorted(v) for k, v in self.avatars.items()},
            },
            "identifiers": [
                {"value": i.value, "type": i.type.value, "origin": i.origin, "depth": i.depth}
                for i in self.identifiers.values()
            ],
            "personas": self.personas,
            "summary": self.summary(),
            "accounts": [a.to_dict() for a in self.sorted_accounts()],
            "infrastructure": self.infrastructure,
            "phones": self.phones,
            "breaches": self.breaches,
            "runs": [asdict(r) for r in self.runs],
            "coverage_gaps": self.gaps,
            "warnings": self.warnings,
        }
