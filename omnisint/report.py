"""Render a Profile for humans and for machines."""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from .correlate import corroborated_names
from .ethics import DISCLAIMER
from .models import Profile

LEVEL_COLOR = {
    "confirmed": "bold green",
    "probable": "yellow",
    "possible": "cyan",
    "weak": "dim",
}
LEVEL_ORDER = ["confirmed", "probable", "possible", "weak"]


def _visible(profile: Profile, min_conf: float):
    return [a for a in profile.sorted_accounts() if a.confidence >= min_conf]


# --------------------------------------------------------------------------
# Terminal
# --------------------------------------------------------------------------
def render_terminal(profile: Profile, console, min_conf: float = 0.35,
                    show_all: bool = False, verbose: bool = False) -> None:
    from rich.panel import Panel
    from rich.table import Table
    from rich import box

    accounts = profile.sorted_accounts() if show_all else _visible(profile, min_conf)
    seeds = ", ".join(f"{s.value} [{s.type.value}]" for s in profile.seeds)

    console.print()
    console.print(Panel(
        f"[bold]Target:[/bold] {seeds}\n"
        f"[bold]Accounts:[/bold] {len(accounts)} shown / {len(profile.accounts)} total   "
        f"[bold]Tools:[/bold] {len({r.adapter for r in profile.runs})}   "
        f"[bold]Generated:[/bold] {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}",
        title="[bold cyan]Omnisint — Consolidated Profile[/bold cyan]",
        border_style="cyan", box=box.ROUNDED,
    ))

    # -- identity ---------------------------------------------------------
    names = corroborated_names(profile)
    if names or profile.locations or profile.bios:
        ident = Table(box=box.SIMPLE, show_header=True, header_style="bold")
        ident.add_column("Attribute", style="bold", no_wrap=True)
        ident.add_column("Value")
        ident.add_column("Seen on", style="dim")

        for name, sources in names[:8]:
            marker = "[green]✔[/green] " if len(sources) > 1 else ""
            ident.add_row("Name", f"{marker}{name}", ", ".join(sources[:6]))
        for loc, sources in sorted(profile.locations.items(),
                                   key=lambda i: -len(i[1]))[:5]:
            ident.add_row("Location", loc, ", ".join(sorted(sources)[:6]))
        for bio, sources in sorted(profile.bios.items(),
                                   key=lambda i: -len(i[1]))[:4]:
            snippet = bio if len(bio) <= 160 else bio[:157] + "…"
            ident.add_row("Bio", snippet, ", ".join(sorted(sources)[:4]))
        for av, sources in list(profile.avatars.items())[:3]:
            ident.add_row("Avatar", av, ", ".join(sorted(sources)[:4]))

        console.print(Panel(ident, title="[bold]Identity attributes[/bold]",
                            border_style="magenta", box=box.ROUNDED))

    # -- identifiers ------------------------------------------------------
    derived = [i for i in profile.identifiers.values() if i.origin != "input"]
    if derived:
        t = Table(box=box.SIMPLE, header_style="bold")
        t.add_column("Identifier"); t.add_column("Type"); t.add_column("Discovered via", style="dim")
        for i in derived[:20]:
            t.add_row(i.value, i.type.value, i.origin)
        console.print(Panel(t, title="[bold]Derived identifiers[/bold]",
                            border_style="blue", box=box.ROUNDED))

    # -- personas ---------------------------------------------------------
    if len(profile.personas) > 1:
        t = Table(box=box.SIMPLE, header_style="bold", expand=True)
        t.add_column("Identity", no_wrap=True, ratio=2)
        t.add_column("Role", no_wrap=True, ratio=2)
        t.add_column("Platforms", overflow="fold", ratio=5)
        for persona in profile.personas[:10]:
            if persona["primary"]:
                tag = "[bold green]primary[/bold green]"
            elif any(x["primary"] for x in profile.personas):
                tag = "[red]likely someone else[/red]"
            else:
                tag = "[yellow]unresolved[/yellow]"
            t.add_row(persona["name"], tag,
                      ", ".join(persona["platforms"][:12]))
        console.print(Panel(
            t,
            title="[bold red]Persona disambiguation[/bold red] "
                  "[dim](one handle, several people)[/dim]",
            subtitle="[dim]a shared username is not a shared identity[/dim]",
            border_style="red", box=box.ROUNDED,
        ))

    # -- accounts ---------------------------------------------------------
    if accounts:
        by_level: dict[str, list] = {}
        for a in accounts:
            by_level.setdefault(a.level, []).append(a)

        table = Table(box=box.SIMPLE_HEAVY, header_style="bold", expand=True,
                      pad_edge=False)
        table.add_column("Exists", justify="right", no_wrap=True, width=6)
        table.add_column("Same?", no_wrap=True, width=9)
        table.add_column("Platform", overflow="ellipsis", ratio=3, min_width=12)
        table.add_column("URL", overflow="fold", ratio=6, min_width=24)
        table.add_column("Sources", overflow="fold", ratio=3, min_width=12)
        table.add_column("Extracted", overflow="fold", ratio=4, min_width=14)

        attr_style = {
            "same person": "green",
            "unknown": "dim",
            "likely different person": "red",
        }
        for level in LEVEL_ORDER:
            for a in by_level.get(level, []):
                meta = ", ".join(
                    f"{k}={str(v)[:28]}" for k, v in list(a.metadata.items())[:2]
                    if k != "avatar"
                )
                srcs = ",".join(sorted(s[:4] for s in a.sources))
                style = LEVEL_COLOR[level]
                astyle = attr_style[a.attribution_level]
                mark = {"same person": "✔", "unknown": "?",
                        "likely different person": "✖"}[a.attribution_level]
                table.add_row(
                    f"[{style}]{a.confidence:.0%}[/{style}]",
                    f"[{astyle}]{mark} {a.attribution:.0%}[/{astyle}]",
                    f"[{style}]{a.platform}[/{style}]",
                    a.url or "—",
                    f"[green]{srcs}[/green]" if len(a.sources) > 1 else f"[dim]{srcs}[/dim]",
                    meta or "—",
                )
        console.print(Panel(
            table,
            title="[bold]Accounts[/bold]",
            subtitle="[dim]Exists = the handle is registered there · "
                     "Same? = evidence it is your subject[/dim]",
            border_style="green", box=box.ROUNDED,
        ))
    else:
        console.print(Panel("No accounts met the confidence threshold.",
                            border_style="yellow"))

    # -- infrastructure ---------------------------------------------------
    if profile.infrastructure:
        t = Table(box=box.SIMPLE, header_style="bold")
        t.add_column("Domain", no_wrap=True); t.add_column("Records", overflow="fold")
        for domain, info in profile.infrastructure.items():
            bits = []
            if info.get("freemail_provider"):
                bits.append("[dim]consumer mail provider[/dim]")
            for k in ("a", "mx", "ns", "spf"):
                if info.get(k):
                    bits.append(f"[bold]{k.upper()}[/bold]: " + ", ".join(info[k][:4]))
            for line in (info.get("whois") or [])[:6]:
                bits.append(f"[dim]{line}[/dim]")
            t.add_row(domain, "\n".join(bits) or "—")
        console.print(Panel(t, title="[bold]Infrastructure[/bold]",
                            border_style="blue", box=box.ROUNDED))

    # -- breaches ---------------------------------------------------------
    if profile.breaches:
        t = Table(box=box.SIMPLE, header_style="bold")
        t.add_column("Source"); t.add_column("Identifier"); t.add_column("Detail", overflow="fold")
        for b in profile.breaches[:25]:
            detail = b.get("name") or str(b.get("detail", ""))[:200]
            if b.get("date"):
                detail += f" ({b['date']})"
            t.add_row(b.get("source", "?"), b.get("identifier", "?"), detail)
        console.print(Panel(
            t,
            title="[bold red]Breach / stealer exposure[/bold red] "
                  "[dim](defensive signal — rotate credentials, enable MFA)[/dim]",
            border_style="red", box=box.ROUNDED,
        ))

    # -- tool runs --------------------------------------------------------
    if profile.runs:
        t = Table(box=box.SIMPLE, header_style="bold")
        for col in ("Tool", "Identifier", "Status", "Hits", "Inconclusive", "Time"):
            t.add_column(col, no_wrap=True)
        for r in sorted(profile.runs, key=lambda r: (-r.found, r.adapter)):
            t.add_row(
                r.adapter, r.identifier,
                "[green]ok[/green]" if r.ok else f"[red]{(r.error or 'failed')[:40]}[/red]",
                str(r.found), str(r.inconclusive), f"{r.duration:.1f}s",
            )
        console.print(Panel(t, title="[bold]Tool coverage[/bold]",
                            border_style="dim", box=box.ROUNDED))

    if verbose and profile.gaps:
        t = Table(box=box.SIMPLE, header_style="bold")
        t.add_column("Tool", no_wrap=True)
        t.add_column("Reason no verdict was reached", overflow="fold")
        t.add_column("Sites", justify="right", no_wrap=True)
        for source, reasons in sorted(profile.gaps.items()):
            for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
                t.add_row(source, reason, str(count))
        console.print(Panel(
            t, title="[bold]Coverage gaps[/bold] [dim](unchecked, not clear)[/dim]",
            border_style="yellow", box=box.ROUNDED))

    if profile.warnings:
        shown = profile.warnings if verbose else profile.warnings[:12]
        extra = len(profile.warnings) - len(shown)
        body = "\n".join(f"• {w}" for w in shown)
        if extra > 0:
            body += (f"\n[dim]…and {extra} more — use [bold]-v[/bold] "
                     "or see the JSON report[/dim]")
        console.print(Panel(body, title="[bold yellow]Caveats[/bold yellow]",
                            border_style="yellow", box=box.ROUNDED))

    console.print(Panel(DISCLAIMER, border_style="red", box=box.ROUNDED,
                        title="[bold red]Handling[/bold red]"))


