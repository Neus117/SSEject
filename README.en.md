# SSEject

**Sure & Swift Eject** — eject portable disks reliably, and fast.

简体中文 (Chinese) | English

![light](docs/screenshots/main-light.png)

## The problem

Windows says "The device is currently in use" when you click Safely Remove Hardware — even though
you closed every file. Usually a background indexer, antivirus scan or system service still holds
the volume. SSEject does one thing: pick the disk, click **Eject**, and it handles the rest.

## How it stays "sure" and "swift"

```
Shell eject (try the device's "Eject" verb once; remember it if it has none)
   ↓
Ask the system to remove the device every 0.4 s (up to 10 s)
   ↓
Success → the drive letter disappears, safe to unplug; failure → device untouched, reason shown
```

**The disk state is never modified.** No offline, no forced dismount, no offline→online cycle —
measured on the same hardware, those "helpful" steps are slower and leave the disk offline, so
Explorer cannot read it after replug.

Measured on one machine with one USB-SATA disk:

| Strategy | Time | Vetoes | Explorer after replug |
|---|---|---|---|
| **Retry only (this tool)** | **4.2–4.6 s** | 2–3 | reads the disk immediately |
| Offline the disk, then remove | 4.0 s | 0 | unreadable until manually onlined |
| Offline→Online, then retry | 16.9 s | 10 | reads the disk immediately |

## Features

- Disk list: number / model / drive letters / capacity / type / online state
- One-click eject with automatic retries; silent on success, explains failures
- Log panel with per-stage timings and veto reasons; clear or open the log file
- Light/dark theme follows the system; custom dialogs and icons
- Single-file exe, no installation

## Requirements

- Windows 10 / 11 (x64)
- **Administrator rights** to eject; without them the app runs read-only and only lists disks

## Usage

1. Run `SSEject.exe` as administrator
2. Select the disk
3. Click **Eject**, unplug when it reports success

## Troubleshooting

- **Still "in use"**: wait a few seconds and click Eject again, or close Explorer windows on that drive.
- **Mojibake in the log**: the log is UTF-8 with BOM, so `Get-Content` works in PowerShell 5.1 and 7.
- **Diagnostics**: `SSEject.exe --diagnose "%TEMP%\sseject.json"` writes the runtime state.

Log: `%LOCALAPPDATA%\SSEject\app.log` (1 MB rotation).

## Build

```powershell
python -m pip install pyinstaller pillow
python tools/design_icon.py
python tools/design_badges.py
python -m PyInstaller --noconfirm app.spec
```

Tests:

```powershell
python -m unittest discover -s tests -v
```

## License

[MIT](LICENSE) © 2026 Neus117
