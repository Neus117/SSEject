<p align="center">
  <img src="assets/app.png" width="128" height="128" alt="SSEject">
</p>

<h1 align="center">SSEject</h1>

<p align="center">
  <a href="README.md">简体中文</a> ｜ <strong>English</strong>
</p>

<p align="center">
  <strong>Eject portable disks reliably, and fast</strong><br>
  Pick the disk, click Eject once, unplug when the log says it is safe
</p>

<p align="center">
  <a href="https://github.com/Neus117/SSEject/releases/latest"><strong>Download latest</strong></a> ·
  <a href="https://github.com/Neus117/SSEject/releases">All releases</a> ·
  <a href="#known-limitations">Known limitations</a>
</p>

<p align="center">
  <img src="docs/screenshots/SSEject_v1.0.0-main-light.png" width="720" alt="Light theme"><br>
  <img src="docs/screenshots/SSEject_v1.0.0-main-dark.png" width="720" alt="Dark theme">
</p>

---

## The problem

Windows says "The device is currently in use" when you click Safely Remove Hardware — even though
you closed every file. Usually a background indexer, an antivirus scan or some system service still
holds the volume. SSEject does one thing: you pick the disk, click **Eject**, and it keeps asking
the system to release that volume until it really works — or tells you which step blocked it.

**Portable and green.** A single exe: no installer, no service, no driver, no registry writes.
To remove it, delete the exe and the `%LOCALAPPDATA%\SSEject` folder.

## Quick start

