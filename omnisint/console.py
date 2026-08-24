"""Interactive console: type what you know, get everything back.

The CLI is fine when you already know the flags. This is for the other case —
you have a handful of scraps about someone (a handle, an old email, a phone
number) and you want every tool on the box pointed at all of them at once.
"""
from __future__ import annotations

import re
import shlex
import time
from pathlib import Path

from . import __version__
from .brand import MARK, banner
from .config import PRESET_BLURB, ScanOptions, apply_preset
from .engine import Engine
from .ethics import AuthorizationError, audit, require_authorization
from .models import Identifier, IdType
from .registry import adapter_status
from .report import render_html, render_json, render_markdown
from .viewer import Viewer

HELP = """\
[bold]Primary[/bold] — things that identify the person. These get searched.
Type them on one line; use commas so multi-word names stay together:

    [cyan]alex rivera, mjs, mjs@example.com, +14155550100[/cyan]

[bold]Secondary[/bold] — things you know [italic]about[/italic] them: employer, school,
city, band. These are [bold]never searched[/bold]. They are matched against what the
primaries bring back, which is faster and far more reliable than
searching "Acme Corp" across 3000 sites.

Put both on one line with a [bold]semicolon[/bold], or add them later with [cyan]sec[/cyan]:

    [cyan]alex rivera, mjs[/cyan][bold];[/bold] [magenta]youtube, field trip[/magenta]
    [cyan]sec Acme Corp, MIT, Portland[/cyan]

An account whose bio names your employer is your subject. That beats any
amount of username matching.

[bold]After a scan[/bold] the report opens full-screen. [bold]j[/bold]/[bold]l[/bold] change section,
[bold]i[/bold]/[bold]k[/bold] scroll, [bold]q[/bold] returns you here. Nothing is written to disk unless
you run [cyan]export[/cyan]. [bold]Ctrl-C[/bold] cancels the current line or an in-progress
scan — it does not exit; use [cyan]quit[/cyan] for that.

[bold]Commands[/bold]
  [cyan]scan[/cyan] / [cyan]go[/cyan]        run against everything collected so far
  [cyan]sec <terms>[/cyan]     add secondary terms (cross-checked, never searched)
  [cyan]show[/cyan]            list everything currently loaded
  [cyan]drop <n|all>[/cyan]    remove one identifier, or clear the list
  [cyan]expand[/cyan]          turn loaded names into likely handles to search

[bold]Flags work anywhere on the line[/bold], same as on the command line:

    [cyan]alex@example.com -v[/cyan]        [cyan]jdoe -d; acme corp[/cyan]
    [cyan]jdoe --pivot 2 --case OPS-9[/cyan]

  toggles: [cyan]-v -q -d -s --nsfw --active --passive --darkweb[/cyan]
  values : [cyan]--pivot --timeout --workers --top-sites --min-confidence[/cyan]
           [cyan]--case --proxy --only --exclude --sec[/cyan]

[bold]Depth[/bold]
  [cyan]-q[/cyan] / [cyan]quick[/cyan]      top 50 sites — mainstream platforms, back in seconds
  [cyan]-s[/cyan] / [cyan]standard[/cyan]   top 500 sites per tool (default)
  [cyan]-d[/cyan] / [cyan]deep[/cyan]       every site in every database, plus a pivot hop (slow)
  [cyan]-v[/cyan] / [cyan]verbose[/cyan]    toggle per-site detail and full caveats
  [cyan]pivot <n>[/cyan]       follow identifiers discovered mid-scan, n hops
  [cyan]set <opt> <v>[/cyan]   timeout, workers, top-sites, min-confidence
  [cyan]opts[/cyan]            show current settings
  [cyan]tools[/cyan]           which backends are installed
  [cyan]found[/cyan]           identifiers the scan discovered — search them too
  [cyan]view[/cyan] / [cyan]last[/cyan]     reopen the last report in the browser
  [cyan]export [dir][/cyan]    write JSON + HTML + Markdown (never automatic)
  [cyan]help[/cyan]  ·  [cyan]quit[/cyan]
"""

