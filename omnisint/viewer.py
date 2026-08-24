"""Full-screen, arrow-key navigable result browser.

A 900-account scan printed as one block is unreadable — you scroll past the
finding you needed. This paginates the same report into sections you step
through with the arrow keys, so the terminal behaves like a tool rather than
a log file.

Pure stdlib: raw-mode key reading via termios, drawing via rich. Falls back
to a plain linear print anywhere stdin is not a TTY.
"""
from __future__ import annotations

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

_ESCAPE_MAP = {
    "A": UP, "B": DOWN, "C": RIGHT, "D": LEFT,
    "H": HOME, "F": END, "5~": PGUP, "6~": PGDN, "1~": HOME, "4~": END,
}


def read_key() -> str:
    """Block for one keypress and return a normalised name."""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch != "\x1b":
            return ch
        # Escape sequence. A bare ESC has nothing following it, so peek with
        # a zero timeout rather than blocking forever.
        import select

        if not select.select([fd], [], [], 0.05)[0]:
            return "escape"
        seq = sys.stdin.read(1)
        if seq != "[":
            return "escape"
        body = ""
        while True:
            if not select.select([fd], [], [], 0.05)[0]:
                break
            c = sys.stdin.read(1)
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

        self.c.print("\x1b[H\x1b[2J", end="")   # home + clear
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
            f"[dim]←/→ section · ↑/↓ scroll · PgUp/PgDn page · [/dim]"
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
                    self.c.print("\x1b[H\x1b[2J", end="")
                    return
                if key in (RIGHT, "\t", "l", "n"):
                    self.index = (self.index + 1) % len(self.sections)
                    self.offset = 0
                elif key in (LEFT, "h", "p"):
                    self.index = (self.index - 1) % len(self.sections)
                    self.offset = 0
                elif key == DOWN or key == "j":
                    self.offset += 1
                elif key == UP or key == "k":
                    self.offset = max(0, self.offset - 1)
                elif key == PGDN or key == " ":
                    self.offset += height
                elif key == PGUP or key == "b":
                    self.offset = max(0, self.offset - height)
                elif key == HOME or key == "g":
                    self.offset = 0
                elif key == END or key == "G":
                    self.offset = max(0, len(self._lines(self.index)) - height)
                elif key in ("e", "E") and self.on_export:
                    self.c.print("\x1b[H\x1b[2J", end="")
                    self.on_export()
                    self.c.input("[dim]press Enter to return to the report[/dim] ")
                elif key.isdigit() and key != "0":
                    target = int(key) - 1
                    if target < len(self.sections):
                        self.index, self.offset = target, 0
        except (KeyboardInterrupt, EOFError):
            self.c.print("\x1b[H\x1b[2J", end="")
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
