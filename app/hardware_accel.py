from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

_VENDOR_NAMES = {
    "0x8086": "Intel",
    "0x1002": "AMD",
    "0x1022": "AMD",
    "0x10de": "NVIDIA",
}

IS_WINDOWS = os.name == "nt"
_HW_PROFILES = {"vaapi", "qsv", "nvenc", "amf"}
_ENCODER_CACHE: tuple[float, set[str]] | None = None
_GPU_CACHE: tuple[float, list[dict[str, Any]]] | None = None


def _creationflags() -> int:
    if not IS_WINDOWS:
        return 0
    # Hide diagnostic subprocess consoles when ViperTV is launched with pythonw.
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _run(args: list[str], timeout: int = 8, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=env or os.environ.copy(),
            creationflags=_creationflags(),
        )
        return int(cp.returncode), (cp.stdout or "")[-16000:]
    except Exception as exc:
        return 999, str(exc)


def ffmpeg_encoders() -> set[str]:
    global _ENCODER_CACHE
    now = time.monotonic()
    if _ENCODER_CACHE and now - _ENCODER_CACHE[0] < 60.0:
        return set(_ENCODER_CACHE[1])
    rc, out = _run(["ffmpeg", "-hide_banner", "-encoders"], timeout=10)
    if rc != 0:
        _ENCODER_CACHE = (now, set())
        return set()
    found: set[str] = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[VAS\.]{6}\s+([^\s]+)", line)
        if m:
            found.add(m.group(1).strip())
    for name in (
        "libx264", "libx265", "h264_vaapi", "hevc_vaapi", "h264_qsv", "hevc_qsv",
        "h264_nvenc", "hevc_nvenc", "h264_amf", "hevc_amf"
    ):
        if name in out:
            found.add(name)
    _ENCODER_CACHE = (now, set(found))
    return found


def _sysfs_vendor_for_render(render_name: str) -> tuple[str, str]:
    candidates = [
        Path("/sys/class/drm") / render_name / "device" / "vendor",
        Path("/sys/class/drm") / render_name / "device" / "subsystem_vendor",
    ]
    vendor_id = ""
    for p in candidates:
        try:
            vendor_id = p.read_text().strip().lower()
            if vendor_id:
                break
        except Exception:
            pass
    return vendor_id, _VENDOR_NAMES.get(vendor_id, "Unknown")


def _vendor_from_text(text: str) -> tuple[str, str]:
    s = (text or "").lower()
    if "nvidia" in s or "ven_10de" in s:
        return "0x10de", "NVIDIA"
    if "intel" in s or "ven_8086" in s:
        return "0x8086", "Intel"
    if "amd" in s or "advanced micro devices" in s or "radeon" in s or "ven_1002" in s:
        return "0x1002", "AMD"
    return "", "Unknown"


def discover_windows_gpus() -> list[dict[str, Any]]:
    global _GPU_CACHE
    if not IS_WINDOWS:
        return []
    now = time.monotonic()
    if _GPU_CACHE and now - _GPU_CACHE[0] < 60.0:
        return [dict(x) for x in _GPU_CACHE[1]]
    rows: list[dict[str, Any]] = []
    ps = shutil.which("powershell") or shutil.which("powershell.exe")
    if ps:
        script = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,PNPDeviceID,AdapterCompatibility,DriverVersion | ConvertTo-Json -Compress"
        )
        rc, out = _run([ps, "-NoProfile", "-NonInteractive", "-Command", script], timeout=8)
        if rc == 0 and out.strip():
            try:
                payload = json.loads(out.strip())
                if isinstance(payload, dict):
                    payload = [payload]
                for i, d in enumerate(payload or []):
                    name = str(d.get("Name") or d.get("AdapterCompatibility") or f"GPU {i+1}")
                    pnp = str(d.get("PNPDeviceID") or "")
                    vendor_id, vendor = _vendor_from_text(name + " " + pnp + " " + str(d.get("AdapterCompatibility") or ""))
                    rows.append({
                        "render": "",
                        "card": name,
                        "name": name,
                        "vendor_id": vendor_id,
                        "vendor": vendor,
                        "driver": str(d.get("DriverVersion") or ""),
                        "platform": "windows",
                    })
            except Exception:
                pass
    if not rows:
        # Older Windows builds can still expose WMIC. It is only a fallback.
        wmic = shutil.which("wmic") or shutil.which("wmic.exe")
        if wmic:
            rc, out = _run([wmic, "path", "win32_VideoController", "get", "Name,PNPDeviceID,DriverVersion", "/format:csv"], timeout=8)
            if rc == 0:
                for line in out.splitlines():
                    if not line.strip() or "PNPDeviceID" in line:
                        continue
                    parts = [p.strip() for p in line.split(",")]
                    joined = " ".join(parts)
                    vendor_id, vendor = _vendor_from_text(joined)
                    name = next((p for p in parts if any(k in p.lower() for k in ("nvidia","intel","amd","radeon"))), joined)
                    rows.append({"render":"","card":name,"name":name,"vendor_id":vendor_id,"vendor":vendor,"driver":"","platform":"windows"})
    _GPU_CACHE = (now, [dict(x) for x in rows])
    return rows


