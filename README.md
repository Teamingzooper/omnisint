```
 ▄██████▄  ▄▄       ▄▄ ▄▄     ▄▄ ▄▄   ▄███████ ▄▄ ▄▄     ▄▄ ██████████
 ██▀    ▀█ ███▄   ▄███ ███▄   ██ ██   ██▀      ██ ███▄   ██     ██
 ██  ◉   █ ██ ▀███▀ ██ ██ ▀█▄ ██ ██   ▀██████▄ ██ ██ ▀█▄ ██     ██
 ██▄    ▄█ ██   ▀   ██ ██   ▀███ ██        ▀██ ██ ██   ▀███     ██
 ▀██████▀  ▀▀       ▀▀ ▀▀     ▀▀ ▀▀   ███████▀ ▀▀ ▀▀     ▀▀     ▀▀

 every source · one profile
```

# Omnisint

*omniscient + OSINT.* One command that runs every OSINT tool on your machine
against a name, username, email, phone or domain, then **correlates the
results into a single profile** instead of leaving you to diff eight terminal
windows by hand.

**Brand:** the mark is an eye built from the `O` — the all-seeing reading of
*omniscient*. The wordmark weights **OMNI** solid and `SINT` outlined so the
seam of the portmanteau stays visible. Cyan reads as instrumentation, magenta
marks identity and corroboration, amber is caution, red is exposure — used
consistently in the terminal and in the HTML report. Three wordmark sizes ship
so the banner never wraps: full, compact, and `◉ OMNISINT`.

## Start here

```bash
omnisint
```

That drops you into the console. Type everything you have and press Enter:

```
◉ alex rivera, mjs, mjs@example.com, +14155550100
  + alex rivera  → name   — used to confirm identity
  + mjs                  → username
  + mjs@example.com      → email
  + +14155550100         → phone
  Press Enter to scan, or add more.

◉ sec Acme Corp, MIT, Portland
  ± Acme Corp   → secondary (cross-check only)
  ± MIT         → secondary (cross-check only)
  ± Portland    → secondary (cross-check only)

◉
▸ scanning 4 identifier(s) · 11 task(s) · quick · passive
  ✔ maigret → mjs (22 hits, 13.5s)
  ✔ sherlock → mjs (92 hits, 17.3s)
```

Then the report opens in a full-screen browser you page through with the
arrow keys — not one endless wall of text.

## The web UI

```bash
omni web            # or `web` from inside the console
```

Opens a local UI in your browser: Windows 98 chrome over a Wireshark-style
data grid, because a few hundred findings are still best read as a dense
sortable table with coloured rows.

```
┌ Omnisint — torvalds ────────────────────────────────────────────── _ □ ✕ ┐
│ Scan  View  Tools  Help                                                   │
│ [torvalds; Linux Foundation, Portland] [▶ Scan] Depth[quick▾] □breach     │
├──────────┬────────────────────────────────────────────────────────────────┤
│ Targets  │ Accounts(135) Identity(16) Identities(15) Discovered(2) Tools  │
│ Identities│ Exists Same? Platform    URL                    Sources        │
│ Scan log │   97%  ✔95%  Github      github.com/torvalds    maig,sher,user │
│          │   97%  ✖20%  Instagram   instagram.com/torvalds maig,user      │
├──────────┴────────────────────────────────────────────────────────────────┤
│ Detail — Github                                                           │
│ ▼ Fields returned                                                         │
│    company: Linux Foundation    location: Portland, OR                    │
└───────────────────────────────────────────────────────────────────────────┘
```

### Stacking accounts into one identity

Each account row has a **+**. Pressing it says *this account is my subject* —
and that is treated as your judgement, not a tool's conclusion: pinned
accounts are labelled "confirmed by you" everywhere, and the report records
that the attribution came from you.

Press **⟳ Rescan** and the confirmed accounts become anchors:

| From the pinned account | Becomes |
|---|---|
| its handle | a target searched in its own right |
| its real name | the anchor persona clustering matches against |
| its employer / school / location | secondary cross-check terms |

