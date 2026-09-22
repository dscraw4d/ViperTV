from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone, time as dt_time
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request as URLRequest, urlopen
from xml.etree import ElementTree
from bs4 import BeautifulSoup
from . import hardware_accel as hwaccel

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse, FileResponse

APP_NAME = "ViperTV"
APP_VERSION = "1.5.0"
DATA_DIR = Path(os.getenv("VIPERTV_DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "vipertv.db"
BACKUP_DIR = DATA_DIR / "backups"
SECONDARY_BACKUP_DIR = Path(os.getenv("VIPERTV_SECONDARY_BACKUP_DIR", "/backup2"))
BACKUP_KEEP = int(os.getenv("VIPERTV_BACKUP_KEEP", "60"))
AUTO_SCAN_HOURS = float(os.getenv("VIPERTV_AUTO_SCAN_HOURS", "6"))
PUBLIC_BASE_URL = os.getenv("VIPERTV_PUBLIC_BASE_URL", "").rstrip("/")
TRANSCODE_PRESET = os.getenv("VIPERTV_TRANSCODE_PRESET", "veryfast")
VIDEO_BITRATE = os.getenv("VIPERTV_VIDEO_BITRATE", "5000k")
AUDIO_BITRATE = os.getenv("VIPERTV_AUDIO_BITRATE", "192k")
PLEX_MAX_VIDEO_BITRATE = int(os.getenv("VIPERTV_PLEX_MAX_VIDEO_BITRATE", "20000"))
PLEX_VIDEO_RESOLUTION = os.getenv("VIPERTV_PLEX_VIDEO_RESOLUTION", "1920x1080").strip()
PLEX_SYNC_PAGE_SIZE = int(os.getenv("VIPERTV_PLEX_SYNC_PAGE_SIZE", "500"))
PLEX_RICH_EPISODE_CREDITS = os.getenv("VIPERTV_PLEX_RICH_EPISODE_CREDITS", "1").strip().lower() not in {"0","false","no","off"}
PLEX_RICH_EPISODE_BATCH_SIZE = min(100, max(1, int(os.getenv("VIPERTV_PLEX_RICH_EPISODE_BATCH_SIZE", "40"))))
PLEX_AUTO_SYNC_DAYS = max(1, int(os.getenv("VIPERTV_PLEX_AUTO_SYNC_DAYS", "3")))
PLEX_AUTO_SYNC_HOUR = min(23, max(0, int(os.getenv("VIPERTV_PLEX_AUTO_SYNC_HOUR", "7"))))
DEFAULT_TIMEZONE = os.getenv("TZ", "UTC").strip() or "UTC"
PLEX_AUTO_SYNC_TIMEZONE = os.getenv("VIPERTV_PLEX_AUTO_SYNC_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
TVDB_API_BASE = os.getenv("VIPERTV_TVDB_API_BASE", "https://api4.thetvdb.com/v4").rstrip("/")
TVDB_REFRESH_DAYS = max(1, int(os.getenv("VIPERTV_TVDB_REFRESH_DAYS", "30")))

# Pluto TV live source integration (v1.1.27). Pluto remains the broadcaster;
# ViperTV discovers the regional channel lineup, stores a guide cache, and
# remuxes selected FAST channels into the same M3U/XMLTV/browser surfaces.
PLUTO_BOOT_URL = os.getenv("VIPERTV_PLUTO_BOOT_URL", "https://boot.pluto.tv/v4/start")
PLUTO_CHANNELS_URL = os.getenv("VIPERTV_PLUTO_CHANNELS_URL", "https://service-channels.clusters.pluto.tv/v2/guide/channels")
PLUTO_CATEGORIES_URL = os.getenv("VIPERTV_PLUTO_CATEGORIES_URL", "https://service-channels.clusters.pluto.tv/v2/guide/categories")
PLUTO_TIMELINES_URL = os.getenv("VIPERTV_PLUTO_TIMELINES_URL", "https://service-channels.clusters.pluto.tv/v2/guide/timelines")
PLUTO_STITCHER_FALLBACK = os.getenv("VIPERTV_PLUTO_STITCHER_FALLBACK", "https://cfd-v4-service-channel-stitcher-use1-1.prd.pluto.tv")
PLUTO_DEFAULT_REGION = os.getenv("VIPERTV_PLUTO_REGION", "ca").strip().lower() or "ca"
PLUTO_DEFAULT_NUMBER_OFFSET = int(os.getenv("VIPERTV_PLUTO_NUMBER_OFFSET", "1000"))
PLUTO_AUTO_SYNC_HOURS = max(1, int(os.getenv("VIPERTV_PLUTO_AUTO_SYNC_HOURS", "24")))
PLUTO_SYNC_STATUS: dict[str, Any] = {
    "running": False, "stage": "Idle", "done": 0, "total": 0, "current": "",
    "channels": 0, "guide_programmes": 0, "started_at": None, "finished_at": None,
    "error": None,
}
PLUTO_BOOT_CACHE: dict[str, dict[str, Any]] = {}
PLUTO_REGION_IPS = {
    "us":"185.236.200.172", "gb":"185.199.220.58", "de":"85.214.132.117",
    "es":"88.26.241.248", "ca":"192.206.151.131", "br":"177.47.27.205",
    "mx":"200.68.128.83", "fr":"176.31.84.249", "it":"5.133.48.0",
    "ar":"104.103.238.0", "cl":"161.238.0.0", "se":"185.39.146.168",
    "dk":"80.63.84.58", "no":"84.214.150.146", "au":"144.48.37.140",
}

# Live-TV low-latency defaults. The shared station feed already contains stable
# PAT/PMT and continuous timestamps, so downstream clients do not need FFmpeg's
# multi-second generic-file probing/buffering defaults. These remain tunable for
# unusual clients/sources without changing the database.
LIVE_PROBE_SIZE = max(32768, int(os.getenv("VIPERTV_LIVE_PROBE_SIZE", "131072")))
LIVE_ANALYZE_US = max(50000, int(os.getenv("VIPERTV_LIVE_ANALYZE_US", "250000")))
LIVE_CLIENT_QUEUE_CHUNKS = max(8, int(os.getenv("VIPERTV_SHARED_STREAM_QUEUE_CHUNKS", "24")))
HLS_SEGMENT_SECONDS = max(0.5, float(os.getenv("VIPERTV_HLS_SEGMENT_SECONDS", "1")))

VIDEO_EXTS = {
    ".mp4", ".mkv", ".m4v", ".avi", ".mov", ".mpg", ".mpeg", ".ts", ".m2ts",
    ".webm", ".wmv", ".flv", ".vob", ".ogv"
}

SEASON_PATTERNS = [
    re.compile(r"^(?:season|series)\s*0*(\d+)$", re.I),
    re.compile(r"^s0*(\d+)$", re.I),
]
EPISODE_PATTERNS = [
    re.compile(r"(?i)\bS(\d{1,2})\s*E(\d{1,3})(?:\s*[-_. ]+\s*(.*))?"),
    re.compile(r"(?i)\b(\d{1,2})x(\d{1,3})(?:\s*[-_. ]+\s*(.*))?"),
]

PLEX_SYNC_STATUS: dict[int, dict[str, Any]] = {}
PLEX_SYNC_ALL_STATUS: dict[str, Any] = {"running": False, "done": 0, "total": 0, "current": "", "results": [], "started_at": None, "finished_at": None}
PLEX_RICH_STATUS: dict[int, dict[str, Any]] = {}
BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()
TVDB_ENRICH_STATUS: dict[str, Any] = {
    "running": False, "stage": "Idle", "done": 0, "total": 0, "current": "",
    "matched": 0, "failed": 0, "skipped": 0, "started_at": None,
    "finished_at": None, "error": None, "force": False
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with db() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default
    except sqlite3.Error:
        return default


def set_setting(key: str, value: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


HARDWARE_STREAM_PROFILES = {"global", "auto", "software", "vaapi", "qsv", "nvenc", "direct"}


def hardware_global_profile() -> str:
    value = str(get_setting("hardware_default_profile", os.getenv("VIPERTV_DEFAULT_STREAM_PROFILE", "auto")) or "auto").strip().lower()
    return value if value in {"auto", "software", "vaapi", "qsv", "nvenc", "direct"} else "auto"


def hardware_preferred_vaapi_device() -> str:
    return str(get_setting("hardware_vaapi_device", "") or "").strip()


def hardware_fallback_enabled() -> bool:
    return str(get_setting("hardware_software_fallback", "1") or "1").strip().lower() not in {"0", "false", "no", "off"}


def default_new_channel_stream_profile() -> str:
    # New channels follow the central hardware setting.  Existing channels keep
    # their explicit profile until the user switches them to Global in System.
    return "global"


def effective_stream_profile(channel: Any, profile_override: str | None = None) -> tuple[str, str, str]:
    """Return (effective, configured, warning) for a channel/profile request."""
    if profile_override:
        configured = str(profile_override).strip().lower()
    else:
        try:
            configured = str(channel["stream_profile"] or "global").strip().lower()
        except Exception:
            configured = "global"
    if configured not in HARDWARE_STREAM_PROFILES:
        configured = "software"
    requested = hardware_global_profile() if configured == "global" else configured
    preferred = hardware_preferred_vaapi_device() or None
    if requested == "auto":
        requested = hwaccel.recommended_profile(preferred)
    warning = ""
    if requested in {"vaapi", "qsv", "nvenc"}:
        prereq = hwaccel.profile_prerequisites(requested, preferred)
        if not prereq.get("available") and hardware_fallback_enabled():
            warning = f"{hwaccel.profile_label(requested)} unavailable: {prereq.get('reason')}; using software."
            requested = "software"
    return requested, configured, warning


def _restart_shared_channel_if_running(channel_id: int) -> None:
    try:
        streams = globals().get("SHARED_CHANNEL_STREAMS", {})
        state = streams.get(int(channel_id)) if isinstance(streams, dict) else None
        if state:
            state["stop"] = True
    except Exception:
        pass


def plex_auto_sync_tz() -> ZoneInfo:
    try:
        return ZoneInfo(PLEX_AUTO_SYNC_TIMEZONE)
    except Exception:
        return ZoneInfo("UTC")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _next_local_7am(after: datetime | None = None) -> datetime:
    tz = plex_auto_sync_tz()
    now = (after or datetime.now(tz)).astimezone(tz)
    candidate = datetime.combine(now.date(), dt_time(PLEX_AUTO_SYNC_HOUR, 0), tzinfo=tz)
    if candidate <= now:
        candidate = datetime.combine(now.date() + timedelta(days=1), dt_time(PLEX_AUTO_SYNC_HOUR, 0), tzinfo=tz)
    return candidate


def ensure_plex_auto_sync_schedule() -> datetime:
    """Return the next scheduled Plex sync, preserving a 3-day local-time cadence.

    The timestamp is persisted in SQLite so container restarts do not reset the
    72-hour cadence. If ViperTV was offline for a scheduled run, missed slots are
    advanced in 3-day steps to the next future 7:00 AM Pacific slot.
    """
    tz = plex_auto_sync_tz()
    now = datetime.now(tz)
    saved = _parse_iso_datetime(get_setting("plex_auto_sync_next_at"))
    if saved:
        candidate = saved.astimezone(tz)
        while candidate <= now:
            next_date = candidate.date() + timedelta(days=PLEX_AUTO_SYNC_DAYS)
            candidate = datetime.combine(next_date, dt_time(PLEX_AUTO_SYNC_HOUR, 0), tzinfo=tz)
    else:
        candidate = _next_local_7am(now)
    set_setting("plex_auto_sync_next_at", candidate.astimezone(timezone.utc).isoformat())
    return candidate


def set_next_plex_auto_sync_from(run_local: datetime | None = None) -> datetime:
    tz = plex_auto_sync_tz()
    base = (run_local or datetime.now(tz)).astimezone(tz)
    next_date = base.date() + timedelta(days=PLEX_AUTO_SYNC_DAYS)
    candidate = datetime.combine(next_date, dt_time(PLEX_AUTO_SYNC_HOUR, 0), tzinfo=tz)
    set_setting("plex_auto_sync_next_at", candidate.astimezone(timezone.utc).isoformat())
    return candidate


def format_plex_schedule_time(value: str | None) -> str:
    dt = _parse_iso_datetime(value)
    if not dt:
        return "Never"
    return dt.astimezone(plex_auto_sync_tz()).strftime("%a %b %d, %Y %I:%M %p %Z")


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SECONDARY_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def db() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {r["name"]: r for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    """Create/upgrade the database without discarding v0.1 data."""
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
                path TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                duration REAL NOT NULL DEFAULT 0,
                size INTEGER NOT NULL DEFAULT 0,
                mtime REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_media_library ON media(library_id);

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )

        # v0.2 local TV metadata fields.
        add_column_if_missing(conn, "media", "show_title", "TEXT")
        add_column_if_missing(conn, "media", "season_number", "INTEGER")
        add_column_if_missing(conn, "media", "episode_number", "INTEGER")
        add_column_if_missing(conn, "media", "episode_title", "TEXT")
        # Large TV libraries benefit heavily from a composite hierarchy index.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_show_picker ON media(library_id,show_title,season_number,episode_number)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_duration ON media(library_id,duration)")

        # Rebuild v0.1 channels once so a channel is no longer forced to use one local library.
        existing_channels = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='channels'"
        ).fetchone()
        if not existing_channels:
            conn.executescript(
                """
                CREATE TABLE channels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    library_id INTEGER REFERENCES libraries(id) ON DELETE SET NULL,
                    shuffle INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
        else:
            ccols = table_columns(conn, "channels")
            # v0.1 library_id was NOT NULL. SQLite can't remove NOT NULL in place.
            if ccols.get("library_id") and int(ccols["library_id"]["notnull"]) == 1:
                conn.execute("PRAGMA foreign_keys=OFF")
                conn.executescript(
                    """
                    ALTER TABLE channels RENAME TO channels_v01;
                    CREATE TABLE channels (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        number TEXT NOT NULL UNIQUE,
                        name TEXT NOT NULL,
                        library_id INTEGER REFERENCES libraries(id) ON DELETE SET NULL,
                        shuffle INTEGER NOT NULL DEFAULT 0,
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL
                    );
                    INSERT INTO channels(id,number,name,library_id,shuffle,enabled,created_at)
                    SELECT id,number,name,library_id,shuffle,enabled,created_at FROM channels_v01;
                    DROP TABLE channels_v01;
                    """
                )
                conn.execute("PRAGMA foreign_keys=ON")

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS plex_servers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL,
                machine_identifier TEXT,
                product_version TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS plex_libraries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
                section_key TEXT NOT NULL,
                title TEXT NOT NULL,
                library_type TEXT NOT NULL,
                uuid TEXT,
                last_synced_at TEXT,
                item_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(server_id, section_key)
            );

            CREATE TABLE IF NOT EXISTS plex_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plex_library_id INTEGER NOT NULL REFERENCES plex_libraries(id) ON DELETE CASCADE,
                rating_key TEXT NOT NULL,
                plex_key TEXT NOT NULL,
                media_type TEXT NOT NULL,
                title TEXT NOT NULL,
                show_rating_key TEXT,
                show_title TEXT,
                season_rating_key TEXT,
                season_number INTEGER,
                episode_number INTEGER,
                duration REAL NOT NULL DEFAULT 0,
                summary TEXT,
                originally_available_at TEXT,
                thumb TEXT,
                year INTEGER,
                updated_at TEXT NOT NULL,
                UNIQUE(plex_library_id, rating_key)
            );

            CREATE INDEX IF NOT EXISTS idx_plex_media_library ON plex_media(plex_library_id);
            CREATE INDEX IF NOT EXISTS idx_plex_media_show ON plex_media(plex_library_id, show_rating_key, season_number, episode_number);

            CREATE TABLE IF NOT EXISTS channel_selections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
                source_type TEXT NOT NULL CHECK(source_type IN ('local','plex')),
                library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
                plex_library_id INTEGER REFERENCES plex_libraries(id) ON DELETE CASCADE,
                selection_type TEXT NOT NULL CHECK(selection_type IN ('library','show','season','movie')),
                show_key TEXT,
                show_title TEXT,
                season_number INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_channel_selections_channel ON channel_selections(channel_id);
            """
        )

        # v0.2.2 lets a discovered Plex library be removed from ViperTV without
        # deleting anything from Plex. Disabled libraries remain tombstoned so
        # a later Discover Libraries does not silently add them back.
        add_column_if_missing(conn, "plex_libraries", "enabled", "INTEGER NOT NULL DEFAULT 1")

        # v1.1.11 show-level metadata used by the automatic Channel Builder.
        add_column_if_missing(conn, "media", "original_network", "TEXT")
        add_column_if_missing(conn, "media", "show_year", "INTEGER")
        add_column_if_missing(conn, "plex_media", "original_network", "TEXT")
        add_column_if_missing(conn, "plex_media", "show_year", "INTEGER")
        # Full episode metadata cache for exact Plex guest/director credits.
        add_column_if_missing(conn, "plex_media", "plex_updated_at", "INTEGER")
        add_column_if_missing(conn, "plex_media", "rich_people_plex_updated_at", "INTEGER")
        add_column_if_missing(conn, "plex_media", "rich_people_at", "TEXT")
        add_column_if_missing(conn, "plex_media", "rich_people_count", "INTEGER NOT NULL DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plex_rich_people ON plex_media(plex_library_id,media_type,rich_people_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_network_year ON media(library_id,original_network,show_year,show_title)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plex_network_year ON plex_media(plex_library_id,original_network,show_year,show_rating_key)")
        conn.execute("""CREATE TABLE IF NOT EXISTS show_metadata_overrides(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL CHECK(source_type IN ('local','plex')),
            library_id INTEGER NOT NULL,
            show_key TEXT NOT NULL,
            show_title TEXT NOT NULL,
            original_network TEXT,
            show_year INTEGER,
            updated_at TEXT NOT NULL,
            UNIQUE(source_type,library_id,show_key)
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tvdb_show_metadata(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL CHECK(source_type IN ('local','plex')),
            library_id INTEGER NOT NULL,
            show_key TEXT NOT NULL,
            show_title TEXT NOT NULL,
            tvdb_id INTEGER,
            original_network TEXT,
            show_year INTEGER,
            genres_json TEXT NOT NULL DEFAULT '[]',
            series_status TEXT,
            match_method TEXT,
            matched_title TEXT,
            refreshed_at TEXT,
            last_error TEXT,
            UNIQUE(source_type,library_id,show_key)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tvdb_show_lookup ON tvdb_show_metadata(source_type,library_id,show_key)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tvdb_network_year ON tvdb_show_metadata(original_network,show_year)")

        # v1.1.38 people metadata. Credits are deliberately stored separately from
        # the media rows because a show/episode/movie can have many actors and
        # directors.  library_id refers to libraries.id for local rows and
        # plex_libraries.id for Plex rows.
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS people_credits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL CHECK(source_type IN ('local','plex')),
            library_id INTEGER NOT NULL,
            media_type TEXT NOT NULL CHECK(media_type IN ('show','episode','movie')),
            media_key TEXT NOT NULL,
            show_key TEXT,
            show_title TEXT,
            person_name TEXT NOT NULL,
            person_name_norm TEXT NOT NULL,
            credit_type TEXT NOT NULL CHECK(credit_type IN ('actor','director')),
            character_name TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(source_type,library_id,media_type,media_key,person_name_norm,credit_type,character_name)
        );
        CREATE INDEX IF NOT EXISTS idx_people_name ON people_credits(person_name_norm,credit_type);
        CREATE INDEX IF NOT EXISTS idx_people_show ON people_credits(source_type,library_id,show_key,credit_type,person_name_norm);
        CREATE INDEX IF NOT EXISTS idx_people_media ON people_credits(source_type,library_id,media_type,media_key,credit_type,person_name_norm);
        CREATE INDEX IF NOT EXISTS idx_people_person_detail ON people_credits(person_name_norm,source_type,library_id,media_type,media_key,credit_type);
        CREATE INDEX IF NOT EXISTS idx_people_person_show ON people_credits(person_name_norm,credit_type,source_type,library_id,show_key,media_type);
        CREATE TABLE IF NOT EXISTS channel_people_filters(
            channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
            actors_json TEXT NOT NULL DEFAULT '[]',
            directors_json TEXT NOT NULL DEFAULT '[]',
            air_year_start INTEGER,
            air_year_end INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        # v1.1.16 used Plex's broad 'studio' value as a network fallback. That
        # can contain production companies and polluted the Channel Builder.
        # v1.1.17 moves canonical station data to TheTVDB, so clear that one-time
        # cache while preserving manual overrides and future dedicated network data.
        if conn.execute("SELECT 1 FROM settings WHERE key='v1117_cleared_plex_station_cache'").fetchone() is None:
            conn.execute("UPDATE plex_media SET original_network=NULL")
            conn.execute("INSERT INTO settings(key,value) VALUES('v1117_cleared_plex_station_cache','1')")

        # Every old v0.1 channel becomes "entire local library" so it behaves exactly as before.
        old_channels = conn.execute("SELECT id,library_id FROM channels WHERE library_id IS NOT NULL").fetchall()
        for c in old_channels:
            if conn.execute("SELECT 1 FROM channel_selections WHERE channel_id=? LIMIT 1", (c["id"],)).fetchone() is None:
                conn.execute(
                    """INSERT INTO channel_selections(channel_id,source_type,library_id,selection_type,created_at)
                       VALUES(?,?,?,?,?)""",
                    (c["id"], "local", c["library_id"], "library", utcnow_iso()),
                )
        conn.commit()

    backfill_local_metadata()


def sqlite_backup_to(directory: Path) -> Path | None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = directory / f"vipertv-{stamp}.db"
        src = db()
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
        return dest
    except Exception as exc:
        print(f"backup failed for {directory}: {exc}", flush=True)
        return None


def prune_backups(directory: Path) -> None:
    try:
        files = sorted(directory.glob("vipertv-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[BACKUP_KEEP:]:
            old.unlink(missing_ok=True)
    except Exception as exc:
        print(f"backup prune failed for {directory}: {exc}", flush=True)


def backup_all(reason: str = "scheduled") -> dict[str, Any]:
    ensure_dirs()
    result: dict[str, Any] = {"reason": reason, "primary": None, "secondary": None}
    p = sqlite_backup_to(BACKUP_DIR)
    if p:
        result["primary"] = str(p)
        prune_backups(BACKUP_DIR)
    if p and SECONDARY_BACKUP_DIR.exists() and os.access(SECONDARY_BACKUP_DIR, os.W_OK):
        # Do not run a second full SQLite backup against the live database.
        # Copy the already-consistent primary snapshot to disk 2 instead. This
        # cuts the live DB work in half on large catalogs.
        try:
            p2 = SECONDARY_BACKUP_DIR / p.name
            shutil.copy2(p, p2)
            result["secondary"] = str(p2)
            prune_backups(SECONDARY_BACKUP_DIR)
        except Exception as exc:
            print(f"secondary backup copy failed: {exc}", flush=True)
    print(f"backup: {result}", flush=True)
    return result


def safe_backup_before_change() -> None:
    if DB_PATH.exists() and DB_PATH.stat().st_size > 0:
        backup_all("before-change")


def probe_duration(path: str) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return 0.0
        return max(0.0, float((result.stdout or "0").strip()))
    except Exception:
        return 0.0


def clean_title(value: str) -> str:
    value = value.replace("_", " ").replace(".", " ")
    value = re.sub(r"\s+", " ", value).strip(" -_")
    return value


def parse_local_tv(root: Path, path: Path) -> tuple[str | None, int | None, int | None, str]:
    """Best-effort show/season/episode metadata from normal TV folder/file naming."""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parents = list(rel.parts[:-1])
    stem = path.stem

    season: int | None = None
    episode: int | None = None
    episode_title = clean_title(stem)

    for pattern in EPISODE_PATTERNS:
        m = pattern.search(stem)
        if m:
            season = int(m.group(1))
            episode = int(m.group(2))
            trailing = m.group(3) if m.lastindex and m.lastindex >= 3 else None
            if trailing:
                episode_title = clean_title(trailing)
            else:
                # Drop the episode marker from the filename for a cleaner subtitle.
                episode_title = clean_title(stem[m.end(2):]) or clean_title(stem)
            break

    season_dir_index: int | None = None
    for idx in range(len(parents) - 1, -1, -1):
        part = parents[idx]
        for pattern in SEASON_PATTERNS:
            m = pattern.match(part.strip())
            if m:
                season_dir_index = idx
                if season is None:
                    season = int(m.group(1))
                break
        if season_dir_index is not None:
            break

    show: str | None = None
    if season_dir_index is not None and season_dir_index > 0:
        show = clean_title(parents[season_dir_index - 1])
    elif parents:
        show = clean_title(parents[-1] if len(parents) == 1 else parents[0])

    # If there's no useful folder structure, derive show name from "Show Name S01E02".
    if (not show or show.lower() in {"season", "tv", "shows"}) and episode is not None:
        marker = re.search(r"(?i)\bS\d{1,2}\s*E\d{1,3}|\b\d{1,2}x\d{1,3}", stem)
        if marker:
            show = clean_title(stem[:marker.start()]) or show

    return show, season, episode, episode_title


def local_show_nfo_metadata(root: Path, path: Path, cache: dict[str, tuple[str | None, int | None]]) -> tuple[str | None, int | None]:
    """Read show-level network/premiere year from the nearest tvshow.nfo.

    Kodi/Plex NFO files commonly use <studio> for the TV network/studio and
    <premiered> for the show premiere date. Directory results are cached so a
    large season does not repeatedly touch the same NFO file.
    """
    seen_dirs: list[Path] = []
    cur = path.parent
    try:
        root_resolved = root.resolve()
    except Exception:
        root_resolved = root
    result: tuple[str | None, int | None] = (None, None)
    while True:
        key = str(cur)
        if key in cache:
            result = cache[key]
            break
        seen_dirs.append(cur)
        nfo = cur / "tvshow.nfo"
        if nfo.exists():
            try:
                nroot = ElementTree.parse(nfo).getroot()
                network = _xml_text(nroot, "studio", "network")
                premiered = _xml_text(nroot, "premiered", "aired")
                year_text = _xml_text(nroot, "year")
                show_year = None
                if premiered and re.match(r"^\d{4}", premiered):
                    show_year = int(premiered[:4])
                elif year_text and year_text.isdigit():
                    show_year = int(year_text)
                result = (network or None, show_year)
            except Exception:
                result = (None, None)
            break
        if cur == root_resolved or cur.parent == cur:
            break
        try:
            if root_resolved not in cur.parents and cur != root_resolved:
                break
        except Exception:
            pass
        cur = cur.parent
    for d in seen_dirs:
        cache[str(d)] = result
    return result


def _nfo_people(root: ElementTree.Element) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    seen: set[tuple[str,str,str]] = set()
    for actor in root.findall('.//actor'):
        name = _xml_text(actor, 'name') or str(actor.attrib.get('name') or actor.attrib.get('tag') or '').strip()
        role = _xml_text(actor, 'role') or str(actor.attrib.get('role') or '').strip()
        norm = _person_norm(name)
        if not norm:
            continue
        marker=('actor',norm,(role or '').casefold())
        if marker not in seen:
            seen.add(marker); out.append({'name':name,'credit_type':'actor','character_name':role or None})
    for director in root.findall('.//director'):
        name = (director.text or director.attrib.get('name') or director.attrib.get('tag') or '').strip()
        norm = _person_norm(name)
        if not norm:
            continue
        marker=('director',norm,'')
        if marker not in seen:
            seen.add(marker); out.append({'name':name,'credit_type':'director','character_name':None})
    return out


def _local_nearest_tvshow_nfo(root: Path, media_path: Path, cache: dict[str, Path | None]) -> Path | None:
    cur = media_path.parent
    try:
        root_resolved = root.resolve()
    except Exception:
        root_resolved = root
    visited: list[Path] = []
    found: Path | None = None
    while True:
        key = str(cur)
        if key in cache:
            found = cache[key]
            break
        visited.append(cur)
        candidate = cur / 'tvshow.nfo'
        if candidate.exists():
            found = candidate
            break
        if cur == root_resolved or cur.parent == cur:
            break
        try:
            if root_resolved not in cur.parents and cur != root_resolved:
                break
        except Exception:
            pass
        cur = cur.parent
    for d in visited:
        cache[str(d)] = found
    return found


def refresh_local_people_metadata(conn: sqlite3.Connection, library_id: int, root: Path) -> dict[str,int]:
    """Rebuild actors/directors from tvshow.nfo and episode/movie sidecar NFOs.

    This runs as part of a normal local-library scan, so there is no separate
    metadata-provider dependency for local collections.
    """
    conn.execute("DELETE FROM people_credits WHERE source_type='local' AND library_id=?", (library_id,))
    rows = conn.execute("SELECT * FROM media WHERE library_id=? ORDER BY id", (library_id,)).fetchall()
    tvshow_cache: dict[str, Path | None] = {}
    parsed_show_nfos: set[tuple[str,str]] = set()
    credits = 0
    shows = 0
    items = 0
    for r in rows:
        p = Path(str(r['path']))
        show_title = str(r['show_title'] or '').strip()
        if show_title:
            show_nfo = _local_nearest_tvshow_nfo(root, p, tvshow_cache)
            marker = (show_title, str(show_nfo or ''))
            if show_nfo and marker not in parsed_show_nfos:
                parsed_show_nfos.add(marker)
                try:
                    nroot = ElementTree.parse(show_nfo).getroot()
                    found = _nfo_people(nroot)
                    credits += _insert_people_credits(conn,'local',library_id,'show',show_title,show_title,show_title,found)
                    if found:
                        shows += 1
                except Exception:
                    pass
        nfo = p.with_suffix('.nfo')
        if nfo.exists():
            try:
                nroot = ElementTree.parse(nfo).getroot()
                found = _nfo_people(nroot)
                media_type = 'episode' if show_title else 'movie'
                credits += _insert_people_credits(conn,'local',library_id,media_type,str(r['id']),show_title or None,show_title or None,found)
                if found:
                    items += 1
                aired = _xml_text(nroot,'aired','premiered','dateadded')
                y = _xml_text(nroot,'year')
                episode_year = int(aired[:4]) if aired and re.match(r'^\d{4}',aired) else (int(y) if y and y.isdigit() else None)
                if episode_year:
                    conn.execute("UPDATE media SET year=COALESCE(year,?) WHERE id=?", (episode_year,r['id']))
            except Exception:
                pass
    return {'credits':credits,'shows':shows,'items':items}


def backfill_local_metadata() -> None:
    """Populate TV hierarchy for an existing v0.1 index without re-running ffprobe."""
    try:
        with db() as conn:
            libs = {r["id"]: Path(r["path"]) for r in conn.execute("SELECT id,path FROM libraries")}
            rows = conn.execute(
                "SELECT id,library_id,path FROM media WHERE show_title IS NULL OR episode_title IS NULL"
            ).fetchall()
            if not rows:
                return
            for r in rows:
                root = libs.get(r["library_id"])
                if root is None:
                    continue
                show, season, episode, episode_title = parse_local_tv(root, Path(r["path"]))
                conn.execute(
                    "UPDATE media SET show_title=?,season_number=?,episode_number=?,episode_title=? WHERE id=?",
                    (show, season, episode, episode_title, r["id"]),
                )
            conn.commit()
            print(f"local metadata backfill: {len(rows)} indexed files", flush=True)
    except Exception as exc:
        print(f"local metadata backfill failed: {exc}", flush=True)


def scan_library(library_id: int) -> dict[str, Any]:
    with db() as conn:
        lib = conn.execute("SELECT * FROM libraries WHERE id=?", (library_id,)).fetchone()
        if not lib:
            raise ValueError("Library not found")
        root = Path(lib["path"])
        if not root.exists():
            return {"library": lib["name"], "error": f"Path does not exist: {root}", "found": 0, "updated": 0, "removed": 0}

        existing = {
            row["path"]: row
            for row in conn.execute("SELECT * FROM media WHERE library_id=?", (library_id,)).fetchall()
        }
        seen: set[str] = set()
        found = updated = 0
        show_nfo_cache: dict[str, tuple[str | None, int | None]] = {}

        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                p = Path(dirpath) / filename
                if p.suffix.lower() not in VIDEO_EXTS:
                    continue
                try:
                    stat = p.stat()
                except OSError:
                    continue
                full = str(p)
                seen.add(full)
                found += 1
                row = existing.get(full)
                if row and row["size"] == stat.st_size and abs(row["mtime"] - stat.st_mtime) < 0.01:
                    # Ensure hierarchy is present even when ffprobe can be skipped.
                    if (not row["show_title"] or not row["episode_title"] or
                            not row["original_network"] or not row["show_year"]):
                        show, season, episode, episode_title = parse_local_tv(root, p)
                        network, show_year = local_show_nfo_metadata(root, p, show_nfo_cache)
                        conn.execute(
                            """UPDATE media SET show_title=?,season_number=?,episode_number=?,episode_title=?,
                               original_network=COALESCE(?,original_network),show_year=COALESCE(?,show_year) WHERE id=?""",
                            (show, season, episode, episode_title, network, show_year, row["id"]),
                        )
                    continue
                duration = probe_duration(full)
                title = clean_title(p.stem)
                show, season, episode, episode_title = parse_local_tv(root, p)
                network, show_year = local_show_nfo_metadata(root, p, show_nfo_cache)
                conn.execute(
                    """
                    INSERT INTO media(library_id,path,title,duration,size,mtime,updated_at,show_title,season_number,episode_number,episode_title,original_network,show_year)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(path) DO UPDATE SET
                        library_id=excluded.library_id,
                        title=excluded.title,
                        duration=excluded.duration,
                        size=excluded.size,
                        mtime=excluded.mtime,
                        updated_at=excluded.updated_at,
                        show_title=excluded.show_title,
                        season_number=excluded.season_number,
                        episode_number=excluded.episode_number,
                        episode_title=excluded.episode_title,
                        original_network=COALESCE(excluded.original_network,media.original_network),
                        show_year=COALESCE(excluded.show_year,media.show_year)
                    """,
                    (library_id, full, title, duration, stat.st_size, stat.st_mtime, utcnow_iso(), show, season, episode, episode_title, network, show_year),
                )
                updated += 1
                if found % 250 == 0:
                    conn.commit()

        removed = 0
        for path in set(existing) - seen:
            conn.execute("DELETE FROM media WHERE path=?", (path,))
            removed += 1
        people_stats = refresh_local_people_metadata(conn, library_id, root)
        conn.commit()
        return {"library": lib["name"], "found": found, "updated": updated, "removed": removed,
                "people_credits": people_stats.get("credits",0), "people_shows": people_stats.get("shows",0)}


def scan_all() -> list[dict[str, Any]]:
    with db() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM libraries WHERE enabled=1 ORDER BY id").fetchall()]
    results: list[dict[str, Any]] = []
    for library_id in ids:
        try:
            results.append(scan_library(library_id))
        except Exception as exc:
            results.append({"library_id": library_id, "error": str(exc)})
    return results


# ------------------------------ Plex integration ------------------------------

def plex_server_row(server_id: int) -> sqlite3.Row:
    with db() as conn:
        row = conn.execute("SELECT * FROM plex_servers WHERE id=? AND enabled=1", (server_id,)).fetchone()
    if not row:
        raise ValueError("Plex server not found")
    return row


def plex_request_json(server: sqlite3.Row | dict[str, Any], path: str, params: dict[str, Any] | None = None,
                      extra_headers: dict[str, str] | None = None, timeout: int = 30) -> dict[str, Any]:
    base = str(server["base_url"]).rstrip("/")
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = base + (path if path.startswith("/") else "/" + path)
    if query:
        url += ("&" if "?" in url else "?") + query
    headers = {
        "X-Plex-Token": str(server["token"]),
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": APP_VERSION,
        "X-Plex-Client-Identifier": "vipertv-server",
        "Accept": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = URLRequest(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read().decode(errors="ignore")[:800]
        raise RuntimeError(f"Plex HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Plex at {base}: {exc.reason}") from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        # Some PMS endpoints still return XML even when JSON is requested.
        try:
            root = ElementTree.fromstring(raw)
        except Exception as exc:
            raise RuntimeError(f"Plex returned an unreadable response ({content_type})") from exc
        return xml_element_to_dict(root)


def plex_request_xml(server: sqlite3.Row | dict[str, Any], path: str, params: dict[str, Any] | None = None,
                     extra_headers: dict[str, str] | None = None, timeout: int = 30) -> ElementTree.Element:
    """Fetch a Plex endpoint as raw XML.

    Plex's long-standing PMS library API exposes some show attributes (notably
    ``network``) more consistently in the XML representation than in some JSON
    projections.  Keep this as a compatibility path rather than depending on a
    single PMS serialization shape.
    """
    base = str(server["base_url"]).rstrip("/")
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    url = base + (path if path.startswith("/") else "/" + path)
    if query:
        url += ("&" if "?" in url else "?") + query
    headers = {
        "X-Plex-Token": str(server["token"]),
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": APP_VERSION,
        "X-Plex-Client-Identifier": "vipertv-server",
        "Accept": "application/xml",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = URLRequest(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        body = exc.read().decode(errors="ignore")[:800]
        raise RuntimeError(f"Plex HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Plex at {base}: {exc.reason}") from exc
    try:
        return ElementTree.fromstring(raw)
    except Exception as exc:
        raise RuntimeError("Plex returned unreadable XML") from exc


def _plex_xml_show_info(el: ElementTree.Element) -> dict[str, Any]:
    # Plex TV metadata is inconsistent across server/agent generations. Older
    # PMS builds may expose ``network=`` directly, newer metadata providers may
    # return <Network tag=...>, and many legacy/current libraries expose the
    # broadcaster in the TV show's ``studio`` field. Plex's NFO documentation
    # explicitly defines TV-show <studio> as network or studio, so studio is a
    # valid compatibility fallback when the dedicated network value is absent.
    network = str(el.attrib.get("network") or el.attrib.get("originalNetwork") or "").strip()
    network_source = "network" if network else ""
    if not network:
        tags: list[str] = []
        for child in list(el):
            if str(child.tag).lower() == "network":
                tag = str(child.attrib.get("tag") or "").strip()
                if tag:
                    tags.append(tag)
        if tags:
            network = " / ".join(dict.fromkeys(tags))
            network_source = "Network"
    year = safe_int(el.attrib.get("year"))
    if not year:
        dt = str(el.attrib.get("originallyAvailableAt") or "")
        year = int(dt[:4]) if re.match(r"^\d{4}", dt) else None
    return {
        "rating_key": str(el.attrib.get("ratingKey") or ""),
        "title": str(el.attrib.get("title") or ""),
        "network": network or None,
        "network_source": network_source or None,
        "year": year,
        "people": _plex_people_from_element(el),
    }


def plex_fetch_show_metadata_xml(server: sqlite3.Row | dict[str, Any], section_key: str) -> list[dict[str, Any]]:
    """Fetch TV-show metadata from PMS XML, including the legacy network attribute."""
    start = 0
    size = max(50, PLEX_SYNC_PAGE_SIZE)
    out: list[dict[str, Any]] = []
    while True:
        headers = {"X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(size)}
        root = plex_request_xml(server, f"/library/sections/{section_key}/all", {"type": 2}, headers, timeout=60)
        children = [x for x in list(root) if x.tag in ("Directory", "Video", "Metadata")]
        for child in children:
            info = _plex_xml_show_info(child)
            if info["rating_key"] or info["title"]:
                out.append(info)
        total = safe_int(root.attrib.get("totalSize")) or safe_int(root.attrib.get("size")) or len(children)
        if not children or len(out) >= total or len(children) < size:
            break
        start += len(children)
    return out


def xml_element_to_dict(root: ElementTree.Element) -> dict[str, Any]:
    def convert(el: ElementTree.Element) -> dict[str, Any]:
        out: dict[str, Any] = dict(el.attrib)
        grouped: dict[str, list[Any]] = {}
        for child in list(el):
            grouped.setdefault(child.tag, []).append(convert(child))
        for tag, items in grouped.items():
            out[tag] = items
        return out
    if root.tag == "MediaContainer":
        return {"MediaContainer": convert(root)}
    return {root.tag: convert(root)}


def plex_media_container(data: dict[str, Any]) -> dict[str, Any]:
    mc = data.get("MediaContainer")
    return mc if isinstance(mc, dict) else {}


def plex_list_value(mc: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = mc.get(key, [])
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def test_plex_connection_data(base_url: str, token: str) -> dict[str, str]:
    temp = {"base_url": base_url.rstrip("/"), "token": token}
    # Root contains friendlyName; identity is a smaller fallback.
    try:
        data = plex_request_json(temp, "/", timeout=15)
        mc = plex_media_container(data)
    except Exception:
        data = plex_request_json(temp, "/identity", timeout=15)
        mc = plex_media_container(data)
    return {
        "name": str(mc.get("friendlyName") or mc.get("machineIdentifier") or "Plex Media Server"),
        "machine_identifier": str(mc.get("machineIdentifier") or ""),
        "version": str(mc.get("version") or ""),
    }


def discover_plex_libraries(server_id: int) -> dict[str, Any]:
    server = plex_server_row(server_id)
    try:
        data = plex_request_json(server, "/library/sections")
        dirs = plex_list_value(plex_media_container(data), "Directory")
        if not dirs:
            data = plex_request_json(server, "/library/sections/all")
            dirs = plex_list_value(plex_media_container(data), "Directory")
    except Exception:
        data = plex_request_json(server, "/library/sections/all")
        dirs = plex_list_value(plex_media_container(data), "Directory")

    imported = 0
    with db() as conn:
        for d in dirs:
            section_key = str(d.get("key") or "")
            title = str(d.get("title") or f"Library {section_key}")
            lib_type = str(d.get("type") or "unknown")
            if not section_key:
                continue
            conn.execute(
                """
                INSERT INTO plex_libraries(server_id,section_key,title,library_type,uuid)
                VALUES(?,?,?,?,?)
                ON CONFLICT(server_id,section_key) DO UPDATE SET
                    title=excluded.title, library_type=excluded.library_type, uuid=excluded.uuid
                """,
                (server_id, section_key, title, lib_type, d.get("uuid")),
            )
            imported += 1
        conn.commit()
    return {"server": server["name"], "libraries": imported}


def plex_fetch_all(server: sqlite3.Row, path: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    start = 0
    size = max(50, PLEX_SYNC_PAGE_SIZE)
    out: list[dict[str, Any]] = []
    while True:
        headers = {"X-Plex-Container-Start": str(start), "X-Plex-Container-Size": str(size)}
        data = plex_request_json(server, path, params=params, extra_headers=headers, timeout=60)
        mc = plex_media_container(data)
        batch = plex_list_value(mc, "Metadata")
        out.extend(batch)
        total = int(mc.get("totalSize") or mc.get("size") or len(batch) or 0)
        if not batch or len(out) >= total or len(batch) < size:
            break
        start += len(batch)
    return out


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except Exception:
        return None


def safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def _plex_show_network(item: dict[str, Any]) -> str | None:
    """Extract the Plex TV broadcaster/network with compatibility fallbacks.

    PMS/agent combinations expose this as ``network``, a ``Network`` tag array,
    or (very commonly for classic TV) the show-level ``studio`` value. Plex's
    TV NFO documentation defines studio as network or studio, so using it only
    when dedicated network metadata is absent mirrors what Plex itself imports.
    """
    for key in ("network", "originalNetwork"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("Network", "networkTags"):
        value = item.get(key)
        if isinstance(value, list):
            tags = []
            for entry in value:
                if isinstance(entry, dict) and str(entry.get("tag") or "").strip():
                    tags.append(str(entry.get("tag")).strip())
                elif isinstance(entry, str) and entry.strip():
                    tags.append(entry.strip())
            if tags:
                return " / ".join(dict.fromkeys(tags))
        elif isinstance(value, dict) and str(value.get("tag") or "").strip():
            return str(value.get("tag")).strip()
    # Do NOT treat Plex's generic studio value as the originating network. It
    # frequently contains production companies (Paramount Television, Warner
    # Bros., etc.). TheTVDB enrichment supplies canonical originalNetwork data.
    return None


def _metadata_year(item: dict[str, Any]) -> int | None:
    y = safe_int(item.get("year"))
    if y:
        return y
    dt = str(item.get("originallyAvailableAt") or "")
    return int(dt[:4]) if re.match(r"^\d{4}", dt) else None


def _person_norm(value: str | None) -> str:
    text = (value or '').casefold().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _plex_people_from_mapping(item: dict[str, Any]) -> list[dict[str, str | None]]:
    """Extract actor/director credits from Plex's JSON-or-XML-dict shape.

    PMS commonly exposes actors as ``Role`` children and directors as
    ``Director`` children. Some metadata agents use ``Actor`` instead of
    ``Role``; accept both without making the caller care about PMS version.
    """
    out: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str]] = set()
    for keys, credit_type in ((('Role','Actor','role','actors'),'actor'), (('Director','director','directors'),'director')):
        values: list[Any] = []
        for key in keys:
            raw = item.get(key)
            if isinstance(raw, list):
                values.extend(raw)
            elif isinstance(raw, dict):
                values.append(raw)
            elif isinstance(raw, str) and raw.strip():
                values.append(raw)
        for entry in values:
            name = ''
            character = ''
            if isinstance(entry, dict):
                name = str(entry.get('tag') or entry.get('name') or entry.get('title') or '').strip()
                if credit_type == 'actor':
                    character = str(entry.get('role') or entry.get('character') or '').strip()
            else:
                name = str(entry).strip()
            norm = _person_norm(name)
            if not norm:
                continue
            marker = (credit_type, norm, character.casefold())
            if marker in seen:
                continue
            seen.add(marker)
            out.append({'name': name, 'credit_type': credit_type, 'character_name': character or None})
    return out


def _plex_people_from_element(el: ElementTree.Element) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str]] = set()
    for child in list(el):
        tag = str(child.tag).casefold()
        if tag not in {'role','actor','director'}:
            continue
        credit_type = 'director' if tag == 'director' else 'actor'
        name = str(child.attrib.get('tag') or child.attrib.get('name') or '').strip()
        character = str(child.attrib.get('role') or child.attrib.get('character') or '').strip() if credit_type == 'actor' else ''
        norm = _person_norm(name)
        if not norm:
            continue
        marker = (credit_type, norm, character.casefold())
        if marker in seen:
            continue
        seen.add(marker)
        out.append({'name': name, 'credit_type': credit_type, 'character_name': character or None})
    return out


def _merge_people(*groups: list[dict[str, str | None]] | None) -> list[dict[str, str | None]]:
    out: list[dict[str, str | None]] = []
    seen: set[tuple[str, str, str]] = set()
    for group in groups:
        for x in group or []:
            name = str(x.get('name') or '').strip()
            credit_type = str(x.get('credit_type') or '').strip()
            character = str(x.get('character_name') or '').strip()
            norm = _person_norm(name)
            if not norm or credit_type not in {'actor','director'}:
                continue
            marker = (credit_type, norm, character.casefold())
            if marker in seen:
                continue
            seen.add(marker)
            out.append({'name': name, 'credit_type': credit_type, 'character_name': character or None})
    return out


def _insert_people_credits(conn: sqlite3.Connection, source_type: str, library_id: int, media_type: str,
                           media_key: str, show_key: str | None, show_title: str | None,
                           credits: list[dict[str, str | None]]) -> int:
    count = 0
    for x in credits:
        name = str(x.get('name') or '').strip()
        norm = _person_norm(name)
        credit_type = str(x.get('credit_type') or '').strip()
        if not norm or credit_type not in {'actor','director'}:
            continue
        conn.execute(
            """INSERT OR IGNORE INTO people_credits(
                source_type,library_id,media_type,media_key,show_key,show_title,person_name,person_name_norm,credit_type,character_name,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (source_type,int(library_id),media_type,str(media_key),show_key,show_title,name,norm,credit_type,x.get('character_name'),utcnow_iso())
        )
        count += 1
    return count


def _normalise_title(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()


def _plex_external_id(item: dict[str, Any], provider: str) -> str | None:
    """Extract a Plex Guid such as tvdb://77811 or imdb://tt0106004."""
    provider = provider.casefold().strip()
    values: list[str] = []
    direct = item.get("guid")
    if isinstance(direct, str):
        values.append(direct)
    for key in ("Guid", "guid", "guids"):
        raw = item.get(key)
        if isinstance(raw, dict):
            raw = [raw]
        if isinstance(raw, list):
            for x in raw:
                if isinstance(x, dict):
                    v = x.get("id") or x.get("guid")
                    if v:
                        values.append(str(v))
                elif isinstance(x, str):
                    values.append(x)
    patterns = [
        re.compile(rf"{re.escape(provider)}://([^?&/]+)", re.I),
        re.compile(rf"com\\.plexapp\\.agents\\.{re.escape(provider)}://([^?&/]+)", re.I),
    ]
    for value in values:
        for pat in patterns:
            m = pat.search(value)
            if m:
                return m.group(1)
    return None


def tvdb_configured() -> bool:
    return bool((get_setting("tvdb_api_key") or "").strip())


def _tvdb_login(force: bool = False) -> str:
    api_key = (get_setting("tvdb_api_key") or "").strip()
    pin = (get_setting("tvdb_pin") or "").strip()
    if not api_key:
        raise RuntimeError("TheTVDB API key is not configured")
    cached = (get_setting("tvdb_token") or "").strip()
    acquired = _parse_iso_datetime(get_setting("tvdb_token_at"))
    if not force and cached and acquired and datetime.now(timezone.utc) - acquired < timedelta(days=25):
        return cached
    payload: dict[str, str] = {"apikey": api_key}
    if pin:
        payload["pin"] = pin
    raw = json.dumps(payload).encode("utf-8")
    req = URLRequest(
        TVDB_API_BASE + "/login",
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"},
    )
    try:
        with urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode(errors="ignore")[:800]
        raise RuntimeError(f"TheTVDB login HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach TheTVDB: {exc.reason}") from exc
    token = str((data.get("data") or {}).get("token") or "").strip()
    if not token:
        raise RuntimeError("TheTVDB login succeeded but no bearer token was returned")
    set_setting("tvdb_token", token)
    set_setting("tvdb_token_at", utcnow_iso())
    return token


def tvdb_request_json(path: str, params: dict[str, Any] | None = None, *, retry_auth: bool = True, timeout: int = 30) -> dict[str, Any]:
    token = _tvdb_login(False)
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None and v != ""})
    url = TVDB_API_BASE + (path if path.startswith("/") else "/" + path)
    if query:
        url += "?" + query
    req = URLRequest(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401 and retry_auth:
            _tvdb_login(True)
            return tvdb_request_json(path, params, retry_auth=False, timeout=timeout)
        if exc.code == 429:
            wait = 2
            try:
                wait = min(30, max(1, int(exc.headers.get("Retry-After") or "2")))
            except Exception:
                pass
            time.sleep(wait)
            if retry_auth:
                return tvdb_request_json(path, params, retry_auth=False, timeout=timeout)
        body = exc.read().decode(errors="ignore")[:800]
        raise RuntimeError(f"TheTVDB HTTP {exc.code}: {body or exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach TheTVDB: {exc.reason}") from exc


def test_tvdb_connection() -> dict[str, Any]:
    token = _tvdb_login(True)
    return {"ok": True, "token_length": len(token)}


def _tvdb_series_search(title: str, year: int | None = None) -> tuple[int | None, str | None, str]:
    """Conservative fallback matching when Plex/local metadata has no TVDB id."""
    def search(use_year: bool) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"query": title, "type": "series", "limit": 20}
        if use_year and year:
            params["year"] = year
        data = tvdb_request_json("/search", params)
        raw = data.get("data") or []
        return [x for x in raw if isinstance(x, dict)]

    candidates = search(True)
    if not candidates and year:
        candidates = search(False)
    want = _normalise_title(title)
    ranked: list[tuple[int, dict[str, Any]]] = []
    for item in candidates:
        names = [str(item.get("title") or "")]
        aliases = item.get("aliases") or []
        if isinstance(aliases, list):
            names.extend(str(x) for x in aliases if isinstance(x, str))
        exact = any(_normalise_title(x) == want for x in names if x)
        if not exact:
            continue
        iy = safe_int(item.get("year"))
        score = 100
        if year and iy == year:
            score += 50
        elif year and iy and abs(iy - year) <= 1:
            score += 10
        tvdb_id = safe_int(item.get("tvdb_id") or item.get("id") or item.get("objectID"))
        if tvdb_id:
            ranked.append((score, item))
    if not ranked:
        return None, None, "no-exact-match"
    ranked.sort(key=lambda x: x[0], reverse=True)
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        return None, None, "ambiguous-title"
    best = ranked[0][1]
    return safe_int(best.get("tvdb_id") or best.get("id") or best.get("objectID")), str(best.get("title") or title), "title/year"


def _tvdb_series_metadata(tvdb_id: int) -> dict[str, Any]:
    data = tvdb_request_json(f"/series/{int(tvdb_id)}/extended", {"short": "true"})
    series = data.get("data") or {}
    if not isinstance(series, dict):
        raise RuntimeError("TheTVDB returned invalid series metadata")
    original = series.get("originalNetwork")
    network = ""
    if isinstance(original, dict):
        network = str(original.get("name") or "").strip()
    elif isinstance(original, str):
        network = original.strip()
    year = safe_int(series.get("year"))
    if not year:
        first_aired = str(series.get("firstAired") or "")
        year = int(first_aired[:4]) if re.match(r"^\d{4}", first_aired) else None
    genres: list[str] = []
    for g in series.get("genres") or []:
        if isinstance(g, dict) and str(g.get("name") or "").strip():
            genres.append(str(g.get("name")).strip())
        elif isinstance(g, str) and g.strip():
            genres.append(g.strip())
    status = series.get("status")
    status_name = str(status.get("name") or "").strip() if isinstance(status, dict) else str(status or "").strip()
    return {
        "tvdb_id": int(tvdb_id),
        "title": str(series.get("name") or "").strip(),
        "original_network": network or None,
        "show_year": year,
        "genres": genres,
        "status": status_name or None,
    }


def _tvdb_enrichment_candidates() -> list[dict[str, Any]]:
    """Build one candidate per local/Plex TV show and include Plex TVDB GUIDs."""
    out: list[dict[str, Any]] = []
    # Local shows can be matched conservatively by title/year. NFO parsing can be
    # extended later with provider IDs without changing the TVDB cache schema.
    with db() as conn:
        local = conn.execute("""SELECT m.library_id,l.name AS library_name,m.show_title AS show_title,MAX(m.show_year) AS show_year
            FROM media m JOIN libraries l ON l.id=m.library_id
            WHERE m.show_title IS NOT NULL AND m.show_title<>'' GROUP BY m.library_id,m.show_title""").fetchall()
        plex_libs = conn.execute("""SELECT pl.*,ps.base_url,ps.token,ps.name AS server_name
            FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
            WHERE pl.enabled=1 AND pl.library_type='show' AND ps.enabled=1 ORDER BY ps.name,pl.title""").fetchall()
    for r in local:
        out.append({"source_type":"local","library_id":int(r["library_id"]),"library_name":r["library_name"],"server_name":"","show_key":str(r["show_title"]),"show_title":str(r["show_title"]),"show_year":safe_int(r["show_year"]),"tvdb_id":None})
    for lib in plex_libs:
        try:
            shows = plex_fetch_all(lib, f"/library/sections/{lib['section_key']}/all", {"type":2,"includeGuids":1})
        except Exception as exc:
            print(f"TVDB: could not read Plex show IDs from {lib['title']}: {exc}", flush=True)
            continue
        for show in shows:
            rk = str(show.get("ratingKey") or "")
            title = str(show.get("title") or "").strip()
            if not rk or not title:
                continue
            tvdb_raw = _plex_external_id(show, "tvdb")
            tvdb_id = safe_int(tvdb_raw)
            out.append({"source_type":"plex","library_id":int(lib["id"]),"library_name":lib["title"],"server_name":lib["server_name"],"show_key":rk,"show_title":title,"show_year":_metadata_year(show),"tvdb_id":tvdb_id})
    return out


def enrich_tvdb_metadata(force: bool = False, prestarted: bool = False) -> dict[str, Any]:
    if TVDB_ENRICH_STATUS.get("running") and not prestarted:
        raise RuntimeError("TheTVDB enrichment is already running")
    if not tvdb_configured():
        raise RuntimeError("Configure a TheTVDB API key first")
    if not prestarted:
        TVDB_ENRICH_STATUS.update({
            "running": True, "stage": "Authenticating with TheTVDB", "done": 0, "total": 0,
            "current": "", "matched": 0, "failed": 0, "skipped": 0,
            "started_at": utcnow_iso(), "finished_at": None, "error": None, "force": bool(force)
        })
    else:
        TVDB_ENRICH_STATUS["stage"] = "Authenticating with TheTVDB"
    # Validate/refresh auth before building a potentially large work queue.
    _tvdb_login(False)
    TVDB_ENRICH_STATUS["stage"] = "Building TV show work list"
    candidates = _tvdb_enrichment_candidates()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=TVDB_REFRESH_DAYS)
    with db() as conn:
        existing = {(r["source_type"],int(r["library_id"]),str(r["show_key"])):r for r in conn.execute("SELECT * FROM tvdb_show_metadata")}
    work: list[dict[str, Any]] = []
    skipped = 0
    for c in candidates:
        old = existing.get((c["source_type"],c["library_id"],c["show_key"]))
        refreshed = _parse_iso_datetime(old["refreshed_at"]) if old and old["refreshed_at"] else None
        if not force and old and refreshed and refreshed >= cutoff and (old["original_network"] or old["show_year"]):
            skipped += 1
            continue
        if old and old["tvdb_id"] and not c.get("tvdb_id"):
            c["tvdb_id"] = int(old["tvdb_id"])
        work.append(c)

    TVDB_ENRICH_STATUS.update({
        "running": True, "stage": "Fetching TheTVDB metadata", "done": 0, "total": len(work),
        "current": "", "matched": 0, "failed": 0, "skipped": skipped,
        "started_at": TVDB_ENRICH_STATUS.get("started_at") or utcnow_iso(),
        "finished_at": None, "error": None, "force": bool(force),
        "candidates": len(candidates)
    })
    cache: dict[int, dict[str, Any]] = {}
    try:
        for idx,c in enumerate(work, start=1):
            TVDB_ENRICH_STATUS["current"] = f"{c['show_title']} — {c['library_name']}"
            TVDB_ENRICH_STATUS["stage"] = "Fetching TheTVDB metadata"
            tvdb_id = safe_int(c.get("tvdb_id"))
            matched_title = None
            method = "plex-guid" if tvdb_id and c["source_type"] == "plex" else "provider-id" if tvdb_id else ""
            last_error = None
            try:
                if not tvdb_id:
                    tvdb_id, matched_title, method = _tvdb_series_search(c["show_title"], safe_int(c.get("show_year")))
                if not tvdb_id:
                    raise RuntimeError(f"No unambiguous TheTVDB series match ({method})")
                meta = cache.get(tvdb_id)
                if meta is None:
                    meta = _tvdb_series_metadata(tvdb_id)
                    cache[tvdb_id] = meta
                    # Be polite to the provider on first-time bulk enrichment.
                    time.sleep(0.08)
                with db() as conn:
                    conn.execute("""INSERT INTO tvdb_show_metadata(source_type,library_id,show_key,show_title,tvdb_id,original_network,show_year,genres_json,series_status,match_method,matched_title,refreshed_at,last_error)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)
                        ON CONFLICT(source_type,library_id,show_key) DO UPDATE SET show_title=excluded.show_title,tvdb_id=excluded.tvdb_id,
                        original_network=excluded.original_network,show_year=excluded.show_year,genres_json=excluded.genres_json,series_status=excluded.series_status,
                        match_method=excluded.match_method,matched_title=excluded.matched_title,refreshed_at=excluded.refreshed_at,last_error=NULL""",
                        (c["source_type"],c["library_id"],c["show_key"],c["show_title"],tvdb_id,meta.get("original_network"),meta.get("show_year"),json.dumps(meta.get("genres") or []),meta.get("status"),method,matched_title or meta.get("title"),utcnow_iso()))
                    conn.commit()
                TVDB_ENRICH_STATUS["matched"] = int(TVDB_ENRICH_STATUS.get("matched") or 0) + 1
            except Exception as exc:
                last_error = str(exc)[:700]
                with db() as conn:
                    conn.execute("""INSERT INTO tvdb_show_metadata(source_type,library_id,show_key,show_title,tvdb_id,match_method,refreshed_at,last_error)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_type,library_id,show_key) DO UPDATE SET show_title=excluded.show_title,
                        tvdb_id=COALESCE(excluded.tvdb_id,tvdb_show_metadata.tvdb_id),match_method=excluded.match_method,refreshed_at=excluded.refreshed_at,last_error=excluded.last_error""",
                        (c["source_type"],c["library_id"],c["show_key"],c["show_title"],tvdb_id,method or "unmatched",utcnow_iso(),last_error))
                    conn.commit()
                TVDB_ENRICH_STATUS["failed"] = int(TVDB_ENRICH_STATUS.get("failed") or 0) + 1
                print(f"TVDB metadata match failed: {c['show_title']!r} ({c['library_name']}): {last_error}", flush=True)
            TVDB_ENRICH_STATUS["done"] = idx
        result={"candidates":len(candidates),"processed":len(work),"matched":int(TVDB_ENRICH_STATUS.get("matched") or 0),"failed":int(TVDB_ENRICH_STATUS.get("failed") or 0),"skipped":skipped}
        set_setting("tvdb_last_enrich_at", utcnow_iso())
        set_setting("tvdb_last_enrich_result", json.dumps(result))
        TVDB_ENRICH_STATUS.update({"running":False,"stage":"Complete","finished_at":utcnow_iso(),"current":"","result":result})
        print(f"TheTVDB enrichment complete: {result}", flush=True)
        return result
    except Exception as exc:
        TVDB_ENRICH_STATUS.update({"running":False,"stage":"Failed","finished_at":utcnow_iso(),"error":str(exc)[:1000]})
        raise


def _plex_full_metadata_items(server: sqlite3.Row | dict[str, Any], rating_keys: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch complete Plex metadata objects for several rating keys at once.

    Plex library listings are partial objects and often omit Role/Director
    children. PMS supports comma-separated metadata keys, so ViperTV can import
    exact episode credits without one HTTP request per episode.
    """
    clean=[str(x).strip() for x in rating_keys if str(x).strip()]
    if not clean:
        return {}
    out: dict[str, dict[str, Any]]={}
    path='/library/metadata/'+','.join(quote(x,safe='') for x in clean)
    try:
        data=plex_request_json(server,path,{"includeGuids":1},timeout=60)
        for item in plex_list_value(plex_media_container(data),'Metadata'):
            rk=str(item.get('ratingKey') or '').strip()
            if rk:
                out[rk]=item
    except Exception:
        pass

    # Some older PMS versions don't return every item in a multi-key request.
    # Only missing records fall back to single-item detail requests.
    for rk in [x for x in clean if x not in out]:
        try:
            data=plex_request_json(server,f"/library/metadata/{quote(rk,safe='')}",{"includeGuids":1},timeout=30)
            items=plex_list_value(plex_media_container(data),'Metadata')
            if items:
                out[rk]=items[0]
                continue
        except Exception:
            pass
        try:
            root=plex_request_xml(server,f"/library/metadata/{quote(rk,safe='')}",{"includeGuids":1},timeout=30)
            candidates=[x for x in list(root) if x.tag in ('Video','Directory','Metadata')]
            if candidates:
                el=candidates[0]
                mapped=dict(el.attrib)
                grouped: dict[str,list[Any]]={}
                for child in list(el):
                    grouped.setdefault(child.tag,[]).append(dict(child.attrib))
                mapped.update(grouped)
                out[rk]=mapped
        except Exception:
            pass
    return out


def enrich_plex_episode_credits(plex_library_id: int, force: bool=False) -> dict[str, Any]:
    """Import exact episode actors/directors from full Plex metadata."""
    with db() as conn:
        lib=conn.execute("""SELECT pl.*,ps.base_url,ps.token,ps.name AS server_name
                            FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
                            WHERE pl.id=? AND pl.enabled=1""",(plex_library_id,)).fetchone()
        if not lib:
            raise ValueError('Plex library not found')
        if str(lib['library_type'])!='show':
            raise ValueError('Rich episode credits are only available for Plex TV libraries')
        base="""SELECT rating_key,title,show_title,season_number,episode_number,plex_updated_at
                FROM plex_media WHERE plex_library_id=? AND media_type='episode'"""
        if not force:
            base += """ AND (rich_people_at IS NULL OR rich_people_plex_updated_at IS NULL
                              OR COALESCE(rich_people_plex_updated_at,-1)<>COALESCE(plex_updated_at,-1))"""
        base += " ORDER BY show_title COLLATE NOCASE,season_number,episode_number"
        episodes=conn.execute(base,(plex_library_id,)).fetchall()

    status=PLEX_RICH_STATUS.setdefault(plex_library_id,{})
    status.update({"running":True,"library":lib['title'],"stage":"fetching full episode credits","done":0,"total":len(episodes),
                   "current":"","credits":0,"episodes_with_credits":0,"errors":0,"force":bool(force),
                   "started_at":utcnow_iso(),"finished_at":None,"error":None})
    if not episodes:
        result={"library":lib['title'],"episodes_checked":0,"episodes_with_credits":0,"credits":0,"skipped":"all episodes already current"}
        status.update({"running":False,"stage":"complete","finished_at":utcnow_iso(),"result":result})
        return result

    credits_total=0; eps_with=0; errors=0; done=0
    try:
        for pos in range(0,len(episodes),PLEX_RICH_EPISODE_BATCH_SIZE):
            batch=episodes[pos:pos+PLEX_RICH_EPISODE_BATCH_SIZE]
            keys=[str(r['rating_key']) for r in batch]
            first=batch[0]
            status['current']=f"{first['show_title'] or 'TV'} — {pos+1:,}-{min(pos+len(batch),len(episodes)):,} of {len(episodes):,}"
            detail=_plex_full_metadata_items(lib,keys)
            with db() as conn:
                for row in batch:
                    rk=str(row['rating_key'])
                    item=detail.get(rk)
                    if item is None:
                        errors+=1; done+=1
                        continue
                    people=_plex_people_from_mapping(item)
                    conn.execute("DELETE FROM people_credits WHERE source_type='plex' AND library_id=? AND media_type='episode' AND media_key=?",(plex_library_id,rk))
                    count=_insert_people_credits(conn,'plex',plex_library_id,'episode',rk,
                                                 str(item.get('grandparentRatingKey') or '') or None,
                                                 str(item.get('grandparentTitle') or row['show_title'] or '') or None,people)
                    credits_total+=count
                    if count:
                        eps_with+=1
                    conn.execute("""UPDATE plex_media SET rich_people_plex_updated_at=plex_updated_at,
                                    rich_people_at=?,rich_people_count=? WHERE plex_library_id=? AND rating_key=?""",
                                 (utcnow_iso(),count,plex_library_id,rk))
                    done+=1
                conn.commit()
            status.update({"done":done,"credits":credits_total,"episodes_with_credits":eps_with,"errors":errors})
        result={"library":lib['title'],"episodes_checked":done,"episodes_with_credits":eps_with,"credits":credits_total,"errors":errors}
        status.update({"running":False,"stage":"complete","finished_at":utcnow_iso(),"result":result})
        return result
    except Exception as exc:
        status.update({"running":False,"stage":"failed","finished_at":utcnow_iso(),"error":str(exc)[:1000],"done":done,"errors":errors+1})
        raise


def sync_plex_library(plex_library_id: int) -> dict[str, Any]:
    with db() as conn:
        lib = conn.execute(
            """SELECT pl.*, ps.base_url,ps.token,ps.name AS server_name
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.id=? AND pl.enabled=1""",
            (plex_library_id,),
        ).fetchone()
    if not lib:
        raise ValueError("Plex library not found")

    status = PLEX_SYNC_STATUS.setdefault(plex_library_id, {})
    status.update({"running": True, "library": lib["title"], "stage": "contacting Plex", "done": 0, "total": 0, "error": None})
    try:
        server = lib
        lib_type = str(lib["library_type"])
        show_metadata_by_key: dict[str, dict[str, Any]] = {}
        show_metadata_by_title: dict[str, dict[str, Any]] = {}
        if lib_type == "show":
            # PMS has used two different network shapes over time: a legacy
            # `network="NBC"` attribute on the show object, and a newer optional
            # Network child array.  Read the ordinary JSON response first, then
            # merge a raw XML pass because the legacy attribute is especially
            # reliable there (and is what mature Plex clients such as PlexAPI use).
            status["stage"] = "downloading show network/year metadata"
            shows = plex_fetch_all(
                server,
                f"/library/sections/{lib['section_key']}/all",
                {"type": 2, "includeGuids": 1},
            )
            for show in shows:
                info = {
                    "network": _plex_show_network(show),
                    "year": _metadata_year(show),
                    "title": str(show.get("title") or ""),
                    "people": _plex_people_from_mapping(show),
                }
                rk = str(show.get("ratingKey") or "")
                if rk:
                    show_metadata_by_key[rk] = info
                if info["title"]:
                    show_metadata_by_title[info["title"].casefold()] = info

            # Bulk XML pass: this catches the long-standing `network=` attribute
            # even when PMS's JSON projection omits it.
            status["stage"] = "reading Plex station/network metadata"
            try:
                xml_shows = plex_fetch_show_metadata_xml(server, str(lib["section_key"]))
                status["xml_shows_found"] = len(xml_shows)
                for xshow in xml_shows:
                    rk = str(xshow.get("rating_key") or "")
                    title = str(xshow.get("title") or "")
                    current = show_metadata_by_key.get(rk, {}) if rk else show_metadata_by_title.get(title.casefold(), {})
                    info = {
                        "network": xshow.get("network") or current.get("network"),
                        "year": xshow.get("year") or current.get("year"),
                        "title": title or str(current.get("title") or ""),
                        "people": _merge_people(current.get("people"), xshow.get("people")),
                    }
                    if rk:
                        show_metadata_by_key[rk] = info
                    if info["title"]:
                        show_metadata_by_title[info["title"].casefold()] = info
            except Exception as exc:
                # Keep syncing episodes even if a PMS build refuses the XML
                # representation. Individual-show XML below gets another chance.
                status["xml_warning"] = str(exc)[:500]
                print(f"Plex bulk XML network lookup failed for {lib['title']}: {exc}", flush=True)

            detail_missing = [
                show for show in shows
                if (lambda info: (not info.get("network")) or (not info.get("people")))(
                    show_metadata_by_key.get(str(show.get("ratingKey") or ""), {})
                    or show_metadata_by_title.get(str(show.get("title") or "").casefold(), {})
                )
            ]

            # Last-resort per-show XML lookup. A normal metadata response also
            # carries Plex Role/Director children, so the same compatibility pass
            # fills both broadcaster metadata and the new people index.
            if detail_missing:
                status["stage"] = "resolving remaining show metadata / cast"
                status["network_total"] = len(detail_missing)
                status["network_done"] = 0
                for nidx, show in enumerate(detail_missing, start=1):
                    rk = str(show.get("ratingKey") or "")
                    if not rk:
                        status["network_done"] = nidx
                        continue
                    try:
                        root = plex_request_xml(server, f"/library/metadata/{quote(rk, safe='')}", timeout=30)
                        candidates = [x for x in list(root) if x.tag in ("Directory", "Video", "Metadata")]
                        if candidates:
                            xinfo = _plex_xml_show_info(candidates[0])
                            current = show_metadata_by_key.get(rk, {})
                            title = str(xinfo.get("title") or current.get("title") or show.get("title") or "")
                            info = {
                                "network": xinfo.get("network") or current.get("network"),
                                "year": xinfo.get("year") or current.get("year"),
                                "title": title,
                                "people": _merge_people(current.get("people"), xinfo.get("people")),
                            }
                            show_metadata_by_key[rk] = info
                            if title:
                                show_metadata_by_title[title.casefold()] = info
                    except Exception as exc:
                        print(f"Plex XML show metadata lookup failed for show {rk}: {exc}", flush=True)
                    status["network_done"] = nidx

            status["networks_found"] = sum(1 for x in show_metadata_by_key.values() if x.get("network"))
            status["people_shows_found"] = sum(1 for x in show_metadata_by_key.values() if x.get("people"))
            status["shows_found"] = len(show_metadata_by_key)
            sample_networks = sorted({str(x.get("network")) for x in show_metadata_by_key.values() if x.get("network")})[:12]
            raw_studios = sorted({str(x.get("studio")) for x in shows if str(x.get("studio") or "").strip()})[:12]
            print(
                f"Plex station metadata: library={lib['title']!r} shows={status['shows_found']} "
                f"networks={status['networks_found']} people_shows={status.get('people_shows_found',0)} xml_shows={status.get('xml_shows_found', 0)} "
                f"unresolved={sum(1 for x in show_metadata_by_key.values() if not x.get('network'))} "
                f"sample={sample_networks!r} plex_studio_sample={raw_studios!r}",
                flush=True,
            )
            status["stage"] = "downloading episode metadata"
            metadata = plex_fetch_all(server, f"/library/sections/{lib['section_key']}/all", {"type": 4})
            expected_type = "episode"
        elif lib_type == "movie":
            status["stage"] = "downloading movie metadata"
            metadata = plex_fetch_all(server, f"/library/sections/{lib['section_key']}/all", {"type": 1})
            expected_type = "movie"
        else:
            raise ValueError(f"ViperTV v0.2 supports Plex TV and Movie libraries; '{lib_type}' is not a video library")

        status["total"] = len(metadata)
        status["stage"] = "saving metadata / people credits"
        seen: set[str] = set()
        with db() as conn:
            # Keep previously enriched exact episode credits until a rich pass replaces
            # each new/changed episode. Show/movie rows are rebuilt every sync.
            conn.execute("DELETE FROM people_credits WHERE source_type='plex' AND library_id=? AND media_type IN ('show','movie')", (plex_library_id,))
            people_credit_count = 0
            if lib_type == "show":
                for rk, info in show_metadata_by_key.items():
                    people_credit_count += _insert_people_credits(
                        conn,'plex',plex_library_id,'show',rk,rk,str(info.get('title') or ''),list(info.get('people') or [])
                    )
            for idx, item in enumerate(metadata, start=1):
                rating_key = str(item.get("ratingKey") or "")
                plex_key = str(item.get("key") or (f"/library/metadata/{rating_key}" if rating_key else ""))
                if not rating_key or not plex_key:
                    continue
                seen.add(rating_key)
                media_type = str(item.get("type") or expected_type)
                duration = safe_float(item.get("duration")) / 1000.0
                show_rating_key = str(item.get("grandparentRatingKey") or "") or None
                show_title = str(item.get("grandparentTitle") or "") or None
                season_rating_key = str(item.get("parentRatingKey") or "") or None
                season_number = safe_int(item.get("parentIndex"))
                episode_number = safe_int(item.get("index"))
                show_network = None
                show_year = None
                if media_type == "movie":
                    show_rating_key = None
                    show_title = None
                    season_rating_key = None
                    season_number = None
                    episode_number = None
                else:
                    show_info = show_metadata_by_key.get(str(show_rating_key or "")) or show_metadata_by_title.get(str(show_title or "").casefold()) or {}
                    show_network = show_info.get("network")
                    show_year = show_info.get("year")
                conn.execute(
                    """
                    INSERT INTO plex_media(
                        plex_library_id,rating_key,plex_key,media_type,title,show_rating_key,show_title,
                        season_rating_key,season_number,episode_number,duration,summary,
                        originally_available_at,thumb,year,original_network,show_year,updated_at,plex_updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(plex_library_id,rating_key) DO UPDATE SET
                        plex_key=excluded.plex_key,media_type=excluded.media_type,title=excluded.title,
                        show_rating_key=excluded.show_rating_key,show_title=excluded.show_title,
                        season_rating_key=excluded.season_rating_key,season_number=excluded.season_number,
                        episode_number=excluded.episode_number,duration=excluded.duration,summary=excluded.summary,
                        originally_available_at=excluded.originally_available_at,thumb=excluded.thumb,
                        year=excluded.year,
                        original_network=COALESCE(excluded.original_network,plex_media.original_network),
                        show_year=COALESCE(excluded.show_year,plex_media.show_year),updated_at=excluded.updated_at,
                        plex_updated_at=excluded.plex_updated_at
                    """,
                    (
                        plex_library_id, rating_key, plex_key, media_type, str(item.get("title") or "Untitled"),
                        show_rating_key, show_title, season_rating_key, season_number, episode_number,
                        duration, item.get("summary"), item.get("originallyAvailableAt"), item.get("thumb"),
                        safe_int(item.get("year")), show_network, show_year, utcnow_iso(), safe_int(item.get("updatedAt")),
                    ),
                )
                people_credit_count += _insert_people_credits(
                    conn,'plex',plex_library_id,'movie' if media_type == 'movie' else 'episode',rating_key,
                    show_rating_key,show_title,_plex_people_from_mapping(item)
                )
                if idx % 250 == 0:
                    conn.commit()
                status["done"] = idx

            existing = conn.execute("SELECT rating_key FROM plex_media WHERE plex_library_id=?", (plex_library_id,)).fetchall()
            for r in existing:
                if r["rating_key"] not in seen:
                    conn.execute("DELETE FROM people_credits WHERE source_type='plex' AND library_id=? AND media_type='episode' AND media_key=?",(plex_library_id,r["rating_key"]))
                    conn.execute("DELETE FROM plex_media WHERE plex_library_id=? AND rating_key=?", (plex_library_id, r["rating_key"]))
            conn.execute(
                "UPDATE plex_libraries SET last_synced_at=?,item_count=? WHERE id=?",
                (utcnow_iso(), len(seen), plex_library_id),
            )
            conn.commit()
        result = {"library": lib["title"], "items": len(seen), "people_credits": int(people_credit_count)}
        if lib_type == "show":
            result["shows"] = int(status.get("shows_found") or 0)
            result["networks"] = int(status.get("networks_found") or 0)
            result["shows_with_people"] = int(status.get("people_shows_found") or 0)
            if PLEX_RICH_EPISODE_CREDITS:
                status["stage"] = "importing exact episode cast/directors"
                try:
                    rich=enrich_plex_episode_credits(plex_library_id,False)
                    result["rich_episode_credits"] = rich
                except Exception as exc:
                    result["rich_episode_credits_error"] = str(exc)[:700]
                    print(f"Plex rich episode credit import failed for {lib['title']}: {exc}",flush=True)
        status.update({"running": False, "stage": "complete", "done": len(seen), "total": len(seen), "result": result})
        return result
    except Exception as exc:
        status.update({"running": False, "stage": "failed", "error": str(exc)})
        print(f"Plex sync {plex_library_id} failed: {exc}", flush=True)
        raise



def sync_all_plex_libraries() -> dict[str, Any]:
    """Synchronize every discovered Plex TV/movie library sequentially.

    Sequential processing deliberately avoids hammering Plex and the NAS with many
    simultaneous metadata requests while still giving one-click administration.
    Individual library progress continues to be exposed through PLEX_SYNC_STATUS.
    """
    with db() as conn:
        libraries = conn.execute(
            """SELECT pl.id,pl.title,pl.library_type,ps.name AS server_name
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1 AND pl.library_type IN ('show','movie')
               ORDER BY ps.name,pl.title"""
        ).fetchall()

    PLEX_SYNC_ALL_STATUS.update({
        "running": True,
        "done": 0,
        "total": len(libraries),
        "current": "",
        "results": [],
        "started_at": utcnow_iso(),
        "finished_at": None,
    })
    results: list[dict[str, Any]] = []
    try:
        for idx, lib in enumerate(libraries, start=1):
            label = f"{lib['server_name']} / {lib['title']}"
            PLEX_SYNC_ALL_STATUS["current"] = label
            existing = PLEX_SYNC_STATUS.get(lib["id"], {})
            if existing.get("running"):
                result = {"library": label, "ok": False, "error": "already syncing"}
            else:
                try:
                    r = sync_plex_library(int(lib["id"]))
                    result = {"library": label, "ok": True, "items": int(r.get("items", 0)),
                              "shows": int(r.get("shows", 0)), "networks": int(r.get("networks", 0))}
                except Exception as exc:
                    result = {"library": label, "ok": False, "error": str(exc)}
            results.append(result)
            PLEX_SYNC_ALL_STATUS["results"] = list(results)
            PLEX_SYNC_ALL_STATUS["done"] = idx
        return {"libraries": len(libraries), "results": results}
    finally:
        PLEX_SYNC_ALL_STATUS.update({
            "running": False,
            "current": "",
            "finished_at": utcnow_iso(),
            "results": list(results),
        })

def plex_transcode_url(item: dict[str, Any], offset: float) -> str:
    with db() as conn:
        server = conn.execute(
            """SELECT ps.* FROM plex_servers ps
               JOIN plex_libraries pl ON pl.server_id=ps.id
               WHERE pl.id=?""",
            (item["plex_library_id"],),
        ).fetchone()
    if not server:
        raise RuntimeError("Plex server for media item no longer exists")

    params: dict[str, Any] = {
        "path": item["plex_key"],
        "mediaIndex": 0,
        "partIndex": 0,
        "protocol": "hls",
        "fastSeek": 1,
        "copyts": 1,
        "offset": max(0, int(offset)),
        "maxVideoBitrate": max(64, PLEX_MAX_VIDEO_BITRATE),
        "X-Plex-Platform": "Chrome",
        "X-Plex-Product": APP_NAME,
        "X-Plex-Version": APP_VERSION,
        "X-Plex-Client-Identifier": "vipertv-server",
        "session": str(uuid.uuid4()),
        "directPlay": 0,
        "directStream": 1,
        "skipSubtitles": 1,
    }
    if PLEX_VIDEO_RESOLUTION and re.match(r"^\d+x\d+$", PLEX_VIDEO_RESOLUTION):
        params["videoResolution"] = PLEX_VIDEO_RESOLUTION
    params["X-Plex-Token"] = server["token"]
    return str(server["base_url"]).rstrip("/") + "/video/:/transcode/universal/start.m3u8?" + urlencode(params)


# --------------------------- channel catalog / picker --------------------------

def encode_selection(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_selection(token: str) -> dict[str, Any]:
    padding = "=" * (-len(token) % 4)
    raw = base64.urlsafe_b64decode((token + padding).encode("ascii"))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid selection")
    return data


def channel_selection_payloads(channel_id: int) -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM channel_selections WHERE channel_id=? ORDER BY id", (channel_id,)).fetchall()
    return [dict(r) for r in rows]


def save_channel_selections(channel_id: int, selection_tokens: list[str]) -> int:
    decoded: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    for token in selection_tokens:
        if not token or token in seen_tokens:
            continue
        seen_tokens.add(token)
        decoded.append(decode_selection(token))

    # If an entire show was selected, drop redundant individual season selections for that same show.
    all_show_keys = {
        (d.get("source_type"), d.get("library_id"), d.get("plex_library_id"), str(d.get("show_key")))
        for d in decoded if d.get("selection_type") == "show"
    }
    cleaned: list[dict[str, Any]] = []
    for d in decoded:
        key = (d.get("source_type"), d.get("library_id"), d.get("plex_library_id"), str(d.get("show_key")))
        if d.get("selection_type") == "season" and key in all_show_keys:
            continue
        cleaned.append(d)

    # The create/save route already takes one pre-change snapshot. Avoid a
    # second full-database backup for the same click; that was making channel
    # creation look frozen on large libraries.
    with db() as conn:
        if not conn.execute("SELECT 1 FROM channels WHERE id=?", (channel_id,)).fetchone():
            raise ValueError("Channel not found")
        conn.execute("DELETE FROM channel_selections WHERE channel_id=?", (channel_id,))
        for d in cleaned:
            source_type = str(d.get("source_type"))
            selection_type = str(d.get("selection_type"))
            if source_type not in {"local", "plex"} or selection_type not in {"library", "show", "season", "movie"}:
                continue
            conn.execute(
                """INSERT INTO channel_selections(
                    channel_id,source_type,library_id,plex_library_id,selection_type,show_key,show_title,season_number,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    channel_id, source_type, safe_int(d.get("library_id")), safe_int(d.get("plex_library_id")),
                    selection_type, d.get("show_key"), d.get("show_title"), safe_int(d.get("season_number")), utcnow_iso(),
                ),
            )
        conn.execute("UPDATE channels SET library_id=NULL WHERE id=?", (channel_id,))
        conn.commit()
    return len(cleaned)


def local_picker_catalog() -> list[dict[str, Any]]:
    with db() as conn:
        libs = conn.execute("SELECT id,name,path FROM libraries ORDER BY name COLLATE NOCASE").fetchall()
        output: list[dict[str, Any]] = []
        for lib in libs:
            rows = conn.execute(
                """SELECT COALESCE(NULLIF(show_title,''),'(Unclassified)') AS show_title,
                          season_number, COUNT(*) AS item_count
                   FROM media WHERE library_id=?
                   GROUP BY COALESCE(NULLIF(show_title,''),'(Unclassified)'),season_number
                   ORDER BY show_title COLLATE NOCASE,season_number""",
                (lib["id"],),
            ).fetchall()
            shows: dict[str, dict[str, Any]] = {}
            for r in rows:
                show = shows.setdefault(r["show_title"], {"title": r["show_title"], "seasons": [], "count": 0})
                show["count"] += r["item_count"]
                show["seasons"].append({"number": r["season_number"], "count": r["item_count"]})
            output.append({"id": lib["id"], "name": lib["name"], "path": lib["path"], "shows": list(shows.values())})
        return output


def plex_picker_catalog() -> list[dict[str, Any]]:
    with db() as conn:
        libs = conn.execute(
            """SELECT pl.*,ps.name AS server_name FROM plex_libraries pl
               JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1
               ORDER BY ps.name,pl.title"""
        ).fetchall()
        output: list[dict[str, Any]] = []
        for lib in libs:
            if lib["library_type"] == "show":
                rows = conn.execute(
                    """SELECT show_rating_key,COALESCE(show_title,'(Unknown Show)') AS show_title,
                              season_number,COUNT(*) AS item_count
                       FROM plex_media WHERE plex_library_id=? AND media_type='episode'
                       GROUP BY show_rating_key,show_title,season_number
                       ORDER BY show_title COLLATE NOCASE,season_number""",
                    (lib["id"],),
                ).fetchall()
                shows: dict[str, dict[str, Any]] = {}
                for r in rows:
                    key = r["show_rating_key"] or r["show_title"]
                    show = shows.setdefault(str(key), {"key": str(key), "title": r["show_title"], "seasons": [], "count": 0})
                    show["count"] += r["item_count"]
                    show["seasons"].append({"number": r["season_number"], "count": r["item_count"]})
                output.append({
                    "id": lib["id"], "server_name": lib["server_name"], "title": lib["title"],
                    "type": "show", "shows": list(shows.values()), "count": lib["item_count"],
                })
            elif lib["library_type"] == "movie":
                movies = conn.execute(
                    "SELECT rating_key,title,year FROM plex_media WHERE plex_library_id=? AND media_type='movie' ORDER BY title COLLATE NOCASE",
                    (lib["id"],),
                ).fetchall()
                output.append({
                    "id": lib["id"], "server_name": lib["server_name"], "title": lib["title"],
                    "type": "movie", "movies": [dict(m) for m in movies], "count": lib["item_count"],
                })
        return output


def selection_key_from_row(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("source_type"), row.get("library_id"), row.get("plex_library_id"),
        row.get("selection_type"), str(row.get("show_key") or ""), row.get("season_number"),
    )


def selected_keys(channel_id: int | None) -> set[tuple[Any, ...]]:
    if channel_id is None:
        return set()
    return {selection_key_from_row(r) for r in channel_selection_payloads(channel_id)}


def channel_media(channel_id: int) -> tuple[sqlite3.Row, list[dict[str, Any]]]:
    with db() as conn:
        channel = conn.execute("SELECT * FROM channels WHERE id=? AND enabled=1", (channel_id,)).fetchone()
        if not channel:
            raise HTTPException(404, "Channel not found")
        selections = conn.execute("SELECT * FROM channel_selections WHERE channel_id=? ORDER BY id", (channel_id,)).fetchall()
        items: list[dict[str, Any]] = []
        # Attach source-library metadata to each playable item.  This is useful
        # to the EPG (and other read-only UIs) without changing channel
        # selection or playback semantics.
        local_library_names = {int(r["id"]): str(r["name"] or "") for r in conn.execute("SELECT id,name FROM libraries")}
        plex_library_info = {int(r["id"]): (str(r["title"] or ""), str(r["library_type"] or "")) for r in conn.execute("SELECT id,title,library_type FROM plex_libraries")}

        for s in selections:
            if s["source_type"] == "local":
                params: list[Any] = []
                where = ["duration>0"]
                if s["library_id"] is not None:
                    where.append("library_id=?")
                    params.append(s["library_id"])
                if s["selection_type"] in {"show", "season"}:
                    where.append("show_title=?")
                    params.append(s["show_title"] or s["show_key"])
                if s["selection_type"] == "season":
                    where.append("season_number IS ?")
                    params.append(s["season_number"])
                rows = conn.execute(
                    "SELECT * FROM media WHERE " + " AND ".join(where), params
                ).fetchall()
                for r in rows:
                    items.append({
                        "source_type": "local", "uid": f"local:{r['id']}", "id": r["id"], "library_id": r["library_id"], "path": r["path"],
                        "title": r["title"], "duration": float(r["duration"]), "show_title": r["show_title"],
                        "season_number": r["season_number"], "episode_number": r["episode_number"],
                        "episode_title": r["episode_title"] or r["title"], "summary": r["summary"] if "summary" in r.keys() else None,
                        "air_date": None, "year": r["year"] if "year" in r.keys() else None, "plex_library_id": None, "plex_key": None,
                        "library_name": local_library_names.get(int(r["library_id"]), ""),
                        "media_type": "episode" if r["show_title"] else "movie",
                    })
            else:
                params = []
                where = ["duration>0"]
                if s["plex_library_id"] is not None:
                    where.append("plex_library_id=?")
                    params.append(s["plex_library_id"])
                if s["selection_type"] in {"show", "season"}:
                    where.append("show_rating_key=?")
                    params.append(s["show_key"])
                elif s["selection_type"] == "movie":
                    where.append("rating_key=?")
                    params.append(s["show_key"])
                if s["selection_type"] == "season":
                    where.append("season_number IS ?")
                    params.append(s["season_number"])
                rows = conn.execute(
                    "SELECT * FROM plex_media WHERE " + " AND ".join(where), params
                ).fetchall()
                for r in rows:
                    items.append({
                        "source_type": "plex", "uid": f"plex:{r['plex_library_id']}:{r['rating_key']}",
                        "id": r["id"], "rating_key": r["rating_key"], "show_rating_key": r["show_rating_key"],
                        "path": None, "title": r["title"], "duration": float(r["duration"]),
                        "show_title": r["show_title"], "season_number": r["season_number"],
                        "episode_number": r["episode_number"], "episode_title": r["title"],
                        "summary": r["summary"], "air_date": r["originally_available_at"], "year": r["year"],
                        "plex_library_id": r["plex_library_id"], "plex_key": r["plex_key"],
                        "library_name": plex_library_info.get(int(r["plex_library_id"]), ("", ""))[0],
                        "media_type": r["media_type"],
                    })

    # Deduplicate overlapping "all show" / season selections or repeated selections.
    unique: dict[str, dict[str, Any]] = {i["uid"]: i for i in items}
    items = list(unique.values())
    items.sort(key=lambda i: (
        (i.get("show_title") or i.get("title") or "").casefold(),
        i.get("season_number") if i.get("season_number") is not None else -1,
        i.get("episode_number") if i.get("episode_number") is not None else -1,
        (i.get("episode_title") or i.get("title") or "").casefold(),
        i["uid"],
    ))
    if channel["shuffle"]:
        items.sort(key=lambda i: hashlib.sha256(f"{channel_id}|{i['uid']}".encode()).digest())
    return channel, items


EPOCH = datetime(2020, 1, 1, tzinfo=timezone.utc)


def locate_at(items: list[dict[str, Any]], when: datetime) -> tuple[int, float, datetime]:
    if not items:
        raise HTTPException(503, "Channel has no playable media")
    total = sum(float(i["duration"]) for i in items)
    if total <= 0:
        raise HTTPException(503, "Channel media has no duration information")
    anchor=EPOCH
    try:
        raw=items[0].get('_cycle_anchor_utc') if isinstance(items[0],dict) else None
        if raw:
            anchor=datetime.fromisoformat(str(raw))
            if anchor.tzinfo is None:anchor=anchor.replace(tzinfo=timezone.utc)
    except Exception:anchor=EPOCH
    elapsed = (when - anchor).total_seconds()
    pos = elapsed % total
    cursor = 0.0
    for idx, item in enumerate(items):
        dur = float(item["duration"])
        if pos < cursor + dur:
            offset = pos - cursor
            start = when - timedelta(seconds=offset)
            return idx, offset, start
        cursor += dur
    return 0, 0.0, when


# ------------------------------------ UI -------------------------------------

def base_url(request: Request) -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def special_media_category(title: str) -> str | None:
    """Classify specially named libraries before generic TV/Movie grouping."""
    folded = (title or "").casefold()
    squashed = re.sub(r"\s+", "", folded)
    if "music videos" in folded:
        return "Music Videos"
    if "game shows" in folded:
        return "Game Shows"
    if "youtube" in squashed:
        return "YouTube"
    return None


def guide_media_class(item: dict[str, Any]) -> str:
    """Return the EPG colour class for one playable item.

    YouTube is identified by ViperTV's existing special-library naming rule.
    Everything explicitly marked as a movie is red, while episodic/show media
    is green.  Unknown local video defaults to movie rather than being
    mislabelled as TV.
    """
    if special_media_category(str(item.get("library_name") or "")) == "YouTube":
        return "youtube"
    media_type = str(item.get("media_type") or "").casefold()
    if media_type in {"episode", "show"} or item.get("show_title"):
        return "tv"
    if media_type == "movie":
        return "movie"
    return "movie"


SIDEBAR_MEDIA_COUNT_CACHE: dict[str, Any] = {"at": 0.0, "tv": 0, "movies": 0, "youtube": 0, "music_videos": 0, "game_shows": 0}


def sidebar_media_counts() -> dict[str, int]:
    """Return responsive sidebar totals for each Media catalog.

    TV is counted as show entries per library/source (not episodes). Movies,
    YouTube and Music Videos are counted as playable media items. Game Shows is
    counted as distinct show titles per library/source. Title-classified special
    libraries stay out of the ordinary TV/Movie totals. Results are cached for
    60 seconds so every page load does not aggregate a large catalog.
    """
    now = time.time()
    if now - float(SIDEBAR_MEDIA_COUNT_CACHE.get("at", 0.0)) < 60:
        return {k: int(SIDEBAR_MEDIA_COUNT_CACHE.get(k, 0)) for k in ("tv", "movies", "youtube", "music_videos", "game_shows")}
    try:
        with db() as conn:
            local_tv = conn.execute(
                """SELECT COUNT(*) c FROM (
                     SELECT l.id,m.show_title
                     FROM media m JOIN libraries l ON l.id=m.library_id
                     WHERE m.show_title IS NOT NULL AND m.show_title<>''
                       AND lower(replace(l.name,' ','')) NOT LIKE '%youtube%'
                       AND lower(l.name) NOT LIKE '%music videos%'
                       AND lower(l.name) NOT LIKE '%game shows%'
                     GROUP BY l.id,m.show_title
                   )"""
            ).fetchone()["c"]
            plex_tv = conn.execute(
                """SELECT COUNT(*) c FROM (
                     SELECT pl.id,pm.show_title
                     FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                     WHERE pm.media_type='episode' AND pm.show_title IS NOT NULL AND pm.show_title<>''
                       AND lower(replace(pl.title,' ','')) NOT LIKE '%youtube%'
                       AND lower(pl.title) NOT LIKE '%music videos%'
                       AND lower(pl.title) NOT LIKE '%game shows%'
                     GROUP BY pl.id,pm.show_title
                   )"""
            ).fetchone()["c"]
            movies = conn.execute(
                """SELECT COUNT(*) c
                     FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                     WHERE pm.media_type='movie'
                       AND lower(replace(pl.title,' ','')) NOT LIKE '%youtube%'
                       AND lower(pl.title) NOT LIKE '%music videos%'
                       AND lower(pl.title) NOT LIKE '%game shows%'"""
            ).fetchone()["c"]

            local_youtube = conn.execute(
                """SELECT COUNT(*) c FROM media m JOIN libraries l ON l.id=m.library_id
                     WHERE lower(replace(l.name,' ','')) LIKE '%youtube%'"""
            ).fetchone()["c"]
            plex_youtube = conn.execute(
                """SELECT COUNT(*) c FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                     WHERE pl.enabled=1 AND lower(replace(pl.title,' ','')) LIKE '%youtube%'"""
            ).fetchone()["c"]

            local_music = conn.execute(
                """SELECT COUNT(*) c FROM media m JOIN libraries l ON l.id=m.library_id
                     WHERE lower(l.name) LIKE '%music videos%'"""
            ).fetchone()["c"]
            plex_music = conn.execute(
                """SELECT COUNT(*) c FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                     WHERE pl.enabled=1 AND lower(pl.title) LIKE '%music videos%'"""
            ).fetchone()["c"]

            local_game = conn.execute(
                """SELECT COUNT(*) c FROM (
                     SELECT l.id,m.show_title
                     FROM media m JOIN libraries l ON l.id=m.library_id
                     WHERE lower(l.name) LIKE '%game shows%'
                       AND m.show_title IS NOT NULL AND m.show_title<>''
                     GROUP BY l.id,m.show_title
                   )"""
            ).fetchone()["c"]
            plex_game = conn.execute(
                """SELECT COUNT(*) c FROM (
                     SELECT pl.id,pm.show_title
                     FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                     WHERE pl.enabled=1 AND lower(pl.title) LIKE '%game shows%'
                       AND pm.media_type='episode' AND pm.show_title IS NOT NULL AND pm.show_title<>''
                     GROUP BY pl.id,pm.show_title
                   )"""
            ).fetchone()["c"]

        counts = {
            "tv": int(local_tv or 0) + int(plex_tv or 0),
            "movies": int(movies or 0),
            "youtube": int(local_youtube or 0) + int(plex_youtube or 0),
            "music_videos": int(local_music or 0) + int(plex_music or 0),
            "game_shows": int(local_game or 0) + int(plex_game or 0),
        }
        SIDEBAR_MEDIA_COUNT_CACHE.update({"at": now, **counts})
        return counts
    except Exception:
        return {k: int(SIDEBAR_MEDIA_COUNT_CACHE.get(k, 0)) for k in ("tv", "movies", "youtube", "music_videos", "game_shows")}


def page_shell(title: str, body: str, extra_head: str = "", extra_script: str = "") -> str:
    media_counts = sidebar_media_counts()
    tv_show_count = media_counts["tv"]
    movie_count = media_counts["movies"]
    youtube_count = media_counts["youtube"]
    music_video_count = media_counts["music_videos"]
    game_show_count = media_counts["game_shows"]
    try:
        with db() as _rc:
            retro_wanted_count = int(_rc.execute("SELECT COUNT(*) c FROM retro_wanted WHERE resolved=0").fetchone()["c"] or 0)
    except Exception:
        retro_wanted_count = 0
    # ViperTV 1.1 uses an ErsatzTV Legacy-inspired information architecture:
    # permanent grouped sidebar, compact top bar, dense data tables and green
    # primary actions.  This is an independent ViperTV implementation; only the
    # navigation/workflow familiarity is intentionally similar.
    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{e(title)} - {APP_NAME}</title>
<style>
:root{{--bg:#111418;--surface:#1a1f24;--surface2:#20262c;--surface3:#282f36;--sidebar:#171b20;--top:#1c2127;--text:#f0f1f2;--muted:#a6adb5;--accent:#52b788;--accent2:#40916c;--danger:#e05b63;--warn:#d6a84b;--line:#343b43;--link:#83c5ff;--shadow:0 2px 10px rgba(0,0,0,.22)}}
*{{box-sizing:border-box}}
html,body{{margin:0;min-height:100%;background:var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;font-size:14px}}
a{{color:var(--link);text-decoration:none}} a:hover{{text-decoration:underline}}
.app-shell{{min-height:100vh;display:flex}}
.sidebar{{position:fixed;inset:0 auto 0 0;width:252px;background:var(--sidebar);border-right:1px solid #2b3137;display:flex;flex-direction:column;z-index:50;overflow-y:auto}}
.brand{{height:64px;display:flex;align-items:center;gap:11px;padding:0 18px;border-bottom:1px solid #2b3137;position:sticky;top:0;background:var(--sidebar);z-index:2}}
.brand-mark{{width:34px;height:34px;border-radius:6px;background:var(--accent);display:grid;place-items:center;color:#0d1b14;font-size:20px;font-weight:900}}
.brand-name{{font-size:20px;font-weight:700;letter-spacing:.2px;color:#fff}} .brand-version{{font-size:10px;color:var(--muted);margin-left:2px}}
.side-scroll{{padding:12px 10px 22px}}
.nav-group{{margin:8px 0 16px}} .nav-label{{padding:7px 10px 5px;font-size:11px;font-weight:700;letter-spacing:.09em;color:#7f8993;text-transform:uppercase}}
.nav-item{{display:flex;align-items:center;gap:10px;padding:9px 11px;border-radius:4px;color:#cbd0d5;margin:1px 0;font-weight:500}}
.nav-item:hover{{background:#232a31;color:white;text-decoration:none}} .nav-item.active{{background:#2a333b;color:white;box-shadow:inset 3px 0 0 var(--accent)}}
.nav-icon{{width:19px;text-align:center;color:#99a3ad;font-size:15px}} .nav-item.active .nav-icon{{color:var(--accent)}} .nav-count{{margin-left:auto;min-width:28px;text-align:right;padding:2px 6px;border-radius:10px;background:#2b333b;color:#c7cdd3;font-size:10px;font-weight:700;font-variant-numeric:tabular-nums}} .nav-item.active .nav-count{{background:#173c2b;color:#8ee0b1}}
.main-area{{margin-left:252px;width:calc(100% - 252px);min-width:0}}
.topbar{{height:64px;background:var(--top);border-bottom:1px solid #313840;display:flex;align-items:center;justify-content:space-between;padding:0 24px;position:sticky;top:0;z-index:40;gap:18px}}
.page-title{{font-size:19px;font-weight:600;color:#f7f7f7;white-space:nowrap}} .top-actions{{display:flex;align-items:center;gap:8px}}
.top-link{{display:inline-flex;align-items:center;gap:6px;padding:7px 10px;border:1px solid #3a434c;border-radius:4px;color:#d9dde1;background:#242b32;font-size:12px;font-weight:600}} .top-link:hover{{background:#2c343c;text-decoration:none}}
.mobile-menu{{display:none;background:none;border:0;color:white;font-size:24px;padding:0}}
.content{{padding:22px 26px 60px;max-width:1600px;margin:0 auto}}
.page-heading{{display:flex;align-items:flex-start;justify-content:space-between;gap:18px;margin-bottom:18px}} .page-heading h1{{font-size:24px;margin:0 0 4px}} .page-heading p{{margin:0;color:var(--muted)}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:18px;margin-bottom:18px;box-shadow:var(--shadow)}}
.card h2{{font-size:18px;margin:0 0 14px;font-weight:600}} .card h3{{font-size:15px;margin:18px 0 10px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}} .grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
.stats{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin-bottom:18px}} .stat{{background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:16px}} .stat-value{{font-size:27px;font-weight:700;margin-top:4px}} .stat-label{{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}}
table{{width:100%;border-collapse:collapse;background:transparent}} th{{color:#b8c0c7;font-size:11px;text-transform:uppercase;letter-spacing:.05em;font-weight:700;background:#171c21}} td,th{{padding:10px 11px;border-bottom:1px solid #30373e;text-align:left;vertical-align:middle}} tr:last-child td{{border-bottom:0}} tbody tr:hover{{background:#20272d}}
.table-wrap{{overflow:auto;border:1px solid #30373e;border-radius:4px}} .table-wrap table{{margin:0}}
label{{display:block;color:#cbd1d6;font-weight:500;margin:3px 0 4px}} input,select,textarea{{width:100%;background:#14191e;color:var(--text);border:1px solid #3a434c;padding:9px 10px;border-radius:4px;margin:0 0 12px;outline:none}} input:focus,select:focus,textarea:focus{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(82,183,136,.12)}} input[type=checkbox],input[type=radio]{{width:auto;margin:0 7px 0 0;vertical-align:middle}}
button,.button{{appearance:none;background:var(--accent2);color:white;border:1px solid #4aa378;border-radius:4px;padding:8px 13px;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-block;line-height:1.2}} button:hover,.button:hover{{background:var(--accent);text-decoration:none}} button.secondary,.button.secondary{{background:#303841;border-color:#46515c;color:#f2f3f4}} button.secondary:hover,.button.secondary:hover{{background:#3a444e}} button.danger,.button.danger{{background:#a94149;border-color:#bd525b;color:#fff}} button.danger:hover,.button.danger:hover{{background:var(--danger)}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}} .inline{{display:inline-block}} form.inline{{margin:0}} form.inline input,form.inline select{{display:inline-block;width:auto;margin:0 6px 0 0}}
.muted{{color:var(--muted)}} .small{{font-size:12px}} .right{{text-align:right}} .nowrap{{white-space:nowrap}} code{{color:#b9e4ff;background:#11161b;padding:2px 5px;border-radius:3px;word-break:break-all}}
.msg{{background:#153426;border:1px solid #2f7653;color:#d7f6e5;padding:11px 13px;border-radius:4px;margin-bottom:16px}} .badge{{display:inline-block;padding:3px 7px;border-radius:3px;background:#173c2b;color:#8ee0b1;font-size:11px;font-weight:600}} .badge.blue{{background:#173147;color:#9bd2ff}} .badge.warn{{background:#4a3517;color:#ffd28f}}
.urls code{{display:block;padding:8px;background:#11161b;border:1px solid #2d353d;border-radius:4px;margin:6px 0}} details{{border:1px solid var(--line);border-radius:4px;padding:10px;margin:8px 0;background:#151a1f}} summary{{cursor:pointer;font-weight:600}}
.season{{display:inline-block;margin:5px 12px 5px 0}} .picker-show{{padding:9px 6px;border-top:1px solid #2d343b}} .picker-show:first-child{{border-top:0}} .progress{{height:8px;background:#0d1115;border-radius:99px;overflow:hidden}} .progress>span{{display:block;height:100%;background:var(--accent);transition:width .35s ease}} .progress.large{{height:14px}} .progress>span.indeterminate{{width:32%!important;animation:vip-progress 1.15s ease-in-out infinite}} @keyframes vip-progress{{0%{{transform:translateX(-120%)}}50%{{transform:translateX(120%)}}100%{{transform:translateX(330%)}}}}
.section-tabs{{display:flex;gap:0;border-bottom:1px solid var(--line);margin:0 0 18px}} .section-tabs a{{padding:9px 13px;color:#aab2ba;border-bottom:2px solid transparent}} .section-tabs a.active{{color:#fff;border-color:var(--accent)}}
.empty{{padding:32px;text-align:center;color:var(--muted)}} hr{{border:0;border-top:1px solid var(--line);margin:18px 0}}
@media(max-width:1100px){{.stats{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:850px){{.sidebar{{transform:translateX(-100%);transition:.2s}} body.sidebar-open .sidebar{{transform:translateX(0)}} .main-area{{margin-left:0;width:100%}} .mobile-menu{{display:block}} .topbar{{padding:0 14px}} .content{{padding:14px}} .grid,.grid3{{grid-template-columns:1fr}} .stats{{grid-template-columns:1fr 1fr}} .top-link span{{display:none}}}}
@media(max-width:520px){{.stats{{grid-template-columns:1fr}}}}
</style>{extra_head}</head><body>
<div class='app-shell'>
<aside class='sidebar' id='sidebar'>
  <div class='brand'><div class='brand-mark'>V</div><div><div class='brand-name'>ViperTV</div><div class='brand-version'>v{APP_VERSION}</div></div></div>
  <div class='side-scroll'>
    <div class='nav-group'><a class='nav-item' data-match='^/$' href='/'><span class='nav-icon'>⌂</span>Dashboard</a></div>
    <div class='nav-group'><div class='nav-label'>Media Sources</div>
      <a class='nav-item' data-match='^/media/local' href='/media/local'><span class='nav-icon'>▣</span>Local</a>
      <a class='nav-item' data-match='^/plex' href='/plex'><span class='nav-icon'>▶</span>Plex</a>
      <a class='nav-item' data-match='^/sources' href='/sources'><span class='nav-icon'>◆</span>Jellyfin / Emby</a>
      <a class='nav-item' data-match='^/pluto|^/watch/pluto' href='/pluto'><span class='nav-icon'>◉</span>Pluto TV</a>
      <a class='nav-item' data-match='^/live|^/watch/live|^/stream/live' href='/live'><span class='nav-icon'>◈</span>Live IPTV</a>
    </div>
    <div class='nav-group'><div class='nav-label'>Media</div>
      <a class='nav-item' data-match='^/media/libraries' href='/media/libraries'><span class='nav-icon'>▤</span>Libraries</a>
      <a class='nav-item' data-match='^/media/search' href='/media/search'><span class='nav-icon'>⌕</span>Search</a>
      <a class='nav-item' data-match='^/media/tv' href='/media/tv'><span class='nav-icon'>▦</span>TV Shows<span class='nav-count'>{tv_show_count:,}</span></a>
      <a class='nav-item' data-match='^/media/people' href='/media/people'><span class='nav-icon'>♟</span>People</a>
      <a class='nav-item' data-match='^/media/movies' href='/media/movies'><span class='nav-icon'>▰</span>Movies<span class='nav-count'>{movie_count:,}</span></a>
      <a class='nav-item' data-match='^/media/youtube' href='/media/youtube'><span class='nav-icon'>▶</span>YouTube<span class='nav-count'>{youtube_count:,}</span></a>
      <a class='nav-item' data-match='^/media/music-videos' href='/media/music-videos'><span class='nav-icon'>♫</span>Music Videos<span class='nav-count'>{music_video_count:,}</span></a>
      <a class='nav-item' data-match='^/media/images' href='/media/images'><span class='nav-icon'>▧</span>Images</a>
      <a class='nav-item' data-match='^/media/game-shows' href='/media/game-shows'><span class='nav-icon'>★</span>Game Shows<span class='nav-count'>{game_show_count:,}</span></a>
    </div>
    <div class='nav-group'><div class='nav-label'>Lists</div>
      <a class='nav-item' data-match='^/lists/collections|^/studio/collections' href='/lists/collections'><span class='nav-icon'>☷</span>Collections</a>
      <a class='nav-item' data-match='^/lists/smart' href='/lists/smart'><span class='nav-icon'>⌁</span>Smart Collections</a>
      <a class='nav-item' data-match='^/lists/multi' href='/lists/multi'><span class='nav-icon'>⊞</span>Multi Collections</a>
      <a class='nav-item' data-match='^/lists/playlists|^/studio/playlists' href='/lists/playlists'><span class='nav-icon'>☰</span>Playlists</a>
      <a class='nav-item' data-match='^/lists/filler' href='/lists/filler'><span class='nav-icon'>⋯</span>Filler</a>
    </div>
    <div class='nav-group'><div class='nav-label'>Scheduling</div>
      <a class='nav-item' data-match='^/channels$|^/channels/new|^/channels/[0-9]|^/watch/channel|^/studio/channel' href='/channels'><span class='nav-icon'>▥</span>Channels</a>
      <a class='nav-item' data-match='^/channels/ai' href='/channels/ai'><span class='nav-icon'>✧</span>AI Channel Builder</a>
      <a class='nav-item' data-match='^/channels/auto' href='/channels/auto'><span class='nav-icon'>✦</span>Channel Builder</a>
      <a class='nav-item' data-match='^/scheduling/schedules' href='/scheduling/schedules'><span class='nav-icon'>▧</span>Schedules</a>
      <a class='nav-item' data-match='^/scheduling/playouts' href='/scheduling/playouts'><span class='nav-icon'>▷</span>Playouts</a>
      <a class='nav-item' data-match='^/scheduling/blocks|^/scheduling/block-|^/scheduling/decos$' href='/scheduling/blocks'><span class='nav-icon'>▦</span>Blocks / Templates</a>
      <a class='nav-item' data-match='^/scheduling/deco-templates' href='/scheduling/deco-templates'><span class='nav-icon'>◇</span>Deco Templates</a>
      <a class='nav-item' data-match='^/scheduling/playout-templates' href='/scheduling/playout-templates'><span class='nav-icon'>▤</span>Playout Templates</a>
      <a class='nav-item' data-match='^/scheduling/marathons' href='/scheduling/marathons'><span class='nav-icon'>↻</span>Marathons</a>
      <a class='nav-item' data-match='^/scheduling/sequential' href='/scheduling/sequential'><span class='nav-icon'>≋</span>Sequential</a>
      <a class='nav-item' data-match='^/scheduling/scripted' href='/scheduling/scripted'><span class='nav-icon'>&lt;/&gt;</span>Scripted</a>
      <a class='nav-item' data-match='^/retro' href='/retro'><span class='nav-icon'>⌛</span>Retro TV<span class='nav-count'>{retro_wanted_count:,}</span></a>
    </div>
    <div class='nav-group'><div class='nav-label'>System</div>
      <a class='nav-item' data-match='^/system/streaming' href='/system/streaming'><span class='nav-icon'>⚙</span>Streaming Profiles</a>
      <a class='nav-item' data-match='^/system/ffmpeg-profiles' href='/system/ffmpeg-profiles'><span class='nav-icon'>◈</span>FFmpeg Profiles</a>
      <a class='nav-item' data-match='^/system/stream-selectors' href='/system/stream-selectors'><span class='nav-icon'>♫</span>Audio / Subtitles</a>
      <a class='nav-item' data-match='^/system/graphics' href='/system/graphics'><span class='nav-icon'>◆</span>Graphics & Branding</a>
      <a class='nav-item' data-match='^/system/hardware' href='/system/hardware'><span class='nav-icon'>▣</span>Hardware Acceleration</a>
      <a class='nav-item' data-match='^/system/metadata' href='/system/metadata'><span class='nav-icon'>◎</span>Metadata Providers</a>
      <a class='nav-item' data-match='^/guide' href='/guide'><span class='nav-icon'>▩</span>Guide</a>
      <a class='nav-item' data-match='^/maintenance' href='/maintenance'><span class='nav-icon'>⛁</span>Backup & Restore</a>
    </div>
  </div>
</aside>
<div class='main-area'>
  <header class='topbar'><div class='toolbar'><button class='mobile-menu' id='mobileMenu' type='button'>☰</button><div class='page-title'>{e(title)}</div></div>
    <div class='top-actions'><a class='top-link' href='/iptv/channels.m3u' title='M3U playlist'>☷ <span>M3U</span></a><a class='top-link' href='/iptv/xmltv.xml' title='XMLTV guide'>▦ <span>XMLTV</span></a></div>
  </header>
  <main class='content'>{body}</main>
</div></div>
<script>
(()=>{{
 const path=location.pathname;
 document.querySelectorAll('.nav-item[data-match]').forEach(a=>{{try{{if(new RegExp(a.dataset.match).test(path))a.classList.add('active')}}catch(e){{}}}});
 const b=document.getElementById('mobileMenu'); if(b)b.addEventListener('click',()=>document.body.classList.toggle('sidebar-open'));
 document.addEventListener('click',ev=>{{if(innerWidth<=850 && document.body.classList.contains('sidebar-open') && !ev.target.closest('.sidebar') && !ev.target.closest('#mobileMenu'))document.body.classList.remove('sidebar-open')}});
}})();
</script>{extra_script}</body></html>"""


def home_page(request: Request, message: str = "") -> str:
    with db() as conn:
        local_libs = conn.execute("SELECT COUNT(*) c FROM libraries WHERE enabled=1").fetchone()["c"]
        local_media = conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"]
        plex_libs = conn.execute("SELECT COUNT(*) c FROM plex_libraries WHERE enabled=1").fetchone()["c"]
        plex_media = conn.execute("SELECT COUNT(*) c FROM plex_media").fetchone()["c"]
        channels = conn.execute("SELECT * FROM channels ORDER BY CAST(number AS REAL),number").fetchall()
        backups = conn.execute("SELECT COUNT(*) c FROM channels WHERE enabled=1").fetchone()["c"]
    url = base_url(request)
    msg_html = f"<div class='msg'>{e(message)}</div>" if message else ""
    channel_rows = "".join(
        f"<tr><td><b>{e(c['number'])}</b></td><td>{e(c['name'])}</td><td>{'Enabled' if c['enabled'] else 'Disabled'}</td>"
        f"<td><span class='playable-count' data-channel='{c['id']}'>…</span></td><td class='nowrap'>"
        f"<a class='button secondary' href='/channels/{c['id']}/edit'>Edit</a> "
        f"<a class='button secondary' href='/studio/channel/{c['id']}'>Playout</a> "
        f"<a class='button' href='/watch/channel/{quote(str(c['number']),safe='')}'>Watch</a></td></tr>" for c in channels
    ) or "<tr><td colspan='5' class='empty'>No channels configured.</td></tr>"
    body = f"""
{msg_html}
<div class='page-heading'><div><h1>Dashboard</h1><p>Virtual television server status and quick access.</p></div><div class='toolbar'><a class='button' href='/channels/new'>Add Channel</a></div></div>
<div class='stats'>
  <div class='stat'><div class='stat-label'>Channels</div><div class='stat-value'>{len(channels)}</div><div class='muted small'>{backups} enabled</div></div>
  <div class='stat'><div class='stat-label'>Local Media</div><div class='stat-value'>{local_media:,}</div><div class='muted small'>{local_libs} libraries</div></div>
  <div class='stat'><div class='stat-label'>Plex Media</div><div class='stat-value'>{plex_media:,}</div><div class='muted small'>{plex_libs} libraries</div></div>
  <div class='stat'><div class='stat-label'>Database</div><div class='stat-value'>OK</div><div class='muted small'>{e(DB_PATH)}</div></div>
</div>
<div class='card'><div class='page-heading'><div><h2>Channels</h2><p>Active ViperTV channels and current playable media counts.</p></div><a class='button' href='/channels'>Manage Channels</a></div><div class='table-wrap'><table><thead><tr><th>#</th><th>Name</th><th>Status</th><th>Playable Items</th><th>Actions</th></tr></thead><tbody>{channel_rows}</tbody></table></div></div>
<div class='grid'>
 <div class='card urls'><h2>Client URLs</h2><p class='muted'>Use these in Kodi, Plex, Jellyfin, TiviMate or another IPTV client.</p><label>M3U Playlist</label><code>{e(url)}/iptv/channels.m3u</code><label>XMLTV Guide</label><code>{e(url)}/iptv/xmltv.xml</code></div>
 <div class='card'><h2>Quick Actions</h2><div class='toolbar'><a class='button secondary' href='/plex'>Plex Sources</a><a class='button secondary' href='/media/local'>Local Libraries</a><a class='button secondary' href='/guide'>Guide Preview</a><a class='button secondary' href='/maintenance'>Backup & Restore</a></div><hr><p class='muted small'>ViperTV data is persisted outside the container and backed up to both configured backup locations.</p></div>
</div>
"""
    count_script = r"""<script>(async()=>{for(const el of document.querySelectorAll('.playable-count')){try{const r=await fetch('/api/channels/'+el.dataset.channel+'/playable-count');const j=await r.json();el.textContent=(j.count??0).toLocaleString();}catch(e){el.textContent='?';}}})();</script>"""
    return page_shell("Dashboard", body, extra_script=count_script)


def plex_page(message: str = "") -> str:
    with db() as conn:
        servers = conn.execute("SELECT * FROM plex_servers ORDER BY name").fetchall()
        libraries = conn.execute(
            """SELECT pl.*,ps.name AS server_name,
                      (SELECT COUNT(DISTINCT NULLIF(pm.original_network,'')) FROM plex_media pm WHERE pm.plex_library_id=pl.id) AS network_count,
                      (SELECT COUNT(*) FROM plex_media pm WHERE pm.plex_library_id=pl.id AND pm.media_type='episode') AS episode_count,
                      (SELECT COUNT(*) FROM plex_media pm WHERE pm.plex_library_id=pl.id AND pm.media_type='episode' AND pm.rich_people_at IS NOT NULL) AS rich_episode_count
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1 ORDER BY ps.name,pl.title"""
        ).fetchall()
        removed_libraries = conn.execute(
            """SELECT pl.*,ps.name AS server_name FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=0 ORDER BY ps.name,pl.title"""
        ).fetchall()
    server_rows = ""
    for s in servers:
        masked = "••••" + (s["token"][-4:] if len(s["token"]) >= 4 else "")
        server_rows += (
            f"<tr><td>{e(s['name'])}</td><td><code>{e(s['base_url'])}</code></td><td>{e(masked)}</td><td>{e(s['product_version'] or '')}</td>"
            f"<td><form class='inline' method='post' action='/plex/servers/{s['id']}/test'><button class='secondary'>Test</button></form> "
            f"<form class='inline' method='post' action='/plex/servers/{s['id']}/discover'><button>Discover Libraries</button></form> "
            f"<form class='inline' method='post' action='/plex/servers/{s['id']}/delete' onsubmit=\"return confirm('Remove Plex server and its cached ViperTV metadata? This does not alter Plex.');\"><button class='danger'>Remove</button></form></td></tr>"
        )
    if not server_rows:
        server_rows = "<tr><td colspan='5' class='muted'>No Plex server connected yet.</td></tr>"

    library_rows = ""
    for l in libraries:
        status = PLEX_SYNC_STATUS.get(l["id"], {})
        rich_status = PLEX_RICH_STATUS.get(l["id"], {})
        state = "Syncing…" if status.get("running") else (l["last_synced_at"] or "Never")
        rich_state = (f"{int(l['rich_episode_count'] or 0):,}/{int(l['episode_count'] or 0):,}" if l['library_type']=='show' else '—')
        rich_button = (f"<form class='inline' method='post' action='/plex/libraries/{l['id']}/rich-credits'><button class='secondary'>{'Importing Rich Credits…' if rich_status.get('running') else 'Refresh Rich Credits'}</button></form> " if l['library_type']=='show' else '')
        library_rows += (
            f"<tr><td>{e(l['server_name'])}</td><td>{e(l['title'])}</td><td>{e(special_media_category(l['title']) or l['library_type'])}</td><td>{l['item_count']:,}</td><td>{int(l['network_count'] or 0) if l['library_type']=='show' else '—'}</td><td>{rich_state}</td><td>{e(state)}</td>"
            f"<td><form class='inline' method='post' action='/plex/libraries/{l['id']}/sync'><button>{'Syncing…' if status.get('running') else 'Sync Metadata'}</button></form> "
            f"{rich_button}<form class='inline' method='post' action='/plex/libraries/{l['id']}/remove' onsubmit=\"return confirm('Remove this library from ViperTV? Cached metadata and this library\'s channel selections will be removed. Nothing in Plex or your media files will be changed.');\"><button class='danger'>Remove</button></form></td></tr>"
        )
    if not library_rows:
        library_rows = "<tr><td colspan='8' class='muted'>Add a server, then click Discover Libraries.</td></tr>"

    removed_rows = ""
    for l in removed_libraries:
        removed_rows += (
            f"<tr><td>{e(l['server_name'])}</td><td>{e(l['title'])}</td><td>{e(special_media_category(l['title']) or l['library_type'])}</td>"
            f"<td><form method='post' action='/plex/libraries/{l['id']}/restore'><button class='secondary'>Restore</button></form></td></tr>"
        )
    removed_html = (
        f"<div class='card'><details><summary>Removed Plex Libraries ({len(removed_libraries)})</summary>"
        f"<p class='muted small'>Removed libraries stay ignored when you run Discover Libraries. Restore one here if you want to sync and use it again.</p>"
        f"<table><thead><tr><th>Server</th><th>Library</th><th>Type</th><th>Action</th></tr></thead><tbody>{removed_rows}</tbody></table>"
        f"</details></div>" if removed_libraries else ""
    )

    msg_html = f"<div class='msg'>{e(message)}</div>" if message else ""
    all_status = PLEX_SYNC_ALL_STATUS
    all_sync_html = ""
    if all_status.get("running"):
        done = int(all_status.get("done", 0))
        total = int(all_status.get("total", 0))
        pct = int((done * 100) / total) if total else 0
        current = e(all_status.get("current") or "Preparing…")
        all_sync_html = f"<p><b>Sync All:</b> {done}/{total} libraries — {current}</p><div class='progress'><span style='width:{pct}%'></span></div>"
    elif all_status.get("results"):
        ok_count = sum(1 for r in all_status["results"] if r.get("ok"))
        fail_count = len(all_status["results"]) - ok_count
        summary_class = "badge" if not fail_count else "badge warn"
        result_lines = "".join(
            f"<li>{'✓' if r.get('ok') else '✗'} {e(r.get('library',''))}"
            + ((f" — {int(r.get('items',0)):,} items" + (f" — {int(r.get('shows',0)):,} shows / {int(r.get('networks',0)):,} networks" if int(r.get('shows',0)) else "")) if r.get('ok') else f" — {e(r.get('error','failed'))}")
            + "</li>"
            for r in all_status["results"]
        )
        all_sync_html = f"<p><span class='{summary_class}'>{ok_count} succeeded / {fail_count} failed</span></p><details><summary>Last Sync All results</summary><ul>{result_lines}</ul></details>"

    next_auto = format_plex_schedule_time(get_setting("plex_auto_sync_next_at"))
    last_auto = format_plex_schedule_time(get_setting("plex_auto_sync_last_at"))
    auto_schedule_html = (
        f"<div class='card'><h2>Automatic Plex Sync</h2>"
        f"<p><b>Automatic Plex sync</b> <span class='muted'>uses the timezone and hour configured by VIPERTV_PLEX_AUTO_SYNC_TIMEZONE / VIPERTV_PLEX_AUTO_SYNC_HOUR.</span></p>"
        f"<div class='grid'><div><span class='muted small'>Last automatic sync</span><br><b>{e(last_auto)}</b></div>"
        f"<div><span class='muted small'>Next automatic sync</span><br><b>{e(next_auto)}</b></div></div></div>"
    )

    body = f"""
{msg_html}
{auto_schedule_html}
<div class='card'><h2>Connect Plex Media Server</h2>
<form method='post' action='/plex/servers/add'><div class='grid3'><div><label>Name (optional)</label><input name='name' placeholder='My Plex Server'></div><div><label>Plex URL</label><input name='base_url' required placeholder='http://192.168.1.100:32400'></div><div><label>X-Plex-Token</label><input type='password' name='token' required autocomplete='off'></div></div><button>Test & Save Plex</button></form>
<p class='muted small'>The token is stored only in ViperTV's persistent SQLite database and is never included in JSON exports. ViperTV uses it to read your Plex catalog and request Plex's transcoder during playback.</p></div>
<div class='card'><h2>Plex Servers</h2><table><thead><tr><th>Name</th><th>URL</th><th>Token</th><th>PMS Version</th><th>Actions</th></tr></thead><tbody>{server_rows}</tbody></table></div>
<div class='card'><div class='toolbar' style='justify-content:space-between'><div><h2 style='margin-bottom:4px'>Plex Libraries</h2><span class='muted small'>Refresh every discovered TV and movie library with one click.</span></div><form method='post' action='/plex/sync-all'><button {'disabled' if all_status.get('running') else ''}>{'Syncing All…' if all_status.get('running') else 'Sync All Libraries'}</button></form></div>
{all_sync_html}
<table><thead><tr><th>Server</th><th>Library</th><th>Type</th><th>Cached Items</th><th>Networks</th><th>Rich Episodes</th><th>Last Sync</th><th>Action</th></tr></thead><tbody>{library_rows}</tbody></table>
<p class='muted'>TV sync downloads Plex's indexed episode metadata and now follows it with a batched <b>full episode metadata</b> pass for exact actors, guest stars and directors. The Rich Episodes column shows checked episodes. Use <b>Refresh Rich Credits</b> to force a complete re-read after refreshing metadata in Plex. Cast/director credits are indexed under Media → People for AI channel building. It does not FFprobe the media files. Sync All runs active libraries sequentially to avoid overloading Plex or the NAS. Removing a library affects only ViperTV's cached metadata and channel selections; it never deletes anything from Plex.</p></div>
{removed_html}
"""
    active = bool(all_status.get("running")) or any(st.get("running") for st in PLEX_SYNC_STATUS.values()) or any(st.get("running") for st in PLEX_RICH_STATUS.values())
    script = "<script>setTimeout(()=>location.reload(),5000)</script>" if active else ""
    return page_shell("Plex", body, extra_script=script)


def season_label(number: int | None) -> str:
    if number is None:
        return "Unknown"
    if number == 0:
        return "Specials"
    return f"Season {number}"


def channel_selected_summary_html(channel_id: int) -> str:
    """Human-readable list of selections and any People filter attached to a channel."""
    with db() as conn:
        rows = conn.execute(
            """SELECT cs.*, l.name AS local_library, pl.title AS plex_library, ps.name AS plex_server
               FROM channel_selections cs
               LEFT JOIN libraries l ON l.id=cs.library_id
               LEFT JOIN plex_libraries pl ON pl.id=cs.plex_library_id
               LEFT JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE cs.channel_id=? ORDER BY cs.source_type,COALESCE(cs.show_title,''),cs.season_number,cs.id""",
            (channel_id,),
        ).fetchall()
        people_filter = conn.execute(
            "SELECT actors_json,directors_json,air_year_start,air_year_end FROM channel_people_filters WHERE channel_id=?",
            (channel_id,),
        ).fetchone()

    people_html = ""
    if people_filter:
        try:
            actors = [str(x) for x in json.loads(people_filter['actors_json'] or '[]') if str(x).strip()]
        except Exception:
            actors = []
        try:
            directors = [str(x) for x in json.loads(people_filter['directors_json'] or '[]') if str(x).strip()]
        except Exception:
            directors = []
        parts=[]
        if actors:
            parts.append('Starring: ' + ', '.join(actors))
        if directors:
            parts.append('Directed by: ' + ', '.join(directors))
        ys=people_filter['air_year_start']; ye=people_filter['air_year_end']
        if ys is not None or ye is not None:
            ys = ys if ys is not None else ye
            ye = ye if ye is not None else ys
            parts.append(f"Episode air years: {ys}" if ys == ye else f"Episode air years: {ys}–{ye}")
        if parts:
            people_html = f"""<div class='card'><div class='page-heading'><div><h2>People Filter</h2><p>{e(' · '.join(parts))}</p><p class='muted small'>This filter is applied after the selected shows are expanded, so year ranges use each episode's actual air date.</p></div><span class='badge blue'>Active</span></div><form method='post' action='/channels/{channel_id}/people-filter/delete' onsubmit="return confirm('Remove the actor/director filter from this channel? The show selections will be kept.');"><button class='secondary'>Remove People Filter</button></form></div>"""

    if not rows:
        return people_html + "<div class='card'><h2>Already Selected</h2><p class='muted'>No shows, seasons or movie selections are currently attached to this channel.</p></div>"
    trs=[]
    for r in rows:
        source = f"Local / {r['local_library'] or 'Library'}" if r['source_type']=='local' else f"Plex / {r['plex_server'] or 'Server'} / {r['plex_library'] or 'Library'}"
        kind = str(r['selection_type'] or '').lower()
        title = r['show_title'] or r['show_key'] or '(Unnamed selection)'
        if kind == 'show':
            detail = 'All seasons'
        elif kind == 'season':
            detail = season_label(r['season_number'])
        elif kind == 'library':
            detail = 'Entire library'
        elif kind == 'movie':
            detail = 'Movie'
        else:
            detail = kind.title() or 'Selection'
        trs.append(f"<tr><td>{e(source)}</td><td><b>{e(title)}</b></td><td>{e(detail)}</td></tr>")
    return people_html + f"""<div class='card'><div class='page-heading'><div><h2>Already Selected</h2><p>These are the shows/seasons currently programmed on this channel.</p></div><span class='badge blue'>{len(rows)} selection{'s' if len(rows)!=1 else ''}</span></div><div class='table-wrap'><table><thead><tr><th>Source</th><th>Show / Media</th><th>Selection</th></tr></thead><tbody>{''.join(trs)}</tbody></table></div></div>"""


def channel_builder_page(channel_id: int | None = None, message: str = "") -> str:
    channel: sqlite3.Row | None = None
    if channel_id is not None:
        with db() as conn:
            channel = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
        if not channel:
            raise HTTPException(404, "Channel not found")
    selected = selected_keys(channel_id)
    local = local_picker_catalog()
    plex = plex_picker_catalog()

    def checked(payload: dict[str, Any]) -> str:
        candidate = (
            payload.get("source_type"), payload.get("library_id"), payload.get("plex_library_id"),
            payload.get("selection_type"), str(payload.get("show_key") or ""), payload.get("season_number"),
        )
        return " checked" if candidate in selected else ""

    local_html = ""
    for lib in local:
        shows_html = ""
        for show in lib["shows"]:
            show_payload = {"source_type": "local", "library_id": lib["id"], "selection_type": "show", "show_key": show["title"], "show_title": show["title"]}
            season_boxes = ""
            for season in show["seasons"]:
                p = {"source_type": "local", "library_id": lib["id"], "selection_type": "season", "show_key": show["title"], "show_title": show["title"], "season_number": season["number"]}
                season_boxes += f"<label class='season'><input type='checkbox' name='sel' value='{encode_selection(p)}'{checked(p)}>{e(season_label(season['number']))} <span class='muted small'>({season['count']})</span></label>"
            shows_html += f"<div class='picker-show'><label><input class='show-all' type='checkbox' name='sel' value='{encode_selection(show_payload)}'{checked(show_payload)}><b>{e(show['title'])}</b> — All seasons <span class='muted small'>({show['count']})</span></label><div style='padding-left:24px'>{season_boxes}</div></div>"
        local_html += f"<details><summary>Local: {e(lib['name'])} — {sum(s['count'] for s in lib['shows']):,} items / {len(lib['shows'])} shows</summary><div class='toolbar'><button type='button' class='secondary select-visible'>Select visible</button><button type='button' class='secondary clear-group'>Clear</button></div>{shows_html or '<p class=muted>No indexed shows.</p>'}</details>"

    plex_html = ""
    for lib in plex:
        if lib["type"] == "show":
            shows_html = ""
            for show in lib["shows"]:
                show_payload = {"source_type": "plex", "plex_library_id": lib["id"], "selection_type": "show", "show_key": show["key"], "show_title": show["title"]}
                season_boxes = ""
                for season in show["seasons"]:
                    p = {"source_type": "plex", "plex_library_id": lib["id"], "selection_type": "season", "show_key": show["key"], "show_title": show["title"], "season_number": season["number"]}
                    season_boxes += f"<label class='season'><input type='checkbox' name='sel' value='{encode_selection(p)}'{checked(p)}>{e(season_label(season['number']))} <span class='muted small'>({season['count']})</span></label>"
                shows_html += f"<div class='picker-show'><label><input class='show-all' type='checkbox' name='sel' value='{encode_selection(show_payload)}'{checked(show_payload)}><b>{e(show['title'])}</b> — All seasons <span class='muted small'>({show['count']})</span></label><div style='padding-left:24px'>{season_boxes}</div></div>"
            plex_html += f"<details><summary>Plex: {e(lib['server_name'])} / {e(lib['title'])} — {lib['count']:,} episodes / {len(lib['shows'])} shows</summary><div class='toolbar'><button type='button' class='secondary select-visible'>Select visible</button><button type='button' class='secondary clear-group'>Clear</button></div>{shows_html or '<p class=muted>Sync this Plex TV library first.</p>'}</details>"
        else:
            whole = {"source_type": "plex", "plex_library_id": lib["id"], "selection_type": "library", "show_key": "", "show_title": lib["title"]}
            movies_html = f"<label><input type='checkbox' name='sel' value='{encode_selection(whole)}'{checked(whole)}><b>Entire movie library</b> ({lib['count']:,} movies)</label>"
            for m in lib.get("movies", []):
                p = {"source_type": "plex", "plex_library_id": lib["id"], "selection_type": "movie", "show_key": m["rating_key"], "show_title": m["title"]}
                movies_html += f"<div class='picker-show'><label><input type='checkbox' name='sel' value='{encode_selection(p)}'{checked(p)}>{e(m['title'])} {f'({m['year']})' if m['year'] else ''}</label></div>"
            plex_html += f"<details><summary>Plex Movies: {e(lib['server_name'])} / {e(lib['title'])} — {lib['count']:,}</summary>{movies_html}</details>"

    number = e(channel["number"] if channel else "")
    name = e(channel["name"] if channel else "")
    shuffle = int(channel["shuffle"] if channel else 0)
    action = f"/channels/{channel_id}/save" if channel_id is not None else "/channels/create"
    heading = f"Edit {name}" if channel else "Create Channel"
    msg_html = f"<div class='msg'>{e(message)}</div>" if message else ""
    selected_summary = channel_selected_summary_html(channel_id) if channel_id is not None else ""
    body = f"""
{msg_html}
{selected_summary}
<form method='post' action='{action}'>
<div class='card'><h2>{heading}</h2><div class='grid3'><div><label>Channel number</label><input name='number' required value='{number}' placeholder='101'></div><div><label>Name</label><input name='name' required value='{name}' placeholder='Classic TV'></div><div><label>Order</label><select name='shuffle'><option value='0'{' selected' if not shuffle else ''}>Sequential</option><option value='1'{' selected' if shuffle else ''}>Stable shuffle</option></select></div></div>
<label>Filter shows</label><input id='show-filter' type='search' placeholder='Type a show name to filter the list…'>
<p class='muted small'>Choose <b>All seasons</b> for a show, or select only the individual seasons you want. A channel can mix local and Plex sources.</p></div>
<div class='card'><h2>Local Shows & Seasons</h2>{local_html or '<p class=muted>No local libraries indexed yet.</p>'}</div>
<div class='card'><h2>Plex Shows, Seasons & Movies</h2>{plex_html or '<p class=muted>Connect and sync Plex first from the Plex page.</p>'}</div>
<div class='card'><button>{'Save Channel' if channel else 'Create Channel'}</button> <a class='button secondary' href='/'>Cancel</a></div>
</form>
"""
    script = r"""<script>
const filter = document.getElementById('show-filter');
filter?.addEventListener('input', () => {
  const q = filter.value.toLowerCase().trim();
  document.querySelectorAll('.picker-show').forEach(el => {
    el.style.display = (!q || el.textContent.toLowerCase().includes(q)) ? '' : 'none';
  });
  document.querySelectorAll('details').forEach(d => { if(q) d.open = true; });
});
document.querySelectorAll('.show-all').forEach(cb => cb.addEventListener('change', () => {
  if (cb.checked) cb.closest('.picker-show').querySelectorAll("input[type=checkbox]:not(.show-all)").forEach(x => x.checked=false);
}));
document.querySelectorAll('.select-visible').forEach(btn => btn.addEventListener('click', () => {
  btn.closest('details').querySelectorAll('.picker-show').forEach(row => { if(row.style.display !== 'none') { const cb=row.querySelector('.show-all'); if(cb) cb.checked=true; } });
}));
document.querySelectorAll('.clear-group').forEach(btn => btn.addEventListener('click', () => {
  btn.closest('details').querySelectorAll("input[type=checkbox]").forEach(cb => cb.checked=false);
}));
</script>"""
    return page_shell("Channel Builder", body, extra_script=script)




def metadata_providers_page(msg: str = "") -> str:
    configured = tvdb_configured()
    key = get_setting("tvdb_api_key") or ""
    pin = get_setting("tvdb_pin") or ""
    masked_key = ("••••••" + key[-4:]) if key else "Not configured"
    masked_pin = ("••••" + pin[-2:]) if pin else "Not configured"
    last = format_plex_schedule_time(get_setting("tvdb_last_enrich_at"))
    with db() as conn:
        stats = conn.execute("""SELECT COUNT(*) total,
            SUM(CASE WHEN original_network IS NOT NULL AND original_network<>'' THEN 1 ELSE 0 END) with_network,
            SUM(CASE WHEN show_year IS NOT NULL THEN 1 ELSE 0 END) with_year,
            SUM(CASE WHEN last_error IS NOT NULL AND last_error<>'' THEN 1 ELSE 0 END) errors
            FROM tvdb_show_metadata""").fetchone()
        networks = conn.execute("""SELECT original_network,COUNT(*) c FROM tvdb_show_metadata
            WHERE original_network IS NOT NULL AND original_network<>'' GROUP BY original_network ORDER BY c DESC,original_network LIMIT 20""").fetchall()
    st = TVDB_ENRICH_STATUS
    done=int(st.get("done") or 0); total=int(st.get("total") or 0)
    pct=int(done*100/total) if total else (100 if st.get("finished_at") and not st.get("error") else 0)
    initial_state = str(st.get("stage") or ("Running" if st.get("running") else "Ready"))
    initial_current = str(st.get("current") or ("Preparing show list…" if st.get("running") else "No enrichment currently running."))
    progress=f"""<div class='card' id='tvdb-progress-card'>
<div class='toolbar' style='justify-content:space-between;align-items:flex-start'>
  <div><h2 style='margin-bottom:4px'>TV Show Enrichment Status</h2><span class='muted small'>Live status updates every second while TheTVDB metadata is being fetched.</span></div>
  <span class='badge blue' id='tvdb-progress-state'>{e(initial_state)}</span>
</div>
<div style='display:flex;justify-content:space-between;gap:12px;margin:14px 0 6px'>
  <b id='tvdb-progress-count'>{done:,} / {total:,}</b><b id='tvdb-progress-percent'>{pct}%</b>
</div>
<div class='progress large'><span id='tvdb-progress-bar' style='width:{pct}%'></span></div>
<p style='margin:12px 0 4px'><b>Current:</b> <span id='tvdb-progress-current'>{e(initial_current)}</span></p>
<div class='grid3' style='margin-top:12px'>
  <div class='stat'><div class='stat-label'>Matched</div><div class='stat-value' id='tvdb-progress-matched'>{int(st.get('matched') or 0):,}</div></div>
  <div class='stat'><div class='stat-label'>Unresolved</div><div class='stat-value' id='tvdb-progress-failed'>{int(st.get('failed') or 0):,}</div></div>
  <div class='stat'><div class='stat-label'>Fresh / Cached</div><div class='stat-value' id='tvdb-progress-skipped'>{int(st.get('skipped') or 0):,}</div></div>
</div>
<p class='muted small' id='tvdb-progress-time'>Elapsed: — · ETA: —</p>
<p class='small' id='tvdb-progress-error' style='color:#ff9da4;display:{'block' if st.get('error') else 'none'}'>{e(st.get('error') or '')}</p>
</div>"""
    network_rows=''.join(f"<tr><td>{e(r['original_network'])}</td><td>{int(r['c']):,}</td></tr>" for r in networks) or "<tr><td colspan='2' class='empty'>No TheTVDB network metadata cached yet.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ""
    body=notice+_page_heading('Metadata Providers','Canonical TV metadata enrichment for Channel Builder.')+f"""
<div class='stats'>
 <div class='stat'><div class='stat-label'>TVDB Shows Cached</div><div class='stat-value'>{int(stats['total'] or 0):,}</div></div>
 <div class='stat'><div class='stat-label'>With Original Network</div><div class='stat-value'>{int(stats['with_network'] or 0):,}</div></div>
 <div class='stat'><div class='stat-label'>With Premiere Year</div><div class='stat-value'>{int(stats['with_year'] or 0):,}</div></div>
 <div class='stat'><div class='stat-label'>Unresolved</div><div class='stat-value'>{int(stats['errors'] or 0):,}</div></div>
</div>
{progress}
<div class='card'><h2>TheTVDB v4</h2>
<p>ViperTV uses TheTVDB's series <b>originalNetwork</b> and premiere year as the canonical metadata for network/year channels. Plex remains the media/playback source.</p>
<p class='muted small'>Stored credentials: API key {e(masked_key)} · PIN {e(masked_pin)} · Last enrichment: {e(last)}</p>
<form method='post' action='/system/metadata/tvdb/save'><div class='grid'><div><label>API Key</label><input type='password' name='api_key' placeholder='Leave blank to keep current key' autocomplete='off'></div><div><label>Subscriber PIN (optional)</label><input type='password' name='pin' placeholder='Leave blank to keep current PIN' autocomplete='off'></div></div><div class='toolbar'><button>Save & Test TheTVDB</button></div></form>
<p class='muted small'>Create/manage your v4 key from your TheTVDB Dashboard → API Keys. User-supported keys may also require your personal subscriber PIN. Credentials stay in ViperTV's persistent SQLite database.</p>
</div>
<div class='card'><div class='toolbar' style='justify-content:space-between'><div><h2 style='margin-bottom:4px'>TV Show Enrichment</h2><span class='muted small'>Uses Plex TVDB GUIDs when available; otherwise title/year matching is conservative.</span></div><div class='toolbar'><form method='post' action='/system/metadata/tvdb/enrich'><button {'disabled' if not configured or st.get('running') else ''}>Enrich New / Stale Shows</button></form><form method='post' action='/system/metadata/tvdb/enrich-force' onsubmit="return confirm('Refresh TheTVDB metadata for every TV show? This can make many API requests.');"><button class='secondary' {'disabled' if not configured or st.get('running') else ''}>Force Refresh All</button></form></div></div>
<p>Normal enrichment refreshes only new shows or metadata older than {TVDB_REFRESH_DAYS} days. After the scheduled 72-hour Plex sync, ViperTV also runs this incremental enrichment automatically when TheTVDB is configured.</p></div>
<div class='card'><h2>Top Original Networks from TheTVDB</h2><table><thead><tr><th>Network</th><th>Shows</th></tr></thead><tbody>{network_rows}</tbody></table></div>
<div class='card'><p class='muted small'>Metadata provided by <a href='https://thetvdb.com' target='_blank' rel='noopener'>TheTVDB</a>. Please consider contributing missing information or subscribing.</p></div>
"""
    script=r"""<script>
(() => {
  const $ = id => document.getElementById(id);
  let wasRunning = false;
  let completionReloaded = false;
  const fmtNum = n => Number(n || 0).toLocaleString();
  const fmtDuration = sec => {
    if (!Number.isFinite(sec) || sec < 0) return '—';
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600); sec %= 3600;
    const m = Math.floor(sec / 60); const s = sec % 60;
    if (h) return `${h}h ${m}m`;
    if (m) return `${m}m ${s}s`;
    return `${s}s`;
  };
  async function updateTvdbProgress() {
    try {
      const resp = await fetch('/api/tvdb/status', {cache:'no-store'});
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const st = await resp.json();
      const done = Number(st.done || 0), total = Number(st.total || 0);
      const running = !!st.running;
      const pct = total > 0 ? Math.min(100, Math.floor(done * 100 / total)) : ((!running && st.finished_at && !st.error) ? 100 : 0);
      const bar = $('tvdb-progress-bar');
      if (bar) {
        if (running && total === 0) bar.classList.add('indeterminate');
        else { bar.classList.remove('indeterminate'); bar.style.width = `${pct}%`; }
      }
      if ($('tvdb-progress-count')) $('tvdb-progress-count').textContent = total ? `${fmtNum(done)} / ${fmtNum(total)}` : (running ? 'Preparing…' : `${fmtNum(done)} / ${fmtNum(total)}`);
      if ($('tvdb-progress-percent')) $('tvdb-progress-percent').textContent = total ? `${pct}%` : (running ? '…' : `${pct}%`);
      if ($('tvdb-progress-state')) $('tvdb-progress-state').textContent = st.stage || (running ? 'Running' : (st.error ? 'Failed' : 'Ready'));
      if ($('tvdb-progress-current')) $('tvdb-progress-current').textContent = st.current || (running ? 'Preparing show list…' : (st.finished_at ? 'Run finished.' : 'No enrichment currently running.'));
      if ($('tvdb-progress-matched')) $('tvdb-progress-matched').textContent = fmtNum(st.matched);
      if ($('tvdb-progress-failed')) $('tvdb-progress-failed').textContent = fmtNum(st.failed);
      if ($('tvdb-progress-skipped')) $('tvdb-progress-skipped').textContent = fmtNum(st.skipped);
      const started = st.started_at ? Date.parse(st.started_at) : NaN;
      let elapsedSec = Number.isFinite(started) ? Math.max(0, (Date.now() - started) / 1000) : NaN;
      if (!running && st.finished_at && Number.isFinite(started)) {
        const finished = Date.parse(st.finished_at);
        if (Number.isFinite(finished)) elapsedSec = Math.max(0, (finished - started) / 1000);
      }
      let etaSec = NaN;
      if (running && done > 0 && total > done && Number.isFinite(elapsedSec)) etaSec = (elapsedSec / done) * (total - done);
      if ($('tvdb-progress-time')) $('tvdb-progress-time').textContent = `Elapsed: ${fmtDuration(elapsedSec)} · ETA: ${running ? fmtDuration(etaSec) : '—'}`;
      const err = $('tvdb-progress-error');
      if (err) { err.textContent = st.error || ''; err.style.display = st.error ? 'block' : 'none'; }
      document.querySelectorAll("form[action='/system/metadata/tvdb/enrich'] button,form[action='/system/metadata/tvdb/enrich-force'] button").forEach(b => b.disabled = running);
      if (wasRunning && !running && st.finished_at && !completionReloaded) {
        completionReloaded = true;
        setTimeout(() => location.reload(), 1200);
        return;
      }
      wasRunning = running;
    } catch (err) {
      if ($('tvdb-progress-state')) $('tvdb-progress-state').textContent = 'Status unavailable';
      if ($('tvdb-progress-current')) $('tvdb-progress-current').textContent = `Could not read live status: ${err}`;
    }
    setTimeout(updateTvdbProgress, 1000);
  }
  updateTvdbProgress();
})();
</script>"""
    return page_shell('Metadata Providers',body,extra_script=script)


# -------------------------------- background ---------------------------------

async def periodic_backup_loop() -> None:
    while True:
        await asyncio.sleep(3600)
        try:
            await asyncio.to_thread(backup_all, "hourly")
        except Exception as exc:
            print(f"hourly backup error: {exc}", flush=True)


async def periodic_scan_loop() -> None:
    if AUTO_SCAN_HOURS <= 0:
        return
    while True:
        await asyncio.sleep(AUTO_SCAN_HOURS * 3600)
        try:
            results = await asyncio.to_thread(scan_all)
            print(f"auto scan: {results}", flush=True)
        except Exception as exc:
            print(f"auto scan error: {exc}", flush=True)


async def periodic_plex_sync_loop() -> None:
    """Sync every 72 hours at 7:00 AM Pacific, with cadence persisted in SQLite."""
    while True:
        try:
            next_local = ensure_plex_auto_sync_schedule()
            now_local = datetime.now(plex_auto_sync_tz())
            delay = max(0.0, (next_local - now_local).total_seconds())
            if delay > 0:
                # Re-check at least hourly so wall-clock / DST changes are harmless.
                await asyncio.sleep(min(delay, 3600.0))
                continue

            if PLEX_SYNC_ALL_STATUS.get("running") or any(st.get("running") for st in PLEX_SYNC_STATUS.values()):
                print("scheduled Plex sync waiting for an existing Plex sync to finish", flush=True)
                await asyncio.sleep(300)
                continue

            run_local = datetime.now(plex_auto_sync_tz())
            print(f"scheduled Plex sync starting at {run_local.strftime('%Y-%m-%d %H:%M %Z')}", flush=True)
            try:
                result = await asyncio.to_thread(sync_all_plex_libraries)
                print(f"scheduled Plex sync complete: {result}", flush=True)
                set_setting("plex_auto_sync_last_at", datetime.now(timezone.utc).isoformat())
                if tvdb_configured() and not TVDB_ENRICH_STATUS.get("running"):
                    try:
                        tvdb_result = await asyncio.to_thread(enrich_tvdb_metadata, False)
                        print(f"scheduled TheTVDB enrichment complete: {tvdb_result}", flush=True)
                    except Exception as tvdb_exc:
                        print(f"scheduled TheTVDB enrichment error: {tvdb_exc}", flush=True)
            except Exception as exc:
                print(f"scheduled Plex sync error: {exc}", flush=True)
                set_setting("plex_auto_sync_last_error", str(exc)[:1000])
                set_setting("plex_auto_sync_last_at", datetime.now(timezone.utc).isoformat())
            finally:
                nxt = set_next_plex_auto_sync_from(run_local)
                print(f"next scheduled Plex sync: {nxt.strftime('%Y-%m-%d %H:%M %Z')}", flush=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"auto Plex sync scheduler error: {exc}", flush=True)
            await asyncio.sleep(300)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Keep startup bounded. v1.0.0 synchronously walked every indexed local
    # file looking for NFO/art/subtitle sidecars here; on very large libraries
    # that could make Uvicorn sit at "Waiting for application startup" for a
    # long time and hammer the media disks. Local metadata enrichment belongs
    # to library scan/update work, not container boot.
    ensure_dirs()
    print("ViperTV: opening/migrating database...", flush=True)
    init_db()
    init_v1_db()
    init_v12_db()
    init_pluto_db()
    init_live_stream_db()
    init_retro_tv_db()
    next_plex_sync = ensure_plex_auto_sync_schedule()
    print(f"ViperTV: next Plex auto-sync {next_plex_sync.strftime('%Y-%m-%d %H:%M %Z')}", flush=True)
    print("ViperTV: creating startup database backup...", flush=True)
    backup_all("startup")
    backup_task = asyncio.create_task(periodic_backup_loop())
    scan_task = asyncio.create_task(periodic_scan_loop())
    plex_sync_task = asyncio.create_task(periodic_plex_sync_loop())
    pluto_sync_task = asyncio.create_task(periodic_pluto_sync_loop())
    preview_cleanup_task = asyncio.create_task(browser_hls_cleanup_loop())
    print("ViperTV: startup initialization complete", flush=True)
    yield
    for task in (backup_task, scan_task, plex_sync_task, pluto_sync_task, preview_cleanup_task):
        task.cancel()
    for channel_id in list(BROWSER_HLS_PROCESSES):
        _stop_browser_hls(channel_id, remove_files=True)
    await stop_all_shared_channel_streams()
    await stop_all_pluto_streams()
    stop_all_pluto_hls(remove_files=True)


app = FastAPI(title=APP_NAME, version=APP_VERSION, lifespan=lifespan)



# ---------------------- ErsatzTV-style navigation pages ----------------------
def _page_heading(title: str, subtitle: str, actions: str = "") -> str:
    return f"<div class='page-heading'><div><h1>{e(title)}</h1><p>{e(subtitle)}</p></div><div class='toolbar'>{actions}</div></div>"


def local_libraries_page(msg: str = "") -> str:
    with db() as conn:
        libs = conn.execute("SELECT l.*,COUNT(m.id) media_count FROM libraries l LEFT JOIN media m ON m.library_id=l.id GROUP BY l.id ORDER BY l.name").fetchall()
    rows = ''.join(
        f"<tr><td><b>{e(x['name'])}</b></td><td><span class='badge blue'>{e(special_media_category(x['name']) or 'Local')}</span></td><td><code>{e(x['path'])}</code></td><td>{x['media_count']:,}</td><td>"
        f"<form class='inline' method='post' action='/libraries/{x['id']}/scan'><button>Scan</button></form> "
        f"<form class='inline' method='post' action='/libraries/{x['id']}/delete' onsubmit='return confirm(&quot;Remove this library from ViperTV? Media files will not be deleted.&quot;);'><button class='danger'>Delete</button></form></td></tr>" for x in libs
    ) or "<tr><td colspan='5' class='empty'>No local libraries have been added.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('Local Media Sources','Add folders from your OMV host and scan them into ViperTV.')+f"""
<div class='grid'><div class='card'><h2>Add Local Library</h2><form method='post' action='/libraries/add'><label>Name</label><input name='name' required placeholder='TV Shows'><label>Container Path</label><input name='path' required placeholder='/mnt/share2'><button>Add Library</button></form></div>
<div class='card'><h2>Scanning</h2><p>Local scanning reads file durations and show/season information. For very large Plex-managed libraries, use the Plex source instead.</p><form method='post' action='/libraries/scan-all'><button class='secondary'>Scan All Local Libraries</button></form></div></div>
<div class='card'><h2>Libraries</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Category</th><th>Path</th><th>Items</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return page_shell('Local Media Sources',body)


def _show_detail_url(source: str, library_id: int, show_title: str, show_key: str = '') -> str:
    return (f"/media/tv/show?source={quote(str(source))}&library_id={int(library_id)}"
            f"&show_title={quote(str(show_title))}&show_key={quote(str(show_key or ''))}")


def _movie_detail_url(source: str, library_id: int, movie_key: str) -> str:
    return (f"/media/movies/detail?source={quote(str(source))}&library_id={int(library_id)}"
            f"&movie_key={quote(str(movie_key))}")


def _person_detail_url(name: str) -> str:
    # Legacy/fallback name URL retained for compatibility with bookmarks.
    return f"/media/people/detail?name={quote(str(name or ''), safe='')}"


def _person_detail_id_url(credit_id: Any, name: str = '') -> str:
    """Return a query-string-free person URL when a credit row id is available."""
    cid=safe_int(credit_id)
    return f"/media/person/{cid}" if cid is not None and cid>0 else _person_detail_url(name)


def libraries_browser_page(msg: str = '') -> str:
    """Unified browse-first view for all indexed media libraries."""
    with db() as conn:
        local = conn.execute("""SELECT l.id,l.name,l.path,COUNT(m.id) items,
               COUNT(DISTINCT CASE WHEN m.show_title IS NOT NULL AND m.show_title<>'' THEN m.show_title END) shows
               FROM libraries l LEFT JOIN media m ON m.library_id=l.id
               GROUP BY l.id ORDER BY l.name COLLATE NOCASE""").fetchall()
        plex = conn.execute("""SELECT pl.id,pl.title,pl.library_type,ps.name server_name,COUNT(pm.id) items,
               COUNT(DISTINCT CASE WHEN pm.show_title IS NOT NULL AND pm.show_title<>'' THEN COALESCE(pm.show_rating_key,pm.show_title) END) shows
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               LEFT JOIN plex_media pm ON pm.plex_library_id=pl.id
               WHERE pl.enabled=1 GROUP BY pl.id ORDER BY pl.title COLLATE NOCASE""").fetchall()
        external = conn.execute("""SELECT el.id,el.name,el.library_type,ms.name server_name,ms.kind,COUNT(em.id) items,
               COUNT(DISTINCT CASE WHEN em.show_title IS NOT NULL AND em.show_title<>'' THEN em.show_title END) shows
               FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id
               LEFT JOIN external_media em ON em.library_id=el.id
               WHERE el.enabled=1 AND ms.enabled=1 GROUP BY el.id ORDER BY el.name COLLATE NOCASE""").fetchall()
    rows=[]
    for x in local:
        rows.append(f"<tr><td><b>{e(x['name'])}</b><div class='muted small'>{e(x['path'])}</div></td><td>Local</td><td>{e(special_media_category(x['name']) or 'Mixed')}</td><td>{int(x['shows'] or 0):,}</td><td>{int(x['items'] or 0):,}</td><td><a class='button secondary' href='/media/libraries/local/{x['id']}'>Browse</a></td></tr>")
    for x in plex:
        rows.append(f"<tr><td><b>{e(x['title'])}</b><div class='muted small'>{e(x['server_name'])}</div></td><td>Plex</td><td>{e(x['library_type'] or 'Mixed')}</td><td>{int(x['shows'] or 0):,}</td><td>{int(x['items'] or 0):,}</td><td><a class='button secondary' href='/media/libraries/plex/{x['id']}'>Browse</a></td></tr>")
    for x in external:
        rows.append(f"<tr><td><b>{e(x['name'])}</b><div class='muted small'>{e(x['server_name'])}</div></td><td>{e(str(x['kind']).title())}</td><td>{e(x['library_type'] or 'Mixed')}</td><td>{int(x['shows'] or 0):,}</td><td>{int(x['items'] or 0):,}</td><td><a class='button secondary' href='/media/libraries/external/{x['id']}'>Browse</a></td></tr>")
    rows_html=''.join(rows) or "<tr><td colspan='6' class='empty'>No indexed libraries yet.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('Libraries','Browse the actual media inside Local, Plex, Jellyfin and Emby libraries. Click a TV show or movie to open its full ViperTV metadata page.')+f"""
<div class='card'><div class='table-wrap'><table><thead><tr><th>Library</th><th>Source</th><th>Type</th><th>Shows</th><th>Items</th><th></th></tr></thead><tbody>{rows_html}</tbody></table></div></div>"""
    return page_shell('Libraries',body)


def library_browse_page(source: str, library_id: int, msg: str = '') -> str:
    source=(source or '').lower()
    show_rows=[]; item_rows=[]; library_name='Library'; source_label=source.title()
    with db() as conn:
        if source=='local':
            lib=conn.execute('SELECT * FROM libraries WHERE id=?',(library_id,)).fetchone()
            if not lib: raise HTTPException(404,'Library not found')
            library_name=str(lib['name']); source_label='Local'
            shows=conn.execute("""SELECT show_title,COUNT(*) episodes,COUNT(DISTINCT season_number) seasons,
                    MAX(original_network) network,MAX(show_year) show_year
                    FROM media WHERE library_id=? AND show_title IS NOT NULL AND show_title<>''
                    GROUP BY show_title ORDER BY show_title COLLATE NOCASE""",(library_id,)).fetchall()
            loose=conn.execute("""SELECT id,title,duration,year FROM media WHERE library_id=?
                    AND (show_title IS NULL OR show_title='') ORDER BY title COLLATE NOCASE LIMIT 3000""",(library_id,)).fetchall()
            for x in shows:
                url=_show_detail_url('local',library_id,x['show_title'],x['show_title'])
                show_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['show_title'])}</b></a></td><td>{e(x['network'] or '')}</td><td>{e(x['show_year'] or '')}</td><td>{int(x['seasons'] or 0)}</td><td>{int(x['episodes'] or 0)}</td></tr>")
            for x in loose:
                url=_movie_detail_url('local',library_id,str(x['id']))
                item_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['title'])}</b></a></td><td>{e(x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>")
        elif source=='plex':
            lib=conn.execute("""SELECT pl.*,ps.name server_name FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id WHERE pl.id=? AND pl.enabled=1""",(library_id,)).fetchone()
            if not lib: raise HTTPException(404,'Library not found')
            library_name=str(lib['title']); source_label=f"Plex / {lib['server_name']}"
            shows=conn.execute("""SELECT COALESCE(show_rating_key,show_title) show_key,show_title,COUNT(*) episodes,COUNT(DISTINCT season_number) seasons,
                    MAX(original_network) network,MAX(COALESCE(show_year,year)) show_year
                    FROM plex_media WHERE plex_library_id=? AND media_type='episode' AND show_title IS NOT NULL AND show_title<>''
                    GROUP BY COALESCE(show_rating_key,show_title),show_title ORDER BY show_title COLLATE NOCASE""",(library_id,)).fetchall()
            loose=conn.execute("""SELECT rating_key,title,duration,year,originally_available_at FROM plex_media WHERE plex_library_id=? AND media_type='movie' ORDER BY title COLLATE NOCASE LIMIT 3000""",(library_id,)).fetchall()
            for x in shows:
                url=_show_detail_url('plex',library_id,x['show_title'],x['show_key'])
                show_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['show_title'])}</b></a></td><td>{e(x['network'] or '')}</td><td>{e(x['show_year'] or '')}</td><td>{int(x['seasons'] or 0)}</td><td>{int(x['episodes'] or 0)}</td></tr>")
            for x in loose:
                url=_movie_detail_url('plex',library_id,str(x['rating_key']))
                item_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['title'])}</b></a></td><td>{e(x['originally_available_at'] or x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>")
        elif source=='external':
            lib=conn.execute("""SELECT el.*,ms.name server_name,ms.kind FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.id=? AND el.enabled=1 AND ms.enabled=1""",(library_id,)).fetchone()
            if not lib: raise HTTPException(404,'Library not found')
            library_name=str(lib['name']); source_label=f"{str(lib['kind']).title()} / {lib['server_name']}"
            shows=conn.execute("""SELECT show_title,COUNT(*) episodes,COUNT(DISTINCT season_number) seasons,MAX(year) show_year
                    FROM external_media WHERE library_id=? AND media_type='episode' AND show_title IS NOT NULL AND show_title<>''
                    GROUP BY show_title ORDER BY show_title COLLATE NOCASE""",(library_id,)).fetchall()
            loose=conn.execute("""SELECT external_id,title,duration,year FROM external_media WHERE library_id=? AND media_type='movie' ORDER BY title COLLATE NOCASE LIMIT 3000""",(library_id,)).fetchall()
            for x in shows:
                url=_show_detail_url('external',library_id,x['show_title'],x['show_title'])
                show_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['show_title'])}</b></a></td><td></td><td>{e(x['show_year'] or '')}</td><td>{int(x['seasons'] or 0)}</td><td>{int(x['episodes'] or 0)}</td></tr>")
            for x in loose:
                url=_movie_detail_url('external',library_id,str(x['external_id']))
                item_rows.append(f"<tr><td><a href='{e(url)}'><b>{e(x['title'])}</b></a></td><td>{e(x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>")
        else:
            raise HTTPException(404,'Unknown library source')
    shows_html=''.join(show_rows) or "<tr><td colspan='5' class='empty'>No TV shows were found in this library.</td></tr>"
    items_html=''.join(item_rows) or "<tr><td colspan='3' class='empty'>No standalone movies/videos were found in this library.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading(library_name,f'{source_label} library — click any TV show or movie to view metadata and add it to a Collection or Playlist.',"<a class='button secondary' href='/media/libraries'>All Libraries</a>")+f"""
<div class='card'><h2>TV Shows</h2><div class='table-wrap'><table><thead><tr><th>Show</th><th>Network</th><th>Year</th><th>Seasons</th><th>Episodes</th></tr></thead><tbody>{shows_html}</tbody></table></div></div>
<div class='card'><h2>Movies / Standalone Videos</h2><div class='table-wrap'><table><thead><tr><th>Title</th><th>Year / Date</th><th>Runtime</th></tr></thead><tbody>{items_html}</tbody></table></div></div>"""
    return page_shell(library_name,body)


def _show_selection_for(source: str, library_id: int, show_title: str, show_key: str='') -> str:
    if source=='local':
        return encode_selection({'source_type':'local','library_id':library_id,'selection_type':'show','show_title':show_title})
    if source=='plex':
        return encode_selection({'source_type':'plex','plex_library_id':library_id,'selection_type':'show','show_key':show_key or show_title,'show_title':show_title})
    if source=='external':
        return encode_selection({'source_type':'external','external_library_id':library_id,'selection_type':'show','show_title':show_title})
    raise ValueError('Unknown source')


def tv_show_detail_page(source: str, library_id: int, show_title: str, show_key: str='', msg: str='') -> str:
    source=(source or '').lower(); show_title=(show_title or '').strip(); show_key=(show_key or '').strip()
    if not show_title: raise HTTPException(404,'Show not found')
    with db() as conn:
        if source=='local':
            lib=conn.execute('SELECT name FROM libraries WHERE id=?',(library_id,)).fetchone()
            eps=conn.execute("""SELECT * FROM media WHERE library_id=? AND show_title=? AND duration>0
                    ORDER BY COALESCE(season_number,-1),COALESCE(episode_number,-1),title COLLATE NOCASE""",(library_id,show_title)).fetchall()
            source_label='Local'; library_name=str(lib['name']) if lib else '' ; effective_key=show_title
        elif source=='plex':
            lib=conn.execute("""SELECT pl.title,ps.name server_name FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id WHERE pl.id=?""",(library_id,)).fetchone()
            if show_key:
                eps=conn.execute("""SELECT * FROM plex_media WHERE plex_library_id=? AND media_type='episode'
                        AND (show_rating_key=? OR (show_rating_key IS NULL AND show_title=?))
                        ORDER BY COALESCE(season_number,-1),COALESCE(episode_number,-1),title COLLATE NOCASE""",(library_id,show_key,show_title)).fetchall()
            else:
                eps=conn.execute("""SELECT * FROM plex_media WHERE plex_library_id=? AND media_type='episode' AND show_title=?
                        ORDER BY COALESCE(season_number,-1),COALESCE(episode_number,-1),title COLLATE NOCASE""",(library_id,show_title)).fetchall()
            source_label=f"Plex / {lib['server_name']}" if lib else 'Plex'; library_name=str(lib['title']) if lib else ''
            effective_key=show_key or (str(eps[0]['show_rating_key']) if eps and eps[0]['show_rating_key'] else show_title)
        elif source=='external':
            lib=conn.execute("""SELECT el.name,ms.name server_name,ms.kind FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.id=?""",(library_id,)).fetchone()
            eps=conn.execute("""SELECT * FROM external_media WHERE library_id=? AND media_type='episode' AND show_title=? AND duration>0
                    ORDER BY COALESCE(season_number,-1),COALESCE(episode_number,-1),title COLLATE NOCASE""",(library_id,show_title)).fetchall()
            source_label=f"{str(lib['kind']).title()} / {lib['server_name']}" if lib else 'External'; library_name=str(lib['name']) if lib else '' ; effective_key=show_title
        else:
            raise HTTPException(404,'Unknown show source')
        if not eps: raise HTTPException(404,'Show not found')
        meta=conn.execute('SELECT * FROM tvdb_show_metadata WHERE source_type=? AND library_id=? AND show_key=?',(source,library_id,effective_key)).fetchone() if source in ('local','plex') else None
        people=conn.execute("""SELECT id,person_name,credit_type,character_name,media_type FROM people_credits
                WHERE source_type=? AND library_id=? AND (show_key=? OR (media_type='show' AND media_key=?))
                ORDER BY credit_type,person_name COLLATE NOCASE""",(source,library_id,effective_key,effective_key)).fetchall() if source in ('local','plex') else []
        manual=conn.execute("SELECT id,name FROM collections WHERE kind='manual' ORDER BY name").fetchall()
        playlists=conn.execute('SELECT id,name FROM playlists ORDER BY name').fetchall()
    def first_nonempty(field):
        for r in eps:
            try:v=r[field]
            except Exception:v=None
            if v not in (None,''): return v
        return None
    network=(meta['original_network'] if meta and meta['original_network'] else first_nonempty('original_network')) if source in ('local','plex') else None
    year=(meta['show_year'] if meta and meta['show_year'] else (first_nonempty('show_year') if source in ('local','plex') else first_nonempty('year')))
    try: genres=[str(x) for x in json.loads(meta['genres_json'] or '[]')] if meta else []
    except Exception: genres=[]
    status=str(meta['series_status'] or '') if meta else ''
    actors=[]; directors=[]; seen=set()
    for r in people:
        key=(r['credit_type'],str(r['person_name']),str(r['character_name'] or ''))
        if key in seen: continue
        seen.add(key)
        person_name=str(r['person_name'])
        person_link=f"<a class='person-link' href='{e(_person_detail_id_url(r['id'] if 'id' in r.keys() else None,person_name))}'><b>{e(person_name)}</b></a>"
        if r['credit_type']=='actor':
            actors.append(person_link+(f" as {e(r['character_name'])}" if r['character_name'] else ''))
        elif r['credit_type']=='director': directors.append(person_link)
    seasons=sorted({int(r['season_number']) for r in eps if r['season_number'] is not None})
    total_seconds=sum(float(r['duration'] or 0) for r in eps)
    token=_show_selection_for(source,library_id,show_title,effective_key)
    manual_opts=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in manual)
    playlist_opts=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in playlists)
    metadata_rows=[('Source',source_label),('Library',library_name),('Network',network or ''),('Original Year',year or ''),('Status',status),('Genres',', '.join(genres)),('Seasons',len(seasons)),('Episodes',len(eps)),('Total Runtime',f"{int(total_seconds//3600)}h {int((total_seconds%3600)//60)}m")]
    meta_html=''.join(f"<tr><th style='width:190px'>{e(k)}</th><td>{e(v)}</td></tr>" for k,v in metadata_rows if v not in ('',None))
    actor_html=', '.join(actors) or '<span class="muted">No actor metadata imported.</span>'
    director_html=', '.join(directors) or '<span class="muted">No director metadata imported.</span>'
    erows=[]
    for r in eps:
        sn=r['season_number']; en=r['episode_number']; ep=f"S{int(sn):02d}E{int(en):02d}" if sn is not None and en is not None else ''
        air=''
        if source=='plex': air=str(r['originally_available_at'] or '')
        elif source=='external': air=str(r['year'] or '')
        else: air=str(r['year'] or r['show_year'] or '') if 'year' in r.keys() else str(r['show_year'] or '')
        title=str((r['episode_title'] if source=='local' else r['title']) or r['title'] or '')
        summary=str(r['summary'] or '') if 'summary' in r.keys() else ''
        erows.append(f"<tr><td>{e(ep)}</td><td><b>{e(title)}</b>{('<div class=\'muted small\'>'+e(summary)+'</div>') if summary else ''}</td><td>{e(air)}</td><td>{int((r['duration'] or 0)/60)} min</td></tr>")
    return_url=_show_detail_url(source,library_id,show_title,effective_key)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading(show_title,'Full ViperTV metadata and library actions.',f"<a class='button secondary' href='/media/libraries/{e(source)}/{library_id}'>Back to Library</a>")+f"""
<div class='grid'>
 <div class='card'><h2>Show Metadata</h2><div class='table-wrap'><table><tbody>{meta_html}</tbody></table></div><h3>Actors / Characters</h3><p>{actor_html}</p><h3>Directors</h3><p>{director_html}</p></div>
 <div>
  <div class='card'><h2>Add Entire Show To Collection</h2><form method='post' action='/media/tv/show/add-to-collection'><input type='hidden' name='token' value='{e(token)}'><input type='hidden' name='return_url' value='{e(return_url)}'><label>Existing Manual Collection</label><select name='collection_id'><option value=''>— choose —</option>{manual_opts}</select><label>Or Create New Collection</label><input name='new_name' placeholder='{e(show_title)} Collection'><button>Add Entire Show</button></form></div>
  <div class='card'><h2>Add Entire Show To Playlist</h2><form method='post' action='/media/tv/show/add-to-playlist'><input type='hidden' name='token' value='{e(token)}'><input type='hidden' name='return_url' value='{e(return_url)}'><label>Existing Playlist</label><select name='playlist_id'><option value=''>— choose —</option>{playlist_opts}</select><label>Or Create New Playlist</label><input name='new_name' placeholder='My TV Playlist'><label>Playback Order</label><select name='playback_order'><option value='season_episode'>Season / Episode</option><option value='chronological'>Chronological</option><option value='shuffle'>Shuffle</option><option value='random'>Random Daily Order</option></select><button>Add Entire Show</button></form><p class='muted small'>Playlists preserve the order of the entries you add. Each show can have its own playback order.</p></div>
 </div>
</div>
<div class='card'><h2>Episodes</h2><div class='table-wrap'><table><thead><tr><th>Episode</th><th>Title / Plot</th><th>Air Date / Year</th><th>Runtime</th></tr></thead><tbody>{''.join(erows)}</tbody></table></div></div>"""
    return page_shell(show_title,body)


def _movie_selection_for(source: str, library_id: int, movie_key: str) -> str:
    source=(source or '').lower(); movie_key=str(movie_key or '')
    if source=='local':
        return encode_selection({'source_type':'local','library_id':library_id,'selection_type':'item','media_id':int(movie_key)})
    if source=='plex':
        return encode_selection({'source_type':'plex','plex_library_id':library_id,'selection_type':'item','rating_key':movie_key})
    if source=='external':
        return encode_selection({'source_type':'external','external_library_id':library_id,'selection_type':'item','external_id':movie_key})
    raise ValueError('Unknown source')


def movie_detail_page(source: str, library_id: int, movie_key: str, msg: str='') -> str:
    source=(source or '').lower(); movie_key=str(movie_key or '').strip()
    if not movie_key: raise HTTPException(404,'Movie not found')
    with db() as conn:
        people=[]
        if source=='local':
            lib=conn.execute('SELECT name FROM libraries WHERE id=?',(library_id,)).fetchone()
            row=conn.execute("""SELECT m.* FROM media m WHERE m.library_id=? AND m.id=?
                    AND (m.show_title IS NULL OR m.show_title='')""",(library_id,safe_int(movie_key))).fetchone()
            source_label='Local'; library_name=str(lib['name']) if lib else ''
            if row:
                people=conn.execute("""SELECT id,person_name,credit_type,character_name FROM people_credits
                    WHERE source_type='local' AND library_id=? AND media_type='movie' AND media_key=?
                    ORDER BY credit_type,person_name COLLATE NOCASE""",(library_id,str(row['id']))).fetchall()
            release_date=str(row['year'] or '') if row else ''
            poster=str(row['poster_path'] or '') if row and 'poster_path' in row.keys() else ''
            fanart=str(row['fanart_path'] or '') if row and 'fanart_path' in row.keys() else ''
            path=str(row['path'] or '') if row else ''
            source_id=str(row['id']) if row else movie_key
        elif source=='plex':
            lib=conn.execute("""SELECT pl.title,ps.name server_name FROM plex_libraries pl
                    JOIN plex_servers ps ON ps.id=pl.server_id WHERE pl.id=?""",(library_id,)).fetchone()
            row=conn.execute("""SELECT * FROM plex_media WHERE plex_library_id=? AND media_type='movie' AND rating_key=?""",(library_id,movie_key)).fetchone()
            source_label=f"Plex / {lib['server_name']}" if lib else 'Plex'; library_name=str(lib['title']) if lib else ''
            if row:
                people=conn.execute("""SELECT id,person_name,credit_type,character_name FROM people_credits
                    WHERE source_type='plex' AND library_id=? AND media_type='movie' AND media_key=?
                    ORDER BY credit_type,person_name COLLATE NOCASE""",(library_id,str(row['rating_key']))).fetchall()
            release_date=str((row['originally_available_at'] or row['year'] or '') if row else '')
            poster=str(row['thumb'] or '') if row else ''
            fanart=''; path=''; source_id=str(row['rating_key']) if row else movie_key
        elif source=='external':
            lib=conn.execute("""SELECT el.name,ms.name server_name,ms.kind FROM external_libraries el
                    JOIN media_servers ms ON ms.id=el.server_id WHERE el.id=?""",(library_id,)).fetchone()
            row=conn.execute("""SELECT * FROM external_media WHERE library_id=? AND media_type='movie' AND external_id=?""",(library_id,movie_key)).fetchone()
            source_label=f"{str(lib['kind']).title()} / {lib['server_name']}" if lib else 'External'; library_name=str(lib['name']) if lib else ''
            release_date=str(row['year'] or '') if row else ''
            poster=str(row['thumb'] or '') if row else ''
            fanart=''; path=str(row['path'] or '') if row else ''; source_id=str(row['external_id']) if row else movie_key
        else:
            raise HTTPException(404,'Unknown movie source')
        if not row: raise HTTPException(404,'Movie not found')
        manual=conn.execute("SELECT id,name FROM collections WHERE kind='manual' ORDER BY name").fetchall()
        playlists=conn.execute('SELECT id,name FROM playlists ORDER BY name').fetchall()
    title=str(row['title'] or 'Untitled')
    duration=float(row['duration'] or 0)
    summary=str(row['summary'] or '') if 'summary' in row.keys() else ''
    actors=[]; directors=[]; seen=set()
    for r in people:
        key=(str(r['credit_type']),str(r['person_name']),str(r['character_name'] or ''))
        if key in seen: continue
        seen.add(key)
        person_name=str(r['person_name'])
        person_link=f"<a class='person-link' href='{e(_person_detail_id_url(r['id'] if 'id' in r.keys() else None,person_name))}'><b>{e(person_name)}</b></a>"
        if r['credit_type']=='actor':
            actors.append(person_link+(f" as {e(r['character_name'])}" if r['character_name'] else ''))
        elif r['credit_type']=='director': directors.append(person_link)
    token=_movie_selection_for(source,library_id,source_id)
    manual_opts=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in manual)
    playlist_opts=''.join(f"<option value='{x['id']}'>{e(x['name'])}</option>" for x in playlists)
    metadata_rows=[
        ('Source',source_label),('Library',library_name),('Release Date / Year',release_date),
        ('Runtime',f"{int(duration//3600)}h {int((duration%3600)//60)}m" if duration>=3600 else f"{int(duration//60)} min"),
    ]
    if path: metadata_rows.append(('File / Path',path))
    if source=='plex': metadata_rows.append(('Plex Rating Key',source_id))
    elif source=='external': metadata_rows.append(('External Media ID',source_id))
    if poster: metadata_rows.append(('Poster',poster))
    if fanart: metadata_rows.append(('Fanart',fanart))
    meta_html=''.join(f"<tr><th style='width:190px'>{e(k)}</th><td>{e(v)}</td></tr>" for k,v in metadata_rows if v not in ('',None))
    actor_html=', '.join(actors) or '<span class="muted">No actor metadata imported for this movie.</span>'
    director_html=', '.join(directors) or '<span class="muted">No director metadata imported for this movie.</span>'
    return_url=_movie_detail_url(source,library_id,source_id)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading(title,'Full ViperTV movie metadata and library actions.',f"<a class='button secondary' href='/media/libraries/{e(source)}/{library_id}'>Back to Library</a>")+f"""
<div class='grid'>
 <div class='card'><h2>Movie Metadata</h2><div class='table-wrap'><table><tbody>{meta_html}</tbody></table></div>
  <h3>Plot / Summary</h3><p>{e(summary) if summary else '<span class="muted">No plot metadata imported.</span>'}</p>
  <h3>Actors / Characters</h3><p>{actor_html}</p><h3>Directors</h3><p>{director_html}</p>
 </div>
 <div>
  <div class='card'><h2>Add Movie To Collection</h2><form method='post' action='/media/movies/add-to-collection'><input type='hidden' name='token' value='{e(token)}'><input type='hidden' name='return_url' value='{e(return_url)}'><label>Existing Manual Collection</label><select name='collection_id'><option value=''>— choose —</option>{manual_opts}</select><label>Or Create New Collection</label><input name='new_name' placeholder='{e(title)} Collection'><button>Add Movie</button></form></div>
  <div class='card'><h2>Add Movie To Playlist</h2><form method='post' action='/media/movies/add-to-playlist'><input type='hidden' name='token' value='{e(token)}'><input type='hidden' name='return_url' value='{e(return_url)}'><label>Existing Playlist</label><select name='playlist_id'><option value=''>— choose —</option>{playlist_opts}</select><label>Or Create New Playlist</label><input name='new_name' placeholder='Movie Night'><button>Add Movie</button></form><p class='muted small'>The movie is inserted as one exact playlist entry. Use the Playlist editor to move it up or down.</p></div>
 </div>
</div>"""
    return page_shell(title,body)


def tv_catalog_page() -> str:
    with db() as conn:
        local=conn.execute("""SELECT l.id library_id,l.name library,COALESCE(NULLIF(m.show_title,''),'(Unidentified TV)') show_title,
               COUNT(*) episodes,COUNT(DISTINCT m.season_number) seasons,MAX(m.original_network) network,MAX(m.show_year) show_year
               FROM media m JOIN libraries l ON l.id=m.library_id WHERE m.show_title IS NOT NULL AND m.show_title<>''
               AND lower(replace(l.name,' ','')) NOT LIKE '%youtube%' AND lower(l.name) NOT LIKE '%music videos%' AND lower(l.name) NOT LIKE '%game shows%'
               GROUP BY l.id,m.show_title ORDER BY m.show_title LIMIT 2500""").fetchall()
        plex=conn.execute("""SELECT pl.id library_id,ps.name server,pl.title library,COALESCE(pm.show_rating_key,pm.show_title) show_key,pm.show_title,
               COUNT(*) episodes,COUNT(DISTINCT pm.season_number) seasons,MAX(pm.original_network) network,MAX(COALESCE(pm.show_year,pm.year)) show_year
               FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pm.media_type='episode' AND pm.show_title IS NOT NULL AND lower(replace(pl.title,' ','')) NOT LIKE '%youtube%'
               AND lower(pl.title) NOT LIKE '%music videos%' AND lower(pl.title) NOT LIKE '%game shows%'
               GROUP BY pl.id,COALESCE(pm.show_rating_key,pm.show_title),pm.show_title ORDER BY pm.show_title LIMIT 2500""").fetchall()
        external=conn.execute("""SELECT el.id library_id,ms.name server,ms.kind,el.name library,em.show_title,COUNT(*) episodes,
               COUNT(DISTINCT em.season_number) seasons,MAX(em.year) show_year
               FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id
               WHERE em.media_type='episode' AND em.show_title IS NOT NULL AND em.show_title<>'' AND el.enabled=1 AND ms.enabled=1
               GROUP BY el.id,em.show_title ORDER BY em.show_title LIMIT 2500""").fetchall()
    rows=''.join(f"<tr><td><a href='{e(_show_detail_url('local',x['library_id'],x['show_title'],x['show_title']))}'><b>{e(x['show_title'])}</b></a></td><td>Local</td><td>{e(x['library'])}</td><td>{e(x['network'] or '')}</td><td>{e(x['show_year'] or '')}</td><td>{x['seasons']}</td><td>{x['episodes']}</td></tr>" for x in local)
    rows+=''.join(f"<tr><td><a href='{e(_show_detail_url('plex',x['library_id'],x['show_title'],x['show_key']))}'><b>{e(x['show_title'])}</b></a></td><td>Plex</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{e(x['network'] or '')}</td><td>{e(x['show_year'] or '')}</td><td>{x['seasons']}</td><td>{x['episodes']}</td></tr>" for x in plex)
    rows+=''.join(f"<tr><td><a href='{e(_show_detail_url('external',x['library_id'],x['show_title'],x['show_title']))}'><b>{e(x['show_title'])}</b></a></td><td>{e(str(x['kind']).title())}</td><td>{e(x['server'])} / {e(x['library'])}</td><td></td><td>{e(x['show_year'] or '')}</td><td>{x['seasons']}</td><td>{x['episodes']}</td></tr>" for x in external)
    if not rows: rows="<tr><td colspan='7' class='empty'>No TV show metadata available yet.</td></tr>"
    body=_page_heading('TV Shows','Browse TV shows available to ViperTV. Click a show to see metadata or add the whole series to a Collection or Playlist.',"<a class='button' href='/channels/new'>Create Channel</a>")+f"<div class='card'><div class='table-wrap'><table><thead><tr><th>Show</th><th>Source</th><th>Library</th><th>Network</th><th>Year</th><th>Seasons</th><th>Episodes</th></tr></thead><tbody>{rows}</tbody></table></div></div>"
    return page_shell('TV Shows',body)


def movies_catalog_page() -> str:
    with db() as conn:
        local=conn.execute("""SELECT l.id library_id,l.name library,m.id media_id,m.title,m.year,m.duration
               FROM media m JOIN libraries l ON l.id=m.library_id
               WHERE (m.show_title IS NULL OR m.show_title='')
               AND lower(replace(l.name,' ','')) NOT LIKE '%youtube%'
               AND lower(l.name) NOT LIKE '%music videos%' AND lower(l.name) NOT LIKE '%game shows%'
               ORDER BY m.title COLLATE NOCASE LIMIT 3000""").fetchall()
        plex=conn.execute("""SELECT pl.id library_id,ps.name server,pl.title library,pm.rating_key,pm.title,
               pm.originally_available_at,pm.year,pm.duration
               FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pm.media_type='movie' AND lower(replace(pl.title,' ','')) NOT LIKE '%youtube%'
               AND lower(pl.title) NOT LIKE '%music videos%' AND lower(pl.title) NOT LIKE '%game shows%'
               ORDER BY pm.title COLLATE NOCASE LIMIT 3000""").fetchall()
        external=conn.execute("""SELECT el.id library_id,ms.name server,ms.kind,el.name library,em.external_id,em.title,em.year,em.duration
               FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id
               WHERE em.media_type='movie' AND el.enabled=1 AND ms.enabled=1
               AND lower(replace(el.name,' ','')) NOT LIKE '%youtube%'
               AND lower(el.name) NOT LIKE '%music videos%' AND lower(el.name) NOT LIKE '%game shows%'
               ORDER BY em.title COLLATE NOCASE LIMIT 3000""").fetchall()
    rows=''.join(f"<tr><td><a href='{e(_movie_detail_url('local',x['library_id'],str(x['media_id'])))}'><b>{e(x['title'])}</b></a></td><td>Local</td><td>{e(x['library'])}</td><td>{e(x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>" for x in local)
    rows+=''.join(f"<tr><td><a href='{e(_movie_detail_url('plex',x['library_id'],str(x['rating_key'])))}'><b>{e(x['title'])}</b></a></td><td>Plex</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{e(x['originally_available_at'] or x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>" for x in plex)
    rows+=''.join(f"<tr><td><a href='{e(_movie_detail_url('external',x['library_id'],str(x['external_id'])))}'><b>{e(x['title'])}</b></a></td><td>{e(str(x['kind']).title())}</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{e(x['year'] or '')}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>" for x in external)
    if not rows: rows="<tr><td colspan='5' class='empty'>No movie metadata available yet.</td></tr>"
    body=_page_heading('Movies','Browse movies available to ViperTV. Click a movie to see all imported metadata or add it directly to a Collection or Playlist.')+f"<div class='card'><div class='table-wrap'><table><thead><tr><th>Movie</th><th>Source</th><th>Library</th><th>Date / Year</th><th>Runtime</th></tr></thead><tbody>{rows}</tbody></table></div></div>"
    return page_shell('Movies',body)


def youtube_catalog_page() -> str:
    """Browse libraries whose name/title contains YouTube or You Tube as a distinct media category."""
    with db() as conn:
        local_libs = conn.execute(
            """SELECT l.id,l.name library,'Local' source,COUNT(m.id) items
               FROM libraries l LEFT JOIN media m ON m.library_id=l.id
               WHERE lower(replace(l.name,' ','')) LIKE '%youtube%'
               GROUP BY l.id,l.name ORDER BY l.name COLLATE NOCASE"""
        ).fetchall()
        plex_libs = conn.execute(
            """SELECT pl.id,pl.title library,ps.name source,COUNT(pm.id) items
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               LEFT JOIN plex_media pm ON pm.plex_library_id=pl.id
               WHERE pl.enabled=1 AND lower(replace(pl.title,' ','')) LIKE '%youtube%'
               GROUP BY pl.id,pl.title,ps.name ORDER BY pl.title COLLATE NOCASE"""
        ).fetchall()
        local_items = conn.execute(
            """SELECT l.name library,
                      COALESCE(NULLIF(m.episode_title,''),NULLIF(m.title,''),m.path) title,
                      COALESCE(NULLIF(m.show_title,''),'') creator,
                      m.duration duration
               FROM media m JOIN libraries l ON l.id=m.library_id
               WHERE lower(replace(l.name,' ','')) LIKE '%youtube%'
               ORDER BY title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()
        plex_items = conn.execute(
            """SELECT ps.name server,pl.title library,pm.title,
                      COALESCE(NULLIF(pm.show_title,''),'') creator,
                      pm.media_type,pm.duration
               FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
               JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1 AND lower(replace(pl.title,' ','')) LIKE '%youtube%'
               ORDER BY pm.title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()

    lib_rows = ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>{e(x['source'])}</td><td><span class='badge blue'>YouTube</span></td><td>{x['items']:,}</td></tr>"
        for x in local_libs
    )
    lib_rows += ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>Plex / {e(x['source'])}</td><td><span class='badge blue'>YouTube</span></td><td>{x['items']:,}</td></tr>"
        for x in plex_libs
    )
    if not lib_rows:
        lib_rows = "<tr><td colspan='4' class='empty'>No libraries with YouTube or You Tube in the title have been indexed or synced.</td></tr>"

    item_rows = ''.join(
        f"<tr><td>{e(x['title'])}</td><td>{e(x['creator'] or '')}</td><td>Local</td><td>{e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in local_items
    )
    item_rows += ''.join(
        f"<tr><td>{e(x['title'])}</td><td>{e(x['creator'] or '')}</td><td>Plex</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in plex_items
    )
    if not item_rows:
        item_rows = "<tr><td colspan='5' class='empty'>No YouTube media has been indexed yet.</td></tr>"

    total_shown = len(local_items) + len(plex_items)
    body = _page_heading(
        'YouTube',
        'Libraries with YouTube or You Tube in their title are automatically classified here instead of TV Shows or Movies.',
        "<a class='button' href='/channels/new'>Create Channel</a>",
    ) + f"""
<div class='card'><h2>YouTube Libraries</h2><div class='table-wrap'><table><thead><tr><th>Library</th><th>Source</th><th>Category</th><th>Items</th></tr></thead><tbody>{lib_rows}</tbody></table></div></div>
<div class='card'><div class='page-heading'><div><h2>Videos</h2><p>Showing up to 1,000 items per source to keep large libraries responsive.</p></div><span class='badge blue'>{total_shown:,} shown</span></div><div class='table-wrap'><table><thead><tr><th>Video</th><th>Show / Creator</th><th>Source</th><th>Library</th><th>Runtime</th></tr></thead><tbody>{item_rows}</tbody></table></div></div>"""
    return page_shell('YouTube', body)


def music_videos_catalog_page() -> str:
    """Browse libraries whose name/title contains Music Videos as a distinct media category."""
    with db() as conn:
        local_libs = conn.execute(
            """SELECT l.id,l.name library,'Local' source,COUNT(m.id) items
               FROM libraries l LEFT JOIN media m ON m.library_id=l.id
               WHERE lower(l.name) LIKE '%music videos%'
               GROUP BY l.id,l.name ORDER BY l.name COLLATE NOCASE"""
        ).fetchall()
        plex_libs = conn.execute(
            """SELECT pl.id,pl.title library,ps.name source,COUNT(pm.id) items
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               LEFT JOIN plex_media pm ON pm.plex_library_id=pl.id
               WHERE pl.enabled=1 AND lower(pl.title) LIKE '%music videos%'
               GROUP BY pl.id,pl.title,ps.name ORDER BY pl.title COLLATE NOCASE"""
        ).fetchall()
        local_items = conn.execute(
            """SELECT l.name library,
                      COALESCE(NULLIF(m.episode_title,''),NULLIF(m.title,''),m.path) title,
                      COALESCE(NULLIF(m.show_title,''),'') artist,
                      m.duration duration
               FROM media m JOIN libraries l ON l.id=m.library_id
               WHERE lower(l.name) LIKE '%music videos%'
               ORDER BY title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()
        plex_items = conn.execute(
            """SELECT ps.name server,pl.title library,pm.title,
                      COALESCE(NULLIF(pm.show_title,''),'') artist,
                      pm.media_type,pm.duration
               FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
               JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1 AND lower(pl.title) LIKE '%music videos%'
               ORDER BY pm.title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()

    lib_rows = ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>{e(x['source'])}</td><td><span class='badge blue'>Music Videos</span></td><td>{x['items']:,}</td></tr>"
        for x in local_libs
    )
    lib_rows += ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>Plex / {e(x['source'])}</td><td><span class='badge blue'>Music Videos</span></td><td>{x['items']:,}</td></tr>"
        for x in plex_libs
    )
    if not lib_rows:
        lib_rows = "<tr><td colspan='4' class='empty'>No libraries with Music Videos in the title have been indexed or synced.</td></tr>"

    item_rows = ''.join(
        f"<tr><td>{e(x['title'])}</td><td>{e(x['artist'] or '')}</td><td>Local</td><td>{e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in local_items
    )
    item_rows += ''.join(
        f"<tr><td>{e(x['title'])}</td><td>{e(x['artist'] or '')}</td><td>Plex</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in plex_items
    )
    if not item_rows:
        item_rows = "<tr><td colspan='5' class='empty'>No Music Videos media has been indexed yet.</td></tr>"

    total_shown = len(local_items) + len(plex_items)
    body = _page_heading(
        'Music Videos',
        'Libraries with Music Videos in their title are automatically classified here instead of TV Shows or Movies.',
        "<a class='button' href='/channels/new'>Create Channel</a>",
    ) + f"""
<div class='card'><h2>Music Video Libraries</h2><div class='table-wrap'><table><thead><tr><th>Library</th><th>Source</th><th>Category</th><th>Items</th></tr></thead><tbody>{lib_rows}</tbody></table></div></div>
<div class='card'><div class='page-heading'><div><h2>Videos</h2><p>Showing up to 1,000 items per source to keep large libraries responsive.</p></div><span class='badge blue'>{total_shown:,} shown</span></div><div class='table-wrap'><table><thead><tr><th>Video</th><th>Artist / Show</th><th>Source</th><th>Library</th><th>Runtime</th></tr></thead><tbody>{item_rows}</tbody></table></div></div>"""
    return page_shell('Music Videos', body)


def game_shows_catalog_page() -> str:
    """Browse libraries whose name/title contains Game Shows as a distinct media category."""
    with db() as conn:
        local_libs = conn.execute(
            """SELECT l.id,l.name library,'Local' source,COUNT(m.id) items
               FROM libraries l LEFT JOIN media m ON m.library_id=l.id
               WHERE lower(l.name) LIKE '%game shows%'
               GROUP BY l.id,l.name ORDER BY l.name COLLATE NOCASE"""
        ).fetchall()
        plex_libs = conn.execute(
            """SELECT pl.id,pl.title library,ps.name source,COUNT(pm.id) items
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               LEFT JOIN plex_media pm ON pm.plex_library_id=pl.id
               WHERE pl.enabled=1 AND lower(pl.title) LIKE '%game shows%'
               GROUP BY pl.id,pl.title,ps.name ORDER BY pl.title COLLATE NOCASE"""
        ).fetchall()
        local_items = conn.execute(
            """SELECT l.name library,
                      COALESCE(NULLIF(m.episode_title,''),NULLIF(m.title,''),m.path) title,
                      COALESCE(NULLIF(m.show_title,''),'') show_title,
                      m.season_number,m.episode_number,m.duration
               FROM media m JOIN libraries l ON l.id=m.library_id
               WHERE lower(l.name) LIKE '%game shows%'
               ORDER BY COALESCE(NULLIF(m.show_title,''),m.title) COLLATE NOCASE,m.season_number,m.episode_number,m.title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()
        plex_items = conn.execute(
            """SELECT ps.name server,pl.title library,pm.title,
                      COALESCE(NULLIF(pm.show_title,''),'') show_title,
                      pm.season_number,pm.episode_number,pm.media_type,pm.duration
               FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
               JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.enabled=1 AND lower(pl.title) LIKE '%game shows%'
               ORDER BY COALESCE(NULLIF(pm.show_title,''),pm.title) COLLATE NOCASE,pm.season_number,pm.episode_number,pm.title COLLATE NOCASE LIMIT 1000"""
        ).fetchall()

    lib_rows = ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>{e(x['source'])}</td><td><span class='badge blue'>Game Shows</span></td><td>{x['items']:,}</td></tr>"
        for x in local_libs
    )
    lib_rows += ''.join(
        f"<tr><td><b>{e(x['library'])}</b></td><td>Plex / {e(x['source'])}</td><td><span class='badge blue'>Game Shows</span></td><td>{x['items']:,}</td></tr>"
        for x in plex_libs
    )
    if not lib_rows:
        lib_rows = "<tr><td colspan='4' class='empty'>No libraries with Game Shows in the title have been indexed or synced.</td></tr>"

    def ep_label(row):
        season = row['season_number']
        episode = row['episode_number']
        if season is not None and episode is not None:
            return f"S{int(season):02d}E{int(episode):02d}"
        return ''

    item_rows = ''.join(
        f"<tr><td>{e(x['show_title'] or x['title'])}</td><td>{e(ep_label(x))}</td><td>{e(x['title'])}</td><td>Local</td><td>{e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in local_items
    )
    item_rows += ''.join(
        f"<tr><td>{e(x['show_title'] or x['title'])}</td><td>{e(ep_label(x))}</td><td>{e(x['title'])}</td><td>Plex</td><td>{e(x['server'])} / {e(x['library'])}</td><td>{int((x['duration'] or 0)/60)} min</td></tr>"
        for x in plex_items
    )
    if not item_rows:
        item_rows = "<tr><td colspan='6' class='empty'>No Game Shows media has been indexed yet.</td></tr>"

    total_shown = len(local_items) + len(plex_items)
    body = _page_heading(
        'Game Shows',
        'Libraries with Game Shows in their title are automatically classified here instead of TV Shows or Movies.',
        "<a class='button' href='/channels/new'>Create Channel</a>",
    ) + f"""
<div class='card'><h2>Game Show Libraries</h2><div class='table-wrap'><table><thead><tr><th>Library</th><th>Source</th><th>Category</th><th>Items</th></tr></thead><tbody>{lib_rows}</tbody></table></div></div>
<div class='card'><div class='page-heading'><div><h2>Episodes</h2><p>Showing up to 1,000 items per source to keep large libraries responsive.</p></div><span class='badge blue'>{total_shown:,} shown</span></div><div class='table-wrap'><table><thead><tr><th>Game Show</th><th>Episode</th><th>Title</th><th>Source</th><th>Library</th><th>Runtime</th></tr></thead><tbody>{item_rows}</tbody></table></div></div>"""
    return page_shell('Game Shows', body)


def _next_clone_channel_number(conn: sqlite3.Connection, source_number: str) -> int:
    """Suggest the next unused whole channel number after the source channel."""
    try:
        candidate = int(float(str(source_number))) + 1
    except Exception:
        candidate = 1
    candidate = max(1, candidate)
    while conn.execute("SELECT 1 FROM channels WHERE number=?", (str(candidate),)).fetchone():
        candidate += 1
    return candidate


def _copy_channel_configuration(conn: sqlite3.Connection, source_id: int, number: str, name: str) -> int:
    """Clone a channel while intentionally starting with fresh playout state.

    Keeping playout_state empty is important: two shuffled clones should not share a
    cursor. The channel id is part of ViperTV's stable-shuffle seed, so every clone
    naturally receives a different deterministic episode order.
    """
    c = conn.execute("SELECT * FROM channels WHERE id=?", (source_id,)).fetchone()
    if not c:
        raise ValueError("Source channel no longer exists")
    cur = conn.execute(
        """INSERT INTO channels(
            number,name,library_id,shuffle,enabled,created_at,logo_path,watermark_enabled,
            subtitle_mode,offline_media,stream_profile,stream_mode,video_bitrate,resolution,frame_rate
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(number), name, c['library_id'], c['shuffle'], c['enabled'], utcnow_iso(),
            c['logo_path'], c['watermark_enabled'], c['subtitle_mode'], c['offline_media'],
            c['stream_profile'], c['stream_mode'], c['video_bitrate'], c['resolution'], c['frame_rate']
        )
    )
    new_id = int(cur.lastrowid)

    for r in conn.execute("SELECT * FROM channel_selections WHERE channel_id=? ORDER BY id", (source_id,)):
        conn.execute(
            """INSERT INTO channel_selections(
                channel_id,source_type,library_id,plex_library_id,selection_type,
                show_key,show_title,season_number,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""",
            (new_id,r['source_type'],r['library_id'],r['plex_library_id'],r['selection_type'],
             r['show_key'],r['show_title'],r['season_number'],utcnow_iso())
        )

    people_filter = conn.execute("SELECT * FROM channel_people_filters WHERE channel_id=?", (source_id,)).fetchone()
    if people_filter:
        conn.execute("""INSERT INTO channel_people_filters(channel_id,actors_json,directors_json,air_year_start,air_year_end,created_at,updated_at)
                      VALUES(?,?,?,?,?,?,?)""",
                     (new_id,people_filter['actors_json'],people_filter['directors_json'],people_filter['air_year_start'],people_filter['air_year_end'],utcnow_iso(),utcnow_iso()))

    for r in conn.execute("SELECT collection_id FROM channel_collections WHERE channel_id=?", (source_id,)):
        conn.execute("INSERT OR IGNORE INTO channel_collections(channel_id,collection_id) VALUES(?,?)", (new_id,r['collection_id']))

    for r in conn.execute("SELECT filler_id FROM channel_fillers WHERE channel_id=?", (source_id,)):
        conn.execute("INSERT OR REPLACE INTO channel_fillers(channel_id,filler_id) VALUES(?,?)", (new_id,r['filler_id']))

    for r in conn.execute("SELECT library_id,show_title,season_number FROM external_channel_selections WHERE channel_id=?", (source_id,)):
        conn.execute(
            "INSERT INTO external_channel_selections(channel_id,library_id,show_title,season_number) VALUES(?,?,?,?)",
            (new_id,r['library_id'],r['show_title'],r['season_number'])
        )

    # Copy schedules and their items. A schedule item that explicitly points back to
    # its own source channel is remapped to the clone; references to other channels
    # remain unchanged.
    for schedule in conn.execute("SELECT * FROM schedules WHERE channel_id=? ORDER BY id", (source_id,)):
        new_schedule_id = conn.execute(
            "INSERT INTO schedules(channel_id,name,enabled,created_at) VALUES(?,?,?,?)",
            (new_id,schedule['name'],schedule['enabled'],utcnow_iso())
        ).lastrowid
        for item in conn.execute("SELECT * FROM schedule_items WHERE schedule_id=? ORDER BY position,id", (schedule['id'],)):
            source_ref = item['source_id']
            if item['source_type'] == 'channel' and source_ref == source_id:
                source_ref = new_id
            conn.execute(
                """INSERT INTO schedule_items(
                    schedule_id,day_mask,start_minute,end_minute,source_type,source_id,mode,
                    play_count,pad_to_minutes,position,label
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (new_schedule_id,item['day_mask'],item['start_minute'],item['end_minute'],
                 item['source_type'],source_ref,item['mode'],item['play_count'],
                 item['pad_to_minutes'],item['position'],item['label'])
            )

    # Deliberately do NOT copy playout_state. Each clone starts independently.
    return new_id


def channels_page(msg: str = "") -> str:
    with db() as conn:
        channels = conn.execute("SELECT * FROM channels ORDER BY CAST(number AS REAL),number").fetchall()
    rows = ''.join(
        f"<tr><td><input class='channel-check' form='bulk-delete-form' type='checkbox' name='channel_ids' value='{c['id']}' aria-label='Select {e(c['number'])} {e(c['name'])}'></td>"
        f"<td><b>{e(c['number'])}</b></td><td>{e(c['name'])}</td><td>{e(c['stream_mode'])}</td><td>{e(c['stream_profile'])}</td><td>{'Enabled' if c['enabled'] else 'Disabled'}</td>"
        f"<td class='nowrap'><a class='button secondary' href='/channels/{c['id']}/edit'>Edit</a> <a class='button secondary' href='/channels/{c['id']}/clone'>Clone</a> <a class='button secondary' href='/studio/channel/{c['id']}'>Schedule</a> <a class='button' href='/watch/channel/{quote(str(c['number']),safe='')}'>Watch</a> "
        f"<form class='inline' method='post' action='/channels/{c['id']}/delete' onsubmit='return confirm(&quot;Delete this ViperTV channel? Its source libraries and media files will not be changed.&quot;);'><button class='danger' type='submit'>Delete</button></form></td></tr>"
        for c in channels
    ) or "<tr><td colspan='7' class='empty'>No channels configured.</td></tr>"
    notice = f"<div class='msg'>{e(msg)}</div>" if msg else ''
    actions = "<button id='delete-selected' class='danger' type='submit' form='bulk-delete-form' disabled>Delete Selected</button> <a class='button secondary' href='/channels/auto'>Channel Builder</a> <a class='button' href='/channels/new'>Add Channel</a>"
    body = notice + _page_heading('Channels','Create, clone, bulk-delete and configure virtual channels.', actions) + f"""
<form id='bulk-delete-form' method='post' action='/channels/delete-selected' onsubmit="return confirm('Delete the selected ViperTV channels? Source libraries and media files will not be changed.');"></form>
<div class='card'>
  <div class='toolbar' style='justify-content:space-between'>
    <div><label style='margin:0'><input id='select-all-channels' type='checkbox'> Select all channels</label> <span id='selected-channel-count' class='muted small'>0 selected</span></div>
    <span class='badge blue'>{len(channels)} channel{'s' if len(channels) != 1 else ''}</span>
  </div>
  <div class='table-wrap'><table><thead><tr><th style='width:34px'></th><th>#</th><th>Name</th><th>Streaming Mode</th><th>Profile</th><th>Status</th><th>Actions</th></tr></thead><tbody>{rows}</tbody></table></div>
</div>
{pluto_channels_card()}
{live_stream_channels_card()}
<div class='card' style='border-color:#6d3438'>
  <div class='page-heading'><div><h2>Danger Zone</h2><p>Erase every ViperTV channel and its schedules/playout state so you can start over. Libraries, Plex metadata, collections, media files and backups are kept.</p></div></div>
  <form method='post' action='/channels/reset-all' onsubmit="return confirm('RESET ALL CHANNELS? This will delete every ViperTV channel.') && confirm('Are you absolutely sure? A backup will be made first, but all current channels and schedules will be removed.');">
    <button class='danger' type='submit' {'disabled' if not channels else ''}>Reset All Channels</button>
  </form>
</div>
"""
    script = r"""<script>
const boxes=[...document.querySelectorAll('.channel-check')];
const all=document.getElementById('select-all-channels');
const del=document.getElementById('delete-selected');
const count=document.getElementById('selected-channel-count');
function updateChannelSelection(){
  const n=boxes.filter(x=>x.checked).length;
  if(count) count.textContent=n+' selected';
  if(del) del.disabled=n===0;
  if(all){ all.checked=boxes.length>0 && n===boxes.length; all.indeterminate=n>0 && n<boxes.length; }
}
all?.addEventListener('change',()=>{boxes.forEach(x=>x.checked=all.checked);updateChannelSelection();});
boxes.forEach(x=>x.addEventListener('change',updateChannelSelection));
updateChannelSelection();
</script>"""
    return page_shell('Channels', body, extra_script=script)


def clone_channel_page(channel_id: int, msg: str = "") -> str:
    with db() as conn:
        c = conn.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
        if not c:
            raise HTTPException(404, "Channel not found")
        suggested = _next_clone_channel_number(conn, c['number'])
    notice = f"<div class='msg'>{e(msg)}</div>" if msg else ''
    shuffle_note = (
        "<div class='msg'>This channel uses shuffle. Every clone gets its own stable shuffle order and independent playout state, so the clones are designed to be on different episodes.</div>"
        if c['shuffle'] else
        "<div class='muted small'>The clones will preserve this channel's sequential playback setting. You can change individual clones afterward.</div>"
    )
    body = notice + _page_heading(
        'Clone Channel',
        f"Create independent copies of {e(c['number'])} {e(c['name'])}.",
        "<a class='button secondary' href='/channels'>Back to Channels</a>"
    ) + f"""
<div class='card'>
  <h2>Clone {e(c['name'])}</h2>
  <p>The clone copies media/show/season selections, collections, filler, schedule, streaming profile, logo and presentation settings. Runtime playout position is reset so each copy runs independently.</p>
  {shuffle_note}
  <form method='post' action='/channels/{channel_id}/clone'>
    <div class='grid3'>
      <div><label>Number of clones</label><input type='number' name='copies' min='1' max='20' value='3' required><div class='muted small'>Create 1–20 copies in one operation.</div></div>
      <div><label>First channel number</label><input type='number' name='first_number' min='1' value='{suggested}' required></div>
      <div><label>Channel number increment</label><input type='number' name='number_step' min='1' value='1' required></div>
    </div>
    <div class='grid'>
      <div><label>Clone name base</label><input name='name_base' value='{e(c['name'])}' required><div class='muted small'>Example: Frasier creates Frasier 2, Frasier 3, Frasier 4...</div></div>
      <div><label>First name suffix</label><input type='number' name='name_start' min='1' value='2' required></div>
    </div>
    <button>Clone Channel</button>
  </form>
</div>
"""
    return page_shell('Clone Channel', body)


def auto_channel_show_catalog() -> list[dict[str, Any]]:
    """Return one row per TV show, with overrides applied."""
    rows: list[dict[str, Any]] = []
    with db() as conn:
        local = conn.execute("""SELECT m.library_id,l.name AS library_name,m.show_title AS show_title,
             COALESCE(MAX(NULLIF(m.original_network,'')),'') AS original_network,
             MAX(m.show_year) AS show_year,COUNT(*) AS episodes
             FROM media m JOIN libraries l ON l.id=m.library_id
             WHERE m.show_title IS NOT NULL AND m.show_title<>''
             GROUP BY m.library_id,m.show_title""").fetchall()
        plex = conn.execute("""SELECT pm.plex_library_id AS library_id,pl.title AS library_name,ps.name AS server_name,
             COALESCE(NULLIF(pm.show_rating_key,''),pm.show_title) AS show_key,pm.show_title AS show_title,
             COALESCE(MAX(NULLIF(pm.original_network,'')),'') AS original_network,
             MAX(pm.show_year) AS show_year,COUNT(*) AS episodes
             FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
             JOIN plex_servers ps ON ps.id=pl.server_id
             WHERE pl.enabled=1 AND pm.media_type='episode' AND pm.show_title IS NOT NULL AND pm.show_title<>''
             GROUP BY pm.plex_library_id,COALESCE(NULLIF(pm.show_rating_key,''),pm.show_title),pm.show_title""").fetchall()
        overrides = {
            (r['source_type'], int(r['library_id']), str(r['show_key'])): r
            for r in conn.execute("SELECT * FROM show_metadata_overrides")
        }
        tvdb_meta = {
            (r['source_type'], int(r['library_id']), str(r['show_key'])): r
            for r in conn.execute("SELECT * FROM tvdb_show_metadata")
        }
    for r in local:
        key = ('local', int(r['library_id']), str(r['show_title']))
        o = overrides.get(key); t = tvdb_meta.get(key)
        network = (o['original_network'] if o and o['original_network'] is not None else (t['original_network'] if t and t['original_network'] else r['original_network'])) or ''
        show_year = (o['show_year'] if o and o['show_year'] is not None else (t['show_year'] if t and t['show_year'] else r['show_year']))
        source = 'Manual' if o and (o['original_network'] is not None or o['show_year'] is not None) else ('TheTVDB' if t and (t['original_network'] or t['show_year']) else 'Local')
        rows.append({
            'source_type':'local','library_id':int(r['library_id']),'library_name':r['library_name'],
            'server_name':'','show_key':str(r['show_title']),'show_title':r['show_title'],
            'original_network':network,'show_year':show_year,'metadata_source':source,
            'tvdb_id':(t['tvdb_id'] if t else None),'episodes':int(r['episodes'] or 0),
        })
    for r in plex:
        key = ('plex', int(r['library_id']), str(r['show_key']))
        o = overrides.get(key); t = tvdb_meta.get(key)
        network = (o['original_network'] if o and o['original_network'] is not None else (t['original_network'] if t and t['original_network'] else r['original_network'])) or ''
        show_year = (o['show_year'] if o and o['show_year'] is not None else (t['show_year'] if t and t['show_year'] else r['show_year']))
        source = 'Manual' if o and (o['original_network'] is not None or o['show_year'] is not None) else ('TheTVDB' if t and (t['original_network'] or t['show_year']) else 'Plex')
        rows.append({
            'source_type':'plex','library_id':int(r['library_id']),'library_name':r['library_name'],
            'server_name':r['server_name'],'show_key':str(r['show_key']),'show_title':r['show_title'],
            'original_network':network,'show_year':show_year,'metadata_source':source,
            'tvdb_id':(t['tvdb_id'] if t else None),'episodes':int(r['episodes'] or 0),
        })
    rows.sort(key=lambda x: (str(x['show_title']).casefold(), x['source_type'], str(x['library_name']).casefold()))
    return rows


def _auto_source_matches(show: dict[str, Any], source_library: str) -> bool:
    if not source_library or source_library == 'all':
        return True
    try:
        st, sid = source_library.split(':',1)
        return show['source_type'] == st and int(show['library_id']) == int(sid)
    except Exception:
        return False


def filtered_auto_channel_shows(source_library: str='all', network: str='', year_start: int | None=None, year_end: int | None=None) -> list[dict[str, Any]]:
    network_cf = network.strip().casefold()
    result = []
    for show in auto_channel_show_catalog():
        if not _auto_source_matches(show, source_library):
            continue
        if network_cf and str(show.get('original_network') or '').strip().casefold() != network_cf:
            continue
        y = safe_int(show.get('show_year'))
        if year_start is not None and (y is None or y < year_start):
            continue
        if year_end is not None and (y is None or y > year_end):
            continue
        result.append(show)
    return result


def channel_auto_builder_page(msg: str='') -> str:
    shows = auto_channel_show_catalog()
    people = people_catalog_rows('', 2000)
    networks: dict[str, set[tuple[str,int,str]]] = {}
    years: dict[int, set[tuple[str,int,str]]] = {}
    for x in shows:
        ident=(x['source_type'],x['library_id'],x['show_key'])
        if x['original_network']:
            networks.setdefault(str(x['original_network']),set()).add(ident)
        if x['show_year']:
            years.setdefault(int(x['show_year']),set()).add(ident)
    with db() as conn:
        local_libs=conn.execute("SELECT id,name FROM libraries ORDER BY name COLLATE NOCASE").fetchall()
        plex_libs=conn.execute("""SELECT pl.id,pl.title,ps.name server_name FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
                                  WHERE pl.enabled=1 AND pl.library_type='show' ORDER BY ps.name,pl.title""").fetchall()
    source_opts=["<option value='all'>All TV libraries</option>"]
    source_opts += [f"<option value='local:{x['id']}'>Local / {e(x['name'])}</option>" for x in local_libs]
    source_opts += [f"<option value='plex:{x['id']}'>Plex / {e(x['server_name'])} / {e(x['title'])}</option>" for x in plex_libs]
    network_opts="<option value=''>Any network</option>"+''.join(f"<option value='{e(n)}'>{e(n)} ({len(ids)} shows)</option>" for n,ids in sorted(networks.items(),key=lambda kv:kv[0].casefold()))
    actor_opts="<option value=''>Any actor</option>"+''.join(f"<option value='{e(x['person_name'])}'>{e(x['person_name'])}</option>" for x in people if x.get('is_actor'))
    director_opts="<option value=''>Any director</option>"+''.join(f"<option value='{e(x['person_name'])}'>{e(x['person_name'])}</option>" for x in people if x.get('is_director'))
    network_rows=''.join(f"<tr><td><b>{e(n)}</b></td><td>{len(ids)}</td><td><button type='button' class='secondary use-network' data-network='{e(n)}'>Use</button></td></tr>" for n,ids in sorted(networks.items(),key=lambda kv:(-len(kv[1]),kv[0].casefold()))) or "<tr><td colspan='3' class='empty'>No original-network metadata yet. Re-sync Plex TV libraries, or add an override below.</td></tr>"
    year_rows=''.join(f"<tr><td><b>{y}</b></td><td>{len(years[y])}</td><td><button type='button' class='secondary use-year' data-year='{y}'>Use</button></td></tr>" for y in sorted(years,reverse=True)) or "<tr><td colspan='3' class='empty'>No show premiere-year metadata yet.</td></tr>"
    show_options=''.join(
        f"<option value='{encode_selection({'source_type':x['source_type'],'library_id':x['library_id'],'show_key':x['show_key'],'show_title':x['show_title']})}'>"
        f"{e(x['show_title'])} — {e(x['original_network'] or 'Unknown network')} — {e(x['show_year'] or 'Unknown year')} — {e(('Plex / '+x['server_name']+' / ') if x['source_type']=='plex' else 'Local / ')}{e(x['library_name'])}</option>"
        for x in shows
    )
    known_network=sum(1 for x in shows if x['original_network']); known_year=sum(1 for x in shows if x['show_year'])
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('Channel Builder','Automatically build TV channels from network, actor/director and year metadata.',"<a class='button secondary' href='/channels'>Back to Channels</a>")+f"""
<div class='stats'>
 <div class='stat'><div class='stat-label'>TV Shows</div><div class='stat-value'>{len(shows):,}</div></div>
 <div class='stat'><div class='stat-label'>With Network</div><div class='stat-value'>{known_network:,}</div></div>
 <div class='stat'><div class='stat-label'>With Premiere Year</div><div class='stat-value'>{known_year:,}</div></div>
 <div class='stat'><div class='stat-label'>Networks Found</div><div class='stat-value'>{len(networks):,}</div></div>
</div>
<div class='card'><h2>Create Filtered Channel</h2>
<p>Create a channel from network, actor/director, year or any combination. With a person selected, the year range applies to <b>episode air year</b>; otherwise it applies to the show's premiere year. Example: <b>John Ritter + 1980–1989</b>.</p>
<form method='post' action='/channels/auto/create'>
 <div class='grid3'><div><label>Channel Number</label><input name='number' required placeholder='25'></div><div><label>Channel Name</label><input name='name' required placeholder='NBC Classics'></div><div><label>Source Library</label><select name='source_library'>{''.join(source_opts)}</select></div></div>
 <div class='grid3'><div><label>Original Network</label><select id='auto-network' name='network'>{network_opts}</select></div><div><label>Start Year</label><input id='auto-year-start' type='number' min='1900' max='2100' name='year_start' placeholder='1980'></div><div><label>End Year</label><input id='auto-year-end' type='number' min='1900' max='2100' name='year_end' placeholder='1989'></div></div>
 <div class='grid'><div><label>Actor</label><select name='actor'>{actor_opts}</select></div><div><label>Director</label><select name='director'>{director_opts}</select></div></div>
 <label><input type='checkbox' name='shuffle' value='1' checked> Shuffle matched shows/episodes</label><br><br><button>Create Channel From Filters</button>
</form></div>
<div class='grid'><div class='card'><h2>Original Networks</h2><p class='muted small'>Counts are distinct shows, not episodes.</p><div class='table-wrap' style='max-height:430px'><table><thead><tr><th>Network</th><th>Shows</th><th></th></tr></thead><tbody>{network_rows}</tbody></table></div></div>
<div class='card'><h2>Premiere Years</h2><p class='muted small'>Use a year to build a channel from shows that premiered that year.</p><div class='table-wrap' style='max-height:430px'><table><thead><tr><th>Year</th><th>Shows</th><th></th></tr></thead><tbody>{year_rows}</tbody></table></div></div></div>
<div class='card'><h2>Correct / Add Show Metadata</h2><p>If Plex or a local NFO is missing the original network or premiere year, add a ViperTV override here. Overrides survive channel creation and future source syncs.</p>
<form method='post' action='/channels/auto/metadata'><label>Show</label><select name='show_token' required>{show_options}</select><div class='grid'><div><label>Original Network</label><input name='original_network' placeholder='NBC, ABC, CBS, FOX...'></div><div><label>Premiere Year</label><input type='number' min='1900' max='2100' name='show_year' placeholder='1993'></div></div><button>Save Metadata Override</button> <span class='muted small'>Leave both fields blank to remove an existing override.</span></form></div>
<div class='card'><h2>Metadata Source</h2><p class='muted'>Original network and premiere year use <b>Manual override → TheTVDB → Plex/local fallback</b>. Actors/directors come from <b>Plex cast/director metadata</b> and local <code>tvshow.nfo</code>/sidecar NFO files. Run Plex Sync Metadata once after upgrading to populate the People index. <a href='/media/people'>Browse People</a>.</p></div>
"""
    script=r"""<script>
document.querySelectorAll('.use-network').forEach(b=>b.addEventListener('click',()=>{const s=document.getElementById('auto-network');if(s){s.value=b.dataset.network;window.scrollTo({top:0,behavior:'smooth'});}}));
document.querySelectorAll('.use-year').forEach(b=>b.addEventListener('click',()=>{const y=b.dataset.year;document.getElementById('auto-year-start').value=y;document.getElementById('auto-year-end').value=y;window.scrollTo({top:0,behavior:'smooth'});}));
</script>"""
    return page_shell('Channel Builder',body,extra_script=script)



def _ai_normalize(value: str) -> str:
    text = (value or '').casefold().replace('&', ' and ')
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def people_catalog_rows(query: str = '', limit: int = 500) -> list[dict[str, Any]]:
    qn = _person_norm(query)
    where = ''
    params: list[Any] = []
    if qn:
        where = 'WHERE person_name_norm LIKE ?'
        params.append('%' + qn + '%')
    params.append(max(1,min(int(limit),2000)))
    with db() as conn:
        rows = conn.execute(f"""SELECT person_name_norm,MIN(person_name) person_name,MIN(id) person_credit_id,
            MAX(CASE WHEN credit_type='actor' THEN 1 ELSE 0 END) is_actor,
            MAX(CASE WHEN credit_type='director' THEN 1 ELSE 0 END) is_director,
            COUNT(DISTINCT CASE WHEN show_key IS NOT NULL AND show_key<>''
                THEN source_type||':'||library_id||':'||show_key
                ELSE source_type||':'||library_id||':'||media_type||':'||media_key END) title_count,
            COUNT(*) credit_count
          FROM people_credits {where}
          GROUP BY person_name_norm
          ORDER BY person_name COLLATE NOCASE LIMIT ?""", params).fetchall()
    return [dict(r) for r in rows]


def _known_people_lookup() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with db() as conn:
        for r in conn.execute("""SELECT person_name_norm,MIN(person_name) person_name,
              MAX(CASE WHEN credit_type='actor' THEN 1 ELSE 0 END) is_actor,
              MAX(CASE WHEN credit_type='director' THEN 1 ELSE 0 END) is_director
              FROM people_credits GROUP BY person_name_norm"""):
            out[str(r['person_name_norm'])] = {'name':str(r['person_name']),'actor':bool(r['is_actor']),'director':bool(r['is_director'])}
    return out


def _people_scope_sets(actors: list[str], directors: list[str]) -> tuple[dict[str,dict[str,set[tuple[Any,...]]]],dict[str,dict[str,set[tuple[Any,...]]]],dict[str,dict[str,set[tuple[Any,...]]]]]:
    """Build series, exact-item and exact-episode-show scopes for people filters.

    The third map is important for guest stars/directors.  Plex can expose a
    person at both series level and on one or more exact episodes.  Once exact
    episode credits exist for that person/show, ViperTV must not treat the
    series-level credit as proof that they appear in every episode.
    """
    actor_norms=[_person_norm(x) for x in actors if _person_norm(x)]
    director_norms=[_person_norm(x) for x in directors if _person_norm(x)]
    wanted=sorted(set(actor_norms+director_norms))
    show_sets={'actor':{n:set() for n in actor_norms},'director':{n:set() for n in director_norms}}
    item_sets={'actor':{n:set() for n in actor_norms},'director':{n:set() for n in director_norms}}
    exact_episode_show_sets={'actor':{n:set() for n in actor_norms},'director':{n:set() for n in director_norms}}
    if not wanted:
        return show_sets,item_sets,exact_episode_show_sets
    marks=','.join('?' for _ in wanted)
    with db() as conn:
        rows=conn.execute(f"SELECT * FROM people_credits WHERE person_name_norm IN ({marks})", wanted).fetchall()
    for r in rows:
        ct=str(r['credit_type'])
        norm=str(r['person_name_norm'])
        if ct not in show_sets or norm not in show_sets[ct]:
            continue
        st=str(r['source_type']); lib=int(r['library_id']); mt=str(r['media_type']); mk=str(r['media_key'])
        sk=str(r['show_key'] or '')
        if mt=='show':
            show_sets[ct][norm].add((st,lib,sk or mk))
        else:
            item_sets[ct][norm].add((st,lib,mt,mk))
            if mt=='episode' and sk:
                exact_episode_show_sets[ct][norm].add((st,lib,sk))
    return show_sets,item_sets,exact_episode_show_sets

def _item_people_identity(item: dict[str,Any]) -> tuple[tuple[str,int,str] | None, tuple[str,int,str,str] | None]:
    st=str(item.get('source_type') or '')
    mt=str(item.get('media_type') or ('episode' if item.get('show_title') else 'movie'))
    if st=='local':
        lib=safe_int(item.get('library_id'))
        mk=str(item.get('id') or '').strip()
        sk=str(item.get('show_title') or '').strip()
    elif st=='plex':
        lib=safe_int(item.get('plex_library_id'))
        mk=str(item.get('rating_key') or '').strip()
        sk=str(item.get('show_rating_key') or item.get('show_key') or '').strip()
    else:
        return None,None
    if lib is None or not mk:
        return None,None
    show_ident=(st,int(lib),sk) if sk else None
    media_ident=(st,int(lib),mt,mk)
    return show_ident,media_ident


def _item_air_year(item: dict[str,Any]) -> int | None:
    for key in ('air_date','originally_available_at'):
        value=str(item.get(key) or '')
        if re.match(r'^\d{4}',value):
            return int(value[:4])
    return safe_int(item.get('year'))


def _item_matches_people(item: dict[str,Any], actors: list[str], directors: list[str],
                         show_sets: dict[str,dict[str,set[tuple[Any,...]]]],
                         item_sets: dict[str,dict[str,set[tuple[Any,...]]]],
                         exact_episode_show_sets: dict[str,dict[str,set[tuple[Any,...]]]]) -> bool:
    show_ident,media_ident=_item_people_identity(item)
    if media_ident is None:
        return False
    media_type=str(media_ident[2])
    for credit_type,names in (('actor',actors),('director',directors)):
        for name in names:
            norm=_person_norm(name)
            if not norm:
                continue
            in_show=show_ident is not None and show_ident in show_sets.get(credit_type,{}).get(norm,set())
            in_item=media_ident in item_sets.get(credit_type,{}).get(norm,set())
            # If Plex/NFO supplied any exact episode credit for this person in
            # this show, exact episode metadata wins over broad series cast.
            # This prevents a guest star (e.g. one M*A*S*H appearance) from
            # accidentally matching the entire series.
            if media_type=='episode' and show_ident is not None:
                has_exact_for_show=show_ident in exact_episode_show_sets.get(credit_type,{}).get(norm,set())
                matched=in_item if has_exact_for_show else (in_item or in_show)
            else:
                matched=in_item or in_show
            if not matched:
                return False
    return True

def people_episode_match_counts(actors: list[str], directors: list[str], year_start: int | None=None, year_end: int | None=None) -> dict[tuple[str,int,str],int]:
    """Return exact TV episode counts matching people + episode air-year filters."""
    if not actors and not directors:
        return {}
    show_sets,item_sets,exact_episode_show_sets=_people_scope_sets(actors,directors)
    counts: dict[tuple[str,int,str],int] = {}
    with db() as conn:
        local=conn.execute("SELECT id,library_id,show_title,year FROM media WHERE duration>0 AND show_title IS NOT NULL AND show_title<>''").fetchall()
        plex=conn.execute("SELECT rating_key,plex_library_id,show_rating_key,show_title,originally_available_at,year FROM plex_media WHERE duration>0 AND media_type='episode' AND show_title IS NOT NULL AND show_title<>''").fetchall()
    for r in local:
        item={'source_type':'local','media_type':'episode','id':r['id'],'library_id':r['library_id'],'show_title':r['show_title'],'year':r['year']}
        if not _item_matches_people(item,actors,directors,show_sets,item_sets,exact_episode_show_sets):
            continue
        y=_item_air_year(item)
        if year_start is not None and (y is None or y<year_start):
            continue
        if year_end is not None and (y is None or y>year_end):
            continue
        key=('local',int(r['library_id']),str(r['show_title']))
        counts[key]=counts.get(key,0)+1
    for r in plex:
        show_key=str(r['show_rating_key'] or r['show_title'])
        item={'source_type':'plex','media_type':'episode','rating_key':r['rating_key'],'plex_library_id':r['plex_library_id'],
              'show_rating_key':show_key,'show_title':r['show_title'],'air_date':r['originally_available_at'],'year':r['year']}
        if not _item_matches_people(item,actors,directors,show_sets,item_sets,exact_episode_show_sets):
            continue
        y=_item_air_year(item)
        if year_start is not None and (y is None or y<year_start):
            continue
        if year_end is not None and (y is None or y>year_end):
            continue
        key=('plex',int(r['plex_library_id']),show_key)
        counts[key]=counts.get(key,0)+1
    return counts


def _apply_channel_people_filter(channel_id: int, items: list[dict[str,Any]]) -> list[dict[str,Any]]:
    with db() as conn:
        row=conn.execute('SELECT * FROM channel_people_filters WHERE channel_id=?',(channel_id,)).fetchone()
    if not row:
        return items
    try:
        actors=[str(x) for x in json.loads(row['actors_json'] or '[]') if str(x).strip()]
        directors=[str(x) for x in json.loads(row['directors_json'] or '[]') if str(x).strip()]
    except Exception:
        actors=[];directors=[]
    ys=safe_int(row['air_year_start']); ye=safe_int(row['air_year_end'])
    show_sets,item_sets,exact_episode_show_sets=_people_scope_sets(actors,directors)
    out=[]
    for item in items:
        if (actors or directors) and not _item_matches_people(item,actors,directors,show_sets,item_sets,exact_episode_show_sets):
            continue
        y=_item_air_year(item)
        if ys is not None and (y is None or y<ys):
            continue
        if ye is not None and (y is None or y>ye):
            continue
        out.append(item)
    return out


def people_page(q: str = '', msg: str = '') -> str:
    rows=people_catalog_rows(q,500)
    with db() as conn:
        totals=conn.execute("""SELECT COUNT(DISTINCT person_name_norm) people,
          COUNT(DISTINCT CASE WHEN credit_type='actor' THEN person_name_norm END) actors,
          COUNT(DISTINCT CASE WHEN credit_type='director' THEN person_name_norm END) directors,COUNT(*) credits
          FROM people_credits""").fetchone()
    row_html=[]
    for r in rows:
        roles=('Actor' if r['is_actor'] else '')+(' / ' if r['is_actor'] and r['is_director'] else '')+('Director' if r['is_director'] else '')
        ai_phrase=('Make a channel starring ' if r['is_actor'] else 'Make a channel directed by ')+str(r['person_name'])
        detail=_person_detail_id_url(r.get('person_credit_id'),str(r['person_name']))
        row_html.append(f"<tr><td><a href='{e(detail)}'><b>{e(r['person_name'])}</b></a></td><td>{e(roles)}</td><td>{int(r['title_count'] or 0):,}</td><td><a class='button secondary' href='{e(detail)}'>View Person</a> <a class='button secondary' href='/channels/ai?prompt={quote(ai_phrase)}'>AI Builder</a></td></tr>")
    trs=''.join(row_html) or "<tr><td colspan='4' class='empty'>No people metadata matched. Sync a Plex library or scan local NFO metadata first.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('People','Actors and directors imported from Plex metadata and local NFO files. Click a person to see their complete ViperTV filmography.',"<a class='button secondary' href='/plex'>Plex Sync</a> <a class='button' href='/channels/ai'>AI Channel Builder</a>")+f"""
<div class='stats'><div class='stat'><div class='stat-label'>People</div><div class='stat-value'>{int(totals['people'] or 0):,}</div></div><div class='stat'><div class='stat-label'>Actors</div><div class='stat-value'>{int(totals['actors'] or 0):,}</div></div><div class='stat'><div class='stat-label'>Directors</div><div class='stat-value'>{int(totals['directors'] or 0):,}</div></div><div class='stat'><div class='stat-label'>Credits</div><div class='stat-value'>{int(totals['credits'] or 0):,}</div></div></div>
<div class='card'><form method='get' action='/media/people'><div class='grid'><div><label>Search actors / directors</label><input name='q' value='{e(q)}' placeholder='John Ritter'></div><div style='align-self:end'><button>Search</button> <a class='button secondary' href='/media/people'>Clear</a></div></div></form></div>
<div class='card'><h2>Imported People</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Credits</th><th>Titles / Shows</th><th></th></tr></thead><tbody>{trs}</tbody></table></div><p class='muted small'>Open a person to see movies, TV shows, individual matching episodes, characters, source libraries and collection tools. Plex Sync Metadata imports show cast plus any episode/movie actor and director credits Plex exposes. Local library scans import <code>tvshow.nfo</code> cast/directors and sidecar episode/movie NFO credits.</p></div>
<div class='card'><h2>AI examples</h2><p><code>Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s</code><br><code>Make a channel directed by James Burrows</code><br><code>Make a 1990s TV channel starring Kelsey Grammer</code></p><p class='muted small'>When a person filter is present, decade/year filtering uses each episode's air date/year instead of the show's premiere year.</p></div>
"""
    return page_shell('People',body)


def _person_credit_maps(rows: list[sqlite3.Row], person_norm: str):
    """Build exact-item and series-level credit maps for one person."""
    show_map: dict[tuple[str,int,str,str], list[sqlite3.Row]] = {}
    item_map: dict[tuple[str,int,str,str,str], list[sqlite3.Row]] = {}
    for r in rows:
        if str(r['person_name_norm']) != person_norm:
            continue
        st=str(r['source_type']); lib=int(r['library_id']); ct=str(r['credit_type']); mt=str(r['media_type']); mk=str(r['media_key'])
        if mt=='show':
            show_map.setdefault((st,lib,mk,ct),[]).append(r)
        else:
            item_map.setdefault((st,lib,mt,mk,ct),[]).append(r)
    return show_map,item_map


def person_detail_page(name: str, msg: str='') -> str:
    """Render one person's credits without scanning the entire media catalog.

    v1.1.44 intentionally builds the page from the indexed people_credits rows
    and fetches only the referenced movies/episodes.  Older builds called
    _collection_search_items(), which walked every media item and every people
    credit on every click and could take close to a minute on large libraries.
    """
    norm=_person_norm(name)
    if not norm:
        raise HTTPException(404,'Person not found')
    with db() as conn:
        credits=conn.execute("""SELECT * FROM people_credits WHERE person_name_norm=?
                                ORDER BY credit_type,source_type,library_id,media_type,show_title,media_key""",(norm,)).fetchall()
        if not credits:
            raise HTTPException(404,'Person not found')
        local_library_names={int(r['id']):str(r['name'] or '') for r in conn.execute('SELECT id,name FROM libraries')}
        plex_library_names={int(r['id']):str(r['title'] or '') for r in conn.execute('SELECT id,title FROM plex_libraries')}

        local_ids=sorted({safe_int(r['media_key']) for r in credits if str(r['source_type'])=='local' and str(r['media_type']) in ('movie','episode') and safe_int(r['media_key']) is not None})
        plex_pairs={(int(r['library_id']),str(r['media_key'])) for r in credits if str(r['source_type'])=='plex' and str(r['media_type']) in ('movie','episode')}

        local_media={}
        if local_ids:
            marks=','.join('?' for _ in local_ids)
            for r in conn.execute(f'SELECT * FROM media WHERE id IN ({marks})',local_ids):
                local_media[int(r['id'])]=dict(r)
        plex_media={}
        if plex_pairs:
            rating_keys=sorted({rk for _,rk in plex_pairs})
            marks=','.join('?' for _ in rating_keys)
            for r in conn.execute(f'SELECT * FROM plex_media WHERE rating_key IN ({marks})',rating_keys):
                plex_media[(int(r['plex_library_id']),str(r['rating_key']))]=dict(r)

    canonical=str(credits[0]['person_name'])
    is_actor=any(str(r['credit_type'])=='actor' for r in credits)
    is_director=any(str(r['credit_type'])=='director' for r in credits)
    roles=[]
    if is_actor: roles.append('Actor')
    if is_director: roles.append('Director')
    character_names=sorted({str(r['character_name']).strip() for r in credits if str(r['credit_type'])=='actor' and str(r['character_name'] or '').strip()},key=str.casefold)
    show_map,item_map=_person_credit_maps(credits,norm)

    def library_name(st:str,lib:int)->str:
        return local_library_names.get(lib,'') if st=='local' else plex_library_names.get(lib,'') if st=='plex' else ''

    def get_media(st:str,lib:int,key:str)->dict[str,Any] | None:
        if st=='local':
            mid=safe_int(key)
            return local_media.get(mid) if mid is not None else None
        if st=='plex':
            return plex_media.get((lib,str(key)))
        return None

    def media_year(st:str,row:dict[str,Any])->int|None:
        if st=='plex':
            air=str(row.get('originally_available_at') or '')
            if re.match(r'^\d{4}',air): return safe_int(air[:4])
            return safe_int(row.get('year') or row.get('show_year'))
        return safe_int(row.get('year') or row.get('show_year'))

    # Exact movies and episodes only. Series-level cast is retained as useful
    # show metadata, but it is never expanded into every episode here.
    movie_rows=[]
    tv_groups:dict[tuple[str,int,str,str],dict[str,Any]]={}
    years:set[int]=set()
    sources:set[str]=set()
    libraries:set[str]=set()

    exact_keys={(str(r['source_type']),int(r['library_id']),str(r['media_type']),str(r['media_key'])) for r in credits if str(r['media_type']) in ('movie','episode')}
    for st,lib,mt,mk in sorted(exact_keys):
        row=get_media(st,lib,mk)
        if not row:
            continue
        libname=library_name(st,lib)
        if st: sources.add(st.title())
        if libname: libraries.add(libname)
        y=media_year(st,row)
        if y is not None: years.add(y)
        actor_exact=item_map.get((st,lib,mt,mk,'actor'),[])
        director_exact=item_map.get((st,lib,mt,mk,'director'),[])
        credit_labels=[]
        if actor_exact: credit_labels.append('Actor')
        if director_exact: credit_labels.append('Director')
        chars=sorted({str(r['character_name']).strip() for r in actor_exact if str(r['character_name'] or '').strip()},key=str.casefold)
        credit_label=' / '.join(credit_labels)
        char_text=', '.join(chars)
        if mt=='movie':
            title=str(row.get('title') or 'Untitled')
            movie_rows.append((title,y,libname,st,lib,mk,credit_label,char_text))
            continue
        show_title=str(row.get('show_title') or next((str(r['show_title']) for r in credits if str(r['source_type'])==st and int(r['library_id'])==lib and str(r['media_type'])=='episode' and str(r['media_key'])==mk and str(r['show_title'] or '').strip()),'Unknown Show'))
        show_key=str(row.get('show_rating_key') or show_title)
        if st=='local': show_key=show_title
        gkey=(st,lib,show_key,show_title)
        g=tv_groups.setdefault(gkey,{'source':st,'library_id':lib,'show_key':show_key,'show_title':show_title,'library_name':libname,'episodes':[],'series_credit':False})
        g['episodes'].append({'row':row,'credit':credit_label,'characters':char_text})

    # Add shows that have only a series-level credit. We display the association
    # but do not invent episode appearances from it.
    for r in credits:
        if str(r['media_type'])!='show':
            continue
        st=str(r['source_type']); lib=int(r['library_id']); sk=str(r['show_key'] or r['media_key']); title=str(r['show_title'] or r['media_key'] or 'Unknown Show')
        libname=library_name(st,lib)
        if st: sources.add(st.title())
        if libname: libraries.add(libname)
        gkey=(st,lib,sk,title)
        g=tv_groups.setdefault(gkey,{'source':st,'library_id':lib,'show_key':sk,'show_title':title,'library_name':libname,'episodes':[],'series_credit':False})
        g['series_credit']=True

    movie_rows.sort(key=lambda x:(x[0].casefold(),x[1] or 0))
    movie_html=[]
    for title,year,libname,st,lib,mk,credit_label,chars in movie_rows:
        href=_movie_detail_url(st,lib,mk)
        movie_html.append(f"<tr><td><a href='{e(href)}'><b>{e(title)}</b></a></td><td>{e(year or '')}</td><td>{e(credit_label)}</td><td>{e(chars)}</td><td>{e(libname)}</td></tr>")
    movies_table=''.join(movie_html) or "<tr><td colspan='5' class='empty'>No exact movie credits are indexed for this person.</td></tr>"

    show_cards=[]
    episode_total=0
    exact_show_total=0
    series_only_total=0
    for key,g in sorted(tv_groups.items(),key=lambda kv:kv[1]['show_title'].casefold()):
        episodes=g['episodes']
        episodes.sort(key=lambda z:(safe_int(z['row'].get('season_number')) or -1,safe_int(z['row'].get('episode_number')) or -1,str(z['row'].get('episode_title') or z['row'].get('title') or '').casefold()))
        episode_total+=len(episodes)
        if episodes: exact_show_total+=1
        elif g['series_credit']: series_only_total+=1
        show_href=_show_detail_url(g['source'],g['library_id'],g['show_title'],g['show_key'])
        erows=[]
        for z in episodes:
            row=z['row']; sn=safe_int(row.get('season_number')); en=safe_int(row.get('episode_number'))
            ep=f"S{sn:02d}E{en:02d}" if sn is not None and en is not None else ''
            title=str(row.get('episode_title') or row.get('title') or 'Untitled')
            air=str(row.get('originally_available_at') or row.get('year') or row.get('show_year') or '')
            erows.append(f"<tr><td>{e(ep)}</td><td><b>{e(title)}</b></td><td>{e(air)}</td><td>{e(z['credit'])}</td><td>{e(z['characters'])}</td><td>Episode credit</td></tr>")
        if erows:
            note="Exact episode credits only."
            if g['series_credit']:
                note+=" A series-level credit also exists, but ViperTV does not use it to assume this person appears in every episode."
            episode_block=f"<div class='table-wrap'><table><thead><tr><th>Episode</th><th>Title</th><th>Air Date / Year</th><th>Credit</th><th>Character</th><th>Credit Scope</th></tr></thead><tbody>{''.join(erows)}</tbody></table></div><p class='muted small'>{e(note)}</p>"
        else:
            episode_block="<div class='msg'>Series-level credit imported, but no episode-specific credits were found. ViperTV will not list the whole series as appearances. Go to Plex → Refresh Rich Credits (or run Sync Metadata) to import full per-episode cast/director metadata.</div>"
        show_cards.append(f"""<div class='card'><div class='page-heading'><div><h2><a href='{e(show_href)}'>{e(g['show_title'])}</a></h2><p>{e(g['library_name'])} · {len(episodes):,} exact matching episode{'s' if len(episodes)!=1 else ''}</p></div><span class='badge blue'>{e(g['source'].title())}</span></div>{episode_block}</div>""")
    shows_html=''.join(show_cards) or "<div class='card'><p class='empty'>No TV credits are indexed for this person.</p></div>"

    year_range=(str(min(years)) if len(years)==1 else f"{min(years)}–{max(years)}") if years else 'Unknown'
    metadata_rows=[
        ('Name',canonical),('Known To ViperTV As',' / '.join(roles)),('Characters',', '.join(character_names)),
        ('Sources',', '.join(sorted(sources))),('Libraries',', '.join(sorted(libraries,key=str.casefold))),('Exact Media Years Represented',year_range),
        ('TV Shows With Exact Episodes',exact_show_total),('Exact Matching TV Episodes',episode_total),('Series-Level-Only TV Credits',series_only_total),
        ('Movies',len(movie_rows)),('Imported Credit Records',len(credits)),
    ]
    meta_html=''.join(f"<tr><th style='width:240px'>{e(k)}</th><td>{e(v)}</td></tr>" for k,v in metadata_rows if v not in ('',None))
    collection_forms=[]
    for role,label in (('actor','Actor'),('director','Director')):
        if not ((role=='actor' and is_actor) or (role=='director' and is_director)):
            continue
        default_name=f"{canonical} — {label}"
        collection_forms.append(f"""<form method='post' action='/media/people/create-collection'><input type='hidden' name='person_name' value='{e(canonical)}'><input type='hidden' name='credit_type' value='{role}'><label>{label} Collection Name</label><div class='grid'><div><input name='collection_name' value='{e(default_name)}' required></div><div style='align-self:end'><button>Create {label} Smart Collection</button></div></div></form>""")
    ai_links=[]
    if is_actor: ai_links.append(f"<a class='button secondary' href='/channels/ai?prompt={quote('Make a channel starring '+canonical)}'>Actor Channel</a>")
    if is_director: ai_links.append(f"<a class='button secondary' href='/channels/ai?prompt={quote('Make a channel directed by '+canonical)}'>Director Channel</a>")
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading(canonical,'Actor/director metadata, exact indexed filmography and per-person Collection tools.',"<a class='button secondary' href='/media/people'>Back to People</a> "+' '.join(ai_links))+f"""
<div class='grid'>
 <div class='card'><h2>Person Metadata</h2><div class='table-wrap'><table><tbody>{meta_html}</tbody></table></div><p class='muted small'>This page now uses ViperTV's indexed credit records directly instead of scanning the full media catalog. Episode lists contain exact episode credits only; a series-level cast credit by itself is never expanded into every episode.</p></div>
 <div class='card'><h2>Create Collection For This Person</h2>{''.join(collection_forms)}<p class='muted small'>These Smart Collections use exact movie/episode credits. Newly synced matching media is added automatically without treating a series-level guest credit as every episode.</p></div>
</div>
<div class='card'><h2>Movies</h2><div class='table-wrap'><table><thead><tr><th>Movie</th><th>Year</th><th>Credit</th><th>Character</th><th>Library</th></tr></thead><tbody>{movies_table}</tbody></table></div></div>
<div><h2>TV Shows & Individual Episodes</h2><p class='muted'>Only episodes with an imported actor/director credit for this person are listed. Series-level metadata is shown separately and is not treated as proof of an appearance in every episode.</p>{shows_html}</div>
"""
    return page_shell(canonical,body)

def _ai_phrase_present(prompt_norm: str, phrase: str) -> bool:
    needle = _ai_normalize(phrase)
    if not needle:
        return False
    return f" {needle} " in f" {prompt_norm} "


def _ai_available_channel_number() -> str:
    with db() as conn:
        used = {str(r['number']).strip() for r in conn.execute("SELECT number FROM channels")}
    n = 1
    while str(n) in used:
        n += 1
    return str(n)


def _ai_parse_years(prompt: str) -> tuple[int | None, int | None, str | None]:
    # Explicit range: 1990-1999, 1990 to 1999, from 1990 through 1999.
    m = re.search(r"\b((?:19|20)\d{2})\s*(?:-|–|—|to|through|thru)\s*((?:19|20)\d{2})\b", prompt, re.I)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        return a, b, f"{a}-{b}"
    # 1990s / 1990's
    m = re.search(r"\b((?:19|20)\d)0\s*'?s\b", prompt, re.I)
    if m:
        a = int(m.group(1) + '0')
        return a, a + 9, f"{a}s"
    # 90s / 80's / 00s / 10s. 30-99 maps to 1900s; 00-29 maps to 2000s.
    m = re.search(r"(?<!\d)(\d{2})\s*'?s\b", prompt, re.I)
    if m:
        d = int(m.group(1))
        a = (1900 + d) if d >= 30 else (2000 + d)
        return a, a + 9, f"{a}s"
    # Single four-digit year. Avoid treating a channel number as a year by requiring 19xx/20xx.
    years = [int(x) for x in re.findall(r"\b((?:19|20)\d{2})\b", prompt)]
    if len(years) == 1:
        return years[0], years[0], str(years[0])
    return None, None, None


def _ai_extract_name(prompt: str) -> str | None:
    # Quoted names first.
    m = re.search(r"\b(?:called|named|name(?:\s+it)?)\s+[\"'“]([^\"'”]+)[\"'”]", prompt, re.I)
    if m:
        return m.group(1).strip()
    # Unquoted: stop at common instruction words or punctuation.
    m = re.search(
        r"\b(?:called|named|name(?:\s+it)?)\s+(.+?)(?=\s+(?:using|from|with|on\s+channel|channel\s+number|number(?:\s+it)?|shuffle|random|sequential|in\s+order)\b|[,.;!?]|$)",
        prompt, re.I,
    )
    if m:
        return m.group(1).strip(' \"\'')
    return None


def _ai_extract_channel_number(prompt: str) -> str | None:
    patterns = [
        r"\bchannel(?:\s+number)?\s*(?:is|to|:)?\s*#?(\d{1,4})\b",
        r"\bnumber(?:\s+it)?\s*(?:is|to|:)?\s*#?(\d{1,4})\b",
        r"(?<!\w)#(\d{1,4})\b",
    ]
    for pat in patterns:
        m = re.search(pat, prompt, re.I)
        if m:
            return str(int(m.group(1)))
    return None


def _ai_source_catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with db() as conn:
        for r in conn.execute("SELECT id,name FROM libraries ORDER BY name COLLATE NOCASE"):
            out.append({'source_type':'local','library_id':int(r['id']),'name':str(r['name']),'category':special_media_category(str(r['name']))})
        for r in conn.execute("""SELECT pl.id,pl.title,ps.name server_name FROM plex_libraries pl
                               JOIN plex_servers ps ON ps.id=pl.server_id WHERE pl.enabled=1 ORDER BY ps.name,pl.title"""):
            out.append({'source_type':'plex','library_id':int(r['id']),'name':str(r['title']),'server_name':str(r['server_name']),'category':special_media_category(str(r['title']))})
    return out


def _ai_prefer_unique_shows(shows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # A Plex and local library often point at the same files. For an AI-built channel,
    # silently choosing Plex first avoids programming every episode twice.
    chosen: dict[str, dict[str, Any]] = {}
    for x in shows:
        key = _ai_normalize(str(x.get('show_title') or ''))
        if not key:
            continue
        old = chosen.get(key)
        if old is None or (old.get('source_type') != 'plex' and x.get('source_type') == 'plex'):
            chosen[key] = x
    return sorted(chosen.values(), key=lambda x: str(x.get('show_title') or '').casefold())


def interpret_ai_channel_prompt(prompt: str) -> dict[str, Any]:
    raw = (prompt or '').strip()
    pn = _ai_normalize(raw)
    shows = auto_channel_show_catalog()
    sources = _ai_source_catalog()
    notes: list[str] = []

    # Network names are learned from the user's own catalog, not hard-coded.
    network_names = sorted({str(x.get('original_network') or '').strip() for x in shows if str(x.get('original_network') or '').strip()}, key=len, reverse=True)
    networks = [n for n in network_names if _ai_phrase_present(pn, n)]

    year_start, year_end, year_label = _ai_parse_years(raw)

    category = None
    if _ai_phrase_present(pn, 'music videos'):
        category = 'Music Videos'
    elif _ai_phrase_present(pn, 'game shows') or _ai_phrase_present(pn, 'game show'):
        category = 'Game Shows'
    elif _ai_phrase_present(pn, 'youtube') or _ai_phrase_present(pn, 'you tube'):
        category = 'YouTube'

    source_kind = None
    if re.search(r"\bplex(?:\s+only)?\b", raw, re.I):
        source_kind = 'plex'
    elif re.search(r"\blocal(?:\s+(?:files?|library|only))?\b", raw, re.I):
        source_kind = 'local'

    # Specific library name, preferring the longest meaningful title match.
    source_library: dict[str, Any] | None = None
    source_candidates = [x for x in sources if len(_ai_normalize(x['name'])) >= 5 and _ai_phrase_present(pn, x['name'])]
    if source_candidates:
        source_candidates.sort(key=lambda x: len(_ai_normalize(x['name'])), reverse=True)
        source_library = source_candidates[0]
        source_kind = source_library['source_type']

    # Explicit show names mentioned in the request.
    explicit_titles: set[str] = set()
    for x in shows:
        title = str(x.get('show_title') or '').strip()
        nt = _ai_normalize(title)
        if len(nt) >= 2 and _ai_phrase_present(pn, title):
            explicit_titles.add(nt)

    # Actors/directors are learned from ViperTV's imported People index. This
    # keeps interpretation local and also means misspelled cue words such as
    # "staring John Ritter" still work as long as the person's name is present.
    known_people = _known_people_lookup()
    matched_people: list[tuple[str,dict[str,Any]]] = []
    for norm, meta in sorted(known_people.items(), key=lambda kv: len(kv[0]), reverse=True):
        if len(norm) >= 3 and _ai_phrase_present(pn, norm):
            # Avoid treating a short one-word name as a second match when it is
            # contained inside a longer already-matched person's name.
            if any(norm != old and f" {norm} " in f" {old} " for old,_ in matched_people):
                continue
            matched_people.append((norm,meta))

    actors: list[str] = []
    directors: list[str] = []
    for norm, meta in matched_people:
        name = str(meta['name'])
        directed_context = bool(
            re.search(rf"\b(?:directed\s+by|director|directors)\s+(?:by\s+)?{re.escape(norm)}\b", pn)
            or re.search(rf"\b{re.escape(norm)}\s+(?:director|directed)\b", pn)
        )
        actor_context = bool(
            re.search(rf"\b(?:starring|staring|featuring|actor|actors|with)\s+(?:tv\s+)?{re.escape(norm)}\b", pn)
            or re.search(rf"\b{re.escape(norm)}\s+(?:actor|starring|staring)\b", pn)
        )
        if directed_context or (meta.get('director') and not meta.get('actor') and not actor_context):
            directors.append(name)
        else:
            actors.append(name)

    # If the prompt explicitly asks for a person but nobody in the imported
    # People index matches, fail closed instead of silently making a broad
    # decade/network channel.
    person_cue = bool(re.search(r"\b(?:starring|staring|featuring|actors?|directed\s+by|directors?)\b", pn))
    unresolved_person_cue = person_cue and not (actors or directors)

    candidates = list(shows)
    if source_kind:
        candidates = [x for x in candidates if x.get('source_type') == source_kind]
    if source_library:
        candidates = [x for x in candidates if x.get('source_type') == source_library['source_type'] and int(x.get('library_id')) == int(source_library['library_id'])]
    if category:
        candidates = [x for x in candidates if special_media_category(str(x.get('library_name') or '')) == category]
    if explicit_titles:
        candidates = [x for x in candidates if _ai_normalize(str(x.get('show_title') or '')) in explicit_titles]
    if networks:
        nset = {_ai_normalize(n) for n in networks}
        candidates = [x for x in candidates if _ai_normalize(str(x.get('original_network') or '')) in nset]

    people_counts: dict[tuple[str,int,str],int] = {}
    if actors or directors:
        # For people channels, 1980s/1994/etc means the episode's actual air
        # year, not the year the series first premiered.
        people_counts = people_episode_match_counts(actors,directors,year_start,year_end)
        filtered=[]
        for x in candidates:
            ident=(str(x['source_type']),int(x['library_id']),str(x['show_key']))
            count=int(people_counts.get(ident,0))
            if count:
                y=dict(x); y['episodes']=count; filtered.append(y)
        candidates=filtered
    elif unresolved_person_cue:
        candidates=[]
    else:
        # Preserve the original Channel Builder behaviour when no person is
        # involved: year/decade means show premiere year.
        if year_start is not None:
            candidates = [x for x in candidates if safe_int(x.get('show_year')) is not None and safe_int(x.get('show_year')) >= year_start]
        if year_end is not None:
            candidates = [x for x in candidates if safe_int(x.get('show_year')) is not None and safe_int(x.get('show_year')) <= year_end]

    candidates = _ai_prefer_unique_shows(candidates)

    selections: list[dict[str, Any]] = []
    for x in candidates:
        selections.append({
            'source_type': x['source_type'],
            'library_id': x['library_id'] if x['source_type'] == 'local' else None,
            'plex_library_id': x['library_id'] if x['source_type'] == 'plex' else None,
            'selection_type': 'show',
            'show_key': x['show_key'],
            'show_title': x['show_title'],
            'season_number': None,
        })

    # YouTube and Music Video libraries are commonly flat instead of TV-show
    # hierarchies. If no show rows exist, selecting the whole matching library is
    # the useful interpretation of "make me a YouTube/Music Videos channel".
    if category and not selections and not networks and year_start is None and not explicit_titles and not (actors or directors) and not unresolved_person_cue:
        cat_sources = [x for x in sources if x.get('category') == category]
        if source_kind:
            cat_sources = [x for x in cat_sources if x['source_type'] == source_kind]
        if source_library:
            cat_sources = [x for x in cat_sources if x['source_type'] == source_library['source_type'] and x['library_id'] == source_library['library_id']]
        # Prefer Plex copies if both Plex and local categories exist and user did not specify.
        if not source_kind and any(x['source_type'] == 'plex' for x in cat_sources):
            cat_sources = [x for x in cat_sources if x['source_type'] == 'plex']
        for x in cat_sources:
            selections.append({
                'source_type': x['source_type'],
                'library_id': x['library_id'] if x['source_type'] == 'local' else None,
                'plex_library_id': x['library_id'] if x['source_type'] == 'plex' else None,
                'selection_type': 'library',
                'show_key': '',
                'show_title': x['name'],
                'season_number': None,
            })

    # A specifically named library with no other criteria means "use that library".
    if source_library and not selections and not networks and year_start is None and not explicit_titles and not (actors or directors) and not unresolved_person_cue:
        x = source_library
        selections.append({
            'source_type': x['source_type'],
            'library_id': x['library_id'] if x['source_type'] == 'local' else None,
            'plex_library_id': x['library_id'] if x['source_type'] == 'plex' else None,
            'selection_type': 'library',
            'show_key': '',
            'show_title': x['name'],
            'season_number': None,
        })

    sequential = bool(re.search(r"\b(sequential|in\s+order|chronological|no\s+shuffle|don'?t\s+shuffle)\b", raw, re.I))
    shuffle = not sequential
    if re.search(r"\b(shuffle|random|randomize|randomise)\b", raw, re.I):
        shuffle = True

    number = _ai_extract_channel_number(raw) or _ai_available_channel_number()
    name = _ai_extract_name(raw)
    if not name:
        if actors and year_label:
            name = f"{' + '.join(actors[:2])} {year_label}"
        elif directors and year_label:
            name = f"{' + '.join(directors[:2])} {year_label}"
        elif actors:
            name = ' + '.join(actors[:3])
        elif directors:
            name = ' + '.join(directors[:3]) + ' Directed'
        elif explicit_titles:
            titles = [x['show_title'] for x in candidates[:3]]
            name = ' + '.join(titles) if titles else 'AI Channel'
        elif category:
            name = category
        elif networks and year_label:
            name = f"{' + '.join(networks)} {year_label}"
        elif networks:
            name = ' + '.join(networks)
        elif year_label:
            name = f"{year_label} TV"
        elif source_library:
            name = str(source_library['name'])
        else:
            name = 'AI Channel'

    if 'sitcom' in pn or 'comedy' in pn or 'drama' in pn or 'cartoon' in pn or 'genre' in pn:
        notes.append('Genre words are not a filter yet; ViperTV used the show/network/year/library/people parts of your request.')
    if networks and any(not str(x.get('original_network') or '').strip() for x in shows):
        notes.append('Shows with unknown original-network metadata cannot match a network request.')
    if actors or directors:
        if year_start is not None:
            notes.append('Because this is a people channel, year/decade filtering uses each episode\'s air year, not the show premiere year.')
        else:
            notes.append('People matching uses show-level cast plus episode-level actor/director credits when available.')
    elif year_start is not None:
        notes.append('Year filtering uses each show\'s premiere year because no actor/director filter was requested.')
    if unresolved_person_cue:
        notes.append('No imported actor/director matched the person request. Sync Plex metadata (or scan local NFO metadata) and try again.')
    if not selections:
        notes.append('No playable selections matched. Mention a show, actor/director, network, year/decade, library name, YouTube, Music Videos, or Game Shows.')

    episode_estimate = sum(int(x.get('episodes') or 0) for x in candidates)
    criteria = []
    if explicit_titles:
        criteria.append('shows: ' + ', '.join(sorted({x['show_title'] for x in candidates}, key=str.casefold)[:12]))
    if actors:
        criteria.append('actors: ' + ', '.join(actors))
    if directors:
        criteria.append('directors: ' + ', '.join(directors))
    if networks:
        criteria.append('network: ' + ', '.join(networks))
    if year_label:
        criteria.append(('air years: ' if (actors or directors) else 'years: ') + year_label)
    if category:
        criteria.append('category: ' + category)
    if source_library:
        criteria.append('library: ' + source_library['name'])
    elif source_kind:
        criteria.append('source: ' + source_kind.title())

    return {
        'prompt': raw,
        'number': number,
        'name': name,
        'shuffle': shuffle,
        'networks': networks,
        'year_start': year_start,
        'year_end': year_end,
        'year_label': year_label,
        'actors': actors,
        'directors': directors,
        'category': category,
        'source_kind': source_kind,
        'source_library': source_library,
        'shows': candidates,
        'selections': selections,
        'episode_estimate': episode_estimate,
        'criteria': criteria,
        'notes': notes,
    }


def ai_channel_builder_page(prompt: str = '', msg: str = '') -> str:
    plan = interpret_ai_channel_prompt(prompt) if prompt.strip() else None
    notice = f"<div class='msg'>{e(msg)}</div>" if msg else ''
    preview = ''
    if plan:
        show_rows = ''.join(
            f"<tr><td><b>{e(x.get('show_title'))}</b></td><td>{e(x.get('original_network') or 'Unknown')}</td><td>{e(x.get('show_year') or 'Unknown')}</td><td>{int(x.get('episodes') or 0):,}</td><td>{e(('Plex / '+str(x.get('server_name'))+' / ') if x.get('source_type')=='plex' else 'Local / ')}{e(x.get('library_name'))}</td></tr>"
            for x in plan['shows'][:100]
        )
        if not show_rows and plan['selections']:
            show_rows = ''.join(f"<tr><td colspan='4'><b>{e(x.get('show_title'))}</b></td><td>{e(x.get('source_type'))} library</td></tr>" for x in plan['selections'])
        if not show_rows:
            show_rows = "<tr><td colspan='5' class='empty'>No matching media.</td></tr>"
        note_html = ''.join(f"<li>{e(n)}</li>" for n in plan['notes'])
        crit = ' · '.join(plan['criteria']) or 'No media filter understood yet'
        create_disabled = ' disabled' if not plan['selections'] else ''
        preview = f"""
<div class='card'>
  <h2>What ViperTV Understood</h2>
  <div class='grid3'>
    <div><label>Channel</label><div class='stat-value' style='font-size:20px'>#{e(plan['number'])} {e(plan['name'])}</div></div>
    <div><label>Playback</label><div class='stat-value' style='font-size:20px'>{'Shuffle' if plan['shuffle'] else 'Sequential'}</div></div>
    <div><label>Matches</label><div class='stat-value' style='font-size:20px'>{len(plan['selections']):,} selection(s)</div></div>
  </div>
  <p><b>Criteria:</b> {e(crit)}</p>
  <p class='muted'>Estimated TV episodes represented by show matches: {int(plan['episode_estimate']):,}. Flat library selections such as YouTube are not included in this estimate.</p>
  {('<ul class="muted">'+note_html+'</ul>') if note_html else ''}
  <form method='post' action='/channels/ai/create'>
    <input type='hidden' name='prompt' value='{e(plan['prompt'])}'>
    <button{create_disabled}>Create This Channel</button>
    <a class='button secondary' href='/channels/ai'>Clear</a>
  </form>
</div>
<div class='card'><h2>Matched Shows / Libraries</h2><div class='table-wrap' style='max-height:520px'><table><thead><tr><th>Show</th><th>Network</th><th>Year</th><th>Episodes</th><th>Source</th></tr></thead><tbody>{show_rows}</tbody></table></div>{'<p class="muted small">Showing the first 100 matches.</p>' if len(plan['shows'])>100 else ''}</div>
"""
    body = notice + _page_heading('AI Channel Builder','Describe the channel you want in ordinary language. Everything is interpreted locally inside ViperTV; your prompt is not sent to a cloud AI service.',"<a class='button secondary' href='/channels'>Back to Channels</a>") + f"""
<div class='card'>
  <h2>Ask ViperTV</h2>
  <form method='post' action='/channels/ai/preview'>
    <label>What channel should I make?</label>
    <textarea name='prompt' rows='4' required placeholder='Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s'>{e(prompt)}</textarea>
    <button>Understand Request</button>
  </form>
  <hr>
  <div class='muted small'><b>Examples</b><br>
    “Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s.”<br>
    “Make a 1990s channel starring Kelsey Grammer.”<br>
    “Make a channel directed by James Burrows.”<br>
    “Make me channel 25 called 90s NBC using NBC shows from the 1990s and shuffle them.”<br>
    “Create channel 42 named Frasier and Cheers with Frasier and Cheers.”<br>
    “Create a YouTube channel called Retro YouTube on channel 70.”
  </div>
</div>
{preview}
<div class='card'><h2>How it works</h2><p class='muted'>The built-in natural-language interpreter uses the metadata already in ViperTV. It understands show titles, <b>actors, directors</b>, original networks, years/decades, Plex versus local sources, named libraries, YouTube / You Tube, Music Videos, Game Shows, channel number/name, and shuffle versus sequential playback. For actor/director channels, a decade or year applies to the <b>episode air year</b>, so “1980s starring John Ritter” can include only matching episodes that actually aired in 1980–1989 even when the series began earlier. The resulting channel is a normal ViperTV channel that can be cloned, scheduled or deleted afterward.</p><p class='muted small'>People metadata is imported during Plex Sync Metadata and local NFO scans. Browse it under Media → People.</p></div>
"""
    return page_shell('AI Channel Builder', body)


def create_channel_from_ai_plan(plan: dict[str, Any]) -> int:
    selections = list(plan.get('selections') or [])
    if not selections:
        raise ValueError('No media matched the request')
    number = str(plan.get('number') or '').strip()
    name = str(plan.get('name') or '').strip() or 'AI Channel'
    if not number:
        raise ValueError('No channel number was available')
    safe_backup_before_change()
    with db() as conn:
        default_profile = default_new_channel_stream_profile()
        cur = conn.execute("INSERT INTO channels(number,name,library_id,shuffle,created_at,stream_profile) VALUES(?,?,?,?,?,?)",
                           (number,name,None,1 if plan.get('shuffle') else 0,utcnow_iso(),default_profile))
        channel_id = int(cur.lastrowid)
        for x in selections:
            conn.execute("""INSERT INTO channel_selections(channel_id,source_type,library_id,plex_library_id,selection_type,show_key,show_title,season_number,created_at)
                          VALUES(?,?,?,?,?,?,?,?,?)""",
                         (channel_id,x.get('source_type'),x.get('library_id'),x.get('plex_library_id'),x.get('selection_type'),x.get('show_key'),x.get('show_title'),x.get('season_number'),utcnow_iso()))
        actors=list(plan.get('actors') or [])
        directors=list(plan.get('directors') or [])
        if actors or directors:
            conn.execute("""INSERT OR REPLACE INTO channel_people_filters(channel_id,actors_json,directors_json,air_year_start,air_year_end,created_at,updated_at)
                          VALUES(?,?,?,?,?,?,?)""",
                         (channel_id,json.dumps(actors),json.dumps(directors),safe_int(plan.get('year_start')),safe_int(plan.get('year_end')),utcnow_iso(),utcnow_iso()))
        conn.commit()
    return channel_id


# ==================== ViperTV 1.1.39 collection/search engine ====================
# The workflow intentionally mirrors the useful parts of ErsatzTV collections:
# browse/search -> select -> Add To Collection, and save a search as a dynamic
# Smart Collection.  ViperTV uses its own SQLite data and query evaluator.

def _collection_search_items() -> list[dict[str,Any]]:
    """Return all playable local/Plex/Jellyfin/Emby items with searchable metadata."""
    with db() as conn:
        items: list[dict[str,Any]] = []
        local_names={int(r['id']):str(r['name'] or '') for r in conn.execute('SELECT id,name FROM libraries')}
        plex_info={int(r['id']):(str(r['title'] or ''),str(r['library_type'] or '')) for r in conn.execute('SELECT id,title,library_type FROM plex_libraries')}
        for r in conn.execute('SELECT * FROM media WHERE duration>0'):
            d=dict(r); lib=int(r['library_id']); show=str(r['show_title'] or '')
            d.update({'source_type':'local','uid':f"local:{r['id']}",'media_type':'episode' if show else 'movie',
                      'library_name':local_names.get(lib,''),'air_date':None,'year':r['show_year'] if 'show_year' in r.keys() else None,
                      'show_key':show or None,'rating_key':None,'external_id':None,'plex_library_id':None,
                      'summary':r['summary'] if 'summary' in r.keys() else None})
            items.append(d)
        for r in conn.execute('SELECT * FROM plex_media WHERE duration>0'):
            d=dict(r); lib=int(r['plex_library_id'])
            d.update({'source_type':'plex','uid':f"plex:{lib}:{r['rating_key']}",'library_id':lib,
                      'library_name':plex_info.get(lib,('', ''))[0],'air_date':r['originally_available_at'],
                      'show_key':r['show_rating_key'] or r['show_title'],'external_id':None})
            items.append(d)
        # External media already contains enough metadata to be used by a manual
        # or smart collection. People/network metadata is not currently imported
        # for these servers, but title/show/year/library/source queries work.
        for r in conn.execute("""SELECT em.*,el.name library_name,ms.kind,ms.base_url,ms.api_key
                                 FROM external_media em JOIN external_libraries el ON el.id=em.library_id
                                 JOIN media_servers ms ON ms.id=el.server_id
                                 WHERE el.enabled=1 AND ms.enabled=1 AND em.duration>0"""):
            d=dict(r); lib=int(r['library_id'])
            d.update({'source_type':'external','uid':f"external:{lib}:{r['external_id']}",
                      'air_date':None,'show_key':r['show_title'] or None,'rating_key':None,'plex_library_id':None})
            items.append(d)

        # Merge show-level network/year/genre metadata.
        meta={}
        for r in conn.execute('SELECT * FROM tvdb_show_metadata'):
            try: genres=[str(x) for x in json.loads(r['genres_json'] or '[]') if str(x).strip()]
            except Exception: genres=[]
            meta[(str(r['source_type']),int(r['library_id']),str(r['show_key']))]={
                'network':r['original_network'],'show_year':r['show_year'],'genres':genres,'series_status':r['series_status']}

        # Merge both show-level and item-level actor/director credits.
        show_people:dict[tuple[str,int,str],dict[str,set[str]]]={}
        item_people:dict[tuple[str,int,str],dict[str,set[str]]]={}
        for r in conn.execute('SELECT * FROM people_credits'):
            bucket={'actor':set(),'director':set()}
            if r['media_type']=='show':
                key=(str(r['source_type']),int(r['library_id']),str(r['media_key']))
                bucket=show_people.setdefault(key,{'actor':set(),'director':set()})
            else:
                key=(str(r['source_type']),int(r['library_id']),str(r['media_key']))
                bucket=item_people.setdefault(key,{'actor':set(),'director':set()})
            if r['credit_type'] in bucket: bucket[str(r['credit_type'])].add(str(r['person_name']))

    for x in items:
        st=str(x.get('source_type') or ''); lib=int(x.get('library_id') or x.get('plex_library_id') or 0)
        show_key=str(x.get('show_key') or x.get('show_title') or '')
        md=meta.get((st,lib,show_key),{})
        if md:
            x['network']=md.get('network')
            x['show_year']=md.get('show_year') or x.get('show_year')
            x['genres']=md.get('genres') or []
            x['series_status']=md.get('series_status')
        else:
            x['network']=x.get('original_network')
            x['genres']=[]
        media_key=str(x.get('id') if st=='local' else (x.get('rating_key') if st=='plex' else x.get('external_id')))
        sp=show_people.get((st,lib,show_key),{'actor':set(),'director':set()})
        ip=item_people.get((st,lib,media_key),{'actor':set(),'director':set()})
        x['actors']=sorted(sp['actor']|ip['actor'])
        x['directors']=sorted(sp['director']|ip['director'])
        # Exact arrays deliberately exclude series-level cast/director data.
        # Person-created Smart Collections use these so a one-episode guest
        # appearance never expands to the entire TV series.
        x['actors_exact']=sorted(ip['actor'])
        x['directors_exact']=sorted(ip['director'])
        # The episode air date is preferred; show/movie year is a fallback.
        air=str(x.get('air_date') or '')
        year=safe_int(air[:4]) if re.match(r'^\d{4}',air) else safe_int(x.get('year') or x.get('show_year'))
        x['search_year']=year
        x['release_date']=(re.sub(r'[^0-9]','',air)[:8] if air else (f'{year:04d}0101' if year else ''))
    return items


def _search_tokenize(query:str)->list[str]:
    if not (query or '').strip(): return []
    pat=re.compile(r"""\s*(\w+:"(?:\\.|[^"])*"|\w+:\[[^\]]+\]|\(|\)|\bAND\b|\bOR\b|\bNOT\b|[^\s()]+)""",re.I)
    raw=[m.group(1) for m in pat.finditer(query)]
    out=[]
    def operand_end(t:str)->bool:return t not in ('AND','OR','NOT','(') and t!=')' or t==')'
    def operand_start(t:str)->bool:return t not in ('AND','OR',')')
    for tok in raw:
        up=tok.upper() if tok.upper() in ('AND','OR','NOT') else tok
        if out and operand_end(out[-1]) and operand_start(up): out.append('AND')
        elif out and out[-1]==')' and up=='(': out.append('AND')
        out.append(up)
    return out


def _search_text_match(candidate:Any, wanted:str)->bool:
    c=str(candidate or '').casefold(); w=str(wanted or '').strip().strip('"').casefold()
    if '*' in w or '?' in w:
        rx=''.join('.*' if ch=='*' else '.' if ch=='?' else re.escape(ch) for ch in w)
        return re.search(rx,c,re.I) is not None
    return w in c


def _search_atom(item:dict[str,Any], token:str)->bool:
    if ':' in token:
        field,value=token.split(':',1); field=field.casefold(); value=value.strip()
    else:
        field='text'; value=token.strip()
    if len(value)>=2 and value[0]=='"' and value[-1]=='"': value=value[1:-1].replace('\\"','"')
    mt=str(item.get('media_type') or '').casefold()
    show_title=str(item.get('show_title') or '')
    if field=='type':
        wanted=value.casefold()
        if wanted=='show': return bool(show_title) and mt=='episode'
        return mt==wanted or (wanted=='tv' and mt=='episode')
    if field in ('title','text'):
        hay=' '.join(str(item.get(k) or '') for k in ('title','episode_title','show_title','summary'))
        return _search_text_match(hay,value)
    if field=='show_title': return _search_text_match(show_title,value)
    if field in ('library','library_name'): return _search_text_match(item.get('library_name'),value)
    if field=='source':
        source=str(item.get('source_type') or '')
        kind=str(item.get('kind') or '')
        return _search_text_match(source,value) or _search_text_match(kind,value)
    if field in ('actor','actors'): return any(_search_text_match(x,value) for x in item.get('actors') or [])
    if field in ('actor_exact','actors_exact'):
        wanted=_person_norm(value)
        return bool(wanted) and any(_person_norm(x)==wanted for x in item.get('actors_exact') or [])
    if field in ('director','directors'): return any(_search_text_match(x,value) for x in item.get('directors') or [])
    if field in ('director_exact','directors_exact'):
        wanted=_person_norm(value)
        return bool(wanted) and any(_person_norm(x)==wanted for x in item.get('directors_exact') or [])
    if field in ('network','show_network'): return _search_text_match(item.get('network') or item.get('original_network'),value)
    if field in ('genre','show_genre'): return any(_search_text_match(x,value) for x in item.get('genres') or [])
    if field in ('plot','summary'): return _search_text_match(item.get('summary'),value)
    if field in ('season','season_number'):
        return safe_int(item.get('season_number'))==safe_int(value)
    if field in ('episode','episode_number'):
        return safe_int(item.get('episode_number'))==safe_int(value)
    if field in ('year','show_year'):
        y=safe_int(item.get('search_year') if field=='year' else item.get('show_year'))
        m=re.match(r'^(\d{4})-(\d{4})$',value)
        if m:return y is not None and int(m.group(1))<=y<=int(m.group(2))
        if value.endswith('*') and value[:-1].isdigit(): return y is not None and str(y).startswith(value[:-1])
        return y==safe_int(value)
    if field in ('release_date','aired','air_date'):
        d=str(item.get('release_date') or '')
        rng=re.match(r'^\[(\d{4,8})\s+TO\s+(\d{4,8})\]$',value,re.I)
        if rng:
            lo,hi=rng.group(1),rng.group(2)
            dcmp=(d+'00000000')[:8]
            lo=(lo+'00000000')[:8]; hi=(hi+'99999999')[:8]
            return bool(d) and lo<=dcmp<=hi
        return _search_text_match(d,value.replace('-',''))
    if field=='status': return _search_text_match(item.get('series_status'),value)
    # Unknown fields deliberately do not match instead of silently broadening a smart collection.
    return False


def _compile_search_query(query:str):
    tokens=_search_tokenize(query); pos=0
    if not tokens: return lambda item: True
    def parse_or():
        nonlocal pos
        node=parse_and()
        while pos<len(tokens) and tokens[pos]=='OR':
            pos+=1; rhs=parse_and(); lhs=node; node=lambda item,lhs=lhs,rhs=rhs: lhs(item) or rhs(item)
        return node
    def parse_and():
        nonlocal pos
        node=parse_not()
        while pos<len(tokens) and tokens[pos]=='AND':
            pos+=1; rhs=parse_not(); lhs=node; node=lambda item,lhs=lhs,rhs=rhs: lhs(item) and rhs(item)
        return node
    def parse_not():
        nonlocal pos
        if pos<len(tokens) and tokens[pos]=='NOT':
            pos+=1; child=parse_not(); return lambda item,child=child:not child(item)
        return parse_primary()
    def parse_primary():
        nonlocal pos
        if pos>=len(tokens): return lambda item: True
        if tokens[pos]=='(':
            pos+=1; node=parse_or()
            if pos<len(tokens) and tokens[pos]==')':pos+=1
            return node
        tok=tokens[pos]; pos+=1
        return lambda item,tok=tok:_search_atom(item,tok)
    try:return parse_or()
    except Exception:return lambda item:False


def media_search_playable(query:str,limit:int|None=None)->list[dict[str,Any]]:
    pred=_compile_search_query(query)
    out=[]
    for x in _collection_search_items():
        try: ok=pred(x)
        except Exception: ok=False
        if ok:
            out.append(x)
            if limit and len(out)>=limit:break
    out.sort(key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    return out


def _item_selection_token(item:dict[str,Any])->str:
    st=str(item.get('source_type') or '')
    if st=='local':
        return encode_selection({'source_type':'local','library_id':int(item.get('library_id')),'selection_type':'item','media_id':int(item.get('id'))})
    if st=='plex':
        return encode_selection({'source_type':'plex','plex_library_id':int(item.get('plex_library_id') or item.get('library_id')),'selection_type':'item','rating_key':str(item.get('rating_key'))})
    return encode_selection({'source_type':'external','external_library_id':int(item.get('library_id')),'selection_type':'item','external_id':str(item.get('external_id'))})


def _show_selection_token(item:dict[str,Any])->str:
    st=str(item.get('source_type') or '')
    if st=='local':
        return encode_selection({'source_type':'local','library_id':int(item.get('library_id')),'selection_type':'show','show_title':str(item.get('show_title') or '')})
    if st=='plex':
        return encode_selection({'source_type':'plex','plex_library_id':int(item.get('plex_library_id') or item.get('library_id')),'selection_type':'show','show_key':str(item.get('show_rating_key') or item.get('show_key') or ''),'show_title':str(item.get('show_title') or '')})
    return encode_selection({'source_type':'external','external_library_id':int(item.get('library_id')),'selection_type':'show','show_title':str(item.get('show_title') or '')})


def _selection_description(token:str)->str:
    try:p=decode_selection(token)
    except Exception:return 'Unknown selection'
    st=str(p.get('source_type') or '').title(); typ=str(p.get('selection_type') or 'selection')
    with db() as conn:
        if p.get('source_type')=='local':
            if typ=='item':
                r=conn.execute('SELECT m.*,l.name library_name FROM media m JOIN libraries l ON l.id=m.library_id WHERE m.id=?',(safe_int(p.get('media_id')),)).fetchone()
                return f"Local / {r['library_name']} / {r['show_title']+' / ' if r and r['show_title'] else ''}{r['title'] if r else 'Missing item'}"
            lib=conn.execute('SELECT name FROM libraries WHERE id=?',(safe_int(p.get('library_id')),)).fetchone()
            return f"Local / {lib['name'] if lib else 'Missing library'} / {p.get('show_title') or typ}"
        if p.get('source_type')=='plex':
            if typ=='item':
                r=conn.execute("""SELECT pm.title,pm.show_title,pl.title library_name FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
                                  WHERE pm.plex_library_id=? AND pm.rating_key=?""",(safe_int(p.get('plex_library_id')),str(p.get('rating_key')))).fetchone()
                return f"Plex / {r['library_name']} / {(r['show_title']+' / ') if r and r['show_title'] else ''}{r['title'] if r else 'Missing item'}"
            lib=conn.execute('SELECT title FROM plex_libraries WHERE id=?',(safe_int(p.get('plex_library_id')),)).fetchone()
            return f"Plex / {lib['title'] if lib else 'Missing library'} / {p.get('show_title') or typ}"
        if p.get('source_type')=='external':
            if typ=='item':
                r=conn.execute("""SELECT em.title,em.show_title,el.name library_name,ms.kind FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id
                                  WHERE em.library_id=? AND em.external_id=?""",(safe_int(p.get('external_library_id')),str(p.get('external_id')))).fetchone()
                return f"{str(r['kind']).title() if r else 'External'} / {r['library_name'] if r else 'Missing library'} / {(r['show_title']+' / ') if r and r['show_title'] else ''}{r['title'] if r else 'Missing item'}"
            return f"External / {p.get('show_title') or typ}"
    return f'{st} / {typ}'


def media_search_page(q:str='',msg:str='')->str:
    q=(q or '').strip(); results=media_search_playable(q,500) if q else []
    show_mode=bool(re.search(r'(?i)(?:^|\s|\()type:show(?:\s|\)|$)',q))
    display=[]
    if show_mode:
        grouped={}
        for x in results:
            if not x.get('show_title'):continue
            key=(x.get('source_type'),x.get('library_id') or x.get('plex_library_id'),x.get('show_key') or x.get('show_title'))
            if key not in grouped: grouped[key]={'item':x,'count':0}
            grouped[key]['count']+=1
        display=list(grouped.values())
    else:
        display=[{'item':x,'count':1} for x in results]
    with db() as conn:
        manual=conn.execute("SELECT id,name FROM collections WHERE kind='manual' ORDER BY name").fetchall()
    rows=[]
    for g in display:
        x=g['item']; typ='Show' if show_mode else str(x.get('media_type') or 'Media').replace('_',' ').title()
        token=_show_selection_token(x) if show_mode else _item_selection_token(x)
        title=str(x.get('show_title') or '') if show_mode else str(x.get('title') or '')
        if not show_mode and x.get('show_title'): title=f"{x.get('show_title')} — {x.get('title')}"
        details=[]
        if x.get('season_number') is not None and not show_mode: details.append(f"S{int(x['season_number']):02d}E{int(x.get('episode_number') or 0):02d}")
        if x.get('search_year'):details.append(str(x['search_year']))
        if x.get('network'):details.append(str(x['network']))
        if show_mode:details.append(f"{g['count']} matching episode(s)")
        people=', '.join((x.get('actors') or [])[:3])
        rows.append(f"<tr><td><input type='checkbox' name='token' value='{e(token)}'></td><td><b>{e(title)}</b><div class='muted small'>{e(' · '.join(details))}</div></td><td>{e(typ)}</td><td>{e(str(x.get('source_type') or '').title())}</td><td>{e(x.get('library_name') or '')}</td><td>{e(people)}</td></tr>")
    result_html=''.join(rows) or ("<tr><td colspan='6' class='empty'>No media matched this search.</td></tr>" if q else "<tr><td colspan='6' class='empty'>Enter a search above. You can then select results for a manual collection or save the search as a Smart Collection.</td></tr>")
    manual_opts=''.join(f"<option value='{r['id']}'>{e(r['name'])}</option>" for r in manual)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    save_smart=''
    add_manual=''
    if q:
        save_smart=f"""<div class='card'><h2>Save As Smart Collection</h2><p class='muted'>The query is saved, not a frozen list. New matching media will appear automatically after future scans/syncs.</p><form method='post' action='/media/search/save-smart'><input type='hidden' name='query' value='{e(q)}'><div class='grid'><div><label>Smart Collection Name</label><input name='name' required placeholder='1980s John Ritter'></div><div><label>Saved Search</label><input value='{e(q)}' disabled></div></div><button>Save As Smart Collection</button></form></div>"""
        add_manual=f"""<div class='card'><h2>Add Selection To Collection</h2><p class='muted'>Select one or more results above, then add them to an existing manual collection or create a new one in the same step.</p><div class='grid'><div><label>Existing Collection</label><select name='collection_id'><option value=''>— choose —</option>{manual_opts}</select></div><div><label>Or Create New Collection</label><input name='new_name' placeholder='Friday Night Favorites'></div></div><button>Add To Collection</button></div>"""
    body=notice+_page_heading('Search','Find media, build manual collections from selected results, or save a search as a Smart Collection.')+f"""
<div class='card'><form method='get' action='/media/search'><label>Search Query</label><div class='grid'><div><input name='q' value='{e(q)}' placeholder='type:episode AND actor:&quot;John Ritter&quot; AND year:1980-1989'></div><div class='toolbar'><button>Search</button><a class='button secondary' href='/media/search'>Clear</a></div></div></form>
<details><summary>Search examples and fields</summary><p class='small muted'>Examples: <code>type:movie AND year:198*</code> · <code>type:episode AND actor:&quot;John Ritter&quot; AND year:1980-1989</code> · <code>type:show AND network:NBC</code> · <code>genre:comedy AND NOT show_title:&quot;Three's Company&quot;</code>. Supported fields: title, show_title, type, actor, director, actor_exact, director_exact, network, genre (TVDB show metadata), library_name, source, year, release_date, season_number, episode_number, plot and status. Operators: AND, OR, NOT and parentheses.</p></details></div>
{save_smart}
<form method='post' action='/media/search/add-to-collection'><input type='hidden' name='return_query' value='{e(q)}'><div class='card'><div class='page-heading'><div><h2>Results</h2><p>{len(display):,} shown{(' (first 500 matching playable items)' if len(results)>=500 else '')}</p></div><button type='button' class='secondary' onclick="document.querySelectorAll('input[name=token]').forEach(x=>x.checked=true)">Select All Shown</button></div><div class='table-wrap'><table><thead><tr><th></th><th>Title</th><th>Type</th><th>Source</th><th>Library</th><th>People</th></tr></thead><tbody>{result_html}</tbody></table></div></div>{add_manual}</form>"""
    return page_shell('Search',body)

def collections_index_page(kind: str='all', msg: str='') -> str:
    wanted={'collections':'manual','smart':'smart','multi':'multi'}.get(kind,'manual')
    with db() as conn:
        cols=[dict(r) for r in conn.execute('SELECT * FROM collections WHERE kind=? ORDER BY name',(wanted,)).fetchall()]
        member_counts={int(r['collection_id']):int(r['n']) for r in conn.execute('SELECT collection_id,COUNT(*) n FROM multi_collection_members GROUP BY collection_id')}
        selection_counts={int(r['collection_id']):int(r['n']) for r in conn.execute('SELECT collection_id,COUNT(*) n FROM collection_selections GROUP BY collection_id')}
    label={'collections':'Collections','smart':'Smart Collections','multi':'Multi Collections'}.get(kind,'Collections')
    rows=[]
    for c in cols:
        cid=int(c['id']); detail=''
        if wanted=='smart':
            try:q=str(json.loads(c.get('rule_json') or '{}').get('query') or '')
            except Exception:q=''
            count=len(media_search_playable(q,10001)) if q else 0
            detail=f"<code>{e(q)}</code>" if q else '<span class=\'muted\'>No saved query</span>'
        elif wanted=='multi':
            count=member_counts.get(cid,0); detail=f"{count} collection member(s)"
        else:
            count=selection_counts.get(cid,0); detail=f"{count} saved selection(s)"
        rows.append(f"<tr><td><b>{e(c['name'])}</b></td><td>{detail}</td><td>{count:,}</td><td>{e((c.get('updated_at') or '')[:19].replace('T',' '))}</td><td><a class='button secondary' href='/studio/collections/{cid}'>Edit</a></td></tr>")
    rows_html=''.join(rows) or f"<tr><td colspan='5' class='empty'>No {e(label.lower())} yet.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    if wanted=='manual':
        actions="<a class='button' href='/media/search'>Search / Select Media</a>"
        create="""<div class='card'><h2>Add Empty Collection</h2><p class='muted'>Create an empty manual collection, then add individual movies, episodes or whole shows from Media → Search.</p><form method='post' action='/studio/collections/add'><input type='hidden' name='kind' value='manual'><div class='grid'><div><label>Name</label><input name='name' required placeholder='Saturday Night Favorites'></div><div style='align-self:end'><button>Add Collection</button></div></div></form></div>"""
        subtitle='Manual collections contain media you explicitly select. Search/browse, tick items, then use Add To Collection.'
    elif wanted=='smart':
        actions="<a class='button' href='/media/search'>Search Media</a>"
        create="""<div class='card'><h2>How Smart Collections Work</h2><p>Search until the results are what you want, then click <b>Save As Smart Collection</b>. ViperTV stores the query and evaluates it dynamically, so later scans and Plex syncs can automatically add or remove matching media.</p><p><a class='button' href='/media/search'>Open Media Search</a></p></div>"""
        subtitle='Dynamic collections created by saving media searches.'
    else:
        actions=''
        create="""<div class='card'><h2>Add Multi Collection</h2><p class='muted'>A Multi Collection combines existing manual and Smart Collections into one reusable programming source.</p><form method='post' action='/studio/collections/add'><input type='hidden' name='kind' value='multi'><div class='grid'><div><label>Name</label><input name='name' required placeholder='All Comedy Shows'></div><div style='align-self:end'><button>Add Multi Collection</button></div></div></form></div>"""
        subtitle='Combine manual Collections and Smart Collections without duplicating their media.'
    body=notice+_page_heading(label,subtitle,actions)+create+f"<div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Definition</th><th>Count</th><th>Updated</th><th></th></tr></thead><tbody>{rows_html}</tbody></table></div></div>"
    return page_shell(label,body)


def playlists_index_page(msg: str='') -> str:
    with db() as conn:
        pls=conn.execute("""SELECT p.*,COUNT(pi.id) item_count FROM playlists p LEFT JOIN playlist_items pi ON pi.playlist_id=p.id
                            GROUP BY p.id ORDER BY p.name COLLATE NOCASE""").fetchall()
    rows=[]
    for p in pls:
        playable=len(playlist_media(int(p['id'])))
        rows.append(f"<tr><td><b>{e(p['name'])}</b></td><td>{int(p['item_count'] or 0)}</td><td>{playable:,}</td><td>{e((p['updated_at'] or '')[:19].replace('T',' '))}</td><td><a class='button secondary' href='/studio/playlists/{p['id']}'>Edit</a></td></tr>")
    rows_html=''.join(rows) or "<tr><td colspan='5' class='empty'>No playlists yet. Create one here, then add TV shows or movies directly from Libraries, TV Shows or Movies.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('Playlists','Ordered programming lists. Add entire TV shows or exact movies from their metadata pages, or add Collections from the playlist editor.')+f"""
<div class='card'><h2>Add Playlist</h2><form method='post' action='/studio/playlists/add'><div class='grid'><div><label>Name</label><input name='name' required placeholder='TGIF Favorites'></div><div style='align-self:end'><button>Create Playlist</button></div></div></form></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Entries</th><th>Playable Media</th><th>Updated</th><th></th></tr></thead><tbody>{rows_html}</tbody></table></div></div>"""
    return page_shell('Playlists',body)


def playlist_edit_page(playlist_id:int,msg:str='')->str:
    with db() as conn:
        p=conn.execute('SELECT * FROM playlists WHERE id=?',(playlist_id,)).fetchone()
        if not p: raise HTTPException(404,'Playlist not found')
        rows=conn.execute('SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall()
        cols=conn.execute("SELECT id,name,kind FROM collections ORDER BY name COLLATE NOCASE").fetchall()
    trs=[]
    for idx,r in enumerate(rows):
        desc=_selection_description(str(r['token']))
        try:
            payload=decode_selection(str(r['token']))
            if payload.get('source_type')=='collection':
                with db() as conn:
                    c=conn.execute('SELECT name,kind FROM collections WHERE id=?',(safe_int(payload.get('collection_id')),)).fetchone()
                desc=f"{str(c['kind']).title()} Collection / {c['name']}" if c else 'Missing Collection'
        except Exception: pass
        up="<button class='secondary' name='direction' value='up' title='Move up'>↑</button>" if idx>0 else ''
        down="<button class='secondary' name='direction' value='down' title='Move down'>↓</button>" if idx<len(rows)-1 else ''
        trs.append(f"<tr><td>{idx+1}</td><td><b>{e(desc)}</b></td><td>{e(str(r['playback_order']).replace('_',' ').title())}</td><td><form class='inline' method='post' action='/studio/playlists/{playlist_id}/items/{r['id']}/move'>{up}{down}</form> <form class='inline' method='post' action='/studio/playlists/{playlist_id}/items/{r['id']}/delete'><button class='danger'>Remove</button></form></td></tr>")
    rows_html=''.join(trs) or "<tr><td colspan='4' class='empty'>This playlist is empty. Add a TV show or movie from Media → Libraries / TV Shows / Movies, or add a Collection below.</td></tr>"
    colopts=''.join(f"<option value='{c['id']}'>{e(c['name'])} ({e(c['kind'])})</option>" for c in cols)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading(str(p['name']),'Playlist entries are played from top to bottom. Each entry may expand to an entire show or Collection.',"<a class='button secondary' href='/lists/playlists'>All Playlists</a>")+f"""
<div class='card'><form method='post' action='/studio/playlists/{playlist_id}/rename'><div class='grid'><div><label>Name</label><input name='name' value='{e(p['name'])}' required></div><div style='align-self:end'><button>Rename</button></div></div></form></div>
<div class='card'><h2>Playlist Entries</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Source</th><th>Playback Order</th><th>Actions</th></tr></thead><tbody>{rows_html}</tbody></table></div></div>
<div class='card'><h2>Add Collection To Playlist</h2><form method='post' action='/studio/playlists/{playlist_id}/add-collection'><div class='grid3'><div><label>Collection</label><select name='collection_id'>{colopts}</select></div><div><label>Playback Order</label><select name='playback_order'><option value='season_episode'>Season / Episode</option><option value='chronological'>Chronological</option><option value='shuffle'>Shuffle</option><option value='random'>Random Daily Order</option></select></div><div style='align-self:end'><button>Add Collection</button></div></div></form></div>
<div class='card'><h2>Use This Playlist</h2><p>Playlists can be selected as a source in a channel's Schedule / Presentation page. A sequential schedule block preserves this playlist's entry order.</p></div>
<div class='card'><h2>Danger Zone</h2><form method='post' action='/studio/playlists/{playlist_id}/delete' onsubmit="return confirm('Delete this playlist? Existing schedule blocks that reference it will no longer have a source.');"><button class='danger'>Delete Playlist</button></form></div>"""
    return page_shell('Playlist',body)


def filler_index_page(msg: str='') -> str:
    with db() as conn:
        fs=conn.execute("SELECT fp.*,l.name library_name FROM filler_presets fp LEFT JOIN libraries l ON l.id=fp.library_id ORDER BY fp.name").fetchall()
        libs=conn.execute("SELECT * FROM libraries ORDER BY name").fetchall()
    rows=''.join(f"<tr><td>{e(x['name'])}</td><td>{e(x['library_name'] or '')}</td><td>Every {x['interval_items']} programme(s)</td><td>{x['max_items']}</td></tr>" for x in fs) or "<tr><td colspan='4' class='empty'>No filler presets.</td></tr>"
    options=''.join(f"<option value='{l['id']}'>{e(l['name'])}</option>" for l in libs)
    body=_page_heading('Filler','Commercials, bumpers, station IDs and other secondary content.')+f"""
<div class='card'><h2>Add Filler Preset</h2><form method='post' action='/studio/fillers/add'>
<div class='grid3'><div><label>Name</label><input name='name' required placeholder='Commercials'></div>
<div><label>Local Library</label><select name='library_id'>{options}</select></div>
<div><label>Insert After N Programmes</label><input type='number' name='interval_items' min='1' value='1'></div></div>
<label>Clips Per Break</label><input type='number' name='max_items' min='1' value='1'><button>Add Filler Preset</button></form></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Library</th><th>Frequency</th><th>Clips</th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    return page_shell('Filler',body)


def schedules_index_page(msg:str='') -> str:
    with db() as conn:
        schedules=conn.execute("""SELECT cs.*,COUNT(DISTINCT csi.id) item_count,COUNT(DISTINCT cp.channel_id) playout_count
          FROM classic_schedules cs
          LEFT JOIN classic_schedule_items csi ON csi.schedule_id=cs.id
          LEFT JOIN classic_playouts cp ON cp.schedule_id=cs.id AND cp.enabled=1
          GROUP BY cs.id ORDER BY cs.name COLLATE NOCASE""").fetchall()
        legacy_count=conn.execute('SELECT COUNT(*) c FROM schedules').fetchone()['c']
    rows=''.join(
        f"<tr><td><b>{e(x['name'])}</b></td><td>{x['item_count']}</td><td>{x['playout_count']}</td>"
        f"<td><a class='button secondary' href='/scheduling/schedules/{x['id']}'>Edit</a> "
        f"<form class='inline' method='post' action='/scheduling/schedules/{x['id']}/clone'><button>Clone</button></form> "
        f"<form class='inline' method='post' action='/scheduling/schedules/{x['id']}/delete' onsubmit=\"return confirm('Delete this schedule? Channels using it will fall back to their normal selections.');\"><button class='danger'>Delete</button></form></td></tr>"
        for x in schedules
    ) or "<tr><td colspan='4' class='empty'>No Classic Schedules yet. Create one below.</td></tr>"
    notice=(f"<div class='msg'>Your {legacy_count} older channel time-block schedule(s) are preserved. New Classic Schedules are reusable and are assigned from <a href='/scheduling/playouts'>Playouts</a>.</div>" if legacy_count else '')
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+_page_heading(
        'Classic Schedules','Reusable, ErsatzTV-style programming schedules. Build a schedule once, then assign it to one or more channels.',
        "<a class='button secondary' href='/scheduling/playouts'>Playouts</a>"
    )+notice+f"""
<div class='card'><h2>Create Schedule</h2><form method='post' action='/scheduling/schedules/add'>
<div class='grid'><div><label>Name</label><input name='name' required placeholder='Weekday TV'></div><div>
<label><input type='checkbox' name='keep_multi_part' value='1' checked> Keep multi-part episodes together</label>
<label><input type='checkbox' name='treat_collections_as_shows' value='1'> Treat Collections as Shows</label>
<label><input type='checkbox' name='shuffle_schedule_items' value='1'> Shuffle schedule items</label>
<label><input type='checkbox' name='random_start_point' value='1'> Random start point</label></div></div><button>Create Schedule</button></form></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>Schedule</th><th>Items</th><th>Playouts</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>How it works</h2><p>A Schedule is the reusable programming recipe. Schedule Items choose a Collection, Smart Collection, Multi Collection, TV Show, TV Season or Playlist, then define start behavior, playback order and playout mode. A Playout assigns that Schedule to a channel and maintains that channel's independent playback position.</p></div>"""
    return page_shell('Schedules',body)


def playouts_index_page(msg:str='') -> str:
    with db() as conn:
        channels=conn.execute("SELECT * FROM channels ORDER BY CAST(number AS REAL),number").fetchall()
        schedules=conn.execute("SELECT * FROM classic_schedules ORDER BY name COLLATE NOCASE").fetchall()
        assigned={int(r['channel_id']):dict(r) for r in conn.execute("""SELECT cp.*,cs.name schedule_name,
          (SELECT COUNT(*) FROM classic_schedule_items i WHERE i.schedule_id=cp.schedule_id) item_count
          FROM classic_playouts cp JOIN classic_schedules cs ON cs.id=cp.schedule_id""")}
    options="<option value=''>— No Classic Schedule —</option>"+''.join(f"<option value='{x['id']}' data-name='{e(x['name'])}'>{e(x['name'])}</option>" for x in schedules)
    rows=[]
    for c in channels:
        a=assigned.get(int(c['id']))
        selected=''.join(f"<option value='{x['id']}' {'selected' if a and int(a['schedule_id'])==int(x['id']) else ''}>{e(x['name'])}</option>" for x in schedules)
        select="<option value=''>— Normal channel selections / legacy blocks —</option>"+selected
        status=(f"{e(a['schedule_name'])} · {a['item_count']} items · generation {a['generation']}" if a else 'Not assigned')
        rows.append(f"<tr><td>{e(c['number'])}</td><td><b>{e(c['name'])}</b></td><td>{status}</td><td>"
                    f"<form class='inline' method='post' action='/scheduling/playouts/{c['id']}/assign'><select name='schedule_id'>{select}</select><button>Assign</button></form> "
                    +(f"<form class='inline' method='post' action='/scheduling/playouts/{c['id']}/reset'><button class='secondary'>Reset Playout</button></form> " if a else '')+
                    f"<a class='button secondary' href='/guide'>Preview</a></td></tr>")
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+_page_heading('Playouts','Assign reusable Classic Schedules to channels. Each channel keeps an independent playout generation and ordering.',"<a class='button secondary' href='/scheduling/schedules'>Schedules</a>")+f"""
<div class='card'><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Playout</th><th></th></tr></thead><tbody>{''.join(rows) if rows else "<tr><td colspan='4' class='empty'>No channels available.</td></tr>"}</tbody></table></div></div>
<div class='card'><h2>Reset Playout</h2><p class='muted'>Resetting a playout starts a new independent generation for that channel. This is useful after changing a schedule or when you want shuffled/random sources to begin from a fresh point.</p></div>"""
    return page_shell('Playouts',body)

def blocks_index_page() -> str:
    with db() as conn:
        templates=conn.execute("SELECT * FROM schedule_templates ORDER BY name").fetchall(); ctemplates=conn.execute("SELECT * FROM channel_templates ORDER BY name").fetchall()
    a=''.join(f"<tr><td>{e(t['name'])}</td><td>Schedule Template</td><td>{e(t['created_at'][:19].replace('T',' '))}</td></tr>" for t in templates)
    b=''.join(f"<tr><td>{e(t['name'])}</td><td>Channel Template</td><td>{e(t['created_at'][:19].replace('T',' '))}</td></tr>" for t in ctemplates)
    rows=a+b or "<tr><td colspan='3' class='empty'>No reusable templates yet.</td></tr>"
    body=_page_heading('Blocks / Templates','Reusable scheduling and channel configurations.')+f"<div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Type</th><th>Created</th></tr></thead><tbody>{rows}</tbody></table></div><p class='muted small'>Save schedule and channel templates from an individual channel's scheduling page.</p></div>"
    return page_shell('Blocks / Templates',body)


def streaming_profiles_page() -> str:
    with db() as conn:
        channels=conn.execute("SELECT * FROM channels ORDER BY CAST(number AS REAL),number").fetchall()
    rows=[]
    for c in channels:
        effective,configured,warn=effective_stream_profile(c)
        rows.append(f"<tr><td>{e(c['number'])}</td><td>{e(c['name'])}</td><td>{e(hwaccel.profile_label(configured))}</td><td>{e(hwaccel.profile_label(effective))}</td><td>{e(c['stream_mode'])}</td><td>{e(c['resolution'])}</td><td>{e(c['video_bitrate'])}</td><td>{e(c['frame_rate'] or '')}</td><td>{e(warn)}</td></tr>")
    trs=''.join(rows) or "<tr><td colspan='9' class='empty'>No channels configured.</td></tr>"
    body=_page_heading('Streaming Profiles','Current channel streaming and transcoding settings.',"<a class='button secondary' href='/system/ffmpeg-profiles'>FFmpeg Profiles</a> <a class='button secondary' href='/system/hardware'>Hardware Acceleration</a>")+f"<div class='card'><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Configured</th><th>Effective</th><th>Mode</th><th>Resolution</th><th>Bitrate</th><th>FPS</th><th>Fallback note</th></tr></thead><tbody>{trs}</tbody></table></div><p class='muted small'>Hardware defaults and encoder tests are managed under System → Hardware Acceleration. Per-channel overrides are also available from Schedule / Presentation.</p></div>"
    return page_shell('Streaming Profiles',body)


# ---------------------------------- routes -----------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, msg: str = ""):
    return home_page(request, msg)



@app.get('/media/local',response_class=HTMLResponse)
def ui_local_media(msg:str=''): return local_libraries_page(msg)
@app.get('/media/libraries',response_class=HTMLResponse)
def ui_libraries(msg:str=''): return libraries_browser_page(msg)
@app.get('/media/libraries/{source}/{library_id}',response_class=HTMLResponse)
def ui_library_browse(source:str,library_id:int,msg:str=''): return library_browse_page(source,library_id,msg)
@app.get('/media/tv/show',response_class=HTMLResponse)
def ui_tv_show(source:str,library_id:int,show_title:str,show_key:str='',msg:str=''): return tv_show_detail_page(source,library_id,show_title,show_key,msg)
@app.get('/media/search',response_class=HTMLResponse)
def ui_media_search(q:str='',msg:str=''): return media_search_page(q,msg)
@app.post('/media/search/save-smart')
def ui_media_search_save_smart(name:str=Form(...),query:str=Form(...)):
    name=name.strip(); query=query.strip()
    if not name or not query: return RedirectResponse('/media/search?q='+quote(query)+'&msg='+quote('Name and search query are required.'),303)
    safe_backup_before_change()
    with db() as conn:
        old=conn.execute('SELECT id,kind FROM collections WHERE name=?',(name,)).fetchone()
        if old and old['kind']!='smart': return RedirectResponse('/media/search?q='+quote(query)+'&msg='+quote('That name is already used by a non-smart collection.'),303)
        payload=json.dumps({'query':query},ensure_ascii=False)
        if old: conn.execute('UPDATE collections SET rule_json=?,updated_at=? WHERE id=?',(payload,utcnow_iso(),old['id']))
        else: conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(name,'smart',payload,utcnow_iso(),utcnow_iso()))
        conn.commit()
    return RedirectResponse('/lists/smart?msg='+quote('Smart Collection saved from search.'),303)
@app.post('/media/search/add-to-collection')
def ui_media_search_add_to_collection(token:list[str]=Form(default=[]),collection_id:str=Form(''),new_name:str=Form(''),return_query:str=Form('')):
    if not token: return RedirectResponse('/media/search?q='+quote(return_query)+'&msg='+quote('Select at least one search result first.'),303)
    safe_backup_before_change()
    with db() as conn:
        cid=safe_int(collection_id)
        if new_name.strip():
            existing=conn.execute('SELECT id,kind FROM collections WHERE name=?',(new_name.strip(),)).fetchone()
            if existing and existing['kind']!='manual': return RedirectResponse('/media/search?q='+quote(return_query)+'&msg='+quote('That name is already used by a Smart or Multi Collection.'),303)
            if existing: cid=int(existing['id'])
            else:
                cur=conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(new_name.strip(),'manual','{}',utcnow_iso(),utcnow_iso()));cid=int(cur.lastrowid)
        if not cid:
            conn.rollback(); return RedirectResponse('/media/search?q='+quote(return_query)+'&msg='+quote('Choose an existing collection or enter a new collection name.'),303)
        c=conn.execute('SELECT kind,name FROM collections WHERE id=?',(cid,)).fetchone()
        if not c or c['kind']!='manual':
            conn.rollback(); return RedirectResponse('/media/search?q='+quote(return_query)+'&msg='+quote('Selected destination is not a manual collection.'),303)
        added=0
        for t in token:
            try: decode_selection(t)
            except Exception: continue
            cur=conn.execute('INSERT OR IGNORE INTO collection_selections(collection_id,token) VALUES(?,?)',(cid,t));added+=max(0,cur.rowcount)
        conn.execute('UPDATE collections SET updated_at=? WHERE id=?',(utcnow_iso(),cid));conn.commit()
        cname=str(c['name'])
    return RedirectResponse('/media/search?q='+quote(return_query)+'&msg='+quote(f'Added {added} selection(s) to {cname}.'),303)
@app.get('/media/tv',response_class=HTMLResponse)
def ui_tv(): return tv_catalog_page()
@app.get('/media/people',response_class=HTMLResponse)
def ui_people(q:str='',msg:str=''): return people_page(q,msg)
@app.get('/media/person/{credit_id}',response_class=HTMLResponse)
def ui_person_detail_by_id(credit_id:int,msg:str=''):
    with db() as conn:
        row=conn.execute('SELECT person_name FROM people_credits WHERE id=?',(credit_id,)).fetchone()
    if not row:
        raise HTTPException(404,'Person not found')
    return person_detail_page(str(row['person_name']),msg)
@app.get('/media/people/detail',response_class=HTMLResponse)
def ui_person_detail(name:str,msg:str=''): return person_detail_page(name,msg)
@app.post('/media/people/create-collection')
def ui_person_create_collection(person_name:str=Form(...),credit_type:str=Form(...),collection_name:str=Form('')):
    person_name=person_name.strip(); credit_type=credit_type.strip().lower(); collection_name=collection_name.strip()
    norm=_person_norm(person_name)
    if credit_type not in ('actor','director') or not norm:
        raise HTTPException(400,'Invalid person or credit type')
    with db() as conn:
        person=conn.execute('SELECT MIN(person_name) person_name FROM people_credits WHERE person_name_norm=? AND credit_type=?',(norm,credit_type)).fetchone()
    if not person or not person['person_name']:
        raise HTTPException(404,'That actor/director credit is not indexed')
    canonical=str(person['person_name'])
    role_label='Actor' if credit_type=='actor' else 'Director'
    base_name=collection_name or f'{canonical} — {role_label}'
    escaped_name=canonical.replace('\\','\\\\').replace('"','\\"')
    query=f'{credit_type}_exact:"{escaped_name}"'
    safe_backup_before_change()
    with db() as conn:
        existing=conn.execute('SELECT * FROM collections WHERE name=?',(base_name,)).fetchone()
        payload=json.dumps({'query':query},ensure_ascii=False)
        if existing and existing['kind']=='smart':
            conn.execute('UPDATE collections SET rule_json=?,updated_at=? WHERE id=?',(payload,utcnow_iso(),existing['id']))
            msg=f'Updated Smart Collection {base_name}.'
        elif existing:
            stem=base_name; n=2
            while conn.execute('SELECT 1 FROM collections WHERE name=?',(f'{stem} ({n})',)).fetchone(): n+=1
            base_name=f'{stem} ({n})'
            conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(base_name,'smart',payload,utcnow_iso(),utcnow_iso()))
            msg=f'Created Smart Collection {base_name}.'
        else:
            conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(base_name,'smart',payload,utcnow_iso(),utcnow_iso()))
            msg=f'Created Smart Collection {base_name}.'
        conn.commit()
    return RedirectResponse(_person_detail_url(canonical)+'&msg='+quote(msg),303)
@app.get('/media/movies',response_class=HTMLResponse)
def ui_movies(): return movies_catalog_page()
@app.get('/media/movies/detail',response_class=HTMLResponse)
def ui_movie_detail(source:str,library_id:int,movie_key:str,msg:str=''): return movie_detail_page(source,library_id,movie_key,msg)
@app.get('/media/youtube',response_class=HTMLResponse)
def ui_youtube(): return youtube_catalog_page()
@app.get('/media/music-videos',response_class=HTMLResponse)
def ui_music_videos(): return music_videos_catalog_page()
@app.get('/media/game-shows',response_class=HTMLResponse)
def ui_game_shows(): return game_shows_catalog_page()
@app.get('/channels',response_class=HTMLResponse)
def ui_channels(msg:str=''): return channels_page(msg)

@app.get('/channels/{channel_id}/clone', response_class=HTMLResponse)
def ui_clone_channel(channel_id:int, msg:str=''):
    return clone_channel_page(channel_id, msg)

@app.post('/channels/{channel_id}/clone')
def clone_channel_copies(
    channel_id:int,
    copies:int=Form(1),
    first_number:int=Form(...),
    number_step:int=Form(1),
    name_base:str=Form(...),
    name_start:int=Form(2),
):
    copies=max(1,min(20,int(copies)))
    number_step=max(1,int(number_step))
    name_start=max(1,int(name_start))
    name_base=name_base.strip()
    if not name_base:
        return RedirectResponse(f'/channels/{channel_id}/clone?msg='+quote('Clone name base is required.'),303)
    desired_numbers=[str(int(first_number)+(i*number_step)) for i in range(copies)]
    try:
        with db() as conn:
            source=conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone()
            if not source: raise HTTPException(404,'Channel not found')
            conflicts=[n for n in desired_numbers if conn.execute('SELECT 1 FROM channels WHERE number=?',(n,)).fetchone()]
            if conflicts:
                return RedirectResponse(f'/channels/{channel_id}/clone?msg='+quote('Channel number(s) already exist: '+', '.join(conflicts)),303)
        safe_backup_before_change()
        created=[]
        with db() as conn:
            for i,num in enumerate(desired_numbers):
                clone_name=f'{name_base} {name_start+i}'
                nid=_copy_channel_configuration(conn,channel_id,num,clone_name)
                created.append((nid,num,clone_name))
            conn.commit()
    except HTTPException:
        raise
    except Exception as exc:
        return RedirectResponse(f'/channels/{channel_id}/clone?msg='+quote('Could not clone channel: '+str(exc)),303)
    detail=', '.join(f'{num} {name}' for _,num,name in created)
    return RedirectResponse('/channels?msg='+quote(f'Created {len(created)} independent clone(s): {detail}'),303)
@app.get('/lists/collections',response_class=HTMLResponse)
def ui_collections(msg:str=''): return collections_index_page('collections',msg)
@app.get('/lists/smart',response_class=HTMLResponse)
def ui_smart(msg:str=''): return collections_index_page('smart',msg)
@app.get('/lists/multi',response_class=HTMLResponse)
def ui_multi(msg:str=''): return collections_index_page('multi',msg)
@app.get('/lists/playlists',response_class=HTMLResponse)
def ui_playlists(msg:str=''): return playlists_index_page(msg)
@app.get('/lists/filler',response_class=HTMLResponse)
def ui_filler(msg:str=''): return filler_index_page(msg)
@app.get('/scheduling/schedules',response_class=HTMLResponse)
def ui_schedules(msg:str=''): return schedules_index_page(msg)
@app.get('/scheduling/playouts',response_class=HTMLResponse)
def ui_playouts(msg:str=''): return playouts_index_page(msg)
@app.get('/scheduling/blocks',response_class=HTMLResponse)
def ui_blocks(): return blocks_index_page()
@app.get('/system/streaming',response_class=HTMLResponse)
def ui_streaming(): return streaming_profiles_page()


# ------------------- ViperTV Classic Schedules / Playouts -------------------
CLASSIC_SOURCE_KINDS={'collection','smart_collection','multi_collection','playlist','tv_show','tv_season','image'}
CLASSIC_PLAYBACK_ORDERS={'chronological','random','shuffle','shuffle_in_order','season_episode'}
CLASSIC_PLAYOUT_MODES={'flood','one','multiple','duration'}


def _classic_touch(schedule_id:int) -> None:
    with db() as conn:
        conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?',(utcnow_iso(),schedule_id));conn.commit()
    _classic_invalidate()


def _classic_source_catalog() -> list[dict[str,str]]:
    out=[]
    with db() as conn:
        for c in conn.execute('SELECT * FROM collections ORDER BY name COLLATE NOCASE'):
            kind={'manual':'collection','smart':'smart_collection','multi':'multi_collection'}.get(str(c['kind']),'collection')
            pretty={'collection':'Collection','smart_collection':'Smart Collection','multi_collection':'Multi Collection'}[kind]
            out.append({'kind':kind,'ref':str(c['id']),'label':f"{pretty} — {c['name']}"})
        for pl in conn.execute('SELECT * FROM playlists ORDER BY name COLLATE NOCASE'):
            out.append({'kind':'playlist','ref':str(pl['id']),'label':f"Playlist — {pl['name']}"})
        # Local shows/seasons
        rows=conn.execute("""SELECT m.library_id,l.name library_name,m.show_title,m.season_number,COUNT(*) cnt
          FROM media m JOIN libraries l ON l.id=m.library_id
          WHERE m.duration>0 AND COALESCE(m.show_title,'')<>''
          GROUP BY m.library_id,m.show_title,m.season_number
          ORDER BY l.name COLLATE NOCASE,m.show_title COLLATE NOCASE,m.season_number""").fetchall()
        seen=set()
        for r in rows:
            key=('local',int(r['library_id']),str(r['show_title']))
            if key not in seen:
                tok=encode_selection({'source_type':'local','selection_type':'show','library_id':int(r['library_id']),'show_title':str(r['show_title'])})
                out.append({'kind':'tv_show','ref':tok,'label':f"TV Show — Local / {r['library_name']} / {r['show_title']}"});seen.add(key)
            if r['season_number'] is not None:
                tok=encode_selection({'source_type':'local','selection_type':'season','library_id':int(r['library_id']),'show_title':str(r['show_title']),'season_number':int(r['season_number'])})
                out.append({'kind':'tv_season','ref':tok,'label':f"TV Season — Local / {r['library_name']} / {r['show_title']} / S{int(r['season_number']):02d}"})
        # Plex shows/seasons
        rows=conn.execute("""SELECT pm.plex_library_id,pl.title library_name,pm.show_title,pm.show_rating_key,pm.season_number,COUNT(*) cnt
          FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
          WHERE pm.duration>0 AND pm.media_type='episode' AND COALESCE(pm.show_title,'')<>''
          GROUP BY pm.plex_library_id,pm.show_rating_key,pm.show_title,pm.season_number
          ORDER BY pl.title COLLATE NOCASE,pm.show_title COLLATE NOCASE,pm.season_number""").fetchall()
        seen=set()
        for r in rows:
            key=('plex',int(r['plex_library_id']),str(r['show_rating_key'] or r['show_title']))
            if key not in seen:
                tok=encode_selection({'source_type':'plex','selection_type':'show','plex_library_id':int(r['plex_library_id']),'show_title':str(r['show_title']),'show_key':str(r['show_rating_key'] or '')})
                out.append({'kind':'tv_show','ref':tok,'label':f"TV Show — Plex / {r['library_name']} / {r['show_title']}"});seen.add(key)
            if r['season_number'] is not None:
                tok=encode_selection({'source_type':'plex','selection_type':'season','plex_library_id':int(r['plex_library_id']),'show_title':str(r['show_title']),'show_key':str(r['show_rating_key'] or ''),'season_number':int(r['season_number'])})
                out.append({'kind':'tv_season','ref':tok,'label':f"TV Season — Plex / {r['library_name']} / {r['show_title']} / S{int(r['season_number']):02d}"})
        # Jellyfin / Emby shows/seasons
        rows=conn.execute("""SELECT em.library_id,el.name library_name,ms.kind,em.show_title,em.season_number,COUNT(*) cnt
          FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id
          WHERE em.duration>0 AND COALESCE(em.show_title,'')<>''
          GROUP BY em.library_id,em.show_title,em.season_number
          ORDER BY ms.kind,el.name COLLATE NOCASE,em.show_title COLLATE NOCASE,em.season_number""").fetchall()
        seen=set()
        for r in rows:
            key=('external',int(r['library_id']),str(r['show_title']))
            server=str(r['kind']).title()
            if key not in seen:
                tok=encode_selection({'source_type':'external','selection_type':'show','external_library_id':int(r['library_id']),'show_title':str(r['show_title'])})
                out.append({'kind':'tv_show','ref':tok,'label':f"TV Show — {server} / {r['library_name']} / {r['show_title']}"});seen.add(key)
            if r['season_number'] is not None:
                tok=encode_selection({'source_type':'external','selection_type':'season','external_library_id':int(r['library_id']),'show_title':str(r['show_title']),'season_number':int(r['season_number'])})
                out.append({'kind':'tv_season','ref':tok,'label':f"TV Season — {server} / {r['library_name']} / {r['show_title']} / S{int(r['season_number']):02d}"})
    return out


def _classic_source_label(kind:str, ref:str) -> str:
    try:
        with db() as conn:
            if kind in ('collection','smart_collection','multi_collection'):
                r=conn.execute('SELECT name,kind FROM collections WHERE id=?',(int(ref),)).fetchone()
                if r:return f"{ {'manual':'Collection','smart':'Smart Collection','multi':'Multi Collection'}.get(str(r['kind']),'Collection') } — {r['name']}"
            if kind=='playlist':
                r=conn.execute('SELECT name FROM playlists WHERE id=?',(int(ref),)).fetchone()
                if r:return f"Playlist — {r['name']}"
        if kind in ('tv_show','tv_season'):
            d=decode_selection(ref); return _selection_human_label(d,kind)
    except Exception:pass
    return f'{kind} — missing source'


def _selection_human_label(d:dict[str,Any],kind:str='tv_show')->str:
    st=str(d.get('source_type') or '').title(); title=str(d.get('show_title') or 'Unknown Show')
    if kind=='tv_season' or d.get('selection_type')=='season':
        return f"TV Season — {st} / {title} / S{safe_int(d.get('season_number')) or 0:02d}"
    return f"TV Show — {st} / {title}"


def _classic_source_options(selected_kind:str='',selected_ref:str='')->str:
    opts=[]
    for x in _classic_source_catalog():
        sel='selected' if x['kind']==selected_kind and x['ref']==selected_ref else ''
        opts.append(f"<option value='{e(x['kind']+'|'+x['ref'])}' {sel}>{e(x['label'])}</option>")
    return ''.join(opts) or "<option value=''>No Collections, Playlists or TV shows are indexed yet</option>"


def _classic_item_form(schedule_id:int,item:sqlite3.Row|None=None)->str:
    x=dict(item) if item else {}
    iid=x.get('id'); action=f"/scheduling/schedule-item/{iid}/save" if iid else f"/scheduling/schedules/{schedule_id}/items/add"
    kind=str(x.get('source_kind') or '');ref=str(x.get('source_ref') or '')
    start_type=str(x.get('start_type') or 'dynamic');fixed=str(x.get('fixed_behavior') or 'flexible')
    order=str(x.get('playback_order') or 'chronological');mode=str(x.get('playout_mode') or 'one')
    mmode=str(x.get('multiple_mode') or 'count');group=str(x.get('fill_group_mode') or 'none');tail=str(x.get('tail_mode') or 'none');guide=str(x.get('guide_mode') or 'normal')
    fillers=[]
    with db() as conn: fillers=conn.execute("SELECT * FROM collections WHERE kind IN ('manual','smart') ORDER BY name COLLATE NOCASE").fetchall()
    filler_options="<option value=''>— None —</option>"+''.join(f"<option value='{c['id']}' {'selected' if x.get('filler_collection_id')==c['id'] else ''}>{e(c['name'])}</option>" for c in fillers)
    start_val=_min_to_hm(int(x.get('start_minute') or 0))
    return f"""<form method='post' action='{action}'>
<div class='grid3'><div><label>Label</label><input name='label' value='{e(x.get('label') or '')}' placeholder='Prime Time / Sitcom / Movie'></div>
<div><label>Start Type</label><select name='start_type'><option value='dynamic' {'selected' if start_type=='dynamic' else ''}>Dynamic — immediately after previous item</option><option value='fixed' {'selected' if start_type=='fixed' else ''}>Fixed — start at a clock time</option></select></div>
<div><label>Fixed Start Time</label><input type='time' name='start_time' value='{start_val}'></div></div>
<div class='grid3'><div><label>Fixed Start Behavior</label><select name='fixed_behavior'><option value='flexible' {'selected' if fixed=='flexible' else ''}>Flexible</option><option value='strict' {'selected' if fixed=='strict' else ''}>Strict</option></select></div>
<div style='grid-column:span 2'><label>Collection / Show / Playlist</label><select name='source_choice' required>{_classic_source_options(kind,ref)}</select></div></div>
<div class='grid3'><div><label>Playback Order</label><select name='playback_order'>
<option value='chronological' {'selected' if order=='chronological' else ''}>Chronological</option><option value='season_episode' {'selected' if order=='season_episode' else ''}>Season, Episode</option><option value='shuffle' {'selected' if order=='shuffle' else ''}>Shuffle — no repeat until pool exhausted</option><option value='shuffle_in_order' {'selected' if order=='shuffle_in_order' else ''}>Shuffle In Order</option><option value='random' {'selected' if order=='random' else ''}>Random — repeats allowed</option></select></div>
<div><label>Playout Mode</label><select name='playout_mode'><option value='one' {'selected' if mode=='one' else ''}>One</option><option value='multiple' {'selected' if mode=='multiple' else ''}>Multiple</option><option value='duration' {'selected' if mode=='duration' else ''}>Duration</option><option value='flood' {'selected' if mode=='flood' else ''}>Flood</option></select></div>
<div><label>Multiple Mode</label><select name='multiple_mode'><option value='count' {'selected' if mmode=='count' else ''}>Count</option><option value='collection_size' {'selected' if mmode=='collection_size' else ''}>Collection Size</option><option value='multi_episode_group_size' {'selected' if mmode=='multi_episode_group_size' else ''}>Multi-Episode Group Size</option><option value='playlist_item_size' {'selected' if mmode=='playlist_item_size' else ''}>Playlist Item Size</option></select></div></div>
<div class='grid3'><div><label>Multiple Count</label><input type='number' min='1' max='1000' name='multiple_count' value='{int(x.get('multiple_count') or 1)}'></div>
<div><label>Playout Duration (minutes)</label><input type='number' min='1' max='1440' name='playout_duration_minutes' value='{int(x.get('playout_duration_minutes') or 30)}'></div>
<div><label>Discard To Fill Attempts</label><input type='number' min='0' max='100' name='discard_attempts' value='{int(x.get('discard_attempts') or 0)}'></div></div>
<div class='grid3'><div><label>Fill With Group</label><select name='fill_group_mode'><option value='none' {'selected' if group=='none' else ''}>None</option><option value='ordered' {'selected' if group=='ordered' else ''}>Ordered Groups</option><option value='shuffled' {'selected' if group=='shuffled' else ''}>Shuffled Groups</option></select></div>
<div><label>Duration Tail</label><select name='tail_mode'><option value='none' {'selected' if tail=='none' else ''}>None — advance immediately</option><option value='offline' {'selected' if tail=='offline' else ''}>Offline / black until block ends</option><option value='filler' {'selected' if tail=='filler' else ''}>Filler Collection</option></select></div>
<div><label>Tail Filler Collection</label><select name='filler_collection_id'>{filler_options}</select></div></div>
<div class='grid'><div><label>Custom EPG Title</label><input name='custom_title' value='{e(x.get('custom_title') or '')}' placeholder='Saturday Morning Cartoons'></div><div><label>Guide Mode</label><select name='guide_mode'><option value='normal' {'selected' if guide=='normal' else ''}>Normal — show in guide</option><option value='filler' {'selected' if guide=='filler' else ''}>Filler — hide from guide</option></select></div></div>
<button>{'Save Item' if iid else 'Add Schedule Item'}</button></form>"""


@app.post('/scheduling/schedules/add')
def classic_schedule_add(name:str=Form(...),keep_multi_part:int=Form(0),treat_collections_as_shows:int=Form(0),shuffle_schedule_items:int=Form(0),random_start_point:int=Form(0)):
    now=utcnow_iso()
    try:
        with db() as conn:
            cur=conn.execute('INSERT INTO classic_schedules(name,keep_multi_part,treat_collections_as_shows,shuffle_schedule_items,random_start_point,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name.strip(),1 if keep_multi_part else 0,1 if treat_collections_as_shows else 0,1 if shuffle_schedule_items else 0,1 if random_start_point else 0,now,now));conn.commit();sid=cur.lastrowid
        return RedirectResponse(f'/scheduling/schedules/{sid}?msg='+quote('Schedule created. Add programming items below.'),303)
    except sqlite3.IntegrityError:
        return RedirectResponse('/scheduling/schedules?msg='+quote('A schedule with that name already exists.'),303)


@app.get('/scheduling/schedules/{schedule_id}',response_class=HTMLResponse)
def classic_schedule_edit(schedule_id:int,msg:str=''):
    with db() as conn:
        sch=conn.execute('SELECT * FROM classic_schedules WHERE id=?',(schedule_id,)).fetchone()
        if not sch:raise HTTPException(404,'Schedule not found')
        items=conn.execute('SELECT * FROM classic_schedule_items WHERE schedule_id=? ORDER BY position,id',(schedule_id,)).fetchall()
        playouts=conn.execute("SELECT c.number,c.name FROM classic_playouts cp JOIN channels c ON c.id=cp.channel_id WHERE cp.schedule_id=? ORDER BY CAST(c.number AS REAL),c.number",(schedule_id,)).fetchall()
    rows=[]
    for i in items:
        start='Dynamic' if i['start_type']=='dynamic' else f"Fixed {_min_to_hm(int(i['start_minute'] or 0))} ({e(i['fixed_behavior'])})"
        mode=e(i['playout_mode'])
        if i['playout_mode']=='multiple':mode+=f" / {e(i['multiple_mode'])}"+(f" ×{i['multiple_count']}" if i['multiple_mode']=='count' else '')
        elif i['playout_mode']=='duration':mode+=f" / {i['playout_duration_minutes']} min"
        rows.append(f"<tr><td>{int(i['position'])+1}</td><td>{e(i['label'] or '')}</td><td>{start}</td><td>{e(_classic_source_label(str(i['source_kind']),str(i['source_ref'])))}</td><td>{e(i['playback_order'])}</td><td>{mode}</td><td>{e(i['custom_title'] or '')}</td><td>"
                    f"<a class='button secondary' href='/scheduling/schedule-item/{i['id']}'>Edit</a> "
                    f"<form class='inline' method='post' action='/scheduling/schedule-item/{i['id']}/move'><input type='hidden' name='direction' value='up'><button>↑</button></form> "
                    f"<form class='inline' method='post' action='/scheduling/schedule-item/{i['id']}/move'><input type='hidden' name='direction' value='down'><button>↓</button></form> "
                    f"<form class='inline' method='post' action='/scheduling/schedule-item/{i['id']}/delete'><button class='danger'>Delete</button></form></td></tr>")
    used=', '.join(f"{e(x['number'])} {e(x['name'])}" for x in playouts) or 'Not assigned to a channel yet.'
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+_page_heading(e(sch['name']),'Classic Schedule editor — items run in order and the schedule loops continuously.',"<a class='button secondary' href='/scheduling/schedules'>All Schedules</a> <a class='button secondary' href='/scheduling/playouts'>Playouts</a>")+f"""
<div class='card'><h2>Schedule Settings</h2><form method='post' action='/scheduling/schedules/{schedule_id}/settings'><div class='grid'><div><label>Name</label><input name='name' value='{e(sch['name'])}' required></div><div>
<label><input type='checkbox' name='keep_multi_part' value='1' {'checked' if sch['keep_multi_part'] else ''}> Keep multi-part episodes together</label>
<label><input type='checkbox' name='treat_collections_as_shows' value='1' {'checked' if sch['treat_collections_as_shows'] else ''}> Treat Collections as Shows</label>
<label><input type='checkbox' name='shuffle_schedule_items' value='1' {'checked' if sch['shuffle_schedule_items'] else ''}> Shuffle schedule items</label>
<label><input type='checkbox' name='random_start_point' value='1' {'checked' if sch['random_start_point'] else ''}> Random start point</label></div></div><button>Save Schedule Settings</button></form><p class='muted'>Assigned playouts: {used}</p></div>
<div class='card'><h2>Schedule Items</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Label</th><th>Start</th><th>Source</th><th>Order</th><th>Playout</th><th>EPG title</th><th></th></tr></thead><tbody>{''.join(rows) if rows else "<tr><td colspan='8' class='empty'>No items yet.</td></tr>"}</tbody></table></div></div>
<div class='card'><h2>Add Schedule Item</h2>{_classic_item_form(schedule_id)}</div>
<div class='card'><h2>ErsatzTV-style behavior</h2><p><b>Dynamic</b> starts after the previous item. <b>Fixed</b> targets an exact clock time. <b>One</b> rotates one programme, <b>Multiple</b> rotates a count/group, <b>Duration</b> fills a time budget, and <b>Flood</b> runs until the next fixed start (or the end of the broadcast day). Shuffle Schedule Items intentionally treats fixed starts as dynamic and flood as one, matching the practical limitation of shuffled classic schedules.</p></div>"""
    return page_shell('Edit Schedule',body)


@app.post('/scheduling/schedules/{schedule_id}/settings')
def classic_schedule_settings(schedule_id:int,name:str=Form(...),keep_multi_part:int=Form(0),treat_collections_as_shows:int=Form(0),shuffle_schedule_items:int=Form(0),random_start_point:int=Form(0)):
    try:
        with db() as conn:
            conn.execute('UPDATE classic_schedules SET name=?,keep_multi_part=?,treat_collections_as_shows=?,shuffle_schedule_items=?,random_start_point=?,updated_at=? WHERE id=?',(name.strip(),1 if keep_multi_part else 0,1 if treat_collections_as_shows else 0,1 if shuffle_schedule_items else 0,1 if random_start_point else 0,utcnow_iso(),schedule_id));conn.commit()
        _classic_invalidate();return RedirectResponse(f'/scheduling/schedules/{schedule_id}?msg=Schedule+settings+saved',303)
    except sqlite3.IntegrityError:return RedirectResponse(f'/scheduling/schedules/{schedule_id}?msg='+quote('That schedule name is already in use.'),303)


def _classic_parse_item_form(source_choice:str,start_type:str,start_time:str,fixed_behavior:str,playback_order:str,playout_mode:str,multiple_mode:str,multiple_count:int,playout_duration_minutes:int,fill_group_mode:str,tail_mode:str,filler_collection_id:str,discard_attempts:int,custom_title:str,guide_mode:str,label:str)->dict[str,Any]:
    try:kind,ref=source_choice.split('|',1)
    except Exception:raise ValueError('Choose a programming source.')
    if kind not in CLASSIC_SOURCE_KINDS:raise ValueError('Invalid source type.')
    if playback_order not in CLASSIC_PLAYBACK_ORDERS:playback_order='chronological'
    if playout_mode not in CLASSIC_PLAYOUT_MODES:playout_mode='one'
    if start_type not in ('dynamic','fixed'):start_type='dynamic'
    if fixed_behavior not in ('strict','flexible'):fixed_behavior='flexible'
    if multiple_mode not in ('count','collection_size','multi_episode_group_size','playlist_item_size'):multiple_mode='count'
    if fill_group_mode not in ('none','ordered','shuffled'):fill_group_mode='none'
    if tail_mode not in ('none','offline','filler'):tail_mode='none'
    if guide_mode not in ('normal','filler'):guide_mode='normal'
    start_minute=_hm_to_min(start_time) if start_type=='fixed' else None
    return {'label':label.strip() or None,'start_type':start_type,'start_minute':start_minute,'fixed_behavior':fixed_behavior,'source_kind':kind,'source_ref':ref,
      'playback_order':playback_order,'playout_mode':playout_mode,'multiple_mode':multiple_mode,'multiple_count':max(1,min(1000,int(multiple_count or 1))),
      'playout_duration_minutes':max(1,min(1440,int(playout_duration_minutes or 30))),'fill_group_mode':fill_group_mode,'tail_mode':tail_mode,
      'filler_collection_id':int(filler_collection_id) if str(filler_collection_id or '').isdigit() else None,'discard_attempts':max(0,min(100,int(discard_attempts or 0))),
      'custom_title':custom_title.strip() or None,'guide_mode':guide_mode}


@app.post('/scheduling/schedules/{schedule_id}/items/add')
def classic_item_add(schedule_id:int,source_choice:str=Form(...),label:str=Form(''),start_type:str=Form('dynamic'),start_time:str=Form('00:00'),fixed_behavior:str=Form('flexible'),playback_order:str=Form('chronological'),playout_mode:str=Form('one'),multiple_mode:str=Form('count'),multiple_count:int=Form(1),playout_duration_minutes:int=Form(30),fill_group_mode:str=Form('none'),tail_mode:str=Form('none'),filler_collection_id:str=Form(''),discard_attempts:int=Form(0),custom_title:str=Form(''),guide_mode:str=Form('normal')):
    try:d=_classic_parse_item_form(source_choice,start_type,start_time,fixed_behavior,playback_order,playout_mode,multiple_mode,multiple_count,playout_duration_minutes,fill_group_mode,tail_mode,filler_collection_id,discard_attempts,custom_title,guide_mode,label)
    except Exception as ex:return RedirectResponse(f'/scheduling/schedules/{schedule_id}?msg='+quote(str(ex)),303)
    with db() as conn:
        pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM classic_schedule_items WHERE schedule_id=?',(schedule_id,)).fetchone()['p'])
        conn.execute("""INSERT INTO classic_schedule_items(schedule_id,position,label,start_type,start_minute,fixed_behavior,source_kind,source_ref,playback_order,playout_mode,multiple_mode,multiple_count,playout_duration_minutes,fill_group_mode,tail_mode,filler_collection_id,discard_attempts,custom_title,guide_mode,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(schedule_id,pos,d['label'],d['start_type'],d['start_minute'],d['fixed_behavior'],d['source_kind'],d['source_ref'],d['playback_order'],d['playout_mode'],d['multiple_mode'],d['multiple_count'],d['playout_duration_minutes'],d['fill_group_mode'],d['tail_mode'],d['filler_collection_id'],d['discard_attempts'],d['custom_title'],d['guide_mode'],utcnow_iso()));conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?',(utcnow_iso(),schedule_id));conn.commit()
    _classic_invalidate();return RedirectResponse(f'/scheduling/schedules/{schedule_id}?msg=Schedule+item+added',303)


@app.get('/scheduling/schedule-item/{item_id}',response_class=HTMLResponse)
def classic_item_edit(item_id:int,msg:str=''):
    with db() as conn:
        item=conn.execute('SELECT * FROM classic_schedule_items WHERE id=?',(item_id,)).fetchone();
        if not item:raise HTTPException(404,'Schedule item not found')
        sch=conn.execute('SELECT * FROM classic_schedules WHERE id=?',(item['schedule_id'],)).fetchone()
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+_page_heading('Edit Schedule Item',str(sch['name']),f"<a class='button secondary' href='/scheduling/schedules/{sch['id']}'>Back to Schedule</a>")+f"<div class='card'>{_classic_item_form(int(sch['id']),item)}</div>"
    return page_shell('Edit Schedule Item',body)


@app.post('/scheduling/schedule-item/{item_id}/save')
def classic_item_save(item_id:int,source_choice:str=Form(...),label:str=Form(''),start_type:str=Form('dynamic'),start_time:str=Form('00:00'),fixed_behavior:str=Form('flexible'),playback_order:str=Form('chronological'),playout_mode:str=Form('one'),multiple_mode:str=Form('count'),multiple_count:int=Form(1),playout_duration_minutes:int=Form(30),fill_group_mode:str=Form('none'),tail_mode:str=Form('none'),filler_collection_id:str=Form(''),discard_attempts:int=Form(0),custom_title:str=Form(''),guide_mode:str=Form('normal')):
    with db() as conn:r=conn.execute('SELECT schedule_id FROM classic_schedule_items WHERE id=?',(item_id,)).fetchone()
    if not r:raise HTTPException(404)
    sid=int(r['schedule_id'])
    try:d=_classic_parse_item_form(source_choice,start_type,start_time,fixed_behavior,playback_order,playout_mode,multiple_mode,multiple_count,playout_duration_minutes,fill_group_mode,tail_mode,filler_collection_id,discard_attempts,custom_title,guide_mode,label)
    except Exception as ex:return RedirectResponse(f'/scheduling/schedule-item/{item_id}?msg='+quote(str(ex)),303)
    with db() as conn:
        conn.execute("""UPDATE classic_schedule_items SET label=?,start_type=?,start_minute=?,fixed_behavior=?,source_kind=?,source_ref=?,playback_order=?,playout_mode=?,multiple_mode=?,multiple_count=?,playout_duration_minutes=?,fill_group_mode=?,tail_mode=?,filler_collection_id=?,discard_attempts=?,custom_title=?,guide_mode=? WHERE id=?""",(d['label'],d['start_type'],d['start_minute'],d['fixed_behavior'],d['source_kind'],d['source_ref'],d['playback_order'],d['playout_mode'],d['multiple_mode'],d['multiple_count'],d['playout_duration_minutes'],d['fill_group_mode'],d['tail_mode'],d['filler_collection_id'],d['discard_attempts'],d['custom_title'],d['guide_mode'],item_id));conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?',(utcnow_iso(),sid));conn.commit()
    _classic_invalidate();return RedirectResponse(f'/scheduling/schedules/{sid}?msg=Schedule+item+saved',303)


@app.post('/scheduling/schedule-item/{item_id}/move')
def classic_item_move(item_id:int,direction:str=Form(...)):
    with db() as conn:
        cur=conn.execute('SELECT * FROM classic_schedule_items WHERE id=?',(item_id,)).fetchone()
        if not cur:raise HTTPException(404)
        op='<' if direction=='up' else '>'; order='DESC' if direction=='up' else 'ASC'
        other=conn.execute(f'SELECT * FROM classic_schedule_items WHERE schedule_id=? AND position {op} ? ORDER BY position {order},id {order} LIMIT 1',(cur['schedule_id'],cur['position'])).fetchone()
        if other:
            conn.execute('UPDATE classic_schedule_items SET position=? WHERE id=?',(other['position'],cur['id']));conn.execute('UPDATE classic_schedule_items SET position=? WHERE id=?',(cur['position'],other['id']))
            conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?',(utcnow_iso(),cur['schedule_id']));conn.commit()
    _classic_invalidate();return RedirectResponse(f"/scheduling/schedules/{cur['schedule_id']}",303)


@app.post('/scheduling/schedule-item/{item_id}/delete')
def classic_item_delete(item_id:int):
    with db() as conn:
        r=conn.execute('SELECT schedule_id FROM classic_schedule_items WHERE id=?',(item_id,)).fetchone()
        if not r:return RedirectResponse('/scheduling/schedules',303)
        sid=int(r['schedule_id']);conn.execute('DELETE FROM classic_schedule_items WHERE id=?',(item_id,));conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?',(utcnow_iso(),sid));conn.commit()
    _classic_invalidate();return RedirectResponse(f'/scheduling/schedules/{sid}?msg=Item+deleted',303)


@app.post('/scheduling/schedules/{schedule_id}/clone')
def classic_schedule_clone(schedule_id:int):
    with db() as conn:
        src=conn.execute('SELECT * FROM classic_schedules WHERE id=?',(schedule_id,)).fetchone()
        if not src:raise HTTPException(404)
        base=str(src['name'])+' Copy';name=base;n=2
        while conn.execute('SELECT 1 FROM classic_schedules WHERE name=?',(name,)).fetchone():name=f'{base} {n}';n+=1
        now=utcnow_iso();cur=conn.execute('INSERT INTO classic_schedules(name,keep_multi_part,treat_collections_as_shows,shuffle_schedule_items,random_start_point,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(name,src['keep_multi_part'],src['treat_collections_as_shows'],src['shuffle_schedule_items'],src['random_start_point'],now,now));nid=cur.lastrowid
        for i in conn.execute('SELECT * FROM classic_schedule_items WHERE schedule_id=? ORDER BY position,id',(schedule_id,)):
            conn.execute("""INSERT INTO classic_schedule_items(schedule_id,position,label,start_type,start_minute,fixed_behavior,source_kind,source_ref,playback_order,playout_mode,multiple_mode,multiple_count,playout_duration_minutes,fill_group_mode,tail_mode,filler_collection_id,discard_attempts,custom_title,guide_mode,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(nid,i['position'],i['label'],i['start_type'],i['start_minute'],i['fixed_behavior'],i['source_kind'],i['source_ref'],i['playback_order'],i['playout_mode'],i['multiple_mode'],i['multiple_count'],i['playout_duration_minutes'],i['fill_group_mode'],i['tail_mode'],i['filler_collection_id'],i['discard_attempts'],i['custom_title'],i['guide_mode'],now))
        conn.commit()
    return RedirectResponse(f'/scheduling/schedules/{nid}?msg=Schedule+cloned',303)


@app.post('/scheduling/schedules/{schedule_id}/delete')
def classic_schedule_delete(schedule_id:int):
    with db() as conn:conn.execute('DELETE FROM classic_schedules WHERE id=?',(schedule_id,));conn.commit()
    _classic_invalidate();return RedirectResponse('/scheduling/schedules?msg=Schedule+deleted',303)


@app.post('/scheduling/playouts/{channel_id}/assign')
def classic_playout_assign(channel_id:int,schedule_id:str=Form('')):
    now=utcnow_iso()
    with db() as conn:
        if schedule_id and schedule_id.isdigit():
            if not conn.execute('SELECT 1 FROM classic_schedules WHERE id=?',(int(schedule_id),)).fetchone():raise HTTPException(404,'Schedule not found')
            old=conn.execute('SELECT schedule_id,generation FROM classic_playouts WHERE channel_id=?',(channel_id,)).fetchone();gen=(int(old['generation'])+1 if old and int(old['schedule_id'])!=int(schedule_id) else int(old['generation']) if old else 0)
            conn.execute('INSERT INTO classic_playouts(channel_id,schedule_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET schedule_id=excluded.schedule_id,enabled=1,generation=?,updated_at=excluded.updated_at',(channel_id,int(schedule_id),1,gen,now,now,gen))
            # Scheduling modes are mutually exclusive in v1.2.0.
            conn.execute('DELETE FROM block_playouts WHERE channel_id=?',(channel_id,))
            conn.execute('DELETE FROM sequential_playouts WHERE channel_id=?',(channel_id,))
        else:conn.execute('DELETE FROM classic_playouts WHERE channel_id=?',(channel_id,))
        conn.commit()
    _classic_invalidate(channel_id);return RedirectResponse('/scheduling/playouts?msg=Playout+assignment+saved',303)


@app.post('/scheduling/playouts/{channel_id}/reset')
def classic_playout_reset(channel_id:int):
    with db() as conn:
        conn.execute('UPDATE classic_playouts SET generation=generation+1,updated_at=? WHERE channel_id=?',(utcnow_iso(),channel_id));conn.execute("DELETE FROM playout_state WHERE channel_id=? AND source_key LIKE 'classic:%'",(channel_id,));conn.commit()
    _classic_invalidate(channel_id);return RedirectResponse('/scheduling/playouts?msg=Playout+reset',303)


# =========================== Manual Live IPTV source ========================

def init_live_stream_db() -> None:
    """Persistent user-managed HLS/M3U8 channels.

    These are intentionally independent of ViperTV's generated playout channels
    and Pluto discovery rows. The user supplies the upstream HLS URL and ViperTV
    publishes a stable channel number plus a signed HLS proxy endpoint.
    """
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS live_streams(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          number TEXT NOT NULL UNIQUE,
          name TEXT NOT NULL,
          stream_url TEXT NOT NULL,
          logo_url TEXT,
          group_name TEXT,
          user_agent TEXT,
          referer TEXT,
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_live_streams_enabled_number
          ON live_streams(enabled,number,name);
        """)
        conn.commit()
    if not get_setting('live_proxy_secret'):
        set_setting('live_proxy_secret', uuid.uuid4().hex + uuid.uuid4().hex)


def _validate_live_hls_url(value: str) -> str:
    value=(value or '').strip()
    if not re.match(r'^https?://', value, re.I):
        raise ValueError('Stream URL must begin with http:// or https://')
    if len(value)>8192:
        raise ValueError('Stream URL is too long')
    return value


def _live_number_in_use(number: str, exclude_live_id: int | None = None) -> bool:
    number=str(number or '').strip()
    if not number:
        return True
    with db() as conn:
        if conn.execute('SELECT 1 FROM channels WHERE number=? LIMIT 1',(number,)).fetchone():
            return True
        q='SELECT 1 FROM live_streams WHERE number=?'
        args=[number]
        if exclude_live_id is not None:
            q+=' AND id<>?'; args.append(int(exclude_live_id))
        if conn.execute(q+' LIMIT 1',tuple(args)).fetchone():
            return True
        if conn.execute('SELECT 1 FROM pluto_channels WHERE imported=1 AND display_number=? LIMIT 1',(number,)).fetchone():
            return True
    return False


def _live_row(stream_id: int) -> sqlite3.Row:
    with db() as conn:
        row=conn.execute('SELECT * FROM live_streams WHERE id=?',(int(stream_id),)).fetchone()
    if not row:
        raise HTTPException(404,'Live IPTV channel not found')
    return row


def _live_headers(row: sqlite3.Row, range_header: str | None = None) -> dict[str,str]:
    headers={
        'Accept':'*/*',
        'User-Agent':str(row['user_agent'] or '').strip() or f'{APP_NAME}/{APP_VERSION}',
    }
    referer=str(row['referer'] or '').strip()
    if referer:
        headers['Referer']=referer
    if range_header:
        headers['Range']=range_header
    return headers


def _live_proxy_secret() -> bytes:
    secret=get_setting('live_proxy_secret','') or ''
    if not secret:
        secret=uuid.uuid4().hex+uuid.uuid4().hex
        set_setting('live_proxy_secret',secret)
    return secret.encode('utf-8')


def _live_proxy_token(url: str) -> str:
    payload=base64.urlsafe_b64encode(url.encode('utf-8')).decode('ascii').rstrip('=')
    sig=hmac.new(_live_proxy_secret(),payload.encode('ascii'),hashlib.sha256).hexdigest()[:32]
    return payload+'.'+sig


def _live_proxy_decode(token: str) -> str:
    try:
        payload,sig=token.rsplit('.',1)
        wanted=hmac.new(_live_proxy_secret(),payload.encode('ascii'),hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig,wanted):
            raise ValueError('signature')
        padded=payload+'='*(-len(payload)%4)
        url=base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
        return _validate_live_hls_url(url)
    except Exception:
        raise HTTPException(400,'Invalid live-stream proxy token')


def _live_local_proxy_url(public_base: str, stream_id: int, target: str) -> str:
    return f"{public_base}/stream/live/{int(stream_id)}/proxy/{_live_proxy_token(target)}"


def _live_rewrite_playlist(text: str, source_url: str, stream_id: int, public_base: str) -> str:
    """Rewrite every HLS child URI through ViperTV.

    Keeping variant manifests, media segments, encryption keys and init maps on
    the same proxy path means optional User-Agent/Referer settings keep applying
    after the root manifest is loaded. Signed child URLs prevent the endpoint
    from becoming an arbitrary open HTTP proxy.
    """
    out=[]
    uri_attr=re.compile(r'URI=("|\')([^"\']+)(\1)')
    for line in text.replace('\r\n','\n').replace('\r','\n').split('\n'):
        stripped=line.strip()
        if not stripped:
            out.append(line); continue
        if stripped.startswith('#'):
            def repl(m):
                q=m.group(1)
                target=urljoin(source_url,m.group(2))
                return 'URI='+q+_live_local_proxy_url(public_base,stream_id,target)+q
            out.append(uri_attr.sub(repl,line)); continue
        target=urljoin(source_url,stripped)
        out.append(_live_local_proxy_url(public_base,stream_id,target))
    return '\n'.join(out).rstrip()+'\n'


def _live_open(row: sqlite3.Row, url: str, range_header: str | None = None):
    req=URLRequest(url,headers=_live_headers(row,range_header))
    return urlopen(req,timeout=20)


def _live_root_playlist(stream_id: int, public_base: str) -> PlainTextResponse:
    row=_live_row(stream_id)
    try:
        url=_validate_live_hls_url(str(row['stream_url']))
        with _live_open(row,url) as resp:
            raw=resp.read(4*1024*1024)
            final_url=resp.geturl() or url
        text=raw.decode('utf-8',errors='replace')
        if '#EXTM3U' not in text[:1024]:
            raise RuntimeError('source did not return an HLS/M3U8 playlist')
        text=_live_rewrite_playlist(text,final_url,stream_id,public_base)
        return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={
            'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','X-Accel-Buffering':'no'
        })
    except HTTPException:
        raise
    except Exception as exc:
        print(f'Live IPTV root failed: id={stream_id} name={row["name"]} error={exc}',flush=True)
        raise HTTPException(502,f'Unable to open live HLS source: {exc}')


def _live_binary_iter(resp):
    try:
        while True:
            chunk=resp.read(128*1024)
            if not chunk:
                break
            yield chunk
    finally:
        try: resp.close()
        except Exception: pass


def live_stream_channels_card() -> str:
    try:
        with db() as conn:
            rows=conn.execute('SELECT * FROM live_streams WHERE enabled=1 ORDER BY CAST(number AS REAL),number,name').fetchall()
    except Exception:
        return ''
    if not rows:
        return "<div class='card'><div class='page-heading'><div><h2>Live IPTV Channels</h2><p>No manual M3U8 channels added.</p></div><a class='button secondary' href='/live'>Add Live IPTV</a></div></div>"
    body=''.join(
        f"<tr><td><b>{e(r['number'])}</b></td><td>{e(r['name'])}</td><td>{e(r['group_name'] or 'Live IPTV')}</td><td><a class='button' href='/watch/live/{r['id']}'>Watch</a> <a class='button secondary' href='/live/{r['id']}/edit'>Edit</a></td></tr>"
        for r in rows[:250]
    )
    more=f"<p class='muted small'>Showing 250 of {len(rows)} manual live channels.</p>" if len(rows)>250 else ''
    return f"<div class='card'><div class='page-heading'><div><h2>Live IPTV Channels</h2><p>User-supplied M3U8/HLS streams published as ViperTV channels.</p></div><a class='button secondary' href='/live'>Manage Live IPTV</a></div><div class='table-wrap'><table><thead><tr><th>#</th><th>Name</th><th>Group</th><th></th></tr></thead><tbody>{body}</tbody></table></div>{more}</div>"


def live_streams_page(msg: str='') -> str:
    with db() as conn:
        rows=conn.execute('SELECT * FROM live_streams ORDER BY CAST(number AS REAL),number,name').fetchall()
    trs=''.join(
        f"<tr><td><b>{e(r['number'])}</b></td><td>{e(r['name'])}</td><td>{e(r['group_name'] or 'Live IPTV')}</td>"
        f"<td><code>{e(r['stream_url'])}</code></td><td>{'<span class=\'badge\'>Enabled</span>' if r['enabled'] else '<span class=\'badge warn\'>Disabled</span>'}</td>"
        f"<td class='nowrap'><a class='button' href='/watch/live/{r['id']}'>Watch</a> <a class='button secondary' href='/live/{r['id']}/edit'>Edit</a> "
        f"<form class='inline' method='post' action='/live/{r['id']}/test'><button class='secondary'>Test</button></form> "
        f"<form class='inline' method='post' action='/live/{r['id']}/toggle'><button class='secondary'>{'Disable' if r['enabled'] else 'Enable'}</button></form> "
        f"<form class='inline' method='post' action='/live/{r['id']}/delete' onsubmit='return confirm(&quot;Delete this live IPTV channel?&quot;);'><button class='danger'>Delete</button></form></td></tr>"
        for r in rows
    ) or "<tr><td colspan='6' class='empty'>No manual live streams yet. Add an M3U8 URL above.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+_page_heading('Live IPTV','Paste a direct HLS/M3U8 stream URL and publish it as a normal ViperTV channel.')+f"""
<div class='grid'>
 <div class='card'><h2>Add M3U8 Channel</h2><form method='post' action='/live/add'>
  <div class='grid'><div><label>Channel Number</label><input name='number' required placeholder='200'></div><div><label>Channel Name</label><input name='name' required placeholder='CNN Live'></div></div>
  <label>M3U8 / HLS URL</label><input name='stream_url' required placeholder='https://example.com/live/master.m3u8'>
  <div class='grid'><div><label>Logo URL (optional)</label><input name='logo_url' placeholder='https://example.com/logo.png'></div><div><label>Group (optional)</label><input name='group_name' value='Live IPTV' placeholder='News'></div></div>
  <details><summary>Optional HTTP headers</summary><label>User-Agent</label><input name='user_agent' placeholder='Leave blank for ViperTV default'><label>Referer</label><input name='referer' placeholder='https://example.com/'></details>
  <button>Add Live Channel</button>
 </form></div>
 <div class='card'><h2>How It Works</h2><p>ViperTV reads the M3U8 playlist, rewrites its child playlists, segments, encryption keys and init maps through a signed ViperTV HLS proxy, and publishes one stable channel in the main Kodi M3U.</p><p>The optional User-Agent and Referer are applied to the entire HLS tree, not only the first playlist request.</p><p class='muted small'>Only add streams you are authorized to access. ViperTV does not bypass source authentication or DRM.</p></div>
</div>
<div class='card'><div class='page-heading'><div><h2>Manual Live Channels</h2><p>{len(rows)} configured.</p></div></div><div class='table-wrap'><table><thead><tr><th>#</th><th>Name</th><th>Group</th><th>Source</th><th>Status</th><th>Actions</th></tr></thead><tbody>{trs}</tbody></table></div></div>"""
    return page_shell('Live IPTV',body)


def live_stream_edit_page(stream_id: int, msg: str='') -> str:
    r=_live_row(stream_id)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    checked='checked' if r['enabled'] else ''
    body=notice+_page_heading('Edit Live IPTV Channel',f"Channel {r['number']} {r['name']}","<a class='button secondary' href='/live'>Back to Live IPTV</a>")+f"""
<div class='card'><form method='post' action='/live/{r['id']}/edit'>
 <div class='grid'><div><label>Channel Number</label><input name='number' required value='{e(r['number'])}'></div><div><label>Channel Name</label><input name='name' required value='{e(r['name'])}'></div></div>
 <label>M3U8 / HLS URL</label><input name='stream_url' required value='{e(r['stream_url'])}'>
 <div class='grid'><div><label>Logo URL</label><input name='logo_url' value='{e(r['logo_url'] or '')}'></div><div><label>Group</label><input name='group_name' value='{e(r['group_name'] or 'Live IPTV')}'></div></div>
 <details open><summary>Optional HTTP headers</summary><label>User-Agent</label><input name='user_agent' value='{e(r['user_agent'] or '')}'><label>Referer</label><input name='referer' value='{e(r['referer'] or '')}'></details>
 <label><input type='checkbox' name='enabled' value='1' {checked}> Enabled</label><br><br>
 <button>Save Changes</button> <a class='button secondary' href='/watch/live/{r['id']}'>Watch</a>
</form></div>"""
    return page_shell('Edit Live IPTV',body)


@app.get('/live',response_class=HTMLResponse)
def ui_live_streams(msg: str=''):
    return live_streams_page(msg)


@app.post('/live/add')
def live_stream_add(number: str=Form(...), name: str=Form(...), stream_url: str=Form(...), logo_url: str=Form(''), group_name: str=Form('Live IPTV'), user_agent: str=Form(''), referer: str=Form('')):
    number=number.strip(); name=name.strip()
    try:
        stream_url=_validate_live_hls_url(stream_url)
        if not number or not name: raise ValueError('Channel number and name are required')
        if _live_number_in_use(number): raise ValueError(f'Channel number {number} is already in use')
        safe_backup_before_change()
        now=utcnow_iso()
        with db() as conn:
            cur=conn.execute('INSERT INTO live_streams(number,name,stream_url,logo_url,group_name,user_agent,referer,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (number,name,stream_url,logo_url.strip(),group_name.strip() or 'Live IPTV',user_agent.strip(),referer.strip(),1,now,now))
            conn.commit(); sid=int(cur.lastrowid)
        return RedirectResponse('/live?msg='+quote(f'Added channel {number} {name}. Test or Watch it now.'),303)
    except Exception as exc:
        return RedirectResponse('/live?msg='+quote('Could not add live channel: '+str(exc)),303)


@app.get('/live/{stream_id}/edit',response_class=HTMLResponse)
def live_stream_edit_get(stream_id: int, msg: str=''):
    return live_stream_edit_page(stream_id,msg)


@app.post('/live/{stream_id}/edit')
def live_stream_edit_post(stream_id: int, number: str=Form(...), name: str=Form(...), stream_url: str=Form(...), logo_url: str=Form(''), group_name: str=Form('Live IPTV'), user_agent: str=Form(''), referer: str=Form(''), enabled: str | None=Form(None)):
    _live_row(stream_id)
    number=number.strip(); name=name.strip()
    try:
        stream_url=_validate_live_hls_url(stream_url)
        if not number or not name: raise ValueError('Channel number and name are required')
        if _live_number_in_use(number,stream_id): raise ValueError(f'Channel number {number} is already in use')
        safe_backup_before_change()
        with db() as conn:
            conn.execute('UPDATE live_streams SET number=?,name=?,stream_url=?,logo_url=?,group_name=?,user_agent=?,referer=?,enabled=?,updated_at=? WHERE id=?',
                (number,name,stream_url,logo_url.strip(),group_name.strip() or 'Live IPTV',user_agent.strip(),referer.strip(),1 if enabled else 0,utcnow_iso(),stream_id))
            conn.commit()
        return RedirectResponse(f'/live/{stream_id}/edit?msg='+quote('Live channel saved.'),303)
    except Exception as exc:
        return RedirectResponse(f'/live/{stream_id}/edit?msg='+quote('Could not save: '+str(exc)),303)


@app.post('/live/{stream_id}/toggle')
def live_stream_toggle(stream_id: int):
    r=_live_row(stream_id); safe_backup_before_change()
    with db() as conn:
        conn.execute('UPDATE live_streams SET enabled=?,updated_at=? WHERE id=?',(0 if r['enabled'] else 1,utcnow_iso(),stream_id)); conn.commit()
    return RedirectResponse('/live?msg='+quote(('Disabled' if r['enabled'] else 'Enabled')+' '+str(r['name'])+'.'),303)


@app.post('/live/{stream_id}/delete')
def live_stream_delete(stream_id: int):
    r=_live_row(stream_id); safe_backup_before_change()
    with db() as conn:
        conn.execute('DELETE FROM live_streams WHERE id=?',(stream_id,)); conn.commit()
    return RedirectResponse('/live?msg='+quote(f'Deleted {r["name"]}.'),303)


@app.post('/live/{stream_id}/test')
def live_stream_test(stream_id: int, request: Request):
    r=_live_row(stream_id)
    try:
        _live_root_playlist(stream_id,base_url(request))
        return RedirectResponse('/live?msg='+quote(f'Test OK: {r["name"]} returned a valid HLS playlist.'),303)
    except Exception as exc:
        detail=exc.detail if isinstance(exc,HTTPException) else str(exc)
        return RedirectResponse('/live?msg='+quote(f'Test failed for {r["name"]}: {detail}'),303)


@app.api_route('/stream/live/{stream_id}.m3u8',methods=['GET','HEAD'])
async def live_stream_root(stream_id: int, request: Request):
    r=_live_row(stream_id)
    if not r['enabled']:
        raise HTTPException(404,'Live IPTV channel is disabled')
    if request.method=='HEAD':
        return PlainTextResponse('',media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})
    return await asyncio.to_thread(_live_root_playlist,stream_id,base_url(request))


@app.api_route('/stream/live/{stream_id}/proxy/{token}',methods=['GET','HEAD'])
async def live_stream_proxy(stream_id: int, token: str, request: Request):
    row=_live_row(stream_id)
    if not row['enabled']:
        raise HTTPException(404,'Live IPTV channel is disabled')
    target=_live_proxy_decode(token)
    if request.method=='HEAD':
        return PlainTextResponse('',headers={'Cache-Control':'no-store'})
    range_header=request.headers.get('range')
    try:
        resp=await asyncio.to_thread(_live_open,row,target,range_header)
        ctype=str(resp.headers.get('Content-Type') or 'application/octet-stream')
        final_url=resp.geturl() or target
        is_playlist=('mpegurl' in ctype.lower() or '.m3u8' in final_url.lower().split('?',1)[0])
        if is_playlist:
            raw=await asyncio.to_thread(resp.read,4*1024*1024)
            try: resp.close()
            except Exception: pass
            text=raw.decode('utf-8',errors='replace')
            if '#EXTM3U' not in text[:1024]:
                raise RuntimeError('upstream child playlist was not HLS')
            text=_live_rewrite_playlist(text,final_url,stream_id,base_url(request))
            return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})
        headers={'Cache-Control':'private, max-age=15','X-Accel-Buffering':'no'}
        for hn in ('Content-Range','Accept-Ranges','Content-Length'):
            hv=resp.headers.get(hn)
            if hv: headers[hn]=hv
        return StreamingResponse(_live_binary_iter(resp),status_code=getattr(resp,'status',200),media_type=ctype,headers=headers)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502,f'Live IPTV proxy error: {exc}')


@app.get('/watch/live/{stream_id}',response_class=HTMLResponse)
def watch_live_stream(stream_id: int):
    r=_live_row(stream_id)
    manifest=f"/stream/live/{r['id']}.m3u8"
    logo=f"<img src='{e(r['logo_url'])}' alt='' style='max-height:52px;max-width:180px;object-fit:contain'>" if r['logo_url'] else ''
    body=_page_heading(f"{r['number']} {r['name']}",'Live manual HLS channel through ViperTV.',"<a class='button secondary' href='/live'>Back to Live IPTV</a>")+f"""
<div class='card' style='max-width:1100px;margin:auto'>{logo}<div style='background:#05070a;border-radius:8px;overflow:hidden;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center;margin-top:8px'><video id='live-preview' controls autoplay playsinline style='width:100%;height:100%;background:#000'></video></div><div id='live-status' class='muted small' style='margin-top:12px'>Connecting to live stream…</div></div>
<script src='/assets/hls.min.js'></script><script>(()=>{{const v=document.getElementById('live-preview'),st=document.getElementById('live-status'),src={json.dumps(manifest)}+'?v='+Date.now();if(v.canPlayType('application/vnd.apple.mpegurl')){{v.src=src;v.play().catch(()=>{{st.textContent='Ready — press Play';}});}}else if(window.Hls&&Hls.isSupported()){{const h=new Hls({{liveSyncDurationCount:2,liveMaxLatencyDurationCount:5,maxBufferLength:10,maxMaxBufferLength:20,backBufferLength:8}});h.loadSource(src);h.attachMedia(v);h.on(Hls.Events.MANIFEST_PARSED,()=>{{st.textContent='LIVE';v.play().catch(()=>{{st.textContent='Ready — press Play';}});}});h.on(Hls.Events.ERROR,(_e,d)=>{{st.textContent=d.fatal?'Stream error — retrying…':'Buffering…';if(d.fatal)setTimeout(()=>location.reload(),1800);}});}}else st.textContent='This browser does not support HLS.';v.addEventListener('playing',()=>st.textContent='LIVE');v.addEventListener('waiting',()=>st.textContent='Buffering…');}})();</script>"""
    return page_shell('Watch Live IPTV',body)


# =========================== Pluto TV source ================================

def init_pluto_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS pluto_channels(
          id TEXT PRIMARY KEY,region TEXT NOT NULL,pluto_number INTEGER,name TEXT NOT NULL,slug TEXT,
          category TEXT,logo_url TEXT,display_number TEXT,imported INTEGER NOT NULL DEFAULT 0,
          available INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_pluto_channels_region ON pluto_channels(region,available,pluto_number);
        CREATE INDEX IF NOT EXISTS idx_pluto_channels_imported ON pluto_channels(imported,available,display_number);
        CREATE TABLE IF NOT EXISTS pluto_epg(
          channel_id TEXT NOT NULL REFERENCES pluto_channels(id) ON DELETE CASCADE,start_utc TEXT NOT NULL,stop_utc TEXT NOT NULL,
          title TEXT,subtitle TEXT,description TEXT,category TEXT,program_type TEXT,rating TEXT,episode_number TEXT,updated_at TEXT NOT NULL,
          PRIMARY KEY(channel_id,start_utc));
        CREATE INDEX IF NOT EXISTS idx_pluto_epg_window ON pluto_epg(channel_id,start_utc,stop_utc);
        """)
        conn.commit()
    if not get_setting('pluto_client_id'):
        set_setting('pluto_client_id', str(uuid.uuid4()))
    if not get_setting('pluto_region'):
        set_setting('pluto_region', PLUTO_DEFAULT_REGION)
    if not get_setting('pluto_number_offset'):
        set_setting('pluto_number_offset', str(PLUTO_DEFAULT_NUMBER_OFFSET))
    if not get_setting('pluto_auto_sync_hours'):
        set_setting('pluto_auto_sync_hours', str(PLUTO_AUTO_SYNC_HOURS))
    if not get_setting('pluto_proxy_secret'):
        set_setting('pluto_proxy_secret', uuid.uuid4().hex + uuid.uuid4().hex)


def _parse_pluto_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text=str(value).strip()
    try:
        if text.endswith('Z'):
            text=text[:-1]+'+00:00'
        dt=datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt=dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pluto_jwt_exp(token: str) -> float:
    try:
        payload=token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload.encode()).decode()).get('exp') or 0)
    except Exception:
        return 0.0


def _pluto_region() -> str:
    return (get_setting('pluto_region', PLUTO_DEFAULT_REGION) or PLUTO_DEFAULT_REGION).strip().lower()


def _pluto_headers(region: str, token: str | None = None) -> dict[str,str]:
    headers={
        'Accept':'*/*','Origin':'https://pluto.tv','Referer':'https://pluto.tv/',
        'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122 Safari/537.36',
    }
    override=os.getenv('VIPERTV_PLUTO_X_FORWARDED_FOR','').strip()
    ip=override or PLUTO_REGION_IPS.get(region,'')
    if ip:
        headers['X-Forwarded-For']=ip
    if token:
        headers['Authorization']=f'Bearer {token}'
    return headers


def _pluto_json(url: str, params: dict[str,Any] | None = None, headers: dict[str,str] | None = None, timeout: int = 25) -> Any:
    if params:
        url += ('&' if '?' in url else '?') + urlencode({k:str(v) for k,v in params.items()})
    req=URLRequest(url,headers=headers or {})
    with urlopen(req,timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8','replace'))


def pluto_boot(region: str | None = None, force: bool = False) -> dict[str,Any]:
    region=(region or _pluto_region()).lower()
    cached=PLUTO_BOOT_CACHE.get(region)
    if cached and not force and time.time() < float(cached.get('exp') or 0)-60:
        return cached
    client_id=get_setting('pluto_client_id') or str(uuid.uuid4())
    set_setting('pluto_client_id',client_id)
    params={
        'appName':'web','appVersion':'8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
        'deviceVersion':'122.0.0','deviceModel':'web','deviceMake':'chrome','deviceType':'web',
        'clientID':client_id,'clientModelNumber':'1.0.0','serverSideAds':'false',
        'drmCapabilities':'widevine:L3','blockingMode':'',
    }
    data=_pluto_json(PLUTO_BOOT_URL,params,_pluto_headers(region),20)
    token=str(data.get('sessionToken') or '')
    if not token:
        raise RuntimeError('Pluto boot response did not contain a session token')
    servers=data.get('servers') or {}
    cache={
        'token':token,'exp':_pluto_jwt_exp(token) or (time.time()+3600),
        'stitcher':str(servers.get('stitcher') or PLUTO_STITCHER_FALLBACK).rstrip('/'),
        'stitcher_params':str(data.get('stitcherParams') or '').lstrip('?&'),
        'region':region,
    }
    PLUTO_BOOT_CACHE[region]=cache
    return cache


def _pluto_new_stream_session(region: str | None = None) -> dict[str,Any]:
    """Create an uncached Pluto playback identity for one live viewer/producer.

    Pluto's stitcher parameters describe a playback session. Reusing one cached
    boot session across independent live channels can cause one stream to stall
    or replace another. Discovery/guide calls still use the normal cached boot;
    live playback gets an isolated client/session identity.
    """
    region=(region or _pluto_region()).lower()
    client_id=str(uuid.uuid4())
    params={
        'appName':'web','appVersion':'8.0.0-111b2b9dc00bd0bea9030b30662159ed9e7c8bc6',
        'deviceVersion':'122.0.0','deviceModel':'web','deviceMake':'chrome','deviceType':'web',
        'clientID':client_id,'clientModelNumber':'1.0.0','serverSideAds':'false',
        'drmCapabilities':'widevine:L3','blockingMode':'',
    }
    data=_pluto_json(PLUTO_BOOT_URL,params,_pluto_headers(region),20)
    token=str(data.get('sessionToken') or '')
    if not token:
        raise RuntimeError('Pluto playback boot response did not contain a session token')
    servers=data.get('servers') or {}
    return {
        'token':token,'exp':_pluto_jwt_exp(token) or (time.time()+3600),
        'stitcher':str(servers.get('stitcher') or PLUTO_STITCHER_FALLBACK).rstrip('/'),
        'stitcher_params':str(data.get('stitcherParams') or '').lstrip('?&'),
        'region':region,'client_id':client_id,
    }


def pluto_stream_url(channel_id: str, region: str | None = None, force_token: bool = False, isolated: bool = False) -> str:
    boot=_pluto_new_stream_session(region) if isolated else pluto_boot(region,force_token)
    url=f"{boot['stitcher']}/v2/stitch/hls/channel/{quote(str(channel_id),safe='')}/master.m3u8?jwt={quote(str(boot['token']),safe='')}&masterJWTPassthrough=true&includeExtendedEvents=true"
    if boot.get('stitcher_params'):
        url += '&' + str(boot['stitcher_params'])
    return url


def _pluto_logo(ch: dict[str,Any]) -> str:
    for img in ch.get('images') or []:
        if str(img.get('type') or '').lower() in ('colorlogopng','colorlogojpg','logo') and img.get('url'):
            return str(img['url'])
    for key in ('colorLogoPNG','solidLogoPNG'):
        val=ch.get(key) or {}
        if isinstance(val,dict) and val.get('path'):
            return str(val['path'])
    return ''


def _pluto_unique_number(conn: sqlite3.Connection, base: int, channel_id: str) -> str:
    candidate=max(1,int(base))
    while True:
        text=str(candidate)
        normal=conn.execute('SELECT 1 FROM channels WHERE number=?',(text,)).fetchone()
        other=conn.execute('SELECT 1 FROM pluto_channels WHERE display_number=? AND id<>?',(text,channel_id)).fetchone()
        if not normal and not other:
            return text
        candidate += 1


def _pluto_assign_number(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    if row['display_number']:
        # Keep existing imported numbers stable unless they collide with a ViperTV channel.
        if not conn.execute('SELECT 1 FROM channels WHERE number=?',(str(row['display_number']),)).fetchone():
            return str(row['display_number'])
    try: offset=int(get_setting('pluto_number_offset',str(PLUTO_DEFAULT_NUMBER_OFFSET)) or PLUTO_DEFAULT_NUMBER_OFFSET)
    except Exception: offset=PLUTO_DEFAULT_NUMBER_OFFSET
    base=offset+int(row['pluto_number'] or 0)
    return _pluto_unique_number(conn,base,row['id'])


def _pluto_program_fields(item: dict[str,Any], channel_category: str='') -> dict[str,str]:
    episode=item.get('episode') or {}
    series=episode.get('series') or {}
    clip=episode.get('clip') or {}
    title=str(item.get('title') or series.get('name') or episode.get('name') or 'Pluto TV')
    subtitle=str(episode.get('name') or '')
    if subtitle == title:
        subtitle=''
    desc=str(episode.get('description') or series.get('description') or series.get('summary') or clip.get('description') or '')
    ptype=str(series.get('type') or episode.get('type') or clip.get('type') or '')
    category=str(episode.get('subGenre') or series.get('genre') or channel_category or '')
    rating=episode.get('rating') or ''
    if isinstance(rating,dict):
        rating=rating.get('name') or rating.get('value') or ''
    season=episode.get('season')
    number=episode.get('number')
    epnum=''
    if season not in (None,'',0,'0') and number not in (None,'',0,'0'):
        try: epnum=f"S{int(season):02d}E{int(number):02d}"
        except Exception: epnum=f"S{season}E{number}"
    elif number not in (None,''):
        epnum=str(number)
    return {'title':title,'subtitle':subtitle,'description':desc,'program_type':ptype,'category':category,'rating':str(rating),'episode_number':epnum}


def sync_pluto_guide(region: str | None = None, channel_ids: list[str] | None = None, duration_minutes: int = 2880) -> int:
    region=(region or _pluto_region()).lower()
    boot=pluto_boot(region)
    headers=_pluto_headers(region,boot['token'])
    if channel_ids is None:
        with db() as conn:
            channel_ids=[str(r['id']) for r in conn.execute('SELECT id FROM pluto_channels WHERE region=? AND available=1',(region,)).fetchall()]
    if not channel_ids:
        return 0
    now=datetime.now(timezone.utc).replace(minute=0,second=0,microsecond=0)
    start=now.strftime('%Y-%m-%dT%H:00:00Z')
    total=0
    with db() as conn:
        # Retain a little history for the on-screen guide, but prune old cache.
        conn.execute('DELETE FROM pluto_epg WHERE stop_utc<?',((now-timedelta(hours=12)).isoformat(),))
        for pos in range(0,len(channel_ids),100):
            group=channel_ids[pos:pos+100]
            data=_pluto_json(PLUTO_TIMELINES_URL,{
                'start':start,'channelIds':','.join(group),'duration':str(int(duration_minutes))
            },headers,30)
            entries=(data or {}).get('data',[]) if isinstance(data,dict) else []
            for entry in entries:
                cid=str(entry.get('channelId') or entry.get('_id') or '')
                if not cid:
                    continue
                crow=conn.execute('SELECT category FROM pluto_channels WHERE id=?',(cid,)).fetchone()
                ccat=str(crow['category'] or '') if crow else ''
                for item in entry.get('timelines') or []:
                    start_raw=str(item.get('start') or '')
                    stop_raw=str(item.get('stop') or '')
                    ps=_parse_pluto_iso(start_raw); pe=_parse_pluto_iso(stop_raw)
                    if not ps or not pe or pe<=ps:
                        continue
                    fields=_pluto_program_fields(item,ccat)
                    conn.execute("""INSERT INTO pluto_epg(channel_id,start_utc,stop_utc,title,subtitle,description,category,program_type,rating,episode_number,updated_at)
                                    VALUES(?,?,?,?,?,?,?,?,?,?,?)
                                    ON CONFLICT(channel_id,start_utc) DO UPDATE SET stop_utc=excluded.stop_utc,title=excluded.title,subtitle=excluded.subtitle,
                                      description=excluded.description,category=excluded.category,program_type=excluded.program_type,rating=excluded.rating,
                                      episode_number=excluded.episode_number,updated_at=excluded.updated_at""",
                                 (cid,ps.isoformat(),pe.isoformat(),fields['title'],fields['subtitle'],fields['description'],fields['category'],fields['program_type'],fields['rating'],fields['episode_number'],utcnow_iso()))
                    total += 1
            PLUTO_SYNC_STATUS.update({'stage':'Guide','done':min(pos+len(group),len(channel_ids)),'total':len(channel_ids),'current':f'Guide group {pos//100+1}'})
        conn.commit()
    return total


def sync_pluto(region: str | None = None) -> dict[str,Any]:
    region=(region or _pluto_region()).lower()
    PLUTO_SYNC_STATUS.update({'running':True,'stage':'Connecting','done':0,'total':0,'current':'Pluto TV','channels':0,'guide_programmes':0,'started_at':utcnow_iso(),'finished_at':None,'error':None})
    try:
        boot=pluto_boot(region,force=True)
        headers=_pluto_headers(region,boot['token'])
        params={'channelIds':'','offset':'0','limit':'1000','sort':'number:asc'}
        payload=_pluto_json(PLUTO_CHANNELS_URL,params,headers,30)
        channels=(payload or {}).get('data',[]) if isinstance(payload,dict) else []
        if not channels:
            # Current Pluto still exposes the legacy channel endpoint in some regions.
            legacy=_pluto_json('https://api.pluto.tv/v2/channels.json',{'sid':get_setting('pluto_client_id') or '', 'deviceId':get_setting('pluto_client_id') or ''},_pluto_headers(region),30)
            channels=legacy if isinstance(legacy,list) else []
        if not channels:
            raise RuntimeError(f'Pluto returned no channels for region {region.upper()}')
        PLUTO_SYNC_STATUS.update({'stage':'Categories','total':len(channels),'current':'Categories'})
        categories={}
        try:
            cats=_pluto_json(PLUTO_CATEGORIES_URL,params,headers,20)
            for cat in ((cats or {}).get('data',[]) if isinstance(cats,dict) else []):
                for cid in cat.get('channelIDs') or []:
                    categories[str(cid)]=str(cat.get('name') or '')
        except Exception as exc:
            print(f'Pluto category sync warning: {exc}',flush=True)
        now=utcnow_iso()
        returned=[]
        with db() as conn:
            conn.execute('UPDATE pluto_channels SET available=0 WHERE region=?',(region,))
            for i,ch in enumerate(channels,1):
                cid=str(ch.get('id') or ch.get('_id') or '')
                if not cid:
                    continue
                returned.append(cid)
                number=ch.get('number')
                try: number=int(number)
                except Exception: number=i
                category=categories.get(cid) or str(ch.get('category') or '')
                logo=_pluto_logo(ch)
                conn.execute("""INSERT INTO pluto_channels(id,region,pluto_number,name,slug,category,logo_url,imported,available,updated_at)
                                VALUES(?,?,?,?,?,?,?,0,1,?)
                                ON CONFLICT(id) DO UPDATE SET region=excluded.region,pluto_number=excluded.pluto_number,name=excluded.name,
                                  slug=excluded.slug,category=excluded.category,logo_url=excluded.logo_url,available=1,updated_at=excluded.updated_at""",
                             (cid,region,number,str(ch.get('name') or f'Pluto {number}'),str(ch.get('slug') or ''),category,logo,now))
                PLUTO_SYNC_STATUS.update({'stage':'Channels','done':i,'total':len(channels),'current':str(ch.get('name') or cid)})
            conn.commit()
        programmes=sync_pluto_guide(region,returned,2880)
        set_setting('pluto_last_sync_at',utcnow_iso())
        set_setting('pluto_enabled','1')
        result={'channels':len(returned),'guide_programmes':programmes,'region':region.upper()}
        PLUTO_SYNC_STATUS.update({'running':False,'stage':'Complete','done':len(returned),'total':len(returned),'channels':len(returned),'guide_programmes':programmes,'finished_at':utcnow_iso(),'current':''})
        print(f'Pluto TV sync complete: {result}',flush=True)
        return result
    except Exception as exc:
        PLUTO_SYNC_STATUS.update({'running':False,'stage':'Failed','finished_at':utcnow_iso(),'error':str(exc)[:1000]})
        print(f'Pluto TV sync failed: {exc}',flush=True)
        raise


async def periodic_pluto_sync_loop() -> None:
    while True:
        try:
            await asyncio.sleep(300)
            if get_setting('pluto_enabled','0') != '1' or PLUTO_SYNC_STATUS.get('running'):
                continue
            try: hours=max(1,int(get_setting('pluto_auto_sync_hours',str(PLUTO_AUTO_SYNC_HOURS)) or PLUTO_AUTO_SYNC_HOURS))
            except Exception: hours=PLUTO_AUTO_SYNC_HOURS
            last=_parse_iso_datetime(get_setting('pluto_last_sync_at'))
            if last and datetime.now(timezone.utc)-last < timedelta(hours=hours):
                continue
            try:
                await asyncio.to_thread(sync_pluto,_pluto_region())
            except Exception:
                pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f'Pluto auto-sync scheduler error: {exc}',flush=True)
            await asyncio.sleep(300)


def _pluto_now_next(channel_id: str) -> tuple[sqlite3.Row | None, sqlite3.Row | None]:
    now=datetime.now(timezone.utc).isoformat()
    with db() as conn:
        current=conn.execute('SELECT * FROM pluto_epg WHERE channel_id=? AND start_utc<=? AND stop_utc>? ORDER BY start_utc DESC LIMIT 1',(channel_id,now,now)).fetchone()
        nxt=conn.execute('SELECT * FROM pluto_epg WHERE channel_id=? AND start_utc>? ORDER BY start_utc LIMIT 1',(channel_id,now)).fetchone()
    return current,nxt


def pluto_channels_card() -> str:
    try:
        with db() as conn:
            rows=conn.execute('SELECT * FROM pluto_channels WHERE imported=1 AND available=1 ORDER BY CAST(display_number AS REAL),display_number LIMIT 12').fetchall()
            count=conn.execute('SELECT COUNT(*) c FROM pluto_channels WHERE imported=1 AND available=1').fetchone()['c']
    except Exception:
        return ''
    if not count:
        return "<div class='card'><div class='page-heading'><div><h2>Pluto TV Channels</h2><p>No Pluto TV channels imported.</p></div><a class='button secondary' href='/pluto'>Pluto TV</a></div></div>"
    body=''.join(f"<tr><td><b>{e(r['display_number'])}</b></td><td>{e(r['name'])}</td><td>{e(r['category'] or '')}</td><td><a class='button' href='/watch/pluto/{quote(str(r['id']),safe='')}'>Watch</a></td></tr>" for r in rows)
    more=f"<div class='muted small' style='margin-top:10px'>Showing 12 of {count} imported Pluto channels.</div>" if count>12 else ''
    return f"<div class='card'><div class='page-heading'><div><h2>Pluto TV Channels</h2><p>Imported live FAST channels. Manage the regional lineup from Pluto TV.</p></div><a class='button secondary' href='/pluto'>Manage Pluto TV</a></div><div class='table-wrap'><table><thead><tr><th>#</th><th>Name</th><th>Category</th><th></th></tr></thead><tbody>{body}</tbody></table></div>{more}</div>"


def pluto_page(msg: str='') -> str:
    region=_pluto_region()
    try: offset=int(get_setting('pluto_number_offset',str(PLUTO_DEFAULT_NUMBER_OFFSET)) or PLUTO_DEFAULT_NUMBER_OFFSET)
    except Exception: offset=PLUTO_DEFAULT_NUMBER_OFFSET
    try: auto_hours=int(get_setting('pluto_auto_sync_hours',str(PLUTO_AUTO_SYNC_HOURS)) or PLUTO_AUTO_SYNC_HOURS)
    except Exception: auto_hours=PLUTO_AUTO_SYNC_HOURS
    with db() as conn:
        channels=conn.execute('SELECT * FROM pluto_channels WHERE region=? ORDER BY pluto_number,name',(region,)).fetchall()
        imported=conn.execute('SELECT COUNT(*) c FROM pluto_channels WHERE region=? AND imported=1 AND available=1',(region,)).fetchone()['c']
        programmes=conn.execute('SELECT COUNT(*) c FROM pluto_epg').fetchone()['c']
    region_names={'ca':'Canada','us':'United States','gb':'United Kingdom','de':'Germany','fr':'France','it':'Italy','es':'Spain','br':'Brazil','mx':'Mexico','au':'Australia','se':'Sweden','dk':'Denmark','no':'Norway','ar':'Argentina','cl':'Chile','local':'Local / Auto'}
    opts=''.join(f"<option value='{k}'{' selected' if k==region else ''}>{e(v)}</option>" for k,v in region_names.items())
    rows=[]
    for ch in channels:
        logo=f"<img src='{e(ch['logo_url'])}' alt='' style='max-width:90px;max-height:32px'>" if ch['logo_url'] else ''
        imported_badge=f"<span class='badge'>Imported #{e(ch['display_number'])}</span>" if ch['imported'] and ch['available'] else ("<span class='badge warn'>Unavailable</span>" if not ch['available'] else '')
        rows.append(f"<tr><td><input class='pluto-check' type='checkbox' name='channel_ids' value='{e(ch['id'])}'></td><td>{logo}</td><td><b>{e(ch['name'])}</b><div class='muted small'>{e(ch['slug'] or '')}</div></td><td>{e(ch['pluto_number'])}</td><td>{e(ch['category'] or '')}</td><td>{imported_badge}</td><td>{('<a class=\"button\" href=\"/watch/pluto/'+quote(str(ch['id']),safe='')+'\">Watch</a>') if ch['imported'] and ch['available'] else ''}</td></tr>")
    rows_html=''.join(rows) or "<tr><td colspan='7' class='empty'>No Pluto channels discovered yet. Save the region and click Sync Pluto TV.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    last=format_plex_schedule_time(get_setting('pluto_last_sync_at'))
    st=PLUTO_SYNC_STATUS
    progress=''
    if st.get('running'):
        total=max(1,int(st.get('total') or 1)); done=int(st.get('done') or 0); pct=min(100,int(done*100/total))
        progress=f"<div class='card'><h2>Pluto Sync</h2><div class='progress large'><span style='width:{pct}%'></span></div><p><b>{e(st.get('stage') or 'Working')}</b> — {done}/{total} {e(st.get('current') or '')}</p></div>"
    body=notice+_page_heading('Pluto TV','Discover regional Pluto TV FAST channels, import the ones you want, and publish them through ViperTV.',"<form class='inline' method='post' action='/pluto/sync'><button>Sync Pluto TV</button></form>")+f"""
{progress}
<div class='stats'>
 <div class='stat'><div class='stat-label'>Discovered</div><div class='stat-value'>{len(channels)}</div><div class='muted small'>{e(region.upper())}</div></div>
 <div class='stat'><div class='stat-label'>Imported</div><div class='stat-value'>{imported}</div><div class='muted small'>Included in M3U/EPG</div></div>
 <div class='stat'><div class='stat-label'>Guide Programmes</div><div class='stat-value'>{programmes:,}</div><div class='muted small'>Cached</div></div>
 <div class='stat'><div class='stat-label'>Last Sync</div><div class='stat-value' style='font-size:16px'>{e(last)}</div><div class='muted small'>Auto every {auto_hours}h</div></div>
</div>
<div class='grid'>
 <div class='card'><h2>Pluto Source Settings</h2><form method='post' action='/pluto/settings'>
  <label>Region</label><select name='region'>{opts}</select>
  <label>ViperTV channel-number offset</label><input type='number' name='number_offset' min='0' max='9000' value='{offset}'><div class='muted small'>Example: Pluto 100 becomes ViperTV {offset+100}. Existing assignments stay stable.</div>
  <label>Automatic sync interval (hours)</label><input type='number' name='auto_hours' min='1' max='168' value='{auto_hours}'>
  <button>Save Settings</button></form></div>
 <div class='card'><h2>How It Works</h2><p>ViperTV caches the Pluto channel list and guide in SQLite. Kodi/IPTV playback uses a fresh isolated Pluto session per viewer and redirects directly to Pluto's HLS CDN for fast startup; browser Watch uses a server-assisted isolated session.</p><p>Imported channels are live sources — Pluto controls the schedule. ViperTV adds them to the main M3U, XMLTV guide, browser Watch page and System → Guide.</p><p class='muted small'>Pluto availability and lineups vary by region and are controlled by Pluto TV.</p></div>
</div>
<div class='card'><div class='page-heading'><div><h2>Regional Channels</h2><p>Select individual Pluto channels or import the entire available lineup.</p></div><div class='toolbar'><form class='inline' method='post' action='/pluto/import-all'><button>Import All Available</button></form><form class='inline' method='post' action='/pluto/remove-all' onsubmit='return confirm("Remove all imported Pluto channels from ViperTV? Discovery data and guide cache are kept.")'><button class='danger'>Remove All Imported</button></form></div></div>
<form method='post' action='/pluto/import-selected' id='pluto-select-form'><div class='toolbar' style='margin-bottom:10px'><button type='button' class='secondary' id='pluto-select-all'>Select All</button><button name='action' value='import'>Import Selected</button><button name='action' value='remove' class='danger'>Remove Selected</button></div>
<div class='table-wrap'><table><thead><tr><th></th><th>Logo</th><th>Channel</th><th>Pluto #</th><th>Category</th><th>Status</th><th></th></tr></thead><tbody>{rows_html}</tbody></table></div></form></div>
"""
    script="""<script>
const all=document.getElementById('pluto-select-all'); if(all)all.addEventListener('click',()=>{const b=[...document.querySelectorAll('.pluto-check')];const target=!b.every(x=>x.checked);b.forEach(x=>x.checked=target);});
""" + ("setTimeout(()=>location.reload(),2000);" if st.get('running') else "") + "</script>"
    return page_shell('Pluto TV',body,extra_script=script)


@app.get('/pluto',response_class=HTMLResponse)
def pluto_page_route(msg: str=''):
    return pluto_page(msg)


@app.post('/pluto/settings')
def pluto_settings_route(region: str=Form('ca'), number_offset: int=Form(1000), auto_hours: int=Form(24)):
    region=region.strip().lower()
    if region not in {'ca','us','gb','de','fr','it','es','br','mx','au','se','dk','no','ar','cl','local'}:
        region='ca'
    set_setting('pluto_region',region); set_setting('pluto_number_offset',str(max(0,min(9000,int(number_offset))))); set_setting('pluto_auto_sync_hours',str(max(1,min(168,int(auto_hours))))); set_setting('pluto_enabled','1')
    PLUTO_BOOT_CACHE.clear()
    return RedirectResponse('/pluto?msg='+quote('Pluto TV settings saved.'),303)


@app.post('/pluto/sync')
async def pluto_sync_route():
    if PLUTO_SYNC_STATUS.get('running'):
        return RedirectResponse('/pluto?msg=Pluto+TV+sync+is+already+running.',303)
    set_setting('pluto_enabled','1')
    async def runner():
        try: await asyncio.to_thread(sync_pluto,_pluto_region())
        except Exception: pass
    task=asyncio.create_task(runner()); BACKGROUND_TASKS.add(task); task.add_done_callback(BACKGROUND_TASKS.discard)
    return RedirectResponse('/pluto?msg=Pluto+TV+sync+started.+This+page+will+refresh+while+it+runs.',303)


@app.get('/api/pluto/status')
def pluto_status_route():
    return JSONResponse(PLUTO_SYNC_STATUS)


@app.post('/pluto/import-selected')
def pluto_import_selected(channel_ids: list[str]=Form([]), action: str=Form('import')):
    if not channel_ids:
        return RedirectResponse('/pluto?msg=Select+at+least+one+Pluto+channel.',303)
    with db() as conn:
        changed=0
        for cid in channel_ids:
            row=conn.execute('SELECT * FROM pluto_channels WHERE id=?',(cid,)).fetchone()
            if not row: continue
            if action=='remove':
                conn.execute('UPDATE pluto_channels SET imported=0 WHERE id=?',(cid,)); changed+=1
            else:
                num=_pluto_assign_number(conn,row)
                conn.execute('UPDATE pluto_channels SET imported=1,display_number=? WHERE id=?',(num,cid)); changed+=1
        conn.commit()
    return RedirectResponse('/pluto?msg='+quote(f'{"Imported" if action!="remove" else "Removed"} {changed} Pluto channel(s).'),303)


@app.post('/pluto/import-all')
def pluto_import_all():
    with db() as conn:
        rows=conn.execute('SELECT * FROM pluto_channels WHERE region=? AND available=1 ORDER BY pluto_number,name',(_pluto_region(),)).fetchall(); changed=0
        for row in rows:
            num=_pluto_assign_number(conn,row)
            conn.execute('UPDATE pluto_channels SET imported=1,display_number=? WHERE id=?',(num,row['id'])); changed+=1
        conn.commit()
    return RedirectResponse('/pluto?msg='+quote(f'Imported {changed} Pluto channels into the ViperTV lineup.'),303)


@app.post('/pluto/remove-all')
def pluto_remove_all():
    with db() as conn:
        count=conn.execute('SELECT COUNT(*) c FROM pluto_channels WHERE imported=1').fetchone()['c']; conn.execute('UPDATE pluto_channels SET imported=0'); conn.commit()
    return RedirectResponse('/pluto?msg='+quote(f'Removed {count} Pluto channels from the lineup. Discovery data was kept.'),303)


# ---------------------- Shared Pluto live streaming -------------------------
PLUTO_STREAMS: dict[str,dict[str,Any]] = {}
PLUTO_HLS_PROCESSES: dict[str,dict[str,Any]] = {}


def _pluto_channel_row(channel_id: str) -> sqlite3.Row:
    with db() as conn:
        row=conn.execute('SELECT * FROM pluto_channels WHERE id=? AND imported=1 AND available=1',(channel_id,)).fetchone()
    if not row: raise HTTPException(404,'Imported Pluto channel not found')
    return row


def _pluto_label(channel_id: str) -> str:
    try:
        r=_pluto_channel_row(channel_id); return f"{r['display_number']} {r['name']}"
    except Exception: return channel_id


async def _pluto_producer(channel_id: str,state: dict[str,Any]) -> None:
    row=_pluto_channel_row(channel_id); label=_pluto_label(channel_id); region=str(row['region'] or _pluto_region()); state['started_at']=time.time(); state['error']=''; state.setdefault('restarts',0)
    print(f'Pluto shared producer started: channel={label}',flush=True)
    proc=None
    try:
        while not state.get('stop'):
            if not state['subscribers']:
                empty=state.get('empty_since') or time.time(); state['empty_since']=empty
                if time.time()-float(empty)>=SHARED_CHANNEL_GRACE_SECONDS: break
            else: state['empty_since']=None
            try:
                src=await asyncio.to_thread(pluto_stream_url,channel_id,region,False,True)
                cmd=['ffmpeg','-hide_banner','-loglevel','error','-fflags','+genpts+discardcorrupt+nobuffer','-flags','low_delay','-probesize',str(LIVE_PROBE_SIZE),'-analyzeduration',str(LIVE_ANALYZE_US),'-rw_timeout','15000000','-i',src,'-map','0:v:0?','-map','0:a:0?','-sn','-dn','-c','copy','-muxdelay','0','-muxpreload','0','-flush_packets','1','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
                proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE); state['proc']=proc; assert proc.stdout is not None
                while not state.get('stop'):
                    chunk=await proc.stdout.read(64*1024)
                    if not chunk: break
                    state['bytes']=int(state.get('bytes') or 0)+len(chunk)
                    for q in list(state['subscribers']):
                        try: q.put_nowait(chunk)
                        except asyncio.QueueFull:
                            state['subscribers'].discard(q); state['slow_disconnects']=int(state.get('slow_disconnects') or 0)+1
                            try:
                                while True: q.get_nowait()
                            except Exception: pass
                            try: q.put_nowait(None)
                            except Exception: pass
                if proc.returncode is None and state.get('stop'): proc.terminate()
                try: await asyncio.wait_for(proc.wait(),timeout=4)
                except asyncio.TimeoutError: proc.kill(); await proc.wait()
                if state.get('stop'): break
                err=''
                try:
                    raw=await proc.stderr.read() if proc.stderr else b''; err=raw.decode(errors='ignore')[-1200:]
                except Exception: pass
                state['last_return_code']=proc.returncode; state['error']=err; state['restarts']=int(state.get('restarts') or 0)+1; PLUTO_BOOT_CACHE.pop(region,None)
                await asyncio.sleep(min(10,1+state['restarts']))
            except Exception as exc:
                state['error']=str(exc); state['restarts']=int(state.get('restarts') or 0)+1; PLUTO_BOOT_CACHE.pop(region,None); await asyncio.sleep(min(10,1+state['restarts']))
    except asyncio.CancelledError: raise
    finally:
        if proc and proc.returncode is None:
            try: proc.kill(); await proc.wait()
            except Exception: pass
        state['proc']=None; state['running']=False
        for q in list(state.get('subscribers',set())):
            try: q.put_nowait(None)
            except Exception: pass
        if PLUTO_STREAMS.get(channel_id) is state: PLUTO_STREAMS.pop(channel_id,None)
        print(f'Pluto shared producer stopped: channel={label}',flush=True)


async def _subscribe_pluto(channel_id: str):
    _pluto_channel_row(channel_id)
    state=PLUTO_STREAMS.get(channel_id)
    if not state or not state.get('running') or not state.get('task') or state['task'].done():
        state={'running':True,'stop':False,'proc':None,'task':None,'subscribers':set(),'empty_since':None,'started_at':time.time(),'error':'','bytes':0,'restarts':0,'slow_disconnects':0}
        PLUTO_STREAMS[channel_id]=state; state['task']=asyncio.create_task(_pluto_producer(channel_id,state))
    q=asyncio.Queue(maxsize=SHARED_CHANNEL_QUEUE_CHUNKS); state['subscribers'].add(q); state['empty_since']=None
    print(f'Pluto viewer joined: channel={_pluto_label(channel_id)} viewers={len(state["subscribers"])}',flush=True)
    try:
        while True:
            chunk=await q.get()
            if chunk is None: break
            yield chunk
    except (asyncio.CancelledError,GeneratorExit): raise
    finally:
        state['subscribers'].discard(q)
        if not state['subscribers']: state['empty_since']=time.time()
        print(f'Pluto viewer left: channel={_pluto_label(channel_id)} viewers={len(state["subscribers"])}',flush=True)


@app.get('/internal/stream/pluto/{channel_id}.ts')
async def internal_pluto_stream(channel_id: str):
    _pluto_channel_row(channel_id)
    return StreamingResponse(_subscribe_pluto(channel_id),media_type='video/mp2t',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'})


async def _clean_pluto_client_stream(channel_id: str):
    shared=f"http://127.0.0.1:8409/internal/stream/pluto/{quote(channel_id,safe='')}.ts"
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-fflags','+genpts+discardcorrupt+nobuffer','-flags','low_delay','-probesize',str(LIVE_PROBE_SIZE),'-analyzeduration',str(LIVE_ANALYZE_US),'-max_delay','0','-i',shared,'-map','0:v:0?','-map','0:a:0?','-sn','-dn','-c','copy','-avoid_negative_ts','make_zero','-muxdelay','0','-muxpreload','0','-flush_packets','1','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
    proc=None
    try:
        proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE); assert proc.stdout is not None
        while True:
            chunk=await proc.stdout.read(64*1024)
            if not chunk: break
            yield chunk
    except (asyncio.CancelledError,GeneratorExit): raise
    finally:
        if proc and proc.returncode is None:
            try: proc.kill(); await proc.wait()
            except Exception: pass


def _pluto_fetch_playlist(url: str, region: str) -> tuple[str,str]:
    """Fetch one Pluto HLS playlist and return (text, final_url).

    Kodi/IPTV Simple does not reliably follow a ViperTV .ts URL that redirects
    to an HLS master playlist. Fetching the master inside ViperTV lets the client
    receive an actual HLS document immediately while all child playlist/segment
    URLs are made absolute against Pluto's final CDN URL.
    """
    headers=_pluto_headers(region)
    headers.update({'Accept':'application/vnd.apple.mpegurl, application/x-mpegURL, */*','User-Agent':f'{APP_NAME}/{APP_VERSION}'})
    req=URLRequest(url,headers=headers)
    with urlopen(req,timeout=15) as resp:
        raw=resp.read(2*1024*1024)
        final_url=resp.geturl() or url
    return raw.decode('utf-8',errors='replace'), final_url


def _pluto_proxy_secret() -> bytes:
    secret=get_setting('pluto_proxy_secret','') or ''
    if not secret:
        secret=uuid.uuid4().hex+uuid.uuid4().hex
        set_setting('pluto_proxy_secret',secret)
    return secret.encode('utf-8')


PLUTO_PROXY_TARGETS: dict[str, dict[str, Any]] = {}
PLUTO_PROXY_TARGET_TTL = int(os.environ.get('VIPERTV_PLUTO_PROXY_TOKEN_TTL_SECONDS','900') or 900)
PLUTO_PROXY_TARGET_MAX = int(os.environ.get('VIPERTV_PLUTO_PROXY_TOKEN_MAX','12000') or 12000)


def _pluto_proxy_cleanup(now: float | None = None) -> None:
    now=float(now if now is not None else time.time())
    expired=[k for k,v in PLUTO_PROXY_TARGETS.items() if float(v.get('expires') or 0) <= now]
    for k in expired:
        PLUTO_PROXY_TARGETS.pop(k,None)
    if len(PLUTO_PROXY_TARGETS) > PLUTO_PROXY_TARGET_MAX:
        ordered=sorted(PLUTO_PROXY_TARGETS.items(), key=lambda kv: float(kv[1].get('expires') or 0))
        for k,_ in ordered[:max(0,len(PLUTO_PROXY_TARGETS)-PLUTO_PROXY_TARGET_MAX)]:
            PLUTO_PROXY_TARGETS.pop(k,None)


def _pluto_proxy_token(channel_id: str, url: str) -> str:
    # Do NOT put Pluto's complete stitcher/JWT URL in Kodi's request path.
    # Those URLs are several KB long and can exceed the HTTP request-line limit.
    # A short HMAC-derived key maps to the real URL only inside this ViperTV process.
    if not re.match(r'^https?://',url,re.I):
        raise ValueError('Invalid Pluto proxy target')
    now=time.time(); _pluto_proxy_cleanup(now)
    material=(str(channel_id)+'\n'+url).encode('utf-8')
    digest=hmac.new(_pluto_proxy_secret(),material,hashlib.sha256).digest()[:18]
    token=base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    PLUTO_PROXY_TARGETS[token]={'channel_id':str(channel_id),'url':url,'expires':now+max(60,PLUTO_PROXY_TARGET_TTL)}
    return token


def _pluto_proxy_decode(channel_id: str, token: str) -> str:
    _pluto_proxy_cleanup()
    entry=PLUTO_PROXY_TARGETS.get(token)
    if not entry or str(entry.get('channel_id')) != str(channel_id):
        raise HTTPException(410,'Pluto proxy token expired; reopen the channel')
    url=str(entry.get('url') or '')
    if not re.match(r'^https?://',url,re.I):
        raise HTTPException(400,'Invalid Pluto proxy target')
    # Refresh active playlist/segment tokens while the channel is playing.
    entry['expires']=time.time()+max(60,PLUTO_PROXY_TARGET_TTL)
    return url


def _pluto_local_proxy_url(public_base: str, channel_id: str, target: str) -> str:
    cid=quote(str(channel_id),safe='')
    return f"{public_base}/stream/pluto/{cid}/proxy/{_pluto_proxy_token(channel_id,target)}"


def _pluto_rewrite_playlist(text: str, source_url: str, channel_id: str, public_base: str) -> str:
    """Keep the entire Pluto HLS tree behind ViperTV.

    Pluto may require the same browser-like headers/session parameters on child
    manifests, media segments, keys and init maps. Returning absolute Pluto CDN
    URLs worked temporarily, but leaves those requests outside ViperTV and some
    Kodi clients then repeatedly reopen only the root manifest. Recursive signed
    proxy URLs make every HLS request deterministic while remaining stateless.
    """
    out=[]
    uri_attr=re.compile(r'URI=("|\')([^"\']+)(\1)')
    for line in text.replace('\r\n','\n').replace('\r','\n').split('\n'):
        stripped=line.strip()
        if not stripped:
            out.append(line); continue
        if stripped.startswith('#'):
            def repl(m):
                q=m.group(1)
                target=urljoin(source_url,m.group(2))
                return 'URI='+q+_pluto_local_proxy_url(public_base,channel_id,target)+q
            out.append(uri_attr.sub(repl,line)); continue
        target=urljoin(source_url,stripped)
        out.append(_pluto_local_proxy_url(public_base,channel_id,target))
    return '\n'.join(out).rstrip()+'\n'


def _pluto_open_hls(url: str, region: str, range_header: str | None = None):
    headers=_pluto_headers(region)
    headers.update({'Accept':'application/vnd.apple.mpegurl, application/x-mpegURL, */*'})
    if range_header:
        headers['Range']=range_header
    return urlopen(URLRequest(url,headers=headers),timeout=20)


def _pluto_native_hls(channel_id: str, public_base: str) -> PlainTextResponse:
    row=_pluto_channel_row(channel_id)
    region=str(row['region'] or _pluto_region())
    try:
        target=pluto_stream_url(channel_id,region,False,True)
        with _pluto_open_hls(target,region) as resp:
            raw=resp.read(4*1024*1024)
            final_url=resp.geturl() or target
        text=raw.decode('utf-8',errors='replace')
        if '#EXTM3U' not in text[:1024]:
            raise RuntimeError('Pluto returned non-HLS data')
        text=_pluto_rewrite_playlist(text,final_url,channel_id,public_base)
        print(f'Pluto proxied HLS session: channel={row["display_number"]} {row["name"]}',flush=True)
        return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={
            'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','X-Accel-Buffering':'no'
        })
    except Exception as exc:
        print(f'Pluto proxied HLS session failed: channel={row["display_number"]} {row["name"]} error={exc}',flush=True)
        raise HTTPException(502,f'Unable to start Pluto HLS: {exc}')


def _pluto_binary_iter(resp):
    try:
        while True:
            chunk=resp.read(128*1024)
            if not chunk:
                break
            yield chunk
    finally:
        try: resp.close()
        except Exception: pass


@app.api_route('/stream/pluto/{channel_id}.m3u8',methods=['GET','HEAD'])
async def pluto_hls_kodi_route(channel_id: str,request: Request):
    _pluto_channel_row(channel_id)
    if request.method=='HEAD':
        return PlainTextResponse('',media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})
    return await asyncio.to_thread(_pluto_native_hls,channel_id,base_url(request))


@app.api_route('/stream/pluto/{channel_id}.ts',methods=['GET','HEAD'])
async def pluto_ts_route(channel_id: str,request: Request):
    # Legacy compatibility for Kodi installations that cached the old .ts URL.
    # It receives the same proxied HLS master as the modern .m3u8 route.
    _pluto_channel_row(channel_id)
    if request.method=='HEAD':
        return PlainTextResponse('',media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})
    return await asyncio.to_thread(_pluto_native_hls,channel_id,base_url(request))


@app.api_route('/stream/pluto/{channel_id}/proxy/{token}',methods=['GET','HEAD'])
async def pluto_hls_proxy(channel_id: str, token: str, request: Request):
    row=_pluto_channel_row(channel_id)
    region=str(row['region'] or _pluto_region())
    target=_pluto_proxy_decode(channel_id,token)
    if request.method=='HEAD':
        return PlainTextResponse('',headers={'Cache-Control':'no-store'})
    range_header=request.headers.get('range')
    try:
        resp=await asyncio.to_thread(_pluto_open_hls,target,region,range_header)
        ctype=str(resp.headers.get('Content-Type') or 'application/octet-stream')
        final_url=resp.geturl() or target
        path=final_url.lower().split('?',1)[0]
        is_playlist=('mpegurl' in ctype.lower() or path.endswith('.m3u8'))
        if is_playlist:
            raw=await asyncio.to_thread(resp.read,4*1024*1024)
            try: resp.close()
            except Exception: pass
            text=raw.decode('utf-8',errors='replace')
            if '#EXTM3U' not in text[:1024]:
                raise RuntimeError('Pluto child playlist was not HLS')
            text=_pluto_rewrite_playlist(text,final_url,channel_id,base_url(request))
            return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={
                'Cache-Control':'no-store, no-cache, must-revalidate','Pragma':'no-cache','X-Accel-Buffering':'no'
            })
        headers={'Cache-Control':'private, max-age=10','X-Accel-Buffering':'no'}
        for hn in ('Content-Range','Accept-Ranges','Content-Length'):
            hv=resp.headers.get(hn)
            if hv: headers[hn]=hv
        return StreamingResponse(_pluto_binary_iter(resp),status_code=getattr(resp,'status',200),media_type=ctype,headers=headers)
    except HTTPException:
        raise
    except Exception as exc:
        print(f'Pluto HLS proxy failed: channel={row["display_number"]} target={target[:180]} error={exc}',flush=True)
        raise HTTPException(502,f'Pluto HLS proxy error: {exc}')


def _pluto_hls_dir(channel_id: str) -> Path:
    safe=re.sub(r'[^A-Za-z0-9_.-]','_',channel_id)
    return BROWSER_HLS_ROOT / ('pluto_'+safe)


def _stop_pluto_hls(channel_id: str,remove_files: bool=False) -> None:
    state=PLUTO_HLS_PROCESSES.pop(channel_id,None)
    if state:
        proc=state.get('proc'); log=state.get('log_handle')
        if proc is not None and proc.poll() is None:
            try: proc.terminate(); proc.wait(timeout=3)
            except Exception:
                try: proc.kill()
                except Exception: pass
        try:
            if log: log.close()
        except Exception: pass
    if remove_files: shutil.rmtree(_pluto_hls_dir(channel_id),ignore_errors=True)


def stop_all_pluto_hls(remove_files: bool=False) -> None:
    for cid in list(PLUTO_HLS_PROCESSES): _stop_pluto_hls(cid,remove_files)


def _cleanup_pluto_hls_previews() -> None:
    now=time.time()
    for cid,st in list(PLUTO_HLS_PROCESSES.items()):
        proc=st.get('proc'); idle=now-float(st.get('last_access') or now)
        if idle>BROWSER_HLS_IDLE_SECONDS:
            _stop_pluto_hls(cid,True)
        elif proc is not None and proc.poll() is not None:
            try:
                if st.get('log_handle'):
                    st['log_handle'].close(); st['log_handle']=None
            except Exception: pass


def _start_pluto_hls(channel_id: str,force: bool=False) -> dict[str,Any]:
    row=_pluto_channel_row(channel_id); existing=PLUTO_HLS_PROCESSES.get(channel_id)
    if existing and not force and existing.get('proc') is not None and existing['proc'].poll() is None:
        existing['last_access']=time.time(); return existing
    _stop_pluto_hls(channel_id,True); out=_pluto_hls_dir(channel_id); out.mkdir(parents=True,exist_ok=True)
    shared=f"http://127.0.0.1:8409/internal/stream/pluto/{quote(channel_id,safe='')}.ts"; manifest=str(out/'index.m3u8'); pattern=str(out/'seg_%012d.ts')
    cmd=['ffmpeg','-hide_banner','-loglevel','warning','-fflags','+genpts+discardcorrupt+nobuffer','-flags','low_delay','-probesize',str(LIVE_PROBE_SIZE),'-analyzeduration',str(LIVE_ANALYZE_US),'-max_delay','0','-i',shared,'-map','0:v:0?','-map','0:a:0?','-sn','-dn','-c','copy','-avoid_negative_ts','make_zero','-f','hls','-hls_time',f'{HLS_SEGMENT_SECONDS:g}','-hls_list_size','16','-hls_delete_threshold','40','-hls_start_number_source','epoch','-hls_flags','delete_segments+independent_segments+program_date_time+temp_file','-hls_segment_filename',pattern,manifest]
    log_handle=open(out/'ffmpeg.log','ab',buffering=0); proc=subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=log_handle,start_new_session=True)
    st={'proc':proc,'log_handle':log_handle,'started_at':time.time(),'last_access':time.time(),'name':row['name']}; PLUTO_HLS_PROCESSES[channel_id]=st
    print(f'Pluto browser HLS started: channel={row["display_number"]} pid={proc.pid} {row["name"]!r}',flush=True); return st


@app.get('/preview/hls/pluto/{channel_id}/index.m3u8')
async def pluto_hls_manifest(channel_id: str):
    st=_start_pluto_hls(channel_id); st['last_access']=time.time(); path=_pluto_hls_dir(channel_id)/'index.m3u8'; deadline=time.time()+30
    while time.time()<deadline:
        if path.exists() and path.stat().st_size>60:
            text=path.read_text(errors='ignore'); durations=[float(x) for x in re.findall(r'#EXTINF:([0-9.]+)',text)]
            if sum(durations)>=2.0:
                return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store, no-cache, must-revalidate','X-Accel-Buffering':'no'})
        if st['proc'].poll() is not None: raise HTTPException(503,'Pluto browser preview stopped before producing HLS')
        await asyncio.sleep(.15)
    raise HTTPException(503,'Pluto browser preview is still starting')


@app.get('/preview/hls/pluto/{channel_id}/{segment_name}')
def pluto_hls_segment(channel_id: str,segment_name: str):
    _pluto_channel_row(channel_id)
    if not re.fullmatch(r'seg_\d+\.ts',segment_name): raise HTTPException(404,'Segment not found')
    st=PLUTO_HLS_PROCESSES.get(channel_id)
    if st: st['last_access']=time.time()
    path=_pluto_hls_dir(channel_id)/segment_name; deadline=time.time()+2
    while not path.exists() and time.time()<deadline: time.sleep(.05)
    if not path.exists(): raise HTTPException(404,'Segment expired or not ready')
    return FileResponse(path,media_type='video/mp2t',headers={'Cache-Control':'private, max-age=30'})


@app.get('/watch/pluto/{channel_id}',response_class=HTMLResponse)
def watch_pluto(channel_id: str):
    row=_pluto_channel_row(channel_id); _start_pluto_hls(channel_id); current,nxt=_pluto_now_next(channel_id)
    now_title=current['title'] if current else row['name']; now_sub=current['subtitle'] if current else 'Live Pluto TV'; next_title=nxt['title'] if nxt else 'Guide data pending'; next_sub=nxt['subtitle'] if nxt else ''
    manifest=f"/preview/hls/pluto/{quote(channel_id,safe='')}/index.m3u8"; raw=f"/stream/pluto/{quote(channel_id,safe='')}.m3u8"
    body=_page_heading(f"{row['display_number']} {row['name']}",'Live Pluto TV channel through ViperTV.',f"<a class='button secondary' href='/pluto'>Back to Pluto TV</a> <a class='button secondary' href='{raw}'>Open HLS</a>")+f"""
<div class='card' style='max-width:1100px;margin:auto'><div style='background:#05070a;border-radius:8px;overflow:hidden;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center'><video id='channel-preview' controls autoplay playsinline style='width:100%;height:100%;background:#000'></video></div>
<div class='grid' style='margin-top:16px'><div><div class='muted small'>NOW PLAYING</div><h2 style='margin:4px 0'>{e(now_title)}</h2><div>{e(now_sub or '')}</div></div><div><div class='muted small'>UP NEXT</div><h3 style='margin:4px 0'>{e(next_title)}</h3><div>{e(next_sub or '')}</div></div></div><div id='preview-status' class='muted small' style='margin-top:12px'>Building live Pluto buffer…</div></div>
<script src='/assets/hls.min.js'></script><script>(()=>{{const v=document.getElementById('channel-preview'),st=document.getElementById('preview-status'),src={json.dumps(manifest)}+'?v='+Date.now();if(v.canPlayType('application/vnd.apple.mpegurl')){{v.src=src;v.play().catch(()=>{{}});}}else if(window.Hls&&Hls.isSupported()){{const h=new Hls({{liveSyncDurationCount:2,liveMaxLatencyDurationCount:4,maxBufferLength:8,maxMaxBufferLength:12,backBufferLength:6}});h.loadSource(src);h.attachMedia(v);h.on(Hls.Events.MANIFEST_PARSED,()=>{{st.textContent='LIVE';v.play().catch(()=>{{st.textContent='Ready — press Play';}});}});h.on(Hls.Events.ERROR,(_e,d)=>{{if(d.fatal){{st.textContent='Reconnecting…';setTimeout(()=>location.reload(),1500);}}}});}}else st.textContent='This browser does not support HLS.';v.addEventListener('waiting',()=>st.textContent='Buffering…');v.addEventListener('playing',()=>st.textContent='LIVE');}})();</script>"""
    return page_shell('Watch Pluto TV',body)


@app.get('/api/pluto/streams')
def pluto_streams_status():
    rows=[]
    for cid,st in list(PLUTO_STREAMS.items()):
        p=st.get('proc'); rows.append({'channel_id':cid,'channel':_pluto_label(cid),'viewers':len(st.get('subscribers',set())),'producer_running':bool(p is not None and p.returncode is None),'uptime_seconds':int(max(0,time.time()-float(st.get('started_at') or time.time()))),'bytes':int(st.get('bytes') or 0),'restarts':int(st.get('restarts') or 0),'slow_disconnects':int(st.get('slow_disconnects') or 0),'playback_mode':'server-assisted-browser','error':str(st.get('error') or '')[-500:]})
    return JSONResponse({'channels':rows,'count':len(rows),'kodi_mode':'recursive-vipertv-hls-proxy','kodi_redirects':False,'session_isolation':'per-viewer'})


async def stop_all_pluto_streams() -> None:
    states=list(PLUTO_STREAMS.values())
    for st in states:
        st['stop']=True; proc=st.get('proc')
        if proc is not None and proc.returncode is None:
            try: proc.terminate()
            except Exception: pass
    tasks=[st.get('task') for st in states if st.get('task')]
    if tasks: await asyncio.gather(*tasks,return_exceptions=True)


@app.get("/healthz")
def healthz():
    with db() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "version": APP_VERSION, "database": str(DB_PATH), "database_exists": DB_PATH.exists()}


@app.post("/libraries/add")
def add_library(name: str = Form(...), path: str = Form(...)):
    path = os.path.abspath(path.strip())
    safe_backup_before_change()
    try:
        with db() as conn:
            conn.execute("INSERT INTO libraries(name,path,created_at) VALUES(?,?,?)", (name.strip(), path, utcnow_iso()))
            conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse("/media/local?msg=That+local+library+path+already+exists", status_code=303)
    return RedirectResponse("/media/local?msg=Local+library+added.+Click+Scan+to+index+it.", status_code=303)


@app.post("/libraries/{library_id}/scan")
async def scan_one(library_id: int):
    result = await asyncio.to_thread(scan_library, library_id)
    return RedirectResponse(f"/media/local?msg={quote(json.dumps(result, separators=(',', ':')))}", status_code=303)


@app.post("/libraries/scan-all")
async def scan_everything():
    result = await asyncio.to_thread(scan_all)
    return RedirectResponse(f"/media/local?msg={quote(json.dumps(result, separators=(',', ':')))}", status_code=303)


@app.post("/libraries/{library_id}/delete")
def delete_library(library_id: int):
    safe_backup_before_change()
    try:
        with db() as conn:
            conn.execute("DELETE FROM people_credits WHERE source_type='local' AND library_id=?", (library_id,))
            conn.execute("DELETE FROM libraries WHERE id=?", (library_id,))
            conn.commit()
    except sqlite3.IntegrityError as exc:
        return RedirectResponse(f"/media/local?msg={quote('Could not delete local library: ' + str(exc))}", status_code=303)
    return RedirectResponse("/media/local?msg=Local+library+removed+from+ViperTV.+Media+files+were+not+deleted.", status_code=303)



@app.get("/system/metadata", response_class=HTMLResponse)
def metadata_providers_manage(msg: str = ""):
    return metadata_providers_page(msg)


@app.post("/system/metadata/tvdb/save")
def tvdb_save_settings(api_key: str = Form(""), pin: str = Form("")):
    api_key=api_key.strip(); pin=pin.strip()
    if api_key:
        set_setting("tvdb_api_key",api_key)
    if pin:
        set_setting("tvdb_pin",pin)
    # Any credential change invalidates the old bearer token.
    set_setting("tvdb_token","")
    set_setting("tvdb_token_at","")
    try:
        test_tvdb_connection()
        msg="TheTVDB connection OK. You can now enrich your TV shows."
    except Exception as exc:
        msg="TheTVDB connection failed: "+str(exc)
    return RedirectResponse(f"/system/metadata?msg={quote(msg)}",status_code=303)


def _start_tvdb_enrichment(force: bool) -> RedirectResponse:
    if TVDB_ENRICH_STATUS.get("running"):
        return RedirectResponse("/system/metadata?msg=TheTVDB+enrichment+is+already+running.",status_code=303)
    if not tvdb_configured():
        return RedirectResponse("/system/metadata?msg=Configure+your+TheTVDB+API+key+first.",status_code=303)
    # Mark the run active before returning the redirect so the progress panel is
    # visible immediately, even while the worker is authenticating/building its queue.
    TVDB_ENRICH_STATUS.update({
        "running": True, "stage": "Queued", "done": 0, "total": 0, "current": "",
        "matched": 0, "failed": 0, "skipped": 0, "started_at": utcnow_iso(),
        "finished_at": None, "error": None, "force": bool(force)
    })
    async def runner():
        try:
            await asyncio.to_thread(enrich_tvdb_metadata, force, True)
        except Exception as exc:
            TVDB_ENRICH_STATUS.update({"running":False,"stage":"Failed","finished_at":utcnow_iso(),"error":str(exc)[:1000]})
            print(f"TheTVDB enrichment failed: {exc}",flush=True)
    task=asyncio.create_task(runner()); BACKGROUND_TASKS.add(task); task.add_done_callback(BACKGROUND_TASKS.discard)
    return RedirectResponse("/system/metadata?msg=TheTVDB+enrichment+started.+Live+progress+is+shown+below.",status_code=303)


@app.post("/system/metadata/tvdb/enrich")
async def tvdb_enrich_route():
    return _start_tvdb_enrichment(False)


@app.post("/system/metadata/tvdb/enrich-force")
async def tvdb_enrich_force_route():
    return _start_tvdb_enrichment(True)


@app.get("/api/tvdb/status")
def tvdb_status_route():
    return JSONResponse(TVDB_ENRICH_STATUS)


@app.get("/plex", response_class=HTMLResponse)
def plex_manage(msg: str = ""):
    return plex_page(msg)


@app.post("/plex/servers/add")
def plex_add_server(name: str = Form(""), base_url: str = Form(...), token: str = Form(...)):
    base_url = base_url.strip().rstrip("/")
    token = token.strip()
    try:
        info = test_plex_connection_data(base_url, token)
    except Exception as exc:
        return RedirectResponse(f"/plex?msg={quote('Plex connection failed: ' + str(exc))}", status_code=303)
    safe_backup_before_change()
    try:
        with db() as conn:
            now = utcnow_iso()
            conn.execute(
                """INSERT INTO plex_servers(name,base_url,token,machine_identifier,product_version,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?)
                   ON CONFLICT(base_url) DO UPDATE SET
                     name=excluded.name,token=excluded.token,machine_identifier=excluded.machine_identifier,
                     product_version=excluded.product_version,updated_at=excluded.updated_at""",
                (name.strip() or info["name"], base_url, token, info["machine_identifier"], info["version"], now, now),
            )
            conn.commit()
            server_id = conn.execute("SELECT id FROM plex_servers WHERE base_url=?", (base_url,)).fetchone()["id"]
        discover_plex_libraries(server_id)
    except Exception as exc:
        return RedirectResponse(f"/plex?msg={quote('Plex saved, but discovery failed: ' + str(exc))}", status_code=303)
    return RedirectResponse(f"/plex?msg={quote('Connected to Plex: ' + (name.strip() or info['name']))}", status_code=303)


@app.post("/plex/servers/{server_id}/test")
def plex_test_server(server_id: int):
    try:
        s = plex_server_row(server_id)
        info = test_plex_connection_data(s["base_url"], s["token"])
        with db() as conn:
            conn.execute("UPDATE plex_servers SET machine_identifier=?,product_version=?,updated_at=? WHERE id=?", (info["machine_identifier"], info["version"], utcnow_iso(), server_id))
            conn.commit()
        msg = f"Plex connection OK: {info['name']} {info['version']}"
    except Exception as exc:
        msg = f"Plex connection failed: {exc}"
    return RedirectResponse(f"/plex?msg={quote(msg)}", status_code=303)


@app.post("/plex/servers/{server_id}/discover")
def plex_discover(server_id: int):
    try:
        result = discover_plex_libraries(server_id)
        msg = f"Discovered {result['libraries']} Plex libraries on {result['server']}"
    except Exception as exc:
        msg = f"Plex discovery failed: {exc}"
    return RedirectResponse(f"/plex?msg={quote(msg)}", status_code=303)


@app.post("/plex/servers/{server_id}/delete")
def plex_delete_server(server_id: int):
    safe_backup_before_change()
    with db() as conn:
        lib_ids=[int(r['id']) for r in conn.execute("SELECT id FROM plex_libraries WHERE server_id=?",(server_id,))]
        for lid in lib_ids:
            conn.execute("DELETE FROM people_credits WHERE source_type='plex' AND library_id=?",(lid,))
        conn.execute("DELETE FROM plex_servers WHERE id=?", (server_id,))
        conn.commit()
    return RedirectResponse("/plex?msg=Plex+server+removed+from+ViperTV.+Nothing+was+changed+on+Plex.", status_code=303)


@app.post("/plex/libraries/{plex_library_id}/remove")
def plex_remove_library(plex_library_id: int):
    if PLEX_SYNC_ALL_STATUS.get("running"):
        return RedirectResponse("/plex?msg=Wait+for+Sync+All+to+finish+before+removing+a+library.", status_code=303)
    status = PLEX_SYNC_STATUS.get(plex_library_id, {})
    if status.get("running"):
        return RedirectResponse("/plex?msg=Wait+for+this+library+sync+to+finish+before+removing+it.", status_code=303)
    with db() as conn:
        row = conn.execute(
            """SELECT pl.title,ps.name AS server_name,pl.enabled
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.id=?""", (plex_library_id,)
        ).fetchone()
    if not row:
        return RedirectResponse("/plex?msg=Plex+library+not+found.", status_code=303)
    if not int(row["enabled"]):
        return RedirectResponse("/plex?msg=That+Plex+library+is+already+removed.", status_code=303)
    safe_backup_before_change()
    with db() as conn:
        selection_count = conn.execute(
            "SELECT COUNT(*) AS c FROM channel_selections WHERE plex_library_id=?", (plex_library_id,)
        ).fetchone()["c"]
        conn.execute("DELETE FROM channel_selections WHERE plex_library_id=?", (plex_library_id,))
        conn.execute("DELETE FROM people_credits WHERE source_type='plex' AND library_id=?", (plex_library_id,))
        conn.execute("DELETE FROM plex_media WHERE plex_library_id=?", (plex_library_id,))
        conn.execute(
            "UPDATE plex_libraries SET enabled=0,item_count=0,last_synced_at=NULL WHERE id=?",
            (plex_library_id,),
        )
        conn.commit()
    PLEX_SYNC_STATUS.pop(plex_library_id, None)
    msg = f"Removed {row['server_name']} / {row['title']} from ViperTV. Cleared cached metadata and {selection_count} channel selection(s). Plex was not changed."
    return RedirectResponse(f"/plex?msg={quote(msg)}", status_code=303)


@app.post("/plex/libraries/{plex_library_id}/restore")
def plex_restore_library(plex_library_id: int):
    safe_backup_before_change()
    with db() as conn:
        row = conn.execute(
            """SELECT pl.title,ps.name AS server_name
               FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id
               WHERE pl.id=?""", (plex_library_id,)
        ).fetchone()
        if not row:
            return RedirectResponse("/plex?msg=Plex+library+not+found.", status_code=303)
        conn.execute("UPDATE plex_libraries SET enabled=1 WHERE id=?", (plex_library_id,))
        conn.commit()
    msg = f"Restored {row['server_name']} / {row['title']}. Click Sync Metadata (or Sync All) to cache it again."
    return RedirectResponse(f"/plex?msg={quote(msg)}", status_code=303)


@app.post("/plex/libraries/{plex_library_id}/sync")
async def plex_sync_library_route(plex_library_id: int):
    st = PLEX_SYNC_STATUS.get(plex_library_id)
    if st and st.get("running"):
        return RedirectResponse("/plex?msg=That+Plex+library+is+already+syncing.", status_code=303)
    # Fire-and-return background sync so huge Plex libraries don't hold the browser request open.
    async def runner():
        try:
            await asyncio.to_thread(sync_plex_library, plex_library_id)
        except Exception:
            pass
    task = asyncio.create_task(runner())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return RedirectResponse("/plex?msg=Plex+metadata+sync+started.+This+page+will+refresh+while+it+runs.", status_code=303)


@app.post("/plex/libraries/{plex_library_id}/rich-credits")
async def plex_rich_episode_credits_route(plex_library_id: int):
    st=PLEX_RICH_STATUS.get(plex_library_id,{})
    if st.get('running'):
        return RedirectResponse('/plex?msg=Rich+episode+credit+import+is+already+running+for+that+library.',status_code=303)
    async def runner():
        try:
            await asyncio.to_thread(enrich_plex_episode_credits,plex_library_id,True)
        except Exception as exc:
            print(f"Plex rich-credit refresh failed: {exc}",flush=True)
    task=asyncio.create_task(runner())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return RedirectResponse('/plex?msg=Rich+episode+credit+refresh+started.+People+pages+will+gain+exact+episode+appearances+as+the+import+runs.',status_code=303)


@app.post("/plex/sync-all")
async def plex_sync_all_libraries_route():
    if PLEX_SYNC_ALL_STATUS.get("running"):
        return RedirectResponse("/plex?msg=Sync+All+is+already+running.", status_code=303)
    with db() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM plex_libraries WHERE enabled=1 AND library_type IN ('show','movie')").fetchone()["c"]
    if not count:
        return RedirectResponse("/plex?msg=No+Plex+TV+or+movie+libraries+were+found.+Discover+libraries+first.", status_code=303)

    async def runner():
        try:
            await asyncio.to_thread(sync_all_plex_libraries)
        except Exception as exc:
            print(f"Plex sync-all failed: {exc}", flush=True)

    task = asyncio.create_task(runner())
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return RedirectResponse(f"/plex?msg={quote(f'Sync All started for {count} Plex libraries. This page will refresh while it runs.')}", status_code=303)


@app.get("/api/plex/sync-status")
def plex_sync_status():
    return JSONResponse({"libraries": PLEX_SYNC_STATUS, "all": PLEX_SYNC_ALL_STATUS, "rich": PLEX_RICH_STATUS})


@app.get("/api/channels/{channel_id}/playable-count")
def channel_playable_count_api(channel_id: int):
    try:
        _, items = channel_media(channel_id)
        return JSONResponse({"count": len(items)})
    except Exception as exc:
        return JSONResponse({"count": 0, "error": str(exc)})


@app.get("/channels/ai", response_class=HTMLResponse)
def ai_channel_builder_route(prompt: str = "", msg: str = ""):
    return ai_channel_builder_page(prompt, msg)


@app.post("/channels/ai/preview", response_class=HTMLResponse)
def ai_channel_builder_preview(prompt: str = Form(...)):
    return ai_channel_builder_page(prompt)


@app.post("/channels/ai/create")
def ai_channel_builder_create(prompt: str = Form(...)):
    try:
        plan = interpret_ai_channel_prompt(prompt)
        create_channel_from_ai_plan(plan)
        detail = ' · '.join(plan.get('criteria') or []) or 'natural-language request'
        message = f"AI Channel Builder created #{plan['number']} {plan['name']} from {detail}."
        return RedirectResponse(f"/channels?msg={quote(message)}", status_code=303)
    except sqlite3.IntegrityError:
        # Most commonly a channel-number collision between preview and create.
        return RedirectResponse(f"/channels/ai?prompt={quote(prompt)}&msg={quote('Could not create channel: that channel number is already in use. Ask for another number or remove the existing channel.')}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/channels/ai?prompt={quote(prompt)}&msg={quote('Could not create channel: '+str(exc))}", status_code=303)


@app.get("/channels/auto", response_class=HTMLResponse)
def auto_channel_builder_route(msg: str=""):
    return channel_auto_builder_page(msg)


@app.post("/channels/auto/metadata")
def save_auto_channel_metadata(show_token: str = Form(...), original_network: str = Form(""), show_year: str = Form("")):
    try:
        payload=decode_selection(show_token)
        st=str(payload.get('source_type') or '')
        lib_id=int(payload.get('library_id'))
        show_key=str(payload.get('show_key') or '')
        show_title=str(payload.get('show_title') or show_key)
        if st not in {'local','plex'} or not show_key:
            raise ValueError('Invalid show selection')
        network=original_network.strip() or None
        year=safe_int(show_year)
        safe_backup_before_change()
        with db() as conn:
            if network is None and year is None:
                conn.execute("DELETE FROM show_metadata_overrides WHERE source_type=? AND library_id=? AND show_key=?",(st,lib_id,show_key))
                msg=f"Removed metadata override for {show_title}."
            else:
                conn.execute("""INSERT INTO show_metadata_overrides(source_type,library_id,show_key,show_title,original_network,show_year,updated_at)
                              VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_type,library_id,show_key) DO UPDATE SET
                              show_title=excluded.show_title,original_network=excluded.original_network,show_year=excluded.show_year,updated_at=excluded.updated_at""",
                             (st,lib_id,show_key,show_title,network,year,utcnow_iso()))
                msg=f"Saved metadata override for {show_title}."
            conn.commit()
        return RedirectResponse(f"/channels/auto?msg={quote(msg)}",status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/channels/auto?msg={quote('Could not save metadata: '+str(exc))}",status_code=303)


@app.post("/channels/auto/create")
def create_auto_channel(number: str = Form(...), name: str = Form(...), source_library: str = Form("all"),
                        network: str = Form(""), year_start: str = Form(""), year_end: str = Form(""),
                        actor: str = Form(""), director: str = Form(""), shuffle: int = Form(0)):
    ys=safe_int(year_start); ye=safe_int(year_end)
    if ys is not None and ye is None: ye=ys
    if ye is not None and ys is None: ys=ye
    if ys is not None and ye is not None and ys>ye: ys,ye=ye,ys
    actor=actor.strip(); director=director.strip()
    actors=[actor] if actor else []
    directors=[director] if director else []
    if actors or directors:
        counts=people_episode_match_counts(actors,directors,ys,ye)
        matches=filtered_auto_channel_shows(source_library,network,None,None)
        filtered=[]
        for x in matches:
            ident=(str(x['source_type']),int(x['library_id']),str(x['show_key']))
            count=int(counts.get(ident,0))
            if count:
                y=dict(x);y['episodes']=count;filtered.append(y)
        matches=filtered
    else:
        matches=filtered_auto_channel_shows(source_library,network,ys,ye)
    if not matches:
        return RedirectResponse(f"/channels/auto?msg={quote('No TV episodes matched those filters. Sync Plex/local people metadata or correct network/year metadata if needed.')}",status_code=303)
    safe_backup_before_change()
    try:
        with db() as conn:
            default_profile=default_new_channel_stream_profile()
            cur=conn.execute("INSERT INTO channels(number,name,library_id,shuffle,created_at,stream_profile) VALUES(?,?,?,?,?,?)",
                             (number.strip(),name.strip(),None,1 if shuffle else 0,utcnow_iso(),default_profile))
            channel_id=int(cur.lastrowid)
            for x in matches:
                conn.execute("""INSERT INTO channel_selections(channel_id,source_type,library_id,plex_library_id,selection_type,show_key,show_title,season_number,created_at)
                              VALUES(?,?,?,?,?,?,?,?,?)""",
                             (channel_id,x['source_type'],x['library_id'] if x['source_type']=='local' else None,
                              x['library_id'] if x['source_type']=='plex' else None,'show',x['show_key'],x['show_title'],None,utcnow_iso()))
            if actors or directors:
                conn.execute("""INSERT OR REPLACE INTO channel_people_filters(channel_id,actors_json,directors_json,air_year_start,air_year_end,created_at,updated_at)
                              VALUES(?,?,?,?,?,?,?)""",
                             (channel_id,json.dumps(actors),json.dumps(directors),ys,ye,utcnow_iso(),utcnow_iso()))
            conn.commit()
    except sqlite3.IntegrityError as exc:
        return RedirectResponse(f"/channels/auto?msg={quote('Could not create channel: '+str(exc))}",status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/channels/auto?msg={quote('Could not create channel: '+str(exc))}",status_code=303)
    filters=[]
    if network.strip(): filters.append(network.strip())
    if actor: filters.append('starring '+actor)
    if director: filters.append('directed by '+director)
    if ys is not None: filters.append((str(ys) if ys==ye else f"{ys}-{ye}") + (' episode air years' if (actors or directors) else ' premiere years'))
    desc=' + '.join(filters) or 'all TV shows'
    return RedirectResponse(f"/channels?msg={quote(f'Created {name.strip()} from {desc}: {len(matches)} shows selected.')}",status_code=303)


@app.get("/channels/new", response_class=HTMLResponse)
def new_channel_page():
    return channel_builder_page()


@app.post("/channels/create")
def create_channel(number: str = Form(...), name: str = Form(...), shuffle: int = Form(0), sel: list[str] = Form(default=[])):
    safe_backup_before_change()
    try:
        with db() as conn:
            default_profile = default_new_channel_stream_profile()
            cur = conn.execute(
                "INSERT INTO channels(number,name,library_id,shuffle,created_at,stream_profile) VALUES(?,?,?,?,?,?)",
                (number.strip(), name.strip(), None, 1 if shuffle else 0, utcnow_iso(), default_profile),
            )
            channel_id = int(cur.lastrowid)
            conn.commit()
        count = save_channel_selections(channel_id, sel)
    except sqlite3.IntegrityError as exc:
        return RedirectResponse(f"/channels?msg={quote('Could not create channel: ' + str(exc))}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/channels?msg={quote('Could not create channel: ' + str(exc))}", status_code=303)
    return RedirectResponse(f"/channels?msg={quote(f'Channel created with {count} content selection(s). A whole show counts as one selection.')}", status_code=303)


@app.get("/channels/{channel_id}/edit", response_class=HTMLResponse)
def edit_channel_page(channel_id: int, msg: str = ""):
    return channel_builder_page(channel_id, msg)


@app.post("/channels/{channel_id}/people-filter/delete")
def delete_channel_people_filter(channel_id: int):
    safe_backup_before_change()
    with db() as conn:
        channel = conn.execute("SELECT id FROM channels WHERE id=?", (channel_id,)).fetchone()
        if not channel:
            return RedirectResponse("/channels?msg=Channel+not+found.", status_code=303)
        conn.execute("DELETE FROM channel_people_filters WHERE channel_id=?", (channel_id,))
        conn.commit()
    return RedirectResponse(f"/channels/{channel_id}/edit?msg={quote('People filter removed. Existing show selections were kept.')}", status_code=303)


@app.post("/channels/{channel_id}/save")
def save_channel(channel_id: int, number: str = Form(...), name: str = Form(...), shuffle: int = Form(0), sel: list[str] = Form(default=[])):
    safe_backup_before_change()
    try:
        with db() as conn:
            conn.execute("UPDATE channels SET number=?,name=?,shuffle=? WHERE id=?", (number.strip(), name.strip(), 1 if shuffle else 0, channel_id))
            conn.commit()
        count = save_channel_selections(channel_id, sel)
    except Exception as exc:
        return RedirectResponse(f"/channels?msg={quote('Could not save channel: ' + str(exc))}", status_code=303)
    return RedirectResponse(f"/channels?msg={quote(f'Channel saved with {count} content selection(s). A whole show counts as one selection.')}", status_code=303)


def _delete_channel_ids(conn: sqlite3.Connection, channel_ids: list[int]) -> int:
    ids = sorted({int(x) for x in channel_ids if int(x) > 0})
    if not ids:
        return 0
    # SQLite parameter limits are commonly >=999; process in conservative chunks.
    deleted = 0
    for start in range(0, len(ids), 400):
        chunk = ids[start:start+400]
        marks = ','.join('?' for _ in chunk)
        # playout_state intentionally has no FK, and schedules on another channel
        # may reference a channel as a source, so clean both explicitly.
        conn.execute(f"DELETE FROM playout_state WHERE channel_id IN ({marks})", chunk)
        conn.execute(f"DELETE FROM schedule_items WHERE source_type='channel' AND source_id IN ({marks})", chunk)
        cur = conn.execute(f"DELETE FROM channels WHERE id IN ({marks})", chunk)
        deleted += max(0, cur.rowcount)
    return deleted


@app.post("/channels/delete-selected")
def delete_selected_channels(channel_ids: list[int] = Form(default=[])):
    ids = sorted({int(x) for x in channel_ids if int(x) > 0})
    if not ids:
        return RedirectResponse("/channels?msg=No+channels+were+selected.", status_code=303)
    with db() as conn:
        marks = ','.join('?' for _ in ids)
        found = conn.execute(f"SELECT id,number,name FROM channels WHERE id IN ({marks}) ORDER BY CAST(number AS REAL),number", ids).fetchall()
    if not found:
        return RedirectResponse("/channels?msg=Selected+channels+were+not+found.", status_code=303)
    safe_backup_before_change()
    with db() as conn:
        deleted = _delete_channel_ids(conn, [r['id'] for r in found])
        conn.commit()
    return RedirectResponse(f"/channels?msg={quote(f'Deleted {deleted} selected channel(s). Media files and source libraries were not changed.')}", status_code=303)


@app.post("/channels/reset-all")
def reset_all_channels():
    with db() as conn:
        channel_count = int(conn.execute("SELECT COUNT(*) c FROM channels").fetchone()['c'])
    if channel_count == 0:
        return RedirectResponse("/channels?msg=There+are+no+channels+to+reset.", status_code=303)
    safe_backup_before_change()
    with db() as conn:
        conn.execute("DELETE FROM playout_state")
        conn.execute("DELETE FROM channels")
        # Reset only the internal channel id sequence; user-visible channel numbers
        # are always chosen by the user and are unaffected by this.
        try:
            conn.execute("DELETE FROM sqlite_sequence WHERE name='channels'")
        except sqlite3.OperationalError:
            pass
        conn.commit()
    msg = f"Reset complete. Deleted all {channel_count} channel(s) and their schedules/playout state. Libraries, media and collections were kept."
    return RedirectResponse(f"/channels?msg={quote(msg)}", status_code=303)


@app.post("/channels/{channel_id}/delete")
def delete_channel(channel_id: int):
    with db() as conn:
        channel = conn.execute("SELECT number,name FROM channels WHERE id=?", (channel_id,)).fetchone()
    if not channel:
        return RedirectResponse("/channels?msg=Channel+not+found.", status_code=303)
    safe_backup_before_change()
    with db() as conn:
        _delete_channel_ids(conn, [channel_id])
        conn.commit()
    message = f"Deleted channel {channel['number']} - {channel['name']}. Media files and source libraries were not changed."
    return RedirectResponse(f"/channels?msg={quote(message)}", status_code=303)


@app.post("/maintenance/backup")
def backup_now():
    result = backup_all("manual")
    return RedirectResponse(f"/maintenance?msg={quote('Backup complete: ' + json.dumps(result))}", status_code=303)


@app.get("/export/config.json")
def export_config():
    with db() as conn:
        libraries = [dict(r) for r in conn.execute("SELECT * FROM libraries ORDER BY id")]
        channels = [dict(r) for r in conn.execute("SELECT * FROM channels ORDER BY id")]
        selections = [dict(r) for r in conn.execute("SELECT * FROM channel_selections ORDER BY id")]
        plex_servers = [
            {k: v for k, v in dict(r).items() if k != "token"}
            for r in conn.execute("SELECT * FROM plex_servers ORDER BY id")
        ]
        plex_libraries = [dict(r) for r in conn.execute("SELECT * FROM plex_libraries ORDER BY id")]
        media_count = conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"]
        plex_media_count = conn.execute("SELECT COUNT(*) c FROM plex_media").fetchone()["c"]
    return JSONResponse({
        "app": APP_NAME, "version": APP_VERSION, "exported_at": utcnow_iso(),
        "libraries": libraries, "channels": channels, "channel_selections": selections,
        "plex_servers_without_tokens": plex_servers, "plex_libraries": plex_libraries,
        "local_media_index_count": media_count, "plex_media_cache_count": plex_media_count,
        "note": "Plex tokens are intentionally excluded. Media catalogs can be regenerated by local scan/Plex sync.",
    }, headers={"Content-Disposition": "attachment; filename=vipertv-config.json"})


@app.get("/api/status")
def api_status():
    with db() as conn:
        return {
            "version": APP_VERSION,
            "local_libraries": conn.execute("SELECT COUNT(*) c FROM libraries").fetchone()["c"],
            "local_media": conn.execute("SELECT COUNT(*) c FROM media").fetchone()["c"],
            "plex_servers": conn.execute("SELECT COUNT(*) c FROM plex_servers").fetchone()["c"],
            "plex_libraries": conn.execute("SELECT COUNT(*) c FROM plex_libraries").fetchone()["c"],
            "plex_media": conn.execute("SELECT COUNT(*) c FROM plex_media").fetchone()["c"],
            "channels": conn.execute("SELECT COUNT(*) c FROM channels").fetchone()["c"],
            "database": str(DB_PATH),
        }


def channel_stream_url(url: str, channel_number: str) -> str:
    # Channel-number URLs remain stable if a channel is deleted/recreated.
    # This avoids IPTV clients (notably Kodi IPTV Simple) retaining a dead DB-id URL.
    return f"{url}/stream/channel/{quote(str(channel_number), safe='')}.ts"


def resolve_channel_ref(channel_ref: int) -> int:
    """Resolve the legacy numeric stream reference.

    Older ViperTV playlists used the SQLite channel id in /stream/<id>.ts.
    If that row was deleted and a replacement channel reuses the same visible
    channel number, fall back to that number so cached Kodi playlists keep
    working until their next M3U refresh.
    """
    with db() as conn:
        row = conn.execute("SELECT id FROM channels WHERE id=? AND enabled=1", (channel_ref,)).fetchone()
        if row is None:
            row = conn.execute("SELECT id FROM channels WHERE number=? AND enabled=1", (str(channel_ref),)).fetchone()
    if row is None:
        raise HTTPException(404, "Channel not found")
    return int(row["id"])


def resolve_channel_number(channel_number: str) -> int:
    with db() as conn:
        row = conn.execute("SELECT id FROM channels WHERE number=? AND enabled=1", (channel_number,)).fetchone()
    if row is None:
        raise HTTPException(404, "Channel not found")
    return int(row["id"])


@app.api_route("/iptv/channels.m3u", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def m3u(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse("", media_type="audio/x-mpegurl", headers={"Cache-Control":"no-store"})
    url = base_url(request)
    with db() as conn:
        channels = conn.execute("SELECT * FROM channels WHERE enabled=1 ORDER BY CAST(number AS REAL),number").fetchall()
        pluto_channels = conn.execute("SELECT * FROM pluto_channels WHERE imported=1 AND available=1 ORDER BY CAST(display_number AS REAL),display_number,name").fetchall()
        live_streams = conn.execute("SELECT * FROM live_streams WHERE enabled=1 ORDER BY CAST(number AS REAL),number,name").fetchall()
    lines = [f'#EXTM3U url-tvg="{url}/iptv/xmltv.xml"']
    for c in channels:
        stable_id = f"vipertv-channel-{c['number']}"
        lines.append(f'#EXTINF:-1 tvg-id="{stable_id}" tvg-chno="{c["number"]}" tvg-name="{c["name"]}",{c["name"]}')
        lines.append(channel_stream_url(url, c["number"]))
    for pch in pluto_channels:
        stable_id = f"vipertv-pluto-{pch['id']}"
        logo = str(pch['logo_url'] or '').replace('"','')
        group = ("Pluto TV" + (" / " + str(pch['category']) if pch['category'] else '')).replace('"','')
        name = str(pch['name']).replace('"','')
        lines.append(f'#EXTINF:-1 tvg-id="{stable_id}" tvg-chno="{pch["display_number"]}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}')
        lines.append(f"{url}/stream/pluto/{quote(str(pch['id']), safe='')}.m3u8")
    for ls in live_streams:
        stable_id=f"vipertv-live-{ls['id']}"
        logo=str(ls['logo_url'] or '').replace('"','')
        group=str(ls['group_name'] or 'Live IPTV').replace('"','')
        name=str(ls['name']).replace('"','')
        lines.append(f'#EXTINF:-1 tvg-id="{stable_id}" tvg-chno="{ls["number"]}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group}",{name}')
        lines.append(f"{url}/stream/live/{int(ls['id'])}.m3u8")
    return "\n".join(lines) + "\n"


def xml_escape(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def xmltv_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S +0000")


@app.api_route("/iptv/xmltv.xml", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def xmltv(request: Request):
    if request.method == "HEAD":
        return PlainTextResponse("", media_type="application/xml", headers={"Cache-Control":"no-store"})
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(hours=48)
    with db() as conn:
        channels = conn.execute("SELECT * FROM channels WHERE enabled=1 ORDER BY CAST(number AS REAL),number").fetchall()
        pluto_channels = conn.execute("SELECT * FROM pluto_channels WHERE imported=1 AND available=1 ORDER BY CAST(display_number AS REAL),display_number,name").fetchall()
        live_streams = conn.execute("SELECT * FROM live_streams WHERE enabled=1 ORDER BY CAST(number AS REAL),number,name").fetchall()

    out = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv generator-info-name="ViperTV">']
    for c in channels:
        out.append(f'<channel id="vipertv-channel-{xml_escape(c["number"])}"><display-name>{xml_escape(c["number"] + " " + c["name"])}</display-name></channel>')
    for pch in pluto_channels:
        icon = f'<icon src="{xml_escape(str(pch["logo_url"]))}"/>' if pch['logo_url'] else ''
        out.append(f'<channel id="vipertv-pluto-{xml_escape(str(pch["id"]))}"><display-name>{xml_escape(str(pch["display_number"]) + " " + str(pch["name"]))}</display-name>{icon}</channel>')
    for ls in live_streams:
        icon=f'<icon src="{xml_escape(str(ls["logo_url"]))}"/>' if ls['logo_url'] else ''
        out.append(f'<channel id="vipertv-live-{int(ls["id"])}"><display-name>{xml_escape(str(ls["number"]) + " " + str(ls["name"]))}</display-name>{icon}</channel>')

    for c in channels:
        try:
            retro_cfg = _retro_config_for_channel(int(c["id"]))
            if retro_cfg:
                for pr in _retro_xmltv_programmes(int(c["id"]), now, horizon):
                    body = f'<programme start="{xmltv_time(pr["start"])}" stop="{xmltv_time(pr["stop"])}" channel="vipertv-channel-{xml_escape(c["number"])}">'
                    body += f'<title>{xml_escape(str(pr["title"]))}</title>'
                    if pr.get("subtitle"):
                        body += f'<sub-title>{xml_escape(str(pr["subtitle"]))}</sub-title>'
                    body += f'<desc>{xml_escape(str(pr.get("desc") or "Retro TV reconstruction"))}</desc>'
                    if pr.get("missing"):
                        body += '<category>Unavailable</category>'
                    else:
                        body += '<category>Retro TV</category>'
                    body += '</programme>'
                    out.append(body)
                continue
            _, items = channel_media(c["id"])
            if not items:
                continue
            idx, _, current_start = locate_at(items, now)
            cursor = current_start
            i = idx
            safety = 0
            while cursor < horizon and safety < 10000:
                item = items[i]
                dur = float(item["duration"])
                actual_end = cursor + timedelta(seconds=dur)
                guide_dur = float(item.get('_guide_duration') or dur)
                end = cursor + timedelta(seconds=guide_dur)
                if item.get('_guide_hidden'):
                    cursor=actual_end;i=(i+1)%len(items);safety+=1;continue
                if item.get('_guide_custom_title'):
                    title=item.get('_guide_custom_title');subtitle=''
                elif item.get("show_title"):
                    title = item["show_title"]
                    subtitle = item.get("episode_title") or item.get("title") or ""
                else:
                    title = item.get("title") or "Untitled"
                    subtitle = ""
                body = (
                    f'<programme start="{xmltv_time(cursor)}" stop="{xmltv_time(end)}" channel="vipertv-channel-{xml_escape(c["number"])}">'
                    f'<title>{xml_escape(str(title))}</title>'
                )
                if subtitle and subtitle != title:
                    body += f'<sub-title>{xml_escape(str(subtitle))}</sub-title>'
                if item.get("season_number") is not None and item.get("episode_number") is not None:
                    body += f'<episode-num system="onscreen">S{int(item["season_number"]):02d}E{int(item["episode_number"]):02d}</episode-num>'
                desc = item.get("summary") or (Path(item["path"]).name if item.get("path") else "Plex")
                body += f'<desc>{xml_escape(str(desc))}</desc>'
                if item.get("air_date"):
                    body += f'<date>{xml_escape(str(item["air_date"]).replace("-", ""))}</date>'
                body += '</programme>'
                out.append(body)
                cursor = actual_end
                i = (i + 1) % len(items)
                safety += 1
        except Exception as exc:
            print(f"XMLTV channel {c['id']} error: {exc}", flush=True)

    # Pluto TV already supplies a real broadcast schedule.  Use the cached
    # regional timeline rather than synthesizing a repeating playout.
    if pluto_channels:
        ids = [str(x['id']) for x in pluto_channels]
        marks = ','.join('?' for _ in ids)
        with db() as conn:
            prows = conn.execute(
                f"SELECT * FROM pluto_epg WHERE channel_id IN ({marks}) AND stop_utc>? AND start_utc<? ORDER BY start_utc",
                (*ids, now.isoformat(), horizon.isoformat()),
            ).fetchall()
        for pr in prows:
            try:
                start = _parse_pluto_iso(pr['start_utc'])
                stop = _parse_pluto_iso(pr['stop_utc'])
                if not start or not stop:
                    continue
                body = f'<programme start="{xmltv_time(start)}" stop="{xmltv_time(stop)}" channel="vipertv-pluto-{xml_escape(str(pr["channel_id"]))}">'
                body += f'<title>{xml_escape(str(pr["title"] or "Pluto TV"))}</title>'
                if pr['subtitle']:
                    body += f'<sub-title>{xml_escape(str(pr["subtitle"]))}</sub-title>'
                if pr['description']:
                    body += f'<desc>{xml_escape(str(pr["description"]))}</desc>'
                if pr['category']:
                    body += f'<category>{xml_escape(str(pr["category"]))}</category>'
                if pr['episode_number']:
                    body += f'<episode-num system="onscreen">{xml_escape(str(pr["episode_number"]))}</episode-num>'
                body += '</programme>'
                out.append(body)
            except Exception as exc:
                print(f"XMLTV Pluto programme error: {exc}", flush=True)
    out.append("</tv>")
    return PlainTextResponse("\n".join(out) + "\n", media_type="application/xml")



# ========================= Retro TV Recreator v1.1.32 =========================
# Rebuild a historical broadcast day against the user's own Plex/local catalog.
# Exact wall-clock slots are authoritative: programmes are truncated at the next
# scheduled boundary, short media is padded with filler, and unavailable titles
# receive Music Videos while remaining visible in the Wanted Programs list.

def init_retro_tv_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS retro_schedules(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          channel_id INTEGER NOT NULL UNIQUE REFERENCES channels(id) ON DELETE CASCADE,
          name TEXT NOT NULL,
          source_kind TEXT NOT NULL DEFAULT 'manual',
          source_url TEXT,
          source_date TEXT NOT NULL,
          network TEXT NOT NULL,
          timezone TEXT NOT NULL DEFAULT 'UTC',
          filler_library_id INTEGER REFERENCES libraries(id) ON DELETE SET NULL,
          missing_media TEXT,
          repeat_mode TEXT NOT NULL DEFAULT 'daily',
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS retro_slots(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          schedule_id INTEGER NOT NULL REFERENCES retro_schedules(id) ON DELETE CASCADE,
          position INTEGER NOT NULL DEFAULT 0,
          start_minute INTEGER NOT NULL,
          end_minute INTEGER NOT NULL,
          title TEXT NOT NULL,
          episode_title TEXT,
          description TEXT,
          matched_source TEXT,
          matched_media_id INTEGER,
          match_status TEXT NOT NULL DEFAULT 'missing',
          match_score INTEGER NOT NULL DEFAULT 0,
          UNIQUE(schedule_id,position)
        );
        CREATE INDEX IF NOT EXISTS idx_retro_slots_schedule_time ON retro_slots(schedule_id,start_minute,end_minute);
        CREATE TABLE IF NOT EXISTS retro_wanted(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          schedule_id INTEGER NOT NULL REFERENCES retro_schedules(id) ON DELETE CASCADE,
          slot_id INTEGER REFERENCES retro_slots(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          episode_title TEXT,
          first_seen TEXT NOT NULL,
          last_seen TEXT NOT NULL,
          resolved INTEGER NOT NULL DEFAULT 0,
          UNIQUE(schedule_id,slot_id)
        );
        """)
        conn.commit()


def _retro_config_for_channel(channel_id: int) -> dict[str, Any] | None:
    try:
        with db() as conn:
            r=conn.execute('SELECT * FROM retro_schedules WHERE channel_id=? AND enabled=1',(channel_id,)).fetchone()
        return dict(r) if r else None
    except Exception:
        return None


def _retro_norm(value: str | None) -> str:
    x=(value or '').casefold().replace('&',' and ')
    x=re.sub(r"[^a-z0-9]+"," ",x)
    return re.sub(r"\s+"," ",x).strip()


def _retro_match_program(title: str, episode_title: str | None, source_date: str) -> dict[str, Any]:
    nt=_retro_norm(title); ne=_retro_norm(episode_title)
    if not nt:
        return {'source':None,'id':None,'status':'missing','score':0}
    candidates=[]
    with db() as conn:
        # Keep candidate sets bounded but consider both episodic and movie media.
        for r in conn.execute("SELECT id,title,show_title,episode_title,season_number,episode_number FROM media WHERE duration>0 AND (lower(show_title)=lower(?) OR lower(title)=lower(?) OR lower(episode_title)=lower(?)) LIMIT 500",(title,title,episode_title or '')):
            candidates.append(('local',dict(r),None))
        for r in conn.execute("SELECT id,title,show_title,season_number,episode_number,originally_available_at,media_type FROM plex_media WHERE duration>0 AND (lower(show_title)=lower(?) OR lower(title)=lower(?)) LIMIT 500",(title,title)):
            candidates.append(('plex',dict(r),r['originally_available_at']))
        # Fallback title candidates handle punctuation variants such as '&' vs 'and'.
        if not candidates:
            for r in conn.execute("SELECT id,title,show_title,episode_title,season_number,episode_number FROM media WHERE duration>0 AND (show_title IS NOT NULL OR title IS NOT NULL) LIMIT 20000"):
                rr=dict(r)
                if _retro_norm(rr.get('show_title'))==nt or _retro_norm(rr.get('title'))==nt:
                    candidates.append(('local',rr,None))
            for r in conn.execute("SELECT id,title,show_title,season_number,episode_number,originally_available_at,media_type FROM plex_media WHERE duration>0 LIMIT 20000"):
                rr=dict(r)
                if _retro_norm(rr.get('show_title'))==nt or _retro_norm(rr.get('title'))==nt:
                    candidates.append(('plex',rr,rr.get('originally_available_at')))
    best=None
    for source,r,air in candidates:
        show_n=_retro_norm(r.get('show_title')); title_n=_retro_norm(r.get('title'))
        ep_n=_retro_norm(r.get('episode_title') if source=='local' else r.get('title'))
        score=0; status='missing'
        if ne and show_n==nt and ep_n==ne:
            score=100;status='exact_episode'
        elif source=='plex' and show_n==nt and air and str(air)[:10]==source_date:
            score=98;status='airdate'
        elif not r.get('show_title') and title_n==nt:
            score=95;status='movie'
        elif show_n==nt:
            score=82;status='show'
        elif title_n==nt:
            score=78;status='title'
        if score and (best is None or score>best['score']):
            best={'source':source,'id':int(r['id']),'status':status,'score':score}
    return best or {'source':None,'id':None,'status':'missing','score':0}


def _retro_resolve_media(source: str, media_id: int) -> dict[str, Any] | None:
    with db() as conn:
        if source=='local':
            r=conn.execute("SELECT m.*,l.name library_name FROM media m JOIN libraries l ON l.id=m.library_id WHERE m.id=? AND m.duration>0",(media_id,)).fetchone()
            if not r:return None
            return {'source_type':'local','uid':f'retro-local:{media_id}','path':r['path'],'title':r['title'],'duration':float(r['duration']),'show_title':r['show_title'],'season_number':r['season_number'],'episode_number':r['episode_number'],'episode_title':r['episode_title'] or r['title'],'library_name':r['library_name'],'media_type':'episode' if r['show_title'] else 'movie'}
        r=conn.execute("SELECT pm.*,pl.title library_name FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id WHERE pm.id=? AND pm.duration>0",(media_id,)).fetchone()
        if not r:return None
        return {'source_type':'plex','uid':f'retro-plex:{media_id}','plex_library_id':r['plex_library_id'],'plex_key':r['plex_key'],'title':r['title'],'duration':float(r['duration']),'show_title':r['show_title'],'season_number':r['season_number'],'episode_number':r['episode_number'],'episode_title':r['title'],'summary':r['summary'],'air_date':r['originally_available_at'],'library_name':r['library_name'],'media_type':r['media_type']}


def _retro_music_video_items() -> list[dict[str,Any]]:
    """Return every playable item from libraries classified as Music Videos.

    Retro TV uses this one pool for both ordinary between-show filler and the
    entire duration of unavailable historical programmes.  Local and Plex
    Music Videos libraries are both supported automatically; no per-channel
    filler library selection is required.
    """
    items: list[dict[str,Any]] = []
    with db() as conn:
        local_rows=conn.execute("""
            SELECT m.*,l.name library_name
              FROM media m JOIN libraries l ON l.id=m.library_id
             WHERE m.duration>0 AND lower(l.name) LIKE '%music videos%'
             ORDER BY l.name COLLATE NOCASE,m.id
        """).fetchall()
        plex_rows=conn.execute("""
            SELECT pm.*,pl.title library_name
              FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id
             WHERE pm.duration>0 AND pl.enabled=1
               AND lower(pl.title) LIKE '%music videos%'
             ORDER BY pl.title COLLATE NOCASE,pm.id
        """).fetchall()
    for r in local_rows:
        items.append({
            'source_type':'local','uid':f'retro-mv-local:{r["id"]}',
            'path':r['path'],'title':r['title'],'duration':float(r['duration']),
            'show_title':r['show_title'],'episode_title':r['episode_title'] or r['title'],
            'library_name':r['library_name'],'media_type':'music_video'
        })
    for r in plex_rows:
        items.append({
            'source_type':'plex','uid':f'retro-mv-plex:{r["id"]}',
            'plex_library_id':r['plex_library_id'],'plex_key':r['plex_key'],
            'title':r['title'],'duration':float(r['duration']),
            'show_title':r['show_title'],'episode_title':r['title'],
            'summary':r['summary'],'air_date':r['originally_available_at'],
            'library_name':r['library_name'],'media_type':'music_video'
        })
    return items


def _retro_manual_lines(text: str) -> list[dict[str,Any]]:
    parsed=[]
    for raw in (text or '').splitlines():
        line=raw.strip()
        if not line or line.startswith('#'):continue
        parts=[x.strip() for x in line.split('|')]
        if len(parts)<2:continue
        m=re.match(r'^(\d{1,2}):(\d{2})$',parts[0])
        if not m:continue
        minute=int(m.group(1))*60+int(m.group(2))
        if not 0<=minute<1440:continue
        parsed.append({'start_minute':minute,'title':parts[1],'episode_title':parts[2] if len(parts)>2 and parts[2] else None,'description':parts[3] if len(parts)>3 else None})
    parsed.sort(key=lambda x:x['start_minute'])
    for i,x in enumerate(parsed):
        x['end_minute']=parsed[i+1]['start_minute'] if i+1<len(parsed) else min(1440,x['start_minute']+30)
        if x['end_minute']<=x['start_minute']:x['end_minute']=min(1440,x['start_minute']+30)
    return parsed


def _retro_parse_clock(text: str) -> int | None:
    t=re.sub(r'\s+',' ',text.strip().lower()).replace('.','')
    for fmt in ('%I:%M %p','%I %p','%H:%M'):
        try:
            d=datetime.strptime(t,fmt);return d.hour*60+d.minute
        except Exception:pass
    return None


def _retro_parse_tvtango_html(raw: str, network: str) -> list[dict[str,Any]]:
    """Parse TVTango's actual HTML grid, preserving colspan-based durations.

    This parser is shared by both direct TVTango fetches and the Jina Reader
    fallback.  Requesting HTML from Reader is important: Markdown conversion
    loses HTML table colspan information, which makes one-hour programmes
    impossible to place reliably on a half-hour grid.
    """
    soup=BeautifulSoup(raw or '', 'html.parser')
    wanted=_retro_norm(network)
    found=[]
    for table in soup.find_all('table'):
        rows=table.find_all('tr')
        if not rows: continue
        headers=[]
        header_row_index=None
        for ri,row in enumerate(rows[:4]):
            trial=[]
            for cell in row.find_all(['th','td']):
                trial.append(_retro_parse_clock(cell.get_text(' ',strip=True)))
            if sum(x is not None for x in trial)>=2:
                headers=trial
                header_row_index=ri
                break
        if header_row_index is None: continue
        clock_headers=[x for x in headers if x is not None]
        if not clock_headers: continue
        step=30
        for row in rows[header_row_index+1:]:
            cells=row.find_all(['th','td'])
            if len(cells)<2: continue
            # Logos/images may precede the station name.  Compare against the
            # visible text in the first two cells and also against a cleaned
            # concatenation so Reader/browser HTML variants both work.
            labels=[]
            for c in cells[:2]:
                txt=re.sub(r'\s+',' ',c.get_text(' ',strip=True)).strip()
                if txt: labels.append(txt)
            label=' '.join(labels)
            label_norm=_retro_norm(re.sub(r'(?i)\bimage\s*\d*\b',' ',label))
            wanted_hit=(label_norm==wanted or re.search(r'(?<![a-z0-9])'+re.escape(wanted)+r'(?![a-z0-9])',label_norm) is not None)
            if not wanted_hit: continue

            # Determine where programme cells begin.  Most TVTango rows use one
            # label cell; Reader/browser-rendered HTML can expose logo and station
            # as separate cells.  Skip leading cells until the network label has
            # been consumed, but never skip an actual programme cell.
            first_prog=1
            if len(cells)>=3:
                c0=_retro_norm(re.sub(r'(?i)\bimage\s*\d*\b',' ',cells[0].get_text(' ',strip=True)))
                c1=_retro_norm(re.sub(r'(?i)\bimage\s*\d*\b',' ',cells[1].get_text(' ',strip=True)))
                if c1==wanted and c0!=wanted:
                    first_prog=2
            cursor=clock_headers[0]
            for cell in cells[first_prog:]:
                try: span=max(1,int(cell.get('colspan') or 1))
                except Exception: span=1
                lines=[]
                for x in cell.stripped_strings:
                    x=re.sub(r'\s+',' ',x.strip())
                    if x: lines.append(x)
                text=' '.join(lines).strip()
                if not text:
                    cursor+=step*span
                    continue
                # The first meaningful line is the title.  Ignore generic image
                # labels and common TVTango decorations if they leak through.
                useful=[x for x in lines if not re.fullmatch(r'(?i)image\s*\d*',x)]
                title=useful[0] if useful else text
                subtitle=None
                for x in useful[1:5]:
                    if not re.search(r'(?i)^(rating|share|viewers)\b|\b(new|repeat|watch|stream|own)\b',x):
                        subtitle=x
                        break
                if title:
                    found.append({
                        'start_minute':cursor,
                        'end_minute':min(1440,cursor+step*span),
                        'title':title,
                        'episode_title':subtitle,
                        'description':None,
                    })
                cursor+=step*span
    unique=[];seen=set()
    for x in sorted(found,key=lambda z:z['start_minute']):
        k=(x['start_minute'],_retro_norm(x['title']))
        if k in seen: continue
        seen.add(k);unique.append(x)
    return unique


def _retro_reader_clean_cell(value: str) -> str:
    x=value or ''
    # Preserve cell-internal line breaks because Reader uses them to separate
    # programme title, episode title and rating/status decorations.
    x=x.replace('\\n','\n')
    x=re.sub(r'(?i)<br\s*/?>','\n',x)
    x=re.sub(r'!\[[^]]*\]\([^)]*\)',' ',x)
    x=re.sub(r'\[(?:Image|Logo)[^]]*\]\([^)]*\)',' ',x,flags=re.I)
    x=re.sub(r'\[([^]]+)\]\([^)]*\)',r'\1',x)
    x=re.sub(r'<[^>]+>',' ',x)
    x=re.sub(r'(?i)\bimage\s*\d*\b',' ',x)
    x=re.sub(r'[ \t]+',' ',x)
    x=re.sub(r' *\n *','\n',x)
    return x.strip()


def _retro_reader_program_cell(value: str) -> tuple[str|None,str|None]:
    """Extract a programme/episode title from one Reader table cell."""
    x=_retro_reader_clean_cell(value)
    if not x:
        return None,None
    raw_lines=[]
    for line in re.split(r'\n+|\s{2,}',x):
        line=re.sub(r'^\s*[-*+]\s*','',line).strip(' |')
        if not line: continue
        if re.search(r'(?i)^(rating|share|viewers)\s*:',line): continue
        if re.search(r'(?i)^(click icon|own/stream|watch free|watch now)\b',line): continue
        if re.fullmatch(r'(?i)(new|repeat|season premiere|series premiere|finale)',line): continue
        raw_lines.append(line)
    if not raw_lines:
        return None,None
    title=raw_lines[0]
    # Reader often flattens "Title\nEpisode title New\nRating...". Remove
    # trailing status words from the first/second meaningful lines.
    title=re.sub(r'\s+(?:New|\(Repeat\)|Repeat)\s*$','',title,flags=re.I).strip()
    episode=None
    for cand in raw_lines[1:5]:
        cand=re.sub(r'\s+(?:New|\(Repeat\)|Repeat)\s*$','',cand,flags=re.I).strip()
        if not cand or _retro_norm(cand)==_retro_norm(title): continue
        if re.search(r'(?i)\b(rating|click icon|own/stream|watch free)\b',cand): continue
        episode=cand
        break
    return title or None,episode


def _retro_parse_tvtango_markdown(raw: str, network: str) -> list[dict[str,Any]]:
    """Parse the normal unauthenticated Jina Reader Markdown representation.

    Reader's default Markdown mode is intentionally used because HTML mode can
    require authorization.  TVTango rows are handled both as conventional
    one-line Markdown table rows and as line-wrapped rows where rich cell text
    is spread over several physical lines.
    """
    text=(raw or '').replace('\r\n','\n').replace('\r','\n')
    lines=text.split('\n')
    wanted=_retro_norm(network)
    header_times=[];table_start=-1

    # Locate the primetime header.  TVTango normally exposes six half-hour
    # columns, but older/newer dates can contain a different number.
    for i,line in enumerate(lines):
        if '|' not in line and not re.search(r'\b\d{1,2}:\d{2}\s*(?:am|pm)\b',line,re.I):
            continue
        clocks=[]
        for m in re.finditer(r'\b\d{1,2}:\d{2}\s*(?:am|pm)\b',line,re.I):
            minute=_retro_parse_clock(m.group(0))
            if minute is not None: clocks.append(minute)
        if len(clocks)>=2:
            header_times=clocks;table_start=i;break
        if '|' in line:
            cells=[c.strip() for c in line.strip().strip('|').split('|')]
            trial=[_retro_parse_clock(_retro_reader_clean_cell(c)) for c in cells]
            clocks=[x for x in trial if x is not None]
            if len(clocks)>=2:
                header_times=clocks;table_start=i;break
    if table_start<0 or not header_times:
        return []

    def parse_cells(cells:list[str]) -> list[dict[str,Any]]:
        if not cells:return []
        first_prog=None
        # Network label can be "NBC", "Image NBC", a markdown image + NBC,
        # or (after conversion) image and network in separate cells.
        for idx in range(min(3,len(cells))):
            label_norm=_retro_norm(_retro_reader_clean_cell(cells[idx]))
            if label_norm==wanted or re.search(r'(?<![a-z0-9])'+re.escape(wanted)+r'(?![a-z0-9])',label_norm):
                first_prog=idx+1;break
        if first_prog is None:
            combo=' '.join(_retro_reader_clean_cell(c) for c in cells[:2])
            if re.search(r'(?<![a-z0-9])'+re.escape(wanted)+r'(?![a-z0-9])',_retro_norm(combo)):
                first_prog=2
        if first_prog is None:return []
        vals=cells[first_prog:]
        out=[]
        for idx,minute in enumerate(header_times):
            if idx>=len(vals):break
            title,episode=_retro_reader_program_cell(vals[idx])
            if not title:continue
            out.append({'start_minute':minute,'end_minute':min(1440,minute+30),'title':title,'episode_title':episode,'description':None})
        return out

    # First try ordinary one-line Markdown rows.
    for line in lines[table_start+1:]:
        if re.search(r'(?i)Some Shows Airing Outside of Primetime',line):break
        if '|' not in line:continue
        cells=[c.strip() for c in line.strip().strip('|').split('|')]
        parsed=parse_cells(cells)
        if parsed:return parsed

    # Reader may line-wrap rich table cells.  Find the requested network marker,
    # collect the block through the next network row/outside-primetime marker,
    # then split on pipes while preserving embedded newlines within each cell.
    network_line=-1
    for i in range(table_start+1,len(lines)):
        line_clean=_retro_norm(_retro_reader_clean_cell(lines[i]))
        if re.search(r'(?i)some shows airing outside of primetime',lines[i]):break
        if line_clean==wanted or re.search(r'(?<![a-z0-9])'+re.escape(wanted)+r'(?![a-z0-9])',line_clean):
            network_line=i;break
    if network_line>=0:
        block=[]
        known_networks={'abc','cbs','nbc','fox','the cw','cw','upn','the wb','wb','pbs','cbc','ctv','global','citytv'}
        for i in range(network_line,min(len(lines),network_line+120)):
            if i>network_line:
                clean=_retro_norm(_retro_reader_clean_cell(lines[i]))
                if re.search(r'(?i)some shows airing outside of primetime',lines[i]):break
                if clean in known_networks and clean!=wanted:break
            block.append(lines[i])
        joined='\n'.join(block)
        cells=[c.strip() for c in joined.strip().strip('|').split('|')]
        parsed=parse_cells(cells)
        if parsed:return parsed
    return []


def _retro_country_for_network(network: str) -> str:
    n=_retro_norm(network)
    if n in {'cbc','cbc television','ctv','ctv2','global','global television','citytv','city tv','tvo','tvo kids','chch'}:
        return 'CA'
    if n in {'bbc one','bbc1','bbc two','bbc2','itv','channel 4','channel four','channel 5','five'}:
        return 'GB'
    return 'US'


def _retro_fetch_tvmaze(source_date: str, network: str) -> tuple[list[dict[str,Any]],str]:
    """Fallback to TVmaze's public daily schedule JSON API.

    TVmaze is very reliable and requires no API key, but its schedule database is
    based on episode premiere airings rather than a complete rerun-inclusive TV
    Guide.  We therefore use it only after TVTango/Reader fail.
    """
    country=_retro_country_for_network(network)
    url='https://api.tvmaze.com/schedule?'+urlencode({'country':country,'date':source_date})
    req=URLRequest(url,headers={
        'User-Agent':f'{APP_NAME}/{APP_VERSION} RetroTV',
        'Accept':'application/json',
    })
    with urlopen(req,timeout=30) as resp:
        payload=json.loads(resp.read(8*1024*1024).decode('utf-8','replace'))
    if not isinstance(payload,list):
        raise RuntimeError('TVmaze returned an unexpected schedule response')
    wanted=_retro_norm(network)
    found=[]
    for item in payload:
        if not isinstance(item,dict):continue
        show=item.get('show') or ((item.get('_embedded') or {}).get('show') if isinstance(item.get('_embedded'),dict) else None) or {}
        if not isinstance(show,dict):show={}
        net=show.get('network') or {}
        if not isinstance(net,dict):net={}
        netname=str(net.get('name') or '').strip()
        if _retro_norm(netname)!=wanted:
            continue
        airtime=str(item.get('airtime') or '').strip()
        minute=_retro_parse_clock(airtime)
        if minute is None:
            # airstamp is useful for validation but its offset/UTC conversion is
            # not the same thing as the station's historical local wall clock.
            continue
        # Match TVTango's primetime grid rather than importing daytime/late-night
        # premieres into the reconstructed evening channel.
        if minute < 18*60 or minute >= 23*60:
            continue
        runtime=item.get('runtime') or show.get('runtime') or show.get('averageRuntime') or 30
        try:runtime=int(runtime)
        except Exception:runtime=30
        runtime=max(15,min(240,runtime or 30))
        # Historical grids are clock based; snap normal 22/42-minute metadata to
        # their 30/60-minute broadcast slot while preserving unusual long events.
        if runtime<=35:slot=30
        elif runtime<=70:slot=60
        elif runtime<=100:slot=90
        elif runtime<=135:slot=120
        else:slot=int(round(runtime/30.0)*30)
        title=str(show.get('name') or item.get('name') or '').strip()
        if not title:continue
        episode=str(item.get('name') or '').strip() or None
        summary=item.get('summary')
        if isinstance(summary,str):
            summary=re.sub(r'<[^>]+>',' ',summary);summary=re.sub(r'\s+',' ',summary).strip()
        found.append({
            'start_minute':minute,'end_minute':min(1440,minute+slot),
            'title':title,'episode_title':episode,'description':summary or None,
        })
    found.sort(key=lambda x:(x['start_minute'],x['title']))
    # Keep the first programme if a source somehow contains duplicates at the
    # same network/time/title.
    unique=[];seen=set()
    for x in found:
        k=(x['start_minute'],_retro_norm(x['title']))
        if k in seen:continue
        seen.add(k);unique.append(x)
    if not unique:
        raise RuntimeError(f'TVmaze returned no primetime premiere listings for {network} on {source_date}')
    return unique,url


def _retro_fetch_tvtango_reader(source_url: str, network: str) -> tuple[list[dict[str,Any]],str]:
    # Default Reader Markdown is intentionally unauthenticated.  HTML/raw mode
    # now returns 401 on some Reader deployments, which is why v1.1.36 failed.
    reader='https://r.jina.ai/'+source_url
    headers={
        'User-Agent':f'{APP_NAME}/{APP_VERSION} RetroTV',
        'Accept':'text/plain, text/markdown;q=0.9, */*;q=0.5',
        'X-Timeout':'20',
    }
    with urlopen(URLRequest(reader,headers=headers),timeout=35) as resp:
        raw=resp.read(8*1024*1024).decode('utf-8','replace')
    found=_retro_parse_tvtango_markdown(raw,network)
    if not found:
        sample=re.sub(r'\s+',' ',raw)[:300]
        raise RuntimeError('Jina Reader fetched the listing but ViperTV could not parse the requested network row'+(f' (response starts: {sample})' if sample else ''))
    # Reader Markdown cannot preserve HTML colspan reliably.  When TVmaze has a
    # premiere record for one of the programmes, use its historical airtime and
    # runtime to restore exact :00/:30 placement and one-hour spans.  Reruns not
    # present in TVmaze keep the TVTango Markdown positions.
    m=re.search(r'/listings/(\d{4})/(\d{2})/(\d{2})',source_url)
    if m:
        source_date='-'.join(m.groups())
        try:
            maze,_=_retro_fetch_tvmaze(source_date,network)
            by_title={_retro_norm(x['title']):x for x in maze}
            for x in found:
                hint=by_title.get(_retro_norm(x.get('title')))
                if not hint:continue
                x['start_minute']=hint['start_minute'];x['end_minute']=hint['end_minute']
                if not x.get('episode_title') and hint.get('episode_title'):
                    x['episode_title']=hint['episode_title']
            found.sort(key=lambda z:(z['start_minute'],z['title']))
        except Exception:
            pass
    return found,source_url


def _retro_fetch_tvtango(source_date: str, network: str) -> tuple[list[dict[str,Any]],str,str]:
    """Fetch a historical schedule with layered public-source fallbacks.

    1. TVTango direct HTML (best: includes reruns + exact grid spans)
    2. Jina Reader default Markdown for the same public TVTango page
    3. TVmaze public daily schedule API (premiere airings only)
    """
    d=date.fromisoformat(source_date)
    path=f'/listings/{d:%Y/%m/%d}'
    candidates=[
        f'https://www.tvtango.com{path}',
        f'https://mail.tvtango.com{path}',
        f'https://tvtango.com{path}',
    ]
    browser_headers={
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36',
        'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language':'en-CA,en-US;q=0.9,en;q=0.8',
        'Cache-Control':'no-cache','Pragma':'no-cache','Referer':'https://www.tvtango.com/',
        'Upgrade-Insecure-Requests':'1','Sec-Fetch-Dest':'document','Sec-Fetch-Mode':'navigate',
        'Sec-Fetch-Site':'same-origin','Sec-Fetch-User':'?1',
    }
    raw=None;source_url=None;errors=[]
    for url in candidates:
        req=URLRequest(url,headers=browser_headers)
        try:
            with urlopen(req,timeout=25) as resp:
                raw=resp.read().decode('utf-8','replace');source_url=resp.geturl() or url
            if raw and len(raw)>500:break
        except HTTPError as ex:
            errors.append(f'{url}: HTTP {ex.code}')
            if ex.code not in (403,429,503):break
        except URLError as ex: errors.append(f'{url}: {ex.reason}')
        except Exception as ex: errors.append(f'{url}: {ex}')
    if raw:
        found=_retro_parse_tvtango_html(raw,network)
        if found:
            print(f'Retro TV: TVTango direct succeeded for {source_date} {network} ({len(found)} slots)',flush=True)
            return found,source_url or candidates[0],'tvtango'
        errors.append(f'{source_url or candidates[0]}: page fetched but network grid was not parseable')

    detail='; '.join(errors[-4:]) or 'no response body'
    reader_error=None
    try:
        slots,src=_retro_fetch_tvtango_reader(candidates[0],network)
        print(f'Retro TV: direct TVTango unavailable ({detail}); Jina Reader Markdown fallback succeeded for {source_date} {network} ({len(slots)} slots)',flush=True)
        return slots,src,'tvtango-reader'
    except Exception as ex:
        reader_error=str(ex)

    # TVmaze is a public, no-key JSON API.  It does not contain rerun listings,
    # so this is deliberately the final automatic fallback rather than the first.
    try:
        slots,src=_retro_fetch_tvmaze(source_date,network)
        print(f'Retro TV: TVTango/Reader unavailable; TVmaze fallback succeeded for {source_date} {network} ({len(slots)} premiere slots)',flush=True)
        return slots,src,'tvmaze'
    except Exception as tvmaze_ex:
        raise RuntimeError(
            'TVTango blocked/unavailable ('+detail+'). '
            +'Reader fallback failed: '+str(reader_error)+'. '
            +'TVmaze fallback failed: '+str(tvmaze_ex)+'. '
            +'Use the manual importer for a rerun-inclusive scanned/printed listing.'
        )


def _retro_create_schedule(channel_number:str,channel_name:str,source_date:str,network:str,timezone_name:str,slots:list[dict[str,Any]],source_kind:str,source_url:str|None,filler_library_id:int|None,missing_media:str|None) -> int:
    if not slots:raise ValueError('No historical programmes were supplied')
    ZoneInfo(timezone_name)  # validate
    safe_backup_before_change()
    with db() as conn:
        if conn.execute('SELECT 1 FROM channels WHERE number=?',(channel_number,)).fetchone():
            raise ValueError(f'Channel number {channel_number} is already in use')
        cid=conn.execute("INSERT INTO channels(number,name,shuffle,enabled,created_at,stream_profile,stream_mode,video_bitrate,resolution) VALUES(?,?,0,1,?,?,?,?,?)",(channel_number,channel_name,utcnow_iso(),default_new_channel_stream_profile(),'mpegts',VIDEO_BITRATE,'1920x1080')).lastrowid
        sid=conn.execute("INSERT INTO retro_schedules(channel_id,name,source_kind,source_url,source_date,network,timezone,filler_library_id,missing_media,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(cid,f'{network} {source_date}',source_kind,source_url,source_date,network,timezone_name,filler_library_id,missing_media or None,utcnow_iso(),utcnow_iso())).lastrowid
        missing=[]
        for pos,x in enumerate(sorted(slots,key=lambda z:z['start_minute'])):
            match=_retro_match_program(x['title'],x.get('episode_title'),source_date)
            cur=conn.execute("INSERT INTO retro_slots(schedule_id,position,start_minute,end_minute,title,episode_title,description,matched_source,matched_media_id,match_status,match_score) VALUES(?,?,?,?,?,?,?,?,?,?,?)",(sid,pos,int(x['start_minute']),int(x['end_minute']),x['title'],x.get('episode_title'),x.get('description'),match['source'],match['id'],match['status'],match['score']))
            if not match['source']:
                missing.append((cur.lastrowid,x))
        nowiso=utcnow_iso()
        for slot_id,x in missing:
            conn.execute("INSERT OR IGNORE INTO retro_wanted(schedule_id,slot_id,title,episode_title,first_seen,last_seen,resolved) VALUES(?,?,?,?,?,?,0)",(sid,slot_id,x['title'],x.get('episode_title'),nowiso,nowiso))
        conn.commit()
    return int(cid)


def _retro_recheck(schedule_id:int) -> dict[str,int]:
    with db() as conn:
        sch=conn.execute('SELECT * FROM retro_schedules WHERE id=?',(schedule_id,)).fetchone()
        if not sch:raise ValueError('Retro schedule not found')
        slots=[dict(r) for r in conn.execute('SELECT * FROM retro_slots WHERE schedule_id=? ORDER BY position',(schedule_id,))]
    matched=missing=0
    with db() as conn:
        for x in slots:
            match=_retro_match_program(x['title'],x.get('episode_title'),sch['source_date'])
            conn.execute('UPDATE retro_slots SET matched_source=?,matched_media_id=?,match_status=?,match_score=? WHERE id=?',(match['source'],match['id'],match['status'],match['score'],x['id']))
            if match['source']:
                matched+=1;conn.execute('UPDATE retro_wanted SET resolved=1,last_seen=? WHERE schedule_id=? AND slot_id=?',(utcnow_iso(),schedule_id,x['id']))
            else:
                missing+=1;nowiso=utcnow_iso();conn.execute("INSERT INTO retro_wanted(schedule_id,slot_id,title,episode_title,first_seen,last_seen,resolved) VALUES(?,?,?,?,?,?,0) ON CONFLICT(schedule_id,slot_id) DO UPDATE SET last_seen=excluded.last_seen,resolved=0",(schedule_id,x['id'],x['title'],x.get('episode_title'),nowiso,nowiso))
        conn.commit()
    return {'matched':matched,'missing':missing}


def _retro_slot_at(channel_id:int, when:datetime) -> tuple[dict[str,Any],dict[str,Any],float,float] | None:
    cfg=_retro_config_for_channel(channel_id)
    if not cfg:return None
    tz=ZoneInfo(cfg['timezone'])
    local=when.astimezone(tz)
    minute=local.hour*60+local.minute
    second=local.second+local.microsecond/1_000_000
    with db() as conn:
        slots=[dict(r) for r in conn.execute('SELECT * FROM retro_slots WHERE schedule_id=? ORDER BY start_minute,position',(cfg['id'],))]
    for sl in slots:
        if int(sl['start_minute'])<=minute<int(sl['end_minute']):
            elapsed=(minute-int(sl['start_minute']))*60+second
            duration=(int(sl['end_minute'])-int(sl['start_minute']))*60
            return cfg,sl,elapsed,duration
    return None


def _retro_guide_programmes(channel_id:int,start:datetime,end:datetime) -> list[dict[str,Any]]:
    cfg=_retro_config_for_channel(channel_id)
    if not cfg:return []
    tz=ZoneInfo(cfg['timezone'])
    with db() as conn:slots=[dict(r) for r in conn.execute('SELECT * FROM retro_slots WHERE schedule_id=? ORDER BY start_minute,position',(cfg['id'],))]
    out=[]
    d0=start.astimezone(tz).date()-timedelta(days=1);d1=end.astimezone(tz).date()+timedelta(days=1)
    d=d0
    while d<=d1:
        midnight=datetime(d.year,d.month,d.day,tzinfo=tz)
        for sl in slots:
            ps=midnight+timedelta(minutes=int(sl['start_minute']));pe=midnight+timedelta(minutes=int(sl['end_minute']))
            if pe>start.astimezone(tz) and ps<end.astimezone(tz):
                out.append({'start':ps,'stop':pe,'title':sl['title'],'subtitle':sl.get('episode_title'),'missing':not bool(sl.get('matched_source')),'desc':('PROGRAM UNAVAILABLE — Music Videos are airing; ViperTV Wanted list notified' if not sl.get('matched_source') else f"Historical {cfg['network']} listing from {cfg['source_date']} · {sl.get('match_status','matched')}")})
        d+=timedelta(days=1)
    return out


def _retro_xmltv_programmes(channel_id:int,start:datetime,end:datetime) -> list[dict[str,Any]]:
    return _retro_guide_programmes(channel_id,start,end)


def _retro_guide_blocks(channel_id:int,guide_start:datetime,guide_end:datetime,now:datetime,px_per_min:float) -> tuple[list[str],str]:
    blocks=[]
    for pr in _retro_guide_programmes(channel_id,guide_start,guide_end):
        ps=pr['start'].astimezone(guide_start.tzinfo);pe=pr['stop'].astimezone(guide_start.tzinfo)
        vs=max(ps,guide_start);ve=min(pe,guide_end)
        left=max(0.0,(vs-guide_start).total_seconds()/60*px_per_min);width=max(3.0,(ve-vs).total_seconds()/60*px_per_min)
        missing=bool(pr['missing']);cls='movie' if missing else 'tv';is_now=ps<=now<pe
        subtitle=pr.get('subtitle') or ('UNAVAILABLE — Music Videos airing' if missing else f"Historical schedule · {ps.strftime('%H:%M')}")
        tip=f"{pr['title']} — {subtitle} ({ps.strftime('%H:%M')}–{pe.strftime('%H:%M')})"
        blocks.append(f"<div class='epg-program epg-{cls}{' epg-program-now' if is_now else ''}' style='left:{left:.1f}px;width:{width:.1f}px' title='{e(tip)}'><div class='epg-program-title'>{e(pr['title'])}</div><div class='epg-program-sub'>{e(subtitle)}</div><div class='epg-program-time'>{e(ps.strftime('%H:%M')+'–'+pe.strftime('%H:%M'))}</div></div>")
    return blocks,""


def retro_page(msg:str='') -> str:
    with db() as conn:
        schedules=conn.execute("SELECT rs.*,c.number,c.name channel_name,(SELECT COUNT(*) FROM retro_slots s WHERE s.schedule_id=rs.id) slot_count,(SELECT COUNT(*) FROM retro_slots s WHERE s.schedule_id=rs.id AND s.matched_source IS NOT NULL) matched_count,(SELECT COUNT(*) FROM retro_wanted w WHERE w.schedule_id=rs.id AND w.resolved=0) wanted_count FROM retro_schedules rs JOIN channels c ON c.id=rs.channel_id ORDER BY CAST(c.number AS REAL),c.number").fetchall()
        wanted=conn.execute("SELECT w.*,rs.network,rs.source_date,c.number,c.name channel_name FROM retro_wanted w JOIN retro_schedules rs ON rs.id=w.schedule_id JOIN channels c ON c.id=rs.channel_id WHERE w.resolved=0 ORDER BY w.first_seen DESC LIMIT 500").fetchall()
        mv_local=conn.execute("SELECT COUNT(*) n FROM media m JOIN libraries l ON l.id=m.library_id WHERE m.duration>0 AND lower(l.name) LIKE '%music videos%'").fetchone()['n']
        mv_plex=conn.execute("SELECT COUNT(*) n FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id WHERE pm.duration>0 AND pl.enabled=1 AND lower(pl.title) LIKE '%music videos%'").fetchone()['n']
    mv_count=int(mv_local or 0)+int(mv_plex or 0)
    rows=''.join(f"<tr><td>{e(r['number'])}</td><td>{e(r['channel_name'])}</td><td>{e(r['network'])} · {e(r['source_date'])}</td><td>{r['matched_count']}/{r['slot_count']}</td><td><span class='badge {'warn' if r['wanted_count'] else ''}'>{r['wanted_count']} missing</span></td><td><form class='inline' method='post' action='/retro/{r['id']}/recheck'><button class='secondary'>Recheck Library</button></form> <a class='button secondary' href='/guide'>Guide</a></td></tr>" for r in schedules) or "<tr><td colspan='6' class='empty'>No retro channels yet.</td></tr>"
    wants=''.join(f"<tr><td>{e(r['number'])} {e(r['channel_name'])}</td><td>{e(r['title'])}</td><td>{e(r['episode_title'] or '')}</td><td>{e(r['network'])} {e(r['source_date'])}</td><td><form class='inline' method='post' action='/retro/wanted/{r['id']}/resolve'><button class='secondary'>Mark Resolved</button></form></td></tr>" for r in wanted) or "<tr><td colspan='5' class='empty'>Nothing missing. Every historical listing currently has media.</td></tr>"
    body=_page_heading('Retro TV','Recreate real historical TV schedules with exact clock starts. Music Videos automatically fill commercial gaps and unavailable programmes.')
    if msg:body+=f"<div class='msg'>{e(msg)}</div>"
    body+=f"""
<div class='stats'><div class='stat'><div class='stat-label'>Retro channels</div><div class='stat-value'>{len(schedules)}</div></div><div class='stat'><div class='stat-label'>Wanted programmes</div><div class='stat-value'>{len(wanted)}</div></div><div class='stat'><div class='stat-label'>Music Videos available</div><div class='stat-value'>{mv_count:,}</div></div><div class='stat'><div class='stat-label'>Clock discipline</div><div class='stat-value'>:00 / :30</div></div></div>
<div class='card'><h2>Automatic Music Video filler</h2><p>All playable media from local or Plex libraries whose name contains <b>Music Videos</b> is used automatically. Short programmes are followed by Music Videos until the next hard start time. If a historical programme is unavailable, Music Videos fill that entire slot while the missing title remains in <b>Wanted Programs</b>.</p>{"<div class='msg'>Music Video pool ready: "+str(mv_count)+" items.</div>" if mv_count else "<div class='msg warn'>No Music Videos are currently indexed. Retro TV will use its safety slate until a Music Videos library is available.</div>"}</div>
<div class='card'><h2>Find a historical listing online</h2><p class='muted'>ViperTV tries TVTango directly, then Jina Reader's unauthenticated Markdown view, then TVmaze's public no-key historical schedule API. TVmaze is a last resort because it tracks premiere airings rather than rerun-inclusive TV Guide listings. The manual importer remains available for scanned/printed schedules.</p><form method='post' action='/retro/import-web'><div class='grid3'><div><label>Historical date</label><input type='date' name='source_date' required value='1994-09-22'></div><div><label>Network / station</label><input name='network' required value='NBC' placeholder='NBC'></div><div><label>ViperTV channel number</label><input name='channel_number' required value='900'></div></div><div class='grid3'><div><label>Channel name</label><input name='channel_name' required value='Retro NBC 1994'></div><div><label>Schedule timezone</label><input name='timezone_name' value='{e(DEFAULT_TIMEZONE)}'></div><div><label>Filler behavior</label><input value='Automatic Music Videos' disabled></div></div><button>Find Listing & Build Channel</button></form></div>
<div class='card'><h2>Manual historical listing</h2><p class='muted'>One programme per line: <code>HH:MM|Show title|Episode title</code>. The next programme time defines the exact slot boundary. This is also useful for scanned TV Guide/Newspaper listings you transcribe.</p><form method='post' action='/retro/import-manual'><div class='grid3'><div><label>Historical date</label><input type='date' name='source_date' required value='1994-09-22'></div><div><label>Network / station</label><input name='network' required value='NBC'></div><div><label>ViperTV channel number</label><input name='channel_number' required value='901'></div></div><div class='grid3'><div><label>Channel name</label><input name='channel_name' required value='Retro TV'></div><div><label>Schedule timezone</label><input name='timezone_name' value='{e(DEFAULT_TIMEZONE)}'></div><div><label>Filler behavior</label><input value='Automatic Music Videos' disabled></div></div><label>Listings</label><textarea name='listing_text' rows='10' required placeholder='18:00|News
18:30|Frasier|The Matchmaker
19:00|Friends|The One with...'></textarea><button>Build Retro Channel</button></form></div>
<div class='card'><h2>Retro Channels</h2><div class='table-wrap'><table><thead><tr><th>Ch</th><th>Name</th><th>Source day</th><th>Matched</th><th>Wanted</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Wanted Programs</h2><p class='muted'>A missing historical programme stays here even though viewers receive Music Videos during its scheduled slot. Add the missing programme to Plex/local media, sync the library, then click Recheck Library so the real programme can play the next time that slot comes around.</p><div class='table-wrap'><table><thead><tr><th>Channel</th><th>Program</th><th>Episode</th><th>Historical listing</th><th></th></tr></thead><tbody>{wants}</tbody></table></div></div>
<div class='card'><h2>Broadcast timing</h2><p>Historical start times remain hard boundaries. A 22-minute sitcom in a 30-minute slot plays for 22 minutes, then Music Videos fill the remaining ~8 minutes. A missing 30-minute show is replaced by Music Videos for that full 30-minute slot. Any Music Video reaching the next scheduled start is cut cleanly so the historical programme begins exactly on time.</p></div>"""
    return page_shell('Retro TV',body)


@app.get('/retro',response_class=HTMLResponse)
def retro_index(msg:str=''):
    return retro_page(msg)


@app.post('/retro/import-manual')
def retro_import_manual(source_date:str=Form(...),network:str=Form(...),channel_number:str=Form(...),channel_name:str=Form(...),timezone_name:str=Form(DEFAULT_TIMEZONE),listing_text:str=Form(...),filler_library_id:str=Form(''),missing_media:str=Form('')):
    try:
        slots=_retro_manual_lines(listing_text)
        cid=_retro_create_schedule(channel_number.strip(),channel_name.strip(),source_date,network.strip(),timezone_name.strip(),slots,'manual',None,None,None)
        return RedirectResponse('/retro?msg='+quote(f'Retro channel {channel_number} created with {len(slots)} historical slots.'),303)
    except Exception as ex:
        return RedirectResponse('/retro?msg='+quote('Import failed: '+str(ex)),303)


@app.post('/retro/import-web')
def retro_import_web(source_date:str=Form(...),network:str=Form(...),channel_number:str=Form(...),channel_name:str=Form(...),timezone_name:str=Form(DEFAULT_TIMEZONE),filler_library_id:str=Form(''),missing_media:str=Form('')):
    try:
        slots,url,source_kind=_retro_fetch_tvtango(source_date,network.strip())
        _retro_create_schedule(channel_number.strip(),channel_name.strip(),source_date,network.strip(),timezone_name.strip(),slots,source_kind,url,None,None)
        label={'tvtango':'TVTango','tvtango-reader':'TVTango via Reader','tvmaze':'TVmaze fallback'}.get(source_kind,source_kind)
        return RedirectResponse('/retro?msg='+quote(f'Found {len(slots)} {network} listings via {label} and built channel {channel_number}.'),303)
    except Exception as ex:
        return RedirectResponse('/retro?msg='+quote('Historical lookup failed: '+str(ex)),303)


@app.post('/retro/{schedule_id}/recheck')
def retro_recheck(schedule_id:int):
    try:
        r=_retro_recheck(schedule_id);msg=f"Library rechecked: {r['matched']} matched, {r['missing']} still unavailable."
    except Exception as ex:msg=str(ex)
    return RedirectResponse('/retro?msg='+quote(msg),303)


@app.post('/retro/wanted/{wanted_id}/resolve')
def retro_wanted_resolve(wanted_id:int):
    with db() as conn:
        conn.execute('UPDATE retro_wanted SET resolved=1,last_seen=? WHERE id=?',(utcnow_iso(),wanted_id));conn.commit()
    return RedirectResponse('/retro?msg=Marked+resolved',303)


def _retro_limit_command(cmd:list[str],seconds:float)->list[str]:
    out=list(cmd)
    try:i=len(out)-1-out[::-1].index('pipe:1')
    except ValueError:i=len(out)
    out[i:i]=['-t',f'{max(0.1,float(seconds)):.3f}']
    return out


def _retro_slate_command(channel:sqlite3.Row,title:str,seconds:float)->list[str]:
    # drawtext uses DejaVu installed in the container. Keep the slate intentionally
    # simple so it is reliable even on the older Ivy Bridge server.
    safe=re.sub(r"[:'\\]",lambda m:'\\'+m.group(0),str(title))[:70]
    text=f"COMING SOON\\nPROGRAM UNAVAILABLE\\n{safe}"
    return ['ffmpeg','-hide_banner','-loglevel','error','-re','-f','lavfi','-i','color=c=#252525:s=1280x720:r=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-vf',f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='{text}':fontcolor=white:fontsize=40:line_spacing=16:x=(w-text_w)/2:y=(h-text_h)/2",'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','veryfast','-tune','zerolatency','-pix_fmt','yuv420p','-c:a','aac','-b:a',AUDIO_BITRATE,'-t',f'{max(0.1,seconds):.3f}','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']


async def _retro_run_cmd_to_subscribers(channel_id:int,state:dict[str,Any],cmd:list[str],label:str)->float:
    cmd=_low_latency_station_command(cmd);cmd=_station_timestamp_command(cmd,float(state.get('timeline_seconds') or 0.0))
    start=time.monotonic();proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE);state['proc']=proc;state['source_item']=label
    assert proc.stdout is not None
    while not state.get('stop'):
        chunk=await proc.stdout.read(64*1024)
        if not chunk:break
        for q in list(state['subscribers']):
            try:q.put_nowait(chunk)
            except asyncio.QueueFull:
                state['subscribers'].discard(q)
                try:q.put_nowait(None)
                except Exception:pass
        if not state['subscribers']:
            empty_since=state.get('empty_since') or time.time();state['empty_since']=empty_since
            if time.time()-float(empty_since)>=SHARED_CHANNEL_GRACE_SECONDS:state['stop']=True;break
        else:state['empty_since']=None
    if proc.returncode is None:
        try:proc.terminate()
        except Exception:pass
    try:await asyncio.wait_for(proc.wait(),timeout=3)
    except asyncio.TimeoutError:
        proc.kill();await proc.wait()
    elapsed=max(0.0,time.monotonic()-start);state['timeline_seconds']=float(state.get('timeline_seconds') or 0)+elapsed;state['proc']=None
    if proc.returncode not in (0,255,-15) and not state.get('stop'):
        try:
            err=(await proc.stderr.read()).decode(errors='ignore')[-1000:]
            state['error']=err
        except Exception:pass
    return elapsed


async def _retro_shared_channel_producer(channel_id:int,state:dict[str,Any]) -> None:
    cfg=_retro_config_for_channel(channel_id)
    if not cfg:return
    with db() as conn:channel=conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone()
    if not channel:return
    fillers=_retro_music_video_items()
    filler_cursor=0
    state['started_at']=time.time();state['timeline_seconds']=0.0;state['retro']=True;state['error']=''
    label=_shared_stream_label(channel_id);print(f'retro channel producer started: channel={label}',flush=True)
    try:
        while not state.get('stop'):
            found=_retro_slot_at(channel_id,datetime.now(timezone.utc))
            if not found:
                # Outside imported grid: a neutral slate until the next minute check.
                await _retro_run_cmd_to_subscribers(channel_id,state,_retro_slate_command(channel,'Retro programming resumes soon',15),'Retro standby')
                continue
            cfg,slot,slot_elapsed,slot_duration=found
            remaining=max(0.2,slot_duration-slot_elapsed)
            item=None
            if slot.get('matched_source') and slot.get('matched_media_id'):
                item=_retro_resolve_media(slot['matched_source'],int(slot['matched_media_id']))
            if item and slot_elapsed<float(item.get('duration') or 0):
                media_offset=slot_elapsed;run_for=min(remaining,max(0.2,float(item['duration'])-media_offset))
                try:
                    if item['source_type']=='plex':
                        url,headers=await asyncio.to_thread(_plex_direct_part_source,item);cmd=_profiled_plex_part_command(channel,item,media_offset,url,headers);state['source_mode']='retro-plex'
                    else:
                        cmd=_profiled_local_command(channel,item,media_offset);state['source_mode']='retro-local'
                    cmd=_retro_limit_command(cmd,run_for)
                    await _retro_run_cmd_to_subscribers(channel_id,state,cmd,str(slot['title']))
                except Exception as ex:
                    state['error']=str(ex);await asyncio.sleep(1)
                continue
            # The programme has ended before the hard slot boundary, or the
            # historical programme is unavailable. In both cases Music Videos
            # are the automatic filler pool. The EPG/Wanted list continues to
            # show the historical programme, but viewers receive music videos
            # until the exact next schedule boundary.
            if fillers:
                fill=fillers[filler_cursor%len(fillers)];filler_cursor+=1
                run_for=min(remaining,max(1.0,float(fill.get('duration') or remaining)))
                try:
                    if fill['source_type']=='plex':
                        url,headers=await asyncio.to_thread(_plex_direct_part_source,fill)
                        cmd=_profiled_plex_part_command(channel,fill,0.0,url,headers)
                    else:
                        cmd=_profiled_local_command(channel,fill,0.0)
                    cmd=_retro_limit_command(cmd,run_for)
                    state['source_mode']='retro-music-video-missing' if not item else 'retro-music-video-filler'
                    filler_label=('Missing '+str(slot['title'])+' — Music Video: ' if not item else 'Music Video filler: ')+str(fill.get('title') or 'Music Video')
                    await _retro_run_cmd_to_subscribers(channel_id,state,cmd,filler_label)
                except Exception as ex:
                    state['error']=str(ex);await asyncio.sleep(0.25)
                continue
            # Safety fallback only when the server has no indexed Music Videos.
            slate_title=(str(slot['title'])+' unavailable — add a Music Videos library') if not item else 'Add a Music Videos library for Retro TV filler'
            state['source_mode']='retro-no-music-videos'
            await _retro_run_cmd_to_subscribers(channel_id,state,_retro_slate_command(channel,slate_title,remaining),'Retro safety slate')
    except asyncio.CancelledError:raise
    except Exception as ex:
        state['error']=str(ex);print(f'retro producer error channel={label}: {ex}',flush=True)
    finally:
        proc=state.get('proc')
        if proc and proc.returncode is None:
            try:proc.kill();await proc.wait()
            except Exception:pass
        state['proc']=None;state['running']=False
        for q in list(state.get('subscribers',set())):
            try:q.put_nowait(None)
            except Exception:pass
        if SHARED_CHANNEL_STREAMS.get(channel_id) is state:SHARED_CHANNEL_STREAMS.pop(channel_id,None)
        print(f'retro channel producer stopped: channel={label}',flush=True)



def local_ffmpeg_command(path: str, offset: float) -> list[str]:
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-re", "-ss", f"{max(offset, 0):.3f}", "-i", path,
        "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
        "-c:v", "libx264", "-preset", TRANSCODE_PRESET,
        "-pix_fmt", "yuv420p", "-b:v", VIDEO_BITRATE,
        "-maxrate", VIDEO_BITRATE, "-bufsize", "10000k",
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000",
        "-mpegts_flags", "+resend_headers+initial_discontinuity", "-f", "mpegts", "pipe:1",
    ]


def plex_ffmpeg_command(item: dict[str, Any], offset: float) -> list[str]:
    # Plex does the video work (direct-stream or transcode to HLS); ViperTV only repackages the HLS output to MPEG-TS.
    url = plex_transcode_url(item, offset)
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-re", "-i", url,
        "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
        "-c", "copy", "-mpegts_flags", "+resend_headers+initial_discontinuity", "-f", "mpegts", "pipe:1",
    ]


async def stream_channel(channel_id: int):
    _, items = channel_media(channel_id)
    idx, offset, _ = locate_at(items, datetime.now(timezone.utc))
    current_idx = idx
    first_offset = offset
    proc: asyncio.subprocess.Process | None = None
    try:
        while True:
            item = items[current_idx]
            if item["source_type"] == "plex":
                cmd = plex_ffmpeg_command(item, first_offset)
            else:
                cmd = local_ffmpeg_command(str(item["path"]), first_offset)
            first_offset = 0.0
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(32 * 1024)
                if not chunk:
                    break
                yield chunk
            await proc.wait()
            if proc.returncode not in (0, 255):
                try:
                    err = await proc.stderr.read() if proc.stderr else b""
                    # Never print the Plex URL/token. Only the end of ffmpeg's error text.
                    text = err.decode(errors="ignore")[-2000:]
                    text = re.sub(r"X-Plex-Token=[^&\s]+", "X-Plex-Token=REDACTED", text)
                    print(f"ffmpeg channel {channel_id}: {text}", flush=True)
                except Exception:
                    pass
            proc = None
            current_idx = (current_idx + 1) % len(items)
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            try:
                await proc.wait()
            except Exception:
                pass


def stream_response_for_channel(channel_id: int):
    _, items = channel_media(channel_id)
    if not items:
        raise HTTPException(503, "Channel has no playable media. Sync Plex or scan local media and select shows/seasons first.")
    return StreamingResponse(
        stream_channel(channel_id),
        media_type="video/mp2t",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@app.api_route("/stream/{channel_ref}.ts", methods=["GET", "HEAD"])
async def stream_ts_legacy(channel_ref: int, request: Request):
    channel_id = resolve_channel_ref(channel_ref)
    # Kodi probes IPTV streams with HEAD before GET. Return a cheap successful
    # probe without starting FFmpeg.
    if request.method == "HEAD":
        _, items = channel_media(channel_id)
        if not items:
            raise HTTPException(503, "Channel has no playable media")
        return PlainTextResponse("", media_type="video/mp2t", headers={"Cache-Control": "no-store"})
    return stream_response_for_channel(channel_id)


@app.api_route("/stream/channel/{channel_number}.ts", methods=["GET", "HEAD"])
async def stream_ts_by_number(channel_number: str, request: Request):
    channel_id = resolve_channel_number(channel_number)
    if request.method == "HEAD":
        _, items = channel_media(channel_id)
        if not items:
            raise HTTPException(503, "Channel has no playable media")
        return PlainTextResponse("", media_type="video/mp2t", headers={"Cache-Control": "no-store"})
    return stream_response_for_channel(channel_id)


# -------------------------- Built-in browser preview -------------------------
# Browser preview uses a real HLS segment buffer. Kodi/IPTV clients continue to
# use the existing continuous MPEG-TS endpoints and are not affected.
BROWSER_HLS_ROOT = Path(os.getenv("VIPERTV_BROWSER_HLS_DIR", "/tmp/vipertv-browser-hls"))
BROWSER_HLS_PROCESSES: dict[int, dict[str, Any]] = {}
BROWSER_HLS_IDLE_SECONDS = int(os.getenv("VIPERTV_BROWSER_HLS_IDLE_SECONDS", "600"))


def _preview_item_label(item: dict[str, Any]) -> tuple[str, str]:
    if item.get("show_title"):
        title = str(item.get("show_title") or "Untitled")
        subtitle = str(item.get("episode_title") or item.get("title") or "")
        if item.get("season_number") is not None and item.get("episode_number") is not None:
            code = f"S{int(item['season_number']):02d}E{int(item['episode_number']):02d}"
            subtitle = f"{code} · {subtitle}" if subtitle else code
        return title, subtitle
    return str(item.get("title") or "Untitled"), ""


def _browser_hls_dir(channel_id: int) -> Path:
    return BROWSER_HLS_ROOT / str(channel_id)


def _stop_browser_hls(channel_id: int, remove_files: bool = False) -> None:
    state = BROWSER_HLS_PROCESSES.pop(channel_id, None)
    if state:
        proc = state.get("proc")
        log_handle = state.get("log_handle")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            if log_handle:
                log_handle.close()
        except Exception:
            pass
    if remove_files:
        try:
            shutil.rmtree(_browser_hls_dir(channel_id), ignore_errors=True)
        except Exception:
            pass


def _browser_hls_command(channel: sqlite3.Row, item: dict[str, Any], offset: float, out_dir: Path) -> list[str]:
    """Build a finite HLS stream for the program that is live right now.

    Each preview session starts at the channel's wall-clock position. When the
    current program ends the browser reloads/restarts the preview at the next
    program. This keeps the channel clock accurate and avoids the fragile
    endless fragmented-MP4 response used by v1.1.19.
    """
    manifest = str(out_dir / "index.m3u8")
    segment_pattern = str(out_dir / "seg_%06d.ts")
    hls_out = [
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "10",
        "-hls_delete_threshold", "5",
        "-hls_flags", "delete_segments+independent_segments+program_date_time",
        "-hls_segment_filename", segment_pattern,
        manifest,
    ]

    if item.get("source_type") == "plex":
        url = plex_transcode_url(item, offset)
        # Ask Plex for browser-friendly H.264/AAC. The second ffmpeg process is
        # only the HLS segmenter, so no additional video encode is normally
        # needed for Plex-backed channels.
        sep = "&" if "?" in url else "?"
        if "videoCodec=" not in url:
            url += sep + "videoCodec=h264&audioCodec=aac"
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re", "-i", url,
            "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
            "-c:v", "copy", "-c:a", "copy",
            *hls_out,
        ]

    path = str(item.get("path") or channel["offline_media"] or "")
    if not path:
        return ["false"]
    return [
        "ffmpeg", "-hide_banner", "-loglevel", "warning", "-re",
        "-ss", f"{max(offset, 0):.3f}", "-i", path,
        "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn",
        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-b:v", "3000k", "-maxrate", "3500k", "-bufsize", "7000k",
        "-force_key_frames", "expr:gte(t,n_forced*2)",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
        *hls_out,
    ]


def _start_browser_hls(channel_id: int, force: bool = False) -> dict[str, Any]:
    retro_cfg = _retro_config_for_channel(channel_id)
    if retro_cfg:
        with db() as conn:
            channel = conn.execute('SELECT * FROM channels WHERE id=? AND enabled=1',(channel_id,)).fetchone()
        if not channel:
            raise HTTPException(404,'Channel not found')
        found=_retro_slot_at(channel_id,datetime.now(timezone.utc))
        if found:
            _,sl,elapsed,_=found
            item={'title':sl['title'],'show_title':sl['title'],'episode_title':sl.get('episode_title') or ('PROGRAM UNAVAILABLE' if not sl.get('matched_source') else ''),'duration':max(60,(int(sl['end_minute'])-int(sl['start_minute']))*60),'source_type':'retro'}
            offset=elapsed
        else:
            item={'title':'Retro programming resumes soon','duration':3600,'source_type':'retro'};offset=0.0
        items=[item];started=datetime.now(timezone.utc)-timedelta(seconds=float(offset))
    else:
        channel, items = channel_media(channel_id)
        if not items:
            raise HTTPException(503, "Channel has no playable media")
        idx, offset, started = locate_at(items, datetime.now(timezone.utc))
        item = items[idx]

    existing = BROWSER_HLS_PROCESSES.get(channel_id)
    if existing and not force:
        proc = existing.get("proc")
        if proc is not None and proc.poll() is None:
            existing["last_access"] = time.time()
            return existing

    _stop_browser_hls(channel_id, remove_files=True)
    out_dir = _browser_hls_dir(channel_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not retro_cfg:
        idx, offset, started = locate_at(items, datetime.now(timezone.utc))
        item = items[idx]
    else:
        idx = 0
    cmd = _browser_hls_command(channel, item, offset, out_dir)
    log_path = out_dir / "ffmpeg.log"
    log_handle = open(log_path, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=log_handle,
            start_new_session=True,
        )
    except Exception:
        log_handle.close()
        raise

    title, subtitle = _preview_item_label(item)
    state = {
        "proc": proc,
        "log_handle": log_handle,
        "started_at": time.time(),
        "last_access": time.time(),
        "item_index": idx,
        "title": title,
        "subtitle": subtitle,
        "channel_number": str(channel["number"]),
        "program_started": started.isoformat(),
    }
    BROWSER_HLS_PROCESSES[channel_id] = state
    print(f"browser HLS preview started: channel={channel['number']} pid={proc.pid} item={title!r}", flush=True)
    return state


def _browser_hls_log_tail(channel_id: int, chars: int = 1800) -> str:
    path = _browser_hls_dir(channel_id) / "ffmpeg.log"
    try:
        text = path.read_text(errors="ignore")[-chars:]
        return re.sub(r"X-Plex-Token=[^&\s]+", "X-Plex-Token=REDACTED", text)
    except Exception:
        return ""


async def browser_hls_cleanup_loop() -> None:
    while True:
        try:
            await asyncio.sleep(60)
            _cleanup_browser_hls_previews()
            _cleanup_pluto_hls_previews()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"browser HLS cleanup error: {exc}", flush=True)


def _cleanup_browser_hls_previews() -> None:
    now = time.time()
    for channel_id, state in list(BROWSER_HLS_PROCESSES.items()):
        proc = state.get("proc")
        idle = now - float(state.get("last_access") or now)
        # Finished program playlists are kept briefly so HLS.js can consume the
        # ENDLIST and trigger a page reload. Truly idle players are removed.
        if idle > BROWSER_HLS_IDLE_SECONDS:
            _stop_browser_hls(channel_id, remove_files=True)
        elif proc is not None and proc.poll() is not None:
            try:
                if state.get("log_handle"):
                    state["log_handle"].close()
                    state["log_handle"] = None
            except Exception:
                pass


@app.get("/preview/hls/channel/{channel_number}/index.m3u8")
async def browser_hls_manifest(channel_number: str):
    channel_id = resolve_channel_number(channel_number)
    state = _start_browser_hls(channel_id)
    state["last_access"] = time.time()
    manifest = _browser_hls_dir(channel_id) / "index.m3u8"

    # Give ffmpeg time to write the first couple of segments. Returning an
    # empty/half-written playlist is what caused the old preview to stutter.
    deadline = time.time() + 30.0
    while time.time() < deadline:
        if manifest.exists() and manifest.stat().st_size > 60:
            try:
                text = manifest.read_text(errors="ignore")
                durations = [float(x) for x in re.findall(r"#EXTINF:([0-9.]+)", text)]
                buffered = sum(durations)
                proc = state.get("proc")
                # Low-latency live TV starts once roughly two seconds are ready.
                # The retained HLS window is much larger than this, so brief client
                # jitter still has room to recover without adding startup lag.
                if buffered >= 2.0 or (durations and proc is not None and proc.poll() is not None):
                    return PlainTextResponse(
                        text,
                        media_type="application/vnd.apple.mpegurl",
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "X-Accel-Buffering": "no"},
                    )
            except Exception:
                pass
        proc = state.get("proc")
        if proc is not None and proc.poll() is not None:
            tail = _browser_hls_log_tail(channel_id)
            print(f"browser HLS preview failed early channel {channel_id}: {tail}", flush=True)
            raise HTTPException(503, "Browser preview encoder stopped before producing HLS")
        await asyncio.sleep(0.15)
    raise HTTPException(503, "Browser preview is still starting; retry shortly")


@app.get("/preview/hls/channel/{channel_number}/{segment_name}")
def browser_hls_segment(channel_number: str, segment_name: str):
    channel_id = resolve_channel_number(channel_number)
    if not re.fullmatch(r"seg_\d+\.ts", segment_name):
        raise HTTPException(404, "Segment not found")
    state = BROWSER_HLS_PROCESSES.get(channel_id)
    if state:
        state["last_access"] = time.time()
    path = _browser_hls_dir(channel_id) / segment_name
    # HLS.js can request the next segment a fraction of a second before FFmpeg
    # atomically renames its .tmp file.  Give that normal race a short grace
    # period instead of returning an immediate 404 and triggering reconnects.
    deadline = time.time() + 2.0
    while not path.exists() and time.time() < deadline:
        time.sleep(0.05)
    if not path.exists():
        raise HTTPException(404, "Segment expired or not ready")
    return FileResponse(path, media_type="video/mp2t", headers={"Cache-Control": "private, max-age=30"})


@app.post("/preview/hls/channel/{channel_number}/restart")
def browser_hls_restart(channel_number: str):
    channel_id = resolve_channel_number(channel_number)
    state = _start_browser_hls(channel_id, force=True)
    return JSONResponse({"ok": True, "title": state.get("title"), "subtitle": state.get("subtitle")})


@app.get("/api/preview/hls/channel/{channel_number}/status")
def browser_hls_status(channel_number: str):
    channel_id = resolve_channel_number(channel_number)
    state = BROWSER_HLS_PROCESSES.get(channel_id)
    if not state:
        return JSONResponse({"running": False, "ready": False})
    state["last_access"] = time.time()
    proc = state.get("proc")
    manifest = _browser_hls_dir(channel_id) / "index.m3u8"
    ready = manifest.exists() and manifest.stat().st_size > 60
    return JSONResponse({
        "running": proc is not None and proc.poll() is None,
        "ready": ready,
        "title": state.get("title"),
        "subtitle": state.get("subtitle"),
        "error": _browser_hls_log_tail(channel_id, 600) if proc is not None and proc.poll() not in (None, 0) else "",
    })


@app.get("/assets/hls.min.js")
def browser_hls_js_asset():
    asset = Path(__file__).with_name("hls.min.js")
    if asset.exists():
        return FileResponse(asset, media_type="application/javascript", headers={"Cache-Control": "public, max-age=86400"})
    # Development-source fallback; packaged Docker images vendor this file at build time.
    return RedirectResponse("https://cdn.jsdelivr.net/npm/hls.js@1.7.3/dist/hls.min.js", status_code=307)


@app.get("/watch/channel/{channel_number}", response_class=HTMLResponse)
def browser_watch_page(channel_number: str, request: Request):
    channel_id = resolve_channel_number(channel_number)
    retro_cfg=_retro_config_for_channel(channel_id)
    if retro_cfg:
        with db() as conn:channel=conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone()
        found=_retro_slot_at(channel_id,datetime.now(timezone.utc))
        if found:
            _,sl,elapsed,dur=found
            current={'title':sl['title'],'show_title':sl['title'],'episode_title':sl.get('episode_title') or ('PROGRAM UNAVAILABLE' if not sl.get('matched_source') else ''),'duration':dur}
            remaining=max(0,int(dur-elapsed))
            with db() as conn:
                nxtrow=conn.execute('SELECT * FROM retro_slots WHERE schedule_id=? AND start_minute>=? ORDER BY start_minute LIMIT 1',(retro_cfg['id'],int(sl['end_minute']))).fetchone()
                if not nxtrow:nxtrow=conn.execute('SELECT * FROM retro_slots WHERE schedule_id=? ORDER BY start_minute LIMIT 1',(retro_cfg['id'],)).fetchone()
            nxt={'title':nxtrow['title'],'show_title':nxtrow['title'],'episode_title':nxtrow['episode_title'] or ''} if nxtrow else {'title':'Retro TV'}
        else:
            current={'title':'Retro programming resumes soon','duration':3600};nxt={'title':'Next historical programme'};remaining=0
        items=[current,nxt]
    else:
        channel, items = channel_media(channel_id)
        if not items:
            body = _page_heading(
                f"{channel['number']} {channel['name']}",
                "Built-in channel preview",
                "<a class='button secondary' href='/channels'>Back to Channels</a>",
            ) + "<div class='card'><h2>Nothing to play</h2><p>This channel currently has no playable media.</p></div>"
            return page_shell("Watch Channel", body)

    # Start segment generation before returning the page so the player has a
    # useful buffer by the time hls.js requests the manifest.
    _cleanup_browser_hls_previews()
    _start_browser_hls(channel_id)

    if not retro_cfg:
        idx, offset, started = locate_at(items, datetime.now(timezone.utc))
        current = items[idx]
        nxt = items[(idx + 1) % len(items)]
        remaining = max(0, int(float(current.get("duration") or 0) - float(offset)))
    title, subtitle = _preview_item_label(current)
    next_title, next_subtitle = _preview_item_label(nxt)
    mins, secs = divmod(remaining, 60)
    hls_path = f"/preview/hls/channel/{quote(str(channel['number']), safe='')}/index.m3u8"
    restart_path = f"/preview/hls/channel/{quote(str(channel['number']), safe='')}/restart"
    raw_path = f"/stream/channel/{quote(str(channel['number']), safe='')}.ts"
    actions = "<a class='button secondary' href='/channels'>Back to Channels</a> " + f"<a class='button secondary' href='{raw_path}'>Raw MPEG-TS</a>"
    body = _page_heading(
        f"{channel['number']} {channel['name']}",
        "Live HLS browser preview — Kodi and IPTV clients continue using the normal MPEG-TS feed.",
        actions,
    ) + f"""
<div class='card' style='max-width:1100px;margin:auto'>
  <div style='background:#05070a;border-radius:8px;overflow:hidden;aspect-ratio:16/9;display:flex;align-items:center;justify-content:center'>
    <video id='channel-preview' controls autoplay playsinline style='width:100%;height:100%;background:#000'></video>
  </div>
  <div class='grid' style='margin-top:16px'>
    <div><div class='muted small'>NOW PLAYING</div><h2 style='margin:4px 0'>{e(title)}</h2><div>{e(subtitle)}</div><div class='muted small' style='margin-top:8px'>About {mins}m {secs:02d}s remaining</div></div>
    <div><div class='muted small'>UP NEXT</div><h3 style='margin:4px 0'>{e(next_title)}</h3><div>{e(next_subtitle)}</div></div>
  </div>
  <div id='preview-status' class='muted small' style='margin-top:12px'>Building live HLS buffer…</div>
</div>
<script src='/assets/hls.min.js'></script>
<script>
(() => {{
  const video = document.getElementById('channel-preview');
  const status = document.getElementById('preview-status');
  const manifest = {json.dumps(hls_path)};
  let hls = null;
  let restarting = false;

  function setStatus(s) {{ status.textContent = s; }}
  function playVideo() {{
    const p = video.play();
    if (p && p.catch) p.catch(() => setStatus('Ready — press Play if your browser blocked autoplay.'));
  }}
  function destroyPlayer() {{
    if (hls) {{ try {{ hls.destroy(); }} catch (_) {{}} hls = null; }}
    video.pause();
    video.removeAttribute('src');
    video.load();
  }}
  function attach() {{
    const src = manifest + '?v=' + Date.now();
    if (video.canPlayType('application/vnd.apple.mpegurl')) {{
      video.src = src;
      video.addEventListener('loadedmetadata', playVideo, {{once:true}});
      return;
    }}
    if (window.Hls && Hls.isSupported()) {{
      hls = new Hls({{
        lowLatencyMode: false,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 4,
        maxBufferLength: 8,
        maxMaxBufferLength: 12,
        backBufferLength: 6,
        maxBufferHole: 0.5,
        manifestLoadingTimeOut: 20000,
        fragLoadingTimeOut: 20000,
      }});
      hls.loadSource(src);
      hls.attachMedia(video);
      hls.on(Hls.Events.MANIFEST_PARSED, () => {{ setStatus('LIVE'); playVideo(); }});
      hls.on(Hls.Events.ERROR, async (_event, data) => {{
        if (!data.fatal) return;
        if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {{
          setStatus('Recovering media stream…');
          try {{ hls.recoverMediaError(); }} catch (_) {{ await restartPreview('Recovering preview…'); }}
          return;
        }}
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {{
          setStatus('Waiting for next HLS segment…');
          try {{ hls.startLoad(); }} catch (_) {{ await restartPreview('Reconnecting preview…'); }}
          return;
        }}
        await restartPreview('Restarting preview…');
      }});
      return;
    }}
    setStatus('This browser does not support HLS playback. Use a current Chrome, Edge, Firefox or Safari browser.');
  }}
  async function restartPreview(message) {{
    if (restarting) return;
    restarting = true;
    setStatus(message || 'Reconnecting preview…');
    // Rebuild only the browser-side HLS session.  The manifest endpoint will
    // restart the backend segmenter itself if (and only if) it has actually
    // stopped.  Never tear down a healthy live station because one fragment
    // request was late.
    destroyPlayer();
    setTimeout(() => {{ restarting = false; attach(); }}, 1500);
  }}

  video.addEventListener('playing', () => setStatus('LIVE'));
  video.addEventListener('waiting', () => setStatus('Buffering HLS…'));
  video.addEventListener('ended', () => {{ window.location.reload(); }});
  video.addEventListener('error', () => restartPreview('Preview interrupted — reconnecting…'));
  window.addEventListener('beforeunload', destroyPlayer);
  attach();
}})();
</script>
"""
    return page_shell("Watch Channel", body)


# =========================== ViperTV 1.0 Studio =============================
# This section intentionally keeps all advanced state in SQLite under /data.
# Containers remain disposable; all features below survive rebuilds.

def init_v1_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS collections(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,kind TEXT NOT NULL DEFAULT 'manual',
          rule_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS collection_selections(
          id INTEGER PRIMARY KEY AUTOINCREMENT,collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
          token TEXT NOT NULL,UNIQUE(collection_id,token));
        CREATE TABLE IF NOT EXISTS multi_collection_members(
          id INTEGER PRIMARY KEY AUTOINCREMENT,collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
          member_collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,UNIQUE(collection_id,member_collection_id));
        CREATE TABLE IF NOT EXISTS playlists(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS playlist_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
          position INTEGER NOT NULL DEFAULT 0,token TEXT NOT NULL,playback_order TEXT NOT NULL DEFAULT 'season_episode',
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_playlist_items_order ON playlist_items(playlist_id,position,id);
        CREATE TABLE IF NOT EXISTS channel_collections(
          channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
          PRIMARY KEY(channel_id,collection_id));
        CREATE TABLE IF NOT EXISTS schedules(
          id INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          name TEXT NOT NULL DEFAULT 'Schedule',enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS schedule_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
          day_mask INTEGER NOT NULL DEFAULT 127,start_minute INTEGER NOT NULL,end_minute INTEGER NOT NULL,
          source_type TEXT NOT NULL,source_id INTEGER,mode TEXT NOT NULL DEFAULT 'sequential',play_count INTEGER NOT NULL DEFAULT 1,
          pad_to_minutes INTEGER NOT NULL DEFAULT 0,position INTEGER NOT NULL DEFAULT 0,label TEXT);
        CREATE TABLE IF NOT EXISTS schedule_templates(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,items_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL);

        -- v1.1.46: reusable ErsatzTV-style Classic Schedules and per-channel Playouts.
        -- These live beside the older channel-bound time-block scheduler so upgrades are
        -- non-destructive. New playouts take precedence; legacy blocks remain available.
        CREATE TABLE IF NOT EXISTS classic_schedules(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          keep_multi_part INTEGER NOT NULL DEFAULT 1,
          treat_collections_as_shows INTEGER NOT NULL DEFAULT 0,
          shuffle_schedule_items INTEGER NOT NULL DEFAULT 0,
          random_start_point INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS classic_schedule_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          schedule_id INTEGER NOT NULL REFERENCES classic_schedules(id) ON DELETE CASCADE,
          position INTEGER NOT NULL DEFAULT 0,
          label TEXT,
          start_type TEXT NOT NULL DEFAULT 'dynamic',
          start_minute INTEGER,
          fixed_behavior TEXT NOT NULL DEFAULT 'flexible',
          source_kind TEXT NOT NULL,
          source_ref TEXT NOT NULL,
          playback_order TEXT NOT NULL DEFAULT 'chronological',
          playout_mode TEXT NOT NULL DEFAULT 'one',
          multiple_mode TEXT NOT NULL DEFAULT 'count',
          multiple_count INTEGER NOT NULL DEFAULT 1,
          playout_duration_minutes INTEGER NOT NULL DEFAULT 30,
          fill_group_mode TEXT NOT NULL DEFAULT 'none',
          tail_mode TEXT NOT NULL DEFAULT 'none',
          filler_collection_id INTEGER REFERENCES collections(id) ON DELETE SET NULL,
          discard_attempts INTEGER NOT NULL DEFAULT 0,
          custom_title TEXT,
          guide_mode TEXT NOT NULL DEFAULT 'normal',
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_classic_items_schedule_pos ON classic_schedule_items(schedule_id,position,id);
        CREATE TABLE IF NOT EXISTS classic_playouts(
          channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
          schedule_id INTEGER NOT NULL REFERENCES classic_schedules(id) ON DELETE CASCADE,
          enabled INTEGER NOT NULL DEFAULT 1,
          generation INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_classic_playouts_schedule ON classic_playouts(schedule_id);

        CREATE TABLE IF NOT EXISTS filler_presets(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,library_id INTEGER REFERENCES libraries(id) ON DELETE SET NULL,
          interval_items INTEGER NOT NULL DEFAULT 1,max_items INTEGER NOT NULL DEFAULT 1,mode TEXT NOT NULL DEFAULT 'between',enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS channel_fillers(
          channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,filler_id INTEGER REFERENCES filler_presets(id) ON DELETE SET NULL);
        CREATE TABLE IF NOT EXISTS media_servers(
          id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,name TEXT NOT NULL,base_url TEXT NOT NULL,api_key TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(kind,base_url));
        CREATE TABLE IF NOT EXISTS external_libraries(
          id INTEGER PRIMARY KEY AUTOINCREMENT,server_id INTEGER NOT NULL REFERENCES media_servers(id) ON DELETE CASCADE,
          external_id TEXT NOT NULL,name TEXT NOT NULL,library_type TEXT NOT NULL,item_count INTEGER NOT NULL DEFAULT 0,last_synced_at TEXT,
          enabled INTEGER NOT NULL DEFAULT 1,UNIQUE(server_id,external_id));
        CREATE TABLE IF NOT EXISTS external_media(
          id INTEGER PRIMARY KEY AUTOINCREMENT,library_id INTEGER NOT NULL REFERENCES external_libraries(id) ON DELETE CASCADE,
          external_id TEXT NOT NULL,title TEXT NOT NULL,media_type TEXT NOT NULL,path TEXT,show_title TEXT,season_number INTEGER,episode_number INTEGER,
          duration REAL NOT NULL DEFAULT 0,summary TEXT,year INTEGER,thumb TEXT,updated_at TEXT NOT NULL,UNIQUE(library_id,external_id));
        CREATE TABLE IF NOT EXISTS external_channel_selections(
          id INTEGER PRIMARY KEY AUTOINCREMENT,channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
          library_id INTEGER NOT NULL REFERENCES external_libraries(id) ON DELETE CASCADE,show_title TEXT,season_number INTEGER);
        CREATE TABLE IF NOT EXISTS channel_templates(
          id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,config_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS playout_state(
          channel_id INTEGER NOT NULL,source_key TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,
          PRIMARY KEY(channel_id,source_key));
        """)
        for col, ddl in [
            ('logo_path','TEXT'),('watermark_enabled','INTEGER NOT NULL DEFAULT 0'),('subtitle_mode',"TEXT NOT NULL DEFAULT 'none'"),
            ('offline_media','TEXT'),('stream_profile',"TEXT NOT NULL DEFAULT 'software'"),('stream_mode',"TEXT NOT NULL DEFAULT 'mpegts'"),
            ('video_bitrate',"TEXT NOT NULL DEFAULT '5000k'"),('resolution',"TEXT NOT NULL DEFAULT '1920x1080'"),('frame_rate','TEXT')]:
            add_column_if_missing(conn,'channels',col,ddl)
        for col, ddl in [('summary','TEXT'),('year','INTEGER'),('poster_path','TEXT'),('fanart_path','TEXT'),('subtitle_path','TEXT')]:
            add_column_if_missing(conn,'media',col,ddl)
        conn.commit()


def _xml_text(root: ElementTree.Element, *tags: str) -> str | None:
    for tag in tags:
        x=root.find(tag)
        if x is not None and x.text:
            return x.text.strip()
    return None


def enrich_local_file(row: sqlite3.Row) -> None:
    p=Path(row['path'])
    nfo=p.with_suffix('.nfo')
    poster=None; fanart=None; subtitle=None; summary=None; year=None
    for candidate in [p.with_name(p.stem+'-poster.jpg'),p.with_name('poster.jpg'),p.parent/'poster.jpg']:
        if candidate.exists(): poster=str(candidate); break
    for candidate in [p.with_name(p.stem+'-fanart.jpg'),p.with_name('fanart.jpg'),p.parent/'fanart.jpg']:
        if candidate.exists(): fanart=str(candidate); break
    for ext in ['.srt','.vtt','.ass']:
        c=p.with_suffix(ext)
        if c.exists(): subtitle=str(c); break
    title=None; show=None; season=None; episode=None
    if nfo.exists():
        try:
            root=ElementTree.parse(nfo).getroot()
            title=_xml_text(root,'title')
            show=_xml_text(root,'showtitle','tvshowtitle')
            summary=_xml_text(root,'plot','outline')
            y=_xml_text(root,'year'); season=_xml_text(root,'season'); episode=_xml_text(root,'episode')
            year=int(y) if y and y.isdigit() else None
            season=int(season) if season and str(season).isdigit() else None
            episode=int(episode) if episode and str(episode).isdigit() else None
        except Exception: pass
    with db() as conn:
        conn.execute("""UPDATE media SET episode_title=COALESCE(?,episode_title),show_title=COALESCE(?,show_title),
          season_number=COALESCE(?,season_number),episode_number=COALESCE(?,episode_number),summary=COALESCE(?,summary),year=COALESCE(?,year),
          poster_path=COALESCE(?,poster_path),fanart_path=COALESCE(?,fanart_path),subtitle_path=COALESCE(?,subtitle_path) WHERE id=?""",
          (title,show,season,episode,summary,year,poster,fanart,subtitle,row['id']))
        conn.commit()


def enrich_all_local_metadata(limit: int | None = None) -> int:
    with db() as conn:
        rows=conn.execute('SELECT * FROM media ORDER BY id'+(' LIMIT ?' if limit else ''),(limit,) if limit else ()).fetchall()
    for r in rows:
        try: enrich_local_file(r)
        except Exception: pass
    return len(rows)


def _selection_items(token: str) -> list[dict[str,Any]]:
    try: payload=decode_selection(token)
    except Exception: return []
    st=str(payload.get('source_type') or ''); typ=str(payload.get('selection_type') or '')
    with db() as conn:
        if st=='local':
            q='SELECT m.*,l.name library_name FROM media m JOIN libraries l ON l.id=m.library_id WHERE m.duration>0';args=[]
            if typ=='item': q+=' AND m.id=?';args.append(safe_int(payload.get('media_id')))
            else:
                q+=' AND m.library_id=?';args.append(safe_int(payload.get('library_id')))
                if typ in ('show','season'):q+=' AND m.show_title=?';args.append(payload.get('show_title'))
                if typ=='season':q+=' AND m.season_number IS ?';args.append(payload.get('season_number'))
            rows=conn.execute(q,args).fetchall();out=[]
            for r in rows:
                d=dict(r);d.update({'source_type':'local','uid':f"local:{r['id']}",'air_date':None,'year':r['show_year'] if 'show_year' in r.keys() else None,
                                    'media_type':'episode' if r['show_title'] else 'movie','library_name':r['library_name']})
                out.append(d)
            return out
        if st=='plex':
            q="""SELECT pm.*,pl.title library_name FROM plex_media pm JOIN plex_libraries pl ON pl.id=pm.plex_library_id WHERE pm.duration>0""";args=[]
            if typ=='item':q+=' AND pm.plex_library_id=? AND pm.rating_key=?';args.extend([safe_int(payload.get('plex_library_id')),str(payload.get('rating_key'))])
            else:
                q+=' AND pm.plex_library_id=?';args.append(safe_int(payload.get('plex_library_id')))
                if typ in ('show','season'):
                    if payload.get('show_key'):q+=' AND (pm.show_rating_key=? OR (pm.show_rating_key IS NULL AND pm.show_title=?))';args.extend([str(payload.get('show_key')),str(payload.get('show_title') or '')])
                    else:q+=' AND pm.show_title=?';args.append(payload.get('show_title'))
                if typ=='season':q+=' AND pm.season_number IS ?';args.append(payload.get('season_number'))
                if typ=='movie':q+=' AND pm.rating_key=?';args.append(str(payload.get('show_key')))
            rows=conn.execute(q,args).fetchall();out=[]
            for r in rows:
                d=dict(r);d.update({'source_type':'plex','uid':f"plex:{r['plex_library_id']}:{r['rating_key']}",'air_date':r['originally_available_at'],'library_name':r['library_name']})
                out.append(d)
            return out
        if st=='external':
            q="""SELECT em.*,el.name library_name,ms.kind,ms.base_url,ms.api_key FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id WHERE em.duration>0""";args=[]
            if typ=='item':q+=' AND em.library_id=? AND em.external_id=?';args.extend([safe_int(payload.get('external_library_id')),str(payload.get('external_id'))])
            else:
                q+=' AND em.library_id=?';args.append(safe_int(payload.get('external_library_id')))
                if typ in ('show','season'):q+=' AND em.show_title=?';args.append(payload.get('show_title'))
                if typ=='season':q+=' AND em.season_number IS ?';args.append(payload.get('season_number'))
            rows=conn.execute(q,args).fetchall();out=[]
            for r in rows:
                d=dict(r);d.update({'source_type':'external','uid':f"external:{r['library_id']}:{r['external_id']}",'air_date':None})
                out.append(d)
            return out
    return []


def collection_media(collection_id:int, seen:set[int]|None=None)->list[dict[str,Any]]:
    seen=seen or set()
    if collection_id in seen:return []
    seen.add(collection_id)
    with db() as conn:
        c=conn.execute('SELECT * FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not c:return []
        tokens=[r['token'] for r in conn.execute('SELECT token FROM collection_selections WHERE collection_id=? ORDER BY id',(collection_id,))]
        members=[r['member_collection_id'] for r in conn.execute('SELECT member_collection_id FROM multi_collection_members WHERE collection_id=?',(collection_id,))]
    items=[]
    if c['kind']=='smart':
        try:
            rule=json.loads(c['rule_json'] or '{}');query=str(rule.get('query') or '').strip()
            if query:items.extend(media_search_playable(query))
            else:
                # Backward compatibility for v1.1.38's primitive field/value smart rule.
                field=rule.get('field'); value=str(rule.get('value','')).lower();base=LEGACY_CHANNEL_MEDIA(int(rule.get('channel_id',0)))[1] if rule.get('channel_id') else []
                if field in {'title','show_title','year'}:items.extend([x for x in base if value in str(x.get(field,'')).lower()])
        except Exception:pass
    else:
        for t in tokens:items.extend(_selection_items(t))
    if c['kind']=='multi':
        for m in members:items.extend(collection_media(m,seen))
    uniq={}
    for x in items:
        ident=x.get('uid') or f"{x.get('source_type')}:{x.get('library_id') or x.get('plex_library_id')}:{x.get('id') or x.get('rating_key') or x.get('external_id')}"
        uniq[str(ident)]=x
    return sorted(uniq.values(),key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))


def _playlist_order_items(items:list[dict[str,Any]], order:str, seed:str='')->list[dict[str,Any]]:
    out=list(items)
    if order=='chronological':
        out.sort(key=lambda x:(str(x.get('air_date') or x.get('originally_available_at') or x.get('year') or x.get('show_year') or ''),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    elif order in ('shuffle','random'):
        salt=(datetime.now().astimezone().date().isoformat() if order=='random' else 'stable')
        out.sort(key=lambda x:hashlib.sha256(f"{salt}|{seed}|{x.get('uid')}|{x.get('source_type')}|{x.get('id')}|{x.get('rating_key')}|{x.get('external_id')}".encode()).hexdigest())
    else:
        out.sort(key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    return out


def playlist_media(playlist_id:int)->list[dict[str,Any]]:
    """Expand one ordered ViperTV playlist into playable media."""
    with db() as conn:
        rows=conn.execute('SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall()
    out=[]
    for row in rows:
        try: payload=decode_selection(str(row['token']))
        except Exception: continue
        if payload.get('source_type')=='collection' and payload.get('collection_id'):
            items=collection_media(int(payload['collection_id']))
        else:
            items=_selection_items(str(row['token']))
        items=_playlist_order_items(items,str(row['playback_order'] or 'season_episode'),f"{playlist_id}:{row['id']}")
        out.extend(items)
    return out


# ---------------------- v1.1.46 Classic playout engine ----------------------
CLASSIC_DAY_CACHE:dict[tuple[Any,...],list[dict[str,Any]]]={}


def _classic_invalidate(channel_id:int|None=None)->None:
    if channel_id is None:CLASSIC_DAY_CACHE.clear();return
    for k in list(CLASSIC_DAY_CACHE):
        if k and k[0]==channel_id:CLASSIC_DAY_CACHE.pop(k,None)


def _classic_assignment(channel_id:int):
    try:
        with db() as conn:
            return conn.execute("""SELECT cp.channel_id,cp.schedule_id,cp.generation,cp.updated_at playout_updated,cs.*
              FROM classic_playouts cp JOIN classic_schedules cs ON cs.id=cp.schedule_id
              WHERE cp.channel_id=? AND cp.enabled=1""",(channel_id,)).fetchone()
    except sqlite3.Error:return None


def _classic_source_items(row:sqlite3.Row)->list[dict[str,Any]]:
    kind=str(row['source_kind']);ref=str(row['source_ref'])
    try:
        if kind in ('collection','smart_collection','multi_collection'):return collection_media(int(ref))
        if kind=='playlist':return playlist_media(int(ref))
        if kind in ('tv_show','tv_season'):return _selection_items(ref)
    except Exception:return []
    return []


def _classic_item_sort_key(x:dict[str,Any])->tuple[Any,...]:
    return (str(x.get('air_date') or x.get('originally_available_at') or x.get('year') or x.get('show_year') or ''),str(x.get('show_title') or x.get('title') or '').casefold(),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('episode_title') or x.get('title') or '').casefold())


def _classic_order_pool(pool:list[dict[str,Any]],order:str,seed:str)->list[dict[str,Any]]:
    out=[dict(x) for x in pool if float(x.get('duration') or 0)>0]
    if order=='season_episode':out.sort(key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),safe_int(x.get('season_number')) or -1,safe_int(x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    elif order=='chronological':out.sort(key=_classic_item_sort_key)
    elif order=='shuffle':out.sort(key=lambda x:hashlib.sha256(f"shuffle|{seed}|{x.get('uid')}|{x.get('id')}|{x.get('rating_key')}|{x.get('external_id')}".encode()).hexdigest())
    elif order=='random':
        if out:
            rnd=random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16],16));base=list(out);out=[dict(rnd.choice(base)) for _ in range(max(len(base),64))]
    elif order=='shuffle_in_order':
        groups={}
        for x in sorted(out,key=_classic_item_sort_key):groups.setdefault(str(x.get('show_title') or x.get('artist') or x.get('title') or ''),[]).append(x)
        keys=sorted(groups,key=lambda k:hashlib.sha256(f"group|{seed}|{k}".encode()).hexdigest());out=[]
        while any(groups[k] for k in keys):
            for k in keys:
                if groups[k]:out.append(groups[k].pop(0))
    return out


def _classic_group_pool(pool:list[dict[str,Any]],mode:str,seed:str,occurrence:int)->list[dict[str,Any]]:
    if mode not in ('ordered','shuffled') or not pool:return pool
    groups={}
    for x in pool:groups.setdefault(str(x.get('show_title') or x.get('artist') or x.get('title') or 'Other'),[]).append(x)
    keys=sorted(groups)
    if mode=='shuffled':keys.sort(key=lambda k:hashlib.sha256(f"{seed}|group|{k}".encode()).hexdigest())
    if not keys:return pool
    return groups[keys[occurrence%len(keys)]]


def _classic_decorate_media(src:dict[str,Any],row:sqlite3.Row,limit:float|None=None)->dict[str,Any]:
    x=dict(src);dur=max(1.0,float(src.get('duration') or 0))
    if limit is not None and limit<dur:
        x['_source_duration']=dur;x['_trim_limit']=max(1.0,float(limit));x['duration']=max(1.0,float(limit))
    x['_classic_schedule_item_id']=int(row['id']);x['_guide_custom_title']=str(row['custom_title'] or '')
    x['_guide_hidden']=str(row['guide_mode'] or 'normal')=='filler';x['_schedule_label']=str(row['label'] or '')
    return x


def _classic_gap(seconds:float,label:str='Off Air',hidden:bool=False)->dict[str,Any]:
    return {'source_type':'gap','uid':f"gap:{uuid.uuid4().hex}",'title':label,'duration':max(1.0,float(seconds)),'_guide_hidden':hidden,'_guide_custom_title':label,'summary':'Unscheduled time'}


def _classic_next_fixed(items:list[sqlite3.Row],used:set[int],cursor:float)->float|None:
    vals=[]
    for r in items:
        if int(r['id']) in used or str(r['start_type'])!='fixed' or r['start_minute'] is None:continue
        t=float(int(r['start_minute'])*60)
        if t>cursor+0.5:vals.append(t)
    return min(vals) if vals else None


def _classic_multipart_count(pool:list[dict[str,Any]],pos:int,treat_collections_as_shows:bool=False)->int:
    if not pool:return 1
    first=pool[pos%len(pool)];title=str(first.get('episode_title') or first.get('title') or '')
    m=re.search(r'(?i)\b(?:part|pt\.?)[ -]*(\d+)\b',title)
    if not m:return 1
    show=str(first.get('show_title') or '');n=int(m.group(1));count=1
    for j in range(1,min(8,len(pool))):
        nxt=pool[(pos+j)%len(pool)];nm=re.search(r'(?i)\b(?:part|pt\.?)[ -]*(\d+)\b',str(nxt.get('episode_title') or nxt.get('title') or ''))
        if (not treat_collections_as_shows and str(nxt.get('show_title') or '')!=show) or not nm or int(nm.group(1))!=n+j:break
        count+=1
    return count


def _classic_day_items(channel_id:int)->list[dict[str,Any]]:
    ass=_classic_assignment(channel_id)
    if not ass:return []
    try:tz=ZoneInfo(DEFAULT_TIMEZONE)
    except Exception:tz=ZoneInfo('UTC')
    today=datetime.now(tz).date();key=(channel_id,int(ass['schedule_id']),int(ass['generation']),str(ass['updated_at']),str(ass['playout_updated']),today.isoformat())
    cached=CLASSIC_DAY_CACHE.get(key)
    if cached is not None:return [dict(x) for x in cached]
    with db() as conn:rows=conn.execute('SELECT * FROM classic_schedule_items WHERE schedule_id=? ORDER BY position,id',(ass['schedule_id'],)).fetchall()
    if not rows:return []
    rows=list(rows)
    seed_base=f"{channel_id}|{ass['schedule_id']}|{ass['generation']}|{today.isoformat()}"
    if ass['shuffle_schedule_items']:
        rows.sort(key=lambda r:hashlib.sha256(f"{seed_base}|schedule-item|{r['id']}".encode()).hexdigest())
    pools={int(r['id']):_classic_order_pool(_classic_source_items(r),str(r['playback_order']),f"{seed_base}|{r['id']}") for r in rows}
    positions={int(r['id']):0 for r in rows};occ={int(r['id']):0 for r in rows};fixed_used:set[int]=set()
    if ass['random_start_point']:
        for r in rows:
            pool=pools[int(r['id'])]
            if pool:positions[int(r['id'])]=int(hashlib.sha256(f"{seed_base}|start|{r['id']}".encode()).hexdigest()[:8],16)%len(pool)
    out=[];cursor=0.0;day_end=86400.0;idx=0;stalled=0
    while cursor<day_end-0.5 and len(out)<20000 and stalled<len(rows)*4+8:
        r=rows[idx%len(rows)];idx+=1;rid=int(r['id']);before=cursor
        # Shuffled schedule items intentionally disable fixed starts and flood, mirroring ErsatzTV's classic limitation.
        start_type='dynamic' if ass['shuffle_schedule_items'] else str(r['start_type'])
        mode='one' if ass['shuffle_schedule_items'] and str(r['playout_mode'])=='flood' else str(r['playout_mode'])
        if start_type=='fixed' and r['start_minute'] is not None:
            target=float(int(r['start_minute'])*60)
            if rid in fixed_used:
                stalled+=1;continue
            if cursor<target:
                out.append(_classic_gap(target-cursor,'Off Air'));cursor=target
            elif cursor>target+0.5 and str(r['fixed_behavior'])=='strict':
                fixed_used.add(rid);stalled+=1;continue
            fixed_used.add(rid)
        pool=pools.get(rid) or []
        if not pool:
            stalled+=1;continue
        work=_classic_group_pool(pool,str(r['fill_group_mode']),f"{seed_base}|{rid}",occ[rid]);pos=positions[rid]%len(work) if work else 0
        if not work:stalled+=1;continue
        if mode=='one':count=_classic_multipart_count(work,pos,bool(ass['treat_collections_as_shows'])) if ass['keep_multi_part'] else 1;budget=None
        elif mode=='multiple':
            mm=str(r['multiple_mode'])
            if mm=='collection_size':count=len(work)
            elif mm=='multi_episode_group_size':count=_classic_multipart_count(work,pos,bool(ass['treat_collections_as_shows']))
            elif mm=='playlist_item_size':count=1
            else:count=max(1,int(r['multiple_count'] or 1))
            budget=None
        elif mode=='duration':count=100000;budget=float(max(1,int(r['playout_duration_minutes'] or 30))*60)
        else: # flood
            count=100000;nf=_classic_next_fixed(rows,fixed_used,cursor);budget=(nf-cursor if nf is not None else day_end-cursor)
        added=0;spent=0.0;attempts=0
        while added<count and cursor<day_end-0.5:
            candidate=work[(pos+added+attempts)%len(work)];dur=max(1.0,float(candidate.get('duration') or 0))
            remaining_day=day_end-cursor
            remaining=(budget-spent) if budget is not None else None
            cap=remaining_day if remaining is None else min(remaining_day,remaining)
            if cap<=0.5:break
            if dur>cap+0.5:
                if mode=='duration' and str(r['playback_order']) in ('shuffle','random') and attempts<int(r['discard_attempts'] or 0):attempts+=1;continue
                break
            out.append(_classic_decorate_media(candidate,r));cursor+=dur;spent+=dur;added+=1;attempts=0
            if mode=='flood' and spent>=float(budget or 0)-0.5:break
        positions[rid]=(positions[rid]+max(1,added))%max(1,len(pool));occ[rid]+=1
        if mode=='duration' and budget is not None:
            remain=max(0.0,budget-spent)
            if remain>0.5:
                if str(r['tail_mode'])=='filler' and r['filler_collection_id']:
                    filler=_classic_order_pool(collection_media(int(r['filler_collection_id'])),'shuffle',f"{seed_base}|tail|{rid}|{occ[rid]}")
                    fi=0
                    while filler and remain>0.5 and fi<len(filler)*3:
                        f=filler[fi%len(filler)];fd=max(1.0,float(f.get('duration') or 0));fi+=1
                        if fd<=remain+0.5:
                            fx=dict(f);fx['_guide_hidden']=True;fx['_classic_schedule_item_id']=rid;out.append(fx);cursor+=fd;remain-=fd
                    if remain>0.5:out.append(_classic_gap(remain,'Filler',True));cursor+=remain
                elif str(r['tail_mode'])=='offline':out.append(_classic_gap(remain,'Off Air'));cursor+=remain
        if mode=='flood' and budget is not None:
            remain=max(0.0,budget-spent)
            if remain>0.5:out.append(_classic_gap(remain,'Off Air'));cursor+=remain
        if cursor<=before+0.5:stalled+=1
        else:stalled=0
        # If all fixed items have been used and we have wrapped, they will be skipped; dynamic items can keep filling the day.
    if cursor<day_end-0.5:out.append(_classic_gap(day_end-cursor,'Off Air'));cursor=day_end
    elif cursor>day_end+0.5 and out:
        overflow=cursor-day_end;last=out[-1];dur=max(1.0,float(last.get('duration') or 0));newdur=max(1.0,dur-overflow);last['_source_duration']=dur;last['_trim_limit']=newdur;last['duration']=newdur
    anchor=datetime.combine(today,dt_time(0,0),tzinfo=tz).astimezone(timezone.utc).isoformat()
    if out:out[0]['_cycle_anchor_utc']=anchor
    for old_key in list(CLASSIC_DAY_CACHE):
        if old_key and old_key[0]==channel_id:CLASSIC_DAY_CACHE.pop(old_key,None)
    CLASSIC_DAY_CACHE[key]=[dict(x) for x in out]
    return [dict(x) for x in out]


LEGACY_CHANNEL_MEDIA=channel_media

def _active_schedule_source(channel_id:int, when:datetime|None=None):
    when=when or datetime.now().astimezone()
    bit=1<<when.weekday(); minute=when.hour*60+when.minute
    with db() as conn:
        return conn.execute("""SELECT si.* FROM schedule_items si JOIN schedules s ON s.id=si.schedule_id
          WHERE s.channel_id=? AND s.enabled=1 AND (si.day_mask & ?) != 0 AND si.start_minute<=? AND si.end_minute>?
          ORDER BY si.position,si.id LIMIT 1""",(channel_id,bit,minute,minute)).fetchone()


def _external_items(channel_id:int)->list[dict[str,Any]]:
    with db() as conn:
        sels=conn.execute('SELECT * FROM external_channel_selections WHERE channel_id=?',(channel_id,)).fetchall()
        out=[]
        for s in sels:
            q='SELECT em.*,ms.kind,ms.base_url,ms.api_key FROM external_media em JOIN external_libraries el ON el.id=em.library_id JOIN media_servers ms ON ms.id=el.server_id WHERE em.library_id=?'; a=[s['library_id']]
            if s['show_title']: q+=' AND em.show_title=?'; a.append(s['show_title'])
            if s['season_number'] is not None:q+=' AND em.season_number=?';a.append(s['season_number'])
            for r in conn.execute(q,a):
                d=dict(r); d['source_type']='external'; d['air_date']=None; out.append(d)
        return out


def _apply_filler(channel_id:int,items:list[dict[str,Any]])->list[dict[str,Any]]:
    with db() as conn:
        f=conn.execute('SELECT fp.* FROM channel_fillers cf JOIN filler_presets fp ON fp.id=cf.filler_id WHERE cf.channel_id=? AND fp.enabled=1',(channel_id,)).fetchone()
        if not f or not f['library_id']:return items
        fillers=[{**dict(r),'source_type':'local','air_date':None} for r in conn.execute('SELECT * FROM media WHERE library_id=? AND duration>0 ORDER BY id',(f['library_id'],))]
    if not fillers:return items
    out=[]; fi=0; every=max(1,int(f['interval_items']))
    for i,item in enumerate(items,1):
        out.append(item)
        if i%every==0:
            for _ in range(max(1,int(f['max_items']))):out.append(fillers[fi%len(fillers)]);fi+=1
    return out


def channel_media(channel_id:int)->tuple[sqlite3.Row,list[dict[str,Any]]]:
    channel,items=LEGACY_CHANNEL_MEDIA(channel_id)
    with db() as conn:
        col_ids=[r['collection_id'] for r in conn.execute('SELECT collection_id FROM channel_collections WHERE channel_id=?',(channel_id,))]
    for cid in col_ids:items.extend(collection_media(cid))
    items.extend(_external_items(channel_id))
    sched=_active_schedule_source(channel_id)
    preserve_source_order=False
    if sched and sched['source_type']=='collection' and sched['source_id']:
        items=collection_media(int(sched['source_id']))
    elif sched and sched['source_type']=='playlist' and sched['source_id']:
        items=playlist_media(int(sched['source_id']));preserve_source_order=True
    elif sched and sched['source_type']=='channel' and sched['source_id'] and int(sched['source_id'])!=channel_id:
        try:items=channel_media(int(sched['source_id']))[1]
        except Exception:pass
    uniq={}
    for x in items:
        # v0.2 local/Plex rows expose a stable 'uid'. The v1.0 wrapper
        # previously ignored it and deduplicated every episode from a source
        # down to a single row (the exact cause of "1 playable item").
        ident = x.get('uid')
        if not ident:
            st = x.get('source_type')
            if st == 'local':
                ident = f"local:{x.get('id') or x.get('path')}"
            elif st == 'plex':
                ident = f"plex:{x.get('plex_library_id')}:{x.get('rating_key') or x.get('plex_key')}"
            elif st == 'external':
                ident = f"external:{x.get('library_id')}:{x.get('external_id')}"
            else:
                ident = repr((st,x.get('id'),x.get('rating_key'),x.get('external_id'),x.get('path')))
        uniq[str(ident)] = x
    items=list(uniq.values())
    if not preserve_source_order:
        if channel['shuffle']:
            items.sort(key=lambda x:hashlib.sha256(f"{channel_id}|{x.get('source_type')}|{x.get('id')}|{x.get('rating_key')}|{x.get('external_id')}".encode()).hexdigest())
        else:
            items.sort(key=lambda x:(str(x.get('show_title') or ''),x.get('season_number') or -1,x.get('episode_number') or -1,str(x.get('title') or '')))
    # Actor/director + episode-air-year criteria are applied to the programme
    # pool before filler is inserted, so station IDs/commercials are not
    # accidentally removed from a people-based channel.
    items=_apply_channel_people_filter(channel_id,items)
    return channel,_apply_filler(channel_id,items)


def _daymask_from_form(days:list[str])->int:
    if not days:return 127
    m=0
    for d in days:
        try:m|=1<<int(d)
        except:pass
    return m


def _hm_to_min(v:str)->int:
    h,m=(v or '00:00').split(':',1);return int(h)*60+int(m)


def _min_to_hm(v:int)->str:return f'{v//60:02d}:{v%60:02d}'


def studio_page(msg:str='')->str:
    with db() as conn:
        cols=conn.execute('SELECT * FROM collections ORDER BY name').fetchall(); channels=conn.execute('SELECT * FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
        fillers=conn.execute('SELECT fp.*,l.name library_name FROM filler_presets fp LEFT JOIN libraries l ON l.id=fp.library_id ORDER BY fp.name').fetchall()
        libs=conn.execute('SELECT * FROM libraries ORDER BY name').fetchall(); templates=conn.execute('SELECT * FROM schedule_templates ORDER BY name').fetchall(); extlibs=conn.execute('SELECT el.*,ms.name server_name,ms.kind FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.enabled=1 ORDER BY ms.name,el.name').fetchall(); ctemplates=conn.execute('SELECT * FROM channel_templates ORDER BY name').fetchall()
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+"<div class='card'><h2>ViperTV Studio</h2><p>Collections, smart/multi-collections, ordered playlists, schedules, reusable blocks, filler, channel presentation, cloning and templates.</p></div>"
    body+="<div class='grid'><div class='card'><h2>Collections</h2><p>Collections now use the same search-first workflow as ErsatzTV: select search results for a manual Collection, or save the search itself as a dynamic Smart Collection.</p><p><a class='button' href='/media/search'>Search Media</a> <a class='button secondary' href='/lists/collections'>Collections</a> <a class='button secondary' href='/lists/smart'>Smart Collections</a> <a class='button secondary' href='/lists/multi'>Multi Collections</a></p><table>"+''.join(f"<tr><td>{e(c['name'])}</td><td>{e(c['kind'])}</td><td><a href='/studio/collections/{c['id']}'>Edit</a></td></tr>" for c in cols)+"</table></div>"
    body+="<div class='card'><h2>Filler presets</h2><form method='post' action='/studio/fillers/add'><input name='name' placeholder='Commercials' required><select name='library_id'>"+''.join(f"<option value='{l['id']}'>{e(l['name'])}</option>" for l in libs)+"</select><label>Insert after every N programmes</label><input type='number' min='1' name='interval_items' value='1'><label>Number of filler clips</label><input type='number' min='1' name='max_items' value='1'><button>Add filler preset</button></form><table>"+''.join(f"<tr><td>{e(f['name'])}</td><td>{e(f['library_name'])}</td></tr>" for f in fillers)+"</table></div></div>"
    body+="<div class='card'><h2>Channels & scheduling</h2><table><tr><th>#</th><th>Channel</th><th>Tools</th></tr>"+''.join(f"<tr><td>{e(c['number'])}</td><td>{e(c['name'])}</td><td><a class='button secondary' href='/studio/channel/{c['id']}'>Schedule / Presentation</a> <a class='button secondary' href='/channels/{c['id']}/clone'>Clone</a></td></tr>" for c in channels)+"</table></div>"
    body+="<div class='card'><h2>Reusable schedule templates</h2><p class='muted'>Save a channel schedule as a template from its Schedule page, then apply it to another channel.</p><p>Templates: "+(', '.join(e(t['name']) for t in templates) or 'None yet')+"</p></div>"
    return page_shell('Studio',body)


@app.get('/studio',response_class=HTMLResponse)
def studio(msg:str=''):return studio_page(msg)

@app.post('/media/movies/add-to-collection')
def movie_add_to_collection(token:str=Form(...),collection_id:str=Form(''),new_name:str=Form(''),return_url:str=Form('/media/movies')):
    try:
        payload=decode_selection(token)
        if payload.get('selection_type')!='item': raise ValueError('not an item')
        found=_selection_items(token)
        if len(found)!=1 or str(found[0].get('media_type') or '')!='movie': raise ValueError('not a movie')
    except Exception:
        return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('Invalid movie selection.'),303)
    safe_backup_before_change(); cid=safe_int(collection_id)
    with db() as conn:
        if new_name.strip():
            old=conn.execute('SELECT id,kind FROM collections WHERE name=?',(new_name.strip(),)).fetchone()
            if old and old['kind']!='manual': return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('That name is already used by a Smart or Multi Collection.'),303)
            if old: cid=int(old['id'])
            else: cid=int(conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(new_name.strip(),'manual','{}',utcnow_iso(),utcnow_iso())).lastrowid)
        c=conn.execute("SELECT id,name,kind FROM collections WHERE id=?",(cid,)).fetchone() if cid else None
        if not c or c['kind']!='manual': return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('Choose a manual collection or enter a new collection name.'),303)
        cur=conn.execute('INSERT OR IGNORE INTO collection_selections(collection_id,token) VALUES(?,?)',(cid,token))
        conn.execute('UPDATE collections SET updated_at=? WHERE id=?',(utcnow_iso(),cid));conn.commit()
        status='Added movie to '+str(c['name'])+'.' if cur.rowcount else 'That movie is already in '+str(c['name'])+'.'
    return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote(status),303)


@app.post('/media/movies/add-to-playlist')
def movie_add_to_playlist(token:str=Form(...),playlist_id:str=Form(''),new_name:str=Form(''),return_url:str=Form('/media/movies')):
    try:
        payload=decode_selection(token)
        if payload.get('selection_type')!='item': raise ValueError('not an item')
        found=_selection_items(token)
        if len(found)!=1 or str(found[0].get('media_type') or '')!='movie': raise ValueError('not a movie')
    except Exception:
        return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('Invalid movie selection.'),303)
    safe_backup_before_change(); pid=safe_int(playlist_id)
    with db() as conn:
        if new_name.strip():
            old=conn.execute('SELECT id FROM playlists WHERE name=?',(new_name.strip(),)).fetchone()
            if old: pid=int(old['id'])
            else: pid=int(conn.execute('INSERT INTO playlists(name,created_at,updated_at) VALUES(?,?,?)',(new_name.strip(),utcnow_iso(),utcnow_iso())).lastrowid)
        p=conn.execute('SELECT id,name FROM playlists WHERE id=?',(pid,)).fetchone() if pid else None
        if not p: return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('Choose a playlist or enter a new playlist name.'),303)
        pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playlist_items WHERE playlist_id=?',(pid,)).fetchone()['p'])
        conn.execute('INSERT INTO playlist_items(playlist_id,position,token,playback_order,created_at) VALUES(?,?,?,?,?)',(pid,pos,token,'season_episode',utcnow_iso()))
        conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(utcnow_iso(),pid));conn.commit()
    return RedirectResponse(return_url+('&' if '?' in return_url else '?')+'msg='+quote('Added movie to playlist '+str(p['name'])+'.'),303)


@app.post('/media/tv/show/add-to-collection')
def tv_show_add_to_collection(token:str=Form(...),collection_id:str=Form(''),new_name:str=Form(''),return_url:str=Form('/media/tv')):
    try:
        payload=decode_selection(token)
        if payload.get('selection_type')!='show': raise ValueError('not a show')
    except Exception:
        return RedirectResponse(return_url+'?msg='+quote('Invalid show selection.'),303)
    safe_backup_before_change(); cid=safe_int(collection_id)
    with db() as conn:
        if new_name.strip():
            old=conn.execute('SELECT id,kind FROM collections WHERE name=?',(new_name.strip(),)).fetchone()
            if old and old['kind']!='manual': return RedirectResponse(return_url+'&msg='+quote('That name is already used by a Smart or Multi Collection.'),303)
            if old: cid=int(old['id'])
            else: cid=int(conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)",(new_name.strip(),'manual','{}',utcnow_iso(),utcnow_iso())).lastrowid)
        c=conn.execute("SELECT id,name,kind FROM collections WHERE id=?",(cid,)).fetchone() if cid else None
        if not c or c['kind']!='manual': return RedirectResponse(return_url+'&msg='+quote('Choose a manual collection or enter a new collection name.'),303)
        cur=conn.execute('INSERT OR IGNORE INTO collection_selections(collection_id,token) VALUES(?,?)',(cid,token))
        conn.execute('UPDATE collections SET updated_at=? WHERE id=?',(utcnow_iso(),cid));conn.commit()
        status='Added entire show to '+str(c['name'])+'.' if cur.rowcount else 'That show is already in '+str(c['name'])+'.'
    return RedirectResponse(return_url+'&msg='+quote(status),303)


@app.post('/media/tv/show/add-to-playlist')
def tv_show_add_to_playlist(token:str=Form(...),playlist_id:str=Form(''),new_name:str=Form(''),playback_order:str=Form('season_episode'),return_url:str=Form('/media/tv')):
    try:
        payload=decode_selection(token)
        if payload.get('selection_type')!='show': raise ValueError('not a show')
    except Exception:
        return RedirectResponse(return_url+'&msg='+quote('Invalid show selection.'),303)
    if playback_order not in ('season_episode','chronological','shuffle','random'): playback_order='season_episode'
    safe_backup_before_change(); pid=safe_int(playlist_id)
    with db() as conn:
        if new_name.strip():
            old=conn.execute('SELECT id FROM playlists WHERE name=?',(new_name.strip(),)).fetchone()
            if old: pid=int(old['id'])
            else: pid=int(conn.execute('INSERT INTO playlists(name,created_at,updated_at) VALUES(?,?,?)',(new_name.strip(),utcnow_iso(),utcnow_iso())).lastrowid)
        p=conn.execute('SELECT id,name FROM playlists WHERE id=?',(pid,)).fetchone() if pid else None
        if not p: return RedirectResponse(return_url+'&msg='+quote('Choose a playlist or enter a new playlist name.'),303)
        pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playlist_items WHERE playlist_id=?',(pid,)).fetchone()['p'])
        conn.execute('INSERT INTO playlist_items(playlist_id,position,token,playback_order,created_at) VALUES(?,?,?,?,?)',(pid,pos,token,playback_order,utcnow_iso()))
        conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(utcnow_iso(),pid));conn.commit()
    return RedirectResponse(return_url+'&msg='+quote('Added entire show to playlist '+str(p['name'])+'.'),303)


@app.post('/studio/playlists/add')
def studio_playlist_add(name:str=Form(...)):
    name=name.strip()
    if not name:return RedirectResponse('/lists/playlists?msg='+quote('Playlist name is required.'),303)
    safe_backup_before_change()
    try:
        with db() as conn: conn.execute('INSERT INTO playlists(name,created_at,updated_at) VALUES(?,?,?)',(name,utcnow_iso(),utcnow_iso()));conn.commit()
    except sqlite3.IntegrityError:return RedirectResponse('/lists/playlists?msg='+quote('A playlist with that name already exists.'),303)
    return RedirectResponse('/lists/playlists?msg='+quote('Playlist created.'),303)


@app.get('/studio/playlists/{playlist_id}',response_class=HTMLResponse)
def studio_playlist_edit(playlist_id:int,msg:str=''): return playlist_edit_page(playlist_id,msg)


@app.post('/studio/playlists/{playlist_id}/rename')
def studio_playlist_rename(playlist_id:int,name:str=Form(...)):
    safe_backup_before_change(); name=name.strip()
    try:
        with db() as conn: conn.execute('UPDATE playlists SET name=?,updated_at=? WHERE id=?',(name,utcnow_iso(),playlist_id));conn.commit()
    except sqlite3.IntegrityError:return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+quote('That playlist name is already in use.'),303)
    return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+quote('Playlist renamed.'),303)


@app.post('/studio/playlists/{playlist_id}/add-collection')
def studio_playlist_add_collection(playlist_id:int,collection_id:int=Form(...),playback_order:str=Form('season_episode')):
    if playback_order not in ('season_episode','chronological','shuffle','random'): playback_order='season_episode'
    safe_backup_before_change()
    with db() as conn:
        p=conn.execute('SELECT id FROM playlists WHERE id=?',(playlist_id,)).fetchone(); c=conn.execute('SELECT id FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not p or not c: raise HTTPException(404)
        token=encode_selection({'source_type':'collection','selection_type':'collection','collection_id':collection_id})
        pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playlist_items WHERE playlist_id=?',(playlist_id,)).fetchone()['p'])
        conn.execute('INSERT INTO playlist_items(playlist_id,position,token,playback_order,created_at) VALUES(?,?,?,?,?)',(playlist_id,pos,token,playback_order,utcnow_iso()))
        conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(utcnow_iso(),playlist_id));conn.commit()
    return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+quote('Collection added to playlist.'),303)


@app.post('/studio/playlists/{playlist_id}/items/{item_id}/move')
def studio_playlist_move_item(playlist_id:int,item_id:int,direction:str=Form(...)):
    safe_backup_before_change()
    with db() as conn:
        rows=conn.execute('SELECT id FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall(); ids=[int(r['id']) for r in rows]
        if item_id in ids:
            i=ids.index(item_id); j=i-1 if direction=='up' else i+1 if direction=='down' else i
            if 0<=j<len(ids) and j!=i: ids[i],ids[j]=ids[j],ids[i]
            for pos,pid in enumerate(ids):conn.execute('UPDATE playlist_items SET position=? WHERE id=?',(pos,pid))
            conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(utcnow_iso(),playlist_id));conn.commit()
    return RedirectResponse(f'/studio/playlists/{playlist_id}',303)


@app.post('/studio/playlists/{playlist_id}/items/{item_id}/delete')
def studio_playlist_delete_item(playlist_id:int,item_id:int):
    safe_backup_before_change()
    with db() as conn:
        conn.execute('DELETE FROM playlist_items WHERE id=? AND playlist_id=?',(item_id,playlist_id))
        rows=conn.execute('SELECT id FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall()
        for pos,r in enumerate(rows):conn.execute('UPDATE playlist_items SET position=? WHERE id=?',(pos,r['id']))
        conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(utcnow_iso(),playlist_id));conn.commit()
    return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+quote('Playlist entry removed.'),303)


@app.post('/studio/playlists/{playlist_id}/delete')
def studio_playlist_delete(playlist_id:int):
    safe_backup_before_change()
    with db() as conn:
        conn.execute("DELETE FROM schedule_items WHERE source_type='playlist' AND source_id=?",(playlist_id,))
        conn.execute('DELETE FROM playlists WHERE id=?',(playlist_id,));conn.commit()
    return RedirectResponse('/lists/playlists?msg='+quote('Playlist deleted.'),303)


@app.post('/studio/collections/add')
def studio_collection_add(name:str=Form(...),kind:str=Form('manual'),rule_json:str=Form('{}')):
    safe_backup_before_change(); name=name.strip(); kind=kind if kind in ('manual','smart','multi') else 'manual'
    if not name:return RedirectResponse('/lists/collections?msg='+quote('Collection name is required.'),303)
    if kind=='smart':
        # Kept for backwards compatibility with older forms/imports; new smart
        # collections should normally be created with Search -> Save As.
        try: parsed=json.loads(rule_json or '{}')
        except Exception: parsed={}
        rule_json=json.dumps(parsed)
    else: rule_json='{}'
    try:
        with db() as conn:
            conn.execute('INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?,?,?,?,?)',(name,kind,rule_json,utcnow_iso(),utcnow_iso()));conn.commit()
    except sqlite3.IntegrityError:
        return RedirectResponse('/lists/'+('smart' if kind=='smart' else 'multi' if kind=='multi' else 'collections')+'?msg='+quote('A collection with that name already exists.'),303)
    target='smart' if kind=='smart' else 'multi' if kind=='multi' else 'collections'
    return RedirectResponse(f'/lists/{target}?msg='+quote('Collection created.'),303)

@app.get('/studio/collections/{collection_id}',response_class=HTMLResponse)
def studio_collection_edit(collection_id:int,msg:str=''):
    with db() as conn:
        c=conn.execute('SELECT * FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not c:raise HTTPException(404)
        toks=[r['token'] for r in conn.execute('SELECT token FROM collection_selections WHERE collection_id=? ORDER BY id',(collection_id,))]
        members={int(r['member_collection_id']) for r in conn.execute('SELECT member_collection_id FROM multi_collection_members WHERE collection_id=?',(collection_id,))}
        allc=conn.execute("SELECT * FROM collections WHERE id<>? AND kind IN ('manual','smart') ORDER BY name",(collection_id,)).fetchall()
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    common=f"""<div class='card'><form method='post' action='/studio/collections/{collection_id}/rename'><div class='grid'><div><label>Name</label><input name='name' value='{e(c['name'])}' required></div><div style='align-self:end'><button>Rename</button></div></div></form></div>"""
    if c['kind']=='smart':
        try:q=str(json.loads(c['rule_json'] or '{}').get('query') or '')
        except Exception:q=''
        count=len(media_search_playable(q,10001)) if q else 0
        body=notice+_page_heading(c['name'],'Smart Collection — a saved search that updates dynamically.',f"<a class='button secondary' href='/media/search?q={quote(q)}'>Test Search</a>")+common+f"""<div class='card'><h2>Saved Search</h2><form method='post' action='/studio/collections/{collection_id}/smart-save'><label>Query</label><textarea name='query' rows='4' required>{e(q)}</textarea><p class='muted'>{count:,} playable item(s) currently match this query.</p><button>Save Query</button></form></div>"""
    elif c['kind']=='multi':
        checks=''.join(f"<label style='display:block;padding:7px 0'><input type='checkbox' name='member' value='{x['id']}' {'checked' if int(x['id']) in members else ''}><b>{e(x['name'])}</b> <span class='badge blue'>{e(x['kind'])}</span></label>" for x in allc) or "<div class='empty'>Create a manual or Smart Collection first.</div>"
        body=notice+_page_heading(c['name'],'Multi Collection — combine existing manual and Smart Collections.')+common+f"<div class='card'><h2>Members</h2><form method='post' action='/studio/collections/{collection_id}/save'>{checks}<button>Save Members</button></form></div>"
    else:
        selected=''.join(f"<tr><td><input type='checkbox' name='remove_token' value='{e(t)}'></td><td>{e(_selection_description(t))}</td></tr>" for t in toks) or "<tr><td colspan='2' class='empty'>This collection is empty. Add media from Search.</td></tr>"
        body=notice+_page_heading(c['name'],'Manual Collection — explicitly selected media.',"<a class='button' href='/media/search'>Search / Add Media</a>")+common+f"""<div class='card'><h2>Selected Media</h2><form method='post' action='/studio/collections/{collection_id}/save'><div class='table-wrap'><table><thead><tr><th></th><th>Selection</th></tr></thead><tbody>{selected}</tbody></table></div><p class='muted small'>A show selection expands to all of its playable episodes; individual movie/episode selections remain exact.</p><button class='secondary'>Remove Checked</button></form></div>"""
    body+=f"""<div class='card'><h2>Danger Zone</h2><form method='post' action='/studio/collections/{collection_id}/delete' onsubmit="return confirm('Delete this collection? Channels using it will lose this collection source.');"><button class='danger'>Delete Collection</button></form></div>"""
    return page_shell('Collection',body)

@app.post('/studio/collections/{collection_id}/rename')
def studio_collection_rename(collection_id:int,name:str=Form(...)):
    safe_backup_before_change();name=name.strip()
    try:
        with db() as conn:conn.execute('UPDATE collections SET name=?,updated_at=? WHERE id=?',(name,utcnow_iso(),collection_id));conn.commit()
    except sqlite3.IntegrityError:return RedirectResponse(f'/studio/collections/{collection_id}?msg='+quote('That collection name is already in use.'),303)
    return RedirectResponse(f'/studio/collections/{collection_id}?msg='+quote('Collection renamed.'),303)

@app.post('/studio/collections/{collection_id}/smart-save')
def studio_collection_smart_save(collection_id:int,query:str=Form(...)):
    safe_backup_before_change();query=query.strip()
    with db() as conn:
        c=conn.execute('SELECT kind FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not c or c['kind']!='smart':raise HTTPException(404)
        conn.execute('UPDATE collections SET rule_json=?,updated_at=? WHERE id=?',(json.dumps({'query':query},ensure_ascii=False),utcnow_iso(),collection_id));conn.commit()
    return RedirectResponse(f'/studio/collections/{collection_id}?msg='+quote('Smart Collection query saved.'),303)

@app.post('/studio/collections/{collection_id}/save')
def studio_collection_save(collection_id:int,member:list[int]=Form(default=[]),remove_token:list[str]=Form(default=[]),sel:list[str]=Form(default=[])):
    safe_backup_before_change()
    with db() as conn:
        c=conn.execute('SELECT kind FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not c:raise HTTPException(404)
        if c['kind']=='multi':
            conn.execute('DELETE FROM multi_collection_members WHERE collection_id=?',(collection_id,))
            for m in member:
                valid=conn.execute("SELECT id FROM collections WHERE id=? AND kind IN ('manual','smart')",(m,)).fetchone()
                if valid:conn.execute('INSERT OR IGNORE INTO multi_collection_members(collection_id,member_collection_id) VALUES(?,?)',(collection_id,m))
        elif c['kind']=='manual':
            for t in remove_token:conn.execute('DELETE FROM collection_selections WHERE collection_id=? AND token=?',(collection_id,t))
            for t in sel:conn.execute('INSERT OR IGNORE INTO collection_selections(collection_id,token) VALUES(?,?)',(collection_id,t))
        conn.execute('UPDATE collections SET updated_at=? WHERE id=?',(utcnow_iso(),collection_id));conn.commit()
    return RedirectResponse(f'/studio/collections/{collection_id}?msg='+quote('Collection saved.'),303)

@app.post('/studio/collections/{collection_id}/delete')
def studio_collection_delete(collection_id:int):
    safe_backup_before_change()
    with db() as conn:
        c=conn.execute('SELECT kind FROM collections WHERE id=?',(collection_id,)).fetchone()
        if not c:raise HTTPException(404)
        kind=str(c['kind']);conn.execute('DELETE FROM collections WHERE id=?',(collection_id,));conn.commit()
    target='smart' if kind=='smart' else 'multi' if kind=='multi' else 'collections'
    return RedirectResponse(f'/lists/{target}?msg='+quote('Collection deleted.'),303)

@app.post('/studio/fillers/add')
def studio_filler_add(name:str=Form(...),library_id:int=Form(...),interval_items:int=Form(1),max_items:int=Form(1)):
    with db() as conn:conn.execute('INSERT INTO filler_presets(name,library_id,interval_items,max_items) VALUES(?,?,?,?)',(name,library_id,max(1,interval_items),max(1,max_items)));conn.commit()
    return RedirectResponse('/lists/filler?msg=Filler+preset+created',303)

@app.get('/studio/channel/{channel_id}',response_class=HTMLResponse)
def studio_channel(channel_id:int,msg:str=''):
    with db() as conn:
        c=conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone(); collections=conn.execute('SELECT * FROM collections ORDER BY name').fetchall(); playlists=conn.execute('SELECT * FROM playlists ORDER BY name').fetchall(); fillers=conn.execute('SELECT * FROM filler_presets ORDER BY name').fetchall();
        sch=conn.execute('SELECT * FROM schedules WHERE channel_id=? ORDER BY id LIMIT 1',(channel_id,)).fetchone(); items=conn.execute('SELECT * FROM schedule_items WHERE schedule_id=? ORDER BY position,id',(sch['id'],)).fetchall() if sch else []
        linked={r['collection_id'] for r in conn.execute('SELECT collection_id FROM channel_collections WHERE channel_id=?',(channel_id,))}; cf=conn.execute('SELECT filler_id FROM channel_fillers WHERE channel_id=?',(channel_id,)).fetchone(); templates=conn.execute('SELECT * FROM schedule_templates ORDER BY name').fetchall(); extlibs=conn.execute('SELECT el.*,ms.name server_name,ms.kind FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.enabled=1 ORDER BY ms.name,el.name').fetchall(); ctemplates=conn.execute('SELECT * FROM channel_templates ORDER BY name').fetchall()
    if not c:raise HTTPException(404)
    rows=''.join(f"<tr><td>{e(i['label'] or '')}</td><td>{_min_to_hm(i['start_minute'])}-{_min_to_hm(i['end_minute'])}</td><td>{e(i['source_type'])} {e(i['source_id'])}</td><td><form method='post' action='/studio/schedule/item/{i['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for i in items) or "<tr><td colspan=4 class='muted'>No schedule items. Channel uses its normal selections 24/7.</td></tr>"
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+f"<div class='card'><h2>{e(c['number'])} {e(c['name'])}</h2><form method='post' action='/studio/channel/{channel_id}/settings'><div class='grid'><div><label>Logo path</label><input name='logo_path' value='{e(c['logo_path'])}' placeholder='/data/logos/channel.png'><label><input type='checkbox' name='watermark_enabled' value='1' {'checked' if c['watermark_enabled'] else ''}> Watermark/logo bug</label><label>Subtitle mode</label><select name='subtitle_mode'><option {'selected' if c['subtitle_mode']=='none' else ''}>none</option><option {'selected' if c['subtitle_mode']=='burn' else ''}>burn</option><option {'selected' if c['subtitle_mode']=='copy' else ''}>copy</option></select><label>Offline media path</label><input name='offline_media' value='{e(c['offline_media'])}'></div><div><label>Stream profile</label><select name='stream_profile'>{_hardware_profile_options(str(c['stream_profile'] or 'global'),True)}</select><div class='muted small'>Manage and test GPUs under System → Hardware Acceleration.</div><label>Stream mode</label><select name='stream_mode'><option value='mpegts' {'selected' if c['stream_mode']=='mpegts' else ''}>MPEG-TS — sanitized / recommended</option><option value='mpegts_legacy' {'selected' if c['stream_mode']=='mpegts_legacy' else ''}>MPEG-TS Legacy — direct shared feed</option><option value='hls' {'selected' if c['stream_mode']=='hls' else ''}>HLS Segmenter — compatibility</option><option value='hls_direct' {'selected' if c['stream_mode']=='hls_direct' else ''}>HLS Direct — low latency</option></select><div class='muted small'>Choose how IPTV clients receive this channel. All modes reuse the one shared station producer.</div><label>Resolution</label><input name='resolution' value='{e(c['resolution'])}'><label>Video bitrate</label><input name='video_bitrate' value='{e(c['video_bitrate'])}'><label>Frame rate (optional)</label><input name='frame_rate' value='{e(c['frame_rate'])}'></div></div><h3>Attach collections</h3>"+''.join(f"<label style='display:block'><input type='checkbox' name='collection_id' value='{x['id']}' {'checked' if x['id'] in linked else ''}>{e(x['name'])}</label>" for x in collections)+"<label>Filler preset</label><select name='filler_id'><option value=''>None</option>"+''.join(f"<option value='{f['id']}' {'selected' if cf and cf['filler_id']==f['id'] else ''}>{e(f['name'])}</option>" for f in fillers)+"</select><button>Save presentation & sources</button></form></div>"
    with db() as conn:
        cp=conn.execute('SELECT cp.*,cs.name schedule_name FROM classic_playouts cp JOIN classic_schedules cs ON cs.id=cp.schedule_id WHERE cp.channel_id=?',(channel_id,)).fetchone()
    body+=f"<div class='card'><h2>Classic Schedule / Playout</h2><p>{('Assigned: <b>'+e(cp['schedule_name'])+'</b>') if cp else 'No reusable Classic Schedule assigned.'}</p><a class='button' href='/scheduling/playouts'>Assign Playout</a> <a class='button secondary' href='/scheduling/schedules'>Edit Schedules</a></div>"
    body+=f"<div class='card'><h2>Legacy Time Blocks</h2><p class='muted'>Preserved for compatibility with schedules created before v1.1.46. A Classic Playout takes precedence when assigned.</p><table><tr><th>Label</th><th>Time</th><th>Source</th><th></th></tr>{rows}</table><h3>Add legacy time block</h3><form method='post' action='/studio/channel/{channel_id}/schedule/add'><input name='label' placeholder='Prime Time'><div class='grid3'><div><label>Start</label><input type='time' name='start' value='18:00'></div><div><label>End</label><input type='time' name='end' value='23:00'></div><div><label>Programming Source</label><select name='source_ref'>"+''.join(f"<option value='collection:{x['id']}'>Collection — {e(x['name'])}</option>" for x in collections)+''.join(f"<option value='playlist:{x['id']}'>Playlist — {e(x['name'])}</option>" for x in playlists)+"</select></div></div><p>Days: "+' '.join(f"<label><input type='checkbox' name='days' value='{i}' checked>{d}</label>" for i,d in enumerate(['Mon','Tue','Wed','Thu','Fri','Sat','Sun']))+"</p><select name='mode'><option>sequential</option><option>shuffle</option><option>random</option></select><label>Pad to minute boundary (0/15/30/60)</label><input type='number' name='pad_to_minutes' value='0'><button>Add block</button></form><hr><form class='inline' method='post' action='/studio/channel/{channel_id}/schedule/template'><input name='name' placeholder='Weekday Schedule' required><button>Save schedule as template</button></form> <form class='inline' method='post' action='/studio/channel/{channel_id}/schedule/apply'><select name='template_id'>"+''.join(f"<option value='{t['id']}'>{e(t['name'])}</option>" for t in templates)+"</select><button>Apply template</button></form></div>"
    body+=f"<div class='grid'><div class='card'><h2>Jellyfin / Emby channel source</h2><form method='post' action='/studio/channel/{channel_id}/external/add'><select name='library_id'>"+''.join(f"<option value='{x['id']}'>{e(x['kind'])} / {e(x['server_name'])} / {e(x['name'])}</option>" for x in extlibs)+"</select><input name='show_title' placeholder='Show title (blank = whole library)'><input name='season_number' placeholder='Season number (optional)'><button>Add source</button></form></div><div class='card'><h2>Channel templates</h2><form method='post' action='/studio/channel/{channel_id}/template'><input name='name' placeholder='My Channel Template' required><button>Save current as template</button></form><form method='post' action='/studio/channel/{channel_id}/template/apply'><select name='template_id'>"+''.join(f"<option value='{t['id']}'>{e(t['name'])}</option>" for t in ctemplates)+"</select><button>Apply template to this channel</button></form></div></div>"
    return page_shell('Channel Studio',body)

@app.post('/studio/channel/{channel_id}/settings')
def studio_channel_settings(channel_id:int,logo_path:str=Form(''),watermark_enabled:int=Form(0),subtitle_mode:str=Form('none'),offline_media:str=Form(''),stream_profile:str=Form('global'),stream_mode:str=Form('mpegts'),resolution:str=Form('1920x1080'),video_bitrate:str=Form('5000k'),frame_rate:str=Form(''),collection_id:list[int]=Form(default=[]),filler_id:str=Form('')):
    stream_profile=stream_profile.strip().lower()
    if stream_profile not in HARDWARE_STREAM_PROFILES:
        return RedirectResponse(f'/studio/channel/{channel_id}?msg='+quote('Invalid stream profile.'),303)
    stream_mode=stream_mode.strip().lower()
    if stream_mode not in {'mpegts','mpegts_legacy','hls','hls_direct'}:
        return RedirectResponse(f'/studio/channel/{channel_id}?msg='+quote('Invalid streaming mode.'),303)
    safe_backup_before_change()
    with db() as conn:
        conn.execute('UPDATE channels SET logo_path=?,watermark_enabled=?,subtitle_mode=?,offline_media=?,stream_profile=?,stream_mode=?,resolution=?,video_bitrate=?,frame_rate=? WHERE id=?',(logo_path or None,1 if watermark_enabled else 0,subtitle_mode,offline_media or None,stream_profile,stream_mode,resolution,video_bitrate,frame_rate or None,channel_id))
        conn.execute('DELETE FROM channel_collections WHERE channel_id=?',(channel_id,));
        for cid in collection_id:conn.execute('INSERT OR IGNORE INTO channel_collections(channel_id,collection_id) VALUES(?,?)',(channel_id,cid))
        conn.execute('DELETE FROM channel_fillers WHERE channel_id=?',(channel_id,));
        if filler_id:conn.execute('INSERT INTO channel_fillers(channel_id,filler_id) VALUES(?,?)',(channel_id,int(filler_id)))
        conn.commit()
    _restart_shared_channel_if_running(channel_id)
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Saved',303)

@app.post('/studio/channel/{channel_id}/schedule/add')
def schedule_add(channel_id:int,label:str=Form(''),start:str=Form(...),end:str=Form(...),source_ref:str=Form(...),days:list[str]=Form(default=[]),mode:str=Form('sequential'),pad_to_minutes:int=Form(0)):
    try:
        source_type,source_id_text=source_ref.split(':',1);source_id=int(source_id_text)
        if source_type not in ('collection','playlist'):raise ValueError()
    except Exception:
        return RedirectResponse(f'/studio/channel/{channel_id}?msg='+quote('Choose a valid Collection or Playlist source.'),303)
    with db() as conn:
        sch=conn.execute('SELECT id FROM schedules WHERE channel_id=? LIMIT 1',(channel_id,)).fetchone()
        if not sch:
            cur=conn.execute('INSERT INTO schedules(channel_id,name,created_at) VALUES(?,?,?)',(channel_id,'Main Schedule',utcnow_iso()));sid=cur.lastrowid
        else:sid=sch['id']
        pos=conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM schedule_items WHERE schedule_id=?',(sid,)).fetchone()['p']
        conn.execute('INSERT INTO schedule_items(schedule_id,day_mask,start_minute,end_minute,source_type,source_id,mode,pad_to_minutes,position,label) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,_daymask_from_form(days),_hm_to_min(start),_hm_to_min(end),source_type,source_id,mode,pad_to_minutes,pos,label));conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Schedule+block+added',303)

@app.post('/studio/schedule/item/{item_id}/delete')
def schedule_item_delete(item_id:int):
    with db() as conn:
        r=conn.execute('SELECT s.channel_id FROM schedule_items si JOIN schedules s ON s.id=si.schedule_id WHERE si.id=?',(item_id,)).fetchone();conn.execute('DELETE FROM schedule_items WHERE id=?',(item_id,));conn.commit()
    return RedirectResponse(f"/studio/channel/{r['channel_id']}" if r else '/studio',303)

@app.post('/studio/channel/{channel_id}/schedule/template')
def schedule_save_template(channel_id:int,name:str=Form(...)):
    with db() as conn:
        sch=conn.execute('SELECT id FROM schedules WHERE channel_id=? LIMIT 1',(channel_id,)).fetchone(); items=[dict(r) for r in conn.execute('SELECT * FROM schedule_items WHERE schedule_id=? ORDER BY position,id',(sch['id'],))] if sch else []
        for i in items:i.pop('id',None);i.pop('schedule_id',None)
        conn.execute('INSERT OR REPLACE INTO schedule_templates(name,items_json,created_at) VALUES(?,?,?)',(name,json.dumps(items),utcnow_iso()));conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Template+saved',303)

@app.post('/studio/channel/{channel_id}/schedule/apply')
def schedule_apply_template(channel_id:int,template_id:int=Form(...)):
    with db() as conn:
        t=conn.execute('SELECT * FROM schedule_templates WHERE id=?',(template_id,)).fetchone();sch=conn.execute('SELECT id FROM schedules WHERE channel_id=? LIMIT 1',(channel_id,)).fetchone()
        if not sch: sid=conn.execute('INSERT INTO schedules(channel_id,name,created_at) VALUES(?,?,?)',(channel_id,'Main Schedule',utcnow_iso())).lastrowid
        else:sid=sch['id'];conn.execute('DELETE FROM schedule_items WHERE schedule_id=?',(sid,))
        for i in json.loads(t['items_json'] if t else '[]'):
            conn.execute('INSERT INTO schedule_items(schedule_id,day_mask,start_minute,end_minute,source_type,source_id,mode,play_count,pad_to_minutes,position,label) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(sid,i['day_mask'],i['start_minute'],i['end_minute'],i['source_type'],i['source_id'],i.get('mode','sequential'),i.get('play_count',1),i.get('pad_to_minutes',0),i.get('position',0),i.get('label')))
        conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Template+applied',303)

@app.post('/studio/channel/{channel_id}/clone')
def clone_channel(channel_id:int):
    # Backward-compatible one-click endpoint retained for old bookmarks/UI.
    # New UI uses /channels/{id}/clone so the user can create several copies at once.
    safe_backup_before_change()
    with db() as conn:
        c=conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone()
        if not c:raise HTTPException(404)
        num=str(_next_clone_channel_number(conn,c['number']))
        nid=_copy_channel_configuration(conn,channel_id,num,c['name']+' 2')
        conn.commit()
    return RedirectResponse(f'/studio/channel/{nid}?msg=Channel+cloned',303)

# ----------------------- Jellyfin / Emby sources -----------------------------
def _server_json(server:sqlite3.Row,path:str,params:dict[str,Any]|None=None):
    params=params or {}; kind=server['kind']; base=server['base_url'].rstrip('/')
    if kind=='jellyfin': headers={'X-Emby-Token':server['api_key']}
    else: headers={'X-Emby-Token':server['api_key']}
    url=base+path
    if params:url+='?'+urlencode(params)
    req=URLRequest(url,headers=headers)
    with urlopen(req,timeout=30) as resp:return json.loads(resp.read().decode())

def discover_external(server_id:int):
    with db() as conn:server=conn.execute('SELECT * FROM media_servers WHERE id=?',(server_id,)).fetchone()
    if not server:raise ValueError('Server not found')
    data=_server_json(server,'/Library/VirtualFolders')
    with db() as conn:
        for x in data:
            ext=x.get('ItemId') or x.get('Id'); name=x.get('Name') or 'Library'; typ=(x.get('CollectionType') or 'mixed').lower()
            if ext:conn.execute('INSERT INTO external_libraries(server_id,external_id,name,library_type) VALUES(?,?,?,?) ON CONFLICT(server_id,external_id) DO UPDATE SET name=excluded.name,library_type=excluded.library_type,enabled=1',(server_id,str(ext),name,typ))
        conn.commit()
    return len(data)

def sync_external_library(library_id:int):
    with db() as conn:
        lib=conn.execute('SELECT el.*,ms.kind,ms.base_url,ms.api_key FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.id=?',(library_id,)).fetchone()
    if not lib:raise ValueError('Library not found')
    data=_server_json(lib,'/Items',{'ParentId':lib['external_id'],'Recursive':'true','IncludeItemTypes':'Episode,Movie','Fields':'Path,Overview,PremiereDate,ProductionYear,RunTimeTicks,SeriesName,ParentIndexNumber,IndexNumber,ImageTags','Limit':'100000'})
    items=data.get('Items',data if isinstance(data,list) else [])
    with db() as conn:
        conn.execute('DELETE FROM external_media WHERE library_id=?',(library_id,))
        for x in items:
            dur=float(x.get('RunTimeTicks') or 0)/10_000_000
            conn.execute('INSERT OR REPLACE INTO external_media(library_id,external_id,title,media_type,path,show_title,season_number,episode_number,duration,summary,year,thumb,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(library_id,str(x.get('Id')),x.get('Name') or 'Untitled',(x.get('Type') or '').lower(),x.get('Path'),x.get('SeriesName'),safe_int(x.get('ParentIndexNumber')),safe_int(x.get('IndexNumber')),dur,x.get('Overview'),safe_int(x.get('ProductionYear')),None,utcnow_iso()))
        conn.execute('UPDATE external_libraries SET item_count=?,last_synced_at=? WHERE id=?',(len(items),utcnow_iso(),library_id));conn.commit()
    return len(items)

@app.get('/sources',response_class=HTMLResponse)
def sources_page(msg:str=''):
    with db() as conn:
        servers=conn.execute('SELECT * FROM media_servers ORDER BY name').fetchall(); libs=conn.execute('SELECT el.*,ms.name server_name,ms.kind FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id ORDER BY ms.name,el.name').fetchall()
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+"<div class='card'><h2>Jellyfin / Emby</h2><p><a class='button secondary' href='/sources/path-replacements'>Direct Media Paths</a></p><p class='muted small'>Optional path replacements let ViperTV use Jellyfin/Emby for metadata while FFmpeg reads the mounted media file directly. HTTP streaming remains the automatic fallback.</p><form method='post' action='/sources/add'><select name='kind'><option>jellyfin</option><option>emby</option></select><input name='name' placeholder='Media Server' required><input name='base_url' placeholder='http://192.168.1.100:8096' required><input name='api_key' type='password' placeholder='API key' required><button>Add & Discover</button></form></div><div class='card'><h2>Servers</h2><table>"+''.join(f"<tr><td>{e(s['kind'])}</td><td>{e(s['name'])}</td><td>{e(s['base_url'])}</td><td><form method='post' action='/sources/{s['id']}/discover'><button>Discover</button></form></td></tr>" for s in servers)+"</table></div><div class='card'><h2>Libraries</h2><table>"+''.join(f"<tr><td>{e(l['server_name'])}</td><td>{e(l['name'])}</td><td>{l['item_count']}</td><td><form method='post' action='/sources/library/{l['id']}/sync'><button>Sync</button></form></td></tr>" for l in libs)+"</table></div>"
    return page_shell('Sources',body)

@app.post('/sources/add')
def sources_add(kind:str=Form(...),name:str=Form(...),base_url:str=Form(...),api_key:str=Form(...)):
    with db() as conn:
        cur=conn.execute('INSERT INTO media_servers(kind,name,base_url,api_key,created_at,updated_at) VALUES(?,?,?,?,?,?)',(kind,name,base_url.rstrip('/'),api_key,utcnow_iso(),utcnow_iso()));conn.commit();sid=cur.lastrowid
    try:n=discover_external(sid);msg=f'Discovered {n} libraries'
    except Exception as ex:msg=f'Saved; discovery failed: {ex}'
    return RedirectResponse('/sources?msg='+quote(msg),303)

@app.post('/sources/{server_id}/discover')
def sources_discover(server_id:int):
    try:n=discover_external(server_id);msg=f'Discovered {n} libraries'
    except Exception as ex:msg=str(ex)
    return RedirectResponse('/sources?msg='+quote(msg),303)

@app.post('/sources/library/{library_id}/sync')
def sources_sync(library_id:int):
    try:n=sync_external_library(library_id);msg=f'Synced {n} items'
    except Exception as ex:msg=str(ex)
    return RedirectResponse('/sources?msg='+quote(msg),303)

# ---------------- Guide preview / XMLTV-friendly schedule preview ------------
@app.get('/guide',response_class=HTMLResponse)
def guide_page(hours:int=6, offset:int=0):
    # A conventional EPG: channels stay fixed on the left while time scrolls
    # horizontally.  Keep the visible window bounded so even a 7-day guide is
    # practical to render on modest ViperTV hardware.
    hours=max(1,min(int(hours or 6),168))
    offset=max(-168,min(int(offset or 0),168))
    now=datetime.now().astimezone()
    rounded=now.replace(minute=(now.minute//30)*30,second=0,microsecond=0)
    guide_start=rounded+timedelta(hours=offset)
    guide_end=guide_start+timedelta(hours=hours)

    # Wider near-term windows read like a normal cable guide.  Long windows are
    # still scrollable without producing an absurdly wide page.
    if hours<=6: px_per_min=2.4
    elif hours<=12: px_per_min=2.0
    elif hours<=24: px_per_min=1.45
    else: px_per_min=0.75
    timeline_width=max(720,int(hours*60*px_per_min))
    slot_minutes=30
    slot_width=slot_minutes*px_per_min

    with db() as conn:
        channels=conn.execute('SELECT * FROM channels WHERE enabled=1 ORDER BY CAST(number AS REAL),number').fetchall()
        pluto_channels=conn.execute('SELECT * FROM pluto_channels WHERE imported=1 AND available=1 ORDER BY CAST(display_number AS REAL),display_number,name').fetchall()
        live_streams=conn.execute('SELECT * FROM live_streams WHERE enabled=1 ORDER BY CAST(number AS REAL),number,name').fetchall()

    # Time ruler every 30 minutes.
    labels=[]
    slots=hours*2+1
    for i in range(slots):
        t=guide_start+timedelta(minutes=i*slot_minutes)
        x=int(i*slot_width)
        day=t.strftime('%a %b %-d') if (i==0 or (t.hour==0 and t.minute==0)) else ''
        labels.append(
            f"<div class='epg-time' style='left:{x}px;width:{max(1,int(slot_width))}px'>"
            f"<span class='epg-day'>{e(day)}</span><span>{e(t.strftime('%H:%M'))}</span></div>"
        )

    rows=[]
    for c in channels:
        blocks=[]
        row_note=''
        retro_cfg = _retro_config_for_channel(int(c['id']))
        if retro_cfg:
            blocks, row_note = _retro_guide_blocks(int(c['id']), guide_start, guide_end, now, px_per_min)
            items = []
        try:
            if retro_cfg:
                raise StopIteration
            _,items=channel_media(c['id'])
            if items:
                idx,off,item_start_utc=locate_at(items,guide_start.astimezone(timezone.utc))
                # Convert the returned UTC-aware start back to the guide's local timezone.
                item_start=item_start_utc.astimezone(guide_start.tzinfo)
                cursor=item_start
                current_off=float(off or 0)
                # Enough repetitions for 7 days even for very short clips, while
                # retaining a hard ceiling against malformed metadata.
                max_programmes=min(10000,max(1000,len(items)*40))
                for n in range(max_programmes):
                    item=items[(idx+n)%len(items)]
                    actual_dur=max(float(item.get('duration') or 0),1.0)
                    guide_dur=max(float(item.get('_guide_duration') or actual_dur),60.0)
                    if n==0:
                        prog_start=cursor
                    else:
                        prog_start=cursor
                    prog_end=prog_start+timedelta(seconds=guide_dur)
                    actual_end=prog_start+timedelta(seconds=actual_dur)
                    if prog_end>guide_start and prog_start<guide_end:
                        visible_start=max(prog_start,guide_start)
                        visible_end=min(prog_end,guide_end)
                        left=max(0.0,(visible_start-guide_start).total_seconds()/60.0*px_per_min)
                        width=max(3.0,(visible_end-visible_start).total_seconds()/60.0*px_per_min)
                        title=item.get('_guide_custom_title') or item.get('show_title') or item.get('title') or 'Untitled'
                        sub='' if item.get('_guide_custom_title') else (item.get('episode_title') or '')
                        if not sub and item.get('show_title') and item.get('title') and item.get('title')!=item.get('show_title'):
                            sub=item.get('title') or ''
                        when=f"{prog_start.strftime('%H:%M')}–{prog_end.strftime('%H:%M')}"
                        is_now=(prog_start<=now<prog_end)
                        media_class=guide_media_class(item)
                        full_tip=f"{title}"+(f" — {sub}" if sub else '')+f" ({when})"
                        if not item.get('_guide_hidden'):
                            blocks.append(
                                f"<div class='epg-program epg-{media_class}{' epg-program-now' if is_now else ''}' "
                                f"style='left:{left:.1f}px;width:{width:.1f}px' title='{e(full_tip)}'>"
                                f"<div class='epg-program-title'>{e(title)}</div>"
                                f"<div class='epg-program-sub'>{e(sub) if sub else e(when)}</div>"
                                f"<div class='epg-program-time'>{e(when)}</div></div>"
                            )
                    cursor=actual_end
                    current_off=0.0
                    if cursor>=guide_end:
                        break
            else:
                row_note="<div class='epg-empty'>No playable media</div>"
        except StopIteration:
            pass
        except Exception as ex:
            row_note=f"<div class='epg-empty'>Guide unavailable: {e(ex)}</div>"

        watch=f"/watch/channel/{quote(str(c['number']),safe='')}"
        rows.append(
            "<div class='epg-row'>"
            f"<div class='epg-channel'><div class='epg-channel-number'>{e(c['number'])}</div>"
            f"<div class='epg-channel-main'><div class='epg-channel-name'>{e(c['name'])}</div>"
            f"<a class='epg-watch' href='{watch}'>▶ Watch</a></div></div>"
            f"<div class='epg-track' style='width:{timeline_width}px;--slot:{slot_width:.2f}px'>{''.join(blocks)}{row_note}</div>"
            "</div>"
        )

    # Imported Pluto channels use Pluto's real guide timeline.
    if pluto_channels:
        with db() as conn:
            for pch in pluto_channels:
                blocks=[]
                prows=conn.execute(
                    'SELECT * FROM pluto_epg WHERE channel_id=? AND stop_utc>? AND start_utc<? ORDER BY start_utc',
                    (pch['id'],guide_start.astimezone(timezone.utc).isoformat(),guide_end.astimezone(timezone.utc).isoformat())
                ).fetchall()
                for pr in prows:
                    ps=_parse_pluto_iso(pr['start_utc']); pe=_parse_pluto_iso(pr['stop_utc'])
                    if not ps or not pe:
                        continue
                    prog_start=ps.astimezone(guide_start.tzinfo); prog_end=pe.astimezone(guide_start.tzinfo)
                    visible_start=max(prog_start,guide_start); visible_end=min(prog_end,guide_end)
                    left=max(0.0,(visible_start-guide_start).total_seconds()/60.0*px_per_min)
                    width=max(3.0,(visible_end-visible_start).total_seconds()/60.0*px_per_min)
                    title=str(pr['title'] or 'Pluto TV'); sub=str(pr['subtitle'] or '')
                    when=f"{prog_start.strftime('%H:%M')}–{prog_end.strftime('%H:%M')}"
                    is_now=(prog_start<=now<prog_end)
                    ptype=(str(pr['program_type'] or '')+' '+str(pr['category'] or '')).lower()
                    media_class='movie' if any(x in ptype for x in ('movie','film','cinema')) else ('youtube' if 'youtube' in ptype else 'tv')
                    full_tip=f"{title}"+(f" — {sub}" if sub else '')+f" ({when})"
                    blocks.append(
                        f"<div class='epg-program epg-{media_class}{' epg-program-now' if is_now else ''}' "
                        f"style='left:{left:.1f}px;width:{width:.1f}px' title='{e(full_tip)}'>"
                        f"<div class='epg-program-title'>{e(title)}</div>"
                        f"<div class='epg-program-sub'>{e(sub) if sub else e(when)}</div>"
                        f"<div class='epg-program-time'>{e(when)}</div></div>"
                    )
                row_note='' if blocks else "<div class='epg-empty'>Pluto guide data pending sync</div>"
                watch=f"/watch/pluto/{quote(str(pch['id']),safe='')}"
                rows.append(
                    "<div class='epg-row'>"
                    f"<div class='epg-channel'><div class='epg-channel-number'>{e(pch['display_number'])}</div>"
                    f"<div class='epg-channel-main'><div class='epg-channel-name'>{e(pch['name'])}</div>"
                    f"<a class='epg-watch' href='{watch}'>▶ Watch</a></div></div>"
                    f"<div class='epg-track' style='width:{timeline_width}px;--slot:{slot_width:.2f}px'>{''.join(blocks)}{row_note}</div>"
                    "</div>"
                )

    # User-managed M3U8 channels do not have an external EPG unless the
    # user later supplies one, so render a truthful continuous "Live Stream"
    # block for the visible window. Channel/logo metadata is still emitted in
    # XMLTV so Kodi lists the station normally.
    for ls in live_streams:
        left=0.0; width=max(3.0,(guide_end-guide_start).total_seconds()/60.0*px_per_min)
        group=(str(ls['group_name'] or '')+' '+str(ls['name'] or '')).lower()
        media_class='youtube' if 'youtube' in group else ('movie' if any(x in group for x in ('movie','film','cinema')) else 'tv')
        watch=f"/watch/live/{int(ls['id'])}"
        block=(f"<div class='epg-program epg-{media_class}' style='left:{left:.1f}px;width:{width:.1f}px' title='{e(str(ls['name']))} — Live Stream'>"
               f"<div class='epg-program-title'>{e(ls['name'])}</div><div class='epg-program-sub'>Live Stream</div></div>")
        rows.append(
            "<div class='epg-row'>"
            f"<div class='epg-channel'><div class='epg-channel-number'>{e(ls['number'])}</div>"
            f"<div class='epg-channel-main'><div class='epg-channel-name'>{e(ls['name'])}</div>"
            f"<a class='epg-watch' href='{watch}'>▶ Watch</a></div></div>"
            f"<div class='epg-track' style='width:{timeline_width}px;--slot:{slot_width:.2f}px'>{block}</div>"
            "</div>"
        )

    now_marker=''
    if guide_start<=now<=guide_end:
        now_left=(now-guide_start).total_seconds()/60.0*px_per_min
        now_marker=f"<div class='epg-now-line' style='left:calc(220px + {now_left:.1f}px)'><span>NOW</span></div>"

    back_offset=offset-3
    next_offset=offset+3
    window_buttons=' '.join(
        f"<a class='button {'secondary' if h!=hours else ''}' href='/guide?hours={h}&offset={offset}'>{label}</a>"
        for h,label in ((6,'6 hours'),(12,'12 hours'),(24,'24 hours'),(168,'7 days'))
    )
    actions=(
        f"<a class='button secondary' href='/guide?hours={hours}&offset={back_offset}'>← 3h</a> "
        f"<a class='button' href='/guide?hours={hours}&offset=0'>Now</a> "
        f"<a class='button secondary' href='/guide?hours={hours}&offset={next_offset}'>3h →</a>"
    )
    heading=_page_heading('Guide','Live programme grid for ViperTV, Pluto TV and manual Live IPTV channels.',actions)
    summary=(
        "<div class='card epg-toolbar'><div><b>Guide window</b><div class='muted small'>"
        f"{e(guide_start.strftime('%a %b %d, %H:%M'))} – {e(guide_end.strftime('%a %b %d, %H:%M %Z'))}"
        "</div></div><div class='epg-legend' aria-label='Guide colours'>"
        "<span><i class='epg-swatch epg-swatch-movie'></i>Movies</span>"
        "<span><i class='epg-swatch epg-swatch-tv'></i>TV</span>"
        "<span><i class='epg-swatch epg-swatch-youtube'></i>YouTube</span>"
        "</div><div class='toolbar'>"+window_buttons+"</div></div>"
    )
    if not channels and not pluto_channels and not live_streams:
        body=heading+summary+"<div class='card empty'>No enabled channels. Create a ViperTV channel, import Pluto TV, or add a Live IPTV stream to populate the guide.</div>"
    else:
        body=(heading+summary+
            "<div class='epg-shell'><div class='epg-scroll' id='epgScroll'>"
            f"<div class='epg-board' style='width:{220+timeline_width}px'>{now_marker}"
            "<div class='epg-header'>"
            "<div class='epg-corner'>CHANNEL</div>"
            f"<div class='epg-time-track' style='width:{timeline_width}px;--slot:{slot_width:.2f}px'>{''.join(labels)}</div></div>"
            +''.join(rows)+"</div></div></div>"
        )

    extra_head=f"""<style>
.epg-toolbar{{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:12px 14px}}
.epg-shell{{border:1px solid var(--line);border-radius:6px;background:#11161b;box-shadow:var(--shadow);overflow:hidden}}
.epg-scroll{{overflow:auto;max-height:calc(100vh - 230px);min-height:330px;position:relative;scrollbar-color:#46515c #171c21}}
.epg-board{{position:relative;min-width:100%}}
.epg-header,.epg-row{{display:grid;grid-template-columns:220px 1fr}}
.epg-header{{position:sticky;top:0;z-index:30;height:54px;background:#151a1f;border-bottom:1px solid #3b434b}}
.epg-corner{{position:sticky;left:0;z-index:34;display:flex;align-items:center;padding:0 14px;background:#171c21;border-right:1px solid #3b434b;color:#aeb7c0;font-size:11px;font-weight:800;letter-spacing:.08em}}
.epg-time-track{{position:relative;height:54px;background-color:#171c21;background-image:repeating-linear-gradient(to right,#3a424a 0,#3a424a 1px,transparent 1px,transparent var(--slot))}}
.epg-time{{position:absolute;top:0;height:54px;padding:19px 0 0 7px;border-left:1px solid #3a424a;color:#dde1e5;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}}
.epg-day{{position:absolute;top:4px;left:7px;color:#88939d;font-size:10px;font-weight:700;text-transform:uppercase}}
.epg-row{{height:68px;border-bottom:1px solid #2e353c}}
.epg-row:last-child{{border-bottom:0}}
.epg-channel{{position:sticky;left:0;z-index:20;display:flex;align-items:center;gap:10px;padding:8px 10px;background:#1a2026;border-right:1px solid #3b434b;box-shadow:4px 0 8px rgba(0,0,0,.16)}}
.epg-channel-number{{min-width:42px;height:42px;border-radius:5px;background:#263039;display:flex;align-items:center;justify-content:center;color:#8ee0b1;font-size:16px;font-weight:800}}
.epg-channel-main{{min-width:0}}
.epg-channel-name{{font-weight:700;color:#f1f3f4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px}}
.epg-watch{{display:inline-block;margin-top:4px;color:#83c5ff;font-size:11px}}
.epg-track{{position:relative;height:68px;background-color:#12171c;background-image:repeating-linear-gradient(to right,#2d343b 0,#2d343b 1px,transparent 1px,transparent var(--slot))}}
.epg-program{{position:absolute;top:4px;height:60px;border:1px solid #4b5661;border-radius:5px;background:#26313a;padding:7px 8px;overflow:hidden;color:#f5f7f8;box-shadow:0 1px 2px rgba(0,0,0,.28)}}
.epg-program.epg-movie{{background:#661f28;border-color:#b74752}}
.epg-program.epg-movie:hover{{background:#7b2732;border-color:#dc6972;z-index:8}}
.epg-program.epg-tv{{background:#1f5b35;border-color:#449566}}
.epg-program.epg-tv:hover{{background:#287244;border-color:#69bd86;z-index:8}}
.epg-program.epg-youtube{{background:#1c4f82;border-color:#4388cb}}
.epg-program.epg-youtube:hover{{background:#2466a5;border-color:#6eace7;z-index:8}}
.epg-program-now{{border-color:#f0d35b!important;box-shadow:inset 4px 0 0 #f0d35b,0 1px 2px rgba(0,0,0,.28)}}
.epg-program-title{{font-size:12px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.epg-program-sub{{margin-top:2px;color:#e0e5e9;font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.epg-program-time{{margin-top:2px;color:#c2ccd4;font-size:9px;white-space:nowrap}}
.epg-legend{{display:flex;align-items:center;gap:14px;flex-wrap:wrap;color:#c4ccd3;font-size:11px;font-weight:700}}
.epg-legend span{{display:inline-flex;align-items:center;gap:5px}}
.epg-swatch{{display:inline-block;width:12px;height:12px;border-radius:3px;border:1px solid rgba(255,255,255,.28)}}
.epg-swatch-movie{{background:#b52e3b}}
.epg-swatch-tv{{background:#2f8c50}}
.epg-swatch-youtube{{background:#287bc1}}
.epg-empty{{position:absolute;left:12px;top:23px;color:#7f8993;font-size:12px}}
.epg-now-line{{position:absolute;top:0;bottom:0;width:2px;background:#f25f5c;z-index:29;pointer-events:none;box-shadow:0 0 5px rgba(242,95,92,.45)}}
.epg-now-line span{{position:sticky;top:3px;display:block;transform:translateX(-15px);width:32px;text-align:center;background:#f25f5c;color:white;border-radius:3px;padding:2px 3px;font-size:9px;font-weight:900;letter-spacing:.04em}}
@media(max-width:850px){{.epg-header,.epg-row{{grid-template-columns:165px 1fr}}.epg-channel-name{{max-width:92px}}.epg-now-line{{display:none}}}}
</style>"""
    extra_script="""<script>
(function(){
 const sc=document.getElementById('epgScroll');
 if(!sc)return;
 // Keep the top-left channel corner visually locked during horizontal scroll.
 // Native sticky positioning does the real work; this only restores the user's
 // scroll position when navigating back from Watch.
 const key='vipertv-guide-scroll';
 try{const old=sessionStorage.getItem(key);if(old)sc.scrollLeft=parseInt(old,10)||0;}catch(e){}
 sc.addEventListener('scroll',()=>{try{sessionStorage.setItem(key,String(sc.scrollLeft))}catch(e){}},{passive:true});
})();
</script>"""
    return page_shell('Guide',body,extra_head=extra_head,extra_script=extra_script)

# ---------------- HDHomeRun emulation ----------------------------------------
@app.get('/discover.json')
def hdhr_discover(request:Request):
    url=base_url(request)
    return {'FriendlyName':'ViperTV','Manufacturer':'ViperTV','ModelNumber':'VTV-1','FirmwareName':'vipertv','FirmwareVersion':APP_VERSION,'DeviceID':'V1PER001','DeviceAuth':'vipertv','BaseURL':url,'LineupURL':url+'/lineup.json','TunerCount':8}

@app.get('/lineup_status.json')
def hdhr_status():return {'ScanInProgress':0,'ScanPossible':1,'Source':'Cable','SourceList':['Cable']}

@app.get('/lineup.json')
def hdhr_lineup(request:Request):
    url=base_url(request)
    with db() as conn:cs=conn.execute('SELECT * FROM channels WHERE enabled=1 ORDER BY CAST(number AS REAL),number').fetchall()
    return [{'GuideNumber':c['number'],'GuideName':c['name'],'URL':channel_stream_url(url,c['number'])} for c in cs]

# ---------------- Backup / restore / integrity -------------------------------
@app.get('/maintenance',response_class=HTMLResponse)
def maintenance_page(msg:str=''):
    primary=sorted(BACKUP_DIR.glob('vipertv-*.db'),reverse=True)[:20]
    with db() as conn:integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
    rows=''.join(f"<tr><td>{e(x.name)}</td><td>{x.stat().st_size:,}</td><td><a href='/maintenance/download/{quote(x.name)}'>Download</a> <form class='inline' method='post' action='/maintenance/restore/{quote(x.name)}' onsubmit=\"return confirm('Restore this database? Current DB is backed up first.');\"><button class='danger'>Restore</button></form></td></tr>" for x in primary)
    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '')+f"<div class='card'><h2>Disaster Recovery</h2><p>Integrity: <span class='badge'>{e(integrity)}</span></p><form class='inline' method='post' action='/maintenance/backup'><button>Backup Now</button></form> <a class='button secondary' href='/maintenance/download-live'>Download Complete Database</a><h3>Restore uploaded database</h3><form method='post' action='/maintenance/upload-restore' enctype='multipart/form-data'><input type='file' name='file' accept='.db' required><button class='danger'>Upload & Restore</button></form><h3>Rolling backups</h3><table><tr><th>Backup</th><th>Bytes</th><th></th></tr>{rows}</table><p>Live DB: <code>{e(DB_PATH)}</code><br>Primary backups: <code>{e(BACKUP_DIR)}</code><br>Secondary: <code>{e(SECONDARY_BACKUP_DIR)}</code></p></div>"
    return page_shell('Backup & Restore',body)

@app.get('/maintenance/download-live')
def maintenance_download_live():
    backup_all('download-live');return FileResponse(DB_PATH,filename='vipertv-live.db',media_type='application/octet-stream')

@app.get('/maintenance/download/{name}')
def maintenance_download(name:str):
    p=BACKUP_DIR/Path(name).name
    if not p.exists():raise HTTPException(404)
    return FileResponse(p,filename=p.name,media_type='application/octet-stream')

@app.post('/maintenance/restore/{name}')
def maintenance_restore(name:str):
    src=BACKUP_DIR/Path(name).name
    if not src.exists():raise HTTPException(404)
    backup_all('before-restore')
    srcconn=sqlite3.connect(src);dst=sqlite3.connect(DB_PATH)
    try:srcconn.backup(dst)
    finally:srcconn.close();dst.close()
    return RedirectResponse('/maintenance?msg=Database+restored',303)

@app.post('/maintenance/upload-restore')
async def maintenance_upload_restore(file:UploadFile=File(...)):
    raw=await file.read()
    temp=DATA_DIR/'restore-upload.db';temp.write_bytes(raw)
    test=sqlite3.connect(temp)
    try:
        ok=test.execute('PRAGMA integrity_check').fetchone()[0]
        if ok!='ok':raise ValueError(ok)
    finally:test.close()
    backup_all('before-upload-restore');src=sqlite3.connect(temp);dst=sqlite3.connect(DB_PATH)
    try:src.backup(dst)
    finally:src.close();dst.close();temp.unlink(missing_ok=True)
    return RedirectResponse('/maintenance?msg=Uploaded+database+restored',303)

# ---------------- Hardware acceleration management (v1.2.5) ------------------
def _run_diag(args: list[str], timeout: int = 8) -> tuple[int, str]:
    """Compatibility helper retained for older diagnostics callers."""
    try:
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, timeout=timeout, env=os.environ.copy())
        return cp.returncode, (cp.stdout or "")[-12000:]
    except Exception as exc:
        return 999, str(exc)


def _hardware_profile_options(selected: str, include_global: bool = True) -> str:
    choices = []
    if include_global:
        choices.append(("global", "Use Global Default"))
    choices += [
        ("auto", "Auto Detect Best Hardware"),
        ("software", "Software (libx264)"),
        ("vaapi", "VAAPI (Intel / AMD)"),
        ("qsv", "Intel Quick Sync (QSV)"),
        ("nvenc", "NVIDIA NVENC"),
        ("direct", "Direct / Copy (no video transcode)"),
    ]
    return ''.join(f"<option value='{e(v)}' {'selected' if selected==v else ''}>{e(label)}</option>" for v,label in choices)


def _hardware_status_payload() -> dict[str, Any]:
    preferred = hardware_preferred_vaapi_device() or None
    st = hwaccel.status(preferred)
    st['global_profile'] = hardware_global_profile()
    st['fallback_enabled'] = hardware_fallback_enabled()
    return st


@app.get('/api/hardware/status', response_class=JSONResponse)
def hardware_status_api():
    st = _hardware_status_payload()
    # Keep the API concise; raw vainfo is available on the HTML diagnostics page.
    return JSONResponse({
        'version': APP_VERSION,
        'global_profile': st['global_profile'],
        'fallback_enabled': st['fallback_enabled'],
        'recommended': st['recommended'],
        'selected_vaapi_device': st['selected_vaapi_device'],
        'devices': st['devices'],
        'profiles': {k: st[k] for k in ('software','vaapi','qsv','nvenc')},
        'nvidia_visible': st['nvidia_visible'],
    })


@app.get('/system/hardware', response_class=HTMLResponse)
def hardware_acceleration_page(msg: str = ''):
    st = _hardware_status_payload()
    global_profile = st['global_profile']
    preferred = hardware_preferred_vaapi_device()
    fallback_checked = 'checked' if st['fallback_enabled'] else ''
    effective_global = global_profile
    if effective_global == 'auto':
        effective_global = st['recommended']
    prereq = st.get(effective_global) if effective_global in ('software','vaapi','qsv','nvenc') else {'available': True}
    global_ready = bool(prereq and prereq.get('available'))
    badge = "<span class='badge green'>READY</span>" if global_ready else "<span class='badge red'>FALLBACK / NOT READY</span>"

    device_rows = ''
    for d in st['devices']:
        selected = ' <b>(preferred)</b>' if d.get('render') == st.get('selected_vaapi_device') else ''
        device_rows += f"<tr><td>{e(d.get('vendor') or 'Unknown')}</td><td><code>{e(d.get('render') or '')}</code>{selected}</td><td>{e(d.get('card') or '')}</td><td>{e(d.get('vendor_id') or 'Unknown')}</td></tr>"
    if not device_rows:
        device_rows = "<tr><td colspan='4' class='empty'>No DRM render devices are visible inside this container.</td></tr>"

    profile_rows = ''
    for key,label in [('software','Software / libx264'),('vaapi','VAAPI — Intel / AMD'),('qsv','Intel Quick Sync'),('nvenc','NVIDIA NVENC')]:
        x=st[key]; ok=bool(x.get('available'))
        b="<span class='badge green'>AVAILABLE</span>" if ok else "<span class='badge red'>UNAVAILABLE</span>"
        test = f"<form class='inline' method='post' action='/system/hardware/test'><input type='hidden' name='profile' value='{key}'><button class='secondary' {'disabled' if not ok else ''}>Test</button></form>"
        profile_rows += f"<tr><td><b>{e(label)}</b></td><td>{b}</td><td>{e(x.get('encoder') or '')}</td><td>{e(x.get('device') or '')}</td><td>{e(x.get('reason') or '')}</td><td>{test}</td></tr>"

    render_options = "<option value=''>Automatic</option>" + ''.join(
        f"<option value='{e(d['render'])}' {'selected' if preferred==d['render'] else ''}>{e(d.get('vendor') or 'Unknown')} — {e(d['render'])}</option>"
        for d in st['devices']
    )

    last_test_html = ''
    try:
        last = json.loads(get_setting('hardware_last_test_json','{}') or '{}')
    except Exception:
        last = {}
    if last:
        ok=bool(last.get('ok')); b="<span class='badge green'>PASSED</span>" if ok else "<span class='badge red'>FAILED</span>"
        last_test_html=f"""
<div class='card'><h2>Last Encoder Test {b}</h2>
<p><b>Profile:</b> {e(hwaccel.profile_label(str(last.get('profile') or '')))} &nbsp; <b>Time:</b> {e(last.get('tested_at') or '')} &nbsp; <b>Runtime:</b> {e(last.get('elapsed') or '')}s</p>
<pre style='white-space:pre-wrap;max-height:300px;overflow:auto'>{e(last.get('output') or '')}</pre></div>"""

    with db() as conn:
        channels=conn.execute("SELECT id,number,name,stream_profile FROM channels ORDER BY CAST(number AS REAL),number").fetchall()
    channel_rows=''
    for c in channels:
        effective,configured,warn=effective_stream_profile(c)
        channel_rows += f"""
<tr><td>{e(c['number'])}</td><td>{e(c['name'])}</td><td>
<form class='inline' method='post' action='/system/hardware/channel/{c['id']}'>
<select name='stream_profile'>{_hardware_profile_options(str(c['stream_profile'] or 'global'),True)}</select>
<button class='secondary'>Save</button></form></td>
<td>{e(hwaccel.profile_label(effective))}</td><td>{e(warn)}</td></tr>"""
    if not channel_rows:
        channel_rows="<tr><td colspan='5' class='empty'>No generated channels configured.</td></tr>"

    active_rows=''
    streams=globals().get('SHARED_CHANNEL_STREAMS',{})
    if isinstance(streams,dict):
        for cid,state in list(streams.items()):
            if not state.get('running'): continue
            with db() as conn:
                c=conn.execute('SELECT number,name FROM channels WHERE id=?',(cid,)).fetchone()
            name=f"{c['number']} {c['name']}" if c else str(cid)
            active_rows+=f"<tr><td>{e(name)}</td><td>{e(state.get('configured_profile') or '')}</td><td>{e(state.get('effective_profile') or '')}</td><td>{int(state.get('hardware_fallbacks') or 0)}</td><td>{e(state.get('hardware_fallback_reason') or '')}</td></tr>"
    if not active_rows:
        active_rows="<tr><td colspan='5' class='empty'>No generated channel is actively streaming right now.</td></tr>"

    body=(f"<div class='msg'>{e(msg)}</div>" if msg else '') + _page_heading(
        'Hardware Acceleration',
        'Detect, test and manage Intel, AMD and NVIDIA video encoding from one place.',
        badge,
    ) + f"""
<div class='grid'>
  <div class='card'><h2>Global Transcoding Default</h2>
    <form method='post' action='/system/hardware/settings'>
      <label>Default profile for channels set to “Use Global Default”</label>
      <select name='default_profile'>{_hardware_profile_options(global_profile,False)}</select>
      <label>Preferred VAAPI / QSV render device</label>
      <select name='vaapi_device'>{render_options}</select>
      <label style='display:block;margin-top:12px'><input type='checkbox' name='software_fallback' value='1' {fallback_checked}> Automatically fall back to software if the selected hardware encoder is unavailable or fails to initialize</label>
      <button>Save Hardware Settings</button>
    </form>
    <p><b>Auto Detect currently chooses:</b> {e(hwaccel.profile_label(st['recommended']))}</p>
    <form class='inline' method='post' action='/system/hardware/channels/use-global'><button class='secondary'>Set All Transcoding Channels To Global Default</button></form>
    <p class='muted small'>Direct/Copy channels are left unchanged by the bulk button. Changing a channel profile restarts its shared station producer so the new encoder is used on the next connection.</p>
  </div>
  <div class='card'><h2>Container Device Visibility</h2>
    <p><b>DRM render devices:</b> {len(st['devices'])}</p>
    <p><b>NVIDIA device nodes:</b> {'Visible' if st['nvidia_visible'] else 'Not visible'}</p>
    <p><b>vainfo on selected device:</b> {'OK' if st['vainfo_ok'] else 'Failed / unavailable'}</p>
    <p class='muted small'>Intel and AMD normally use <code>/dev/dri</code>. NVIDIA NVENC additionally requires the NVIDIA Container Toolkit/runtime to expose the GPU and driver libraries to this container. ViperTV will never silently rewrite your OMV Compose file.</p>
  </div>
</div>
<div class='card'><h2>Detected GPUs</h2><div class='table-wrap'><table><thead><tr><th>Vendor</th><th>Render node</th><th>Card</th><th>PCI vendor</th></tr></thead><tbody>{device_rows}</tbody></table></div></div>
<div class='card'><h2>Encoder Readiness</h2><div class='table-wrap'><table><thead><tr><th>Profile</th><th>Status</th><th>FFmpeg encoder</th><th>Device</th><th>Diagnostic</th><th></th></tr></thead><tbody>{profile_rows}</tbody></table></div></div>
{last_test_html}
<div class='card'><h2>Per-Channel Hardware Override</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Configured</th><th>Effective now</th><th>Fallback note</th></tr></thead><tbody>{channel_rows}</tbody></table></div></div>
<div class='card'><h2>Active Hardware Sessions</h2><div class='table-wrap'><table><thead><tr><th>Channel</th><th>Configured</th><th>Effective</th><th>Fallbacks</th><th>Last fallback reason</th></tr></thead><tbody>{active_rows}</tbody></table></div></div>
<div class='card'><h2>VAAPI Diagnostic</h2><pre style='white-space:pre-wrap;max-height:420px;overflow:auto'>{e(st['vainfo'])}</pre></div>
"""
    return page_shell('Hardware Acceleration', body)


@app.post('/system/hardware/settings')
def hardware_acceleration_settings(default_profile:str=Form('auto'),vaapi_device:str=Form(''),software_fallback:int=Form(0)):
    profile=default_profile.strip().lower()
    if profile not in {'auto','software','vaapi','qsv','nvenc','direct'}:
        return RedirectResponse('/system/hardware?msg='+quote('Invalid hardware profile.'),303)
    devices={d['render'] for d in hwaccel.discover_dri_devices()}
    vaapi_device=vaapi_device.strip()
    if vaapi_device and vaapi_device not in devices:
        return RedirectResponse('/system/hardware?msg='+quote('The selected render device is not visible in the container.'),303)
    safe_backup_before_change()
    set_setting('hardware_default_profile',profile)
    set_setting('hardware_vaapi_device',vaapi_device)
    set_setting('hardware_software_fallback','1' if software_fallback else '0')
    for cid,state in list(globals().get('SHARED_CHANNEL_STREAMS',{}).items()):
        try:
            with db() as conn:r=conn.execute('SELECT stream_profile FROM channels WHERE id=?',(cid,)).fetchone()
            if r and str(r['stream_profile'] or '') in {'global','auto'}: state['stop']=True
        except Exception: pass
    return RedirectResponse('/system/hardware?msg='+quote('Hardware acceleration settings saved.'),303)


@app.post('/system/hardware/test')
def hardware_acceleration_test(profile:str=Form(...)):
    profile=profile.strip().lower()
    result=hwaccel.test_profile(profile, hardware_preferred_vaapi_device() or None)
    result['tested_at']=utcnow_iso()
    set_setting('hardware_last_test_json',json.dumps(result))
    msg=f"{hwaccel.profile_label(profile)} test {'PASSED' if result.get('ok') else 'FAILED'}."
    return RedirectResponse('/system/hardware?msg='+quote(msg),303)


@app.post('/system/hardware/channels/use-global')
def hardware_channels_use_global():
    safe_backup_before_change()
    with db() as conn:
        cur=conn.execute("UPDATE channels SET stream_profile='global' WHERE stream_profile<>'direct'")
        conn.commit(); count=cur.rowcount
    for state in list(globals().get('SHARED_CHANNEL_STREAMS',{}).values()):
        state['stop']=True
    return RedirectResponse('/system/hardware?msg='+quote(f'{count} channel(s) now follow the global hardware profile.'),303)


@app.post('/system/hardware/channel/{channel_id}')
def hardware_channel_profile(channel_id:int,stream_profile:str=Form('global')):
    profile=stream_profile.strip().lower()
    if profile not in HARDWARE_STREAM_PROFILES:
        return RedirectResponse('/system/hardware?msg='+quote('Invalid channel hardware profile.'),303)
    safe_backup_before_change()
    with db() as conn:
        if not conn.execute('SELECT 1 FROM channels WHERE id=?',(channel_id,)).fetchone():
            raise HTTPException(404,'Channel not found')
        conn.execute('UPDATE channels SET stream_profile=? WHERE id=?',(profile,channel_id));conn.commit()
    _restart_shared_channel_if_running(channel_id)
    return RedirectResponse('/system/hardware?msg='+quote('Channel hardware profile saved.'),303)


# Compatibility routes retained for older bookmarks/buttons.
@app.post('/system/hardware/enable-vaapi')
def enable_vaapi_all_channels():
    safe_backup_before_change(); set_setting('hardware_default_profile','vaapi')
    with db() as conn:
        cur=conn.execute("UPDATE channels SET stream_profile='global' WHERE stream_profile IN ('software','vaapi','qsv','nvenc','auto','global')");conn.commit();count=cur.rowcount
    return RedirectResponse('/system/hardware?msg='+quote(f'VAAPI selected globally for {count} channel(s).'),303)


@app.post('/system/hardware/use-software')
def disable_vaapi_all_channels():
    safe_backup_before_change(); set_setting('hardware_default_profile','software')
    with db() as conn:
        cur=conn.execute("UPDATE channels SET stream_profile='global' WHERE stream_profile IN ('software','vaapi','qsv','nvenc','auto','global')");conn.commit();count=cur.rowcount
    return RedirectResponse('/system/hardware?msg='+quote(f'Software encoding selected globally for {count} channel(s).'),303)


# ---------------- Channel templates + external selection API -----------------
@app.post('/studio/channel/{channel_id}/template')
def save_channel_template(channel_id:int,name:str=Form(...)):
    with db() as conn:
        c=dict(conn.execute('SELECT * FROM channels WHERE id=?',(channel_id,)).fetchone());sels=[dict(r) for r in conn.execute('SELECT * FROM channel_selections WHERE channel_id=?',(channel_id,))];cols=[r['collection_id'] for r in conn.execute('SELECT collection_id FROM channel_collections WHERE channel_id=?',(channel_id,))]
        people_filter=conn.execute('SELECT actors_json,directors_json,air_year_start,air_year_end FROM channel_people_filters WHERE channel_id=?',(channel_id,)).fetchone()
        for x in sels:x.pop('id',None);x.pop('channel_id',None)
        cfg={'channel':{k:v for k,v in c.items() if k not in ('id','number','name','created_at')},'selections':sels,'collections':cols,'people_filter':dict(people_filter) if people_filter else None}
        conn.execute('INSERT OR REPLACE INTO channel_templates(name,config_json,created_at) VALUES(?,?,?)',(name,json.dumps(cfg),utcnow_iso()));conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Channel+template+saved',303)

@app.post('/studio/channel/{channel_id}/external/add')
def add_external_selection(channel_id:int,library_id:int=Form(...),show_title:str=Form(''),season_number:str=Form('')):
    with db() as conn:conn.execute('INSERT INTO external_channel_selections(channel_id,library_id,show_title,season_number) VALUES(?,?,?,?)',(channel_id,library_id,show_title or None,int(season_number) if season_number else None));conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=External+source+added',303)

# ---------------- HLS compatibility endpoint ---------------------------------
@app.get('/hls/{channel_id}/index.m3u8',response_class=PlainTextResponse)
def hls_master(channel_id:int,request:Request):
    # Standards-compatible master playlist that delegates to the continuous MPEG-TS endpoint.
    # Clients that insist on HLS can still discover the stream; native segment generation is planned for the next streaming core.
    url=base_url(request)
    return PlainTextResponse(f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:BANDWIDTH=6000000\n{url}/stream/{channel_id}.ts\n",media_type='application/vnd.apple.mpegurl')


@app.post('/studio/channel/{channel_id}/template/apply')
def apply_channel_template(channel_id:int,template_id:int=Form(...)):
    safe_backup_before_change()
    with db() as conn:
        t=conn.execute('SELECT * FROM channel_templates WHERE id=?',(template_id,)).fetchone()
        if not t:raise HTTPException(404,'Template not found')
        cfg=json.loads(t['config_json']); ch=cfg.get('channel',{})
        allowed=['library_id','shuffle','enabled','logo_path','watermark_enabled','subtitle_mode','offline_media','stream_profile','stream_mode','video_bitrate','resolution','frame_rate']
        vals=[ch.get(k) for k in allowed]
        conn.execute('UPDATE channels SET '+','.join(k+'=?' for k in allowed)+' WHERE id=?',vals+[channel_id])
        conn.execute('DELETE FROM channel_selections WHERE channel_id=?',(channel_id,));conn.execute('DELETE FROM channel_collections WHERE channel_id=?',(channel_id,));conn.execute('DELETE FROM channel_people_filters WHERE channel_id=?',(channel_id,))
        for x in cfg.get('selections',[]):
            conn.execute('INSERT INTO channel_selections(channel_id,source_type,library_id,plex_library_id,selection_type,show_key,show_title,season_number,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(channel_id,x.get('source_type'),x.get('library_id'),x.get('plex_library_id'),x.get('selection_type'),x.get('show_key'),x.get('show_title'),x.get('season_number'),utcnow_iso()))
        pf=cfg.get('people_filter')
        if pf:
            conn.execute('INSERT INTO channel_people_filters(channel_id,actors_json,directors_json,air_year_start,air_year_end,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(channel_id,pf.get('actors_json','[]'),pf.get('directors_json','[]'),pf.get('air_year_start'),pf.get('air_year_end'),utcnow_iso(),utcnow_iso()))
        for cid in cfg.get('collections',[]):conn.execute('INSERT OR IGNORE INTO channel_collections(channel_id,collection_id) VALUES(?,?)',(channel_id,cid))
        conn.commit()
    return RedirectResponse(f'/studio/channel/{channel_id}?msg=Channel+template+applied',303)


def _profiled_local_command(channel:sqlite3.Row,item:dict[str,Any],offset:float,profile_override:str|None=None)->list[str]:
    path=str(item.get('path') or channel['offline_media'] or '')
    if not path:return ['false']
    profile, _configured, _warning = effective_stream_profile(channel, profile_override)
    bitrate=channel['video_bitrate'] or VIDEO_BITRATE
    resolution=channel['resolution'] or '1920x1080'
    scale=resolution.replace('x',':')
    preferred=hardware_preferred_vaapi_device() or None
    prereq=hwaccel.profile_prerequisites(profile, preferred) if profile in {'vaapi','qsv','nvenc'} else {}
    base=['ffmpeg','-hide_banner','-loglevel','error']
    if profile=='vaapi':
        base += ['-vaapi_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
    elif profile=='qsv':
        base += ['-qsv_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
    base += ['-re','-ss',f'{max(offset,0):.3f}','-i',path]

    cpu_filters=[]
    if channel['subtitle_mode']=='burn' and item.get('subtitle_path'):
        sub=str(item['subtitle_path']).replace('\\','/').replace(':','\\:').replace("'","\\'")
        cpu_filters.append(f"subtitles='{sub}'")
    logo=channel['logo_path'] if channel['watermark_enabled'] else None
    has_logo=bool(logo and Path(str(logo)).exists())
    if has_logo:
        base += ['-i',str(logo)]

    # Direct/copy cannot be combined with video filters.  Preserve the user's
    # content presentation by transcoding filtered direct channels in software.
    if profile=='direct' and (cpu_filters or has_logo):
        profile='software'

    post=[]
    if profile=='vaapi': post=[f'scale={scale}','format=nv12','hwupload']
    elif profile=='qsv': post=[f'scale={scale}','format=nv12']
    elif profile=='nvenc': post=[f'scale={scale}','format=yuv420p']
    elif profile=='software': post=[f'scale={scale}']

    if has_logo:
        chains=[]; vin='[0:v]'
        if cpu_filters:
            chains.append(f"{vin}{','.join(cpu_filters)}[vbase]"); vin='[vbase]'
        chains.append(f"{vin}[1:v]overlay=W-w-24:24[vlogo]")
        if post:
            chains.append(f"[vlogo]{','.join(post)}[vout]")
        else:
            chains.append('[vlogo]null[vout]')
        base += ['-filter_complex',';'.join(chains),'-map','[vout]','-map','0:a:0?']
    else:
        base += ['-map','0:v:0?','-map','0:a:0?']
        filters=cpu_filters+post
        if filters:base += ['-vf',','.join(filters)]

    if profile=='direct':
        base += ['-c','copy']
    elif profile=='qsv':
        base += ['-c:v','h264_qsv','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    elif profile=='vaapi':
        base += ['-c:v','h264_vaapi','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    elif profile=='nvenc':
        base += ['-c:v','h264_nvenc','-preset','p4','-tune','ll','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    else:
        base += ['-c:v','libx264','-preset',TRANSCODE_PRESET,'-pix_fmt','yuv420p','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE,'-ar','48000']
    if channel['frame_rate']:base += ['-r',str(channel['frame_rate'])]
    base += ['-sn','-dn','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
    return base


def _external_stream_url(item:dict[str,Any])->str:
    base=str(item.get('base_url') or '').rstrip('/'); ext=str(item.get('external_id') or ''); key=str(item.get('api_key') or '')
    return f"{base}/Videos/{quote(ext)}/stream?static=true&api_key={quote(key)}"


def _profiled_external_command(channel:sqlite3.Row,item:dict[str,Any],offset:float)->list[str]:
    url=_external_stream_url(item)
    return ['ffmpeg','-hide_banner','-loglevel','error','-re','-ss',f'{max(offset,0):.3f}','-i',url,'-map','0:v:0?','-map','0:a:0?','-c','copy','-sn','-dn','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']


def _profiled_gap_command(channel:sqlite3.Row,item:dict[str,Any],offset:float)->list[str]:
    remaining=max(1.0,float(item.get('duration') or 1.0)-max(0.0,float(offset or 0.0)))
    resolution=str(channel['resolution'] or '1920x1080') if 'resolution' in channel.keys() else '1920x1080'
    return ['ffmpeg','-hide_banner','-loglevel','error','-re','-f','lavfi','-i',f'color=c=black:s={resolution}:r=30','-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',f'{remaining:.3f}','-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset',TRANSCODE_PRESET,'-pix_fmt','yuv420p','-c:a','aac','-b:a',AUDIO_BITRATE,'-shortest','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']


def _limit_station_command(cmd:list[str],seconds:float|None)->list[str]:
    if not seconds or seconds<=0:return cmd
    out=list(cmd);insert_at=None
    for i in range(len(out)-1):
        if out[i]=='-f' and out[i+1]=='mpegts':insert_at=i
    if insert_at is not None:out[insert_at:insert_at]=['-t',f'{float(seconds):.3f}']
    return out


def _scheduled_cursor(channel_id:int)->tuple[str|None,int]:
    classic=_classic_assignment(channel_id)
    if classic:
        key=f"classic:{classic['schedule_id']}:{classic['generation']}"
        with db() as conn:r=conn.execute('SELECT cursor FROM playout_state WHERE channel_id=? AND source_key=?',(channel_id,key)).fetchone()
        return key,int(r['cursor']) if r else 0
    sched=_active_schedule_source(channel_id)
    if not sched:return None,0
    key=f"schedule:{sched['id']}"
    with db() as conn:r=conn.execute('SELECT cursor FROM playout_state WHERE channel_id=? AND source_key=?',(channel_id,key)).fetchone()
    return key,int(r['cursor']) if r else 0


def _set_playout_cursor(channel_id:int,key:str|None,cursor:int)->None:
    if not key:return
    try:
        with db() as conn:
            conn.execute('INSERT INTO playout_state(channel_id,source_key,cursor,updated_at) VALUES(?,?,?,?) ON CONFLICT(channel_id,source_key) DO UPDATE SET cursor=excluded.cursor,updated_at=excluded.updated_at',(channel_id,key,cursor,utcnow_iso()));conn.commit()
    except Exception:pass

# Re-wrap channel_media so a scheduled collection resumes from its persisted episode cursor.
V1_CHANNEL_MEDIA=channel_media

def channel_media(channel_id:int)->tuple[sqlite3.Row,list[dict[str,Any]]]:
    ch,items=V1_CHANNEL_MEDIA(channel_id)
    classic=_classic_day_items(channel_id)
    if classic:
        return ch,classic
    sched=_active_schedule_source(channel_id)
    key,cursor=_scheduled_cursor(channel_id)
    if sched and items:
        mode=sched['mode'] or 'sequential'
        if mode in ('shuffle','random'):
            day=datetime.now().astimezone().date().isoformat()
            items.sort(key=lambda x:hashlib.sha256(f"{day}|{sched['id']}|{x.get('source_type')}|{x.get('id')}|{x.get('rating_key')}|{x.get('external_id')}".encode()).hexdigest())
        if cursor:
            n=cursor%len(items);items=items[n:]+items[:n]
    return ch,items


async def stream_channel(channel_id:int):
    channel,items=channel_media(channel_id)
    if not items:
        offline=channel['offline_media'] if 'offline_media' in channel.keys() else None
        if offline and Path(str(offline)).exists():items=[{'source_type':'local','path':offline,'duration':3600,'title':'Offline'}]
        else:return
    idx,offset,_=locate_at(items,datetime.now(timezone.utc)); current_idx=idx; first_offset=offset; proc=None; state_key,state_cursor=_scheduled_cursor(channel_id)
    try:
        while True:
            item=items[current_idx]
            if item['source_type']=='plex':cmd=plex_ffmpeg_command(item,first_offset)
            elif item['source_type']=='external':cmd=_profiled_external_command(channel,item,first_offset)
            else:cmd=_profiled_local_command(channel,item,first_offset)
            first_offset=0.0
            proc=await asyncio.create_subprocess_exec(*cmd,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
            assert proc.stdout is not None
            while True:
                chunk=await proc.stdout.read(64*1024)
                if not chunk:break
                yield chunk
            await proc.wait()
            if proc.returncode not in (0,255):
                try:
                    err=await proc.stderr.read() if proc.stderr else b''; text=err.decode(errors='ignore')[-2000:];text=re.sub(r'(X-Plex-Token|api_key)=[^&\\s]+',r'\1=REDACTED',text);print(f'ffmpeg channel {channel_id}: {text}',flush=True)
                except Exception:pass
            proc=None;current_idx=(current_idx+1)%len(items)
            if state_key:_set_playout_cursor(channel_id,state_key,state_cursor+1);state_cursor+=1
    except (asyncio.CancelledError,GeneratorExit):raise
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            try:await proc.wait()
            except Exception:pass



# ---------------- Plex direct-part streaming (v1.1.22) ----------------------
# Plex's documented media-part endpoint is a better station source than the
# universal-transcoder HLS endpoint.  Resolve the media Part once per item and
# let the single shared ViperTV producer read that source directly.
PLEX_PART_SOURCE_CACHE: dict[str, tuple[str, str]] = {}

def _plex_part_cache_key(item: dict[str, Any]) -> str:
    return f"{item.get('plex_library_id')}:{item.get('plex_key')}"

def _plex_direct_part_source(item: dict[str, Any]) -> tuple[str, str]:
    key = _plex_part_cache_key(item)
    cached = PLEX_PART_SOURCE_CACHE.get(key)
    if cached:
        return cached
    with db() as conn:
        server = conn.execute(
            """SELECT ps.* FROM plex_servers ps
               JOIN plex_libraries pl ON pl.server_id=ps.id
               WHERE pl.id=?""",
            (item['plex_library_id'],),
        ).fetchone()
    if not server:
        raise RuntimeError('Plex server for media item no longer exists')
    root = plex_request_xml(server, str(item['plex_key']), {'includeMedia': 1}, timeout=30)
    part = next((el for el in root.iter() if el.tag.lower().endswith('part') and el.attrib.get('key')), None)
    if part is None:
        raise RuntimeError('Plex metadata did not include a playable Media Part key')
    part_key = str(part.attrib.get('key') or '')
    if not part_key:
        raise RuntimeError('Plex Media Part key is empty')
    if part_key.startswith('http://') or part_key.startswith('https://'):
        url = part_key
    else:
        url = str(server['base_url']).rstrip('/') + ('/' if not part_key.startswith('/') else '') + part_key
    headers = (
        f"X-Plex-Token: {server['token']}\r\n"
        f"X-Plex-Product: {APP_NAME}\r\n"
        f"X-Plex-Version: {APP_VERSION}\r\n"
        f"X-Plex-Client-Identifier: vipertv-server\r\n"
    )
    result = (url, headers)
    PLEX_PART_SOURCE_CACHE[key] = result
    return result

def _profiled_plex_part_command(channel: sqlite3.Row, item: dict[str, Any], offset: float, url: str, headers: str, profile_override: str|None=None) -> list[str]:
    profile, _configured, _warning = effective_stream_profile(channel, profile_override)
    bitrate = channel['video_bitrate'] or VIDEO_BITRATE
    resolution = channel['resolution'] or '1920x1080'
    scale = resolution.replace('x',':')
    preferred=hardware_preferred_vaapi_device() or None
    prereq=hwaccel.profile_prerequisites(profile, preferred) if profile in {'vaapi','qsv','nvenc'} else {}
    base = ['ffmpeg','-hide_banner','-loglevel','error']
    if profile == 'vaapi':
        base += ['-vaapi_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
    elif profile == 'qsv':
        base += ['-qsv_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
    base += ['-re','-ss',f'{max(offset,0):.3f}','-headers',headers,'-i',url]
    base += ['-map','0:v:0?','-map','0:a:0?']
    if profile == 'direct':
        base += ['-c','copy']
    elif profile == 'qsv':
        base += ['-vf',f'scale={scale},format=nv12','-c:v','h264_qsv','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    elif profile == 'vaapi':
        base += ['-vf',f'scale={scale},format=nv12,hwupload','-c:v','h264_vaapi','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    elif profile == 'nvenc':
        base += ['-vf',f'scale={scale},format=yuv420p','-c:v','h264_nvenc','-preset','p4','-tune','ll','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE]
    else:
        base += ['-c:v','libx264','-preset',TRANSCODE_PRESET,'-s',resolution,'-pix_fmt','yuv420p','-b:v',bitrate,'-c:a','aac','-b:a',AUDIO_BITRATE,'-ar','48000']
    if channel['frame_rate']:
        base += ['-r',str(channel['frame_rate'])]
    base += ['-sn','-dn','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
    return base


# ---------------- Shared live channel core (v1.1.22) ------------------------
# A channel is a station, not a per-viewer transcode.  The first viewer starts
# one source FFmpeg process and every additional Kodi/browser client receives a
# copy of that same live MPEG-TS output.  This prevents Watch + Kodi (and two
# Kodi clients) from starting competing hardware/Plex transcodes.
SHARED_CHANNEL_STREAMS: dict[int, dict[str, Any]] = {}
SHARED_CHANNEL_GRACE_SECONDS = float(os.getenv("VIPERTV_SHARED_STREAM_GRACE_SECONDS", "15"))
SHARED_CHANNEL_QUEUE_CHUNKS = LIVE_CLIENT_QUEUE_CHUNKS


def _shared_stream_label(channel_id: int) -> str:
    try:
        with db() as conn:
            row = conn.execute("SELECT number,name FROM channels WHERE id=?", (channel_id,)).fetchone()
        if row:
            return f"{row['number']} {row['name']}"
    except Exception:
        pass
    return str(channel_id)


async def _shared_channel_producer(channel_id: int, state: dict[str, Any]) -> None:
    channel, items = channel_media(channel_id)
    if not items:
        offline = channel['offline_media'] if 'offline_media' in channel.keys() else None
        if offline and Path(str(offline)).exists():
            items = [{'source_type':'local','path':offline,'duration':3600,'title':'Offline'}]
        else:
            state['error'] = 'Channel has no playable media'
            return

    idx, offset, _ = locate_at(items, datetime.now(timezone.utc))
    current_idx = idx
    first_offset = offset
    state_key, state_cursor = _scheduled_cursor(channel_id)
    proc: asyncio.subprocess.Process | None = None
    label = _shared_stream_label(channel_id)
    state['started_at'] = time.time()
    state['error'] = ''
    print(f"shared channel producer started: channel={label}", flush=True)

    try:
        while not state.get('stop'):
            # If everybody left, keep the station warm briefly so a browser HLS
            # reconnect or a Kodi channel change does not immediately respawn FFmpeg.
            if not state['subscribers']:
                empty_since = state.get('empty_since') or time.time()
                state['empty_since'] = empty_since
                if time.time() - float(empty_since) >= SHARED_CHANNEL_GRACE_SECONDS:
                    break
            else:
                state['empty_since'] = None

            item = items[current_idx]
            if item['source_type'] == 'plex':
                try:
                    part_url, plex_headers = await asyncio.to_thread(_plex_direct_part_source, item)
                    cmd = _profiled_plex_part_command(channel, item, first_offset, part_url, plex_headers)
                    state['source_mode'] = 'plex-direct-part'
                    state['source_warning'] = ''
                except Exception as exc:
                    # Compatibility fallback for unusual Plex items that do not expose Media/Part.
                    cmd = plex_ffmpeg_command(item, first_offset)
                    state['source_mode'] = 'plex-universal-fallback'
                    state['source_warning'] = str(exc)[:300]
            elif item['source_type'] == 'external':
                state['source_mode'] = 'external-direct'
                cmd = _profiled_external_command(channel, item, first_offset)
            else:
                state['source_mode'] = 'local'
                cmd = _profiled_local_command(channel, item, first_offset)
            _src_title, _src_subtitle = _preview_item_label(item)
            state['source_item'] = f"{_src_title} — {_src_subtitle}" if _src_subtitle else _src_title
            first_offset = 0.0
            produced_bytes = 0

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            state['proc'] = proc
            state['item_index'] = current_idx
            assert proc.stdout is not None

            while not state.get('stop'):
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break

                # Fan one station output to every viewer.  A slow/dead viewer must
                # never stall the station; drop its oldest queued chunk instead.
                for q in list(state['subscribers']):
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        try:
                            q.get_nowait()
                        except Exception:
                            pass
                        try:
                            q.put_nowait(chunk)
                        except Exception:
                            pass

                if not state['subscribers']:
                    empty_since = state.get('empty_since') or time.time()
                    state['empty_since'] = empty_since
                    if time.time() - float(empty_since) >= SHARED_CHANNEL_GRACE_SECONDS:
                        state['stop'] = True
                        break
                else:
                    state['empty_since'] = None

            if proc.returncode is None and state.get('stop'):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=4)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            state['last_return_code'] = proc.returncode
            state['last_item_bytes'] = produced_bytes
            if proc.returncode not in (0, 255, -15) and not state.get('stop'):
                try:
                    err = await proc.stderr.read() if proc.stderr else b''
                    text = err.decode(errors='ignore')[-2000:]
                    text = re.sub(r'(X-Plex-Token|api_key)=[^&\\s]+', r'\1=REDACTED', text)
                    state['error'] = text
                    print(f"shared ffmpeg channel {channel_id}: {text}", flush=True)
                except Exception:
                    pass

            state['proc'] = None
            proc = None
            if state.get('stop'):
                break

            current_idx = (current_idx + 1) % len(items)
            if state_key:
                state_cursor += 1
                _set_playout_cursor(channel_id, state_key, state_cursor)

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state['error'] = str(exc)
        print(f"shared channel producer error channel={label}: {exc}", flush=True)
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        state['proc'] = None
        state['running'] = False
        # Wake remaining subscribers so StreamingResponse can close cleanly.
        for q in list(state.get('subscribers', set())):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(None)
                except Exception:
                    pass
            except Exception:
                pass
        if SHARED_CHANNEL_STREAMS.get(channel_id) is state:
            SHARED_CHANNEL_STREAMS.pop(channel_id, None)
        print(f"shared channel producer stopped: channel={label}", flush=True)


async def _subscribe_shared_channel(channel_id: int):
    state = SHARED_CHANNEL_STREAMS.get(channel_id)
    if state is None or not state.get('running') or state.get('task') is None or state['task'].done():
        state = {
            'running': True,
            'stop': False,
            'proc': None,
            'task': None,
            'subscribers': set(),
            'empty_since': None,
            'started_at': time.time(),
            'error': '',
        }
        SHARED_CHANNEL_STREAMS[channel_id] = state
        state['task'] = asyncio.create_task(_shared_channel_producer(channel_id, state))

    q: asyncio.Queue = asyncio.Queue(maxsize=SHARED_CHANNEL_QUEUE_CHUNKS)
    state['subscribers'].add(q)
    state['empty_since'] = None
    label = _shared_stream_label(channel_id)
    print(f"shared channel viewer joined: channel={label} viewers={len(state['subscribers'])}", flush=True)
    try:
        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        state['subscribers'].discard(q)
        if not state['subscribers']:
            state['empty_since'] = time.time()
        print(f"shared channel viewer left: channel={label} viewers={len(state['subscribers'])}", flush=True)


# Override the earlier per-viewer generator. Existing /stream routes call this
# name at request time, so they automatically gain shared station fan-out.
async def stream_channel(channel_id: int):
    async for chunk in _subscribe_shared_channel(channel_id):
        yield chunk


@app.get('/internal/stream/channel/{channel_number}.ts')
async def internal_shared_stream(channel_number: str):
    """Loopback feed used by the browser HLS segmenter.

    It subscribes to the same station producer as Kodi; it does NOT create a
    second Plex/local source transcode.
    """
    channel_id = resolve_channel_number(channel_number)
    if not _retro_config_for_channel(channel_id):
        _, items = channel_media(channel_id)
        if not items:
            raise HTTPException(503, 'Channel has no playable media')
    return StreamingResponse(
        stream_channel(channel_id),
        media_type='video/mp2t',
        headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'},
    )


# Override v1.1.20 browser source command. HLS is now only a lightweight
# segmenter fed from the shared station output instead of a second encoder.
def _browser_hls_command(channel: sqlite3.Row, item: dict[str, Any], offset: float, out_dir: Path) -> list[str]:
    manifest = str(out_dir / 'index.m3u8')
    segment_pattern = str(out_dir / 'seg_%06d.ts')
    channel_number = quote(str(channel['number']), safe='')
    shared_url = f'http://127.0.0.1:8409/internal/stream/channel/{channel_number}.ts'
    return [
        'ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-fflags', '+genpts+discardcorrupt', '-i', shared_url,
        '-map', '0:v:0?', '-map', '0:a:0?', '-sn', '-dn',
        '-c', 'copy',
        '-f', 'hls',
        '-hls_time', '2',
        '-hls_list_size', '10',
        '-hls_delete_threshold', '5',
        '-hls_flags', 'delete_segments+independent_segments+program_date_time',
        '-hls_segment_filename', segment_pattern,
        manifest,
    ]


@app.get('/api/streams/shared')
def shared_stream_status():
    """Small diagnostics endpoint for concurrent-stream troubleshooting."""
    rows = []
    for channel_id, state in list(SHARED_CHANNEL_STREAMS.items()):
        proc = state.get('proc')
        rows.append({
            'channel_id': channel_id,
            'channel': _shared_stream_label(channel_id),
            'viewers': len(state.get('subscribers', set())),
            'producer_running': bool(proc is not None and proc.returncode is None),
            'uptime_seconds': max(0, int(time.time() - float(state.get('started_at') or time.time()))),
            'source_mode': str(state.get('source_mode') or ''),
            'source_item': str(state.get('source_item') or ''),
            'source_warning': str(state.get('source_warning') or '')[-300:],
            'last_return_code': state.get('last_return_code'),
            'last_item_bytes': int(state.get('last_item_bytes') or 0),
            'current_item_bytes': int(state.get('current_item_bytes') or 0),
            'source_retries': int(state.get('source_retries') or 0),
            'slow_disconnects': int(state.get('slow_disconnects') or 0),
            'program_advances': int(state.get('program_advances') or 0),
            'item_offset': float(state.get('item_offset') or 0),
            'timeline_seconds': float(state.get('timeline_seconds') or 0),
            'error': str(state.get('error') or '')[-500:],
        })
    return JSONResponse({'channels': rows, 'count': len(rows), 'live_profile': {'probe_size': LIVE_PROBE_SIZE, 'analyze_us': LIVE_ANALYZE_US, 'queue_chunks': SHARED_CHANNEL_QUEUE_CHUNKS, 'hls_segment_seconds': HLS_SEGMENT_SECONDS}})


async def stop_all_shared_channel_streams() -> None:
    states = list(SHARED_CHANNEL_STREAMS.values())
    for state in states:
        state['stop'] = True
        proc = state.get('proc')
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
            except Exception:
                pass
    tasks = [state.get('task') for state in states if state.get('task') is not None]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


# ---------------- Stream stability hardening (v1.1.23+) --------------------

def _low_latency_station_command(cmd: list[str]) -> list[str]:
    """Reduce mux/encoder latency on the one shared station producer.

    This is intentionally applied only at the station output.  Viewers still get
    their own clean remux, but the producer flushes MPEG-TS packets promptly and
    encoded profiles emit frequent keyframes so a newly joined Kodi/HLS client can
    lock onto the live picture quickly.
    """
    out = list(cmd)
    insert_at = None
    for i in range(len(out) - 1):
        if out[i] == '-f' and out[i + 1] == 'mpegts':
            insert_at = i
    if insert_at is None:
        return out
    opts = ['-muxdelay', '0', '-muxpreload', '0', '-flush_packets', '1']
    # A one-ish-second GOP makes live joins/HLS cuts much less dependent on the
    # source's default keyframe interval. Never apply encoder-only options to
    # direct stream-copy channels.
    is_copy = any(out[i] == '-c' and i + 1 < len(out) and out[i + 1] == 'copy' for i in range(len(out)-1))
    is_copy = is_copy or any(out[i] == '-c:v' and i + 1 < len(out) and out[i + 1] == 'copy' for i in range(len(out)-1))
    if not is_copy:
        opts += ['-g', '30']
        if 'libx264' in out:
            opts += ['-tune', 'zerolatency']
    out[insert_at:insert_at] = opts
    return out

def _station_timestamp_command(cmd: list[str], timeline_seconds: float) -> list[str]:
    """Shift each source FFmpeg's MPEG-TS timestamps onto one station clock.

    A channel is assembled from a sequence of separate FFmpeg processes.  Each
    process normally starts its output timestamps near zero; blindly concatenating
    those transport streams makes PTS/DTS jump backwards at every programme or
    retry.  Give each source process a monotonically increasing output offset so
    downstream Kodi/HLS remuxers see one continuous live timeline.
    """
    out = list(cmd)
    insert_at = None
    for i in range(len(out) - 1):
        if out[i] == '-f' and out[i + 1] == 'mpegts':
            insert_at = i
    if insert_at is None:
        return out
    out[insert_at:insert_at] = ['-output_ts_offset', f'{max(0.0, float(timeline_seconds)):.6f}']
    return out

# v1.1.22 proved the one-producer/many-viewers design, but two transport edge
# cases remained:
#   1) a slow subscriber could have arbitrary chunks dropped from its queue,
#      corrupting MPEG-TS continuity; and
#   2) *any* early source-FFmpeg exit was treated as the end of the programme,
#      which could advance the station into another show/movie after a transient
#      decoder/network failure.
# The hardened producer below disconnects a lagging viewer cleanly instead of
# feeding it damaged TS, and retries an unexpectedly-ended programme at the
# appropriate offset without advancing playout state.

async def _shared_channel_producer(channel_id: int, state: dict[str, Any]) -> None:
    channel, items = channel_media(channel_id)
    if not items:
        offline = channel['offline_media'] if 'offline_media' in channel.keys() else None
        if offline and Path(str(offline)).exists():
            items = [{'source_type':'local','path':offline,'duration':3600,'title':'Offline'}]
        else:
            state['error'] = 'Channel has no playable media'
            state['running'] = False
            return

    idx, offset, _ = locate_at(items, datetime.now(timezone.utc))
    current_idx = idx
    next_offset = max(0.0, float(offset or 0.0))
    state_key, state_cursor = _scheduled_cursor(channel_id)
    proc: asyncio.subprocess.Process | None = None
    label = _shared_stream_label(channel_id)
    state['started_at'] = time.time()
    state['error'] = ''
    state.setdefault('source_retries', 0)
    state.setdefault('slow_disconnects', 0)
    state.setdefault('program_advances', 0)
    state.setdefault('timeline_seconds', 0.0)
    print(f"shared channel producer started: channel={label}", flush=True)

    try:
        while not state.get('stop'):
            if not state['subscribers']:
                empty_since = state.get('empty_since') or time.time()
                state['empty_since'] = empty_since
                if time.time() - float(empty_since) >= SHARED_CHANNEL_GRACE_SECONDS:
                    break
            else:
                state['empty_since'] = None

            item = items[current_idx]
            launch_offset = max(0.0, next_offset)
            next_offset = 0.0
            duration = max(0.0, float(item.get('duration') or 0.0))
            expected_remaining = max(0.0, duration - launch_offset) if duration else 0.0

            requested_effective, configured_profile, profile_warning = effective_stream_profile(channel)
            force_software = int(state.get('force_software_item', -1)) == int(current_idx)
            profile_override = 'software' if force_software else None
            effective_profile = 'software' if force_software else requested_effective
            state['configured_profile'] = configured_profile
            state['effective_profile'] = effective_profile
            if profile_warning and not state.get('hardware_fallback_reason'):
                state['hardware_fallback_reason'] = profile_warning[:300]

            if item['source_type'] == 'gap':
                state['source_mode']='schedule-gap';state['source_warning']='';state['effective_profile']='software';cmd=_profiled_gap_command(channel,item,launch_offset)
            elif item['source_type'] == 'plex':
                try:
                    part_url, plex_headers = await asyncio.to_thread(_plex_direct_part_source, item)
                    cmd = _profiled_plex_part_command(channel, item, launch_offset, part_url, plex_headers, profile_override)
                    state['source_mode'] = 'plex-direct-part'
                    state['source_warning'] = ''
                except Exception as exc:
                    cmd = plex_ffmpeg_command(item, launch_offset)
                    state['source_mode'] = 'plex-universal-fallback'
                    state['effective_profile'] = 'plex-transcoder'
                    state['source_warning'] = str(exc)[:300]
            elif item['source_type'] == 'external':
                state['source_mode'] = 'external-direct'
                state['effective_profile'] = 'direct'
                cmd = _profiled_external_command(channel, item, launch_offset)
            else:
                state['source_mode'] = 'local'
                cmd = _profiled_local_command(channel, item, launch_offset, profile_override)

            if item.get('_actual_stream_profile'):
                state['effective_profile'] = str(item.get('_actual_stream_profile'))

            trim_limit=float(item.get('_trim_limit') or 0.0)
            if trim_limit>0:
                cmd=_limit_station_command(cmd,max(0.1,trim_limit-launch_offset))
            state['source_item'] = str(item.get('show_title') or item.get('title') or '')
            state['item_index'] = current_idx
            state['item_offset'] = round(launch_offset, 3)
            state['expected_remaining'] = round(expected_remaining, 3)
            produced_bytes = 0
            timeline_offset = float(state.get('timeline_seconds') or 0.0)
            cmd = _low_latency_station_command(cmd)
            cmd = _station_timestamp_command(cmd, timeline_offset)
            state['timeline_offset'] = round(timeline_offset, 3)
            launch_monotonic = time.monotonic()

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            state['proc'] = proc
            assert proc.stdout is not None

            while not state.get('stop'):
                chunk = await proc.stdout.read(64 * 1024)
                if not chunk:
                    break
                produced_bytes += len(chunk)
                state['current_item_bytes'] = produced_bytes

                # Never repair a lagging viewer by deleting bytes from the middle
                # of its MPEG-TS stream.  That creates continuity-counter/PES
                # corruption.  Disconnect that one viewer cleanly; Kodi/HLS will
                # reconnect to the still-running station producer.
                for q in list(state['subscribers']):
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        state['subscribers'].discard(q)
                        state['slow_disconnects'] = int(state.get('slow_disconnects') or 0) + 1
                        try:
                            while True:
                                q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        except Exception:
                            pass
                        try:
                            q.put_nowait(None)
                        except Exception:
                            pass
                        print(
                            f"shared channel slow viewer disconnected: channel={label} "
                            f"remaining_viewers={len(state['subscribers'])}",
                            flush=True,
                        )

                if not state['subscribers']:
                    empty_since = state.get('empty_since') or time.time()
                    state['empty_since'] = empty_since
                    if time.time() - float(empty_since) >= SHARED_CHANNEL_GRACE_SECONDS:
                        state['stop'] = True
                        break
                else:
                    state['empty_since'] = None

            if proc.returncode is None and state.get('stop'):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=4)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

            elapsed = max(0.0, time.monotonic() - launch_monotonic)
            state['last_return_code'] = proc.returncode
            state['last_item_bytes'] = produced_bytes
            state['last_item_runtime'] = round(elapsed, 3)
            state['timeline_seconds'] = timeline_offset + elapsed

            err_text = ''
            if proc.returncode not in (0, 255, -15) and not state.get('stop'):
                try:
                    err = await proc.stderr.read() if proc.stderr else b''
                    err_text = err.decode(errors='ignore')[-2000:]
                    err_text = re.sub(r'(X-Plex-Token|api_key)=[^&\\s]+', r'\1=REDACTED', err_text)
                    state['error'] = err_text
                    print(f"shared ffmpeg channel {channel_id}: {err_text}", flush=True)
                except Exception:
                    pass

            state['proc'] = None
            proc = None
            if state.get('stop'):
                break

            # Hardware encoder initialization failures should never take a station
            # off air. Retry this exact programme in software when enabled. The
            # fallback is scoped to the current item and automatically clears at
            # the next programme boundary.
            used_profile = str(state.get('effective_profile') or '')
            hardware_failed = (
                hwaccel.is_hardware_profile(used_profile) and
                state.get('last_return_code') not in (0, -15) and
                (state.get('last_return_code') != 255 or produced_bytes < 1880) and
                elapsed < 12.0 and
                not force_software
            )
            if hardware_failed and hardware_fallback_enabled():
                state['hardware_fallbacks'] = int(state.get('hardware_fallbacks') or 0) + 1
                reason = f"{hwaccel.profile_label(used_profile)} failed to initialize or exited early; retrying this programme with software encoding."
                if err_text:
                    first_line = next((x.strip() for x in err_text.splitlines() if x.strip()), '')
                    if first_line:
                        reason += ' ' + first_line[:180]
                state['hardware_fallback_reason'] = reason[:300]
                state['force_software_item'] = current_idx
                if duration > 1 and produced_bytes > 0:
                    next_offset = min(max(0.0, duration - 0.5), launch_offset + elapsed)
                else:
                    next_offset = launch_offset
                state['error'] = ''
                print(f"hardware fallback: channel={label} profile={used_profile} item={state['source_item']!r}", flush=True)
                await asyncio.sleep(0.5)
                continue

            # With -re, a healthy source process consumes roughly wall-clock
            # programme time.  Only a process that made it to the expected end
            # is allowed to advance the station.  Short/failed processes retry
            # the SAME item instead of jumping to another programme.
            tolerance = min(30.0, max(5.0, expected_remaining * 0.10)) if expected_remaining else 5.0
            reached_program_end = (
                proc is None and
                state.get('last_return_code') == 0 and
                (not expected_remaining or elapsed >= max(1.0, expected_remaining - tolerance))
            )

            if reached_program_end:
                current_idx = (current_idx + 1) % len(items)
                next_offset = 0.0
                state['source_retries'] = 0
                state.pop('force_software_item', None)
                state['program_advances'] = int(state.get('program_advances') or 0) + 1
                state['error'] = ''
                if state_key:
                    state_cursor += 1
                    _set_playout_cursor(channel_id, state_key, state_cursor)
                continue

            # Unexpected EOF/error: resume this exact programme.  Never mutate
            # the persistent schedule cursor for a transport failure.
            state['source_retries'] = int(state.get('source_retries') or 0) + 1
            if duration > 1:
                next_offset = min(max(0.0, duration - 0.5), launch_offset + elapsed)
            else:
                next_offset = launch_offset
            why = f"source ended early rc={state.get('last_return_code')} runtime={elapsed:.1f}s expected={expected_remaining:.1f}s"
            if err_text:
                why += ' (ffmpeg error logged)'
            state['source_warning'] = why[:300]
            print(f"shared channel retry same item: channel={label} item={state['source_item']!r} {why}", flush=True)
            await asyncio.sleep(min(5.0, 1.0 + float(state['source_retries'])))

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        state['error'] = str(exc)
        print(f"shared channel producer error channel={label}: {exc}", flush=True)
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        state['proc'] = None
        state['running'] = False
        for q in list(state.get('subscribers', set())):
            try:
                while True:
                    q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            except Exception:
                pass
            try:
                q.put_nowait(None)
            except Exception:
                pass
        if SHARED_CHANNEL_STREAMS.get(channel_id) is state:
            SHARED_CHANNEL_STREAMS.pop(channel_id, None)
        print(f"shared channel producer stopped: channel={label}", flush=True)


async def _clean_client_ts_stream(channel_id: int):
    """Per-viewer *remux only* sanitizer for Kodi/IPTV clients.

    The expensive source decode/encode still happens exactly once in the shared
    station producer.  This tiny copy/remux process gives every external client
    fresh PAT/PMT tables, continuity counters and wall-clock timestamps instead
    of attaching it to an arbitrary byte in an already-running transport stream.
    """
    with db() as conn:
        ch = conn.execute('SELECT number FROM channels WHERE id=?', (channel_id,)).fetchone()
    if not ch:
        return
    channel_number = quote(str(ch['number']), safe='')
    shared_url = f'http://127.0.0.1:8409/internal/stream/channel/{channel_number}.ts'
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-fflags', '+genpts+discardcorrupt+nobuffer',
        '-flags', 'low_delay',
        '-probesize', str(LIVE_PROBE_SIZE), '-analyzeduration', str(LIVE_ANALYZE_US),
        '-max_delay', '0',
        '-i', shared_url,
        '-map', '0:v:0?', '-map', '0:a:0?', '-sn', '-dn',
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        '-muxdelay', '0', '-muxpreload', '0', '-flush_packets', '1',
        '-mpegts_flags', '+resend_headers+initial_discontinuity',
        '-f', 'mpegts', 'pipe:1',
    ]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(64 * 1024)
            if not chunk:
                break
            yield chunk
        await proc.wait()
        if proc.returncode not in (0, 255, -15):
            try:
                err = await proc.stderr.read() if proc.stderr else b''
                text = err.decode(errors='ignore')[-1200:]
                if text:
                    print(f'client TS remux channel {channel_id}: {text}', flush=True)
            except Exception:
                pass
    except (asyncio.CancelledError, GeneratorExit):
        raise
    finally:
        if proc and proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass


def stream_response_for_channel(channel_id: int):
    # Retro channels are clock-driven and intentionally have no ordinary
    # channel_selections. All other channels retain the normal validation.
    if not _retro_config_for_channel(channel_id):
        _, items = channel_media(channel_id)
        if not items:
            raise HTTPException(503, 'Channel has no playable media. Sync Plex or scan local media and select shows/seasons first.')
    return StreamingResponse(
        _clean_client_ts_stream(channel_id),
        media_type='video/mp2t',
        headers={'Cache-Control':'no-store','X-Accel-Buffering':'no'},
    )


# HLS uses the same station producer, but with a long enough segment-retention
# window that a temporarily busy browser cannot request a segment that FFmpeg
# has already deleted.  Epoch-based numbering prevents stale fragment URLs from
# one preview generation colliding with a later generation.
def _browser_hls_command(channel: sqlite3.Row, item: dict[str, Any], offset: float, out_dir: Path) -> list[str]:
    manifest = str(out_dir / 'index.m3u8')
    segment_pattern = str(out_dir / 'seg_%012d.ts')
    channel_number = quote(str(channel['number']), safe='')
    shared_url = f'http://127.0.0.1:8409/internal/stream/channel/{channel_number}.ts'
    return [
        'ffmpeg', '-hide_banner', '-loglevel', 'warning',
        '-fflags', '+genpts+discardcorrupt+nobuffer',
        '-flags', 'low_delay',
        '-probesize', str(LIVE_PROBE_SIZE), '-analyzeduration', str(LIVE_ANALYZE_US),
        '-max_delay', '0',
        '-i', shared_url,
        '-map', '0:v:0?', '-map', '0:a:0?', '-sn', '-dn',
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        '-f', 'hls',
        '-hls_time', f'{HLS_SEGMENT_SECONDS:g}',
        '-hls_list_size', '16',
        '-hls_delete_threshold', '40',
        '-hls_start_number_source', 'epoch',
        '-hls_flags', 'delete_segments+independent_segments+program_date_time+temp_file',
        '-hls_segment_filename', segment_pattern,
        manifest,
    ]


# ---------------- Retro producer dispatch (v1.1.31 final binding) ----------------
# Bound last so every existing route/subscriber resolves this dispatcher at runtime.
_STANDARD_SHARED_CHANNEL_PRODUCER_1131 = _shared_channel_producer
async def _shared_channel_producer(channel_id:int,state:dict[str,Any]) -> None:
    if _retro_config_for_channel(channel_id):
        await _retro_shared_channel_producer(channel_id,state)
    else:
        await _STANDARD_SHARED_CHANNEL_PRODUCER_1131(channel_id,state)

# ---------------- ViperTV v1.2.0 advanced scheduling/branding ----------------
# Installed last so the additive Block/Sequential/filler/graphics layers wrap the
# proven v1.1.46 scheduling and stream command bindings rather than replacing them.
from .advanced_scheduling import init_v12_db, install_advanced_scheduling
install_advanced_scheduling(app, globals())

# ---------------- ViperTV v1.2.4 playlists + persistent indexed smart search ----------------
from .media_power import install_media_power
install_media_power(app, globals())

# ---------------- ViperTV v1.2.6 scheduled images + streaming modes ----------------
from .scheduled_media_stream_modes import install_v126
install_v126(app, globals())

# ---------------- ViperTV v1.2.7 scheduler completion ----------------
# Reusable Marathons plus unified Advanced Filler complete the Classic / Block /
# Sequential scheduling stack without replacing the proven streaming core.
from .scheduler_completion import install_v127
install_v127(app, globals())

# ---------------- ViperTV v1.2.8 scheduler automation ----------------
# Deco Templates + prioritized Playout Templates + authenticated Scripted
# Scheduling API/OpenAPI. Installed last so it can safely wrap v1.2.7.
from .scheduler_automation import install_v128
install_v128(app, globals())

# ---------------- ViperTV v1.2.9 streams + graphics + Plex direct paths ----------------
# Advanced stream selectors, Graphics Engine 2.0 and Plex stream-from-disk.
# Installed last so all stream-command wrappers resolve the v1.2.9 behavior.
from .stream_graphics_paths import install_v129
install_v129(app, globals())


# ---------------- ViperTV v1.3.0 direct external paths + FFmpeg profiles ----------------
# Jellyfin/Emby stream-from-disk and reusable complete transcoding recipes.
from .direct_media_ffmpeg_profiles import install_v130
install_v130(app, globals())

# v1.4.0: media/security/automation completion
from .media_security_completion import install_v140
install_v140(app, globals())

# ---------------- ViperTV v1.5.0 administration, diagnostics & setup ----------------
from .administration_suite import install_v150
install_v150(app, globals())