# --------------------------------------------------------------------------
# Machine / document formats
# --------------------------------------------------------------------------
def render_json(profile: Profile, meta: dict) -> str:
    payload = profile.to_dict()
    payload["report"] = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "disclaimer": DISCLAIMER,
        **meta,
    }
    return json.dumps(payload, indent=2, default=str)


def _md(value) -> str:
    """Escape a value for a Markdown table cell."""
    return (str(value).replace("\\", "\\\\").replace("|", "\\|")
            .replace("\n", " ").replace("\r", " ").strip())


def render_markdown(profile: Profile, meta: dict, min_conf: float = 0.35) -> str:
    seeds = ", ".join(f"`{s.value}` ({s.type.value})" for s in profile.seeds)
    out = [
        "# Omnisint — Consolidated Profile",
        "",
        f"**Target:** {seeds}  ",
        f"**Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}  ",
        f"**Case:** {meta.get('case') or '—'}  ",
        f"**Operator:** {meta.get('operator') or '—'}  ",
        f"**Lawful basis:** {meta.get('basis') or '—'}",
        "",
        f"> {DISCLAIMER}",
        "",
    ]

    names = corroborated_names(profile)
    if names or profile.locations:
        out += ["## Identity attributes", "",
                "| Attribute | Value | Seen on |", "|---|---|---|"]
        for n, s in names[:10]:
            out.append(f"| Name | {_md(n)} | {_md(', '.join(s[:6]))} |")
        for loc, s in sorted(profile.locations.items(), key=lambda i: -len(i[1]))[:6]:
            out.append(f"| Location | {_md(loc)} | {_md(', '.join(sorted(s)[:6]))} |")
        for bio, s in sorted(profile.bios.items(), key=lambda i: -len(i[1]))[:5]:
            out.append(f"| Bio | {_md(bio[:200])} | {_md(', '.join(sorted(s)[:4]))} |")
        out.append("")

    if len(profile.personas) > 1:
        out += ["## Persona disambiguation", "",
                "More than one name appears under this handle. A shared "
                "username is not a shared identity.", "",
                "| Identity | Role | Platforms |", "|---|---|---|"]
        any_primary = any(x["primary"] for x in profile.personas)
        for persona in profile.personas:
            role = ("**primary**" if persona["primary"]
                    else ("likely someone else" if any_primary else "unresolved"))
            out.append(f"| {_md(persona['name'])} | {role} | "
                       f"{_md(', '.join(persona['platforms'][:12]))} |")
        out.append("")

    accounts = _visible(profile, min_conf)
    out += ["## Accounts", "",
            "`Exists` = the handle is registered there. `Same?` = evidence it "
            "belongs to your subject. They are different questions.", "",
            "| Exists | Same? | Platform | URL | Sources | Extracted |",
            "|---|---|---|---|---|---|"]
    for a in accounts:
        meta_s = "; ".join(f"{_md(k)}={_md(v)}"
                           for k, v in list(a.metadata.items())[:3] if k != "avatar")
        out.append(
            f"| {a.confidence:.0%} ({a.level}) | {a.attribution:.0%} "
            f"({a.attribution_level}) | {_md(a.platform)} | "
            f"{_md(a.url) if a.url else '—'} | {_md(', '.join(sorted(a.sources)))} "
            f"| {meta_s or '—'} |"
        )
    out.append("")

    if profile.breaches:
        out += ["## Breach / stealer exposure", ""]
        for b in profile.breaches:
            out.append(f"- **{_md(b.get('source'))}** — {_md(b.get('identifier'))}: "
                       f"{_md(b.get('name') or str(b.get('detail',''))[:200])}")
        out.append("")

    if profile.infrastructure:
        out += ["## Infrastructure", ""]
        for domain, info in profile.infrastructure.items():
            out.append(f"### {domain}")
            for k in ("a", "mx", "ns", "spf"):
                if info.get(k):
                    out.append(f"- **{k.upper()}**: {', '.join(info[k][:6])}")
            for line in (info.get("whois") or [])[:8]:
                out.append(f"- {line}")
            out.append("")

    out += ["## Tool coverage", "",
            "| Tool | Identifier | Status | Hits | Inconclusive | Time |",
            "|---|---|---|---|---|---|"]
    for r in profile.runs:
        out.append(f"| {_md(r.adapter)} | {_md(r.identifier)} | "
                   f"{_md('ok' if r.ok else (r.error or 'failed'))} | {r.found} | "
                   f"{r.inconclusive} | {r.duration:.1f}s |")
    out.append("")

    if profile.warnings:
        out += ["## Caveats", ""] + [f"- {_md(w)}" for w in profile.warnings[:60]] + [""]
    return "\n".join(out)


