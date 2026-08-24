"""Omnisint brand: wordmark, mark, palette.

The name is a portmanteau — omniscient + OSINT — so the identity leans on
the "all-seeing" reading: an eye built from the O, and a wordmark where
OMNI and SINT are weighted differently so the seam is visible.

Three sizes, chosen by terminal width, because a banner that wraps looks
broken and a broken banner undermines everything after it.
"""
from __future__ import annotations

# -- palette ---------------------------------------------------------------
# Cyan reads as instrumentation; magenta marks identity/corroboration; amber
# is caution; red is exposure. Used consistently across every surface.
CYAN = "#22d3ee"
MAGENTA = "#c084fc"
AMBER = "#fbbf24"
RED = "#f87171"
GREEN = "#34d399"
DIM = "#64748b"

TAGLINE = "every source · one profile"

# -- the mark --------------------------------------------------------------
# An eye in a ring: the O of OMNI doubling as an iris.
MARK = "◉"
MARK_LARGE = r"""
    ╭───────────╮
   ╱   ▄█████▄   ╲
  │   ███ ◉ ███   │
   ╲   ▀█████▀   ╱
    ╰───────────╯
"""

# -- wordmarks -------------------------------------------------------------
# Full block wordmark. OMNI is solid, SINT is outlined, so the join between
# the two halves of the portmanteau is legible at a glance.
FULL = r"""
 ▄██████▄  ▄▄       ▄▄ ▄▄     ▄▄ ▄▄   ▄███████ ▄▄ ▄▄     ▄▄ ██████████
 ██▀    ▀█ ███▄   ▄███ ███▄   ██ ██   ██▀      ██ ███▄   ██     ██
 ██  ◉   █ ██ ▀███▀ ██ ██ ▀█▄ ██ ██   ▀██████▄ ██ ██ ▀█▄ ██     ██
 ██▄    ▄█ ██   ▀   ██ ██   ▀███ ██        ▀██ ██ ██   ▀███     ██
 ▀██████▀  ▀▀       ▀▀ ▀▀     ▀▀ ▀▀   ███████▀ ▀▀ ▀▀     ▀▀     ▀▀
"""

# Mid-width: same letterforms, half the height.
COMPACT = r"""
 ╔═╗ ╔╦╗ ╔╗╔ ╦ ╔═╗ ╦ ╔╗╔ ╔╦╗
 ║◉║ ║║║ ║║║ ║ ╚═╗ ║ ║║║  ║
 ╚═╝ ╩ ╩ ╝╚╝ ╩ ╚═╝ ╩ ╝╚╝  ╩
"""

# Narrow terminals get the mark plus plain type.
TINY = "◉ OMNISINT"

WIDTH_FULL = 76
WIDTH_COMPACT = 34


def wordmark(width: int) -> str:
    """Pick the largest wordmark that fits without wrapping."""
    if width >= WIDTH_FULL:
        return FULL
    if width >= WIDTH_COMPACT:
        return COMPACT
    return TINY


def banner(width: int, version: str, ready: int, case: str | None) -> str:
    """Full startup banner as rich markup."""
    art = wordmark(width)
    # Gradient the wordmark line by line: cyan at the top, magenta at the
    # base, so the mark reads as one object rather than coloured text.
    ramp = [CYAN, "#5eead4", "#a5b4fc", MAGENTA, MAGENTA]
    lines = art.strip("\n").split("\n")
    painted = "\n".join(
        f"[bold {ramp[min(i, len(ramp) - 1)]}]{line}[/]"
        for i, line in enumerate(lines)
    )
    pad = "  " if width >= WIDTH_COMPACT else ""
    meta = (f"{pad}[{DIM}]v{version}[/]  [bold {GREEN}]{ready}[/][{DIM}] backends ready[/]"
            f"  [{DIM}]· case[/] [bold]{case or '—'}[/]")
    tag = f"{pad}[{MAGENTA}]{TAGLINE}[/]"
    return f"\n{painted}\n\n{tag}\n{meta}\n"


# -- HTML ------------------------------------------------------------------
def svg_logo(height: int = 34) -> str:
    """Inline SVG wordmark for the HTML report. No external assets."""
    return f"""\
<svg viewBox="0 0 420 64" height="{height}" role="img" aria-label="Omnisint"
     xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="og" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="{CYAN}"/>
      <stop offset="100%" stop-color="{MAGENTA}"/>
    </linearGradient>
  </defs>
  <circle cx="32" cy="32" r="22" fill="none" stroke="url(#og)" stroke-width="4"/>
  <ellipse cx="32" cy="32" rx="20" ry="11" fill="none"
           stroke="url(#og)" stroke-width="3" opacity=".55"/>
  <circle cx="32" cy="32" r="7" fill="url(#og)"/>
  <text x="72" y="43" font-family="ui-monospace,SFMono-Regular,Menlo,monospace"
        font-size="30" letter-spacing="1.5">
    <tspan font-weight="700" fill="url(#og)">OMNI</tspan><tspan
       font-weight="400" fill="currentColor" opacity=".82">SINT</tspan>
  </text>
</svg>"""