So confirming one GitHub profile turns the next scan from "find `torvalds`"
into "find `torvalds` and `Linus Torvalds`, cross-checked against Linux
Foundation and Portland, OR" — which is what actually resolves a shared
handle.

### What they do

The Identity tab opens with a characterisation inferred from *which*
platforms the subject is on and what their bios say:

```
Most active in software development (2 accounts: GitHub, GitHubGist).
also social / messaging (1). accounts created 2011–2017.
  Employers: Linux Foundation
  Locations: Portland, OR
  software development  ████████████████████ 2
  social / messaging    ██████████           1
Based on 4 accounts attributed to your subject.
```

Eight code-hosting accounts and a Kaggle profile say something a list of URLs
does not. It maps ~300 platforms onto interest areas, ignores the ones
everybody has (Gravatar, Linktree), and pulls roles, employers, schools,
locations and frequent bio terms out of the profile fields.

**It only ever summarises accounts believed to be one person** — pinned
first, then those attributed to your subject, then the primary identity. If
nothing is attributed yet it says so instead of guessing, because
characterising a handle that 92 people share would produce confident
nonsense. The scope it used is printed underneath every time.

The same summary appears in the terminal viewer ("What they do") and in the
Markdown and HTML exports.

Rows are coloured the way Wireshark colours packets: **green** = corroborated
as your subject, **red** = probably a different person, yellow/blue = weaker
existence evidence. Click any row to see every field a tool returned in the
detail pane. Columns sort. Discovered identifiers pop a dialog offering to
queue them for the next scan.

**It is loopback-only and token-gated.** Any page in your browser can reach
`localhost`, so the token in the URL is what stops an unrelated tab from
driving the server or reading your results — treat the URL as a credential.
Binding to anything other than `127.0.0.1` is refused outright: the UI has no
login and serves personal data. Tunnel over SSH if you need it elsewhere. The
authorisation gate and audit log apply exactly as they do in the console, and
nothing is written to disk until you press Export.

## Primary vs secondary input

**Primary** identifies the person and gets searched: names, handles, emails,
phone numbers, domains.

**Secondary** is what you know *about* them — employer, school, city, band.
These are **never searched**. Searching "Acme Corp" across 3000 username
databases is worthless; finding it in the bio of an account a username
already surfaced is decisive. So secondary terms are matched only against
what the primaries bring back. It is both faster and far more reliable.

```
◉ sec Acme Corp, MIT
```

An account whose bio names the employer you supplied is marked `± Acme Corp`
and promoted to **same person**. That beats any amount of handle matching.

## Reading the report

`j`/`l` move between sections and `i`/`k` scroll — the right-hand equivalent
of WASD, which also works. Arrow keys do the same. `space` pages, number keys
jump straight to a section, `e` exports, `q` returns to the prompt.

Letter keys are the reliable path: some terminals send arrows as SS3
(`ESC O A`) rather than CSI (`ESC [ A`), and multiplexers vary. Both are
handled, but `ijkl` never depends on escape sequences arriving at all.

```
 Overview  Identity 7  Identities 2 flagged  Accounts 136  Full data 41 …
```

| Section | What it answers |
|---|---|
| Overview | how many accounts, how many are actually your subject |
| Identity | names, locations, bios, avatars, and where each was seen |
| Identities | the distinct *people* sharing these identifiers |
| Accounts | every hit, scored for existence and attribution |
| Full data | every field every tool returned |
| Existence only | hits with no extractable data |
| Infrastructure | WHOIS, MX, DNS, phone metadata |
| Breaches | stealer-log and breach exposure |
| Tools | what ran, what failed, what timed out |
| Caveats | everything unchecked, rate-limited, or uncertain |

`q` closes the report and returns you to the prompt, with a one-line recap so
you can see what you found without reopening it:

```
torvalds — 136 accounts · 4 likely your subject · 17 likely other people
  identity: Alex Rivera
  view reopen report · export save to disk · sec <term> add a cross-check · drop all start over
```

