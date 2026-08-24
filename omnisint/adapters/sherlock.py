"""Sherlock: broad username sweep. High recall, notable false-positive rate."""
from __future__ import annotations

import re

from ..models import Evidence, IdType, Status
from .base import Adapter, AdapterResult

# Sherlock prints "[+] Site: https://…" for each hit.
_HIT = re.compile(r"^\[\+\]\s+(?P<site>[^:]+):\s+(?P<url>\S+)")


class SherlockAdapter(Adapter):
    name = "sherlock"
    binary = "sherlock"
    accepts = (IdType.USERNAME,)
    # Deliberately low: Sherlock's status-code heuristics produce real
    # false positives (Reddit will "match" almost any string).
    base_weight = 0.45
    description = "400+ site username sweep"

    def run(self, ident, workdir) -> AdapterResult:
        out = workdir / f"sherlock_{ident.value}.txt"
        cmd = [
            self.locate(), ident.value,
            "--print-found", "--no-color", "--no-txt",
            "--timeout", str(self.opts.request_timeout),
            "--output", str(out),
        ]
        if self.opts.nsfw:
            cmd.append("--nsfw")
        if self.opts.tor:
            cmd.append("--tor")
        elif self.opts.proxy:
            cmd += ["--proxy", self.opts.proxy]

        proc = self._sh(cmd)
        res = AdapterResult()

        for line in proc.stdout.splitlines():
            m = _HIT.match(line.strip())
            if not m:
                continue
            site = m.group("site").strip()
            url = m.group("url").strip()
            res.evidence.append(
                Evidence(
                    source=self.name,
                    platform=site,
                    url=url,
                    status=Status.FOUND,
                    weight=self.base_weight,
                )
            )

        if proc.returncode != 0 and not res.evidence:
            res.warnings.append(
                f"sherlock exited {proc.returncode}: {proc.stderr.strip()[:200]}"
            )
        return res
