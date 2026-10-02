"""SpiderFoot: a second opinion from a very different engine.

Everything else Omnisint drives answers "does this handle exist here?".
SpiderFoot answers a different question — it walks outward from a target
through DNS, certificates, WHOIS, breach data and 200+ other modules — so it
contributes infrastructure and derived identifiers the username sweepers
cannot see.

It is opt-in (`--spiderfoot`) because a SpiderFoot scan is measured in
minutes, not seconds, and Omnisint's default is a scan you wait for. The
default module set here is small, passive and key-free; `-d` widens it to
SpiderFoot's whole passive use case.

Install: git clone https://github.com/smicallef/spiderfoot, then either put
it at ~/spiderfoot or set OMNISINT_SPIDERFOOT=/path/to/sf.py
"""
from __future__ import annotations

import csv
import io
import os
import select
import shutil
import subprocess
import sys
import time
from functools import lru_cache
from pathlib import Path

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult

CANDIDATES = (
    "~/spiderfoot/sf.py", "~/.spiderfoot/sf.py",
    "/opt/spiderfoot/sf.py", "/usr/local/spiderfoot/sf.py",
    "/usr/share/spiderfoot/sf.py",
)

#: Modules per target type. Pointing the 500-site account sweep at a domain
#: costs minutes and finds nothing, so each identifier gets the modules that
#: can actually consume it. Intersected at runtime with what the installed
#: version ships, so a renamed module cannot break the whole run.
MODULES_BY_TYPE: dict[IdType, tuple[str, ...]] = {
    IdType.DOMAIN: ("sfp_dnsresolve", "sfp_whois", "sfp_crt", "sfp_email",
                    "sfp_names", "sfp_company", "sfp_hackertarget"),
    IdType.EMAIL: ("sfp_email", "sfp_names", "sfp_social", "sfp_github",
                   "sfp_hackertarget"),
    IdType.USERNAME: ("sfp_accounts", "sfp_social", "sfp_socialprofiles",
                      "sfp_github", "sfp_names"),
    IdType.PHONE: ("sfp_callername", "sfp_names"),
}

#: SpiderFoot prints the human-readable event description, not the type id.
ACCOUNTS = {"account on external site", "social media presence",
            "hacked account on external site", "username"}
EMAILS = {"email address", "hacked email address", "affiliate - email address",
          "deliverable email address"}
NAMES = {"human name", "person name"}
PHONES = {"phone number"}
INFRA = {"ip address", "ipv6 address", "internet name", "domain name",
         "domain whois", "name server", "co-hosted site", "subdomain",
         "ssl certificate - issued to", "affiliate - domain name"}