Nothing is written to disk unless you ask. `export [dir]` writes JSON + HTML
+ Markdown (mode 600) to `~/omnisint-reports/` or a directory you name.

**Ctrl-C** cancels the current line, or aborts a running scan and hands you
back the prompt with your identifiers still loaded. It does not exit — `quit`
does that. A scan you interrupt is marked as partial in the report, because
tools that never finished contributed nothing, which is not the same as them
finding nothing.

## Depth

| | |
|---|---|
| `-q` / `quick` | top 50 sites — mainstream platforms, back in seconds |
| `-s` / `standard` | top 500 sites per tool (default) |
| `-d` / `deep` | every site in every database, plus a pivot hop |
| `-v` / `verbose` | per-site detail, tool errors, full caveat list |

These work as launch flags (`omnisint -q`) and as console commands.

## Following what a scan finds

Scans surface new identifiers — an email on a GitHub profile, a linked handle
on Keybase. Those are the strongest leads a scan produces and the easiest to
miss in a long report, so they are offered explicitly when the report closes:

```
3 new identifier(s) found during this scan
  1. jdoe@noreply.codeberg.org  (email, via user-scanner:Codeberg)
  2. j_doe                      (username, via maigret:Keybase)
  3. jdoe2                      (username, via maigret:GitHub)

Search these too? [y]es / [n]o / numbers (e.g. 1,3):
```

Emails are listed first — an address is a far stronger lead than a handle
scraped off a profile page. Declining is remembered, so you are not asked
about the same ones after every scan; `found` re-opens the list. It asks
rather than pivoting automatically because each extra identifier multiplies
the next scan's cost, and some of what turns up is junk.

Other console commands: `sec`, `show`, `drop`, `expand`, `pivot N`, `found`,
`set <opt> <val>`, `opts`, `tools`, `view`, `export`, `help`, `quit`.
Bare Enter scans whatever is loaded.

## Scripted use

```bash
omnisint scan johndoe
omnisint scan john@example.com
omnisint scan johndoe john@example.com --pivot 1 --html dossier.html
```

## What it wraps

| Backend | Input | Trust | What it contributes |
|---|---|---|---|
| **maigret** | username | 0.70 | 3000+ sites, and it *parses profiles* — names, locations, follower counts, linked IDs |
| **sherlock** | username | 0.45 | 400+ sites, high recall, high false-positive rate |
| **user-scanner** | username, email | 0.68 | 400+ vectors with profile metadata and avatars |
| **holehe** | email | 0.72 | which sites have an account registered to an address |
| **gravatar** | email | 0.90 | subject-published profile + self-declared linked accounts |
| **hudsonrock** | username, email | 0.80 | infostealer-malware breach exposure |
| **infrastructure** | email, domain | — | WHOIS, MX, NS, SPF — is this a real domain or a throwaway mailbox? |
| **hibp** | email | — | breach exposure (set `HIBP_API_KEY`) |
| **phone** | phone | — | offline number parsing: country, carrier, line type, timezone |
| **toutatis** | username | 0.85 | Instagram detail incl. obfuscated email/phone (needs `TOUTATIS_SESSION_ID`) |
| **darkweb** | username, email | 0.50 | hidden-service index search — opt-in, needs Tor and `--darkweb` |

Missing backends are skipped, never fatal. `omnisint tools` shows what is installed.

## The two questions

Every tool in this stack answers **"does this handle exist here?"** None of
them answer **"is it your subject?"** Conflating those is how OSINT gets the
wrong person hurt, so the report scores them separately:

```
Exists   Same?      Platform     URL
  97%    ✔ 90%      GitHub       https://github.com/riverdale
  97%    ✖ 20%      Instagram    https://www.instagram.com/riverdale/
```

Both accounts certainly exist. The second belongs to someone else — the
scrape returned a different name. A tool that reported both at 97% and
stopped there would be actively misleading.

