"""Runtime options shared by the engine and every adapter."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScanOptions:
    #: Seconds before an individual upstream tool is killed.
    tool_timeout: int = 600
    #: Per-request timeout handed down to tools that accept one.
    request_timeout: int = 20
    #: How many adapters run at once.
    workers: int = 6
    #: Maigret/user-scanner breadth. 0 means "all sites" for maigret.
    top_sites: int = 500
    all_sites: bool = False
    #: Follow discovered emails/usernames this many hops from the seed.
    pivot_depth: int = 0
    #: Cap on how many discovered identifiers we will chase per hop.
    pivot_limit: int = 5
    #: Passive mode never triggers password-recovery flows or anything else
    #: that could send mail to, or otherwise touch, the data subject.
    passive: bool = True
    #: Skip adult-content site lists unless explicitly enabled.
    nsfw: bool = False
    proxy: str | None = None
    tor: bool = False
    delay: float = 0.0
    only: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)
    #: Minimum confidence an account needs to appear in the default report.
    min_confidence: float = 0.35
    keep_raw: bool = False
    #: Show per-site detail, tool errors and the full caveat list.
    verbose: bool = False
    #: Which depth preset produced these settings, for display only.
    preset: str = "standard"


#: Depth presets. `quick` trades coverage for a result in seconds; `deep`
#: trades your afternoon for everything the databases know.
PRESETS = {
    "quick": dict(
        top_sites=50, all_sites=False, request_timeout=8, tool_timeout=180,
        workers=8, pivot_depth=0,
    ),
    "standard": dict(
        top_sites=500, all_sites=False, request_timeout=20, tool_timeout=900,
        workers=6, pivot_depth=0,
    ),
    "deep": dict(
        top_sites=0, all_sites=True, request_timeout=30, tool_timeout=2400,
        workers=8, pivot_depth=1,
    ),
}

PRESET_BLURB = {
    "quick": "top 50 sites — the mainstream platforms, back in seconds",
    "standard": "top 500 sites per tool",
    "deep": "every site in every database, plus one pivot hop (slow)",
}


def apply_preset(opts: "ScanOptions", preset: str) -> "ScanOptions":
    """Overlay a depth preset onto an options object, in place."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}; "
                         f"choose from {', '.join(PRESETS)}")
    for key, value in PRESETS[preset].items():
        setattr(opts, key, value)
    opts.preset = preset
    return opts
