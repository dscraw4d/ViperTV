from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import json
import os
import re
import secrets
import shlex
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, FileResponse, Response

from . import media_power as mp
from . import scheduled_media_stream_modes as sm
from . import scheduler_automation as sa
from . import stream_graphics_paths as sgp
from . import advanced_scheduling as adv

G: dict[str, Any] = {}
_BASE_CHANNEL_MEDIA = None
_BASE_PROFILED_LOCAL = None
_BASE_SCRIPTED_DAY_ITEMS = None
_BASE_SEARCH_ATOM = None
_BASE_IMAGES_PAGE = None
_BASE_PAGE_SHELL = None

_IPTV_TOKEN_CTX: contextvars.ContextVar[str] = contextvars.ContextVar('vipertv_iptv_token', default='')
_SCRIPT_RUNS: dict[str, dict[str, Any]] = {}
_SCRIPT_LOCK = threading.RLock()
_GRAPHICS_TESTS: dict[str, dict[str, Any]] = {}
_GRAPHICS_LOCK = threading.RLock()
_BG_STARTED = False


def _db(): return G['db']()
def _e(v: Any) -> str: return G['e'](v)
def _now() -> str: return G['utcnow_iso']()
def _page(title: str, body: str) -> str: return G['page_shell'](title, body)
def _heading(title: str, subtitle: str, actions: str='') -> str: return G['_page_heading'](title, subtitle, actions)

def _setting(key: str, default: str='') -> str:
    try: return str(G['get_setting'](key, default) or default)
    except Exception: return default

def _set_setting(key: str, value: Any) -> None:
    G['set_setting'](key, str(value))