def discover_dri_devices() -> list[dict[str, Any]]:
    if IS_WINDOWS:
        return discover_windows_gpus()
    dri = Path("/dev/dri")
    out: list[dict[str, Any]] = []
    if not dri.exists():
        return out
    for render in sorted(dri.glob("renderD*")):
        vendor_id, vendor = _sysfs_vendor_for_render(render.name)
        card = None
        try:
            target = (Path("/sys/class/drm") / render.name / "device").resolve()
            for c in sorted(dri.glob("card*")):
                sp = Path("/sys/class/drm") / c.name / "device"
                try:
                    if sp.resolve() == target:
                        card = str(c)
                        break
                except Exception:
                    pass
        except Exception:
            pass
        out.append({"render": str(render), "card": card, "vendor_id": vendor_id, "vendor": vendor, "platform":"linux"})
    return out


def nvidia_device_visible() -> bool:
    if IS_WINDOWS:
        if shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe"):
            return True
        return any(d.get("vendor") == "NVIDIA" for d in discover_windows_gpus())
    return any(Path(p).exists() for p in ("/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-modeset"))


def _vainfo(device: str) -> tuple[int, str]:
    if IS_WINDOWS:
        return 998, "VAAPI/vainfo is a Linux interface. Windows uses QSV, NVENC or AMF."
    if not shutil.which("vainfo"):
        return 998, "vainfo is not installed"
    return _run(["vainfo", "--display", "drm", "--device", device], timeout=8, env=os.environ.copy())


def _has_vendor(vendor: str) -> bool:
    return any(str(d.get("vendor") or "") == vendor for d in discover_dri_devices())


