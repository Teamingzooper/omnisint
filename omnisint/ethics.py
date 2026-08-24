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
Omnisint searches public sources and pulls the results into one profile.

Before the first scan, one question: who are you looking into, and what
gives you the standing to do it? Whatever you answer is written to a local
audit log, which is what makes an investigation defensible later.

Ground rules, in short:
  · Results are unverified signals, not facts. Handles collide constantly.
  · Do not act against someone on a "possible" or "probable" match.
  · Treat what you find as sensitive personal data: keep little, share
    nothing, delete it when you are done.\
"""

#: Offered as a numbered menu rather than a blank prompt. A free-text box
#: asking for a "lawful basis" mostly produces the word "yes".
BASIS_CHOICES = [
    ("Myself — checking my own footprint",
     "self-audit of my own accounts"),
    ("Someone who asked me to — they gave permission",
     "consent of the data subject"),
    ("Work — pentest, trust & safety, HR, legal, or similar",
     "authorised engagement"),
    ("Security research on a public figure or public account",
     "security research, public sources only"),
]


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

    typed_basis = basis
    if not typed_basis:
        print("\nWho are you looking into?")
        for n, (label, _) in enumerate(BASIS_CHOICES, 1):
            print(f"  {n}. {label}")
        print(f"  {len(BASIS_CHOICES) + 1}. Something else — I'll describe it")
        choice = input("\nChoose 1-5 (or q to quit): ").strip().lower()

        if choice in ("q", "quit", "exit", ""):
            raise AuthorizationError(
                "No basis given, so nothing was scanned. Run it again when "
                "you can answer that question.")
        if choice.isdigit() and 1 <= int(choice) <= len(BASIS_CHOICES):
            typed_basis = BASIS_CHOICES[int(choice) - 1][1]
        else:
            typed_basis = input("Describe it in a few words: ").strip()
            if not typed_basis or typed_basis.lower() in {"yes", "y", "n", "ok"}:
                raise AuthorizationError(
                    "That is not a reason. Say who you are looking into and "
                    "why you may — it goes in the audit log, and it is the "
                    "thing that makes this defensible later.")

    auth = Authorization(operator=operator, basis=typed_basis, case=case)
    if console is not None:
        console.print(f"\n[dim]Recorded: {typed_basis}[/dim]")
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
