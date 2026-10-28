"""Accuracy harness: does Omnisint agree with reality?

Unit tests prove the plumbing. They cannot tell you whether a scan is
*right*. This checks findings against ground truth established live from
each platform's own API, so the expectations cannot drift out of date or
rest on anybody's memory.

Two kinds of case, and the second matters more:

* **Positive controls** — public accounts that demonstrably exist. These
  measure recall: did the tool find a thing that is really there?
* **Negative controls** — handles that exist nowhere. These measure false
  positives, which is the failure mode that actually hurts: a sweeper that
  claims a nonexistent handle is registered on 90 sites will happily
  implicate an innocent person.

Only public figures' public accounts and synthetic handles are used. No
private individual is profiled to test a tool.

    python3 tests/test_accuracy.py            # ground truth + fast adapters
    python3 tests/test_accuracy.py --full     # every adapter, several minutes
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from omnisint.config import ScanOptions
from omnisint.models import Identifier, Status

UA = {"User-Agent": "omnisint-accuracy-check/1.0 (+testing)"}

#: Handles whose real state we can confirm from an API, not from memory.
#: Public figures / project accounts only.
POSITIVE = ["torvalds", "gvanrossum"]
#: Nothing should ever be registered under these.
NEGATIVE = ["qzvm7x3k9wplrt2dh", "xbnq4w8zrv61ksjta"]

PASS = FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}" + (f"  [{detail}]" if detail else ""))
    else:
        FAIL += 1
        print(f"  FAIL {label}" + (f"  [{detail}]" if detail else ""))


# -- ground truth -----------------------------------------------------------
def github_exists(handle: str) -> bool | None:
    req = urllib.request.Request(f"https://api.github.com/users/{handle}",
                                 headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        return None            # rate limited or blocked: unknown, not false
    except Exception:
        return None


def reddit_exists(handle: str) -> bool | None:
    req = urllib.request.Request(
        f"https://www.reddit.com/user/{handle}/about.json", headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read())
            return bool(body.get("data", {}).get("name"))
    except urllib.error.HTTPError as e:
        # 403 is Reddit refusing a non-browser client, not a missing user.
        # Recording it as "absent" would manufacture false ground truth and
        # then blame a tool for correctly finding a real account.
        return False if e.code == 404 else None
    except Exception:
        return None


PLATFORM_ORACLES = {"GitHub": github_exists, "Reddit": reddit_exists}


def establish_truth() -> dict:
    print("establishing ground truth from the platforms themselves")
    truth: dict[tuple[str, str], bool] = {}
    for handle in POSITIVE + NEGATIVE:
        for platform, oracle in PLATFORM_ORACLES.items():
            state = oracle(handle)
            truth[(handle, platform)] = state
            mark = {True: "exists", False: "absent", None: "unknown"}[state]
            print(f"    {platform:8} {handle:20} {mark}")
            time.sleep(1.2)            # be polite to the oracles
    return truth


# -- running adapters -------------------------------------------------------
def run_adapter(cls, handle: str, timeout: int = 120):
    opts = ScanOptions(tool_timeout=timeout, request_timeout=12, top_sites=120)
    adapter = cls(opts)
    res, run = adapter.execute(Identifier.parse(handle),
                               pathlib.Path(tempfile.mkdtemp()))
    found = {e.platform.split("[")[0].strip().lower(): e
             for e in res.evidence if e.status is Status.FOUND}
    return found, run


def main() -> int:
    full = "--full" in sys.argv
    from omnisint.adapters.maigret import MaigretAdapter
    from omnisint.adapters.sherlock import SherlockAdapter
    from omnisint.adapters.user_scanner import UserScannerAdapter

    adapters = [MaigretAdapter, UserScannerAdapter]
    if full:
        adapters.append(SherlockAdapter)

    truth = establish_truth()
    known_true = {k for k, v in truth.items() if v is True}
    known_false = {k for k, v in truth.items() if v is False}
    check("ground truth found live accounts", len(known_true) >= 2,
          f"{len(known_true)} confirmed present")
    check("ground truth found absent accounts", len(known_false) >= 2,
          f"{len(known_false)} confirmed absent")

    results: dict[str, dict] = {}
    for cls in adapters:
        if not cls.available():
            print(f"\n{cls.name}: not installed, skipped")
            continue
        print(f"\n{cls.name}")
        stats = {"recall_hit": 0, "recall_total": 0, "false_pos": 0,
                 "neg_claims": 0, "seconds": 0.0}

        for handle in POSITIVE:
            found, run = run_adapter(cls, handle)
            stats["seconds"] += run.duration
            for (h, platform), present in truth.items():
                if h != handle or present is not True:
                    continue
                stats["recall_total"] += 1
                if platform.lower() in found:
                    stats["recall_hit"] += 1
            print(f"    {handle:20} {len(found):4} accounts  {run.duration:5.1f}s")

        for handle in NEGATIVE:
            found, run = run_adapter(cls, handle)
            stats["seconds"] += run.duration
            stats["neg_claims"] += len(found)
            for (h, platform), present in truth.items():
                if h == handle and present is False and platform.lower() in found:
                    stats["false_pos"] += 1
            print(f"    {handle:20} {len(found):4} accounts  {run.duration:5.1f}s"
                  f"   <- should be ~0")
        results[cls.name] = stats

    print("\n" + "=" * 72)
    print(f"{'backend':16} {'recall':>12} {'oracle FPs':>11} "
          f"{'claims on fake':>15} {'time':>8}")
    for name, s in results.items():
        recall = (f"{s['recall_hit']}/{s['recall_total']}"
                  if s["recall_total"] else "n/a")
        print(f"{name:16} {recall:>12} {s['false_pos']:>11} "
              f"{s['neg_claims']:>15} {s['seconds']:>7.0f}s")
    print("=" * 72)

    for name, s in results.items():
        if s["recall_total"]:
            check(f"{name} finds accounts that verifiably exist",
                  s["recall_hit"] == s["recall_total"],
                  f"{s['recall_hit']}/{s['recall_total']}")
        check(f"{name} does not claim oracle-verified absent accounts",
              s["false_pos"] == 0, f"{s['false_pos']} false positives")
        # A handle that exists nowhere should produce almost nothing. Some
        # noise is expected from sites that 200 on any profile URL.
        check(f"{name} stays quiet on a handle that exists nowhere",
              s["neg_claims"] <= 10, f"{s['neg_claims']} claims")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
