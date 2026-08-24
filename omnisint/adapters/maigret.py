"""Maigret: username sweep plus profile-data extraction.

Maigret is the highest-value source here because it does not just say
"exists" — for many sites it parses the profile and returns real fields
(name, location, follower counts, linked accounts). Those extracted IDs are
what makes cross-tool correlation and pivoting possible.
"""
from __future__ import annotations

import json

from ..models import Evidence, Identifier, IdType, Status
from .base import Adapter, AdapterResult

# Fields Maigret's extractors expose that describe the person, not the site.
_IDENTITY_KEYS = {
    "fullname", "full_name", "name", "first_name", "last_name",
    "location", "country", "city", "bio", "about", "description", "status",
    "follower_count", "following_count", "created_at", "registration_date",
    "uid", "id", "company", "website", "url", "gender", "age", "birthday",
    "language", "public_repos_count", "public_gists_count", "is_verified",
}


class MaigretAdapter(Adapter):
    name = "maigret"
    binary = "maigret"
    accepts = (IdType.USERNAME,)
    base_weight = 0.7
    description = "3000+ site sweep with profile-data extraction"

    def run(self, ident, workdir) -> AdapterResult:
        outdir = workdir / "maigret"
        outdir.mkdir(parents=True, exist_ok=True)

        cmd = [
            self.locate(), ident.value,
            "--no-progressbar", "--no-color", "--no-autoupdate",
            "--timeout", str(self.opts.request_timeout),
            "-J", "simple", "-fo", str(outdir),
        ]
        if self.opts.all_sites:
            cmd.append("--all-sites")
        else:
            cmd += ["--top-sites", str(self.opts.top_sites)]
        if not self.opts.nsfw:
            cmd += ["--exclude-tags", "porn,nsfw,erotic"]
        if self.opts.pivot_depth <= 0:
            # Maigret's own recursion would fight our pivot budget.
            cmd.append("--no-recursion")
        if self.opts.tor:
            cmd.append("--tor-proxy")
        elif self.opts.proxy:
            cmd += ["--proxy", self.opts.proxy]

        proc = self._sh(cmd)
        res = AdapterResult()

        report = outdir / f"report_{ident.value}_simple.json"
        if not report.exists():
            matches = sorted(outdir.glob(f"report_{ident.value}*simple*.json"))
            report = matches[0] if matches else None

        if report is None:
            res.warnings.append(
                f"maigret produced no report ({proc.stderr.strip()[:200] or 'no stderr'})"
            )
            return res

        try:
            data = json.loads(report.read_text() or "{}")
        except json.JSONDecodeError as exc:
            res.warnings.append(f"maigret report unparseable: {exc}")
            return res

        for site_name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            status_blk = entry.get("status") or {}
            raw_status = str(status_blk.get("status", "")).lower()
            url = status_blk.get("url") or entry.get("url_user")

            if raw_status == "claimed":
                status = Status.FOUND
            elif raw_status in {"available", "unclaimed"}:
                status = Status.NOT_FOUND
            elif raw_status in {"illegal", "unknown", ""}:
                status = Status.INCONCLUSIVE
            else:
                status = Status.INCONCLUSIVE

            ids = {k: v for k, v in (status_blk.get("ids") or {}).items() if v}
            meta = {k: v for k, v in ids.items() if k.lower() in _IDENTITY_KEYS}
            if ids.get("image"):
                meta["avatar"] = ids["image"]

            weight = self.base_weight
            # A parsed profile body is much stronger proof than a status code.
            if meta:
                weight = min(0.9, weight + 0.15)

            if status is Status.FOUND:
                res.evidence.append(
                    Evidence(
                        source=self.name,
                        platform=site_name,
                        url=url,
                        status=status,
                        weight=weight,
                        metadata=meta,
                        note="profile data extracted" if meta else None,
                    )
                )
            elif status is Status.INCONCLUSIVE:
                res.evidence.append(
                    Evidence(
                        source=self.name, platform=site_name, url=url,
                        status=status, weight=0.0,
                        note=f"maigret status: {raw_status or 'unknown'}",
                    )
                )

            # Pivots: Maigret hands back other usernames/ids it saw.
            for other in (entry.get("ids_usernames") or {}):
                cand = Identifier.parse(
                    str(other), origin=f"maigret:{site_name}", depth=ident.depth + 1
                )
                if cand.type in (IdType.USERNAME, IdType.EMAIL):
                    res.pivots.append(cand)
            for key in ("email", "emails"):
                val = ids.get(key)
                if val:
                    for piece in str(val).replace(";", ",").split(","):
                        cand = Identifier.parse(
                            piece, origin=f"maigret:{site_name}", depth=ident.depth + 1
                        )
                        if cand.type is IdType.EMAIL:
                            res.pivots.append(cand)
        return res