def profile_prerequisites(profile: str, preferred_vaapi_device: str | None = None) -> dict[str, Any]:
    profile = (profile or "software").strip().lower()
    enc = ffmpeg_encoders()
    devices = discover_dri_devices()
    render_paths = [str(d.get("render") or "") for d in devices if d.get("render")]
    selected_render = preferred_vaapi_device if preferred_vaapi_device in render_paths else (render_paths[0] if render_paths else "")

    if profile in ("software", "direct"):
        return {"available": True, "reason": "Available", "device": "", "encoder": "libx264" if profile == "software" else "copy"}
    if profile == "vaapi":
        if IS_WINDOWS:
            return {"available": False, "reason": "VAAPI is Linux-only; use Intel QSV, NVIDIA NVENC or AMD AMF on Windows", "device": "", "encoder": "h264_vaapi"}
        if "h264_vaapi" not in enc:
            return {"available": False, "reason": "FFmpeg h264_vaapi encoder is missing", "device": selected_render, "encoder": "h264_vaapi"}
        if not selected_render:
            return {"available": False, "reason": "No /dev/dri/renderD* device is visible in the container", "device": "", "encoder": "h264_vaapi"}
        return {"available": True, "reason": "VAAPI render device and FFmpeg encoder detected", "device": selected_render, "encoder": "h264_vaapi"}
    if profile == "qsv":
        if "h264_qsv" not in enc:
            return {"available": False, "reason": "FFmpeg h264_qsv encoder is missing", "device": selected_render, "encoder": "h264_qsv"}
        if IS_WINDOWS:
            if devices and not _has_vendor("Intel"):
                return {"available": False, "reason": "No Intel display adapter was detected by Windows", "device": "Windows D3D11/QSV", "encoder": "h264_qsv"}
            return {"available": True, "reason": "FFmpeg QSV encoder detected; Windows supplies the Intel device through the graphics driver", "device": "Windows QSV", "encoder": "h264_qsv"}
        if not selected_render:
            return {"available": False, "reason": "No /dev/dri/renderD* device is visible in the container", "device": "", "encoder": "h264_qsv"}
        if not _has_vendor("Intel"):
            return {"available": False, "reason": "No Intel DRM render device was detected", "device": selected_render, "encoder": "h264_qsv"}
        return {"available": True, "reason": "Intel render device and FFmpeg QSV encoder detected", "device": selected_render, "encoder": "h264_qsv"}
    if profile == "nvenc":
        if "h264_nvenc" not in enc:
            return {"available": False, "reason": "FFmpeg h264_nvenc encoder is missing", "device": "", "encoder": "h264_nvenc"}
        if not nvidia_device_visible():
            return {"available": False, "reason": "No NVIDIA GPU/driver was detected", "device": "", "encoder": "h264_nvenc"}
        return {"available": True, "reason": "NVIDIA GPU and FFmpeg NVENC encoder detected", "device": "Windows NVIDIA" if IS_WINDOWS else "/dev/nvidia0", "encoder": "h264_nvenc"}
    if profile == "amf":
        if "h264_amf" not in enc:
            return {"available": False, "reason": "FFmpeg h264_amf encoder is missing", "device": "", "encoder": "h264_amf"}
        if IS_WINDOWS and devices and not _has_vendor("AMD"):
            return {"available": False, "reason": "No AMD/Radeon display adapter was detected by Windows", "device": "Windows D3D11/AMF", "encoder": "h264_amf"}
        if not IS_WINDOWS:
            return {"available": False, "reason": "ViperTV uses AMF only in the native Windows build; Linux AMD uses VAAPI", "device": "", "encoder": "h264_amf"}
        return {"available": True, "reason": "AMD GPU and FFmpeg AMF encoder detected", "device": "Windows AMF", "encoder": "h264_amf"}
    return {"available": False, "reason": f"Unknown profile {profile}", "device": "", "encoder": ""}


def recommended_profile(preferred_vaapi_device: str | None = None) -> str:
    if IS_WINDOWS:
        # Prefer a discrete NVIDIA GPU, then Intel QSV, then AMD AMF.
        for p in ("nvenc", "qsv", "amf"):
            if profile_prerequisites(p, preferred_vaapi_device).get("available"):
                return p
        return "software"

    devices = discover_dri_devices()
    selected = None
    for d in devices:
        if d.get("render") == preferred_vaapi_device:
            selected = d
            break
    if selected is None and devices:
        selected = devices[0]
    if selected and selected.get("vendor") == "AMD" and profile_prerequisites("vaapi", preferred_vaapi_device).get("available"):
        return "vaapi"
    if selected and selected.get("vendor") == "Intel":
        if profile_prerequisites("vaapi", preferred_vaapi_device).get("available"):
            return "vaapi"
        if profile_prerequisites("qsv", preferred_vaapi_device).get("available"):
            return "qsv"
    if selected and selected.get("vendor") == "NVIDIA" and profile_prerequisites("nvenc", preferred_vaapi_device).get("available"):
        return "nvenc"
    for p in ("vaapi", "qsv", "nvenc"):
        if profile_prerequisites(p, preferred_vaapi_device).get("available"):
            return p
    return "software"


def status(preferred_vaapi_device: str | None = None) -> dict[str, Any]:
    enc = ffmpeg_encoders()
    devices = discover_dri_devices()
    render_paths = [str(d.get("render") or "") for d in devices if d.get("render")]
    selected = preferred_vaapi_device if preferred_vaapi_device in render_paths else (render_paths[0] if render_paths else "")
    vainfo_rc, vainfo_out = _vainfo(selected) if selected else (998, "Windows native GPU detection" if IS_WINDOWS else "No DRM render device is visible")
    return {
        "platform": "windows" if IS_WINDOWS else "linux",
        "devices": devices,
        "selected_vaapi_device": selected,
        "ffmpeg_encoders": sorted(enc),
        "software": profile_prerequisites("software", selected),
        "vaapi": profile_prerequisites("vaapi", selected),
        "qsv": profile_prerequisites("qsv", selected),
        "nvenc": profile_prerequisites("nvenc", selected),
        "amf": profile_prerequisites("amf", selected),
        "recommended": recommended_profile(selected),
        "vainfo_ok": vainfo_rc == 0,
        "vainfo": vainfo_out,
        "nvidia_visible": nvidia_device_visible(),
        "nvidia_smi": shutil.which("nvidia-smi") or shutil.which("nvidia-smi.exe") or "",
    }


