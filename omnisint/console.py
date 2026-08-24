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

    [cyan]michael silverstein, mjs, mjs@example.com, +14155550100[/cyan]

[bold]Secondary[/bold] — things you know [italic]about[/italic] them: employer, school,
city, band. These are [bold]never searched[/bold]. They are matched against what the
primaries bring back, which is faster and far more reliable than
searching "Acme Corp" across 3000 sites:

    [cyan]sec Acme Corp, MIT, Portland[/cyan]

An account whose bio names your employer is your subject. That beats any
amount of username matching.

[bold]Commands[/bold]
  [cyan]scan[/cyan] / [cyan]go[/cyan]        run against everything collected so far
  [cyan]sec <terms>[/cyan]     add secondary terms (cross-checked, never searched)
  [cyan]show[/cyan]            list everything currently loaded
  [cyan]drop <n|all>[/cyan]    remove one identifier, or clear the list
  [cyan]expand[/cyan]          turn loaded names into likely handles to search

[bold]Depth[/bold]
  [cyan]-q[/cyan] / [cyan]quick[/cyan]      top 50 sites — mainstream platforms, back in seconds
  [cyan]-s[/cyan] / [cyan]standard[/cyan]   top 500 sites per tool (default)
  [cyan]-d[/cyan] / [cyan]deep[/cyan]       every site in every database, plus a pivot hop (slow)
  [cyan]-v[/cyan] / [cyan]verbose[/cyan]    toggle per-site detail and full caveats
  [cyan]pivot <n>[/cyan]       follow identifiers discovered mid-scan, n hops
  [cyan]set <opt> <v>[/cyan]   timeout, workers, top-sites, min-confidence
  [cyan]opts[/cyan]            show current settings
  [cyan]tools[/cyan]           which backends are installed
  [cyan]view[/cyan] / [cyan]last[/cyan]     reopen the last report in the browser
  [cyan]export [dir][/cyan]    write JSON + HTML + Markdown (never automatic)
  [cyan]help[/cyan]  ·  [cyan]quit[/cyan]
"""

_NAME_WORD = re.compile(r"^[A-Za-z][A-Za-z'\u2019-]{1,}$")


def _looks_like_one_name(tokens: list[str]) -> bool:
    """True when a space-separated line reads as a single person's name."""
    return (2 <= len(tokens) <= 4
            and all(_NAME_WORD.match(t) for t in tokens))


_COMMANDS = {"scan", "go", "run", "show", "drop", "deep", "pivot", "set",
             "opts", "options", "tools", "last", "save", "help", "?", "quit",
             "exit", "q", "clear", "expand", "quick", "standard", "verbose",
             "-q", "-d", "-v", "-s", "export", "view", "sec", "secondary",
             "+"}


class Console:
    def __init__(self, console, opts: ScanOptions, auth, outdir: Path | None = None):
        self.c = console
        self.opts = opts
        self.auth = auth
        self.targets: list[Identifier] = []
        self.secondary: list[str] = []
        self.last = None
        self.last_meta: dict = {}
        self.outdir = outdir or (Path.home() / "omnisint-reports")

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def split_input(raw: str) -> list[str]:
        """Split a line into identifiers.

        If the line has commas, the comma is the separator and nothing else
        is — so `michael silverstein, jdoe` is a name and a handle, not three
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
            # `michael silverstein` is a person, not two handles. Anything
            # with a comma, a digit, an @ or a dot escapes this branch, and
            # a comma always forces the split explicitly.
            return [" ".join(tokens)]
        return tokens

    def _classify(self, raw: str) -> None:
        added, skipped = [], []
        for piece in self.split_input(raw):
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
            profile = engine.scan(self.targets, secondary=self.secondary)

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
        self.c.print("[dim]type [cyan]view[/cyan] to reopen the report, "
                     "[cyan]export[/cyan] to write it to disk[/dim]")

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
        base = outdir / f"{slug}-{stamp}"

        written = []
        for suffix, text in (
            (".json", render_json(self.last, self.last_meta)),
            (".html", render_html(self.last, self.last_meta, 0.0)),
            (".md", render_markdown(self.last, self.last_meta, 0.0)),
        ):
            path = base.with_suffix(suffix)
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
            except (EOFError, KeyboardInterrupt):
                self.c.print("\n[dim]bye[/dim]")
                return 0
            if not raw:
                # Bare Enter is the natural "go" once something is loaded.
                if self.targets:
                    self._scan()
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
                    self.opts.pivot_depth = int(rest[0]) if rest else (
                        0 if self.opts.pivot_depth else 1)
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
            except KeyboardInterrupt:
                self.c.print("\n[yellow]interrupted — back to prompt[/yellow]")
            except Exception as exc:
                # One bad command must never drop the operator's session.
                self.c.print(f"[red]{type(exc).__name__}: {exc}[/red]")

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
                         "e.g. [cyan]michael silverstein[/cyan]")
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
