from __future__ import annotations

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

_HW_PROFILES = {"vaapi", "qsv", "nvenc"}
_ENCODER_CACHE: tuple[float, set[str]] | None = None


def _run(args: list[str], timeout: int = 8, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        cp = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=env or os.environ.copy(),
        )
        return int(cp.returncode), (cp.stdout or "")[-16000:]
    except Exception as exc:
        return 999, str(exc)


def ffmpeg_encoders() -> set[str]:
    global _ENCODER_CACHE
    now = time.monotonic()
    if _ENCODER_CACHE and now - _ENCODER_CACHE[0] < 60.0:
        return set(_ENCODER_CACHE[1])
    rc, out = _run(["ffmpeg", "-hide_banner", "-encoders"], timeout=8)
    if rc != 0:
        _ENCODER_CACHE = (now, set())
        return set()
    found: set[str] = set()
    for line in out.splitlines():
        m = re.match(r"^\s*[VAS\.]{6}\s+([^\s]+)", line)
        if m:
            found.add(m.group(1).strip())
    # The regex above intentionally stays conservative.  Fall back to token
    # discovery for distro FFmpeg builds whose flag columns differ.
    for name in ("libx264", "h264_vaapi", "hevc_vaapi", "h264_qsv", "hevc_qsv", "h264_nvenc", "hevc_nvenc"):
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


def discover_dri_devices() -> list[dict[str, Any]]:
    dri = Path("/dev/dri")
    out: list[dict[str, Any]] = []
    if not dri.exists():
        return out
    for render in sorted(dri.glob("renderD*")):
        vendor_id, vendor = _sysfs_vendor_for_render(render.name)
        card = None
        # Match the card through sysfs device symlinks when possible.
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
        out.append({
            "render": str(render),
            "card": card,
            "vendor_id": vendor_id,
            "vendor": vendor,
        })
    return out


def nvidia_device_visible() -> bool:
    return any(Path(p).exists() for p in ("/dev/nvidia0", "/dev/nvidiactl", "/dev/nvidia-modeset"))


def _vainfo(device: str) -> tuple[int, str]:
    if not shutil.which("vainfo"):
        return 998, "vainfo is not installed"
    env = os.environ.copy()
    # Respect an explicitly configured driver, but do not force i965.  Let
    # libva choose i965/iHD/radeonsi automatically on mixed/newer systems.
    return _run(["vainfo", "--display", "drm", "--device", device], timeout=8, env=env)


def profile_prerequisites(profile: str, preferred_vaapi_device: str | None = None) -> dict[str, Any]:
    profile = (profile or "software").strip().lower()
    enc = ffmpeg_encoders()
    devices = discover_dri_devices()
    render_paths = [d["render"] for d in devices]
    selected_render = preferred_vaapi_device if preferred_vaapi_device in render_paths else (render_paths[0] if render_paths else "")

    if profile in ("software", "direct"):
        return {"available": True, "reason": "Available", "device": "", "encoder": "libx264" if profile == "software" else "copy"}
    if profile == "vaapi":
        if "h264_vaapi" not in enc:
            return {"available": False, "reason": "FFmpeg h264_vaapi encoder is missing", "device": selected_render, "encoder": "h264_vaapi"}
        if not selected_render:
            return {"available": False, "reason": "No /dev/dri/renderD* device is visible in the container", "device": "", "encoder": "h264_vaapi"}
        return {"available": True, "reason": "VAAPI render device and FFmpeg encoder detected", "device": selected_render, "encoder": "h264_vaapi"}
    if profile == "qsv":
        if "h264_qsv" not in enc:
            return {"available": False, "reason": "FFmpeg h264_qsv encoder is missing", "device": selected_render, "encoder": "h264_qsv"}
        if not selected_render:
            return {"available": False, "reason": "No /dev/dri/renderD* device is visible in the container", "device": "", "encoder": "h264_qsv"}
        intel = any(d.get("vendor") == "Intel" for d in devices)
        if not intel:
            return {"available": False, "reason": "No Intel DRM render device was detected", "device": selected_render, "encoder": "h264_qsv"}
        return {"available": True, "reason": "Intel render device and FFmpeg QSV encoder detected", "device": selected_render, "encoder": "h264_qsv"}
    if profile == "nvenc":
        if "h264_nvenc" not in enc:
            return {"available": False, "reason": "FFmpeg h264_nvenc encoder is missing", "device": "", "encoder": "h264_nvenc"}
        if not nvidia_device_visible():
            return {"available": False, "reason": "NVIDIA device nodes are not visible in the container", "device": "", "encoder": "h264_nvenc"}
        return {"available": True, "reason": "NVIDIA device and FFmpeg NVENC encoder detected", "device": "/dev/nvidia0", "encoder": "h264_nvenc"}
    return {"available": False, "reason": f"Unknown profile {profile}", "device": "", "encoder": ""}