**Persona disambiguation** clusters accounts by the names they expose and
flags the ones that don't match:

```
Identity          Role                   Platforms
Alex Rivera       primary                GitHub, GitLab, Mastodon, Keybase
Dana Okonkwo      likely someone else    Instagram, Pinterest
Sam Lindqvist     likely someone else    Medium
```

On a real 136-account run, 18 accounts were flagged as probably different
people. If no name is better corroborated than the rest, the tool declines to
pick a primary and says so rather than guessing.

## Names

A name is not searchable, but it is the best anchor you have. Supply one and
persona clustering picks the primary identity by matching it, instead of
guessing from corroboration counts. `expand` additionally turns a name into
the handles people actually pick (`alexrivera`, `a.rivera`,
`arivera`, …) and searches those — clearly labelled as guesses.

Primary identity is chosen from the strongest evidence available, in order:

1. an account matched a **secondary term** you supplied
2. an account's name matches a **name** you supplied
3. one name is **corroborated on more platforms** than any other

If none of those hold, no primary is assigned and the report says so.

## How confidence is computed

Sources are combined with a discounted noisy-OR. They are *not* treated as
independent — most decide "exists" from an HTTP status code, so they share
their false positives:

| Agreeing sources | Score |
|---|---|
| sherlock alone | 0.45 |
| sherlock + user-scanner | 0.76 |
| + maigret | 0.84 |

Nothing ever reaches certainty. A parsed profile body adds a small bonus,
because rendered profile fields prove something is actually there in a way a
status code does not.

## Silence is not absence

A tool that got rate-limited on every site has told you *nothing*, and left
unsaid that silence reads as "clean". Inconclusive results are tracked apart
from negatives and reported:

```
holehe: NO USABLE SIGNAL — 116 site(s) returned no verdict and nothing was
found (rate limited ×116). Treat this tool as having not run: absence here
is not evidence of absence.
```

## Ethics, and why they are enforced in code

- **Authorisation gate.** The first scan requires you to confirm a lawful
  basis. Non-interactively, `--i-have-authorization --basis "…"`. It is
  recorded, not just displayed.
- **Audit trail.** Every scan writes to `~/.omnisint/audit.jsonl`:
  operator, targets, adapters, case reference, counts. `omnisint audit` reads
  it back. This is what makes an investigation defensible afterwards.
- **Passive by default.** `holehe` runs with `-NP` so no password-recovery
  mail reaches the subject. An investigation should not be visible to its
  target. `--active` lifts this and warns you.
- **NSFW site lists off** unless `--nsfw`.
- **Reports are chmod 600**, because a dossier is sensitive personal data.

None of this stops a determined misuser. It does mean misuse has to be
deliberate, and leaves a record.

## Usage

```bash
omnisint                              # interactive console
omnisint tools                         # what is installed
omnisint scan <target> [...]           # scan; type is auto-detected
omnisint audit                         # read the audit log
```

Scope: `--deep` (all sites), `--top-sites N`, `--pivot N` (follow discovered
identifiers N hops), `--pivot-limit N`, `--nsfw`
Tools: `--only a,b`, `--exclude a,b`, `--active`
Network: `--timeout`, `--tool-timeout`, `--workers`, `--proxy`, `--tor`, `--delay`
Output: `--json F`, `--html F`, `--markdown F`, `--min-confidence`, `--show-all`, `--keep-raw`, `--dry-run`

`--pivot` is where scans explode: an email found on one platform becomes a
new seed for every email-capable tool. `--pivot-limit` (default 5) caps the
fan-out per hop, and the report tells you what it chose not to follow.

## Sample output

[`examples/sample-report.html`](examples/sample-report.html) is a rendered
report built from **entirely fictional data** — regenerate it with
`python3 examples/make_sample.py`.

Real scan output is never committed here, and you should not commit yours
either. A report is personal data about real people, and in a username
collision it describes people who have nothing to do with your subject.
`.gitignore` excludes `omnisint-reports/` and the tools' raw output files
for exactly this reason.

