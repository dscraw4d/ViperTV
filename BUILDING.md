# Building ViperTV Windows Standalone

## GitHub Actions

1. Put this source tree in a GitHub repository.
2. Open **Actions**.
3. Select **Build Windows Standalone**.
4. Choose **Run workflow**.
5. When the job finishes, download the `ViperTV-v1.5.0-Windows-x64` artifact.

The artifact contains the portable ZIP, Setup EXE, and SHA-256 files.

## Local Windows build

Use Windows 10/11 x64 with Python 3.12 on the build machine. Double-click `BUILD-WINDOWS.cmd`, or run:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\Build-Windows-Standalone.ps1
```

Inno Setup 6 is optional for a local build. Without it, the portable ZIP is still produced. The GitHub workflow installs Inno Setup automatically.