def recommended_profile(preferred_vaapi_device: str | None = None) -> str:
    devices = discover_dri_devices()
    selected = None
    for d in devices:
        if d.get("render") == preferred_vaapi_device:
            selected = d
            break
    if selected is None and devices:
        selected = devices[0]

    # Prefer the selected GPU first.  Older Intel systems are often more
    # reliable through VAAPI than QSV in Linux containers, so Intel VAAPI is
    # tried before QSV.  NVIDIA is preferred when it is the only/selected GPU.
    if selected and selected.get("vendor") == "AMD":
        if profile_prerequisites("vaapi", preferred_vaapi_device).get("available"):
            return "vaapi"
    if selected and selected.get("vendor") == "Intel":
        if profile_prerequisites("vaapi", preferred_vaapi_device).get("available"):
            return "vaapi"
        if profile_prerequisites("qsv", preferred_vaapi_device).get("available"):
            return "qsv"
    if selected and selected.get("vendor") == "NVIDIA":
        if profile_prerequisites("nvenc", preferred_vaapi_device).get("available"):
            return "nvenc"

    # Mixed-GPU fallback order.
    if profile_prerequisites("vaapi", preferred_vaapi_device).get("available"):
        return "vaapi"
    if profile_prerequisites("qsv", preferred_vaapi_device).get("available"):
        return "qsv"
    if profile_prerequisites("nvenc", preferred_vaapi_device).get("available"):
        return "nvenc"
    return "software"


def status(preferred_vaapi_device: str | None = None) -> dict[str, Any]:
    enc = ffmpeg_encoders()
    devices = discover_dri_devices()
    render_paths = [d["render"] for d in devices]
    selected = preferred_vaapi_device if preferred_vaapi_device in render_paths else (render_paths[0] if render_paths else "")
    vainfo_rc, vainfo_out = _vainfo(selected) if selected else (998, "No DRM render device is visible")
    return {
        "devices": devices,
        "selected_vaapi_device": selected,
        "ffmpeg_encoders": sorted(enc),
        "software": profile_prerequisites("software", selected),
        "vaapi": profile_prerequisites("vaapi", selected),
        "qsv": profile_prerequisites("qsv", selected),
        "nvenc": profile_prerequisites("nvenc", selected),
        "recommended": recommended_profile(selected),
        "vainfo_ok": vainfo_rc == 0,
        "vainfo": vainfo_out,
        "nvidia_visible": nvidia_device_visible(),
        "nvidia_smi": shutil.which("nvidia-smi") or "",
    }


def test_profile(profile: str, preferred_vaapi_device: str | None = None, timeout: int = 12) -> dict[str, Any]:
    profile = (profile or "software").strip().lower()
    prereq = profile_prerequisites(profile, preferred_vaapi_device)
    started = time.monotonic()
    if profile not in {"software", "vaapi", "qsv", "nvenc"}:
        return {"ok": False, "profile": profile, "elapsed": 0.0, "output": "Only software/VAAPI/QSV/NVENC can be tested."}
    if not prereq.get("available"):
        return {"ok": False, "profile": profile, "elapsed": 0.0, "output": str(prereq.get("reason") or "Unavailable")}

    base = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
        "-t", "1.0", "-an",
    ]
    if profile == "software":
        base += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-f", "null", "-"]
    elif profile == "vaapi":
        dev = str(prereq.get("device") or preferred_vaapi_device or "/dev/dri/renderD128")
        base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-vaapi_device", dev,
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1.0", "-an",
                "-vf", "format=nv12,hwupload", "-c:v", "h264_vaapi", "-f", "null", "-"]
    elif profile == "qsv":
        dev = str(prereq.get("device") or preferred_vaapi_device or "/dev/dri/renderD128")
        base = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-qsv_device", dev,
                "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "1.0", "-an",
                "-vf", "format=nv12", "-c:v", "h264_qsv", "-f", "null", "-"]
    else:
        base += ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "ll", "-pix_fmt", "yuv420p", "-f", "null", "-"]

    rc, out = _run(base, timeout=timeout)
    elapsed = round(time.monotonic() - started, 3)
    return {
        "ok": rc == 0,
        "profile": profile,
        "elapsed": elapsed,
        "output": out[-8000:] or ("Test completed successfully." if rc == 0 else f"FFmpeg exited with code {rc}."),
        "command_summary": " ".join(base[:12]) + " …",
    }


def is_hardware_profile(profile: str) -> bool:
    return (profile or "").strip().lower() in _HW_PROFILES


def profile_label(profile: str) -> str:
    return {
        "global": "Use Global Default",
        "auto": "Auto Detect",
        "software": "Software (libx264)",
        "vaapi": "VAAPI (Intel / AMD)",
        "qsv": "Intel Quick Sync (QSV)",
        "nvenc": "NVIDIA NVENC",
        "direct": "Direct / Copy",
    }.get((profile or "").strip().lower(), profile or "Unknown")
