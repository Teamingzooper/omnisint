"""Full-screen, arrow-key navigable result browser.

A 900-account scan printed as one block is unreadable — you scroll past the
finding you needed. This paginates the same report into sections you step
through with the arrow keys, so the terminal behaves like a tool rather than
a log file.

Pure stdlib: raw-mode key reading via termios, drawing via rich. Falls back
to a plain linear print anywhere stdin is not a TTY.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Callable

from rich.console import Console as RichConsole

from . import panels
from .models import Profile

# ---------------------------------------------------------------------------
# key input
# ---------------------------------------------------------------------------
UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
PGUP, PGDN, HOME, END = "pgup", "pgdn", "home", "end"

# Terminals disagree about arrow keys. In normal cursor mode they send CSI
# sequences (ESC [ A); with DECCKM set — which many terminals and
# multiplexers enable — they send SS3 instead (ESC O A). Handling only the
# first meant an arrow press fell through to "escape" and quit the viewer,
# which is why arrows looked like they did nothing at all.
_ESCAPE_MAP = {
    "A": UP, "B": DOWN, "C": RIGHT, "D": LEFT,
    "H": HOME, "F": END, "5~": PGUP, "6~": PGDN, "1~": HOME, "4~": END,
    "P": HOME, "Q": END,          # SS3 Home/End
}

#: Letter keys, so navigation never depends on escape sequences arriving.
#: i/k scroll, j/l change section — the right-hand equivalent of WASD.
_LETTER_KEYS = {
    "i": UP, "k": DOWN, "j": LEFT, "l": RIGHT,
    "I": UP, "K": DOWN, "J": LEFT, "L": RIGHT,
    "w": UP, "s": DOWN, "a": LEFT, "d": RIGHT,
    "n": RIGHT, "p": LEFT, "\t": RIGHT,
}


def read_key() -> str:
    """Block for one keypress and return a normalised name.

    Reads with os.read on the raw fd rather than sys.stdin.read. Python's
    text stream is buffered, and in raw mode a one-character read on it can
    block waiting for a buffer fill that never comes — which stalled the
    viewer after its first frame and made every key look dead.
    """
    import select
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)

        def _read(n: int = 1) -> str:
            return os.read(fd, n).decode("utf-8", "replace")

        ch = _read()
        if ch != "\x1b":
            return ch

        # A bare ESC has nothing after it, so peek rather than block.
        if not select.select([fd], [], [], 0.12)[0]:
            return "escape"
        intro = _read()
        if intro not in ("[", "O"):
            return "escape"
        body = ""
        while len(body) < 8:
            if not select.select([fd], [], [], 0.12)[0]:
                break
            c = _read()
            body += c
            if c.isalpha() or c == "~":
                break
        return _ESCAPE_MAP.get(body, "unknown")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ---------------------------------------------------------------------------
@dataclass
class Section:
    key: str
    title: str
    build: Callable[[], object]
    badge: str = ""


class Viewer:
    def __init__(self, profile: Profile, console: RichConsole,
                 on_export: Callable[[], None] | None = None):
        self.profile = profile
        self.c = console
        self.on_export = on_export
        self.index = 0
        self.offset = 0
        self.sections = self._build_sections()
        self._cache: dict[int, list[str]] = {}

    # -- sections ---------------------------------------------------------
    def _build_sections(self) -> list[Section]:
        p = self.profile
        accounts = p.sorted_accounts()
        same = sum(1 for a in accounts if a.attribution_level == "same person")
        diff = sum(1 for a in accounts if a.attribution_level == "likely different person")
        bare = sum(1 for a in accounts if not a.metadata and not a.avatar)

        sections = [
            Section("overview", "Overview", lambda: panels.overview(p)),
            Section("summary", "What they do", lambda: panels.summary(p)),
            Section("identity", "Identity", lambda: panels.identity(p),
                    badge=str(len(p.names))),
            Section("personas", "Identities", lambda: panels.personas(p),
                    badge=f"{diff} flagged" if diff else str(len(p.personas))),
            Section("accounts", "Accounts", lambda: panels.accounts(p, 0.0, True),
                    badge=str(len(accounts))),
            Section("details", "Full data", lambda: panels.details(p),
                    badge=str(len(accounts) - bare)),
        ]
        if bare:
            sections.append(Section(
                "bare", "Existence only",
                lambda: panels.bare_hits(p) or panels.overview(p), badge=str(bare)))
        sections += [
            Section("infra", "Infrastructure", lambda: panels.infrastructure(p)),
            Section("breach", "Breaches", lambda: panels.breaches(p),
                    badge=str(len(p.breaches)) if p.breaches else ""),
            Section("tools", "Tools", lambda: panels.tool_coverage(p),
                    badge=str(len(p.runs))),
            Section("caveats", "Caveats", lambda: panels.caveats(p),
                    badge=str(len(p.warnings)) if p.warnings else ""),
        ]
        _ = same
        return sections

    def _lines(self, index: int) -> list[str]:
        """Render a section once and cache its ANSI lines."""
        if index not in self._cache:
            import io
            width = max(60, self.c.size.width)
            buf = RichConsole(width=width, record=True, file=io.StringIO(),
                              force_terminal=True,
                              color_system=self.c.color_system or "truecolor")
            buf.print(self.sections[index].build())
            text = buf.export_text(styles=True)
            self._cache[index] = text.rstrip("\n").split("\n")
        return self._cache[index]

    def invalidate(self) -> None:
        """Drop cached renders, e.g. after the terminal is resized."""
        self._cache.clear()

    # -- drawing ----------------------------------------------------------
    @staticmethod
    def _clear() -> None:
        """Home the cursor and clear the screen.

        Written straight to stdout, not through rich: rich reads square
        brackets as markup, so an ANSI sequence handed to console.print is
        swallowed as a style tag and the screen never actually clears.
        """
        sys.stdout.write("\x1b[H\x1b[2J")
        sys.stdout.flush()

    def _tabs(self) -> str:
        out = []
        for i, s in enumerate(self.sections):
            label = s.title + (f" [dim]{s.badge}[/dim]" if s.badge else "")
            if i == self.index:
                out.append(f"[reverse bold] {s.title}"
                           f"{' ' + s.badge if s.badge else ''} [/reverse bold]")
            else:
                out.append(f"[dim] {label} [/dim]")
        return "".join(out)

    def _draw(self, body_height: int) -> None:
        lines = self._lines(self.index)
        total = len(lines)
        self.offset = max(0, min(self.offset, max(0, total - body_height)))
        window = lines[self.offset:self.offset + body_height]

        self._clear()
        self.c.print(self._tabs())
        for line in window:
            print(line)
        for _ in range(body_height - len(window)):
            print()

        if total > body_height:
            first = self.offset + 1
            last = min(self.offset + body_height, total)
            pos = f"lines {first}–{last} of {total}"
        else:
            pos = f"{total} line{'s' if total != 1 else ''}"
        self.c.print(
            f"[bold]j[/bold][dim]/[/dim][bold]l[/bold][dim] or ←/→ section · [/dim]"
            f"[bold]i[/bold][dim]/[/dim][bold]k[/bold][dim] or ↑/↓ scroll · [/dim]"
            f"[bold]space[/bold][dim] page · [/dim][bold]1-9[/bold][dim] jump · [/dim]"
            f"[bold]e[/bold][dim] export · [/dim][bold]q[/bold][dim] back"
            f"   ·   {self.sections[self.index].title} · {pos}[/dim]"
        )

    # -- loop -------------------------------------------------------------
    def run(self) -> None:
        if not sys.stdin.isatty():
            self.dump()
            return
        try:
            last_width = self.c.size.width
            while True:
                if self.c.size.width != last_width:
                    self.invalidate()
                    last_width = self.c.size.width
                height = max(8, self.c.size.height - 3)
                self._draw(height)
                key = read_key()

                if key in ("q", "Q", "escape", "\x03", "\x04"):
                    self._clear()
                    return

                # Letter keys and arrows funnel into the same four moves, so
                # navigation works even where escape sequences never arrive.
                move = _LETTER_KEYS.get(key, key)

                if move == RIGHT:
                    self.index = (self.index + 1) % len(self.sections)
                    self.offset = 0
                elif move == LEFT:
                    self.index = (self.index - 1) % len(self.sections)
                    self.offset = 0
                elif move == DOWN:
                    self.offset += 3
                elif move == UP:
                    self.offset = max(0, self.offset - 3)
                elif key in (PGDN, " ", "f"):
                    self.offset += height
                elif key in (PGUP, "b"):
                    self.offset = max(0, self.offset - height)
                elif key in (HOME, "g"):
                    self.offset = 0
                elif key in (END, "G"):
                    self.offset = max(0, len(self._lines(self.index)) - height)
                elif key in ("e", "E") and self.on_export:
                    self._clear()
                    self.on_export()
                    self.c.input("[dim]press Enter to return to the report[/dim] ")
                elif key.isdigit() and key != "0":
                    target = int(key) - 1
                    if target < len(self.sections):
                        self.index, self.offset = target, 0
        except (KeyboardInterrupt, EOFError):
            self._clear()
        except Exception as exc:
            # Never trap the operator in a broken TUI — fall back to plain text.
            self.c.print(f"[yellow]viewer unavailable ({exc}); "
                         "printing plain report[/yellow]")
            self.dump()

    def dump(self) -> None:
        """Linear print — used when there is no TTY, or the viewer fails."""
        for section in self.sections:
            self.c.print(section.build())
        self.c.print(panels.handling())