class SpiderFootAdapter(Adapter):
    name = "spiderfoot"
    binary = None
    accepts = (IdType.USERNAME, IdType.EMAIL, IdType.DOMAIN, IdType.PHONE)
    base_weight = 0.66
    opt_in = True
    #: SpiderFoot modules feed each other, so a scan can cascade and never
    #: settle. We read its stream against a deadline instead of waiting.
    max_seconds = 180
    install = "git clone https://github.com/smicallef/spiderfoot ~/spiderfoot"
    install_note = ("opt-in with --spiderfoot; set OMNISINT_SPIDERFOOT if it "
                    "is not at ~/spiderfoot/sf.py")
    homepage = "https://github.com/smicallef/spiderfoot"
    description = "200+ module OSINT engine: DNS, certs, WHOIS, breach data"

    # -- locating ---------------------------------------------------------
    @staticmethod
    @lru_cache(maxsize=1)
    def _script() -> str | None:
        env = os.environ.get("OMNISINT_SPIDERFOOT")
        if env and Path(env).expanduser().is_file():
            return str(Path(env).expanduser())
        for candidate in CANDIDATES:
            path = Path(candidate).expanduser()
            if path.is_file():
                return str(path)
        found = shutil.which("sf.py") or shutil.which("spiderfoot")
        return found

    @classmethod
    def locate(cls) -> str | None:
        return cls._script()

    @classmethod
    def available(cls) -> bool:
        return cls._script() is not None

    @staticmethod
    @lru_cache(maxsize=1)
    def _installed_modules() -> frozenset[str]:
        """Which modules this install ships.

        Read from the modules directory rather than `sf.py -M`: that flag
        imports all 230 modules and costs about a minute, which would
        dominate the scan budget before a single request went out.
        """
        script = SpiderFootAdapter._script()
        if script:
            mods = Path(script).parent / "modules"
            if mods.is_dir():
                return frozenset(f.stem for f in mods.glob("sfp_*.py"))
        return frozenset()

    def _stream(self, cmd: list[str], cwd, budget: int) -> tuple[str, bool]:
        """Run SpiderFoot, keeping whatever it emits before the deadline.

        A SpiderFoot scan does not reliably end: modules consume each
        other's output, so DNS finds an IP, which finds a host, which
        resolves again. Waiting for exit means waiting forever and keeping
        nothing. It writes CSV to stdout as results arrive, so we read the
        stream, stop at the deadline, and say the result is partial.
        """
        proc = subprocess.Popen(cmd, cwd=str(cwd), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        rows: list[str] = []
        deadline = time.time() + budget
        try:
            while time.time() < deadline:
                if not select.select([proc.stdout], [], [], 0.5)[0]:
                    if proc.poll() is not None:
                        break
                    continue
                line = proc.stdout.readline()
                if not line:
                    break
                rows.append(line)
        finally:
            completed = proc.poll() is not None
            if not completed:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            try:
                proc.stdout.close(); proc.stderr.close()
            except Exception:
                pass
        return "".join(rows), completed

    # -- running ----------------------------------------------------------
    def run(self, ident, workdir) -> AdapterResult:
        res = AdapterResult()
        script = self._script()
        if not script:
            return res

        cmd = [sys.executable, script, "-s", ident.value, "-o", "csv", "-q",
               # Without -n, multi-line values (WHOIS blobs) are emitted
               # unquoted and every CSV row after one is garbage.
               "-n", "-max-threads", str(max(4, self.opts.workers))]
        if self.opts.all_sites:
            cmd += ["-u", "passive"]
        else:
            wanted = MODULES_BY_TYPE.get(ident.type, ())
            usable = sorted(set(wanted) & self._installed_modules())
            if not usable:
                res.warnings.append(
                    "spiderfoot: none of the default modules exist in this "
                    "install; use --deep for its own passive module set")
                return res
            cmd += ["-m", ",".join(usable)]

        budget = min(self.opts.tool_timeout, self.max_seconds)
        if self.opts.all_sites:
            budget = self.opts.tool_timeout
        out, completed = self._stream(cmd, Path(script).parent, budget)
        if not out.strip():
            res.warnings.append(
                f"spiderfoot: no output for {ident.value} within {budget}s")
            return res

        seen: set[tuple[str, str]] = set()
        infra: dict[str, list[str]] = {}
        for row in csv.reader(io.StringIO(out)):
            # Source, Type, the entity it came from, Data
            if len(row) < 4 or row[0] in ("Source", "SpiderFoot UI"):
                continue
            module, etype, origin, data = row[0], row[1].strip().lower(), row[2], row[3].strip()
            if not data or (etype, data) in seen:
                continue
            seen.add((etype, data))

            if etype in ACCOUNTS:
                platform, url = self._split_account(data)
                res.evidence.append(Evidence(
                    source=self.name, platform=platform, url=url,
                    status=Status.FOUND, weight=self.base_weight,
                    note=f"via {module}"))
            elif etype in EMAILS:
                cand = Identifier.parse(data, origin=f"spiderfoot:{module}",
                                        depth=ident.depth + 1)
                if cand.type is IdType.EMAIL:
                    res.pivots.append(cand)
                    infra.setdefault("emails", []).append(data)
            elif etype in NAMES:
                infra.setdefault("names", []).append(data)
            elif etype in PHONES:
                infra.setdefault("phones", []).append(data)
            elif etype in INFRA:
                infra.setdefault(etype.replace(" ", "_"), []).append(data[:200])

        if infra:
            res.extras["infrastructure"] = {
                f"spiderfoot:{ident.value}": {
                    "domain": ident.value,
                    **{k: sorted(set(v))[:12] for k, v in infra.items()},
                }
            }
        if not completed:
            res.warnings.append(
                f"spiderfoot: stopped at {budget}s with partial results. Its "
                "modules feed each other, so a scan need not ever settle — "
                "what is here is real, what is absent was simply not reached.")
        if not res.evidence and not infra:
            res.warnings.append(
                f"spiderfoot: ran but produced nothing for {ident.value} — "
                "that is a thin result, not a negative one")
        return res

    @staticmethod
    def _split_account(data: str) -> tuple[str, str | None]:
        """SpiderFoot reports accounts as 'Platform: url' or a bare URL."""
        if ": " in data and data.split(": ", 1)[1].startswith("http"):
            platform, url = data.split(": ", 1)
            return platform.strip(), url.strip()
        if data.startswith("http"):
            host = data.split("/")[2] if "/" in data[8:] else data
            return host.removeprefix("www."), data
        return data[:60], None
