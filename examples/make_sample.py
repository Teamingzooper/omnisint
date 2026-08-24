"""Generate the sample report shipped in the README.

Every account, name and URL below is invented. Real scan output is personal
data about real people — including, in a username-collision case, people who
have nothing to do with the subject — so it must never be committed to a
public repository. This script produces something that looks exactly like a
real report without describing anybody.

    python3 examples/make_sample.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from omnisint.correlate import (apply_corroboration, cluster_personas,
                                harvest_identity, merge_evidence,
                                score_accounts, summarize_gaps)
from omnisint.models import (Evidence, Identifier, IdType, Profile, Status,
                             ToolRun)
from omnisint.report import render_html

SUBJECT = "riverdale"          # invented handle
COMPANY = "Northwind Labs"     # invented employer (secondary term)
CITY = "Portland, OR"

# (platform, url, sources, metadata) — all fabricated.
ACCOUNTS = [
    ("GitHub", f"https://github.com/{SUBJECT}",
     [("maigret", 0.85), ("sherlock", 0.45), ("user-scanner", 0.83)],
     {"fullname": "Alex Rivera", "company": COMPANY, "location": CITY,
      "followers": "412", "public_repos": "37", "created_at": "2014-02-11T09:14:02Z"}),
    ("GitLab", f"https://gitlab.com/{SUBJECT}",
     [("maigret", 0.85), ("user-scanner", 0.83)],
     {"fullname": "Alex Rivera", "company": COMPANY, "location": CITY}),
    ("Mastodon", f"https://fosstodon.org/@{SUBJECT}",
     [("maigret", 0.85), ("sherlock", 0.45)],
     {"fullname": "Alex Rivera", "bio": f"infra @ {COMPANY}. opinions my own.",
      "followers": "1,204"}),
    ("Keybase", f"https://keybase.io/{SUBJECT}",
     [("maigret", 0.7), ("sherlock", 0.45), ("user-scanner", 0.68)],
     {"fullname": "Alex Rivera"}),
    # A different person on the same handle — the case the report exists for.
    ("Instagram", f"https://www.instagram.com/{SUBJECT}/",
     [("maigret", 0.85), ("user-scanner", 0.83)],
     {"fullname": "Dana Okonkwo", "followers": "88", "private": "True"}),
    ("Pinterest", f"https://www.pinterest.com/{SUBJECT}/",
     [("maigret", 0.85)], {"fullname": "Dana Okonkwo"}),
    # A third, on one platform only.
    ("Medium", f"https://medium.com/@{SUBJECT}",
     [("maigret", 0.85), ("sherlock", 0.45)],
     {"fullname": "Sam Lindqvist", "followers": "12"}),
    # Existence-only hits: no extractable data.
    ("Reddit", f"https://www.reddit.com/user/{SUBJECT}", [("sherlock", 0.45)], {}),
    ("Steam", f"https://steamcommunity.com/id/{SUBJECT}", [("sherlock", 0.45)], {}),
    ("Pastebin", f"https://pastebin.com/u/{SUBJECT}",
     [("sherlock", 0.45), ("user-scanner", 0.68)], {}),
    ("SoundCloud", f"https://soundcloud.com/{SUBJECT}", [("user-scanner", 0.68)], {}),
]


def build() -> Profile:
    profile = Profile(
        seeds=[
            Identifier(SUBJECT, IdType.USERNAME),
            Identifier("Alex Rivera", IdType.NAME),
            Identifier("alex.rivera@example.com", IdType.EMAIL),
        ],
        secondary=[COMPANY, "Portland"],
    )

    for platform, url, sources, meta in ACCOUNTS:
        merge_evidence(profile, SUBJECT, [
            Evidence(src, platform, url, Status.FOUND, weight,
                     meta if i == 0 else {})
            for i, (src, weight) in enumerate(sources)
        ])

    profile.infrastructure = {
        "example.com": {
            "domain": "example.com", "freemail_provider": False,
            "a": ["93.184.216.34"],
            "mx": ["10 mail.example.com."],
            "ns": ["a.iana-servers.net.", "b.iana-servers.net."],
            "spf": ["v=spf1 -all"],
            "whois": ["Registrar: RESERVED-Internet Assigned Numbers Authority",
                      "Creation Date: 1995-08-14T04:00:00Z"],
        }
    }
    profile.phones = {
        "+15035550142": {
            "e164": "+15035550142", "region": "US", "location": "Portland, OR",
            "carrier": "unknown", "line_type": "mobile", "valid": True,
            "timezones": ["America/Los_Angeles"],
        }
    }
    profile.breaches = [{
        "source": "Have I Been Pwned", "identifier": "alex.rivera@example.com",
        "name": "ExampleForum", "date": "2019-04-02",
        "data": ["Email addresses", "Passwords"],
        "meaning": "account exposed in this breach; rotate credentials and enable MFA",
    }]
    profile.runs = [
        ToolRun("maigret", SUBJECT, True, 14.2, found=7),
        ToolRun("sherlock", SUBJECT, True, 18.9, found=6),
        ToolRun("user-scanner", SUBJECT, True, 11.4, found=5, inconclusive=4),
        ToolRun("holehe", "alex.rivera@example.com", True, 6.1, found=0, inconclusive=61),
        ToolRun("gravatar", "alex.rivera@example.com", True, 0.2, found=0),
        ToolRun("phone", "+15035550142", True, 0.1, found=0),
    ]
    profile.gaps = {
        "user-scanner": {"Cloudflare challenge, cannot be solved without a browser": 2,
                         "Unexpected status: 403": 2},
        "holehe": {"rate limited — no signal, not a negative": 61},
    }

    score_accounts(profile)
    harvest_identity(profile)
    apply_corroboration(profile)
    cluster_personas(profile)
    summarize_gaps(profile)
    return profile


if __name__ == "__main__":
    profile = build()
    out = pathlib.Path(__file__).resolve().parents[1] / "examples" / "sample-report.html"
    out.write_text(render_html(profile, {
        "run_id": "0000example0", "case": "DEMO-1", "operator": "analyst",
        "basis": "synthetic data for documentation", "version": "1.0.0",
        "passive": True,
    }, 0.0))
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"accounts: {len(profile.accounts)}  "
          f"personas: {[p['name'] for p in profile.personas]}")
