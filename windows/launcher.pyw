from __future__ import annotations

import ctypes
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime"
PYTHONW = RUNTIME / "pythonw.exe"
PYTHON = RUNTIME / "python.exe"
FFMPEG_DIR = RUNTIME / "ffmpeg" / "bin"
INSTALLED = (ROOT / "installed.mode").exists()
PORT = int(os.environ.get("VIPERTV_PORT", "8409") or "8409")


def data_root() -> Path:
    explicit = os.environ.get("VIPERTV_WINDOWS_DATA_ROOT", "").strip()
    if explicit:
        return Path(explicit)
    if INSTALLED:
        return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ViperTV"
    return ROOT / "UserData"


DATA_ROOT = data_root()
DATA_DIR = DATA_ROOT / "data"
LOG_DIR = DATA_ROOT / "logs"
PID_FILE = DATA_ROOT / "vipertv.pid"
PROXY_PID_FILE = DATA_ROOT / "streaming-proxy.pid"
LOG_FILE = LOG_DIR / "vipertv.log"


def msg(text: str, title: str = "ViperTV") -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, str(text), title, 0x40)
    except Exception:
        pass


def ensure_dirs() -> None:
    for p in (DATA_ROOT, DATA_DIR, DATA_DIR / "backups", DATA_ROOT / "backups-secondary", LOG_DIR, DATA_ROOT / "updates"):
        p.mkdir(parents=True, exist_ok=True)


def env() -> dict[str, str]:
    e = os.environ.copy()
    e["VIPERTV_DATA_DIR"] = str(DATA_DIR)
    e["VIPERTV_SECONDARY_BACKUP_DIR"] = str(DATA_ROOT / "backups-secondary")
    e["VIPERTV_WINDOWS_STANDALONE"] = "1"
    e["VIPERTV_PORT"] = str(PORT)
    e["VIPERTV_SOURCE_ROOT"] = str(ROOT)
    e.setdefault("VIPERTV_BACKUP_KEEP", "60")
    e.setdefault("VIPERTV_AUTO_SCAN_HOURS", "6")
    e.setdefault("TZ", "UTC")
    e["PATH"] = str(FFMPEG_DIR) + os.pathsep + str(RUNTIME) + os.pathsep + e.get("PATH", "")
    return e


def health_ok(timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/healthz", timeout=timeout) as r:
            if r.status != 200:
                return False
            payload = json.loads(r.read().decode("utf-8", errors="replace"))
            return isinstance(payload, dict) and payload.get("status") == "ok" and bool(payload.get("version"))
    except Exception:
        return False


def read_pid(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except Exception:
        return 0


def process_command_line(pid: int) -> str:
    if pid <= 0:
        return ""
    try:
        script = (
            "$p=Get-CimInstance Win32_Process -Filter \"ProcessId = %d\" -ErrorAction SilentlyContinue;"
            "if($p){[Console]::Out.Write($p.CommandLine)}" % pid
        )
        cp = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=5,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (cp.stdout or "").strip()
    except Exception:
        return ""


def process_alive(pid: int, expected: tuple[str, ...] = ()) -> bool:
    cmd = process_command_line(pid)
    if not cmd:
        return False
    low = cmd.casefold()
    return all(token.casefold() in low for token in expected)


def streaming_only_port() -> int:
    db = DATA_DIR / "vipertv.db"
    if not db.exists():
        return 0
    try:
        con = sqlite3.connect(db)
        row = con.execute("SELECT value FROM settings WHERE key='streaming_only_port'").fetchone()
        con.close()
        p = int(row[0]) if row and row[0] else 0
        return p if p not in (PORT,) and 1 <= p <= 65535 else 0
    except Exception:
        return 0


def start_proxy(e: dict[str, str]) -> None:
    p = streaming_only_port()
    if not p:
        return
    old = read_pid(PROXY_PID_FILE)
    if process_alive(old, ("streaming_proxy.py",)):
        return
    proxy = ROOT / "windows" / "streaming_proxy.py"
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    with open(LOG_DIR / "streaming-proxy.log", "ab", buffering=0) as log:
        proc = subprocess.Popen([str(PYTHONW), str(proxy), str(p), str(PORT)], cwd=str(ROOT), env=e,
                                stdout=log, stderr=log, creationflags=creation)
    PROXY_PID_FILE.write_text(str(proc.pid))


def start(open_browser: bool = True) -> None:
    ensure_dirs()
    if health_ok():
        if open_browser:
            webbrowser.open(f"http://127.0.0.1:{PORT}/")
        return
    if not PYTHONW.exists():
        msg("The bundled Python runtime is missing. Use the Windows Standalone release package, not the source-only package.")
        return
    if not (FFMPEG_DIR / "ffmpeg.exe").exists():
        msg("The bundled FFmpeg runtime is missing. Use the Windows Standalone release package, not the source-only package.")
        return
    e = env()
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    log = open(LOG_FILE, "ab", buffering=0)
    cmd = [str(PYTHONW), "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(PORT), "--workers", "1"]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), env=e, stdout=log, stderr=log, creationflags=creation)
    PID_FILE.write_text(str(proc.pid))
    deadline = time.time() + 40
    while time.time() < deadline:
        if health_ok(1.0):
            start_proxy(e)
            if open_browser:
                webbrowser.open(f"http://127.0.0.1:{PORT}/")
            return
        if proc.poll() is not None:
            break
        time.sleep(0.5)
    msg(f"ViperTV did not finish starting. Check the log:\n{LOG_FILE}")


def kill_pid(pid: int, expected: tuple[str, ...]) -> None:
    if pid <= 0 or not process_alive(pid, expected):
        return
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=10)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass


def stop(show: bool = True) -> None:
    # Never kill a recycled PID unless its command line still identifies the ViperTV process.
    kill_pid(read_pid(PROXY_PID_FILE), ("streaming_proxy.py",))
    kill_pid(read_pid(PID_FILE), ("uvicorn", "app.main:app"))
    for p in (PROXY_PID_FILE, PID_FILE):
        try:
            p.unlink()
        except Exception:
            pass
    if show:
        msg("ViperTV has been stopped.")


def open_ui() -> None:
    if not health_ok():
        start(False)
    webbrowser.open(f"http://127.0.0.1:{PORT}/")


def show_logs() -> None:
    ensure_dirs()
    if not LOG_FILE.exists():
        LOG_FILE.touch()
    subprocess.Popen(["notepad.exe", str(LOG_FILE)])


def main() -> None:
    action = (sys.argv[1] if len(sys.argv) > 1 else "start").lower()
    if action == "start":
        start(True)
    elif action == "start-silent":
        start(False)
    elif action == "stop":
        stop(True)
    elif action == "stop-silent":
        stop(False)
    elif action == "restart":
        stop(False); time.sleep(1); start(True)
    elif action == "open":
        open_ui()
    elif action == "logs":
        show_logs()
    else:
        start(True)


if __name__ == "__main__":
    main()
