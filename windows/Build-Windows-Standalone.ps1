param(
  [string]$Version = "1.5.0",
  [string]$PythonVersion = "3.12.10",
  [string]$OutDir = ""
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if ($env:OS -ne "Windows_NT") { throw "This builder must run on 64-bit Windows." }
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
if (-not $OutDir) { $OutDir = Join-Path $Root "dist-windows" }
$OutDir = [IO.Path]::GetFullPath($OutDir)
$Stage = Join-Path $OutDir "ViperTV-v$Version-Windows-Portable-x64"
$Runtime = Join-Path $Stage "runtime"
$Tmp = Join-Path $OutDir "_build"

Write-Host "Building ViperTV v$Version Windows Standalone x64" -ForegroundColor Cyan
Remove-Item $Stage,$Tmp -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $Stage,$Runtime,$Tmp | Out-Null

# Copy only the Windows runtime application/distribution files. Docker files are
# source/distribution assets, not needed by the standalone runtime.
Copy-Item (Join-Path $Root "app") $Stage -Recurse
Copy-Item (Join-Path $Root "windows") $Stage -Recurse
Copy-Item (Join-Path $Root "ViperTV-Start.cmd") $Stage
Copy-Item (Join-Path $Root "ViperTV-Stop.cmd") $Stage
Copy-Item (Join-Path $Root "ViperTV-Restart.cmd") $Stage
Copy-Item (Join-Path $Root "ViperTV-Open.cmd") $Stage
Copy-Item (Join-Path $Root "ViperTV-Logs.cmd") $Stage
Copy-Item (Join-Path $Root "VERSION") $Stage
Copy-Item (Join-Path $Root "LICENSE-NOTICE.txt") $Stage -ErrorAction SilentlyContinue
Copy-Item (Join-Path $Root "README-WINDOWS-STANDALONE.md") $Stage
Copy-Item (Join-Path $Root "THIRD-PARTY-NOTICES-WINDOWS.md") $Stage
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "UserData") | Out-Null
Set-Content -Path (Join-Path $Stage "portable.mode") -Value "portable" -Encoding ascii

# Python embeddable runtime.
$PyZip = Join-Path $Tmp "python-embed.zip"
$PyUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
Write-Host "Downloading CPython $PythonVersion embeddable runtime..."
Invoke-WebRequest -UseBasicParsing -Uri $PyUrl -OutFile $PyZip
Expand-Archive -Path $PyZip -DestinationPath $Runtime -Force

# Enable site-packages and the ViperTV root in the embeddable runtime.
$Pth = Get-ChildItem $Runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $Pth) { throw "Python embeddable _pth file not found" }
@(
  "python312.zip",
  ".",
  "Lib\site-packages",
  "..",
  "import site"
) | Set-Content -Path $Pth.FullName -Encoding ascii
New-Item -ItemType Directory -Force -Path (Join-Path $Runtime "Lib\site-packages") | Out-Null

# Use the Windows build Python to populate the embedded runtime. This avoids
# requiring pip inside the final standalone package.
$Req = Join-Path $Root "requirements-windows.txt"
Write-Host "Installing pinned ViperTV Python dependencies into embedded runtime..."
python -m pip install --disable-pip-version-check --no-compile --target (Join-Path $Runtime "Lib\site-packages") -r $Req
if ($LASTEXITCODE -ne 0) { throw "pip dependency installation failed" }

# Browser HLS runtime, vendored so browser preview has no CDN runtime dependency.
$Hls = Join-Path $Stage "app\hls.min.js"
Invoke-WebRequest -UseBasicParsing -Uri "https://cdn.jsdelivr.net/npm/hls.js@1.7.3/dist/hls.min.js" -OutFile $Hls
$LicenseDir = Join-Path $Runtime "licenses"
New-Item -ItemType Directory -Force -Path $LicenseDir | Out-Null
Invoke-WebRequest -UseBasicParsing -Uri "https://cdn.jsdelivr.net/npm/hls.js@1.7.3/LICENSE" -OutFile (Join-Path $LicenseDir "hls.js-LICENSE.txt")

