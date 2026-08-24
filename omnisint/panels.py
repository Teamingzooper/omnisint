"""Report sections as reusable rich renderables.

Both the one-shot terminal report and the interactive viewer draw from these,
so a section looks identical however you reach it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from rich import box
from rich.panel import Panel
from rich.table import Table

from .correlate import corroborated_names
from .ethics import DISCLAIMER
from .models import Profile

LEVEL_COLOR = {
    "confirmed": "bold green", "probable": "yellow",
    "possible": "cyan", "weak": "dim",
}
LEVEL_ORDER = ["confirmed", "probable", "possible", "weak"]
ATTR_STYLE = {"same person": "green", "unknown": "yellow",
              "likely different person": "red"}
ATTR_MARK = {"same person": "✔", "unknown": "?", "likely different person": "✖"}


def visible(profile: Profile, min_conf: float, show_all: bool = False):
    accounts = profile.sorted_accounts()
    return accounts if show_all else [a for a in accounts if a.confidence >= min_conf]


# --------------------------------------------------------------------------
def overview(profile: Profile) -> Panel:
    seeds = ", ".join(f"{s.value} [dim]({s.type.value})[/dim]" for s in profile.seeds)
    accounts = profile.sorted_accounts()
    confirmed = sum(1 for a in accounts if a.level == "confirmed")
    same = sum(1 for a in accounts if a.attribution_level == "same person")
    diff = sum(1 for a in accounts if a.attribution_level == "likely different person")

    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold", justify="right")
    t.add_column()
    t.add_row("Target", seeds)
    t.add_row("Generated", f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    t.add_row("Accounts", f"{len(accounts)} total · "
                          f"[bold green]{confirmed}[/bold green] confirmed to exist")
    t.add_row("Attribution", f"[green]{same} likely your subject[/green] · "
                             f"[red]{diff} likely other people[/red] · "
                             f"[yellow]{len(accounts) - same - diff} unresolved[/yellow]")
    t.add_row("Identities", f"{len(profile.personas)} distinct name(s) under these identifiers")
    if profile.secondary:
        matched = sum(1 for a in accounts if a.corroborated)
        t.add_row("Secondary", ", ".join(profile.secondary) +
                  f"  [bold magenta]→ matched {matched} account(s)[/bold magenta]")
    t.add_row("Tools", f"{len({r.adapter for r in profile.runs})} ran · "
                       f"{sum(1 for r in profile.runs if not r.ok)} failed")
    return Panel(t, title="[bold cyan]Consolidated Profile[/bold cyan]",
                 border_style="cyan", box=box.ROUNDED)


def tool_coverage(profile: Profile) -> Panel:
    t = Table(box=box.SIMPLE, header_style="bold", expand=True)
    for col, kw in (("Tool", {"no_wrap": True}), ("Identifier", {"overflow": "fold"}),
                    ("Status", {"overflow": "fold"}), ("Hits", {"justify": "right"}),
                    ("No verdict", {"justify": "right"}), ("Time", {"justify": "right"})):
        t.add_column(col, **kw)
    for r in sorted(profile.runs, key=lambda r: (-r.found, r.adapter)):
        t.add_row(r.adapter, r.identifier,
                  "[green]ok[/green]" if r.ok else f"[red]{(r.error or 'failed')[:44]}[/red]",
                  str(r.found), str(r.inconclusive), f"{r.duration:.1f}s")
    return Panel(t, title="[bold]Tool coverage[/bold]", border_style="dim",
                 box=box.ROUNDED)


def identity(profile: Profile) -> Panel:
    t = Table(box=box.SIMPLE, header_style="bold", expand=True)
    t.add_column("Attribute", style="bold", no_wrap=True, width=10)
    t.add_column("Value", overflow="fold", ratio=5)
    t.add_column("Seen on", style="dim", overflow="fold", ratio=4)

    names = corroborated_names(profile)
    if not (names or profile.locations or profile.bios or profile.avatars):
        return Panel("[dim]No identity attributes were extracted.[/dim]",
                     title="[bold]Identity attributes[/bold]",
                     border_style="magenta", box=box.ROUNDED)
    for name, sources in names:
        mark = "[green]✔[/green] " if len(sources) > 1 else "  "
        t.add_row("Name", f"{mark}{name}", ", ".join(sources))
    for loc, sources in sorted(profile.locations.items(), key=lambda i: -len(i[1])):
        t.add_row("Location", loc, ", ".join(sorted(sources)))
    for bio, sources in sorted(profile.bios.items(), key=lambda i: -len(i[1])):
        t.add_row("Bio", bio, ", ".join(sorted(sources)))
    for av, sources in profile.avatars.items():
        t.add_row("Avatar", av, ", ".join(sorted(sources)))
    return Panel(t, title="[bold]Identity attributes[/bold] "
                          "[dim](✔ = seen on more than one platform)[/dim]",
                 border_style="magenta", box=box.ROUNDED)


def personas(profile: Profile) -> Panel:
    if not profile.personas:
        return Panel("[dim]No named identities were extracted, so there is "
                     "nothing to disambiguate.[/dim]",
                     title="[bold]Persona disambiguation[/bold]",
                     border_style="red", box=box.ROUNDED)
    any_primary = any(p["primary"] for p in profile.personas)
    t = Table(box=box.SIMPLE, header_style="bold", expand=True)
    t.add_column("Identity", no_wrap=True, ratio=3)
    t.add_column("Assessment", no_wrap=True, ratio=3)
    t.add_column("Platforms", overflow="fold", ratio=7)
    for p in profile.personas:
        if p["primary"]:
            tag = "[bold green]primary — your subject[/bold green]"
        elif any_primary:
            tag = "[red]likely someone else[/red]"
        else:
            tag = "[yellow]unresolved[/yellow]"
        t.add_row(p["name"], tag, ", ".join(p["platforms"]))
    sub = ("[dim]a shared username is not a shared identity[/dim]"
           if any_primary else
           "[yellow]no name is better corroborated than the others — "
           "add a name or widen the scan[/yellow]")
    return Panel(t, title="[bold red]Persona disambiguation[/bold red]",
                 subtitle=sub, border_style="red", box=box.ROUNDED)


def accounts(profile: Profile, min_conf: float = 0.0,
             show_all: bool = True) -> Panel:
    rows = visible(profile, min_conf, show_all)
    if not rows:
        return Panel("[dim]No accounts met the confidence threshold.[/dim]",
                     title="[bold]Accounts[/bold]", border_style="green",
                     box=box.ROUNDED)
    t = Table(box=box.SIMPLE_HEAVY, header_style="bold", expand=True, pad_edge=False)
    t.add_column("Exists", justify="right", no_wrap=True, width=6)
    t.add_column("Same?", no_wrap=True, width=8)
    t.add_column("Platform", overflow="ellipsis", ratio=3, min_width=12)
    t.add_column("URL", overflow="fold", ratio=6, min_width=24)
    t.add_column("Sources", overflow="fold", ratio=3, min_width=11)
    t.add_column("Extracted", overflow="fold", ratio=4, min_width=14)

    by_level: dict[str, list] = {}
    for a in rows:
        by_level.setdefault(a.level, []).append(a)
    for level in LEVEL_ORDER:
        for a in by_level.get(level, []):
            meta = ", ".join(f"{k}={str(v)[:26]}"
                             for k, v in list(a.metadata.items())[:2] if k != "avatar")
            if a.corroborated:
                meta = (f"[bold magenta]± {', '.join(a.corroborated)}[/bold magenta]"
                        + (f" · {meta}" if meta else ""))
            srcs = ",".join(sorted(s[:4] for s in a.sources))
            style, astyle = LEVEL_COLOR[level], ATTR_STYLE[a.attribution_level]
            t.add_row(
                f"[{style}]{a.confidence:.0%}[/{style}]",
                f"[{astyle}]{ATTR_MARK[a.attribution_level]} {a.attribution:.0%}[/{astyle}]",
                f"[{style}]{a.platform}[/{style}]", a.url or "—",
                f"[green]{srcs}[/green]" if len(a.sources) > 1 else f"[dim]{srcs}[/dim]",
                meta or "—",
            )
    return Panel(t, title=f"[bold]Accounts[/bold] [dim]({len(rows)})[/dim]",
                 subtitle="[dim]Exists = handle is registered · "
                          "Same? = evidence it is your subject · "
                          "± = matched a secondary term[/dim]",
                 border_style="green", box=box.ROUNDED)


def details(profile: Profile) -> Panel:
    detailed = [a for a in profile.sorted_accounts() if a.metadata or a.avatar]
    if not detailed:
        return Panel("[dim]No account returned extractable profile data.[/dim]",
                     title="[bold]Full data[/bold]", border_style="cyan",
                     box=box.ROUNDED)
    lines = []
    for a in detailed:
        astyle = ATTR_STYLE[a.attribution_level]
        lines.append(
            f"[bold]{a.platform}[/bold]  "
            f"[{LEVEL_COLOR[a.level]}]exists {a.confidence:.0%}[/{LEVEL_COLOR[a.level]}] · "
            f"[{astyle}]same {a.attribution:.0%}[/{astyle}] · "
            f"[dim]{', '.join(sorted(a.sources))}[/dim]")
        if a.url:
            lines.append(f"    [blue]{a.url}[/blue]")
        if a.corroborated:
            lines.append(f"    [bold magenta]± corroborated by: "
                         f"{', '.join(a.corroborated)}[/bold magenta]")
        if a.persona:
            lines.append(f"    [dim]identity:[/dim] {a.persona} [dim]({a.persona_note})[/dim]")
        for k, v in sorted(a.metadata.items()):
            text = str(v)
            if len(text) > 110:
                text = text[:107] + "…"
            lines.append(f"    [dim]{k}:[/dim] {text}")
        lines.append("")
    return Panel("\n".join(lines).rstrip(),
                 title="[bold]Full data[/bold] [dim](every field returned)[/dim]",
                 border_style="cyan", box=box.ROUNDED)


def bare_hits(profile: Profile) -> Panel | None:
    bare = [a for a in profile.sorted_accounts() if not a.metadata and not a.avatar]
    if not bare:
        return None
    body = "\n".join(f"[dim]{a.confidence:>4.0%}[/dim]  {a.platform:<22} {a.url or '—'}"
                     for a in bare)
    return Panel(body, title=f"[bold]Existence-only hits[/bold] [dim]({len(bare)})[/dim]",
                 subtitle="[dim]nothing here ties these to a person[/dim]",
                 border_style="dim", box=box.ROUNDED)


def infrastructure(profile: Profile) -> Panel:
    parts = []
    if profile.infrastructure:
        t = Table(box=box.SIMPLE, header_style="bold", expand=True)
        t.add_column("Domain", no_wrap=True); t.add_column("Records", overflow="fold")
        for domain, info in profile.infrastructure.items():
            bits = []
            if info.get("freemail_provider"):
                bits.append("[dim]consumer mail provider[/dim]")
            for k in ("a", "mx", "ns", "spf"):
                if info.get(k):
                    bits.append(f"[bold]{k.upper()}[/bold]: " + ", ".join(info[k][:5]))
            for line in (info.get("whois") or [])[:8]:
                bits.append(f"[dim]{line}[/dim]")
            t.add_row(domain, "\n".join(bits) or "—")
        parts.append(t)

    phones = getattr(profile, "phones", None) or {}
    if phones:
        t = Table(box=box.SIMPLE, header_style="bold", expand=True)
        t.add_column("Number", no_wrap=True); t.add_column("Detail", overflow="fold")
        for num, info in phones.items():
            t.add_row(num, " · ".join(
                f"[bold]{k}[/bold]: {v}" for k, v in info.items()
                if k in ("region", "location", "carrier", "line_type", "valid")))
        parts.append(t)

    if not parts:
        return Panel("[dim]No domain or phone context was gathered.[/dim]",
                     title="[bold]Infrastructure[/bold]", border_style="blue",
                     box=box.ROUNDED)
    from rich.console import Group
    return Panel(Group(*parts), title="[bold]Infrastructure[/bold]",
                 border_style="blue", box=box.ROUNDED)


def breaches(profile: Profile) -> Panel:
    if not profile.breaches:
        return Panel("[dim]No breach or stealer-log exposure found.[/dim] "
                     "[dim](set HIBP_API_KEY for breach coverage)[/dim]",
                     title="[bold]Breach exposure[/bold]", border_style="red",
                     box=box.ROUNDED)
    t = Table(box=box.SIMPLE, header_style="bold", expand=True)
    t.add_column("Source"); t.add_column("Identifier"); t.add_column("Detail", overflow="fold")
    for b in profile.breaches:
        detail = b.get("name") or str(b.get("detail", ""))[:300]
        if b.get("date"):
            detail += f" ({b['date']})"
        t.add_row(str(b.get("source", "?")), str(b.get("identifier", "?")), detail)
    return Panel(t, title="[bold red]Breach / stealer exposure[/bold red]",
                 subtitle="[dim]defensive signal — rotate credentials, enable MFA[/dim]",
                 border_style="red", box=box.ROUNDED)


def caveats(profile: Profile) -> Panel:
    parts = []
    if profile.warnings:
        parts.append("\n".join(f"• {w}" for w in profile.warnings))
    if profile.gaps:
        t = Table(box=box.SIMPLE, header_style="bold", expand=True)
        t.add_column("Tool", no_wrap=True)
        t.add_column("Why no verdict", overflow="fold")
        t.add_column("Sites", justify="right", no_wrap=True)
        for source, reasons in sorted(profile.gaps.items()):
            for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
                t.add_row(source, reason, str(count))
        parts.append(t)
    if not parts:
        return Panel("[dim]No caveats recorded.[/dim]", title="[bold]Caveats[/bold]",
                     border_style="yellow", box=box.ROUNDED)
    from rich.console import Group
    return Panel(Group(*parts), title="[bold yellow]Caveats[/bold yellow]",
                 subtitle="[dim]unchecked is not the same as clear[/dim]",
                 border_style="yellow", box=box.ROUNDED)


def handling() -> Panel:
    return Panel(DISCLAIMER, title="[bold red]Handling[/bold red]",
                 border_style="red", box=box.ROUNDED)