def render_html(profile: Profile, meta: dict, min_conf: float = 0.35) -> str:
    e = html.escape
    seeds = ", ".join(f"{e(s.value)} <em>({s.type.value})</em>" for s in profile.seeds)
    rows = []
    attr_class = {"same person": "same", "unknown": "unk",
                  "likely different person": "diff"}
    for a in _visible(profile, min_conf):
        meta_s = "; ".join(f"{e(k)}={e(str(v))}"
                           for k, v in list(a.metadata.items())[:4] if k != "avatar")
        url = f'<a href="{e(a.url)}" rel="noreferrer noopener">{e(a.url)}</a>' if a.url else "—"
        rows.append(
            f'<tr class="{a.level}"><td class="c">{a.confidence:.0%}</td>'
            f'<td class="a {attr_class[a.attribution_level]}">{a.attribution:.0%}'
            f'<span class="al">{e(a.attribution_level)}</span></td>'
            f"<td>{e(a.platform)}</td><td>{url}</td>"
            f"<td>{e(', '.join(sorted(a.sources)))}</td><td>{meta_s or '—'}</td></tr>"
        )

    persona_html = ""
    if len(profile.personas) > 1:
        any_primary = any(x["primary"] for x in profile.personas)

        def _role(p):
            if p["primary"]:
                return ("same", "primary")
            return ("diff", "likely someone else") if any_primary else ("unk", "unresolved")

        items = "".join(
            f"<tr><td>{e(p['name'])}</td>"
            f'<td class="{_role(p)[0]}">{_role(p)[1]}</td>'
            f"<td>{e(', '.join(p['platforms'][:14]))}</td></tr>"
            for p in profile.personas
        )
        persona_html = (
            "<h2>Persona disambiguation</h2>"
            "<p class=\"meta\">More than one name appears under this handle. "
            "A shared username is not a shared identity.</p>"
            "<div class='wrap'><table><tr><th>Identity</th><th>Role</th>"
            f"<th>Platforms</th></tr>{items}</table></div>"
        )

    ident_rows = "".join(
        f"<tr><td>Name</td><td>{e(n)}</td><td>{e(', '.join(s))}</td></tr>"
        for n, s in corroborated_names(profile)[:10]
    ) + "".join(
        f"<tr><td>Location</td><td>{e(loc)}</td><td>{e(', '.join(sorted(s)))}</td></tr>"
        for loc, s in sorted(profile.locations.items(), key=lambda i: -len(i[1]))[:6]
    )

    breach_html = ""
    if profile.breaches:
        items = "".join(
            f"<li><strong>{e(str(b.get('source')))}</strong> — {e(str(b.get('identifier')))}: "
            f"{e(str(b.get('name') or str(b.get('detail',''))[:200]))}</li>"
            for b in profile.breaches
        )
        breach_html = f"<h2>Breach / stealer exposure</h2><ul class='breach'>{items}</ul>"

    warn_html = ""
    if profile.warnings:
        items = "".join(f"<li>{e(w)}</li>" for w in profile.warnings[:60])
        warn_html = f"<h2>Caveats</h2><ul class='warn'>{items}</ul>"

    from .brand import svg_logo
    return f"""<!doctype html><meta charset="utf-8">
<title>Omnisint — {e(', '.join(s.value for s in profile.seeds))}</title>
<style>
:root{{--bg:#fff;--fg:#14161a;--mut:#5b6472;--line:#e4e7ec;--card:#f7f8fa}}
@media(prefers-color-scheme:dark){{:root{{--bg:#0f1115;--fg:#e6e9ef;--mut:#98a2b3;--line:#242833;--card:#161923}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif;margin:0;padding:2.5rem 1.25rem;max-width:1100px;margin-inline:auto}}
h1{{font-size:1.6rem;margin:0 0 .3rem}} h2{{font-size:1.1rem;margin:2rem 0 .6rem;border-bottom:1px solid var(--line);padding-bottom:.35rem}}
.meta{{color:var(--mut);font-size:.9rem}}
.note{{background:var(--card);border-left:3px solid #d92d20;padding:.8rem 1rem;border-radius:6px;margin:1.25rem 0;color:var(--mut);font-size:.9rem}}
table{{width:100%;border-collapse:collapse;font-size:.88rem}}
th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line);vertical-align:top;word-break:break-word}}
th{{color:var(--mut);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}}
td.c{{font-variant-numeric:tabular-nums;font-weight:700}}
tr.confirmed td.c{{color:#12805c}} tr.probable td.c{{color:#b25e09}} tr.possible td.c{{color:#175cd3}} tr.weak td.c{{color:var(--mut)}}
td.a{{font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}}
td.a .al{{display:block;font-weight:400;font-size:.72rem;color:var(--mut)}}
.same,td.a.same{{color:#12805c}} .diff,td.a.diff{{color:#b42318}} .unk,td.a.unk{{color:var(--mut)}}
a{{color:#175cd3}} ul.breach li{{color:#b42318}} ul.warn li{{color:var(--mut);font-size:.88rem}}
.wrap{{overflow-x:auto}}
.brand{{margin:0 0 1.25rem}} .brand svg{{display:block;max-width:100%;height:auto}}
h1{{font-size:1.35rem;color:var(--mut);font-weight:600;letter-spacing:.01em}}
</style>
<header class="brand">{svg_logo(38)}</header>
<h1>Consolidated Profile</h1>
<p class="meta">Target: {seeds}<br>Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}
 · Case {e(str(meta.get('case') or '—'))} · Operator {e(str(meta.get('operator') or '—'))}</p>
<div class="note">{e(DISCLAIMER)}</div>
<h2>Identity attributes</h2>
<div class="wrap"><table><tr><th>Attribute</th><th>Value</th><th>Seen on</th></tr>
{ident_rows or '<tr><td colspan=3>None extracted.</td></tr>'}</table></div>
{persona_html}
<h2>Accounts</h2>
<p class="meta"><strong>Exists</strong> = the handle is registered there.
<strong>Same person?</strong> = evidence it belongs to your subject. These are
different questions; a high existence score is not an identification.</p>
<div class="wrap"><table>
<tr><th>Exists</th><th>Same person?</th><th>Platform</th><th>URL</th><th>Sources</th><th>Extracted data</th></tr>
{''.join(rows) or '<tr><td colspan=6>No accounts above threshold.</td></tr>'}
</table></div>
{breach_html}
{warn_html}
"""