## Install

```bash
git clone https://github.com/Teamingzooper/omnisint
cd omnisint
pip install -e .
```

That gives you `omnisint` (and the shorter `omni`) plus three built-in
backends — Gravatar, WHOIS/DNS and phone parsing. Everything else is an
external tool you install separately.

## Installing the backends

Omnisint drives other people's tools rather than reimplementing them.
**Every backend is optional**: missing ones are skipped with a note, never a
crash. Run `omnisint tools` at any time to see what is present and get the
exact command for anything that is not.

### Everything at once

```bash
pip install maigret sherlock-project holehe user-scanner phonenumbers toutatis onionsearch
```

### One at a time

| Backend | Install | Also needs |
|---|---|---|
| [maigret](https://github.com/soxoj/maigret) | `pip install maigret` | — |
| [sherlock](https://github.com/sherlock-project/sherlock) | `pip install sherlock-project` | — |
| [holehe](https://github.com/megadose/holehe) | `pip install holehe` | — |
| [user-scanner](https://github.com/kaifcodec/user-scanner) | `pip install user-scanner` | — |
| [phonenumbers](https://github.com/daviddrysdale/python-phonenumbers) | `pip install phonenumbers` | — |
| [toutatis](https://github.com/megadose/toutatis) | `pip install toutatis` | `export TOUTATIS_SESSION_ID=…` |
| [OnionSearch](https://github.com/megadose/OnionSearch) | `pip install onionsearch` | Tor, and the `--darkweb` flag |
| [Have I Been Pwned](https://haveibeenpwned.com/API/v3) | built in | `export HIBP_API_KEY=…` (paid) |

> **`pip install sherlock` installs the wrong package.** There is an
> unrelated project squatting that name on PyPI. The one you want is
> **`sherlock-project`**. On macOS `brew install sherlock` also works.

### The ones with extra requirements

**toutatis** reads Instagram profile detail — including the obfuscated
recovery email and phone — which needs a logged-in session:

```bash
export TOUTATIS_SESSION_ID="<your Instagram sessionid cookie>"
```

This uses *your* Instagram session against Instagram's terms, so it stays
inert until you set that yourself. It is never enabled by default.

**OnionSearch** searches hidden-service indexes and needs a local Tor proxy:

```bash
pip install onionsearch
brew install tor && brew services start tor    # or: sudo apt install tor
omnisint scan jdoe --darkweb
```

It is opt-in twice over — excluded from the default set *and* gated behind
`--darkweb` — because it is slow and scraping onion indexes should be a
deliberate act.

**Have I Been Pwned** needs a paid API key from
[haveibeenpwned.com/API/Key](https://haveibeenpwned.com/API/Key):

```bash
export HIBP_API_KEY="…"
```

### Checking what you have

```bash
omnisint tools
```

```
2 backend(s) not ready. Missing backends are skipped, never fatal.

  toutatis — Instagram detail incl. obfuscated email/phone
      pip install toutatis
      then: export TOUTATIS_SESSION_ID=<your Instagram sessionid cookie>
      https://github.com/megadose/toutatis
```

### A note on trusting these

Each of these runs on your machine with your network access, and several
have hundreds of transitive dependencies. Every link above goes to the
upstream project so you can read what you are installing. Consider a
virtualenv:

```bash
python3 -m venv ~/.venvs/omnisint
source ~/.venvs/omnisint/bin/activate
pip install -e . maigret sherlock-project holehe user-scanner phonenumbers
```

## Tests

```bash
python3 tests/test_logic.py
```

Covers identifier detection, platform normalisation, confidence combination
and the name-noise filters — the logic that decides what the operator ends up
believing.

## Limits

Findings are unverified third-party signals. Username collision is the norm,
not the exception. Scrapers return page titles that look like names. Sites
change their responses and every tool's site database rots. Treat anything
below `confirmed` + `same person` as a lead to verify by hand, never as a
fact to act on.
