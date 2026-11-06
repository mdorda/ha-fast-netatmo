# Netatmo (fast weather) for Home Assistant

[![Marketplace](https://img.shields.io/badge/Marketplace%20%2F%20HACS-Custom-41BDF5.svg)](https://www.home-assistant.io/integrations/marketplace/)
[![Validate](https://github.com/mdorda/ha-fast-netatmo/actions/workflows/validate.yml/badge.svg)](https://github.com/mdorda/ha-fast-netatmo/actions/workflows/validate.yml)

A Home Assistant integration for the **Netatmo Smart Weather Station**. It shows the main (indoor) station's values with a delay of **about 30 seconds**, configurable down to 10 seconds. The built-in Netatmo integration shows values that can be 10 to 20 minutes old.

- **Weather station only.** It runs next to the built-in [Netatmo integration](https://www.home-assistant.io/integrations/netatmo/). Thermostats, cameras, Home Coach and everything else stay in the built-in integration.
- **Uses the right endpoint.** It reads `/homestatus`, which returns near real-time values from the devices. The built-in integration reads `/getstationsdata`, which Netatmo refreshes only every 10 minutes.
- **Needs only read access.** It requests just the `read_station` permission.

## How fast is it?

Netatmo's modules send data at different rates. We measured a station (main station + outdoor module) for several minutes, polling every 5 and every 30 seconds:

| Module | How often the module sends data | Built-in integration | This integration (default settings) |
|---|---|---|---|
| Main station (indoor): temperature, humidity, CO₂, noise, pressure | every ~4 s. CO₂ itself changes only every 10–40 s. | up to 10 minutes old, plus its polling interval | at most ~30 s old |
| Outdoor module | every ~10 minutes | up to 10 minutes after the module sent it, plus its polling interval | within ~30 s after the module sent it |
| Wind gauge, rain gauge, additional indoor module | not measured, see [Known limitations](#known-limitations) | | within one polling interval after the module sent it |

So the big gain is for the **main station**, for example for CO₂-controlled ventilation. Radio modules such as the outdoor module only send a new value every few minutes; this integration shows it sooner, but it can't make the module measure more often.

To see how old a value is, enable the **Last measurement** sensor of the module (see [Entities](#entities)).

## Why this exists

The built-in integration reads weather station data from `/getstationsdata`. Netatmo's API documentation says:

> /getstationsdata retrieves data from the cloud where data are updated every 10min whereas /homestatus retrieves data from the devices and data are near realtime data (<10s).
>
> — [Netatmo Weather API](https://dev.netatmo.com/apidocumentation/weather#homestatus), quoted in [home-assistant/core#152449](https://github.com/home-assistant/core/issues/152449#issuecomment-3574314295)

On top of that, the built-in integration polls weather data only every **300 s** with Home Assistant Cloud, or every **~85 s** with your own Netatmo app. Users report sensors that lag behind the Netatmo app by 10 to 20 minutes, sometimes by hours:

- [#152449](https://github.com/home-assistant/core/issues/152449) "Netatmo Weather Station - Interval update" (open, 150+ comments)
- [#151224](https://github.com/home-assistant/core/issues/151224) "Netatmo integration not refreshing properly"
- [#157049](https://github.com/home-assistant/core/issues/157049) "Netatmo integration seems to have API polling-rate issues"

The integration maintainer has [declined to change the polling frequency](https://github.com/home-assistant/core/issues/152449#issuecomment-4990006524), because of Netatmo's API rate limits. That is a reasonable decision for a built-in integration that everyone uses. This integration is for users who want faster weather data and are willing to set up their own Netatmo app.

### Why not read the station locally?

Netatmo offers no local API. Their [developer guidelines](https://dev.netatmo.com/guideline) say:

> Can I access data directly from the devices? It is not possible for the moment. The only way to access the data and the devices is via the Netatmo Cloud.

The station's HomeKit support doesn't help either. We logged a station connected through Home Assistant's HomeKit Device integration for 24 hours. Its CO₂, temperature and humidity values changed only every 10 minutes (08:15, 08:25, 08:35, …), the same cadence as `/getstationsdata`. Polling the Netatmo cloud via `/homestatus` is currently the only way to get fresh values.

## Netatmo API limits

Netatmo limits API calls ([developer guidelines](https://dev.netatmo.com/guideline)). An app with a single user, such as your own Netatmo app, gets the per-user limit: **500 requests per hour** and 50 requests per 10 seconds. Netatmo [confirmed this in 2025](https://helpcenter.netatmo.com/hc/en-us/community/posts/28272276247058).

With the default interval of 30 seconds, this integration makes about 120 `/homestatus` calls per hour for one home, plus 6 `/getstationsdata` calls per hour for trends and battery, and at most one `/homesdata` call per hour while the live data shows a different set of modules. At the minimum interval of 10 seconds it makes about 366 calls per hour. With several homes, the interval is stretched automatically (at least 10 seconds per home).

> [!IMPORTANT]
> Netatmo doesn't say whether the 500 requests per hour are counted per app or per account. **They may be shared with other integrations and apps that use the same Netatmo account**, for example the built-in Netatmo integration for your thermostat. If you use them and lower the interval, keep an eye on the total.

## Requirements

- Home Assistant 2026.10 or newer.
- The [Marketplace](https://www.home-assistant.io/integrations/marketplace/), built into Home Assistant 2026.11 and newer. On Home Assistant 2026.10, [HACS](https://hacs.xyz/) instead.
- **Your own Netatmo developer app.** This is required, not optional. Setting one up is free and takes a few minutes, see [Setup](#setup).

### Why you need your own Netatmo app

- **Home Assistant Cloud can't sign you in.** Home Assistant Cloud (Nabu Casa) provides Netatmo sign-in only for the built-in `netatmo` integration.
- **The two integrations can't share one app.** Netatmo issues new tokens on every refresh and invalidates the old ones. Two integrations signed in through the same app would keep logging each other out.
- **Home Assistant Cloud shares one app among all its users**, and that app hits Netatmo's limits regularly. Netatmo says your own app is ["not subject to this common rate limit"](https://helpcenter.netatmo.com/hc/en-us/community/posts/29846852785298).

## Installation

### Marketplace (recommended, Home Assistant 2026.11 and newer)

Since Home Assistant 2026.11, HACS is built in as the **Marketplace**. If you installed this integration through HACS before, it moved to the Marketplace automatically and keeps receiving updates.

1. Go to **Settings → Marketplace** and select **Add from link** in the upper-right corner. Adding a link requires a GitHub connection; the Marketplace asks you to connect if needed.
2. Under **GitHub link**, enter `https://github.com/mdorda/ha-fast-netatmo` and select **Add**. If asked for a **Type**, choose **Integration**.
3. Open **Netatmo (fast weather)**, select **Install** and confirm.
4. If Home Assistant asks for a restart (**Settings → System → Repairs**), restart it.

### HACS (Home Assistant 2026.10)

1. In Home Assistant, open **HACS**. From the **⋮** menu, choose **Custom repositories**.
2. Add `https://github.com/mdorda/ha-fast-netatmo` with the category **Integration**.
3. Search for **Netatmo (fast weather)**, open it and click **Download**.
4. Restart Home Assistant.

### Manual

1. Copy the `custom_components/fast_netatmo` folder into the `custom_components` folder of your Home Assistant configuration.
2. Restart Home Assistant.

## Setup

If you already use the built-in Netatmo integration for your weather station, read [Moving from the built-in integration](#moving-from-the-built-in-integration) **before** step 2, so your history continues.

### 1. Create a Netatmo app

1. Sign in at [dev.netatmo.com](https://dev.netatmo.com/) with your Netatmo account and open **My apps → Create**.
2. Fill in the form:
   - **App name:** pick a name that doesn't contain "Netatmo", for example `Home Assistant fast weather`. Netatmo's guidelines ask that app names don't imitate their brand.
   - **Redirect URI:** `https://my.home-assistant.io/redirect/oauth`
3. Save the app and copy its **client ID** and **client secret**.

Use a new app for this integration. Don't reuse the app of the built-in Netatmo integration or of any other tool.

### 2. Add the integration

1. Go to **Settings → Devices & services → Add integration** and choose **Netatmo (fast weather)**.
2. When asked for application credentials, enter the client ID and client secret from step 1.
3. Home Assistant opens the Netatmo sign-in page. Sign in and allow access. Only `read_station` (read weather station data) is requested.
4. You are redirected back to Home Assistant, and your weather station appears as devices with sensors. The integration entry is named after your Netatmo home; your e-mail address is not stored.

The browser you use for step 3 must be able to reach your Home Assistant instance.

## Options

Open **Settings → Devices & services → Netatmo (fast weather) → Configure**. Saving reloads the integration.

| Option | Default | Range | What it does |
|---|---|---|---|
| Polling interval | 30 s | 10–600 s | How often live values are read. The main station sends data every few seconds, but CO₂ changes only every 10–40 s, so going below 30 s brings little. Lower values use more of the [API limit](#netatmo-api-limits). With several homes, the interval is at least 10 s per home. |
| Grace period | 5 min | 0–60 min | How long sensors keep their last value when Netatmo doesn't respond, or answers with an error for the module instead of its data (this happens when Netatmo is overloaded). After that, they become unavailable, so a stale value is never shown for long. 0 makes them unavailable at the first failed call. |
| Reload on module changes | on | on/off | When live data shows a module that was added to or removed from your station, the integration checks the module list with Netatmo (at most once an hour) and, if confirmed, reloads itself, so new modules get their sensors. Turn it off to reload by hand; a change is then only logged. |

## Moving from the built-in integration

The built-in integration keeps handling your thermostats, cameras and other devices; only the weather station moves. This integration uses the same device and entity names as the built-in one, so its sensors get the same entity IDs, and Home Assistant keeps their history, long-term statistics and dashboard cards.

1. In the built-in Netatmo integration, open each weather station device (the station and each of its modules). From the **⋮** menu, choose **Disable**.
   - Disabled devices are not polled, so the built-in integration stops calling `/getstationsdata`.
   - Disable the device rather than its entities. A disabled device also keeps any entity the built-in integration recreates later disabled.
2. Delete the entities of those devices: **Settings → Entities**, filter by the devices, select the entities, **Delete**.
3. Add this integration ([Setup](#setup), step 2). Its entities get the old entity IDs, for example `sensor.weather_station_temperature`.

**If you already added this integration**, its entities have IDs ending in `_2`. For each sensor:
1. Note the old entity ID, for example `sensor.living_room_temperature`.
2. Delete the old, now disabled, entity: **Settings → Entities**, select it, **Delete**.
3. Rename the new entity to the old entity ID.

Sensors that the built-in integration doesn't have (absolute pressure, last measurement) start with an empty history.

## Entities

Every module is a device. Sensors marked "off" are disabled by default; enable them on the device page.

| Module | Enabled by default | Disabled by default |
|---|---|---|
| Main station (NAMain) | temperature, humidity, CO₂, noise, pressure | absolute pressure, temperature trend, pressure trend, Wi-Fi strength, last measurement |
| Outdoor module (NAModule1) | temperature, humidity, battery | temperature trend, RF strength, reachability, last measurement |
| Wind gauge (NAModule2) | wind speed, wind direction, battery | wind angle, gust strength, gust direction, gust angle, RF strength, reachability, last measurement |
| Rain gauge (NAModule3) | precipitation, precipitation today, battery | precipitation last hour, RF strength, reachability, last measurement |
| Additional indoor module (NAModule4) | temperature, humidity, CO₂, battery | temperature trend, RF strength, reachability, last measurement |

- **Trends and battery** come from `/getstationsdata` and update every 10 minutes.
- **Wi-Fi and RF strength** show Netatmo's own rating (very low, low, medium, high, full), the same as in the Netatmo app.
- **Last measurement** is when the module last sent data. Use it to see whether a value is fresh.
- When a module is unreachable, its measurements become unavailable. Battery, signal, reachability and last measurement stay available.

## Known limitations

- **Only the main station and the outdoor module are tested on real hardware.** The wind gauge, the rain gauge and additional indoor modules are implemented from Netatmo's API responses as published by other projects, but not tested. If you have one, please [report](https://github.com/mdorda/ha-fast-netatmo/issues) whether its sensors work; the debug log (see [Troubleshooting](#troubleshooting)) lists any data the integration doesn't use yet.
- **Trends and battery update every 10 minutes.** `/homestatus` doesn't report trends and reports battery only roughly, so they come from `/getstationsdata`.
- **Weather station only.** Home Coach, thermostats, cameras and all other Netatmo devices are not supported. Use the built-in integration for them.
- **Cloud dependent.** Netatmo offers no local API (see [Why not read the station locally?](#why-not-read-the-station-locally)).

## Troubleshooting

- **Home Assistant asks you to re-authenticate.** Your Netatmo authorization was revoked or has expired. Open the notification and sign in again with the same Netatmo account; you don't need to create a new Netatmo app.
- **Sensors are unavailable.** Check that the module is reachable in the Netatmo app. Short Netatmo outages are bridged by the [grace period](#options); after it, sensors become unavailable until Netatmo answers again.
- **What happens after errors.** After a failed call, the integration waits twice the polling interval before the next one. If Netatmo asks for a longer pause (`Retry-After`), it waits that long, at most one hour.
- **Values don't change.** Enable the **Last measurement** sensor of the module. If it doesn't change either, the module isn't sending new data. Remember that radio modules send only every few minutes.
- **Errors "User usage reached" (code 26) persist even though the integration makes few calls.** Netatmo users have reported quota errors that stay for hours. What helped: remove the app's access at [home.netatmo.com → Settings → My account](https://home.netatmo.com/settings/my-account), then re-authenticate in Home Assistant.
- **Errors "Failed to enter concurrency limited section" (code 11).** Netatmo is overloaded; it is not about your usage. The integration retries automatically.
- **Debug log "/homestatus reports errors for ['NAMain', 'NAModule1'] (codes ['2'])".** Netatmo is overloaded and sends an error for the station instead of its data. Code 2 here has nothing to do with your access token. The sensors keep their last value for the [grace period](#options); when no module has data, the integration waits twice the interval, as after any other error.

To see each API call and how long it takes, enable debug logging:

```yaml
logger:
  default: warning
  logs:
    custom_components.fast_netatmo: debug
```

When reporting an issue, attach the diagnostics: **Settings → Devices & services → Netatmo (fast weather) → ⋮ → Download diagnostics**. Tokens, names, your e-mail address and location are removed, and IDs are replaced by aliases.

## Removal

1. Go to **Settings → Devices & services → Netatmo (fast weather)** and delete the integration.
2. Uninstall it in the **Marketplace** (or **HACS** on Home Assistant 2026.10), or delete `custom_components/fast_netatmo`, and restart Home Assistant.
3. Optionally, delete the app at [dev.netatmo.com](https://dev.netatmo.com/) under **My apps**. This also revokes its access to your account.
4. If you disabled weather station devices in the built-in Netatmo integration, enable them again.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions made with AI agents are welcome.

## Credits

- The [Home Assistant Netatmo integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/netatmo) by [@cgtobi](https://github.com/cgtobi) and the Home Assistant contributors. The OAuth setup, sensor definitions and translations are based on it.
- [@tiimjcb](https://github.com/tiimjcb), who analysed the problem and first proposed switching weather data to `/homestatus` in [home-assistant/core#152449](https://github.com/home-assistant/core/issues/152449).

This project is not affiliated with Netatmo or Home Assistant.

## License

Apache License 2.0. See [LICENSE](LICENSE).