def test_profile(profile: str, preferred_vaapi_device: str | None = None, timeout: int = 12) -> dict[str, Any]:
    profile = (profile or "software").strip().lower()
    prereq = profile_prerequisites(profile, preferred_vaapi_device)
    started = time.monotonic()
    if profile not in {"software", "vaapi", "qsv", "nvenc", "amf"}:
        return {"ok": False, "profile": profile, "elapsed": 0.0, "output": "Only software/VAAPI/QSV/NVENC/AMF can be tested."}
    if not prereq.get("available"):
        return {"ok": False, "profile": profile, "elapsed": 0.0, "output": str(prereq.get("reason") or "Unavailable")}

    base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1.0", "-an"]
    if profile == "software":
        base += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-f", "null", "-"]
    elif profile == "vaapi":
        dev = str(prereq.get("device") or preferred_vaapi_device or "/dev/dri/renderD128")
        base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-vaapi_device", dev, "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1.0", "-an", "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-"]
    elif profile == "qsv":
        if IS_WINDOWS:
            base += ["-c:v", "h264_qsv", "-global_quality", "24", "-pix_fmt", "nv12", "-f", "null", "-"]
        else:
            dev = str(prereq.get("device") or preferred_vaapi_device or "/dev/dri/renderD128")
            base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-qsv_device", dev, "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1.0", "-an", "-vf", "format=nv12", "-c:v", "h264_qsv", "-f", "null", "-"]
    elif profile == "amf":
        base += ["-c:v", "h264_amf", "-quality", "speed", "-pix_fmt", "nv12", "-f", "null", "-"]
    else:
        base += ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-pix_fmt", "yuv420p", "-f", "null", "-"]

    rc, out = _run(base, timeout=timeout)
    elapsed = round(time.monotonic() - started, 3)
    return {"ok": rc == 0, "profile": profile, "elapsed": elapsed, "output": out[-8000:] or ("Test completed successfully." if rc == 0 else f"FFmpeg exited with code {rc}."), "command_summary": " ".join(base[:12]) + " …"}


def is_hardware_profile(profile: str) -> bool:
    return (profile or "").strip().lower() in _HW_PROFILES


def profile_label(profile: str) -> str:
    return {
        "global": "Use Global Default",
        "auto": "Auto Detect",
        "software": "Software (libx264)",
        "vaapi": "VAAPI (Intel / AMD — Linux)",
        "qsv": "Intel Quick Sync (QSV)",
        "nvenc": "NVIDIA NVENC",
        "amf": "AMD AMF",
        "direct": "Direct / Copy",
    }.get((profile or "").strip().lower(), profile or "Unknown")


def ffmpeg_device_args(profile: str, preferred_vaapi_device: str | None = None) -> list[str]:
    """Return platform-correct FFmpeg device-selection arguments."""
    p = (profile or '').strip().lower()
    prereq = profile_prerequisites(p, preferred_vaapi_device) if p in _HW_PROFILES else {}
    if p == 'vaapi' and not IS_WINDOWS:
        return ['-vaapi_device', str(prereq.get('device') or preferred_vaapi_device or '/dev/dri/renderD128')]
    if p == 'qsv' and not IS_WINDOWS:
        return ['-qsv_device', str(prereq.get('device') or preferred_vaapi_device or '/dev/dri/renderD128')]
    return []


def h264_encoder_args(profile: str, bitrate: str) -> list[str]:
    p = (profile or '').strip().lower()
    if p == 'qsv':
        return ['-c:v','h264_qsv','-b:v',str(bitrate)]
    if p == 'vaapi':
        return ['-c:v','h264_vaapi','-b:v',str(bitrate)]
    if p == 'nvenc':
        return ['-c:v','h264_nvenc','-preset','p4','-tune','ll','-b:v',str(bitrate)]
    if p == 'amf':
        return ['-c:v','h264_amf','-quality','speed','-b:v',str(bitrate)]
    return []
