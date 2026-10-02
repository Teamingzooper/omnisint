"""Local web UI for Omnisint.

A stdlib-only HTTP server on 127.0.0.1 that drives the same engine as the
console. No new dependencies, no external assets.

Security posture, because this is a tool that reads personal data:

* Bound to the loopback interface only — never 0.0.0.0.
* Every request carries a random per-process token. Any page in your browser
  can send a request to localhost; the token is what stops an unrelated tab
  from starting scans or reading results off this server.
* The authorisation gate and audit log are the console's, unchanged. Opening
  a browser does not opt you out of either.
* Results live in memory for the life of the process and are written to disk
  only when you ask.
"""
from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .. import __version__
from ..config import PRESETS, ScanOptions, apply_preset
from ..console import Console as ConsoleApp
from ..engine import Engine
from ..ethics import audit
from ..models import Identifier, IdType
from ..registry import adapter_status
from ..report import render_html, render_json, render_markdown

STATIC = Path(__file__).parent / "static"


class Run:
    """One scan, its live progress, and its result."""

    def __init__(self, run_id: str, targets, secondary, preset: str):
        self.id = run_id
        self.targets = targets
        self.secondary = secondary
        self.preset = preset
        self.started = time.time()
        self.finished: float | None = None
        self.state = "running"          # running | done | failed | cancelled
        self.events: list[dict] = []
        self.profile = None
        self.pinned: list[dict] = []
        self.error: str | None = None
        self.lock = threading.Lock()

    def log(self, kind: str, message: str) -> None:
        with self.lock:
            self.events.append(
                {"kind": kind, "message": message, "t": time.time() - self.started})

    def snapshot(self, include_profile: bool = False) -> dict:
        with self.lock:
            data = {
                "id": self.id,
                "state": self.state,
                "preset": self.preset,
                "targets": [{"value": t.value, "type": t.type.value} for t in self.targets],
                "secondary": list(self.secondary),
                "pinned": list(self.pinned),
                "started": self.started,
                "elapsed": (self.finished or time.time()) - self.started,
                "events": list(self.events),
                "error": self.error,
            }
        if include_profile and self.profile is not None:
            data["profile"] = self.profile.to_dict()
        return data


class State:
    def __init__(self, auth, opts: ScanOptions, outdir: Path):
        self.auth = auth
        self.opts = opts
        self.outdir = outdir
        self.runs: dict[str, Run] = {}
        self.order: list[str] = []
        self.lock = threading.Lock()

    @staticmethod
    def anchors_from_pins(pinned: list[dict]) -> tuple[list[str], list[str]]:
        """Turn confirmed accounts into things worth searching and matching.

        A confirmed account is the richest anchor an operator can give us:
        its handle becomes a target in its own right, its name anchors
        persona clustering, and its employer/school/location become
        cross-checks. This is what makes "stack these, then rescan" better
        than simply re-running the same query.
        """
        seeds, terms = [], []
        for pin in pinned:
            for key in ("username", "handle", "login"):
                v = str(pin.get(key) or "").strip()
                if v and v not in seeds:
                    seeds.append(v)
            name = str(pin.get("fullname") or "").strip()
            if name and name not in seeds:
                seeds.append(name)
            for t in (pin.get("terms") or []):
                t = str(t).strip()
                if t and t not in terms:
                    terms.append(t)
        return seeds, terms

    def start(self, raw_targets: list[str], secondary: list[str],
              preset: str, extra: dict, pinned: list[dict] | None = None) -> Run:
        pinned = pinned or []
        pin_seeds, pin_terms = self.anchors_from_pins(pinned)
        raw_targets = list(raw_targets) + [s for s in pin_seeds if s not in raw_targets]
        secondary = list(secondary) + [t for t in pin_terms if t not in secondary]

        seeds, skipped = [], []
        for raw in raw_targets:
            ident = Identifier.parse(raw)
            if ident.type is IdType.UNKNOWN:
                skipped.append(raw)
                continue
            seeds.append(ident)
        if not seeds:
            raise ValueError(
                "No usable identifiers. " +
                (f"Could not classify: {', '.join(skipped)}" if skipped else ""))

        opts = apply_preset(ScanOptions(), preset if preset in PRESETS else "standard")
        opts.min_confidence = 0.0
        for key in ("nsfw", "passive", "pivot_depth", "verbose"):
            if key in extra:
                setattr(opts, key, extra[key])
        only = set()
        if extra.get("hudson"):
            only.add("hudsonrock")
        if extra.get("darkweb"):
            only.add("darkweb")
        opts.only = only

        run_id = secrets.token_hex(6)
        run = Run(run_id, seeds, secondary, opts.preset)
        run.pinned = pinned
        with self.lock:
            self.runs[run_id] = run
            self.order.insert(0, run_id)

        audit("web.scan", self.auth, run_id=run_id,
              targets=[s.value for s in seeds], secondary=secondary,
              preset=opts.preset, passive=opts.passive,
              confirmed_accounts=[p.get("url") or p.get("platform") for p in pinned])

        def work():
            try:
                engine = Engine(opts, progress=run.log)
                run.profile = engine.scan(seeds, secondary=secondary,
                                          pinned=pinned)
                run.state = "done"
            except Exception as exc:                      # noqa: BLE001
                run.state = "failed"
                run.error = f"{type(exc).__name__}: {exc}"
            finally:
                run.finished = time.time()
                audit("web.scan.finish", self.auth, run_id=run_id,
                      state=run.state,
                      accounts=len(run.profile.accounts) if run.profile else 0)

        threading.Thread(target=work, daemon=True, name=f"scan-{run_id}").start()
        if skipped:
            run.log("warn", f"ignored (could not classify): {', '.join(skipped)}")
        return run

    def export(self, run: Run) -> list[str]:
        if run.profile is None:
            raise ValueError("nothing to export yet")
        self.outdir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        slug = "_".join(
            "".join(c for c in t.value if c.isalnum() or c in "-_.@")[:40]
            for t in run.profile.seeds[:3]) or "scan"
        meta = {"run_id": run.id, "case": self.auth.case,
                "operator": self.auth.operator, "basis": self.auth.basis,
                "version": __version__, "passive": True}
        written = []
        for suffix, text in ((".json", render_json(run.profile, meta)),
                             (".html", render_html(run.profile, meta, 0.0)),
                             (".md", render_markdown(run.profile, meta, 0.0))):
            path = self.outdir / (f"{slug}-{stamp}" + suffix)
            path.write_text(text)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            written.append(str(path))
        audit("web.export", self.auth, run_id=run.id, files=written)
        return written


