# AvianVisitors

*A live bird collage from your window.*

See it running at [bird.onethreenine.net](https://bird.onethreenine.net).

<img alt="avianvisitors collage" src="docs/thumb.png" />

---

## BOM

| Qty | Description | Price | Link | Notes |
|-----|-------------|-------|------| ----- |
| 1 | Raspberry Pi (4B / 5 / 3A+ / Zero 2W) | ~$25-80 | [Amazon](https://amzn.to/43yLDZJ) | [See note for 512 MB Pis](https://github.com/mcguirepr89/BirdNET-Pi/wiki/RPi0W2-Installation-Guide) |
| 1 | Micro SD Card (≥32 GB) | ~$10 | [Amazon](https://amzn.to/4eGy7te) | |
| 1 | USB lavalier microphone | $16.95 | [Amazon](https://amzn.to/4vLSaMK) | |
| 1 | Pi power supply | ~$10 | - | |

Optional: a [Gemini API key](https://aistudio.google.com/apikey) to restyle illustrations, an [eBird API key](https://ebird.org/api/keygen) to filter species by region.

### Kits

I offer the bird mic and the wall frame as separate electronics kits. I put up a store for some of my open-source projects and will soon be able to offer kits cheaper than buying all the components individually, once I start buying in bulk.

- [Bird mic kit](https://theodore.net/store/avian-mic/)
- [Frame kit](https://theodore.net/store/avian-visitors/)

---

## 1. Flash the SD card

Use [Raspberry Pi Imager](https://www.raspberrypi.com/software/). Pick Raspberry Pi OS Lite (64-bit). In the customisation dialog set:

- Username
- WiFi SSID + password
- Hostname: `birdnet`
- Enable SSH with password auth

Plug the USB mic into the Pi. Place the capsule in a window or mount it outside. Boot.

---

## 2. Run the installer

Installer assumes passwordless sudo (Raspberry Pi OS Lite default - if you've tightened it, run `sudo raspi-config` -> *System Options* -> restore the default first).

```bash
ssh <your-username>@birdnet.local
curl -s https://raw.githubusercontent.com/white111/AvianVisitors_Weather/avian-visitors/newinstaller.sh | bash
```

Clones this fork, installs BirdNET-Pi, symlinks the AvianVisitors overlay into the Caddy web root. Takes 20-40 minutes. Reboots when done.

Collage: `http://birdnet.local/`. Stock BirdNET-Pi UI: `http://birdnet.local/index.php`. The menu button in the top right opens an admin overlay with Settings, System, Logs, and Tools.

Stock BirdNET-Pi pages still render, but privileged legacy controls are not enabled. Use the Avian Visitors menu for the station controls it exposes, and SSH for remaining maintenance.

Optional Google Drive backups are set up under **Settings → Nightly Drive backup**. Local cleanup stays unavailable until an archive run has been verified.

### Local admin access

Optional password protection for local administrator controls can be enabled in **Settings**. Public bird pages remain available without signing in, while live audio is unavailable when protection is on.

If no password is configured, or the state is missing or invalid, recover it from an SSH session:

```bash
sudo /usr/local/sbin/avian-admin-control password-reset
```

The command prompts privately for a new password. Return to **Settings** after it finishes.

### Educators mode

Educators mode is an optional profile for the BirdNET-Pi website. It adds a fifth menu page for starting, pausing, organizing, and reviewing listening periods. Enable it after installation over SSH:

```bash
sudo /usr/local/sbin/avian-educators enable
```

New stations can also install with the profile enabled:

```bash
curl -fsSL https://raw.githubusercontent.com/white111/AvianVisitors_Weather/avian-visitors/newinstaller.sh | bash -s -- --educators
```

Listening periods scope the Collage, Stats, Atlas, and available detection clips without copying or protecting audio files from normal retention. Saved period and folder exports require a direct local connection. See [the Educators guide](docs/educators.md) for the full workflow and privacy details.

### Updating an existing station

For the first v1 update, or if an interrupted older update left the admin helper missing and Tools locked, keep the existing checkout and run this verified setup over SSH:

```bash
upgrade=$(mktemp "$HOME/avian-v1-upgrade.XXXXXX")
curl -fsSL https://raw.githubusercontent.com/white111/AvianVisitors_Weather/avian-visitors/scripts/bootstrap_v1.sh -o "$upgrade"
sudo bash "$upgrade"
rm -f "$upgrade"
```

After v1, use **Tools → Pull latest** or run:

```bash
cd ~/BirdNET-Pi
./scripts/update_birdnet.sh
```

The updater preserves custom bird artwork, generated mask data, and existing credentials. It stops if other tracked files have local edits. It verifies and stages one official release before changing the checkout. If applying that release is interrupted, keep the new checkout and resume the same prepared installation without fetching another release:

```bash
sudo /usr/local/sbin/avian-service-refresh
```

If the installed refresher itself is missing or unsafe, use the verified setup command above. An already-running older updater cannot gain the new preparation checks until it has finished or been recovered this way. Only use `sudo /usr/local/sbin/avian-admin-control password-reset` for missing credentials after the helper is installed successfully.

---

## iPad display (including 1st-gen iPad Air)

Open `http://pibird.local/` in Safari on the iPad and use **Share → Add to Home Screen** for a full-screen wall display. On touch screens, tap a bird once to see its name and tap it again to open its postcard. A postcard closes itself after 30 seconds without a touch, and a quiet **1H** window switches to **12H** until a bird is heard again. A species heard for the first time ever gets a gold glow and a **first heard** label for its first 24 hours.

**Theme.** Settings > Theme offers follow system, light, dark and **sunrise / sunset**. The last switches the page to the dark theme at sunset and back to light at sunrise, checked every minute, using the forecast place (or, if none is set, the station location from Settings). Each browser keeps its own theme choice, so pick it on the iPad itself.

The 1st-gen iPad Air tops out at iOS 12 (Safari 12), which cannot read much of the modern CSS and a few of the browser APIs the collage uses. That browser automatically gets:

- `styles.legacy.css`, generated from `styles.css`. Rebuild it whenever `styles.css` changes, for example after syncing upstream:
  ```
  cd avian/scripts/legacy_css && npm ci && npm run build
  ```
- `compat.js`, small stand-ins for `Element.animate`, `replaceChildren` and pointer events.
- PNG copies of the nest artwork (Safari 12 has no WebP), and the classic Atlas cards instead of stamps.

Tablet sizing lives in `avian/frontend/ipad.css`, kept separate so upstream changes to `styles.css` merge cleanly.

---

## 3. (Optional) Restyle the illustrations

The repo ships with 666 bundled illustrations (333 species, perched + flight). To restyle them or generate a set for your own region:

```bash
pip install -r ~/BirdNET-Pi/avian/scripts/requirements.txt
export GEMINI_API_KEY='your-key'  # image generation requires billing enabled

# generate on a cream ground, cut the ground off, rebuild the collage masks
python3 ~/BirdNET-Pi/avian/scripts/pregen.py --labels ~/BirdNET-Pi/model/labels.txt --force
python3 ~/BirdNET-Pi/avian/scripts/cutout.py
python3 ~/BirdNET-Pi/avian/scripts/build_masks.py
```

On a Pi with 4 GB of RAM or less, add `--model u2net` to the `cutout.py` command; the default model may be [OOM-killed](https://github.com/Twarner491/AvianVisitors/issues/17).

Filter to your region with `--ebird-region US-CA` (needs `EBIRD_API_KEY`). The full pipeline, prompt, reference images, and per-species tuning live in [`avian/scripts/README.md`](avian/scripts/README.md). Style lives in [`prompt.template.md`](avian/scripts/prompt.template.md).

See [illustration bundles](illustration-bundles.md) for pregenerated bundles shared by other folks in the community, or share your own for others to use!

---

## 4. (Optional) Forward off your LAN

See [`avian/forwarding/`](avian/forwarding/) for three independent recipes:

- **Cloudflare Tunnel** for a public HTTPS URL.
- **Home Assistant REST sensor** that exposes the latest detection.
- **MQTT bridge** that publishes every new detection.

---

## Weather badge: sensors and local forecast (optional)

The collage can show a small weather badge in the corner with your own sensor readings (temperature, humidity, wind and rain) and a local 5-day forecast. Tap the badge to expand the forecast.

### Supported sensors

Any of these sensors that the receiver hears shows up on its own. Nothing needs to be paired.

| Sensor | Band | Reports | Identified by | Sends every | Status |
| --- | --- | --- | --- | --- | --- |
| ThermoPro TX-2 (sold with TP-60S, TP-62, TP-65 bases) | 433 MHz | temperature, humidity | channel 1, 2, 3 | ~50 s | tested |
| AcuRite 592TXR tower (00592TXR, 00592TXRA2) | 433 MHz | temperature, humidity | channel A, B, C | ~16 s | tested |
| La Crosse Breeze Pro (LTV-WSDTH01/04) | 915 MHz | temperature, humidity, wind speed and direction | sensor id | ~30 s | tested |
| La Crosse View LTV-TH | 915 MHz | temperature, humidity | sensor id | under a minute | decoder included |
| La Crosse View LTV-WR1 | 915 MHz | wind, rain | sensor id | under a minute | decoder included |
| La Crosse rain gauge LTV-R1, LTV-R3 | 915 MHz | rain (shown as rain today) | sensor id | a few minutes | decoder included |
| La Crosse IT+ TX29-IT / TX29U, TX35DTH-IT, TX31U-IT | 915 MHz | temperature (TX35 adds humidity) | sensor id | ~4 s | decoder included; a TX29U was not heard in testing |

The 433 MHz sensors work with either receiver below. The 915 MHz La Crosse sensors need the RTL-SDR dongle.

On the badge, wind shows as `WSW 4 mph` (km/h when the forecast is set to °C), with a gust range when the sensor reports one, and `calm` under 1 km/h. A rain gauge shows `0.12 in today` (mm with °C). Rain is counted from local midnight and kept across receiver restarts and gauge battery changes (`/var/lib/avian-thermopro/rain.json`). Readings older than 15 minutes are hidden. To move the badge out of its corner, turn on **Settings > Float weather** (per device): it then sits in open space between the birds, steps aside when the collage changes, and drifts to another clear spot every 5 minutes. A tap holds it still for a minute. Phones and the Stats/Atlas views keep the corner.

**Name or hide sensors** in the pibird menu under **Settings > Weather sensors**. Every sensor heard is listed with its model, latest reading and age, a name box (blank uses the default name) and a switch to show or hide it on the collage. Names are stored in `/var/lib/avian-forecast/sensors.json`. La Crosse sensors are listed by their id. Some models pick a new id when the batteries are replaced; give the new id the old name, then clear the old id's name to drop it from the list.

### Receivers

**RTL-SDR dongle (recommended).** An RTL2832U dongle with an R820T/R820T2 tuner running [`rtl_433`](https://github.com/merbanan/rtl_433) hears the 433 MHz sensors far better than an RXB6, and it is the only way to hear the 915 MHz La Crosse sensors. One dongle hears one band at a time, so the receiver takes turns: 60 s on 433.92 MHz, then 60 s on 915 MHz (`--rtl433-hop`), restarting `rtl_433` for each band. Every sensor is still heard each cycle; a second dongle would cover both bands continuously.

- Use an antenna cut for the band you care most about (about 17 cm for 433 MHz, 8 cm for 915 MHz); the stock telescopic whip works for both when sensors are within ~30 m.
- Keep sensors at least a few metres from the dongle. A transmitter right next to it overloads the tuner and decodes worse, not better.
- A streaming dongle deafens an RXB6 nearby, so the installer turns the RXB6 off (`--no-gpio`) when it finds a dongle.

**RXB6 on GPIO (no dongle).** A 433 MHz RXB6 receiver decodes the ThermoPro and AcuRite itself:

| RXB6 | Pi pin |
| --- | --- |
| VCC | 1 (3.3 V). Do not use 5 V: DATA would then drive 5 V into the GPIO |
| GND | 6 |
| DATA | 13 (GPIO27) |
| ANT | 17.3 cm straight wire |

### Install or update

1. Plug the RTL-SDR dongle into the Pi (or wire the RXB6).
2. Pull this branch and run the installer. Run it again after every update; it restarts the receiver on the new code and refreshes the web server's routes:
   ```bash
   cd ~/BirdNET-Pi && git pull
   bash ~/BirdNET-Pi/avian/thermopro/install.sh
   ```
   It installs `rtl-433`, `rtl-sdr` and `python3-lgpio`, frees the dongle from Linux's TV-tuner driver, switches the receiver to the dongle on both bands, installs and restarts the `avian-thermopro` service, and creates the settings folder for the forecast and sensor names.
3. Watch readings arrive (each sensor appears when it next transmits; give the 915 MHz band a couple of minutes):
   ```bash
   journalctl -fu avian-thermopro
   ```
   A line like `lacrosse ch8994842 La Crosse 8994842 id=8994842 22.4 C 72.3 F 42% wind 3.9 km/h from 253 deg` means it works.
4. Name the sensors in **Settings > Weather sensors**, set the forecast place (below), and reload the iPad.

Receiver options live in `/etc/avian/thermopro.env`. The installer writes, for example:

```
THERMOPRO_ARGS=--gpio 27 --units F --print --rtl433 --no-gpio --rtl433-freq 433.92M --rtl433-freq 915M
```

Use only `--rtl433-freq 433.92M` for 433 MHz sensors alone (no hopping), or only `--rtl433-freq 915M` for La Crosse alone. Restart with `sudo systemctl restart avian-thermopro`. To test by hand, stop the service and run `python3 ~/BirdNET-Pi/avian/thermopro/thermopro_rx.py --print --no-gpio --rtl433 --no-write`.

### Troubleshooting

- **`[R82XX] PLL not locked!`** at each band switch is normal for R820T dongles and harmless.
- **`rtl_433 exited with code 3`** (or `usb_claim_interface error`) repeating: the dongle has stalled or something else holds it. Stop the service, unplug the dongle for 5 seconds, plug it back in, and start the service. Rerun `install.sh` if the TV-tuner driver grabbed it again.
- **A sensor never appears:** check its batteries and distance, then listen to its band alone, e.g. `sudo systemctl stop avian-thermopro; timeout 120 rtl_433 -f 915M -F kv` (or `-f 433.92M`), and look for its model name. Start the service again afterwards.
- **Readings show up in the journal but not on the badge:** reload the page, and check the sensor is not hidden in Settings.

### Sunrise, sunset and moon phase

Once a location is known, the badge adds a line with today's sunrise and sunset times and the moon's phase, drawn as it looks tonight (for example `7:19 am  6:28 pm  First quarter`; hold or hover over the moon for how much of it is lit). The location is the forecast place, or the station location from Settings when no forecast place is set, rounded to about 1 km. Everything is worked out in the browser; no extra service is used.

### Local forecast

In the pibird menu, open **Settings** and find **Local forecast** under Station location. Type a city (`San Jose, CA`) or a ZIP code (`95120`) and press **set**. If the name is ambiguous, pick the right place from the suggestions. You can also switch between °F and °C and turn the forecast on or off there.

Forecasts come from [Open-Meteo](https://open-meteo.com/) (free, no API key) and refresh every 30 minutes. Only the chosen place is sent. The settings and cache live in `/var/lib/avian-forecast`, which `install.sh` creates.

## Repo layout

```
avian/                  # everything we add to BirdNET-Pi
├── frontend/           # static HTML/JS/CSS for the collage
├── assets/             # 666 bundled illustrations + photo-cutout fallbacks
├── api/                # PHP shims served by BirdNET-Pi's PHP-FPM
├── scripts/            # generate -> cutout -> masks pipeline + prompt
└── forwarding/         # optional HA / MQTT / Cloudflare configs
frame/                  # optional e-ink wall display
```

Everything outside `avian/` and `frame/` is upstream BirdNET-Pi.

---

## Wall frame

An optional e-ink frame puts the bird collage on a panel by your window. Build it from [`frame/`](frame/README.md). It can run off your own BirdNET mic, from BirdWeather around a ZIP code, or from one public BirdWeather station with `frame/install.sh --station-id <ID>`.

---

## AI-assisted modifications

Much of this fork's own code (beyond upstream AvianVisitors) was written with an AI coding assistant, Anthropic's Claude, working from the owner's requests and test results from the real station. The owner reviewed, pushed and installed every change. Those commits carry a `Co-Authored-By: Claude` trailer; list them with:

```bash
git log --oneline --grep='Co-Authored-By: Claude'
```

The weather receiver itself started with a commit made without that trailer ("Adding a temp", plus the lgpio working-directory fix), but it came from the same AI-assisted work.

**What was written with AI help:**

- **Weather badge:**
  - The receiver service (`avian/thermopro/`): ThermoPro TX-2 and AcuRite 592TXR decoders for the RXB6, the RTL-SDR/`rtl_433` source with band switching, wind and rain handling, and the installer.
  - The sensor API and Settings controls (`avian/api/thermopro.php`, the Weather sensors rows in `apt.js`).
  - The local forecast (`avian/api/forecast.php`, `avian/frontend/thermopro.*`).
- **Collage:** the "first heard" highlight for new species.
- **iPad:** 1st-gen iPad Air (iOS 12) support and the iPad layout and touch fixes.
- **Fixes:**
  - The OpenStreetMap Referer fix for the Station location map.
  - Pointing installers and docs at this fork.
- **Docs:** these README sections. `CLAUDE.md` and `CLAUDE_HANDOFF.md` are notes for the assistant about the repo and the station; they are not needed to run anything.

**How it was checked:**

- Each change came with unit tests (`tests/test_thermopro_decode.py`, `test_acurite_decode.py`, `test_rtl433_source.py`, `test_rain_today.py`, `test_sensors_api.py`, `test_forecast_api.py`).
- The radio decoders were confirmed against live sensors on the station: a ThermoPro TX-2, an AcuRite 592TXR and a La Crosse Breeze Pro.

**Limits to keep in mind:**

- Sensors marked "decoder included" in the sensor table rely on `rtl_433`'s decoders and have not been heard on this station.
- The rain gauge support has only been tested with sample data, since no gauge was installed yet.
- The assistant could not reach the Pi or GitHub directly. It worked on a local checkout, and the owner ran every on-device step.
- AI-written code can be confidently wrong. If something misbehaves, the journal (`journalctl -u avian-thermopro`) and the tests are the first places to look, and issues are welcome.

Bird illustrations are a separate, upstream use of AI: restyling them, and drawing art for a newly heard species, uses Google's Gemini image model (see *Restyle the illustrations* above).

---

## License

CC-BY-NC-SA-4.0, inherited from [BirdNET-Pi](https://github.com/Nachtzuster/BirdNET-Pi/blob/main/LICENSE). Non-commercial use only. See the [BirdNET-Pi README](https://github.com/Nachtzuster/BirdNET-Pi/blob/main/README.md) for full Cornell attribution.

---

- [Fork this repository](https://github.com/Twarner491/AvianVisitors/fork)
- [Watch this repo](https://github.com/Twarner491/AvianVisitors/subscription)
- [Create issue](https://github.com/Twarner491/AvianVisitors/issues/new)
