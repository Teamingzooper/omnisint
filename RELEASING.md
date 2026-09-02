# Releasing

Publishing runs on GitHub Actions via **trusted publishing** (OIDC), so there
is no PyPI API token to create, store, or leak.

## One-time setup on PyPI

This cannot be done from the repository — it has to be done in your PyPI
account, once, before the first release.

1. Sign in at <https://pypi.org> (create an account if needed, and enable 2FA
   — PyPI requires it for publishing).
2. Go to **Your projects → Publishing**, or directly to
   <https://pypi.org/manage/account/publishing/>.
3. Under **Add a new pending publisher**, fill in:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `omnisint` |
   | Owner | `Teamingzooper` |
   | Repository name | `omnisint` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   "Pending publisher" is the right choice while the project does not exist
   on PyPI yet; it becomes a normal publisher on first upload.

4. In GitHub, go to **Settings → Environments → New environment**, name it
   `pypi`. Optionally add a required reviewer so a release cannot publish
   without a human approving it — worth doing, since a version on PyPI can
   be yanked but never replaced.

## Cutting a release

```bash
# 1. Bump the version — the workflow refuses to publish if it disagrees
#    with the tag.
$EDITOR pyproject.toml          # version = "1.1.0"
$EDITOR omnisint/__init__.py    # __version__ = "1.1.0"

# 2. Confirm it builds and passes locally.
python tests/test_logic.py && python tests/test_web.py
python -m build && python -m twine check dist/*

git commit -am "Release 1.1.0" && git push

# 3. Tag and publish a GitHub Release. Publishing it triggers the workflow.
gh release create v1.1.0 --generate-notes
```

The workflow then runs the tests, builds, checks the metadata renders,
verifies the wheel actually contains the web UI, checks the tag matches the
packaged version, and only then publishes.

## What the guards are for

- **Tests gate the build.** A release is the worst time to discover a broken
  test, and PyPI versions are immutable.
- **The wheel is inspected for `omnisint/web/static/*`.** Those are data
  files rather than modules, so they can go missing from a wheel without
  anything failing loudly — `omni web` would then serve a 404 to every user.
- **Tag and version must agree.** Otherwise `pip install omnisint==1.1.0`
  quietly installs something labelled differently from the release notes.

## Verifying a published release

```bash
python -m venv /tmp/check && /tmp/check/bin/pip install omnisint
/tmp/check/bin/omnisint tools     # backends missing is correct and expected
/tmp/check/bin/omnisint --version
```

A base install deliberately pulls only `rich`, `dnspython` and
`phonenumbers`. The scanning backends are external tools the user chooses to
install — see the install table in the README.