# FFmpeg/FFprobe Windows x64 build. Kept as separate executables under runtime.
$FfmpegZip = Join-Path $Tmp "ffmpeg.zip"
Write-Host "Downloading FFmpeg Windows essentials build..."
Invoke-WebRequest -UseBasicParsing -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile $FfmpegZip
$FfTmp = Join-Path $Tmp "ffmpeg"
Expand-Archive -Path $FfmpegZip -DestinationPath $FfTmp -Force
$FfBin = Get-ChildItem $FfTmp -Directory -Recurse | Where-Object { Test-Path (Join-Path $_.FullName "ffmpeg.exe") } | Select-Object -First 1
if (-not $FfBin) { throw "ffmpeg.exe was not found in the downloaded FFmpeg package" }
$FfDest = Join-Path $Runtime "ffmpeg\bin"
New-Item -ItemType Directory -Force -Path $FfDest | Out-Null
Copy-Item (Join-Path $FfBin.FullName "ffmpeg.exe") $FfDest
Copy-Item (Join-Path $FfBin.FullName "ffprobe.exe") $FfDest
if (Test-Path (Join-Path $FfBin.FullName "ffplay.exe")) { Copy-Item (Join-Path $FfBin.FullName "ffplay.exe") $FfDest }
$FfRoot = $FfBin.Parent.FullName
Get-ChildItem $FfRoot -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(LICENSE|COPYING|README)' } | ForEach-Object { Copy-Item $_.FullName $LicenseDir -Force }

# Build a tiny native Windows launcher. It delegates to the bundled Python
# runtime and keeps the public package feeling like a normal Windows app.
$CscCandidates = @(
  (Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"),
  (Join-Path $env:WINDIR "Microsoft.NET\Framework\v4.0.30319\csc.exe")
)
$Csc = $CscCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Csc) { throw "The Windows .NET Framework C# compiler (csc.exe) was not found." }
$LauncherSource = Join-Path $Root "windows\ViperTVLauncher.cs"
$LauncherExe = Join-Path $Stage "ViperTV.exe"
& $Csc /nologo /target:winexe /optimize+ /reference:System.Windows.Forms.dll "/out:$LauncherExe" $LauncherSource
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $LauncherExe)) { throw "ViperTV.exe launcher build failed" }

# Sanity checks using the exact embedded runtime.
Write-Host "Running standalone import smoke test..."
& (Join-Path $Runtime "python.exe") -c "import sys; sys.path.insert(0,r'$Stage'); import fastapi,uvicorn,yaml,bs4; import app.main; print(app.main.APP_VERSION)"
if ($LASTEXITCODE -ne 0) { throw "Embedded Python smoke test failed" }
& (Join-Path $FfDest "ffmpeg.exe") -hide_banner -version | Select-Object -First 1
if ($LASTEXITCODE -ne 0) { throw "Bundled FFmpeg smoke test failed" }

$PortableZip = Join-Path $OutDir "ViperTV-v$Version-Windows-Portable-x64.zip"
Remove-Item $PortableZip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $Stage "*") -DestinationPath $PortableZip -CompressionLevel Optimal
$Hash = (Get-FileHash $PortableZip -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -Path "$PortableZip.sha256" -Value "$Hash  $(Split-Path $PortableZip -Leaf)" -Encoding ascii
Write-Host "Portable release: $PortableZip" -ForegroundColor Green

# Build a normal Setup.exe when Inno Setup is available.
$Iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($Iscc) {
  Write-Host "Building Inno Setup installer..."
  $env:VIPERTV_STAGE = $Stage
  $env:VIPERTV_OUT = $OutDir
  & $Iscc (Join-Path $Root "windows\ViperTV-Windows.iss") "/DMyAppVersion=$Version"
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }
  $Setup = Join-Path $OutDir "ViperTV-v$Version-Windows-x64-Setup.exe"
  if (Test-Path $Setup) {
    $SetupHash=(Get-FileHash $Setup -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path "$Setup.sha256" -Value "$SetupHash  $(Split-Path $Setup -Leaf)" -Encoding ascii
    Write-Host "Installer: $Setup" -ForegroundColor Green
  }
} else {
  Write-Warning "Inno Setup 6 not found. Portable ZIP was built; install Inno Setup and rerun to also build Setup.exe."
}