def init_v140_db() -> None:
    # live_streams is normally initialized later in the main lifespan; v1.4 adds
    # columns to it, so ensure the legacy table exists first. The main lifespan
    # may safely call the initializer again afterward.
    if callable(G.get('init_live_stream_db')):
        G['init_live_stream_db']()
    with _db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS image_folder_durations(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
          folder_path TEXT NOT NULL,
          duration_seconds REAL NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(library_id,folder_path)
        );
        CREATE INDEX IF NOT EXISTS idx_image_folder_durations_lookup
          ON image_folder_durations(library_id,enabled,folder_path);

        CREATE TABLE IF NOT EXISTS trakt_lists(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          username TEXT NOT NULL,
          list_slug TEXT NOT NULL,
          target_kind TEXT NOT NULL DEFAULT 'playlist',
          target_id INTEGER,
          refresh_hours INTEGER NOT NULL DEFAULT 24,
          enabled INTEGER NOT NULL DEFAULT 1,
          last_refresh TEXT,
          last_count INTEGER NOT NULL DEFAULT 0,
          last_matched INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduler_scripts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          script_path TEXT NOT NULL,
          interpreter TEXT NOT NULL DEFAULT 'auto',
          arguments_json TEXT NOT NULL DEFAULT '[]',
          mode TEXT NOT NULL DEFAULT 'build',
          timeout_seconds INTEGER NOT NULL DEFAULT 120,
          enabled INTEGER NOT NULL DEFAULT 1,
          last_run TEXT,
          last_rc INTEGER,
          last_log TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scripted_graphics_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          schedule_id INTEGER NOT NULL REFERENCES scripted_schedules(id) ON DELETE CASCADE,
          air_date TEXT,
          day_mask INTEGER NOT NULL DEFAULT 127,
          start_minute INTEGER NOT NULL,
          graphic_id INTEGER NOT NULL REFERENCES graphics_elements(id) ON DELETE CASCADE,
          action TEXT NOT NULL DEFAULT 'on',
          position INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_scripted_graphics_events
          ON scripted_graphics_events(schedule_id,air_date,start_minute,position,id);
        ''')
        # Extend legacy Live IPTV into general remote definitions without breaking old rows.
        G['add_column_if_missing'](conn, 'live_streams', 'input_kind', "TEXT NOT NULL DEFAULT 'url'")
        G['add_column_if_missing'](conn, 'live_streams', 'command_json', 'TEXT')
        G['add_column_if_missing'](conn, 'live_streams', 'stream_behavior', "TEXT NOT NULL DEFAULT 'live'")
        G['add_column_if_missing'](conn, 'live_streams', 'scheduled_duration', 'REAL')
        G['add_column_if_missing'](conn, 'live_streams', 'probe_timeout', 'INTEGER NOT NULL DEFAULT 15')
        conn.commit()
    if not _setting('auth_cookie_secret'):
        _set_setting('auth_cookie_secret', secrets.token_urlsafe(48))
    if not _setting('iptv_jwt_secret'):
        _set_setting('iptv_jwt_secret', secrets.token_urlsafe(48))


# ---------------- image folder duration inheritance ----------------

def _norm_path(p: str) -> str:
    try: return str(Path(str(p or '')).resolve())
    except Exception: return os.path.normpath(str(p or ''))


def _image_folder_duration(library_id: int, path: str) -> float | None:
    p = _norm_path(path)
    with _db() as conn:
        rows = conn.execute('''SELECT folder_path,duration_seconds FROM image_folder_durations
                               WHERE enabled=1 AND (library_id=? OR library_id IS NULL)
                               ORDER BY CASE WHEN library_id=? THEN 0 ELSE 1 END,
                                        LENGTH(folder_path) DESC,id DESC''',
                            (int(library_id or 0), int(library_id or 0))).fetchall()
    for r in rows:
        root = _norm_path(str(r['folder_path'] or ''))
        try:
            common = os.path.commonpath([p, root])
        except Exception:
            continue
        if common == root:
            return max(1.0, float(r['duration_seconds'] or 10))
    return None


def _effective_image_duration(item: dict[str, Any]) -> float:
    # If the media duration differs from the global default, preserve it as the
    # strongest per-image override. Otherwise inherit the nearest folder rule.
    stored = float(item.get('duration') or 0.0)
    global_default = max(1.0, float(_setting('image_default_duration_seconds', '10') or 10))
    folder = _image_folder_duration(int(item.get('library_id') or 0), str(item.get('path') or ''))
    if stored > 0 and abs(stored - global_default) > 0.001:
        return stored
    if folder is not None:
        return folder
    return stored if stored > 0 else global_default


def _apply_image_durations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out=[]
    for raw in items:
        x=dict(raw)
        if str(x.get('media_kind') or x.get('media_type') or '').lower()=='image' and x.get('path'):
            x['duration']=_effective_image_duration(x)
            x['_effective_image_duration']=x['duration']
        out.append(x)
    return out


def _channel_media_v140(channel_id: int):
    ch, items = _BASE_CHANNEL_MEDIA(channel_id)
    return ch, _apply_image_durations([dict(x) for x in items])


def _images_page_v140(msg: str='') -> str:
    base = _BASE_IMAGES_PAGE(msg)
    with _db() as conn:
        libs=conn.execute('SELECT id,name,path FROM libraries ORDER BY name COLLATE NOCASE').fetchall()
        rules=conn.execute('''SELECT r.*,l.name library_name FROM image_folder_durations r
                             LEFT JOIN libraries l ON l.id=r.library_id ORDER BY COALESCE(l.name,''),LENGTH(r.folder_path),r.folder_path''').fetchall()
    libopts="<option value=''>All libraries</option>"+''.join(f"<option value='{r['id']}'>{_e(r['name'])}</option>" for r in libs)
    rows=''.join(f"<tr><td>{_e(r['library_name'] or 'All libraries')}</td><td><code>{_e(r['folder_path'])}</code></td><td>{float(r['duration_seconds']):g}s</td><td>{'Yes' if r['enabled'] else 'No'}</td><td><form class='inline' method='post' action='/media/images/folder-duration/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for r in rules) or "<tr><td colspan='5' class='empty'>No folder duration rules yet.</td></tr>"
    extra=f"""
<div class='card'><h2>Folder duration inheritance</h2><p class='muted'>A rule applies to every image in that folder and its child folders. The most specific matching child folder wins. An explicit per-image duration still wins over folder inheritance.</p>
<form method='post' action='/media/images/folder-duration/add'><div class='grid3'><div><label>Library</label><select name='library_id'>{libopts}</select></div><div><label>Folder path visible to ViperTV</label><input name='folder_path' required placeholder='D:\\Media\\Station IDs'></div><div><label>Duration seconds</label><input type='number' name='seconds' min='1' max='86400' step='.5' value='10'></div></div><button>Add Folder Rule</button></form>
<div class='table-wrap' style='margin-top:16px'><table><thead><tr><th>Library</th><th>Folder</th><th>Duration</th><th>Enabled</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>"""
    pos=base.rfind('</main>')
    return base[:pos]+extra+base[pos:] if pos>=0 else base+extra


def _standalone_data_subdir(name: str) -> Path:
    base = Path(os.environ.get('VIPERTV_DATA_DIR', '/data')).resolve()
    p = base / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def _remote_script_root() -> Path:
    default = str(_standalone_data_subdir('remote-scripts'))
    p = Path(_setting('remote_script_root', default)).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------- general remote stream definitions ----------------

def _remote_row_to_item(r: Any) -> dict[str, Any]:
    d=dict(r)
    dur=float(d.get('scheduled_duration') or (86400 if str(d.get('stream_behavior') or 'live')=='live' else 3600))
    return {
        **d,'source_type':'live','uid':f"live:{d['id']}",'media_type':'remote_stream','media_kind':'remote_stream',
        'title':d.get('name'),'duration':dur,'source_url':d.get('stream_url'),'library_name':'Remote Streams',
        '_trim_limit':dur if str(d.get('stream_behavior') or 'live')!='live' else 0,
    }


def _remote_command(channel: Any, item: dict[str, Any], offset: float, profile_override=None) -> list[str] | None:
    if str(item.get('source_type') or '')!='live' or str(item.get('input_kind') or 'url')!='command':
        return None
    try: argv=json.loads(str(item.get('command_json') or '[]'))
    except Exception: argv=[]
    if not isinstance(argv,list) or not argv: raise RuntimeError('Remote command has no executable configured')
    argv=[str(x) for x in argv]
    exe=Path(argv[0])
    allowed=_remote_script_root()
    try: resolved=exe.resolve()
    except Exception: resolved=exe
    if not resolved.is_absolute() or os.path.commonpath([str(resolved),str(allowed)])!=str(allowed):
        raise RuntimeError(f'Remote command must live under {allowed}')
    dur=max(1.0,float(item.get('duration') or item.get('scheduled_duration') or 3600)-max(0.0,float(offset or 0)))
    ff=['ffmpeg','-hide_banner','-loglevel','error','-fflags','+genpts','-i','pipe:0','-t',f'{dur:.3f}','-map','0:v:0?','-map','0:a:0?','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-f','mpegts','pipe:1']
    # create_subprocess_exec executes this wrapper; shlex.join keeps configured
    # argv literal while still allowing a stdout pipe into FFmpeg.
    if os.name == 'nt':
        # cmd.exe provides a native stdout pipe between the trusted producer and FFmpeg.
        return ['cmd.exe','/d','/s','/c',subprocess.list2cmdline(argv)+' | '+subprocess.list2cmdline(ff)]
    return ['/bin/sh','-c',f"exec {shlex.join(argv)} | {shlex.join(ff)}"]


def _profiled_local_v140(channel: Any, item: dict[str, Any], offset: float, profile_override=None):
    cmd=_remote_command(channel,item,offset,profile_override)
    if cmd is not None:return cmd
    return _BASE_PROFILED_LOCAL(channel,item,offset,profile_override)


def _remote_streams_page(msg: str='') -> str:
    with _db() as conn: rows=conn.execute('SELECT * FROM live_streams ORDER BY CAST(number AS REAL),number,name').fetchall()
    trs=''.join(f"<tr><td>{_e(r['number'])}</td><td><b>{_e(r['name'])}</b></td><td>{_e(r['input_kind'] or 'url')}</td><td>{_e(r['stream_behavior'] or 'live')}</td><td>{_e((str(r['scheduled_duration'])+'s') if r['scheduled_duration'] else '—')}</td><td>{'Yes' if r['enabled'] else 'No'}</td><td><a class='button secondary' href='/sources/remote-streams/{r['id']}'>Edit</a></td></tr>" for r in rows) or "<tr><td colspan='7'>No remote streams.</td></tr>"
    notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    body=notice+_heading('Remote Streams','Define any FFmpeg-readable URL or a trusted executable whose stdout is media. Streams can behave as Live or scheduled VOD.',"<a class='button secondary' href='/live'>Legacy Live IPTV</a>")+f"""
<div class='card'><h2>Add Remote Stream</h2><form method='post' action='/sources/remote-streams/add'><div class='grid3'><div><label>Channel number</label><input name='number' value='900'><label>Name</label><input name='name' required></div><div><label>Input kind</label><select name='input_kind'><option value='url'>URL / file readable by FFmpeg</option><option value='command'>Executable stdout</option></select><label>Behavior</label><select name='stream_behavior'><option value='live'>Live</option><option value='vod'>VOD / scheduled duration</option></select></div><div><label>URL</label><input name='stream_url' placeholder='https://example/stream.m3u8'><label>Scheduled seconds</label><input type='number' name='scheduled_duration' min='1' placeholder='3600'></div></div><label>Command JSON argv (command input only)</label><textarea name='command_json' rows='3' placeholder='[&quot;C:\\ViperTV\\remote-scripts\\feed.exe&quot;,&quot;--channel&quot;,&quot;news&quot;]'></textarea><p class='muted small'>Executable paths are restricted to <code>{_e(str(_remote_script_root()))}</code>.</p><button>Add Remote Stream</button></form></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>#</th><th>Name</th><th>Input</th><th>Behavior</th><th>Duration</th><th>Enabled</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>"""
    return _page('Remote Streams',body)


def _remote_stream_edit(rid:int,msg:str='')->str:
    with _db() as conn:r=conn.execute('SELECT * FROM live_streams WHERE id=?',(rid,)).fetchone()
    if not r:raise HTTPException(404,'Remote stream not found')
    notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    ik=''.join(f"<option value='{v}' {'selected' if str(r['input_kind'] or 'url')==v else ''}>{label}</option>" for v,label in [('url','URL / file'),('command','Executable stdout')])
    sb=''.join(f"<option value='{v}' {'selected' if str(r['stream_behavior'] or 'live')==v else ''}>{label}</option>" for v,label in [('live','Live'),('vod','VOD / scheduled')])
    body=notice+_heading('Edit Remote Stream',str(r['name']),"<a class='button secondary' href='/sources/remote-streams'>Back</a>")+f"""
<div class='card'><form method='post' action='/sources/remote-streams/{rid}/save'><div class='grid3'><div><label>Number</label><input name='number' value='{_e(r['number'])}'><label>Name</label><input name='name' value='{_e(r['name'])}' required></div><div><label>Input kind</label><select name='input_kind'>{ik}</select><label>Behavior</label><select name='stream_behavior'>{sb}</select></div><div><label>URL</label><input name='stream_url' value='{_e(r['stream_url'] or '')}'><label>Scheduled seconds</label><input type='number' name='scheduled_duration' value='{_e(r['scheduled_duration'] or '')}'></div></div><label>Command JSON argv</label><textarea name='command_json' rows='3'>{_e(r['command_json'] or '')}</textarea><label><input type='checkbox' name='enabled' value='1' {'checked' if r['enabled'] else ''}> Enabled</label><button>Save</button></form></div>"""
    return _page('Edit Remote Stream',body)


# ---------------- Trakt Lists ----------------

def _trakt_fetch(username:str,slug:str)->list[dict[str,Any]]:
    client=_setting('trakt_client_id')
    if not client: raise RuntimeError('Trakt Client ID is not configured')
    u=urllib.parse.quote(username,safe='');s=urllib.parse.quote(slug,safe='')
    url=f'https://api.trakt.tv/users/{u}/lists/{s}/items?extended=full'
    req=urllib.request.Request(url,headers={'trakt-api-key':client,'trakt-api-version':'2','User-Agent':f"ViperTV/{G['APP_VERSION']}",'Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=30) as resp:
        data=json.loads(resp.read().decode('utf-8'))
    return data if isinstance(data,list) else []


def _trakt_candidates(entry:dict[str,Any])->tuple[str,int|None]:
    obj=entry.get('movie') or entry.get('show') or entry.get('episode') or {}
    title=str(obj.get('title') or '')
    year=obj.get('year')
    try: year=int(year) if year else None
    except Exception: year=None
    return title,year


def _refresh_trakt_list(list_id:int)->dict[str,Any]:
    with _db() as conn:r=conn.execute('SELECT * FROM trakt_lists WHERE id=?',(list_id,)).fetchone()
    if not r:raise RuntimeError('Trakt list not found')
    try:
        raw=_trakt_fetch(str(r['username']),str(r['list_slug']))
        tokens=[];matched=0
        for entry in raw:
            title,year=_trakt_candidates(entry)
            if not title:continue
            q=f'"{title}"'+(f' {year}' if year else '')
            hits=G['media_search_playable'](q,10)
            best=None
            for h in hits:
                ht=str(h.get('show_title') or h.get('title') or '').casefold()
                if ht==title.casefold():best=h;break
            if best is None and hits:best=hits[0]
            if best:
                try:tokens.append(G['_item_selection_token'](best));matched+=1
                except Exception:pass
        # de-dup order
        tokens=list(dict.fromkeys(tokens))
        target_kind=str(r['target_kind'] or 'playlist');target_id=r['target_id'];now=_now()
        G['safe_backup_before_change']()
        with _db() as conn:
            if target_kind=='playlist':
                if not target_id:
                    cur=conn.execute('INSERT INTO playlists(name,created_at,updated_at) VALUES(?,?,?)',(f"Trakt - {r['name']}",now,now));target_id=int(cur.lastrowid)
                    conn.execute('UPDATE trakt_lists SET target_id=? WHERE id=?',(target_id,list_id))
                conn.execute('DELETE FROM playlist_items WHERE playlist_id=?',(int(target_id),))
                for pos,t in enumerate(tokens):
                    conn.execute('''INSERT INTO playlist_items(playlist_id,position,token,playback_order,play_all,show_in_epg,created_at)
                                    VALUES(?,?,?,?,?,?,?)''',(int(target_id),pos,t,'season_episode',0,1,now))
                conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(now,int(target_id)))
            else:
                if not target_id:
                    cur=conn.execute("INSERT INTO collections(name,kind,rule_json,created_at,updated_at) VALUES(?, 'manual','{}',?,?)",(f"Trakt - {r['name']}",now,now));target_id=int(cur.lastrowid)
                    conn.execute('UPDATE trakt_lists SET target_id=? WHERE id=?',(target_id,list_id))
                conn.execute('DELETE FROM collection_selections WHERE collection_id=?',(int(target_id),))
                for t in tokens:conn.execute('INSERT OR IGNORE INTO collection_selections(collection_id,token) VALUES(?,?)',(int(target_id),t))
                conn.execute('UPDATE collections SET updated_at=? WHERE id=?',(now,int(target_id)))
            conn.execute('UPDATE trakt_lists SET last_refresh=?,last_count=?,last_matched=?,last_error=NULL,updated_at=? WHERE id=?',(now,len(raw),matched,now,list_id));conn.commit()
        try:G['_classic_invalidate']()
        except Exception:pass
        return {'items':len(raw),'matched':matched,'target_id':target_id}
    except Exception as exc:
        with _db() as conn:conn.execute('UPDATE trakt_lists SET last_refresh=?,last_error=?,updated_at=? WHERE id=?',(_now(),str(exc)[:1000],_now(),list_id));conn.commit()
        raise


def _trakt_page(msg:str='')->str:
    with _db() as conn:rows=conn.execute('SELECT * FROM trakt_lists ORDER BY name').fetchall()
    trs=''.join(f"<tr><td><b>{_e(r['name'])}</b><div class='small muted'>{_e(r['username'])}/{_e(r['list_slug'])}</div></td><td>{_e(r['target_kind'])} #{_e(r['target_id'] or 'auto')}</td><td>{_e(r['last_refresh'] or 'Never')}</td><td>{int(r['last_matched'] or 0)}/{int(r['last_count'] or 0)}</td><td>{_e(r['last_error'] or '')}</td><td><form class='inline' method='post' action='/sources/trakt/{r['id']}/refresh'><button>Refresh</button></form> <form class='inline' method='post' action='/sources/trakt/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for r in rows) or "<tr><td colspan='6'>No Trakt lists.</td></tr>"
    notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    body=notice+_heading('Trakt Lists','Mirror a Trakt list into a ViperTV Playlist or manual Collection and refresh it automatically.')+f"""
<div class='grid'><div class='card'><h2>Trakt API</h2><form method='post' action='/sources/trakt/settings'><label>Client ID</label><input name='client_id' value='{_e(_setting('trakt_client_id'))}' autocomplete='off'><button>Save Client ID</button></form></div><div class='card'><h2>Add List</h2><form method='post' action='/sources/trakt/add'><label>Name</label><input name='name' required><div class='grid'><div><label>Trakt username</label><input name='username' required></div><div><label>List slug</label><input name='list_slug' required></div></div><div class='grid'><div><label>Target</label><select name='target_kind'><option value='playlist'>Auto Playlist</option><option value='collection'>Auto Collection</option></select></div><div><label>Refresh every hours</label><input type='number' min='1' max='168' name='refresh_hours' value='24'></div></div><button>Add List</button></form></div></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>List</th><th>Target</th><th>Last refresh</th><th>Matched</th><th>Error</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>"""
    return _page('Trakt Lists',body)


def _trakt_worker() -> None:
    while True:
        time.sleep(300)
        try:
            with _db() as conn:rows=conn.execute('SELECT * FROM trakt_lists WHERE enabled=1').fetchall()
            now=datetime.now(timezone.utc)
            for r in rows:
                due=True
                if r['last_refresh']:
                    try:due=(now-datetime.fromisoformat(str(r['last_refresh']).replace('Z','+00:00'))).total_seconds()>=max(3600,int(r['refresh_hours'] or 24)*3600)
                    except Exception:due=True
                if due:
                    try:_refresh_trakt_list(int(r['id']))
                    except Exception:pass
        except Exception:pass


# ---------------- auth, OIDC, JWT, streaming-only port ----------------

def _b64u(data:bytes)->str:return base64.urlsafe_b64encode(data).rstrip(b'=').decode()
def _b64ud(s:str)->bytes:return base64.urlsafe_b64decode(s+'='*((4-len(s)%4)%4))

def _sign_blob(payload:dict[str,Any],secret:str)->str:
    raw=_b64u(json.dumps(payload,separators=(',',':'),sort_keys=True).encode());sig=_b64u(hmac.new(secret.encode(),raw.encode(),hashlib.sha256).digest());return raw+'.'+sig

def _verify_blob(token:str,secret:str)->dict[str,Any]|None:
    try:
        raw,sig=token.split('.',1);want=_b64u(hmac.new(secret.encode(),raw.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,want):return None
        p=json.loads(_b64ud(raw));exp=int(p.get('exp') or 0)
        if exp and exp<int(time.time()):return None
        return p
    except Exception:return None

def _jwt_make(subject:str='iptv',hours:int=8760)->str:
    head=_b64u(json.dumps({'alg':'HS256','typ':'JWT'},separators=(',',':')).encode())
    body=_b64u(json.dumps({'sub':subject,'iat':int(time.time()),'exp':int(time.time()+hours*3600)},separators=(',',':')).encode())
    sig=_b64u(hmac.new(_setting('iptv_jwt_secret').encode(),f'{head}.{body}'.encode(),hashlib.sha256).digest())
    return f'{head}.{body}.{sig}'

def _jwt_verify(token:str)->bool:
    try:
        h,b,s=token.split('.');want=_b64u(hmac.new(_setting('iptv_jwt_secret').encode(),f'{h}.{b}'.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(s,want):return False
        p=json.loads(_b64ud(b));return int(p.get('exp') or 0)>=int(time.time())
    except Exception:return False

def _password_hash(password:str)->str:
    salt=secrets.token_bytes(16);iters=260000;dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,iters)
    return f'pbkdf2_sha256${iters}${_b64u(salt)}${_b64u(dk)}'

def _password_check(password:str,stored:str)->bool:
    try:
        _name,it,salt,want=stored.split('$');dk=hashlib.pbkdf2_hmac('sha256',password.encode(),_b64ud(salt),int(it));return hmac.compare_digest(_b64u(dk),want)
    except Exception:return False

def _session_make(user:str)->str:return _sign_blob({'sub':user,'exp':int(time.time()+86400*7)},_setting('auth_cookie_secret'))
def _session_user(request:Request)->str|None:
    p=_verify_blob(request.cookies.get('vipertv_session',''),_setting('auth_cookie_secret'))
    return str(p.get('sub')) if p else None

def _stream_path(path:str)->bool:
    return path.startswith('/stream/') or path.startswith('/iptv/') or path in {'/discover.json','/lineup.json','/lineup_status.json'}

def _security_page(msg:str='')->str:
    token=_jwt_make('iptv',24*365)
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Security & Network','Protect ViperTV management, issue signed IPTV access URLs, and reserve a streaming-only port.')+f"""
<div class='grid'><div class='card'><h2>Management authentication</h2><form method='post' action='/system/security/local'><label><input type='checkbox' name='enabled' value='1' {'checked' if _setting('auth_enabled')=='1' else ''}> Require authentication for management</label><label>Administrator username</label><input name='username' value='{_e(_setting('auth_admin_username','admin'))}'><label>New password (leave blank to keep existing)</label><input type='password' name='password'><button>Save Local Login</button></form></div>
<div class='card'><h2>OIDC / OpenID Connect</h2><form method='post' action='/system/security/oidc'><label><input type='checkbox' name='enabled' value='1' {'checked' if _setting('oidc_enabled')=='1' else ''}> Enable OIDC sign-in</label><label>Discovery URL</label><input name='discovery_url' value='{_e(_setting('oidc_discovery_url'))}' placeholder='https://auth.example/.well-known/openid-configuration'><label>Client ID</label><input name='client_id' value='{_e(_setting('oidc_client_id'))}'><label>Client secret</label><input type='password' name='client_secret' placeholder='leave blank to keep existing'><label>Allowed email/domain (optional)</label><input name='allowed' value='{_e(_setting('oidc_allowed'))}' placeholder='user@example.com or example.com'><button>Save OIDC</button></form></div></div>
<div class='grid'><div class='card'><h2>Protected IPTV / JWT</h2><form method='post' action='/system/security/iptv'><label><input type='checkbox' name='enabled' value='1' {'checked' if _setting('iptv_jwt_enabled')=='1' else ''}> Require signed access token for IPTV/stream endpoints</label><button>Save</button></form><p class='small muted'>Example one-year token:</p><code style='overflow-wrap:anywhere'>{_e(token)}</code><p><a class='button secondary' href='/iptv/channels.m3u?token={urllib.parse.quote(token)}'>Open tokenized M3U</a></p></div>
<div class='card'><h2>Streaming-only port</h2><form method='post' action='/system/security/port'><label>External port</label><input type='number' name='port' value='{_e(_setting('streaming_only_port'))}' placeholder='8410'><button>Save Port Rule</button></form><p class='small muted'>On Windows Standalone, restart ViperTV after setting this port. The bundled streaming-only proxy will listen on that port and forward only IPTV/M3U/XMLTV/HDHomeRun traffic; management pages return 404.</p></div></div>"""
    return _page('Security & Network',body)


def _oidc_discovery()->dict[str,Any]:
    url=_setting('oidc_discovery_url')
    if not url:raise RuntimeError('OIDC discovery URL is not configured')
    with urllib.request.urlopen(url,timeout=15) as r:return json.loads(r.read().decode())


def _oidc_allowed(info:dict[str,Any])->bool:
    allow=_setting('oidc_allowed').strip().casefold()
    if not allow:return True
    email=str(info.get('email') or '').casefold();sub=str(info.get('sub') or '').casefold()
    if '@' in allow:return email==allow
    return email.endswith('@'+allow) or sub==allow


# ---------------- scripted execution + client ----------------

def _script_root()->Path:
    default=str(_standalone_data_subdir('scheduler-scripts'))
    p=Path(_setting('scheduler_script_root',default));p.mkdir(parents=True,exist_ok=True);return p.resolve()

def _safe_script(path:str)->Path:
    p=Path(path);p=(p if p.is_absolute() else _script_root()/p).resolve();root=_script_root()
    if os.path.commonpath([str(p),str(root)])!=str(root):raise RuntimeError(f'Script must live under {root}')
    if not p.is_file():raise RuntimeError('Script file does not exist')
    return p

def _script_argv(row:Any)->list[str]:
    p=_safe_script(str(row['script_path']));interp=str(row['interpreter'] or 'auto').lower()
    try:args=json.loads(str(row['arguments_json'] or '[]'))
    except Exception:args=[]
    if not isinstance(args,list):args=[]
    args=list(map(str,args));suffix=p.suffix.lower()
    if interp=='python' or (interp=='auto' and suffix=='.py'):
        py=Path(sys.executable)
        if os.name=='nt' and py.name.lower()=='pythonw.exe' and py.with_name('python.exe').exists():py=py.with_name('python.exe')
        return [str(py),str(p),*args]
    if os.name=='nt':
        if interp=='powershell' or (interp=='auto' and suffix=='.ps1'):
            ps=shutil.which('powershell.exe') or shutil.which('pwsh.exe') or 'powershell.exe'
            return [ps,'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(p),*args]
        if interp in {'batch','shell'} or (interp=='auto' and suffix in {'.cmd','.bat'}):
            return ['cmd.exe','/d','/s','/c',subprocess.list2cmdline([str(p),*args])]
        if interp=='auto' and suffix in {'.sh','.bash'}:
            bash=shutil.which('bash.exe') or shutil.which('bash')
            if not bash:raise RuntimeError('A Bash executable is required to run .sh scripts on Windows')
            return [bash,str(p),*args]
    elif interp=='shell' or (interp=='auto' and suffix in {'.sh','.bash'}):
        return ['/bin/sh',str(p),*args]
    return [str(p),*args]

def _run_scheduler_script(script_id:int,run_id:str)->None:
    with _db() as conn:r=conn.execute('SELECT * FROM scheduler_scripts WHERE id=?',(script_id,)).fetchone()
    if not r:return
    started=time.time();env=os.environ.copy();root=str(Path(__file__).resolve().parent.parent);port=str(os.environ.get('VIPERTV_PORT','8409'));env.update({'VIPERTV_API_BASE':f'http://127.0.0.1:{port}','VIPERTV_API_TOKEN':_setting('scripted_api_token'),'VIPERTV_BUILD_ID':run_id,'VIPERTV_MODE':str(r['mode'] or 'build'),'VIPERTV_ARGS_JSON':str(r['arguments_json'] or '[]'),'PYTHONPATH':root})
    try:
        proc=subprocess.run(_script_argv(r),capture_output=True,text=True,timeout=max(5,min(3600,int(r['timeout_seconds'] or 120))),env=env,cwd=str(_script_root()),creationflags=(int(getattr(subprocess,'CREATE_NO_WINDOW',0)) if os.name=='nt' else 0))
        log=((proc.stdout or '')+('\n--- stderr ---\n'+proc.stderr if proc.stderr else ''))[-20000:];rc=int(proc.returncode);err=''
    except Exception as exc:log=str(exc);rc=-1;err=str(exc)
    with _db() as conn:conn.execute('UPDATE scheduler_scripts SET last_run=?,last_rc=?,last_log=?,updated_at=? WHERE id=?',(_now(),rc,log,_now(),script_id));conn.commit()
    with _SCRIPT_LOCK:_SCRIPT_RUNS[run_id]={'id':run_id,'script_id':script_id,'state':'done','rc':rc,'log':log,'seconds':round(time.time()-started,2)}

def _scripts_page(msg:str='')->str:
    root=_script_root()
    with _db() as conn:rows=conn.execute('SELECT * FROM scheduler_scripts ORDER BY name').fetchall()
    trs=''.join(f"<tr><td><b>{_e(r['name'])}</b><div class='small muted'><code>{_e(r['script_path'])}</code></div></td><td>{_e(r['mode'])}</td><td>{int(r['timeout_seconds'])}s</td><td>{_e(r['last_run'] or 'Never')}</td><td>{_e(r['last_rc'] if r['last_rc'] is not None else '—')}</td><td><form class='inline' method='post' action='/scheduling/script-runner/{r['id']}/run'><button>Run</button></form> <form class='inline' method='post' action='/scheduling/script-runner/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for r in rows) or "<tr><td colspan='6'>No executable scheduler scripts configured.</td></tr>"
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Script Runner','Execute trusted local Python, PowerShell, batch, or executable scheduler programs on the ViperTV Windows host. Scripts receive build ID, mode, arguments and REST API credentials as environment variables.',"<a class='button secondary' href='/scheduling/scripted'>Scripted Schedules</a>")+f"""
<div class='grid'><div class='card'><h2>Upload Script</h2><form method='post' enctype='multipart/form-data' action='/scheduling/script-runner/upload'><input type='file' name='upload' required><button>Upload to {_e(str(root))}</button></form></div><div class='card'><h2>Add Runner</h2><form method='post' action='/scheduling/script-runner/add'><label>Name</label><input name='name' required><label>Script path/name</label><input name='script_path' required placeholder='build_schedule.py'><div class='grid'><div><label>Interpreter</label><select name='interpreter'><option value='auto'>Auto</option><option value='python'>Python</option><option value='powershell'>PowerShell</option><option value='batch'>Batch / CMD</option><option value='shell'>Shell / Bash</option><option value='exec'>Executable</option></select></div><div><label>Mode</label><input name='mode' value='build'></div></div><label>Arguments JSON</label><input name='arguments_json' value='[]'><label>Timeout seconds</label><input type='number' name='timeout_seconds' value='120'><button>Add Runner</button></form></div></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>Runner</th><th>Mode</th><th>Timeout</th><th>Last run</th><th>RC</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>"""
    return _page('Script Runner',body)


# ---------------- scripted graphics controls ----------------

def _scripted_day_items_v140(channel_id:int)->list[dict[str,Any]]:
    items=[dict(x) for x in _BASE_SCRIPTED_DAY_ITEMS(channel_id)]
    ass=sa._scripted_assignment(channel_id)
    if not ass:return items
    today=datetime.now(G['local_tz']()).date() if callable(G.get('local_tz')) else date.today();bit=1<<today.weekday();day=today.isoformat()
    with _db() as conn:
        exact=conn.execute('''SELECT e.*,g.name graphic_name FROM scripted_graphics_events e JOIN graphics_elements g ON g.id=e.graphic_id WHERE e.schedule_id=? AND e.air_date=? ORDER BY start_minute,position,id''',(int(ass['schedule_id']),day)).fetchall()
        events=exact or conn.execute('''SELECT e.*,g.name graphic_name FROM scripted_graphics_events e JOIN graphics_elements g ON g.id=e.graphic_id WHERE e.schedule_id=? AND e.air_date IS NULL AND (e.day_mask & ?) != 0 ORDER BY start_minute,position,id''',(int(ass['schedule_id']),bit)).fetchall()
    active:set[str]=set();ei=0;cursor=0.0
    for item in items:
        minute=int(cursor//60)
        while ei<len(events) and int(events[ei]['start_minute'])<=minute:
            name=str(events[ei]['graphic_name']);action=str(events[ei]['action']).lower()
            if action=='on':active.add(name)
            else:active.discard(name)
            ei+=1
        if active:item['_graphics_names']=sorted(set(item.get('_graphics_names') or [])|active)
        cursor+=max(0,float(item.get('duration') or 0))
    return items


# ---------------- graphics test bench ----------------

def _graphics_test_page(msg:str='')->str:
    with _db() as conn:
        channels=conn.execute('SELECT id,number,name FROM channels WHERE enabled=1 ORDER BY CAST(number AS REAL),number').fetchall()
        graphics=conn.execute('SELECT id,name,kind,z_index FROM graphics_elements WHERE enabled=1 ORDER BY z_index,name').fetchall()
    copts=''.join(f"<option value='{c['id']}'>{_e(c['number'])} {_e(c['name'])}</option>" for c in channels)
    checks=' '.join(f"<label style='display:block'><input type='checkbox' name='graphic_id' value='{g['id']}'> {_e(g['name'])} <span class='muted small'>{_e(g['kind'])} z{g['z_index']}</span></label>" for g in graphics) or '<p>No enabled graphics.</p>'
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Graphics Test Bench','Render a short real-media preview with several Graphics Engine 2.0 layers active together. This never modifies the channel schedule.')+f"""
<div class='card'><form method='post' action='/system/graphics-test/run'><div class='grid'><div><label>Channel/source</label><select name='channel_id'>{copts}</select><label>Seconds</label><input type='number' name='seconds' min='2' max='30' value='8'></div><div><label>Graphics</label>{checks}</div></div><button>Render Test Preview</button></form></div>"""
    return _page('Graphics Test Bench',body)


def _render_graphics_test(channel_id:int,gids:list[int],seconds:int,job:str)->None:
    outdir=_standalone_data_subdir('graphics-tests');outfile=outdir/f'{job}.mp4'
    try:
        channel,items=G['channel_media'](channel_id)
        item=next((dict(x) for x in items if str(x.get('source_type'))!='gap'),None)
        if not item:raise RuntimeError('Channel has no playable item')
        with _db() as conn:names=[str(r['name']) for r in conn.execute('SELECT name FROM graphics_elements WHERE id IN (%s)'%','.join('?'*len(gids)),gids)] if gids else []
        item['_graphics_names']=names
        if item.get('source_type')=='plex':
            # Let the ordinary profiled path select direct-disk if available.
            cmd=G['_profiled_plex_part_command'](channel,item,0,*G['_plex_direct_part_source'](item)) if False else G['_profiled_local_command'](channel,item,0)
        elif item.get('source_type')=='external':cmd=G['_profiled_external_command'](channel,item,0)
        else:cmd=G['_profiled_local_command'](channel,item,0)
        cmd=list(cmd)
        # Replace station output with a finite MP4 preview.
        while len(cmd)>=2 and cmd[-2:]==['-f','mpegts']:cmd=cmd[:-2]
        if cmd and cmd[-1]=='pipe:1':cmd=cmd[:-1]
        # Most station commands end -f mpegts pipe:1; robustly trim that tail.
        if 'pipe:1' in cmd:cmd=cmd[:cmd.index('pipe:1')]
        if len(cmd)>=2 and cmd[-2:]==['-f','mpegts']:cmd=cmd[:-2]
        cmd += ['-t',str(max(2,min(30,seconds))),'-movflags','+faststart','-f','mp4',str(outfile)]
        proc=subprocess.run(cmd,capture_output=True,timeout=max(20,seconds+30))
        if proc.returncode!=0:raise RuntimeError(proc.stderr.decode(errors='ignore')[-1800:])
        with _GRAPHICS_LOCK:_GRAPHICS_TESTS[job]={'state':'done','file':str(outfile)}
    except Exception as exc:
        with _GRAPHICS_LOCK:_GRAPHICS_TESTS[job]={'state':'error','error':str(exc)}


# ---------------- relative date operators ----------------

def _parse_dateish(v:Any)->date|None:
    s=str(v or '').strip()
    if not s:return None
    for cand in (s[:10],re.sub(r'[^0-9]','',s)[:8]):
        for fmt in ('%Y-%m-%d','%Y%m%d'):
            try:return datetime.strptime(cand,fmt).date()
            except Exception:pass
    return None

def _days_value(value:str)->int|None:
    m=re.match(r'^\s*(\d+)\s*(?:d|day|days)?\s*$',value,re.I)
    return int(m.group(1)) if m else None

def _search_atom_v140(item:dict[str,Any],token:str)->bool:
    if ':' not in token:return _BASE_SEARCH_ATOM(item,token)
    field,value=token.split(':',1);field=field.casefold();value=value.strip().strip('"')
    today=date.today();released=_parse_dateish(item.get('air_date') or item.get('release_date') or item.get('originally_available_at'));added=_parse_dateish(item.get('added_at'))
    if field in {'released_inthelast','released_in_the_last'}:
        n=_days_value(value);return bool(released and n is not None and today-timedelta(days=n)<=released<=today)
    if field in {'added_inthelast','added_in_the_last'}:
        n=_days_value(value);return bool(added and n is not None and today-timedelta(days=n)<=added<=today)
    if field=='released_onthisday':return bool(released and released.month==today.month and released.day==today.day)
    if field=='added_onthisday':return bool(added and added.month==today.month and added.day==today.day)
    if field in {'released_before','released_after','added_before','added_after'}:
        want=_parse_dateish(value);actual=released if field.startswith('released') else added
        if not want or not actual:return False
        return actual<want if field.endswith('before') else actual>want
    return _BASE_SEARCH_ATOM(item,token)


# ---------------- sidebar/page decoration ----------------

def _page_shell_v140(title:str,body:str,extra_head:str='',extra_script:str='')->str:
    html=_BASE_PAGE_SHELL(title,body,extra_head,extra_script)
    # Add compact links without rewriting the huge page-shell template.
    links="""
<a href='/sources/remote-streams'>Remote Streams</a>
<a href='/sources/trakt'>Trakt Lists</a>
<a href='/scheduling/script-runner'>Script Runner</a>
<a href='/system/graphics-test'>Graphics Test Bench</a>
<a href='/system/security'>Security & Network</a>
"""
    marker="<a href='/system/ffmpeg-profiles'>FFmpeg Profiles</a>"
    if marker in html:html=html.replace(marker,marker+links,1)
    else:
        marker='</nav>'
        if marker in html:html=html.replace(marker,links+marker,1)
    return html



class _SecurePlaylistRewriteMiddleware:
    """Raw ASGI response rewriter so tokenized M3U/HLS child URLs keep auth.

    Starlette's function middleware wraps responses as StreamingResponse, so
    rewriting `response.body` there is unreliable. This wrapper edits body
    chunks at the ASGI send layer and therefore also works for streaming route
    wrappers and ordinary PlainTextResponse manifests.
    """
    def __init__(self, app): self.app=app
    async def __call__(self, scope, receive, send):
        if scope.get('type')!='http':
            return await self.app(scope,receive,send)
        raw_path=str(scope.get('path') or '')
        query=urllib.parse.parse_qs((scope.get('query_string') or b'').decode(errors='ignore'))
        token=str((query.get('token') or [''])[0])
        m=re.match(r'^/iptv/access/([^/]+)',raw_path)
        if m: token=urllib.parse.unquote(m.group(1))
        if not token or not _jwt_verify(token):
            return await self.app(scope,receive,send)
        start_msg=None; chunks=[]
        async def capture(message):
            nonlocal start_msg
            if message['type']=='http.response.start':
                start_msg=message;return
            if message['type']=='http.response.body':
                chunks.append(message.get('body',b''))
                if message.get('more_body',False):return
                headers=list((start_msg or {'headers':[]}).get('headers',[]));ctype=''
                for k,v in headers:
                    if k.lower()==b'content-type':ctype=v.decode(errors='ignore').lower()
                body=b''.join(chunks)
                if 'mpegurl' in ctype or raw_path.endswith('.m3u') or raw_path.endswith('.m3u8'):
                    try:
                        text=body.decode('utf-8');prefix='/iptv/access/'+urllib.parse.quote(token,safe='')
                        hdrs={k.decode().lower():v.decode() for k,v in scope.get('headers',[])}
                        host=hdrs.get('host','');scheme=scope.get('scheme','http');base=f'{scheme}://{host}' if host else ''
                        if base:
                            text=text.replace(base+'/iptv/',base+prefix+'/iptv/').replace(base+'/stream/',base+prefix+'/stream/')
                        out=[]
                        for line in text.splitlines():
                            st=line.strip()
                            if st.startswith('/') and not st.startswith(prefix+'/'):line=prefix+st
                            line=re.sub(r'URI="/(?!iptv/access/)([^"]+)"',lambda mm:f'URI="{prefix}/{mm.group(1)}"',line)
                            out.append(line)
                        body=('\n'.join(out)+'\n').encode()
                        headers=[(k,v) for k,v in headers if k.lower()!=b'content-length']
                        headers.append((b'content-length',str(len(body)).encode()))
                    except Exception:pass
                await send({'type':'http.response.start','status':(start_msg or {}).get('status',200),'headers':headers})
                await send({'type':'http.response.body','body':body,'more_body':False})
        return await self.app(scope,receive,capture)

# ---------------- route install ----------------

def install_v140(app, main_globals:dict[str,Any])->None:
    global G,_BASE_CHANNEL_MEDIA,_BASE_PROFILED_LOCAL,_BASE_SCRIPTED_DAY_ITEMS,_BASE_SEARCH_ATOM,_BASE_IMAGES_PAGE,_BASE_PAGE_SHELL,_BG_STARTED
    G=main_globals
    app.add_middleware(_SecurePlaylistRewriteMiddleware)
    base_init=G['init_v12_db']
    def init_all():
        base_init();init_v140_db()
        global _BG_STARTED
        if not _BG_STARTED:
            _BG_STARTED=True
            threading.Thread(target=_trakt_worker,name='vipertv-trakt-refresh',daemon=True).start()
    G['init_v12_db']=init_all

    _BASE_CHANNEL_MEDIA=G['channel_media'];G['channel_media']=_channel_media_v140
    _BASE_PROFILED_LOCAL=G['_profiled_local_command'];G['_profiled_local_command']=_profiled_local_v140
    _BASE_SCRIPTED_DAY_ITEMS=sa._scripted_day_items;sa._scripted_day_items=_scripted_day_items_v140
    _BASE_SEARCH_ATOM=G['_search_atom'];G['_search_atom']=_search_atom_v140;mp.search_atom=_search_atom_v140
    _BASE_IMAGES_PAGE=sm.images_page;sm.images_page=_images_page_v140
    _BASE_PAGE_SHELL=G['page_shell'];G['page_shell']=_page_shell_v140

    @app.post('/media/images/folder-duration/add')
    def image_folder_add(library_id:str=Form(''),folder_path:str=Form(...),seconds:float=Form(10)):
        G['safe_backup_before_change']();lid=int(library_id) if library_id.isdigit() else None;seconds=max(1,min(86400,float(seconds)));path=_norm_path(folder_path)
        with _db() as conn:conn.execute('''INSERT INTO image_folder_durations(library_id,folder_path,duration_seconds,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(library_id,folder_path) DO UPDATE SET duration_seconds=excluded.duration_seconds,enabled=1,updated_at=excluded.updated_at''',(lid,path,seconds,1,_now(),_now()));conn.commit()
        try:G['_v124_mark_index_dirty']('Image folder durations changed')
        except Exception:pass
        return RedirectResponse('/media/images?msg='+G['quote']('Folder duration rule saved.'),303)

    @app.post('/media/images/folder-duration/{rid}/delete')
    def image_folder_delete(rid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM image_folder_durations WHERE id=?',(rid,));conn.commit()
        return RedirectResponse('/media/images?msg=Folder+duration+rule+deleted',303)

    @app.get('/sources/remote-streams',response_class=HTMLResponse)
    def remote_streams(msg:str=''):return _remote_streams_page(msg)
    @app.post('/sources/remote-streams/add')
    def remote_add(number:str=Form('900'),name:str=Form(...),input_kind:str=Form('url'),stream_behavior:str=Form('live'),stream_url:str=Form(''),command_json:str=Form(''),scheduled_duration:str=Form('')):
        G['safe_backup_before_change']();dur=float(scheduled_duration) if scheduled_duration.strip() else None
        if input_kind=='command':
            try:argv=json.loads(command_json);assert isinstance(argv,list) and argv
            except Exception:return RedirectResponse('/sources/remote-streams?msg='+G['quote']('Command must be a JSON argv array.'),303)
        with _db() as conn:
            conn.execute('''INSERT INTO live_streams(number,name,stream_url,logo_url,group_name,user_agent,referer,enabled,created_at,updated_at,input_kind,command_json,stream_behavior,scheduled_duration) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(number.strip(),name.strip(),stream_url.strip(),None,'Remote Streams',None,None,1,_now(),_now(),input_kind,command_json.strip() or None,stream_behavior,dur));conn.commit()
        try:G['_v124_mark_index_dirty']('Remote stream definitions changed')
        except Exception:pass
        return RedirectResponse('/sources/remote-streams?msg=Remote+stream+added',303)
    @app.get('/sources/remote-streams/{rid}',response_class=HTMLResponse)
    def remote_edit(rid:int,msg:str=''):return _remote_stream_edit(rid,msg)
    @app.post('/sources/remote-streams/{rid}/save')
    def remote_save(rid:int,number:str=Form(''),name:str=Form(...),input_kind:str=Form('url'),stream_behavior:str=Form('live'),stream_url:str=Form(''),command_json:str=Form(''),scheduled_duration:str=Form(''),enabled:int=Form(0)):
        dur=float(scheduled_duration) if scheduled_duration.strip() else None;G['safe_backup_before_change']()
        with _db() as conn:conn.execute('''UPDATE live_streams SET number=?,name=?,stream_url=?,input_kind=?,command_json=?,stream_behavior=?,scheduled_duration=?,enabled=?,updated_at=? WHERE id=?''',(number.strip(),name.strip(),stream_url.strip(),input_kind,command_json.strip() or None,stream_behavior,dur,1 if enabled else 0,_now(),rid));conn.commit()
        try:G['_v124_mark_index_dirty']('Remote stream definitions changed')
        except Exception:pass
        return RedirectResponse(f'/sources/remote-streams/{rid}?msg=Saved',303)

    @app.get('/sources/trakt',response_class=HTMLResponse)
    def trakt_page(msg:str=''):return _trakt_page(msg)
    @app.post('/sources/trakt/settings')
    def trakt_settings(client_id:str=Form('')):_set_setting('trakt_client_id',client_id.strip());return RedirectResponse('/sources/trakt?msg=Trakt+settings+saved',303)
    @app.post('/sources/trakt/add')
    def trakt_add(name:str=Form(...),username:str=Form(...),list_slug:str=Form(...),target_kind:str=Form('playlist'),refresh_hours:int=Form(24)):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:conn.execute('INSERT INTO trakt_lists(name,username,list_slug,target_kind,refresh_hours,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',(name.strip(),username.strip(),list_slug.strip(),target_kind if target_kind in {'playlist','collection'} else 'playlist',max(1,min(168,refresh_hours)),1,_now(),_now()));conn.commit()
        except sqlite3.IntegrityError:return RedirectResponse('/sources/trakt?msg='+G['quote']('That Trakt list name already exists.'),303)
        return RedirectResponse('/sources/trakt?msg=Trakt+list+added',303)
    @app.post('/sources/trakt/{lid}/refresh')
    def trakt_refresh(lid:int):
        try:r=_refresh_trakt_list(lid);msg=f"Refreshed: {r['matched']} of {r['items']} Trakt items matched."
        except Exception as exc:msg='Refresh failed: '+str(exc)
        return RedirectResponse('/sources/trakt?msg='+G['quote'](msg),303)
    @app.post('/sources/trakt/{lid}/delete')
    def trakt_delete(lid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM trakt_lists WHERE id=?',(lid,));conn.commit()
        return RedirectResponse('/sources/trakt?msg=Trakt+definition+deleted',303)

    @app.get('/system/security',response_class=HTMLResponse)
    def security_page(msg:str=''):return _security_page(msg)
    @app.post('/system/security/local')
    def security_local(enabled:int=Form(0),username:str=Form('admin'),password:str=Form('')):
        _set_setting('auth_admin_username',username.strip() or 'admin')
        if password:_set_setting('auth_admin_password_hash',_password_hash(password))
        if enabled and not _setting('auth_admin_password_hash') and _setting('oidc_enabled')!='1':return RedirectResponse('/system/security?msg='+G['quote']('Set a password or enable OIDC before requiring authentication.'),303)
        _set_setting('auth_enabled','1' if enabled else '0');return RedirectResponse('/system/security?msg=Management+authentication+saved',303)
    @app.post('/system/security/oidc')
    def security_oidc(enabled:int=Form(0),discovery_url:str=Form(''),client_id:str=Form(''),client_secret:str=Form(''),allowed:str=Form('')):
        _set_setting('oidc_enabled','1' if enabled else '0');_set_setting('oidc_discovery_url',discovery_url.strip());_set_setting('oidc_client_id',client_id.strip());_set_setting('oidc_allowed',allowed.strip())
        if client_secret:_set_setting('oidc_client_secret',client_secret)
        return RedirectResponse('/system/security?msg=OIDC+settings+saved',303)
    @app.post('/system/security/iptv')
    def security_iptv(enabled:int=Form(0)):_set_setting('iptv_jwt_enabled','1' if enabled else '0');return RedirectResponse('/system/security?msg=IPTV+protection+saved',303)
    @app.post('/system/security/port')
    def security_port(port:str=Form('')):
        p=str(int(port)) if port.strip().isdigit() and 1<=int(port)<=65535 else ''
        _set_setting('streaming_only_port',p);return RedirectResponse('/system/security?msg=Streaming-only+port+rule+saved',303)

    @app.get('/auth/login',response_class=HTMLResponse)
    def login_page(request:Request,msg:str=''):
        oidc="<a class='button secondary' href='/auth/oidc/login'>Sign in with OpenID Connect</a>" if _setting('oidc_enabled')=='1' else ''
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+f"<div class='card' style='max-width:520px;margin:60px auto'><h1>ViperTV Sign In</h1><form method='post' action='/auth/login'><label>Username</label><input name='username' autofocus><label>Password</label><input type='password' name='password'><button>Sign In</button></form><p>{oidc}</p></div>"
        return _BASE_PAGE_SHELL('Sign In',body)
    @app.post('/auth/login')
    def login_submit(username:str=Form(''),password:str=Form('')):
        if username==_setting('auth_admin_username','admin') and _password_check(password,_setting('auth_admin_password_hash')):
            r=RedirectResponse('/',303);r.set_cookie('vipertv_session',_session_make(username),httponly=True,samesite='lax',max_age=86400*7);return r
        return RedirectResponse('/auth/login?msg='+G['quote']('Invalid username or password.'),303)
    @app.get('/auth/logout')
    def logout():r=RedirectResponse('/auth/login',303);r.delete_cookie('vipertv_session');return r
    @app.get('/auth/oidc/login')
    def oidc_login(request:Request):
        cfg=_oidc_discovery();state=secrets.token_urlsafe(24);redirect=str(request.base_url).rstrip('/')+'/auth/oidc/callback';params={'client_id':_setting('oidc_client_id'),'response_type':'code','scope':'openid profile email','redirect_uri':redirect,'state':state}
        r=RedirectResponse(str(cfg['authorization_endpoint'])+'?'+urllib.parse.urlencode(params),302);r.set_cookie('vipertv_oidc_state',_sign_blob({'s':state,'exp':int(time.time()+600)},_setting('auth_cookie_secret')),httponly=True,samesite='lax',max_age=600);return r
    @app.get('/auth/oidc/callback')
    def oidc_callback(request:Request,code:str='',state:str=''):
        p=_verify_blob(request.cookies.get('vipertv_oidc_state',''),_setting('auth_cookie_secret'))
        if not p or str(p.get('s'))!=state:raise HTTPException(400,'OIDC state validation failed')
        cfg=_oidc_discovery();redirect=str(request.base_url).rstrip('/')+'/auth/oidc/callback';form=urllib.parse.urlencode({'grant_type':'authorization_code','code':code,'redirect_uri':redirect,'client_id':_setting('oidc_client_id'),'client_secret':_setting('oidc_client_secret')}).encode();req=urllib.request.Request(str(cfg['token_endpoint']),data=form,headers={'Content-Type':'application/x-www-form-urlencoded','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=20) as rr:tok=json.loads(rr.read().decode())
        access=str(tok.get('access_token') or '');uinfo=str(cfg.get('userinfo_endpoint') or '')
        if not access or not uinfo:raise HTTPException(400,'OIDC provider did not return usable access token/userinfo endpoint')
        req2=urllib.request.Request(uinfo,headers={'Authorization':'Bearer '+access,'Accept':'application/json'})
        with urllib.request.urlopen(req2,timeout=20) as rr:info=json.loads(rr.read().decode())
        if not _oidc_allowed(info):raise HTTPException(403,'This OIDC identity is not allowed')
        who=str(info.get('email') or info.get('preferred_username') or info.get('sub') or 'oidc-user');r=RedirectResponse('/',303);r.set_cookie('vipertv_session',_session_make(who),httponly=True,samesite='lax',max_age=86400*7);r.delete_cookie('vipertv_oidc_state');return r

    @app.get('/scheduling/script-runner',response_class=HTMLResponse)
    def scripts(msg:str=''):return _scripts_page(msg)
    @app.post('/scheduling/script-runner/upload')
    async def script_upload(upload:UploadFile=File(...)):
        name=Path(upload.filename or 'script.py').name;p=_script_root()/name;data=await upload.read()
        if len(data)>2_000_000:raise HTTPException(413,'Script is too large')
        p.write_bytes(data);os.chmod(p,0o750);return RedirectResponse('/scheduling/script-runner?msg='+G['quote']('Uploaded '+name),303)
    @app.post('/scheduling/script-runner/add')
    def script_add(name:str=Form(...),script_path:str=Form(...),interpreter:str=Form('auto'),arguments_json:str=Form('[]'),mode:str=Form('build'),timeout_seconds:int=Form(120)):
        _safe_script(script_path)
        try:args=json.loads(arguments_json);assert isinstance(args,list)
        except Exception:raise HTTPException(400,'Arguments must be a JSON array')
        with _db() as conn:conn.execute('INSERT INTO scheduler_scripts(name,script_path,interpreter,arguments_json,mode,timeout_seconds,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(name.strip(),script_path.strip(),interpreter,arguments_json,mode.strip() or 'build',max(5,min(3600,timeout_seconds)),1,_now(),_now()));conn.commit()
        return RedirectResponse('/scheduling/script-runner?msg=Runner+added',303)
    @app.post('/scheduling/script-runner/{sid}/run')
    def script_run(sid:int):
        run=uuid.uuid4().hex
        with _SCRIPT_LOCK:_SCRIPT_RUNS[run]={'id':run,'script_id':sid,'state':'running'}
        threading.Thread(target=_run_scheduler_script,args=(sid,run),daemon=True).start();return RedirectResponse('/scheduling/script-runner?msg='+G['quote']('Script started. Run ID '+run[:8]),303)
    @app.get('/api/v1/scripted/runs/{run_id}')
    def script_run_status(request:Request,run_id:str):
        # reuse scripted API token authorization
        sa._api_authorized(request)
        with _SCRIPT_LOCK:r=_SCRIPT_RUNS.get(run_id)
        if not r:raise HTTPException(404,'Run not found')
        return r
    @app.post('/scheduling/script-runner/{sid}/delete')
    def script_delete(sid:int):
        with _db() as conn:conn.execute('DELETE FROM scheduler_scripts WHERE id=?',(sid,));conn.commit()
        return RedirectResponse('/scheduling/script-runner?msg=Runner+deleted',303)

    @app.post('/api/v1/scripted/schedules/{sid}/graphics-events')
    async def scripted_graphics(request:Request,sid:int):
        sa._api_authorized(request);data=await request.json();events=data.get('events')
        if not isinstance(events,list):raise HTTPException(400,'events must be an array')
        norm=[]
        with _db() as conn:
            for pos,x in enumerate(events):
                gid=int(x.get('graphic_id') or 0);gr=conn.execute('SELECT id FROM graphics_elements WHERE id=?',(gid,)).fetchone()
                if not gr:raise HTTPException(400,f'Unknown graphic_id {gid}')
                st=str(x.get('start') or '00:00');m=re.match(r'^(\d{1,2}):(\d{2})$',st)
                if not m:raise HTTPException(400,f'Invalid start {st}')
                minute=int(m.group(1))*60+int(m.group(2));act=str(x.get('action') or 'on').lower()
                if act not in {'on','off'}:raise HTTPException(400,'action must be on/off')
                air=str(x.get('date') or '').strip() or None;days=x.get('days') or ['mon','tue','wed','thu','fri','sat','sun'];mask=0;names=['mon','tue','wed','thu','fri','sat','sun']
                for d in days:
                    if str(d).lower() in names:mask|=1<<names.index(str(d).lower())
                norm.append((sid,air,mask or 127,minute,gid,act,pos,_now()))
            conn.execute('BEGIN IMMEDIATE');conn.execute('DELETE FROM scripted_graphics_events WHERE schedule_id=?',(sid,));conn.executemany('INSERT INTO scripted_graphics_events(schedule_id,air_date,day_mask,start_minute,graphic_id,action,position,created_at) VALUES(?,?,?,?,?,?,?,?)',norm);conn.commit()
        return {'ok':True,'events':len(norm)}
    @app.get('/api/v1/scripted/schedules/{sid}/graphics-events')
    def scripted_graphics_get(request:Request,sid:int):
        sa._api_authorized(request)
        with _db() as conn:rows=conn.execute('SELECT e.*,g.name graphic_name FROM scripted_graphics_events e JOIN graphics_elements g ON g.id=e.graphic_id WHERE schedule_id=? ORDER BY COALESCE(air_date,\'\'),start_minute,position,id',(sid,)).fetchall()
        return {'events':[dict(r) for r in rows]}

    @app.get('/system/graphics-test',response_class=HTMLResponse)
    def graphics_test(msg:str=''):return _graphics_test_page(msg)
    @app.post('/system/graphics-test/run')
    def graphics_test_run(channel_id:int=Form(...),graphic_id:list[int]=Form(default=[]),seconds:int=Form(8)):
        job=uuid.uuid4().hex
        with _GRAPHICS_LOCK:_GRAPHICS_TESTS[job]={'state':'running'}
        threading.Thread(target=_render_graphics_test,args=(channel_id,graphic_id,seconds,job),daemon=True).start()
        return RedirectResponse(f'/system/graphics-test/view/{job}',303)
    @app.get('/system/graphics-test/view/{job}',response_class=HTMLResponse)
    def graphics_test_view(job:str):
        with _GRAPHICS_LOCK:r=dict(_GRAPHICS_TESTS.get(job) or {})
        if not r:return _page('Graphics Test','<div class=card>Test job not found.</div>')
        if r.get('state')=='running':body=f"<div class='card'><h2>Rendering preview…</h2><progress style='width:100%'></progress><script>setTimeout(()=>location.reload(),1200)</script></div>"
        elif r.get('state')=='error':body=f"<div class='card'><h2>Render failed</h2><pre>{_e(r.get('error'))}</pre></div>"
        else:body=f"<div class='card'><h2>Graphics Preview</h2><video controls autoplay style='width:100%;max-height:70vh' src='/system/graphics-test/output/{job}.mp4'></video></div>"
        return _page('Graphics Test',body)
    @app.get('/system/graphics-test/output/{job}.mp4')
    def graphics_test_output(job:str):
        with _GRAPHICS_LOCK:r=_GRAPHICS_TESTS.get(job) or {}
        p=Path(str(r.get('file') or ''))
        if not p.is_file():raise HTTPException(404,'Preview not ready')
        return FileResponse(p,media_type='video/mp4')

    # HTTP middleware is installed last so it sees every existing route.
    @app.middleware('http')
    async def v140_security_middleware(request:Request,call_next):
        path=request.url.path
        # Streaming-only listener gate. OMV may map e.g. 8410:8409.
        configured=_setting('streaming_only_port')
        port=str(request.headers.get('x-forwarded-port') or request.url.port or '')
        if configured and port==configured and not (_stream_path(path) or path=='/healthz'):
            return PlainTextResponse('Not Found',status_code=404)

        # Secure-prefix transport for clients that cannot propagate query params
        # through child HLS requests: /iptv/access/<JWT>/stream/...
        access_token=''
        auth_header=str(request.headers.get('authorization') or '')
        bearer=auth_header[7:].strip() if auth_header.lower().startswith('bearer ') else ''
        m=re.match(r'^/iptv/access/([^/]+)(/.*)$',path)
        if m:
            access_token=urllib.parse.unquote(m.group(1));
            if not _jwt_verify(access_token):return PlainTextResponse('Unauthorized',status_code=401)
            request.scope['path']=m.group(2);path=request.scope['path'];_IPTV_TOKEN_CTX.set(access_token)
        elif request.query_params.get('token') and _jwt_verify(str(request.query_params.get('token'))):
            access_token=str(request.query_params.get('token'));_IPTV_TOKEN_CTX.set(access_token)
        elif bearer and _jwt_verify(bearer):
            access_token=bearer;_IPTV_TOKEN_CTX.set(access_token)

        auth_user=_session_user(request)
        scripted_token=_setting('scripted_api_token')
        scripted_api_ok=bool(path.startswith('/api/v1/scripted/') and bearer and scripted_token and hmac.compare_digest(bearer,scripted_token))
        if _setting('iptv_jwt_enabled')=='1' and _stream_path(path) and not access_token and not auth_user:
            return PlainTextResponse('Signed IPTV token required',status_code=401)

        if _setting('auth_enabled')=='1' and not auth_user and not scripted_api_ok and not path.startswith('/auth/') and path!='/healthz' and not (_stream_path(path) and access_token):
            if path.startswith('/api/'):return JSONResponse({'error':'authentication required'},status_code=401)
            return RedirectResponse('/auth/login?next='+urllib.parse.quote(str(request.url.path)),303)

        return await call_next(request)
