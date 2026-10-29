# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.1] - 2026-10-29

### Changed

- The debug log names the types of modules that `/homestatus` reports in addition to, or without, the known modules, and every step of the `/homesdata` check described below.

### Fixed

- No more needless reloads while Netatmo is overloaded. A slow `/homestatus` can report a different set of modules for a few minutes; the integration now reloads only when `/homesdata` confirms the change, and checks it at most once an hour. Before, each such episode reloaded the integration, and sensors were unavailable for up to a minute and a half when `/homesdata` was unavailable too.

## [1.0.0] - 2026-10-21

First release. A separate integration for the Netatmo Smart Weather Station that runs alongside the built-in Netatmo integration.

### Added

- Live values from Netatmo's `/homestatus` endpoint. The main station sends new data every few seconds, and the integration polls every 30 s by default.
- Sensors for the main station (NAMain), the outdoor module (NAModule1), the wind gauge (NAModule2), the rain gauge (NAModule3) and additional indoor modules (NAModule4), including wind gust strength and direction.
- Temperature and pressure trends and battery level from `/getstationsdata`, every 10 minutes.
- A "Last measurement" diagnostic sensor per module, disabled by default.
- Options for the polling interval (10–600 s), a grace period during which sensors keep their last value when Netatmo doesn't respond (0–60 min), and automatic reloading when modules are added or removed.
- Backoff after API errors: the next attempt waits twice the interval, or longer if Netatmo sends a `Retry-After` header.
- Diagnostics with tokens, names, e-mail address and location removed and IDs replaced by aliases.
- Entity names and entity IDs match the built-in integration, so existing history continues after migration.

### Known limitations

- The wind gauge, the rain gauge and additional indoor modules have not been tested on real hardware.

[Unreleased]: https://github.com/mdorda/ha-fast-netatmo/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/mdorda/ha-fast-netatmo/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mdorda/ha-fast-netatmo/releases/tag/v1.0.0
