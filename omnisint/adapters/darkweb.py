"""Dark-web exposure check via OnionSearch (megadose).

Searches .onion indexes for an identifier. This answers a defensive
question — "is my handle or address showing up on hidden services?" — and
it is genuinely different from everything else in the stack, which only
looks at the clear web.

Opt-in for three reasons: it needs a local Tor SOCKS proxy, it is slow
(many engines, many pages), and scraping hidden-service indexes is a
deliberate act rather than something a routine scan should do silently.
Enable with `--darkweb`, or `--only darkweb`.
"""
from __future__ import annotations

import csv
import shutil

from ..models import Evidence, IdType, Status
from .base import Adapter, AdapterResult


class DarkWebAdapter(Adapter):
    name = "darkweb"
    binary = "onionsearch"
    accepts = (IdType.USERNAME, IdType.EMAIL)
    base_weight = 0.5
    max_seconds = 600
    #: Never runs unless explicitly requested — see module docstring.
    opt_in = True
    install = "pip install onionsearch"
    install_note = "also needs Tor running: brew install tor && brew services start tor"
    homepage = "https://github.com/megadose/OnionSearch"
    description = "hidden-service index search (opt-in, needs Tor + --darkweb)"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("onionsearch") is not None

    def run(self, ident, workdir) -> AdapterResult:
        res = AdapterResult()
        out = workdir / "onion.csv"
        proxy = self.opts.proxy or "127.0.0.1:9050"
        # onionsearch wants host:port, not a socks5:// URL.
        proxy = proxy.split("://", 1)[-1]

        proc = self._sh([
            self.locate(), ident.value,
            "--proxy", proxy,
            "--output", str(out),
            "--limit", "1",
        ])

        if not out.exists():
            res.warnings.append(
                "darkweb: no results file — a local Tor proxy is required "
                f"(tried {proxy}). Start Tor, or pass --proxy host:port. "
                f"{proc.stderr.strip()[:160]}"
            )
            return res

        seen: set[str] = set()
        with out.open(newline="", errors="replace") as fh:
            for row in csv.reader(fh):
                if len(row) < 3:
                    continue
                engine, _name, link = row[0], row[1], row[2]
                if not link.startswith("http") or link in seen:
                    continue
                seen.add(link)
                res.evidence.append(Evidence(
                    source=self.name,
                    platform=f"onion:{engine}",
                    url=link,
                    status=Status.FOUND,
                    # A search-index hit means the string appears somewhere on
                    # that page — not that your subject has an account there.
                    weight=0.25,
                    note="hidden-service index hit — mention, not an account",
                ))

        if seen:
            res.warnings.append(
                f"darkweb: {len(seen)} hidden-service page(s) mention "
                f"'{ident.value}'. A mention is not an account and not proof "
                "of wrongdoing — read the pages before drawing any conclusion."
            )
        return res
