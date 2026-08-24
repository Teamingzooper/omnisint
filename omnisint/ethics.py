"""Authorisation gate, audit trail and passive-by-default policy.

The point of this module is that every investigation leaves a record of who
ran it, against what, and under what claimed authority. That record is what
makes the difference between research and surveillance defensible after the
fact.
"""
from __future__ import annotations

import getpass
import json
import os
import socket
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path

HOME = Path(os.environ.get("OMNISINT_HOME", Path.home() / ".omnisint"))
CONSENT_FILE = HOME / "authorization.json"
AUDIT_LOG = HOME / "audit.jsonl"

BANNER = """\
Omnisint aggregates publicly available information from third-party
services. Before you continue, confirm all of the following:

  1. You are investigating yourself, or you have documented authorisation
     from the data subject or from an engagement owner (pentest scope,
     legal hold, HR/trust-and-safety mandate, or equivalent).
  2. Your purpose is lawful and proportionate. Stalking, harassment,
     doxxing, and building profiles on people who have not consented are
     not lawful purposes, whatever your local statute says.
  3. You will hold the results as sensitive personal data: minimise what
     you keep, do not redistribute it, and delete it when the engagement
     ends.
  4. You accept that everything you run is written to a local audit log.

Findings here are unverified third-party signals, not facts. Username
collision is common. Do not act against a person on the strength of a
"possible" or "probable" match.\
"""


@dataclass
class Authorization:
    """A recorded acknowledgement of lawful basis."""
    operator: str
    basis: str                 # free text: what authorises this
    case: str | None = None
    acknowledged_at: float = field(default_factory=time.time)
    host: str = field(default_factory=socket.gethostname)

    def to_dict(self) -> dict:
        return asdict(self)


class AuthorizationError(RuntimeError):
    pass


def _ensure_home() -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(HOME, 0o700)
    except OSError:
        pass


def load_authorization() -> Authorization | None:
    if not CONSENT_FILE.exists():
        return None
    try:
        return Authorization(**json.loads(CONSENT_FILE.read_text()))
    except Exception:
        return None


def save_authorization(auth: Authorization) -> None:
    _ensure_home()
    CONSENT_FILE.write_text(json.dumps(auth.to_dict(), indent=2))
    try:
        os.chmod(CONSENT_FILE, 0o600)
    except OSError:
        pass


def require_authorization(
    *,
    accepted: bool,
    basis: str | None,
    case: str | None,
    interactive: bool,
    console=None,
) -> Authorization:
    """Gate every scan behind an explicit, recorded acknowledgement."""
    existing = load_authorization()
    operator = getpass.getuser()

    if accepted:
        auth = Authorization(
            operator=operator,
            basis=basis or "acknowledged via --i-have-authorization",
            case=case,
        )
        save_authorization(auth)
        return auth

    if existing is not None:
        # Re-use a standing acknowledgement but keep the current case ref.
        return Authorization(
            operator=existing.operator,
            basis=existing.basis,
            case=case or existing.case,
            acknowledged_at=existing.acknowledged_at,
            host=existing.host,
        )

    if not interactive:
        raise AuthorizationError(
            "No recorded authorisation. Re-run with --i-have-authorization "
            '(and ideally --basis "…") to record your lawful basis.'
        )

    if console is not None:
        console.print(BANNER)
    else:
        print(BANNER)
    answer = input("\nDo you confirm all four points? [type 'yes' to continue] ").strip()
    if answer.lower() not in {"yes", "y"}:
        raise AuthorizationError("Authorisation not confirmed; aborting.")
    typed_basis = basis or input("Lawful basis / engagement reference: ").strip()
    if not typed_basis:
        raise AuthorizationError("A lawful basis is required; aborting.")
    auth = Authorization(operator=operator, basis=typed_basis, case=case)
    save_authorization(auth)
    return auth


def audit(event: str, auth: Authorization | None = None, **fields) -> str:
    """Append one tamper-evident-ish line to the local audit log."""
    _ensure_home()
    record = {
        "id": uuid.uuid4().hex[:12],
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        "operator": auth.operator if auth else getpass.getuser(),
        "case": auth.case if auth else None,
        "basis": auth.basis if auth else None,
        **fields,
    }
    with AUDIT_LOG.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    try:
        os.chmod(AUDIT_LOG, 0o600)
    except OSError:
        pass
    return record["id"]


DISCLAIMER = (
    "Unverified third-party signals. Username collisions are common; treat "
    "anything below 'confirmed' as a lead, not a fact. Handle as sensitive "
    "personal data."
)
