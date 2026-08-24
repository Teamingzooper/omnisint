"""Holehe: which sites have an account registered to an email address.

Holehe works by probing registration/login/password-reset endpoints. In
passive mode we pass -NP so it never triggers a password-recovery email to
the data subject — an investigation should not be visible to its target.
"""
from __future__ import annotations

import csv

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult


class HoleheAdapter(Adapter):
    name = "holehe"
    binary = "holehe"
    accepts = (IdType.EMAIL,)
    base_weight = 0.72
    install = "pip install holehe"
    homepage = "https://github.com/megadose/holehe"
    description = "email-to-site registration checks"

    def run(self, ident, workdir) -> AdapterResult:
        cmd = [self.locate(), ident.value, "--no-color", "--no-clear", "-C",
               "-T", str(min(self.opts.request_timeout, 30))]
        if self.opts.passive:
            cmd.append("-NP")

        proc = self._sh(cmd, cwd=workdir)
        res = AdapterResult()

        reports = sorted(
            workdir.glob("holehe_*_results.csv"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        target = next(
            (p for p in reports if ident.value.lower() in p.name.lower()),
            reports[0] if reports else None,
        )
        if target is None:
            res.warnings.append(
                f"holehe produced no CSV ({proc.stderr.strip()[:200] or 'no stderr'})"
            )
            return res

        with target.open(newline="") as fh:
            for row in csv.DictReader(fh):
                site = (row.get("name") or "").strip()
                if not site:
                    continue
                domain = (row.get("domain") or "").strip()
                exists = (row.get("exists") or "").strip().lower() == "true"
                limited = (row.get("rateLimit") or "").strip().lower() == "true"

                if limited and not exists:
                    res.evidence.append(
                        Evidence(
                            source=self.name, platform=site,
                            url=f"https://{domain}" if domain else None,
                            status=Status.INCONCLUSIVE, weight=0.0,
                            note="rate limited — no signal, not a negative",
                        )
                    )
                    continue
                if not exists:
                    continue

                meta = {}
                for key, label in (
                    ("emailrecovery", "recovery_email_hint"),
                    ("phoneNumber", "phone_hint"),
                    ("others", "other"),
                ):
                    val = (row.get(key) or "").strip()
                    if val and val.lower() not in {"none", "null"}:
                        meta[label] = val

                res.evidence.append(
                    Evidence(
                        source=self.name, platform=site,
                        url=f"https://{domain}" if domain else None,
                        status=Status.FOUND,
                        weight=self.base_weight,
                        metadata=meta,
                        note="email registered",
                    )
                )
                # Masked recovery hints are leads, not addresses; keep them
                # as metadata but only pivot on a fully-formed address.
                hint = meta.get("recovery_email_hint", "")
                cand = Identifier.parse(hint, origin=f"holehe:{site}", depth=ident.depth + 1)
                if cand.type is IdType.EMAIL and "*" not in hint:
                    res.pivots.append(cand)

        # The count itself is reported by correlate.summarize_gaps; adding a
        # second line here would just duplicate it.
        return res
