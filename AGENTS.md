# Agent guide

Essential context for AI agents working on this repository. Read it before changing anything.

## What this is

A Home Assistant custom integration, domain `fast_netatmo`, for the **Netatmo Smart Weather Station only** (NAMain, NAModule1–4). It reads live values from Netatmo's `/homestatus` endpoint and runs alongside the built-in `netatmo` integration, which keeps handling everything else.

Boundaries. Don't change these without the owner's explicit agreement:

- **Weather station only.** Never add thermostats, cameras, Home Coach or other devices.
- **No Python requirements.** `manifest.json` has `"requirements": []`. Don't add pyatmo or anything else: the built-in integration pins pyatmo, and two versions in one environment conflict.
- **OAuth scope `read_station` only**, with the user's own Netatmo app. No Home Assistant Cloud, no webhooks.
- **No personal data** in config entry data, title, unique ID, logs at info level or above, diagnostics, test fixtures or anywhere in the repo. No e-mail addresses, real IDs, names or locations.
- **Minimum Home Assistant 2026.10.** Don't add compatibility code for older versions.

## Layout

```
custom_components/fast_netatmo/
  __init__.py        setup/unload, device removal hook
  api.py             HTTP client (form POST + bearer token), error mapping, response parsing
  coordinator.py     polling, backoff, grace period, slow fetch, topology change detection
  entity.py          device registration, base entity
  sensor.py          sensor descriptions and entity
  config_flow.py     OAuth flow, reauth, options flow
  diagnostics.py     redaction and ID aliases
  const.py           constants, option defaults and ranges
  translations/      en.json is the source; no strings.json
  brand/             icon PNGs and their SVG sources
tests/
  conftest.py        FakeNetatmo: mocks api.netatmo.com at the HTTP level
  fixtures/          anonymized real API responses
```

## Commands

```bash
uv venv -p 3.14 .venv && source .venv/bin/activate
uv pip install -r requirements_test.txt
ruff check . && ruff format --check . && mypy && pytest --cov
```

## Merge criteria (CI)

`.github/workflows/validate.yml` must be fully green:

- hassfest and HACS validation,
- `ruff check`, `ruff format --check`, `mypy` (strict),
- `CHANGELOG.md` has a section and link for the manifest version,
- tests against the minimum Home Assistant (pinned in `requirements_test.txt`) **and** the latest release, with **coverage ≥ 95 %**.

Add tests for every behaviour change. Mock the API through `FakeNetatmo` (HTTP level), not by patching the client.

## Invariants

- **Map Netatmo errors by `error.code`, never by HTTP status alone.** Codes 2, 3, -1 and 30 (or a 401 without a code) are auth errors and start reauth. Everything else is a normal error. Netatmo returns code 2 with HTTP 403 although its docs say 401, and code 26 with both 403 and 429.
- **Backoff:** after a normal error, the next poll waits 2× the interval, or the `Retry-After` value if it is longer (that value is capped at 1 hour). Repeated errors keep the same delay; it doesn't escalate. Don't add exponential backoff: this behaviour is proven in production.
- **Rate budget:** Netatmo allows a single-user app 500 calls per hour, possibly shared with other apps on the same account.
  - `/homestatus` is polled once per home per interval, with the interval at least 10 s per home.
  - `/getstationsdata` runs every 10 minutes.
  - A guard delays polls when the client made more than 400 calls in the last hour.
  - Never add calls to the polling loop without recalculating this budget.
- **Grace period:** on errors the coordinator keeps the last data until the grace period expires, then raises `UpdateFailed`. Auth errors bypass it.
- **Entity names follow the built-in integration** (same device names, translation keys and enabled defaults). Entity IDs must match core so that users keep their history. Don't rename translation keys or device names.
- **Measurements of an unreachable module are unavailable;** battery, signal, reachability and last measurement stay available.
- **Translations:** copy names that core has from core; add a new string only in languages where it is certain.
- **README must match behaviour.** When you change intervals, options, entities, errors or limits, update `README.md` and `CHANGELOG.md` (`[Unreleased]`) in the same change.
- **Untested hardware:** NAModule2/3/4 keys come from pyatmo, not from real devices. Missing keys must give `unknown`, never an exception.

## Git and releases

- Don't commit, push, tag or create releases unless the owner asks. The owner does git writes.
- Releases run through **Actions → Release** (see `CONTRIBUTING.md`); never tag by hand.

## Pull requests by agents

The **last line of the pull request description** must disclose agent work, naming the agent and the model, for example:

```
Written by an agent (Claude Code, claude-opus-5-5).
```