def make_handler(state: State, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"Omnisint/{__version__}"
        protocol_version = "HTTP/1.1"

        # -- plumbing -------------------------------------------------------
        def log_message(self, *_args):
            pass  # the audit log is the record; stdout is the operator's

        def _send(self, code, body: bytes, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # This server holds personal data; keep it out of caches and out
            # of other origins' reach.
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; img-src 'self' data:; style-src 'self'; "
                "script-src 'self'; connect-src 'self'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=HTTPStatus.OK):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _fail(self, code, message):
            self._json({"error": message}, code)

        def _authorised(self, query) -> bool:
            supplied = (self.headers.get("X-Omnisint-Token")
                        or (query.get("t", [""])[0]))
            return secrets.compare_digest(supplied or "", token)

        # -- routing --------------------------------------------------------
        def do_GET(self):
            url = urlparse(self.path)
            query = parse_qs(url.query)
            path = url.path

            if path in ("/", "/index.html"):
                if not self._authorised(query):
                    return self._send(HTTPStatus.FORBIDDEN,
                                      b"Missing or bad token. Start the UI with "
                                      b"`omni web` and use the URL it prints.",
                                      "text/plain; charset=utf-8")
                return self._static("index.html")

            if path.startswith("/static/"):
                return self._static(path[len("/static/"):])

            if not self._authorised(query):
                return self._fail(HTTPStatus.FORBIDDEN, "bad token")

            if path == "/api/meta":
                return self._json({
                    "version": __version__,
                    "case": state.auth.case,
                    "operator": state.auth.operator,
                    "presets": list(PRESETS),
                    "reports_dir": str(state.outdir),
                })
            if path == "/api/tools":
                return self._json({"backends": adapter_status()})
            if path == "/api/runs":
                with state.lock:
                    runs = [state.runs[r].snapshot() for r in state.order[:50]]
                return self._json({"runs": runs})
            if path.startswith("/api/run/"):
                run = state.runs.get(path.rsplit("/", 1)[-1])
                if run is None:
                    return self._fail(HTTPStatus.NOT_FOUND, "no such run")
                return self._json(run.snapshot(include_profile=True))
            return self._fail(HTTPStatus.NOT_FOUND, "no such endpoint")

        def do_POST(self):
            url = urlparse(self.path)
            if not self._authorised(parse_qs(url.query)):
                return self._fail(HTTPStatus.FORBIDDEN, "bad token")
            length = int(self.headers.get("Content-Length") or 0)
            if length > 1_000_000:
                return self._fail(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too big")
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                return self._fail(HTTPStatus.BAD_REQUEST, "malformed JSON")

            if url.path == "/api/leads":
                raw = payload.get("targets") or ""
                primary, _ = (ConsoleApp.parse_line(raw) if isinstance(raw, str)
                              else ([str(x) for x in raw], []))
                seeds = [Identifier.parse(x) for x in primary]
                from ..catalog import attribution, flags, leads_for
                found = leads_for(seeds, limit=int(payload.get("limit") or 12))
                return self._json({
                    "attribution": attribution(),
                    "buckets": [
                        {"bucket": b,
                         "items": [{**e, "flags": flags(e)} for e in items]}
                        for b, items in found.items()
                    ],
                })

            if url.path == "/api/advise":
                raw = payload.get("targets") or ""
                primary, sec = (ConsoleApp.parse_line(raw) if isinstance(raw, str)
                                else ([str(x) for x in raw], []))
                seeds = [Identifier.parse(x) for x in primary]
                from ..advice import review
                return self._json({
                    **review([s for s in seeds if s.type is not IdType.UNKNOWN], sec),
                    "parsed": [{"value": s.value, "type": s.type.value} for s in seeds],
                })

            if url.path == "/api/scan":
                raw = payload.get("targets") or []
                if isinstance(raw, str):
                    primary, sec = ConsoleApp.parse_line(raw)
                else:
                    primary = [str(x) for x in raw]
                    sec = []
                sec += [str(x) for x in (payload.get("secondary") or [])]
                pins = payload.get("pinned") or []
                if not isinstance(pins, list) or len(pins) > 200:
                    return self._fail(HTTPStatus.BAD_REQUEST, "bad pinned list")
                try:
                    run = state.start(primary, [s for s in sec if s.strip()],
                                      str(payload.get("preset") or "standard"),
                                      payload.get("options") or {},
                                      pinned=[p for p in pins if isinstance(p, dict)])
                except ValueError as exc:
                    return self._fail(HTTPStatus.BAD_REQUEST, str(exc))
                return self._json({"id": run.id})

            if url.path.startswith("/api/export/"):
                run = state.runs.get(url.path.rsplit("/", 1)[-1])
                if run is None:
                    return self._fail(HTTPStatus.NOT_FOUND, "no such run")
                try:
                    return self._json({"files": state.export(run)})
                except (ValueError, OSError) as exc:
                    return self._fail(HTTPStatus.BAD_REQUEST, str(exc))

            return self._fail(HTTPStatus.NOT_FOUND, "no such endpoint")

        # -- static ---------------------------------------------------------
        def _static(self, name: str):
            # Resolve inside STATIC only: never let a crafted path escape.
            target = (STATIC / name).resolve()
            if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
                return self._fail(HTTPStatus.NOT_FOUND, "no such file")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
                ctype += "; charset=utf-8"
            return self._send(HTTPStatus.OK, target.read_bytes(), ctype)

    return Handler


def serve(auth, opts: ScanOptions, outdir: Path, host: str = "127.0.0.1",
          port: int = 8787, open_browser: bool = True, console=None):
    """Run the UI until interrupted. Returns the exit code."""
    token = secrets.token_urlsafe(24)
    state = State(auth, opts, outdir)
    handler = make_handler(state, token)

    for candidate in range(port, port + 20):
        try:
            httpd = ThreadingHTTPServer((host, candidate), handler)
            break
        except OSError:
            continue
    else:
        if console:
            console.print(f"[red]No free port in {port}–{port + 19}.[/red]")
        return 1

    url = f"http://{host}:{httpd.server_address[1]}/?t={token}"
    if console:
        console.print(
            f"\n  [bold cyan]Omnisint UI[/bold cyan]  [dim]v{__version__}[/dim]\n"
            f"  [bold]{url}[/bold]\n\n"
            f"  [dim]Loopback only. The token in that URL is what stops other\n"
            f"  pages in your browser from driving this server — treat the URL\n"
            f"  as a credential and do not paste it anywhere.[/dim]\n"
            f"  [dim]Ctrl-C to stop.[/dim]\n")
    audit("web.start", auth, url=f"http://{host}:{httpd.server_address[1]}")

    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        if console:
            console.print("\n[dim]UI stopped.[/dim]")
    finally:
        httpd.shutdown()
        httpd.server_close()
        audit("web.stop", auth)
    return 0
