# Third-party notices

Omnisint drives other people's tools and ships one third-party data set.

## Bundled data

**OSINT Framework** — `omnisint/data/osint-framework.json` is a curated
subset of the OSINT Framework catalogue.

- Source: https://github.com/lockfale/OSINT-Framework
- Copyright (c) 2017 Justin Nordine
- Licence: MIT

Curation (filtering, de-duplication, type routing, trimming) is Omnisint's;
the resource list and its metadata are the upstream project's work.
Regenerate with `python3 tools/build_catalog.py`.

## Tools driven, not bundled

These are invoked if present on your machine. Omnisint ships none of them,
and each carries its own licence and terms:

| Tool | Project |
|---|---|
| maigret | https://github.com/soxoj/maigret |
| sherlock | https://github.com/sherlock-project/sherlock |
| holehe | https://github.com/megadose/holehe |
| user-scanner | https://github.com/kaifcodec/user-scanner |
| toutatis | https://github.com/megadose/toutatis |
| OnionSearch | https://github.com/megadose/OnionSearch |
| SpiderFoot | https://github.com/smicallef/spiderfoot |
| phonenumbers | https://github.com/daviddrysdale/python-phonenumbers |

Using them through Omnisint does not change their terms of service. Several
query third-party sites directly; that is your request, made from your
machine, under your responsibility.
