"""omnisint — one command, every OSINT tool you have, one profile."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import PRESET_BLURB, ScanOptions, apply_preset
from .engine import Engine
from .ethics import AuthorizationError, audit, require_authorization
from .models import Identifier, IdType
from .registry import ALL_ADAPTERS, adapter_status
from .report import render_html, render_json, render_markdown, render_terminal

EPILOG = """\
examples:
  omnisint                                      interactive console (start here)
  omnisint scan johndoe                       identify the type, run everything
  omnisint scan john@example.com              email sweep + Gravatar + DNS/WHOIS
  omnisint scan johndoe john@example.com      correlate several identifiers
  omnisint scan johndoe --pivot 1             follow identifiers found en route
  omnisint scan johndoe --deep --html out.html  all sites, HTML dossier
  omnisint tools                              show which backends are installed

Set HIBP_API_KEY to enable breach-exposure lookups.
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="omnisint",
        description="Aggregate maigret, sherlock, holehe, user-scanner and "
                    "native lookups into one correlated profile.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"omnisint {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="run a scan", epilog=EPILOG,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    s.add_argument("targets", nargs="+",
                   help="usernames, emails, domains or phone numbers")
    s.add_argument("--type", choices=[t.value for t in IdType],
                   help="force the identifier type instead of auto-detecting")
    s.add_argument("-S", "--secondary", default="", metavar="TERMS",
                   help="comma-separated context terms (employer, school, city). "
                        "Never searched on their own — matched against what the "
                        "primary identifiers return, to confirm identity.")

    scope = s.add_argument_group("scope")
    scope.add_argument("-q", "--quick", action="store_true",
                       help="top 50 sites — mainstream platforms, fast")
    scope.add_argument("-d", "--deep", action="store_true",
                       help="every site in every database, plus a pivot hop (slow)")
    scope.add_argument("--top-sites", type=int, default=500,
                       help="sites per tool when not using --deep (default 500)")
    scope.add_argument("--pivot", type=int, default=0, metavar="N",
                       help="follow identifiers discovered mid-scan, N hops deep")
    scope.add_argument("--pivot-limit", type=int, default=5,
                       help="max identifiers followed per hop (default 5)")
    scope.add_argument("--nsfw", action="store_true",
                       help="include adult-content sites (off by default)")

    tools = s.add_argument_group("tools")
    tools.add_argument("--only", default="", metavar="A,B",
                       help="run only these adapters")
    tools.add_argument("--exclude", default="", metavar="A,B",
                       help="skip these adapters")
    tools.add_argument("--spiderfoot", action="store_true",
                       help="also run SpiderFoot (DNS, certs, WHOIS; slow)")
    tools.add_argument("--hudson", action="store_true",
                       help="also check infostealer breach exposure (slow)")
    tools.add_argument("--darkweb", action="store_true",
                       help="also search hidden-service indexes (needs Tor; slow)")
    tools.add_argument("--active", action="store_true",
                       help="allow probes the subject could notice, e.g. "
                            "password-recovery flows (passive by default)")

    net = s.add_argument_group("network")
    net.add_argument("--timeout", type=int, default=20,
                     help="per-request timeout in seconds (default 20)")
    net.add_argument("--tool-timeout", type=int, default=900,
                     help="per-tool wall-clock limit in seconds (default 900)")
    net.add_argument("--workers", type=int, default=6,
                     help="adapters to run concurrently (default 6)")
    net.add_argument("--delay", type=float, default=0.0,
                     help="delay between requests where supported")
    net.add_argument("--proxy", help="proxy URL, e.g. socks5://127.0.0.1:1080")
    net.add_argument("--tor", action="store_true", help="route through Tor")

    out = s.add_argument_group("output")
    out.add_argument("--json", metavar="FILE", help="write the full JSON dossier")
    out.add_argument("--html", metavar="FILE", help="write an HTML dossier")
    out.add_argument("--markdown", metavar="FILE", help="write a Markdown dossier")
    out.add_argument("--min-confidence", type=float, default=0.35,
                     help="hide accounts below this confidence (default 0.35)")
    out.add_argument("--show-all", action="store_true",
                     help="show every account regardless of confidence")
    out.add_argument("-v", "--verbose", action="store_true",
                     help="per-site detail, tool errors and the full caveat list")
    out.add_argument("--quiet", action="store_true", help="suppress progress lines")
    out.add_argument("--keep-raw", action="store_true",
                     help="keep each tool's raw output for verification")
    out.add_argument("--dry-run", action="store_true",
                     help="show what would run, then exit")

    eth = s.add_argument_group("authorisation")
    eth.add_argument("--i-have-authorization", action="store_true",
                     help="record that you have a lawful basis for this scan")
    eth.add_argument("--basis", help="what authorises this scan (recorded)")
    eth.add_argument("--case", help="case or engagement reference (recorded)")

    con = sub.add_parser(
        "console", help="interactive console (also the default with no args)")
    con.add_argument("--case", help="case or engagement reference (recorded)")
    con.add_argument("--basis", help="what authorises this session (recorded)")
    con.add_argument("--i-have-authorization", action="store_true",
                     help="skip the interactive confirmation prompt")
    con.add_argument("--reports", metavar="DIR",
                     help="where `export` writes (default ~/omnisint-reports)")
    con.add_argument("-q", "--quick", action="store_true",
                     help="start in quick mode (top 50 sites)")
    con.add_argument("-d", "--deep", action="store_true",
                     help="start in full-database sweep mode")
    con.add_argument("-v", "--verbose", action="store_true",
                     help="start with verbose output on")
    con.add_argument("--timeout", type=int, default=20)
    con.add_argument("--workers", type=int, default=6)

    web = sub.add_parser("web", help="open the local web UI in a browser")
    web.add_argument("--port", type=int, default=8787,
                     help="preferred port (default 8787; tries the next 19)")
    web.add_argument("--host", default="127.0.0.1",
                     help="bind address (loopback only unless you know why)")
    web.add_argument("--no-open", action="store_true",
                     help="print the URL instead of opening a browser")
    web.add_argument("--reports", metavar="DIR",
                     help="where Export writes (default ~/omnisint-reports)")
    web.add_argument("--case", help="case or engagement reference (recorded)")
    web.add_argument("--basis", help="what authorises this session (recorded)")
    web.add_argument("--i-have-authorization", action="store_true",
                     help="skip the interactive confirmation prompt")

    sub.add_parser("tools", help="list backends and whether they are installed")
    sub.add_parser("audit", help="show the local audit log")
    return p


def _console(quiet: bool = False):
    from rich.console import Console
    return Console(stderr=False, quiet=False, highlight=False, soft_wrap=False)


def cmd_tools(console) -> int:
    from rich import box
    from rich.table import Table

    rows = adapter_status()
    t = Table(box=box.SIMPLE_HEAVY, header_style="bold",
              title="Omnisint backends", expand=True)
    t.add_column("Backend", no_wrap=True)
    t.add_column("Status", no_wrap=True)
    t.add_column("Accepts", overflow="fold")
    t.add_column("Trust", justify="right", no_wrap=True)
    t.add_column("What it does", overflow="fold", ratio=3)
    for row in rows:
        if row["available"]:
            status = "[green]ready[/green]"
        elif row["install"] == "built in":
            status = "[yellow]needs key[/yellow]"
        else:
            status = "[red]missing[/red]"
        name = row["name"] + (" [dim](opt-in)[/dim]" if row["opt_in"] else "")
        t.add_row(name, status, ", ".join(row["accepts"]),
                  f"{row['weight']:.2f}" if row["weight"] else "—",
                  row["description"])
    console.print(t)

    missing = [r for r in rows if not r["available"]]
    if not missing:
        console.print("\n[green]Every backend is installed.[/green]\n")
        return 0

    console.print(f"\n[bold]{len(missing)} backend(s) not ready.[/bold] "
                  "[dim]Missing backends are skipped, never fatal.[/dim]\n")
    for row in missing:
        console.print(f"  [bold]{row['name']}[/bold] [dim]— {row['description']}[/dim]")
        if row["install"] and row["install"] != "built in":
            console.print(f"      [cyan]{row['install']}[/cyan]")
        if row["install_note"]:
            console.print(f"      [dim]{row['install_note']}[/dim]")
        if row["homepage"]:
            console.print(f"      [dim]{row['homepage']}[/dim]")
        console.print()

    installable = [r["install"] for r in missing
                   if r["install"] and r["install"] != "built in"]
    if installable:
        pkgs = " ".join(sorted({c.split()[-1] for c in installable}))
        console.print("[bold]Install them all:[/bold]")
        console.print(f"  [cyan]pip install {pkgs}[/cyan]\n")
    return 0


def cmd_audit(console) -> int:
    from .ethics import AUDIT_LOG
    if not AUDIT_LOG.exists():
        console.print("[dim]No audit log yet.[/dim]")
        return 0
    console.print(AUDIT_LOG.read_text().rstrip())
    return 0


def cmd_scan(args, console) -> int:
    try:
        auth = require_authorization(
            accepted=args.i_have_authorization,
            basis=args.basis,
            case=args.case,
            interactive=sys.stdin.isatty(),
            console=console,
        )
    except AuthorizationError as exc:
        console.print(f"[bold red]Refusing to scan:[/bold red] {exc}")
        return 2

    forced = IdType(args.type) if args.type else None
    seeds: list[Identifier] = []
    for raw in args.targets:
        ident = Identifier.parse(raw)
        if forced:
            ident = Identifier(ident.value, forced, "input", 0)
        if ident.type is IdType.UNKNOWN:
            console.print(
                f"[yellow]Skipping[/yellow] {raw!r}: cannot classify it. "
                "Use --type to force one."
            )
            continue
        seeds.append(ident)
    if not seeds:
        console.print("[bold red]No usable targets.[/bold red]")
        return 2

    preset = "quick" if args.quick else ("deep" if args.deep else "standard")
    opts = apply_preset(ScanOptions(), preset)
    # Anything the user typed explicitly overrides the preset.
    defaults = build_parser().parse_args(["scan", "x"])
    if args.tool_timeout != defaults.tool_timeout:
        opts.tool_timeout = args.tool_timeout
    if args.timeout != defaults.timeout:
        opts.request_timeout = args.timeout
    if args.workers != defaults.workers:
        opts.workers = args.workers
    if args.top_sites != defaults.top_sites:
        opts.top_sites = args.top_sites
    _extra = dict(
        pivot_limit=args.pivot_limit,
        passive=not args.active,
        nsfw=args.nsfw,
        proxy=args.proxy,
        tor=args.tor,
        delay=args.delay,
        only={s.strip() for s in args.only.split(",") if s.strip()}
             | ({"darkweb"} if args.darkweb else set())
             | ({"hudsonrock"} if args.hudson else set())
             | ({"spiderfoot"} if args.spiderfoot else set()),
        exclude={s.strip() for s in args.exclude.split(",") if s.strip()},
        min_confidence=args.min_confidence,
        keep_raw=args.keep_raw,
        verbose=args.verbose,
    )
    for key, value in _extra.items():
        setattr(opts, key, value)
    if args.pivot:
        opts.pivot_depth = args.pivot

    # Defined before the audit record below, which references it.
    secondary = [t.strip() for t in args.secondary.split(",") if t.strip()]

    engine = Engine(opts)
    if not engine.adapters:
        console.print("[bold red]No backends available.[/bold red] "
                      "Run [bold]omnisint tools[/bold] to see what is missing.")
        return 3

    plan = engine.plan(seeds)
    if args.dry_run:
        console.print("[bold]Would run:[/bold]")
        for adapter, target in plan:
            console.print(f"  • {adapter} → {target}")
        return 0

    if args.active:
        console.print(
            "[bold yellow]Active mode:[/bold yellow] probes may be visible to "
            "the subject (password-recovery flows). Make sure your "
            "authorisation covers that."
        )

    run_id = audit(
        "scan.start", auth,
        targets=[s.value for s in seeds],
        types=[s.type.value for s in seeds],
        secondary=secondary,
        adapters=sorted({a for a, _ in plan}),
        passive=opts.passive,
        pivot_depth=opts.pivot_depth,
    )

    console.print(
        f"\n[bold cyan]Omnisint[/bold cyan] · run [bold]{run_id}[/bold] · "
        f"{len(plan)} task(s) across {len({a for a, _ in plan})} tool(s) · "
        f"[bold]{opts.preset}[/bold] ({PRESET_BLURB[opts.preset]}) · "
        f"{'passive' if opts.passive else 'ACTIVE'}"
    )

    from rich.progress import (BarColumn, Progress, SpinnerColumn, TextColumn,
                               TimeElapsedColumn)

    profile = None
    if args.quiet:
        profile = engine.scan(seeds, secondary=secondary)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=24),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console, transient=True,
        ) as prog:
            task = prog.add_task("querying sources…", total=len(plan))

            def on_progress(kind: str, message: str) -> None:
                if kind in ("done", "fail"):
                    prog.advance(task)
                    prog.console.print(
                        f"  [{'green' if kind == 'done' else 'red'}]"
                        f"{'✔' if kind == 'done' else '✖'}[/] {message}"
                    )
                else:
                    prog.update(task, description=message)

            engine.progress = on_progress
            profile = engine.scan(seeds, secondary=secondary)

    render_terminal(profile, console, args.min_confidence, args.show_all)

    meta = {
        "run_id": run_id,
        "case": auth.case,
        "operator": auth.operator,
        "basis": auth.basis,
        "version": __version__,
        "passive": opts.passive,
    }
    written = []
    for flag, renderer in (
        (args.json, lambda: render_json(profile, meta)),
        (args.markdown, lambda: render_markdown(profile, meta, args.min_confidence)),
        (args.html, lambda: render_html(profile, meta, args.min_confidence)),
    ):
        if flag:
            path = Path(flag).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(renderer())
            try:
                path.chmod(0o600)  # dossiers are sensitive personal data
            except OSError:
                pass
            written.append(str(path))

    if written:
        console.print("\n[bold]Reports written[/bold] (mode 600):")
        for w in written:
            console.print(f"  • {w}")

    audit(
        "scan.finish", auth,
        run_id=run_id,
        accounts=len(profile.accounts),
        confirmed=sum(1 for a in profile.accounts.values() if a.level == "confirmed"),
        reports=written,
    )
    return 0