def render_dump(profile: Profile, console) -> None:
    """Print every scrap of data collected, nothing truncated.

    `render_terminal` is the summary you read; this is the appendix you grep.
    Anything a tool handed back that survived parsing shows up here, so a
    field we did not think to surface in the summary is still recoverable
    without digging through the JSON.
    """
    from rich.panel import Panel
    from rich import box

    detailed = [a for a in profile.sorted_accounts() if a.metadata or a.avatar]
    if detailed:
        lines = []
        for a in detailed:
            attr = {"same person": "green", "unknown": "yellow",
                    "likely different person": "red"}[a.attribution_level]
            lines.append(
                f"[bold]{a.platform}[/bold]  "
                f"[{LEVEL_COLOR[a.level]}]exists {a.confidence:.0%}[/{LEVEL_COLOR[a.level]}] · "
                f"[{attr}]same {a.attribution:.0%}[/{attr}] · "
                f"[dim]{', '.join(sorted(a.sources))}[/dim]"
            )
            if a.url:
                lines.append(f"    [blue]{a.url}[/blue]")
            if a.persona:
                lines.append(f"    [dim]identity:[/dim] {a.persona}"
                             f" [dim]({a.persona_note})[/dim]")
            for k, v in sorted(a.metadata.items()):
                text = str(v)
                if len(text) > 110:
                    # Signed CDN URLs run to hundreds of characters and would
                    # bury everything else. Full value stays in the JSON.
                    text = text[:107] + "…"
                lines.append(f"    [dim]{k}:[/dim] {text}")
            lines.append("")
        console.print(Panel("\n".join(lines).rstrip(),
                            title="[bold]Full data dump[/bold] "
                                  "[dim](every field returned)[/dim]",
                            border_style="cyan", box=box.ROUNDED))

    bare = [a for a in profile.sorted_accounts() if not a.metadata and not a.avatar]
    if bare:
        body = "\n".join(
            f"[dim]{a.confidence:>4.0%}[/dim]  {a.platform:<22} {a.url or '—'}"
            for a in bare
        )
        console.print(Panel(
            body,
            title=f"[bold]Hits with no extractable data[/bold] [dim]({len(bare)})[/dim]",
            subtitle="[dim]existence only — nothing ties these to a person[/dim]",
            border_style="dim", box=box.ROUNDED,
        ))
