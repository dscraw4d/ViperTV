# ViperTV v1.5.0 — Windows Standalone x64

**Created by Darren “The Viper” Crawford**

This is the native Windows distribution of ViperTV v1.5.0. It is intended for users who want ViperTV on Windows 10/11 without Docker Desktop and without installing Python or FFmpeg separately.

## Release formats

- `ViperTV-v1.5.0-Windows-Portable-x64.zip` — extract and double-click `ViperTV.exe`.
- `ViperTV-v1.5.0-Windows-x64-Setup.exe` — normal Windows installer with Start Menu shortcuts and optional autostart/firewall setup.

The standalone release bundles its own CPython runtime, Python dependencies, FFmpeg and FFprobe. It does **not** use Docker, WSL, a system Python installation, or a system FFmpeg installation.

## Data locations

The installed edition keeps durable user data outside Program Files:

`C:\ProgramData\ViperTV\`

This contains the SQLite database, logs, backups and update cache. Uninstalling ViperTV deliberately leaves this folder intact so removing the application cannot silently erase a user's television configuration.

The portable edition keeps its persistent data in `UserData` beside ViperTV. Move the entire extracted folder together if you want to move a portable installation.

## Starting and stopping

Use `ViperTV.exe` or the Start Menu shortcuts created by Setup. The portable release also includes command-file fallbacks (`ViperTV-Start.cmd`, `ViperTV-Open.cmd`, `ViperTV-Restart.cmd`, `ViperTV-Stop.cmd`, and `ViperTV-Logs.cmd`).

The default management address is `http://localhost:8409`.

## Windows hardware acceleration

The Windows build uses FFmpeg's Windows-native encoder paths:

- Intel Quick Sync Video (QSV)
- NVIDIA NVENC
- AMD AMF
- Software libx264/libx265
- Direct stream copy

VAAPI remains visible only as a Linux compatibility profile and is reported unavailable on Windows. ViperTV's Hardware Acceleration page detects the Windows display adapters and tests the actual FFmpeg encoder before it is selected automatically.

## Network use

The installer can optionally create a Windows Firewall rule for TCP 8409. Only enable this if other devices on the LAN need to reach ViperTV. Management authentication and JWT stream protection remain configurable inside ViperTV.

If a streaming-only port is configured in ViperTV, restart the Windows standalone application. Its lightweight local proxy will then bind that additional port and mark requests as streaming-only before forwarding them to the main ViperTV process.


## Windows signing

The public build workflow creates an ordinary unsigned Windows installer unless the project owner later adds a trusted code-signing certificate. Windows SmartScreen may therefore show an unknown-publisher warning on first download. Do not replace this with a self-signed public release certificate; sign release binaries only with a proper trusted certificate if one is obtained.

## Building the Windows release yourself

On Windows 10/11 x64 with Python 3.12 available for the build step:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Build-Windows-Standalone.ps1
```

The script downloads the official CPython embeddable runtime, installs the pinned Windows Python dependencies into that private runtime, downloads FFmpeg, vendors hls.js, performs smoke tests and creates the portable ZIP. If Inno Setup 6 is installed, it also creates the Setup EXE.

The included GitHub Actions workflow performs the same build on `windows-latest` and uploads both release artifacts.

## Docker edition

The original Docker/OMV ViperTV v1.5.0 remains a separate distribution and is unchanged by the Windows project. Database/configuration export and import are the recommended way to move configuration between editions.