# Flags accepted anywhere on an input line, so the CLI's vocabulary works
# inside the console too. Without this, `alex@example.com -v` classified the
# `-v` as a username and silently searched for it.
_TOGGLE_FLAGS = {
    "-v": "verbose", "--verbose": "verbose",
    "-q": "quick", "--quick": "quick",
    "-d": "deep", "--deep": "deep",
    "-s": "standard", "--standard": "standard",
    "--nsfw": "nsfw", "--active": "active", "--darkweb": "darkweb",
    "--hudson": "hudson",
    "--passive": "passive",
}
_VALUE_FLAGS = {
    "--pivot": "pivot", "--timeout": "timeout", "--workers": "workers",
    "--top-sites": "top-sites", "--tool-timeout": "tool-timeout",
    "--min-confidence": "min-confidence", "--delay": "delay",
    "--case": "case", "--proxy": "proxy", "--only": "only",
    "--exclude": "exclude", "--sec": "sec", "--secondary": "sec",
}

_NAME_WORD = re.compile(r"^[A-Za-z][A-Za-z'\u2019-]{1,}$")


def _looks_like_one_name(tokens: list[str]) -> bool:
    """True when a space-separated line reads as a single person's name."""
    return (2 <= len(tokens) <= 4
            and all(_NAME_WORD.match(t) for t in tokens))


_COMMANDS = {"scan", "go", "run", "show", "drop", "deep", "pivot", "set",
             "opts", "options", "tools", "last", "save", "help", "?", "quit",
             "exit", "q", "clear", "expand", "quick", "standard", "verbose",
             "-q", "-d", "-v", "-s", "export", "view", "sec", "secondary",
             "+", "found"}