1. Download `SSEject_v1.0.0.exe` from [Releases](https://github.com/Neus117/SSEject/releases)
2. Double-click it (it asks for administrator rights)
3. Select the disk, click **Eject**, and unplug when the log says it is safe

Declining administrator rights still works: the app starts read-only, still lists disks, but the
Eject button is disabled with the reason shown.

## Features

Included by default:

| Capability | What it does |
|---|---|
| Disk list | Disk number / model / drive letters / size / type (external · internal) / online state |
| One-click eject | Uses the device's Shell "eject" verb when it has one; otherwise asks the system to remove it safely every 0.4 s, up to 10 s |
| Occupancy check | Before ejecting, checks whether the volume can be locked exclusively — so "a file handle is open" and "the volume is still mounted" are reported separately |
| Staged log | Duration of every stage and the raw reason for every veto; clear it or open the log file |
| Quiet on success | A success is one log line; only failures raise a dialog with a next step |
| Light and dark | Follows the system, or pin one in Settings; dialogs and icons are drawn in-house, so the look is consistent |
| UI language | Follows the system by default; switch between Chinese and English in Settings |

Optional (off by default) — **with the cost spelled out, so you can decide**:

| Switch | Cost | When to turn it on |
|---|---|---|
| Show all disks (toolbar `ALL`) | Internal disks show up in the list and you must tell them apart | You want to confirm whether a disk is external or internal |
| Pin the theme to light / dark | No longer follows the system | The system theme changes often, or you need one fixed theme for screenshots or a projector |
| Pin the UI language to Chinese / English | No longer follows the system | Your system language is not the UI language you want |

## Performance

Baseline: same machine, same USB-SATA hard drive, median of three runs. The strategy comparison
comes from `CHANGELOG.md`; the startup and query timings come from the measurements recorded in
`docs/handoff-2026-10-24.md`.

| Scenario | Result |
|---|---|
| **Eject (this tool: retry only)** | **4.2 – 4.6 s**, vetoed 2–3 times along the way, Explorer can read the disk again after re-plugging |
| Offline first, then remove | 4.0 s, zero vetoes, but Explorer **cannot** read the disk after re-plugging until you bring it online |
| Offline → online → retry | 16.9 s, 10 vetoes |
| Window appears | 0.80 – 0.87 s |
| Disk list appears | ~1.0 s (from the previous query's snapshot; the real query runs in the background) |
| One full disk query | 1.36 – 1.39 s (4.29 s for the first one after a boot) |

**Where we are slow, and why we chose it.** The disk query runs a PowerShell CIM query
(`Get-CimInstance` + `Get-Partition` + `Get-Disk` in one process); the 1.4 s is almost entirely
that query (process start is only 0.21 s). Native IOCTL calls could get this down to tens of
milliseconds — but **a non-admin process cannot open `\\.\PhysicalDriveN`**, and "keep listing
disks read-only after the user declines elevation" is this tool's default path. Switching would
hand those users an empty list, so we kept the slower path that everyone can see, and hid the
wait behind the startup snapshot.

## How to use

| | |
|---|---|
| **Download** | Get `SSEject_v1.0.0.exe` from [Releases](https://github.com/Neus117/SSEject/releases); double-click, no install |
| **Rights** | Double-clicking asks for administrator rights; declining starts read-only mode (view only, no eject) |
| **Where files land** | `%LOCALAPPDATA%\SSEject\`: `settings.json` (theme / language), `app.log` (UTF-8 with BOM, rotated at 1 MB), `last-disks.json` (snapshot of the previous query, only used to fill the list instantly at startup) |
| **Run at logon** | `Win+R` → `shell:startup` → drop a shortcut to the exe there |
| **Uninstall** | Delete the exe, then delete `%LOCALAPPDATA%\SSEject`; no service, no driver, no registry writes |
| **Check the version** | The bottom-right corner shows `v1.0.0`; or right-click the exe → Properties → Details |
| **Diagnostics** | `SSEject.exe --diagnose "%TEMP%\sseject.json"` writes a runtime-state JSON (disk count, row counts for both views, language, font size, badge ink ratio); exit code is 1 on failure |
| **Skip elevation** (testing) | `SSEject.exe --no-elevate` |

## Known limitations

| Item | Status |
|---|---|
| Ejecting needs administrator rights | Read-only mode can only view, not eject |
| The device has no Shell "eject" verb | The Shell stage is skipped and the system safe-removal path is used; same result, one log line |
| Phones and cameras (MTP portable devices) | **Not supported, and not planned** — see below |
| Each disk query takes ~1.4 s, 4.3 s right after a boot | Mostly hidden behind the startup snapshot; the log still shows the real timing |
| Windows 10 / 11 (x64) only | Older versions untested |
| Historical log lines do not follow a language switch | Each line keeps the language it was written in; only new lines follow the current language |

**Why MTP devices are not supported: they are not a file system.** A phone or camera appears in
Explorer as an item in the shell namespace, not as a block device. The things this tool depends
on — physical disk number, drive letters, volumes, device nodes — do not exist for it, so "safely
eject" has no meaning there.

**What to do instead:** such devices are meant to be unplugged directly (there is no volume to
dismount and no write cache to flush). To move files, copy them to a local disk with Explorer
first, then use this tool on that local disk if you need to.

## Documentation

| Document | Audience |
|---|---|
| `README.md` / `README.en.md` | Users — every feature, switch, cost and limitation |
| [`CHANGELOG.md`](CHANGELOG.md) | Users and maintainers — user-visible changes per version |
| [`docs/handoff-2026-10-24.md`](docs/handoff-2026-10-24.md) | Maintainers — measurements, traps, current state and open items (Chinese) |

## For developers

```powershell
# Windows 10 / 11 + Python 3.12 (developed on 3.12.15)
python -m pip install pyinstaller          # build only; running needs just the stdlib + Tk

python app.py                              # run from source
python -m unittest discover -s tests       # 36 unit tests, no real disks touched

# Build the single-file exe (output in dist\)
python -m PyInstaller --noconfirm --distpath dist --workpath build app.spec

# Gate: really runs one disk query, builds the UI and loads the badge, writes JSON
dist\SSEject.exe --diagnose "%TEMP%\sseject.json"
```

What the gate checks:

| Field | Criterion |
|---|---|
| `error` | Must be `null` |
| `rows` / `rows_show_all` | How many rows each view found (external-only vs. all disks) |
| `lang_pt` | Effective font size of the language buttons (currently 11) |
| `badge_ink_ratio` | Ink ratio of the warning badge: outline version ≈ 0.17, a filled triangle is > 0.4 |
| `help_window` / `icon_handles` | Whether the help window builds and icon handles load |

Code layout (**the layering exists so the decisions can be verified automatically**):

```
core/    Disk query, eject, PNP veto mapping, diskpart, logging, i18n
         — no Tk here; "does this disk count as external", "which failure is this" live here
           and are covered by tests/
gui/     Tk windows, canvas-drawn controls, theme and fonts, in-house dialogs, Win32 bridge
tools/   Pillow generators for icons and badges, capture/measure probes (not shipped)
tests/   Unit tests (36)
```

The UI layer only draws and forwards; change the eject strategy or the classification rules in
`core/` and run the tests.

## Licence

[MIT](LICENSE) © 2026 Neus117

"SSEject" is this project's name and stands for **S**ure & **S**wift **Eject**. The official
channels are this repository and its
[Releases](https://github.com/Neus117/SSEject/releases); verify the SHA256 of builds obtained
anywhere else.
