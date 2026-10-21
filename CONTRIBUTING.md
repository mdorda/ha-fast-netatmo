# Contributing

Thanks for helping with Netatmo (fast weather). Bug reports, tests with modules we don't have, translations and code are all welcome.

## Reporting issues

- Search the [existing issues](https://github.com/mdorda/ha-fast-netatmo/issues) first.
- Say which Home Assistant version and which Netatmo modules you have.
- Attach the diagnostics (**Settings → Devices & services → Netatmo (fast weather) → ⋮ → Download diagnostics**). Tokens, names, e-mail address and location are removed, but have a look before posting.
- For update problems, add the debug log (see the README, "Troubleshooting").

**Owners of a wind gauge (NAModule2), rain gauge (NAModule3) or additional indoor module (NAModule4):** these are not tested on real hardware. A report saying "works" or "doesn't work", with diagnostics, helps a lot.

## Development setup

You need Python 3.14 and, ideally, [uv](https://docs.astral.sh/uv/).

```bash
uv venv -p 3.14 .venv
source .venv/bin/activate
uv pip install -r requirements_test.txt
pre-commit install   # optional: run the checks before every commit
```

`requirements_test.txt` pins `pytest-homeassistant-custom-component` to the **minimum** Home Assistant version we support. CI also runs the tests against the latest release.

## Checks

Run these before opening a pull request. CI runs the same checks and must be green before merging.

```bash
ruff check .
ruff format --check .
mypy
pytest --cov
```

- Test coverage must stay at **95 % or more**; CI fails below that.
- The Netatmo API is mocked at the HTTP level (`tests/conftest.py`, `FakeNetatmo`). The responses in `tests/fixtures/` are anonymized real responses. **Never commit real tokens, IDs, names, e-mail addresses or locations.**
- CI also runs [hassfest](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) and the [HACS action](https://hacs.xyz/docs/publish/action/).

## Pull requests

- Keep a pull request focused on one change. No drive-by reformatting or unrelated refactors.
- Add or update tests for every behaviour change.
- Update `README.md` when user-visible behaviour changes, and add an entry under `[Unreleased]` in `CHANGELOG.md`.
- Don't add Python requirements to `manifest.json`. The integration has no dependencies on purpose, so it can't conflict with the built-in Netatmo integration.
- Stay within Netatmo's API budget: see "Rate budget" in [AGENTS.md](AGENTS.md).

### AI-assisted contributions

AI coding agents are welcome here; this project is developed with them too. But you, the contributor, are responsible for what you submit. An agent's output is a draft, not a finished pull request. Before submitting, make sure that:

- you understand the change and can answer review questions about it yourself,
- you ran the checks above locally and they pass,
- the pull request does only what it says.

Pull requests, issues and comments written with an agent must say so. **The last line of the pull request description** names the agent and the model, for example:

```
Written by an agent (Claude Code, claude-opus-5-5).
```

Agents should read [AGENTS.md](AGENTS.md) first.

## Translations

`custom_components/fast_netatmo/translations/en.json` is the source. There is no `strings.json`.

- Entity names that the built-in Netatmo integration has were copied from its translations. Keep them identical, because entity IDs are derived from the names.
- Only add a translation when you are sure of it. Missing keys fall back to English, which is better than a wrong translation.
- A new key goes into every language file where its translation is certain.

## Releases

Maintainers only:

1. In a pull request, set the new `version` in `custom_components/fast_netatmo/manifest.json` and rename `[Unreleased]` in `CHANGELOG.md` to `[X.Y.Z] - YYYY-MM-DD`, with a new link at the bottom. CI checks that both match.
2. Merge to `main`.
3. Run **Actions → Release → Run workflow** on `main`. It reruns all checks, then creates the tag `vX.Y.Z` and the GitHub release with the notes from `CHANGELOG.md`. If anything is wrong, it stops before publishing.