class Console:
    def __init__(self, console, opts: ScanOptions, auth, outdir: Path | None = None):
        self.c = console
        self.opts = opts
        self.auth = auth
        self.targets: list[Identifier] = []
        self.secondary: list[str] = []
        #: Discovered identifiers the operator has already been offered and
        #: declined, so we stop asking about the same ones every scan.
        self.declined: set[str] = set()
        self.last = None
        self.last_meta: dict = {}
        self.outdir = outdir or (Path.home() / "omnisint-reports")

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def split_input(raw: str) -> list[str]:
        """Split a line into identifiers.

        If the line has commas, the comma is the separator and nothing else
        is — so `alex rivera, jdoe` is a name and a handle, not three
        handles. Without commas, whitespace separates, which keeps the common
        `jdoe jdoe@example.com` case a single keystroke.

        Quotes always win, so a multi-word name can be given on a line that
        uses spaces as separators.
        """
        raw = raw.strip()
        if not raw:
            return []
        if '"' in raw or "'" in raw:
            try:
                return [p for p in shlex.split(raw) if p]
            except ValueError:
                pass  # unbalanced quote: fall through to the plain rules
        if "," in raw:
            return [p.strip() for p in raw.split(",") if p.strip()]
        tokens = raw.split()
        if _looks_like_one_name(tokens):
            # `alex rivera` is a person, not two handles. Anything
            # with a comma, a digit, an @ or a dot escapes this branch, and
            # a comma always forces the split explicitly.
            return [" ".join(tokens)]
        return tokens

    @staticmethod
    def extract_flags(raw: str) -> tuple[str, list[tuple[str, str | None]], list[str]]:
        """Pull flags out of an input line, wherever they appear.

        Returns the line with flags removed, the flags found, and any
        unrecognised ones. Splitting on whitespace and rejoining keeps the
        comma and semicolon structure intact, so `a, b -v; work` still parses
        as two primaries and one secondary.
        """
        tokens = raw.split()
        kept: list[str] = []
        found: list[tuple[str, str | None]] = []
        unknown: list[str] = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            # A flag can butt up against a separator (`jdoe -d; work`). Peel
            # the punctuation off and put it back, or the semicolon is lost
            # and the secondary half of the line silently becomes primary.
            trailer = ""
            while tok and tok[-1] in ",;":
                trailer = tok[-1] + trailer
                tok = tok[:-1]
            bare, _, inline = tok.partition("=")
            low = bare.lower()

            if low in _TOGGLE_FLAGS:
                found.append((_TOGGLE_FLAGS[low], None))
                if trailer:
                    kept.append(trailer)
            elif low in _VALUE_FLAGS:
                value = inline
                if not value and i + 1 < len(tokens):
                    i += 1
                    value = tokens[i]
                    # The value can carry the separator too (`--pivot 2, mjs`).
                    while value and value[-1] in ",;":
                        trailer = value[-1] + trailer
                        value = value[:-1]
                found.append((_VALUE_FLAGS[low], (value or "").rstrip(",;") or None))
                if trailer:
                    kept.append(trailer)
            elif (len(tok) > 1 and tok.startswith("-")
                  and not tok[1].isdigit()):
                # Looks like a flag but is not one. Refusing it beats
                # searching for "-x" as though it were a handle.
                unknown.append(tok)
                if trailer:
                    kept.append(trailer)
            else:
                kept.append(tok + trailer)
            i += 1
        return " ".join(kept), found, unknown

    def _apply_flags(self, found: list[tuple[str, str | None]]) -> None:
        for name, value in found:
            if name in ("quick", "standard", "deep"):
                self._preset(name)
            elif name == "verbose":
                self.opts.verbose = not self.opts.verbose
                self.c.print(f"  [green]verbose "
                             f"{'ON' if self.opts.verbose else 'off'}[/green]")
            elif name == "nsfw":
                self.opts.nsfw = True
                self.c.print("  [green]nsfw sites included[/green]")
            elif name == "active":
                self.opts.passive = False
                self.c.print("  [bold yellow]ACTIVE mode[/bold yellow][dim] — probes "
                             "may be visible to the subject[/dim]")
            elif name == "passive":
                self.opts.passive = True
                self.c.print("  [green]passive mode[/green]")
            elif name == "hudson":
                self.opts.only = set(self.opts.only) | {"hudsonrock"}
                self.c.print("  [green]breach-exposure check enabled[/green]"
                             "[dim] (slow)[/dim]")
            elif name == "darkweb":
                self.opts.only = set(self.opts.only) | {"darkweb"}
                self.c.print("  [green]dark-web search enabled[/green][dim] "
                             "(needs Tor)[/dim]")
            elif name == "sec" and value:
                self._add_secondary(value)
            elif name == "case" and value:
                self.auth.case = value
                self.c.print(f"  [green]case = {value}[/green]")
            elif name == "pivot" and value:
                try:
                    self.opts.pivot_depth = int(value)
                    self.c.print(f"  [green]pivot depth = {value}[/green]")
                except ValueError:
                    self.c.print(f"  [yellow]pivot needs a number, got {value!r}[/yellow]")
            elif name in ("only", "exclude") and value:
                target = {t.strip() for t in value.split(",") if t.strip()}
                setattr(self.opts, name, target)
                self.c.print(f"  [green]{name} = {', '.join(sorted(target))}[/green]")
            elif name == "proxy" and value:
                self.opts.proxy = value
                self.c.print(f"  [green]proxy = {value}[/green]")
            elif value:
                self._set(name, value)

    @classmethod
    def parse_line(cls, raw: str) -> tuple[list[str], list[str]]:
        """Split one line into (primary, secondary).

        A semicolon separates the two halves, so a whole investigation fits
        on one line:

            alex rivera, the man zooper; youtube, field trip
            └────────── primary ────────────┘  └──── secondary ────┘

        Each half then follows the normal comma/whitespace rules. Everything
        after the first semicolon is secondary, so stray semicolons later in
        the line cannot silently promote a term to being searched.
        """
        if ";" not in raw:
            return cls.split_input(raw), []
        head, _, tail = raw.partition(";")
        secondary = [t.strip() for t in tail.replace(";", ",").split(",") if t.strip()]
        return cls.split_input(head), secondary

    def _classify(self, raw: str) -> None:
        raw, flags, unknown = self.extract_flags(raw)
        self._apply_flags(flags)
        for bad in unknown:
            self.c.print(f"  [yellow]?[/yellow] {bad}  [dim]→ not a known flag; "
                         f"ignored (see [/dim][cyan]help[/cyan][dim])[/dim]")
        if not raw.strip():
            return
        primary_raw, secondary_raw = self.parse_line(raw)
        added, skipped = [], []
        for piece in primary_raw:
            ident = Identifier.parse(piece)
            if ident.type is IdType.UNKNOWN:
                skipped.append(piece)
                continue
            if any(t.key() == ident.key() for t in self.targets):
                continue
            self.targets.append(ident)
            added.append(ident)

        for ident in added:
            hint = ""
            if ident.type is IdType.NAME:
                # No backend searches a name, so say what it *will* do rather
                # than letting it look like a queued search.
                hint = ("  [dim]— used to confirm identity; "
                        "type [cyan]expand[/cyan] to also search likely handles[/dim]")
            self.c.print(f"  [green]+[/green] {ident.value}  "
                         f"[dim]→ {ident.type.value}[/dim]{hint}")
        for piece in skipped:
            self.c.print(f"  [yellow]?[/yellow] {piece}  [dim]→ could not "
                         f"classify; ignored[/dim]")
        if secondary_raw:
            self._add_secondary(", ".join(secondary_raw))

    def _add_secondary(self, raw: str) -> None:
        terms = [t.strip() for t in raw.replace(",", "\n").split("\n") if t.strip()]
        if not terms:
            self.c.print("[yellow]usage:[/yellow] sec Acme Corp, MIT, Portland")
            return
        for term in terms:
            if term.lower() not in {t.lower() for t in self.secondary}:
                self.secondary.append(term)
                self.c.print(f"  [magenta]±[/magenta] {term}  "
                             f"[dim]→ secondary (cross-check only)[/dim]")

    def _show(self) -> None:
        if not self.targets and not self.secondary:
            self.c.print("[dim]Nothing loaded yet. Type what you know.[/dim]")
            return
        self.c.print("\n[bold]Primary[/bold] [dim](searched)[/dim]")
        for n, ident in enumerate(self.targets, 1):
            self.c.print(f"  [dim]{n}.[/dim] {ident.value}  "
                         f"[dim]({ident.type.value})[/dim]")
        if self.secondary:
            self.c.print("\n[bold]Secondary[/bold] [dim](cross-checked, never searched)[/dim]")
            for term in self.secondary:
                self.c.print(f"  [magenta]±[/magenta] {term}")
        engine = Engine(self.opts)
        plan = engine.plan(self.targets)
        self.c.print(f"\n[dim]{len(plan)} task(s) across "
                     f"{len({a for a, _ in plan})} tool(s)[/dim]\n")

    def _opts(self) -> None:
        o = self.opts
        self.c.print(
            f"\n  [bold]depth[/bold]      [bold cyan]{o.preset}[/bold cyan] — "
            f"{'ALL sites' if o.all_sites else f'top {o.top_sites} sites'}"
            f"   pivot={o.pivot_depth}\n"
            f"  [bold]network[/bold]    timeout={o.request_timeout}s  "
            f"workers={o.workers}  tool-timeout={o.tool_timeout}s\n"
            f"  [bold]mode[/bold]       {'passive' if o.passive else 'ACTIVE'}"
            f"   nsfw={'on' if o.nsfw else 'off'}\n"
            f"  [bold]display[/bold]    min-confidence={o.min_confidence}  "
            f"verbose={'on' if o.verbose else 'off'}\n"
            f"  [bold]reports[/bold]    {self.outdir}\n"
        )

    def _set(self, key: str, value: str) -> None:
        mapping = {
            "timeout": ("request_timeout", int),
            "workers": ("workers", int),
            "top-sites": ("top_sites", int),
            "topsites": ("top_sites", int),
            "tool-timeout": ("tool_timeout", int),
            "min-confidence": ("min_confidence", float),
            "minconf": ("min_confidence", float),
            "delay": ("delay", float),
        }
        if key not in mapping:
            self.c.print(f"[yellow]Unknown setting {key!r}.[/yellow] "
                         f"Try: {', '.join(sorted(mapping))}")
            return
        attr, cast = mapping[key]
        try:
            setattr(self.opts, attr, cast(value))
        except ValueError:
            self.c.print(f"[red]{value!r} is not a valid {cast.__name__}.[/red]")
            return
        self.c.print(f"[green]{attr} = {getattr(self.opts, attr)}[/green]")

    # -- the scan ---------------------------------------------------------
    def _scan(self) -> None:
        if not self.targets:
            self.c.print("[yellow]Nothing to scan.[/yellow] "
                         "Secondary terms alone are not searchable — "
                         "add a name, handle, email or phone first.")
            return

        engine = Engine(self.opts)
        if not engine.adapters:
            self.c.print("[red]No backends available.[/red] Try [bold]tools[/bold].")
            return

        plan = engine.plan(self.targets)
        if not plan:
            self.c.print("[yellow]No installed tool accepts these identifier "
                         "types.[/yellow] Try [bold]tools[/bold].")
            return

        run_id = audit(
            "console.scan", self.auth,
            targets=[t.value for t in self.targets],
            secondary=list(self.secondary),
            types=[t.type.value for t in self.targets],
            adapters=sorted({a for a, _ in plan}),
            passive=self.opts.passive,
            pivot_depth=self.opts.pivot_depth,
        )
        self.c.print(
            f"\n[bold cyan]▸ scanning[/bold cyan] {len(self.targets)} "
            f"identifier(s) · {len(plan)} task(s) · run [bold]{run_id}[/bold]"
            f" · {'passive' if self.opts.passive else 'ACTIVE'}\n"
        )

        from rich.progress import (BarColumn, Progress, SpinnerColumn,
                                   TextColumn, TimeElapsedColumn)
        started = time.time()
        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=22), TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(), console=self.c, transient=True,
        ) as prog:
            task = prog.add_task("querying…", total=len(plan))

            def on_progress(kind, message):
                if kind in ("done", "fail"):
                    prog.advance(task)
                    prog.console.print(
                        f"  [{'green' if kind == 'done' else 'red'}]"
                        f"{'✔' if kind == 'done' else '✖'}[/] {message}")
                else:
                    prog.update(task, description=message)

            engine.progress = on_progress
            try:
                profile = engine.scan(self.targets, secondary=self.secondary)
            except KeyboardInterrupt:
                profile = None

        if profile is None:
            self.c.print(
                "\n[yellow]Scan interrupted.[/yellow] [dim]Your identifiers are "
                "still loaded — press Enter to run it again, or[/dim] "
                "[cyan]quit[/cyan][dim] to exit.[/dim]")
            audit("console.scan.interrupted", self.auth, run_id=run_id)
            return

        self.last = profile
        self.last_meta = {
            "run_id": run_id, "case": self.auth.case,
            "operator": self.auth.operator, "basis": self.auth.basis,
            "version": __version__, "passive": self.opts.passive,
        }

        elapsed = time.time() - started
        audit("console.scan.finish", self.auth, run_id=run_id,
              accounts=len(profile.accounts))

        same = sum(1 for a in profile.accounts.values()
                   if a.attribution_level == "same person")
        diff = sum(1 for a in profile.accounts.values()
                   if a.attribution_level == "likely different person")
        self.c.print(
            f"\n[bold green]done[/bold green] in {elapsed:.1f}s · "
            f"[bold]{len(profile.accounts)}[/bold] accounts · "
            f"[green]{same} likely your subject[/green] · "
            f"[red]{diff} likely other people[/red]"
        )
        self._view()

    def _view(self) -> None:
        if self.last is None:
            self.c.print("[dim]No scan yet.[/dim]")
            return
        Viewer(self.last, self.c, on_export=lambda: self._export()).run()
        self._recap()
        self._offer_discovered()

    def _recap(self) -> None:
        """Compact summary printed on returning from the full-screen viewer.

        The viewer clears the screen on exit, so without this the operator
        lands on an empty terminal and it looks like the scan was lost.
        """
        if self.last is None:
            return
        p = self.last
        accounts = p.sorted_accounts()
        same = sum(1 for a in accounts if a.attribution_level == "same person")
        diff = sum(1 for a in accounts if a.attribution_level == "likely different person")
        primary = next((x["name"] for x in p.personas if x["primary"]), None)
        seeds = ", ".join(s.value for s in p.seeds)

        self.c.print(
            f"\n[bold]{seeds}[/bold] — [bold]{len(accounts)}[/bold] accounts · "
            f"[green]{same} likely your subject[/green] · "
            f"[red]{diff} likely other people[/red]"
        )
        if primary:
            self.c.print(f"  identity: [bold green]{primary}[/bold green]")
        elif p.personas:
            self.c.print("  [yellow]identity unresolved[/yellow][dim] — "
                         "several names, none better corroborated[/dim]")
        self.c.print(
            "  [cyan]view[/cyan][dim] reopen report · [/dim]"
            "[cyan]export[/cyan][dim] save to disk · [/dim]"
            "[cyan]sec <term>[/cyan][dim] add a cross-check and rescan · [/dim]"
            "[cyan]drop all[/cyan][dim] start over[/dim]\n"
        )

    def discovered(self) -> list[Identifier]:
        """Identifiers the tools turned up that we have not searched yet."""
        if self.last is None:
            return []
        loaded = {t.key() for t in self.targets}
        out: list[Identifier] = []
        for ident in self.last.identifiers.values():
            if ident.origin == "input" or ident.key() in loaded:
                continue
            if ident.key() in self.declined:
                continue
            if ident.type not in (IdType.USERNAME, IdType.EMAIL):
                continue
            out.append(ident)
        # Emails first: an address is a far stronger lead than a handle
        # scraped off a profile page.
        out.sort(key=lambda i: (i.type is not IdType.EMAIL, i.value.lower()))
        return out

    def _offer_discovered(self) -> None:
        """Show identifiers found mid-scan and offer to search them too.

        These are the highest-value leads a scan produces — an email on a
        GitHub profile, a linked handle on Keybase — and they are easy to
        miss in a long report. Asking is better than pivoting automatically:
        each one multiplies the next scan's cost, and some are junk.
        """
        found = self.discovered()
        if not found:
            return

        self.c.print(f"[bold magenta]{len(found)} new identifier(s) found "
                     f"during this scan[/bold magenta]")
        for n, ident in enumerate(found, 1):
            tag = ("[bold]email[/bold]" if ident.type is IdType.EMAIL
                   else "username")
            self.c.print(f"  [magenta]{n}.[/magenta] [bold]{ident.value}[/bold]"
                         f"  [dim]({tag}, via {ident.origin})[/dim]")

        try:
            answer = input("\nSearch these too? [y]es / [n]o / numbers "
                           "(e.g. 1,3): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            self.c.print()
            return

        if answer in ("n", "no", "", "q"):
            self.declined.update(i.key() for i in found)
            self.c.print("[dim]skipped — type[/dim] [cyan]found[/cyan]"
                         "[dim] to see them again[/dim]\n")
            return

        if answer in ("y", "yes", "a", "all"):
            chosen = found
        else:
            picked = set()
            for piece in answer.replace(" ", ",").split(","):
                if piece.isdigit() and 1 <= int(piece) <= len(found):
                    picked.add(int(piece))
            if not picked:
                self.c.print("[yellow]Did not understand that.[/yellow] "
                             "[dim]Nothing added.[/dim]\n")
                return
            chosen = [found[n - 1] for n in sorted(picked)]
            self.declined.update(
                i.key() for i in found if i not in chosen)

        for ident in chosen:
            # Re-seed as input so it is searched in its own right rather
            # than inheriting the pivot depth that produced it.
            self.targets.append(Identifier(ident.value, ident.type,
                                           origin="input", depth=0))
            self.c.print(f"  [green]+[/green] {ident.value}")
        self.c.print(f"\n[dim]{len(chosen)} added — press Enter to scan, or "
                     "add more first.[/dim]\n")

    def _export(self, arg: str | None = None) -> None:
        if self.last is None:
            self.c.print("[yellow]Nothing to export yet.[/yellow]")
            return
        outdir = Path(arg).expanduser() if arg else self.outdir
        outdir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = "_".join(
            "".join(ch for ch in t.value if ch.isalnum() or ch in "-_.@")[:40]
            for t in self.last.seeds[:3]
        ) or "scan"
        stem = f"{slug}-{stamp}"

        written = []
        for suffix, text in (
            (".json", render_json(self.last, self.last_meta)),
            (".html", render_html(self.last, self.last_meta, 0.0)),
            (".md", render_markdown(self.last, self.last_meta, 0.0)),
        ):
            # String concatenation, not with_suffix: a dotted stem (any
            # email address) makes with_suffix eat part of the name.
            path = outdir / (stem + suffix)
            path.write_text(text)
            try:
                path.chmod(0o600)   # a dossier is sensitive personal data
            except OSError:
                pass
            written.append(path)

        self.c.print("\n[bold green]exported[/bold green] [dim](mode 600)[/dim]")
        for path in written:
            self.c.print(f"  {path}")
        self.c.print()
        audit("console.export", self.auth, files=[str(p) for p in written])

    def _tools(self) -> None:
        from rich.table import Table
        from rich import box
        t = Table(box=box.SIMPLE, header_style="bold")
        for col in ("Backend", "Status", "Accepts", "What it does"):
            t.add_column(col, overflow="fold")
        for row in adapter_status():
            t.add_row(
                row["name"],
                "[green]ready[/green]" if row["available"] else "[red]missing[/red]",
                ", ".join(row["accepts"]), row["description"],
            )
        self.c.print(t)

    # -- loop -------------------------------------------------------------
    def run(self) -> int:
        ready = sum(1 for r in adapter_status() if r["available"])
        self.c.print(banner(self.c.size.width, __version__, ready, self.auth.case))
        self.c.print("  [dim]type[/dim] [cyan]help[/cyan][dim], or just start "
                     "typing what you know[/dim]\n")

        while True:
            try:
                raw = input(f"{MARK} ").strip()
            except KeyboardInterrupt:
                # Cancel the line, keep the session. Losing a loaded target
                # list and a finished scan to a stray Ctrl-C is punishing.
                self.c.print("\n[dim]cancelled — type[/dim] [cyan]quit[/cyan]"
                             "[dim] to exit[/dim]")
                continue
            except EOFError:
                self.c.print("\n[dim]bye[/dim]")
                return 0
            if not raw:
                # Bare Enter is the natural "go" once something is loaded.
                if self.targets:
                    self._scan()
                elif self.secondary:
                    self.c.print(
                        "[yellow]Only secondary terms are loaded.[/yellow] Those "
                        "are cross-checks, never searched on their own — add a "
                        "name, handle, email or phone to search for.")
                else:
                    self.c.print("[dim]Nothing loaded yet. Type what you know "
                                 "(or[/dim] [cyan]help[/cyan][dim]).[/dim]")
                continue

            parts = shlex.split(raw) if raw.count("'") % 2 == 0 else raw.split()
            head = parts[0].lower()
            rest = parts[1:]

            if head not in _COMMANDS:
                self._classify(raw)
                if self.targets:
                    self.c.print("[dim]Press Enter to scan, or add more.[/dim]")
                continue

            try:
                if head in ("quit", "exit", "q"):
                    self.c.print("[dim]bye[/dim]")
                    return 0
                if head in ("help", "?"):
                    self.c.print(HELP)
                elif head in ("scan", "go", "run"):
                    self._scan()
                elif head in ("sec", "secondary", "+"):
                    self._add_secondary(" ".join(rest))
                elif head == "show":
                    self._show()
                elif head in ("drop", "clear"):
                    self._drop(rest)
                elif head == "expand":
                    self._expand()
                elif head in ("quick", "-q"):
                    self._preset("quick")
                elif head in ("standard", "-s"):
                    self._preset("standard")
                elif head in ("deep", "-d"):
                    self._preset("deep")
                elif head in ("verbose", "-v"):
                    self.opts.verbose = not self.opts.verbose
                    self.c.print(f"[green]verbose "
                                 f"{'ON' if self.opts.verbose else 'off'}[/green]")
                elif head == "pivot":
                    if rest:
                        try:
                            depth = int(rest[0])
                        except ValueError:
                            self.c.print(f"[yellow]pivot needs a number "
                                         f"(got {rest[0]!r}).[/yellow] "
                                         "[dim]e.g.[/dim] [cyan]pivot 1[/cyan]")
                            continue
                        if depth < 0:
                            self.c.print("[yellow]pivot depth cannot be "
                                         "negative.[/yellow]")
                            continue
                        self.opts.pivot_depth = depth
                    else:
                        self.opts.pivot_depth = 0 if self.opts.pivot_depth else 1
                    self.c.print(f"[green]pivot depth = "
                                 f"{self.opts.pivot_depth}[/green]")
                elif head == "set":
                    if len(rest) < 2:
                        self.c.print("[yellow]usage: set <option> <value>[/yellow]")
                    else:
                        self._set(rest[0].lower(), rest[1])
                elif head in ("opts", "options"):
                    self._opts()
                elif head == "tools":
                    self._tools()
                elif head == "last":
                    self._view()
                elif head in ("export", "save"):
                    self._export(rest[0] if rest else None)
                elif head == "view":
                    self._view()
                elif head == "found":
                    self.declined.clear()
                    if not self.discovered():
                        self.c.print("[dim]No unsearched identifiers from the "
                                     "last scan.[/dim]")
                    else:
                        self._offer_discovered()
            except KeyboardInterrupt:
                self.c.print("\n[yellow]interrupted — back to prompt[/yellow]")
            except Exception as exc:
                # One bad command must never drop the operator's session, and
                # a raw traceback is not a useful thing to show them. Escape
                # the message: an exception whose text contains square
                # brackets would otherwise be parsed as markup and raise
                # again *inside* the handler, killing the session.
                from rich.markup import escape as _escape
                self.c.print(f"[red]That did not work:[/red] {_escape(str(exc))}")
                self.c.print("[dim]type[/dim] [cyan]help[/cyan][dim] for the "
                             "command list[/dim]")

    def _preset(self, name: str) -> None:
        # Preserve the operator's display and safety choices; a depth preset
        # should change coverage, not what they are willing to do.
        keep = (self.opts.min_confidence, self.opts.verbose,
                self.opts.passive, self.opts.nsfw, self.opts.proxy,
                self.opts.tor, self.opts.only, self.opts.exclude)
        apply_preset(self.opts, name)
        (self.opts.min_confidence, self.opts.verbose, self.opts.passive,
         self.opts.nsfw, self.opts.proxy, self.opts.tor, self.opts.only,
         self.opts.exclude) = keep
        self.c.print(f"[green]{name}[/green] — {PRESET_BLURB[name]}")

    def _expand(self) -> None:
        """Turn each loaded name into the handles a person plausibly picks."""
        from .names import candidates

        names = [t for t in self.targets if t.type is IdType.NAME]
        if not names:
            self.c.print("[yellow]No names loaded.[/yellow] Add one first, "
                         "e.g. [cyan]alex rivera[/cyan]")
            return

        added = 0
        for name in names:
            handles = candidates(name.value)
            self.c.print(f"\n[bold]{name.value}[/bold] → "
                         f"{len(handles)} candidate handle(s)")
            for handle in handles:
                ident = Identifier(handle, IdType.USERNAME,
                                   origin=f"guessed from name: {name.value}",
                                   depth=1)
                if any(t.key() == ident.key() for t in self.targets):
                    continue
                self.targets.append(ident)
                added += 1
                self.c.print(f"  [green]+[/green] {handle}")

        self.c.print(
            f"\n[dim]{added} added. These are [bold]guesses[/bold] — a hit "
            "proves the handle exists, not that it is your subject. The "
            "identity check does that separately.[/dim]\n"
        )

    def _drop(self, rest: list[str]) -> None:
        if not rest or rest[0].lower() == "all":
            self.targets.clear()
            self.c.print("[green]cleared[/green]")
            return
        try:
            idx = int(rest[0]) - 1
            removed = self.targets.pop(idx)
        except (ValueError, IndexError):
            self.c.print("[yellow]usage: drop <number from `show`> | drop all[/yellow]")
            return
        self.c.print(f"[green]dropped[/green] {removed.value}")


def start(console, opts: ScanOptions, case: str | None,
          basis: str | None, accepted: bool, outdir: Path | None = None) -> int:
    try:
        auth = require_authorization(
            accepted=accepted, basis=basis, case=case,
            interactive=True, console=console,
        )
    except AuthorizationError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 2
    return Console(console, opts, auth, outdir).run()
