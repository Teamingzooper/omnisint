"""Adapter contract: wrap one upstream OSINT tool, emit normalised Evidence."""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Iterable

from ..models import Evidence, Identifier, IdType, ToolRun


@dataclass
class AdapterResult:
    evidence: list[Evidence] = field(default_factory=list)
    # Identifiers discovered along the way (emails, alternate usernames …).
    pivots: list[Identifier] = field(default_factory=list)
    # Free-form extras that are not per-account (whois records, breaches …).
    extras: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class Adapter:
    """Base class. Subclasses implement `run`."""

    name: str = "adapter"
    accepts: tuple[IdType, ...] = ()
    #: Baseline trust in a positive result from this tool, 0..1.
    base_weight: float = 0.5
    #: True when the tool is an external binary we must find on PATH.
    binary: str | None = None
    #: Cap this adapter's wall-clock below the global --tool-timeout, for
    #: backends that should be a quick lookup rather than a full sweep.
    max_seconds: int | None = None
    #: --deep legitimately takes longer, so the cap scales rather than
    #: strangling a sweep the operator deliberately widened.
    deep_multiplier: int = 4
    #: Excluded from the default set; must be asked for by name or by flag.
    opt_in: bool = False
    #: Exact command that installs this backend.
    install: str | None = None
    #: Anything else needed after installing (credentials, a daemon, a key).
    install_note: str | None = None
    #: Upstream project, so users can audit what they are installing.
    homepage: str | None = None
    description: str = ""

    def __init__(self, opts: "ScanOptions"):
        self.opts = opts

    # -- availability -----------------------------------------------------
    @classmethod
    def locate(cls) -> str | None:
        if cls.binary is None:
            return cls.name
        return shutil.which(cls.binary)

    @classmethod
    def available(cls) -> bool:
        return cls.locate() is not None

    def handles(self, ident: Identifier) -> bool:
        return ident.type in self.accepts

    # -- execution --------------------------------------------------------
    def run(self, ident: Identifier, workdir) -> AdapterResult:  # pragma: no cover
        raise NotImplementedError

    def execute(self, ident: Identifier, workdir) -> tuple[AdapterResult, ToolRun]:
        start = time.time()
        try:
            result = self.run(ident, workdir)
        except subprocess.TimeoutExpired:
            # Report the budget, not the whole argv — the raw command is
            # noise in a findings report.
            limit = self.budget()
            msg = (f"{self.name}: timed out after {limit}s — no results from "
                   "this source (not a negative result)")
            return AdapterResult(warnings=[msg]), ToolRun(
                adapter=self.name, identifier=ident.value, ok=False,
                duration=time.time() - start, error=f"timeout after {limit}s",
            )
        except Exception as exc:  # a broken adapter must not kill the scan
            return AdapterResult(warnings=[f"{self.name}: {exc}"]), ToolRun(
                adapter=self.name,
                identifier=ident.value,
                ok=False,
                duration=time.time() - start,
                error=f"{type(exc).__name__}: {exc}",
            )
        found = sum(1 for e in result.evidence if e.status.value == "found")
        inconclusive = sum(1 for e in result.evidence if e.status.value == "inconclusive")
        return result, ToolRun(
            adapter=self.name,
            identifier=ident.value,
            ok=True,
            duration=time.time() - start,
            found=found,
            inconclusive=inconclusive,
        )

    # -- helpers ----------------------------------------------------------
    def budget(self, requested: int | None = None) -> int:
        """Seconds this adapter actually gets.

        The per-adapter cap is the important half: without one, a single
        wedged tool holds the whole scan for the global --tool-timeout
        while the console shows a spinner and nothing else.
        """
        limit = requested or self.opts.tool_timeout
        cap = self.max_seconds
        if cap is not None:
            if self.opts.all_sites:
                cap *= self.deep_multiplier
            limit = min(limit, cap)
        return limit

    def _sh(self, cmd: Iterable[str], timeout: int | None = None, cwd=None):
        cmd = [str(c) for c in cmd]
        budget = self.budget(timeout)
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=budget,
            cwd=str(cwd) if cwd else None,
            errors="replace",
        )
        return proc
