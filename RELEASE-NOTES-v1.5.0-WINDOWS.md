# ViperTV v1.5.0 — Windows Standalone x64

**Created by Darren “The Viper” Crawford**

This is the native Windows 10/11 x64 distribution project for ViperTV v1.5.0. It is separate from the Docker/OMV edition and does not require Docker Desktop, WSL, a system Python install, or a system FFmpeg install on end-user PCs.

## Release outputs

A Windows build produces:

- `ViperTV-v1.5.0-Windows-Portable-x64.zip`
- `ViperTV-v1.5.0-Windows-x64-Setup.exe`
- SHA-256 checksum files for both artifacts

The portable build launches through `ViperTV.exe` and stores its durable database, backups and logs under `UserData` beside the application. The installed edition uses `C:\ProgramData\ViperTV`, so uninstalling the program does not erase a user's ViperTV database.

## Native Windows additions

- bundled private CPython 3.12 runtime
- bundled FFmpeg and FFprobe
- native `ViperTV.exe` launcher
- Windows Start Menu shortcuts and optional desktop shortcut
- optional start-with-Windows entry
- optional Windows Firewall rule for TCP 8409
- Intel Quick Sync Video (QSV)
- NVIDIA NVENC
- AMD AMF
- software encoding and direct stream copy
- Windows GPU detection through Windows Management APIs
- Windows drive, mapped-drive and UNC media paths
- Windows-compatible remote-stream executable support
- Python, PowerShell, batch/CMD and executable Script Runner support
- bundled streaming-only proxy for the optional streaming-only port

All normal ViperTV v1.5.0 features remain present, including the Setup Wizard, System Health, stream diagnostics, media integrity scanning, duplicate detection, metadata repair, configuration export/import, snapshots, multi-user roles, audit logging, scheduling, Graphics Engine 2.0, advanced stream selection, direct-media paths and reusable FFmpeg profiles.

## Building

The repository includes `.github/workflows/build-windows-standalone.yml`. Run **Build Windows Standalone** from GitHub Actions, or double-click `BUILD-WINDOWS.cmd` on a Windows build machine with Python 3.12 available. The build workflow obtains the private runtime and third-party binaries, performs smoke tests, and creates the portable ZIP and Setup EXE.

The source/build package itself is not the end-user runtime: the Windows build step must complete once to create the bundled executable distributions.

## Code signing

The generated Setup EXE is unsigned unless the project owner later configures a trusted Windows code-signing certificate. Windows SmartScreen may therefore display an unknown-publisher warning. A self-signed certificate is not substituted for a trusted public release certificate.

## Docker edition

The existing ViperTV v1.5.0 Docker/OMV edition is unchanged and remains a separate distribution.