def cmd_console(args, console) -> int:
    from .console import start
    preset = ("quick" if getattr(args, "quick", False)
              else "deep" if getattr(args, "deep", False) else "standard")
    opts = apply_preset(ScanOptions(), preset)
    opts.verbose = getattr(args, "verbose", False)
    # The console exists to dump everything; filtering is opt-in there.
    opts.min_confidence = 0.0
    reports = getattr(args, "reports", None)
    return start(
        console, opts,
        case=getattr(args, "case", None),
        basis=getattr(args, "basis", None),
        accepted=getattr(args, "i_have_authorization", False),
        outdir=Path(reports).expanduser() if reports else None,
    )


SUBCOMMANDS = {"scan", "console", "tools", "audit", "web"}


def _default_to_console(argv: list[str]) -> list[str]:
    """`osint` and `osint --case X` mean `osint console …`.

    Without this, argparse reads the console's own flags as a bad subcommand
    name, which is a confusing error for the most common way to start.
    """
    if not argv:
        return ["console"]
    if argv[0] in SUBCOMMANDS:
        return argv
    if argv[0] in ("-h", "--help", "--version"):
        return argv
    return ["console", *argv]


def cmd_web(args, console) -> int:
    from .ethics import AuthorizationError, require_authorization
    from .web.server import serve

    try:
        auth = require_authorization(
            accepted=getattr(args, "i_have_authorization", False),
            basis=getattr(args, "basis", None),
            case=getattr(args, "case", None),
            interactive=sys.stdin.isatty(),
            console=console,
        )
    except AuthorizationError as exc:
        console.print(f"[bold red]{exc}[/bold red]")
        return 2

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        # Binding outward exposes an OSINT console and its results to the
        # network. Refuse rather than make that a one-flag mistake.
        console.print(
            f"[bold red]Refusing to bind {args.host}.[/bold red] The UI has no "
            "login and serves personal data; it is loopback-only by design. "
            "Use an SSH tunnel if you need it elsewhere.")
        return 2

    opts = apply_preset(ScanOptions(), "standard")
    opts.min_confidence = 0.0
    reports = (Path(args.reports).expanduser() if args.reports
               else Path.home() / "omnisint-reports")
    return serve(auth, opts, reports, host=args.host, port=args.port,
                 open_browser=not args.no_open, console=console)


def main(argv: list[str] | None = None) -> int:
    import sys as _sys
    parser = build_parser()
    args = parser.parse_args(_default_to_console(
        list(argv) if argv is not None else _sys.argv[1:]))
    console = _console()
    if args.command is None:
        args.command = "console"
    if args.command == "web":
        try:
            return cmd_web(args, console)
        except KeyboardInterrupt:
            console.print("\n[dim]UI stopped.[/dim]")
            return 0
    if args.command == "console":
        try:
            return cmd_console(args, console)
        except KeyboardInterrupt:
            console.print("\n[dim]bye[/dim]")
            return 0
    if args.command == "tools":
        return cmd_tools(console)
    if args.command == "audit":
        return cmd_audit(console)
    if args.command == "scan":
        try:
            return cmd_scan(args, console)
        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted.[/yellow]")
            return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
