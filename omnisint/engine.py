"""Orchestration: fan every identifier out to every capable adapter, then
fold the results back into one profile — optionally following the new
identifiers that turn up along the way.
"""
from __future__ import annotations

import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .config import ScanOptions
from .correlate import (apply_corroboration, cluster_personas,
                        harvest_identity, merge_evidence, score_accounts,
                        summarize_gaps)
from .models import Identifier, IdType, Profile
from .registry import available_adapters

ProgressFn = Callable[[str, str], None]


class Engine:
    def __init__(self, opts: ScanOptions, progress: ProgressFn | None = None):
        self.opts = opts
        self.progress = progress or (lambda *_: None)
        self.adapters = [cls(opts) for cls in
                         available_adapters(opts.only, opts.exclude)]

    # -- public -----------------------------------------------------------
    def scan(self, seeds: list[Identifier], workdir: Path | None = None,
             secondary: list[str] | None = None) -> Profile:
        profile = Profile(seeds=list(seeds), secondary=list(secondary or []))
        temp_root = workdir is None
        root = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="omnisint-"))
        root.mkdir(parents=True, exist_ok=True)

        try:
            queue = list(seeds)
            seen: set[str] = set()

            while queue:
                # One "hop": everything currently queued at the same depth.
                batch = [i for i in queue if i.key() not in seen]
                queue = []
                for ident in batch:
                    seen.add(ident.key())
                if not batch:
                    break

                discovered = self._run_hop(batch, profile, root)

                if self.opts.pivot_depth <= 0:
                    break
                next_hop = [
                    i for i in discovered
                    if i.key() not in seen and i.depth <= self.opts.pivot_depth
                ]
                # Budget the fan-out: pivoting is where scans explode.
                queue = next_hop[: self.opts.pivot_limit]
                if len(next_hop) > self.opts.pivot_limit:
                    profile.warnings.append(
                        f"pivot: {len(next_hop)} new identifiers found, only "
                        f"{self.opts.pivot_limit} followed (raise --pivot-limit "
                        "to chase the rest)"
                    )

            score_accounts(profile)
            harvest_identity(profile)
            apply_corroboration(profile)
            cluster_personas(profile)
            summarize_gaps(profile)
            for ident in seeds:
                profile.identifiers.setdefault(ident.key(), ident)
            return profile
        finally:
            if temp_root and not self.opts.keep_raw:
                shutil.rmtree(root, ignore_errors=True)
            elif temp_root:
                profile.warnings.append(f"raw tool output kept in {root}")

    def plan(self, seeds: list[Identifier]) -> list[tuple[str, str]]:
        """What would run, without running it."""
        return [
            (a.name, i.value)
            for i in seeds for a in self.adapters if a.handles(i)
        ]

    # -- internals --------------------------------------------------------
    def _run_hop(self, batch: list[Identifier], profile: Profile,
                 root: Path) -> list[Identifier]:
        jobs = [(a, i) for i in batch for a in self.adapters if a.handles(i)]
        discovered: list[Identifier] = []

        if not jobs:
            profile.warnings.append(
                "no adapter accepts the supplied identifier type(s); "
                "run `omnisint tools` to see what is installed"
            )
            return discovered

        # Not a `with` block: its __exit__ waits for every worker, so a
        # Ctrl-C mid-scan would appear to hang instead of returning control.
        pool = ThreadPoolExecutor(max_workers=self.opts.workers)
        try:
            futures = {}
            for adapter, ident in jobs:
                wd = root / f"{adapter.name}_{ident.type.value}_{abs(hash(ident.value)) % 10**8}"
                wd.mkdir(parents=True, exist_ok=True)
                self.progress("start", f"{adapter.name} → {ident.value}")
                futures[pool.submit(adapter.execute, ident, wd)] = (adapter, ident)

            for fut in as_completed(futures):
                adapter, ident = futures[fut]
                try:
                    result, run = fut.result()
                except Exception as exc:
                    profile.warnings.append(f"{adapter.name}: {exc}")
                    self.progress("fail", f"{adapter.name} → {ident.value}")
                    continue

                profile.runs.append(run)
                merge_evidence(profile, ident.value, result.evidence)
                profile.identifiers.setdefault(ident.key(), ident)

                for key, value in result.extras.items():
                    if key == "breaches":
                        profile.breaches.extend(value)
                    elif key == "infrastructure":
                        profile.infrastructure.update(value)
                    elif key == "phones":
                        profile.phones.update(value)
                    elif key == "notes":
                        profile.warnings.extend(value)
                profile.warnings.extend(result.warnings)

                for cand in result.pivots:
                    if cand.type in (IdType.USERNAME, IdType.EMAIL):
                        discovered.append(cand)
                        profile.identifiers.setdefault(cand.key(), cand)

                self.progress(
                    "done",
                    f"{adapter.name} → {ident.value} "
                    f"({run.found} hit{'s' if run.found != 1 else ''}, {run.duration:.1f}s)",
                )
        except KeyboardInterrupt:
            # Drop queued work and stop waiting. Tools already running are
            # subprocesses we cannot pre-empt; they exit on their own.
            pool.shutdown(wait=False, cancel_futures=True)
            profile.warnings.insert(0, (
                "scan interrupted — results below are partial. Tools that had "
                "not finished contributed nothing, which is not the same as "
                "them finding nothing."))
            raise
        finally:
            pool.shutdown(wait=False)

        # Deduplicate discovered identifiers, keeping the shallowest origin.
        unique: dict[str, Identifier] = {}
        for cand in discovered:
            unique.setdefault(cand.key(), cand)
        return list(unique.values())
