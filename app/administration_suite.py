from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

from . import media_security_completion as sec

G: dict[str, Any] = {}
_BASE_PAGE_SHELL = None
_BASE_COMMANDS: dict[str, Any] = {}
_COMMAND_HISTORY: dict[int, dict[str, Any]] = {}
_COMMAND_LOCK = threading.RLock()
_STARTED_AT = time.time()

CONFIG_TABLES = [
    'channels','channel_selections','external_channel_selections','channel_collections','channel_people_filters',
    'collections','collection_selections','multi_collection_members','playlists','playlist_items',
    'classic_schedules','classic_schedule_items','classic_playouts','schedules','schedule_items','schedule_templates',
    'filler_presets','channel_fillers','channel_templates','playout_state',
    'blocks','block_items','block_templates','block_template_items','decos','deco_items',
    'deco_templates','deco_template_items','playout_templates','playout_template_rules',
    'sequential_schedules','sequential_playouts','marathons','advanced_filler_presets',
    'scripted_schedules','scripted_schedule_items','scripted_playouts','scripted_graphics_events','scheduler_scripts',
    'graphics_elements','channel_graphics','stream_selector_profiles','stream_selector_rules','channel_stream_selectors',
    'ffmpeg_profiles','channel_ffmpeg_profiles','plex_path_replacements','external_path_replacements',
    'image_folder_durations','trakt_lists','live_streams'
]
SAFE_SETTING_PREFIXES = (
    'image_','hardware_','ffmpeg_','search_','plex_auto_','streaming_','scheduler_','browser_','guide_','setup_'
)
SECRET_WORDS = ('token','secret','password','api_key','apikey','client_id','auth_cookie','jwt')
FORBIDDEN_UPDATE_PARTS = {'compose.yml','vipertv.yml','.env','vipertv.db'}


def _db(): return G['db']()
def _e(v: Any) -> str: return G['e'](v)
def _now() -> str: return G['utcnow_iso']()
def _setting(k: str, d: str='') -> str:
    try: return str(G['get_setting'](k,d) or d)
    except Exception: return d

def _set(k: str, v: Any) -> None: G['set_setting'](k,str(v))
def _page(title: str, body: str, extra_head: str='', extra_script: str='') -> str: return G['page_shell'](title,body,extra_head,extra_script)
def _heading(title: str, subtitle: str, actions: str='') -> str: return G['_page_heading'](title,subtitle,actions)

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone())

def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r['name']) for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def init_v150_db() -> None:
    with _db() as conn:
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS admin_users(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'viewer',
          enabled INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS audit_log(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          created_at TEXT NOT NULL,
          username TEXT,
          role TEXT,
          method TEXT NOT NULL,
          path TEXT NOT NULL,
          status_code INTEGER,
          remote_addr TEXT,
          details TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
        CREATE TABLE IF NOT EXISTS system_jobs(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued',
          total INTEGER NOT NULL DEFAULT 0,
          checked INTEGER NOT NULL DEFAULT 0,
          found INTEGER NOT NULL DEFAULT 0,
          message TEXT,
          result_json TEXT,
          created_at TEXT NOT NULL,
          started_at TEXT,
          finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS media_integrity_issues(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          scan_id INTEGER,
          source_type TEXT NOT NULL,
          source_id INTEGER,
          issue_type TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'warning',
          title TEXT,
          path TEXT,
          details TEXT,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_integrity_scan ON media_integrity_issues(scan_id,severity,issue_type);
        CREATE TABLE IF NOT EXISTS metadata_repair_queue(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source_type TEXT NOT NULL,
          source_id INTEGER NOT NULL,
          library_id INTEGER,
          title TEXT,
          issue TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'open',
          attempts INTEGER NOT NULL DEFAULT 0,
          last_error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(source_type,source_id,issue)
        );
        CREATE TABLE IF NOT EXISTS named_snapshots(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          file_path TEXT NOT NULL UNIQUE,
          size_bytes INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          note TEXT
        );
        CREATE TABLE IF NOT EXISTS update_packages(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          version TEXT,
          filename TEXT NOT NULL,
          file_path TEXT NOT NULL UNIQUE,
          sha256 TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'staged',
          notes TEXT,
          created_at TEXT NOT NULL
        );
        ''')
        legacy_user=_setting('auth_admin_username','admin').strip() or 'admin'
        legacy_hash=_setting('auth_admin_password_hash','')
        count=int(conn.execute('SELECT COUNT(*) n FROM admin_users').fetchone()['n'] or 0)
        if count==0 and legacy_hash:
            conn.execute('INSERT OR IGNORE INTO admin_users(username,password_hash,role,enabled,created_at,updated_at) VALUES(?,?,\'admin\',1,?,?)',(legacy_user,legacy_hash,_now(),_now()))
        conn.commit()


def _role_for_user(username: str | None) -> str:
    if not username: return 'anonymous'
    legacy=_setting('auth_admin_username','admin')
    if username==legacy: return 'admin'
    with _db() as conn:
        row=conn.execute('SELECT role,enabled FROM admin_users WHERE username=?',(username,)).fetchone()
    if row and int(row['enabled'] or 0): return str(row['role'] or 'viewer')
    return _setting('oidc_default_role','viewer') if _setting('oidc_enabled')=='1' else 'viewer'


def _audit(username: str, role: str, method: str, path: str, status: int, remote: str='', details: str='') -> None:
    try:
        with _db() as conn:
            conn.execute('INSERT INTO audit_log(created_at,username,role,method,path,status_code,remote_addr,details) VALUES(?,?,?,?,?,?,?,?)',(_now(),username,role,method,path,int(status),remote,details[:1000]));conn.commit()
    except Exception: pass


def _login_user(username: str, password: str) -> bool:
    with _db() as conn:
        row=conn.execute('SELECT * FROM admin_users WHERE username=? AND enabled=1',(username,)).fetchone()
        if row and sec._password_check(password,str(row['password_hash'] or '')):
            conn.execute('UPDATE admin_users SET last_login=?,updated_at=? WHERE id=?',(_now(),_now(),int(row['id'])));conn.commit();return True
    return username==_setting('auth_admin_username','admin') and sec._password_check(password,_setting('auth_admin_password_hash',''))


def _restricted(role: str, method: str, path: str) -> bool:
    if role=='admin': return False
    if role=='anonymous': return False  # v1.4 auth middleware handles unauthenticated requests
    admin_prefixes=('/admin/','/system/update','/system/config','/system/snapshots','/system/security')
    if any(path.startswith(p) for p in admin_prefixes): return True
    if role=='viewer' and method not in {'GET','HEAD','OPTIONS'}: return True
    if role=='viewer' and path.startswith('/maintenance'): return True
    if role=='editor' and (path.startswith('/maintenance/restore') or path.startswith('/maintenance/upload-restore')): return True
    return False


async def _admin_middleware(request: Request, call_next):
    path=request.url.path; method=request.method.upper()
    # Replace v1.4's single-user POST login with a backward-compatible multi-user handler.
    if path=='/auth/login' and method=='POST':
        raw=await request.body(); form=urllib.parse.parse_qs(raw.decode(errors='ignore'))
        username=str((form.get('username') or [''])[0]); password=str((form.get('password') or [''])[0])
        if _login_user(username,password):
            r=RedirectResponse('/',303);r.set_cookie('vipertv_session',sec._session_make(username),httponly=True,samesite='lax',max_age=86400*7)
            _audit(username,_role_for_user(username),'LOGIN',path,303,request.client.host if request.client else '')
            return r
        return RedirectResponse('/auth/login?msg='+urllib.parse.quote('Invalid username or password.'),303)
    user=sec._session_user(request); role=_role_for_user(user)
    if user and _restricted(role,method,path):
        return PlainTextResponse('Forbidden for your ViperTV role',403)
    response=await call_next(request)
    if method in {'POST','PUT','PATCH','DELETE'} and path!='/auth/login':
        _audit(user or '',role,method,path,int(getattr(response,'status_code',0) or 0),request.client.host if request.client else '')
    return response


def _sanitize_cmd(cmd: list[str]) -> list[str]:
    out=[]
    for a in map(str,cmd):
        a=re.sub(r'(?i)(X-Plex-Token|api_key|token)=([^&\s]+)',r'\1=REDACTED',a)
        out.append(a)
    return out


def _wrap_command(name: str) -> None:
    fn=G.get(name)
    if not callable(fn) or name in _BASE_COMMANDS: return
    _BASE_COMMANDS[name]=fn
    def wrapped(*args,**kwargs):
        cmd=fn(*args,**kwargs)
        try:
            channel=args[0] if args else None
            cid=int(channel['id']) if channel is not None and 'id' in channel.keys() else 0
            if cid:
                with _COMMAND_LOCK:
                    _COMMAND_HISTORY[cid]={'at':_now(),'builder':name,'command':_sanitize_cmd(list(cmd))}
        except Exception: pass
        return cmd
    G[name]=wrapped


def _nav_page_shell(title: str, body: str, extra_head: str='', extra_script: str='') -> str:
    html=_BASE_PAGE_SHELL(title,body,extra_head,extra_script)
    entries=[
      ('/setup','⚑','Setup Wizard'),('/system/health','♥','System Health'),('/system/diagnostics','⌁','Stream Diagnostics'),
      ('/system/media-integrity','✓','Media Integrity'),('/system/duplicates','≡','Duplicates'),('/system/metadata-repair','✚','Metadata Repair'),
      ('/system/config','⇄','Import / Export'),('/system/snapshots','◫','Snapshots'),('/system/update','⇧','Update Manager'),
      ('/admin/users','♙','Users & Roles'),('/admin/audit','☷','Audit Log'),('/system/about','ⓘ','About / System Info'),
      ('/system/security','◆','Security & Network'),('/sources/remote-streams','◉','Remote Streams'),('/sources/trakt','↻','Trakt Lists'),('/scheduling/script-runner','</>','Script Runner'),('/system/graphics-test','▧','Graphics Test Bench')]
    marker="<a class='nav-item' data-match='^/maintenance' href='/maintenance'>"
    if marker in html:
        links=''.join(f"<a class='nav-item' data-match='^{re.escape(url)}' href='{url}'><span class='nav-icon'>{icon}</span>{label}</a>" for url,icon,label in entries if f"href='{url}'" not in html)
        html=html.replace(marker,links+marker,1)
    if title=='Dashboard' and _setting('setup_completed','0')!='1':
        banner="<div class='card' style='border-color:#52b788'><h2>Finish ViperTV Setup</h2><p>The v1.5 setup wizard can verify storage, sources, hardware, metadata and your first channel.</p><a class='button' href='/setup'>Open Setup Wizard</a></div>"
        needle="<main class='content'>"
        if needle in html: html=html.replace(needle,needle+banner,1)
    return html


def _ffver(binary: str) -> str:
    try:
        cp=subprocess.run([binary,'-version'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=5)
        return (cp.stdout or '').splitlines()[0][:240]
    except Exception as exc: return f'Unavailable: {exc}'


def _health_payload() -> dict[str,Any]:
    with _db() as conn:
        integrity=str(conn.execute('PRAGMA integrity_check').fetchone()[0])
        tables=int(conn.execute("SELECT COUNT(*) n FROM sqlite_master WHERE type='table'").fetchone()['n'])
        channels=int(conn.execute('SELECT COUNT(*) n FROM channels WHERE enabled=1').fetchone()['n']) if _table_exists(conn,'channels') else 0
        libs=int(conn.execute('SELECT COUNT(*) n FROM libraries WHERE enabled=1').fetchone()['n']) if _table_exists(conn,'libraries') else 0
        plex=int(conn.execute('SELECT COUNT(*) n FROM plex_servers WHERE enabled=1').fetchone()['n']) if _table_exists(conn,'plex_servers') else 0
        ext=int(conn.execute('SELECT COUNT(*) n FROM media_servers WHERE enabled=1').fetchone()['n']) if _table_exists(conn,'media_servers') else 0
        idx=dict(conn.execute('SELECT * FROM search_index_state WHERE id=1').fetchone()) if _table_exists(conn,'search_index_state') and conn.execute('SELECT 1 FROM search_index_state WHERE id=1').fetchone() else {}
    dbp=Path(G['DB_PATH']); data=Path(G['DATA_DIR']); usage=shutil.disk_usage(data)
    active=G.get('SHARED_CHANNEL_STREAMS',{})
    try: hw=G['_hardware_status_payload']()
    except Exception: hw={}
    latest=''
    bdir=Path(G['BACKUP_DIR'])
    try:
        files=sorted([p for p in bdir.glob('*.db') if p.is_file()],key=lambda p:p.stat().st_mtime,reverse=True);latest=files[0].name if files else ''
    except Exception: pass
    return {'version':G.get('APP_VERSION'),'uptime_seconds':int(time.time()-_STARTED_AT),'database':{'path':str(dbp),'bytes':dbp.stat().st_size if dbp.exists() else 0,'integrity':integrity,'tables':tables},'disk':{'path':str(data),'total':usage.total,'used':usage.used,'free':usage.free},'catalog':{'libraries':libs,'channels':channels,'plex_servers':plex,'jellyfin_emby_servers':ext},'search_index':idx,'active_streams':len(active),'latest_backup':latest,'ffmpeg':_ffver('ffmpeg'),'ffprobe':_ffver('ffprobe'),'hardware':{'recommended':hw.get('recommended'),'global_profile':hw.get('global_profile'),'devices':len(hw.get('devices') or [])}}


def _fmt_bytes(n: int) -> str:
    v=float(n or 0)
    for u in ('B','KB','MB','GB','TB'):
        if v<1024 or u=='TB': return f'{v:.1f} {u}'
        v/=1024
    return f'{v:.1f} TB'


def _source_probe() -> dict[str,Any]:
    out=[]
    with _db() as conn:
        if _table_exists(conn,'plex_servers'):
            for r in conn.execute('SELECT id,name,base_url,token FROM plex_servers WHERE enabled=1').fetchall():
                url=str(r['base_url']).rstrip('/')+'/identity';headers={'X-Plex-Token':str(r['token'] or '')}
                out.append(('Plex',str(r['name']),url,headers))
        if _table_exists(conn,'media_servers'):
            cols=set(_columns(conn,'media_servers'))
            for r in conn.execute('SELECT * FROM media_servers WHERE enabled=1').fetchall():
                base=str(r['base_url']).rstrip('/'); kind=str(r['kind'] or 'Media Server');key=str(r['api_key'] or '') if 'api_key' in cols else ''
                out.append((kind.title(),str(r['name']),base+'/System/Info/Public',{'X-Emby-Token':key} if key else {}))
    results=[]
    for kind,name,url,headers in out:
        t=time.time();ok=False;err=''
        try:
            req=urllib.request.Request(url,headers=headers);resp=urllib.request.urlopen(req,timeout=4);ok=200<=int(resp.status)<500;resp.close()
        except Exception as exc: err=str(exc)[:300]
        results.append({'kind':kind,'name':name,'ok':ok,'ms':int((time.time()-t)*1000),'error':err})
    _set('health_last_probe_json',json.dumps({'at':_now(),'results':results}))
    return {'at':_now(),'results':results}


def _job_create(kind: str, total: int=0, message: str='') -> int:
    with _db() as conn:
        cur=conn.execute('INSERT INTO system_jobs(kind,status,total,checked,found,message,created_at) VALUES(?,?,?,?,?,?,?)',(kind,'queued',int(total),0,0,message,_now()));conn.commit();return int(cur.lastrowid)

def _job_update(jid:int,**kw):
    if not kw:return
    allowed={'status','total','checked','found','message','result_json','started_at','finished_at'}; pairs=[];vals=[]
    for k,v in kw.items():
        if k in allowed:pairs.append(k+'=?');vals.append(v)
    if not pairs:return
    with _db() as conn:conn.execute('UPDATE system_jobs SET '+','.join(pairs)+' WHERE id=?',(*vals,jid));conn.commit()


def _integrity_worker(jid:int):
    _job_update(jid,status='running',started_at=_now(),message='Checking indexed media paths')
    try:
        with _db() as conn:
            conn.execute('DELETE FROM media_integrity_issues WHERE scan_id=?',(jid,));conn.commit()
            local=conn.execute('SELECT id,library_id,path,title,size,duration FROM media ORDER BY id').fetchall() if _table_exists(conn,'media') else []
            plex=conn.execute("SELECT id,title,direct_local_path FROM plex_media WHERE COALESCE(direct_local_path,'')<>'' ORDER BY id").fetchall() if _table_exists(conn,'plex_media') and 'direct_local_path' in _columns(conn,'plex_media') else []
            ext=conn.execute("SELECT id,title,direct_local_path FROM external_media WHERE COALESCE(direct_local_path,'')<>'' ORDER BY id").fetchall() if _table_exists(conn,'external_media') and 'direct_local_path' in _columns(conn,'external_media') else []
        total=len(local)+len(plex)+len(ext);_job_update(jid,total=total)
        found=0;checked=0
        def issue(source,sid,itype,severity,title,path,details):
            nonlocal found;found+=1
            with _db() as c:c.execute('INSERT INTO media_integrity_issues(scan_id,source_type,source_id,issue_type,severity,title,path,details,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(jid,source,sid,itype,severity,title,path,details,_now()));c.commit()
        for r in local:
            p=Path(str(r['path'] or ''));checked+=1
            if not p.exists(): issue('local',r['id'],'missing_file','error',r['title'],str(p),'File is indexed but is not accessible to ViperTV.')
            else:
                try:
                    if p.stat().st_size==0:issue('local',r['id'],'zero_byte','error',r['title'],str(p),'File size is zero bytes.')
                except Exception:pass
                if float(r['duration'] or 0)<=0 and p.suffix.lower() not in {'.jpg','.jpeg','.png','.webp','.bmp','.gif'}:issue('local',r['id'],'missing_duration','warning',r['title'],str(p),'No playable duration is stored.')
            if checked%200==0:_job_update(jid,checked=checked,found=found,message=f'Checked {checked:,} of {total:,}')
        for source,rows in [('plex',plex),('external',ext)]:
            for r in rows:
                checked+=1;p=Path(str(r['direct_local_path'] or ''))
                if not p.exists():issue(source,r['id'],'direct_path_missing','warning',r['title'],str(p),'Direct-path mapping no longer resolves; HTTP fallback may still work.')
                if checked%200==0:_job_update(jid,checked=checked,found=found,message=f'Checked {checked:,} of {total:,}')
        _job_update(jid,status='complete',checked=checked,found=found,message=f'Complete: {found:,} issue(s)',finished_at=_now(),result_json=json.dumps({'issues':found,'checked':checked}))
    except Exception as exc:_job_update(jid,status='failed',message=str(exc)[:1000],finished_at=_now())


def _metadata_worker(jid:int):
    _job_update(jid,status='running',started_at=_now(),message='Building metadata repair queue')
    try:
        with _db() as conn:
            conn.execute("DELETE FROM metadata_repair_queue WHERE status='open'");conn.commit()
            batches=[]
            if _table_exists(conn,'media'):
                cols=set(_columns(conn,'media')); q='SELECT * FROM media ORDER BY id';batches.append(('local',conn.execute(q).fetchall(),cols))
            if _table_exists(conn,'plex_media'):
                batches.append(('plex',conn.execute('SELECT * FROM plex_media ORDER BY id').fetchall(),set(_columns(conn,'plex_media'))))
            if _table_exists(conn,'external_media'):
                batches.append(('external',conn.execute('SELECT * FROM external_media ORDER BY id').fetchall(),set(_columns(conn,'external_media'))))
        total=sum(len(x[1]) for x in batches);_job_update(jid,total=total);checked=found=0
        for source,rows,cols in batches:
            for r in rows:
                checked+=1; issues=[];mtype=str(r['media_type'] if 'media_type' in cols else '')
                title=str(r['title'] if 'title' in cols else '')
                if not title:issues.append('Missing title')
                if mtype in {'episode','tv',''} and 'show_title' in cols and not str(r['show_title'] or ''):issues.append('Missing show title')
                if mtype=='episode' and 'season_number' in cols and r['season_number'] is None:issues.append('Missing season number')
                if mtype=='episode' and 'episode_number' in cols and r['episode_number'] is None:issues.append('Missing episode number')
                if 'duration' in cols and float(r['duration'] or 0)<=0:issues.append('Missing duration')
                yearval=None
                for yc in ('year','show_year'):
                    if yc in cols and r[yc]:yearval=r[yc];break
                if mtype in {'movie','episode'} and yearval is None:issues.append('Missing year')
                if issues:
                    with _db() as c:
                        for issue in issues:
                            c.execute('INSERT OR IGNORE INTO metadata_repair_queue(source_type,source_id,library_id,title,issue,status,attempts,created_at,updated_at) VALUES(?,?,?,?,?,\'open\',0,?,?)',(source,int(r['id']),int(r['library_id']) if 'library_id' in cols and r['library_id'] else (int(r['plex_library_id']) if 'plex_library_id' in cols and r['plex_library_id'] else None),title,issue,_now(),_now()));found+=1
                        c.commit()
                if checked%250==0:_job_update(jid,checked=checked,found=found,message=f'Checked {checked:,} of {total:,}')
        _job_update(jid,status='complete',checked=checked,found=found,message=f'Queue rebuilt: {found:,} repair item(s)',finished_at=_now())
    except Exception as exc:_job_update(jid,status='failed',message=str(exc)[:1000],finished_at=_now())


def _duplicate_groups() -> list[dict[str,Any]]:
    items=[]
    with _db() as conn:
        if _table_exists(conn,'media'):
            for r in conn.execute('SELECT id,title,show_title,season_number,episode_number,path FROM media').fetchall():
                if r['show_title'] and r['season_number'] is not None and r['episode_number'] is not None:key=f"episode|{str(r['show_title']).casefold()}|{r['season_number']}|{r['episode_number']}"
                else:key=f"title|{str(r['title'] or '').casefold()}"
                items.append((key,'Local',int(r['id']),str(r['title'] or ''),str(r['path'] or '')))
        if _table_exists(conn,'plex_media'):
            for r in conn.execute('SELECT id,title,media_type,show_title,season_number,episode_number,direct_local_path FROM plex_media').fetchall():
                if str(r['media_type'])=='episode' and r['show_title'] and r['season_number'] is not None and r['episode_number'] is not None:key=f"episode|{str(r['show_title']).casefold()}|{r['season_number']}|{r['episode_number']}"
                else:key=f"title|{str(r['title'] or '').casefold()}"
                items.append((key,'Plex',int(r['id']),str(r['title'] or ''),str(r['direct_local_path'] or '')))
        if _table_exists(conn,'external_media'):
            cols=set(_columns(conn,'external_media'))
            for r in conn.execute('SELECT * FROM external_media').fetchall():
                show=str(r['show_title'] or '') if 'show_title' in cols else '';sn=r['season_number'] if 'season_number' in cols else None;en=r['episode_number'] if 'episode_number' in cols else None;typ=str(r['media_type'] or '') if 'media_type' in cols else ''
                key=f"episode|{show.casefold()}|{sn}|{en}" if typ=='episode' and show and sn is not None and en is not None else f"title|{str(r['title'] or '').casefold()}"
                items.append((key,'Jellyfin/Emby',int(r['id']),str(r['title'] or ''),str(r['direct_local_path'] or '') if 'direct_local_path' in cols else ''))
    groups={}
    for x in items:
        if not x[0] or x[0] in {'title|','episode|||'}:continue
        groups.setdefault(x[0],[]).append(x[1:])
    return [{'key':k,'items':v} for k,v in groups.items() if len(v)>1]


def _snapshot(name: str, note: str='') -> Path:
    safe=re.sub(r'[^A-Za-z0-9._-]+','-',name.strip() or 'snapshot').strip('-')[:80] or 'snapshot'
    root=Path(G['BACKUP_DIR'])/'snapshots';root.mkdir(parents=True,exist_ok=True)
    dest=root/f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{safe}.db"
    # Register the snapshot first so restoring it later does not make its own UI entry disappear.
    with _db() as conn:
        cur=conn.execute('INSERT INTO named_snapshots(name,file_path,size_bytes,created_at,note) VALUES(?,?,?,?,?)',(name,str(dest),0,_now(),note));sid=int(cur.lastrowid);conn.commit()
    try:
        src=sqlite3.connect(G['DB_PATH']);dst=sqlite3.connect(dest)
        try:src.backup(dst)
        finally:src.close();dst.close()
        with _db() as conn:conn.execute('UPDATE named_snapshots SET size_bytes=? WHERE id=?',(dest.stat().st_size,sid));conn.commit()
    except Exception:
        with _db() as conn:conn.execute('DELETE FROM named_snapshots WHERE id=?',(sid,));conn.commit()
        dest.unlink(missing_ok=True);raise
    return dest


def _safe_settings_export(conn) -> list[dict[str,Any]]:
    out=[]
    for r in conn.execute('SELECT key,value FROM settings ORDER BY key').fetchall():
        k=str(r['key']);lk=k.casefold()
        if any(w in lk for w in SECRET_WORDS):continue
        if k.startswith(SAFE_SETTING_PREFIXES):out.append({'key':k,'value':r['value']})
    return out


def _config_bundle() -> dict[str,Any]:
    tables={}
    with _db() as conn:
        for t in CONFIG_TABLES:
            if _table_exists(conn,t):tables[t]=[dict(r) for r in conn.execute(f'SELECT * FROM "{t}"').fetchall()]
        settings=_safe_settings_export(conn)
    return {'format':'vipertv-config','version':1,'app_version':G.get('APP_VERSION'),'exported_at':_now(),'settings':settings,'tables':tables}


def _import_config(data: dict[str,Any]) -> dict[str,int]:
    if data.get('format')!='vipertv-config' or not isinstance(data.get('tables'),dict):raise ValueError('Not a ViperTV configuration bundle')
    _snapshot('before-config-import','Automatic snapshot before configuration import')
    counts={}
    with _db() as conn:
        conn.execute('PRAGMA foreign_keys=OFF')
        try:
            conn.execute('BEGIN')
            present=[t for t in CONFIG_TABLES if t in data['tables'] and _table_exists(conn,t)]
            for t in reversed(present):conn.execute(f'DELETE FROM "{t}"')
            for t in present:
                cols=_columns(conn,t);rows=data['tables'].get(t) or [];n=0
                for raw in rows:
                    vals={k:v for k,v in dict(raw).items() if k in cols}
                    if not vals:continue
                    names=list(vals);q=','.join('?' for _ in names)
                    conn.execute(f'INSERT INTO "{t}" ({",".join(chr(34)+x+chr(34) for x in names)}) VALUES ({q})',[vals[x] for x in names]);n+=1
                counts[t]=n
            for r in data.get('settings') or []:
                k=str(r.get('key') or '');lk=k.casefold()
                if k and k.startswith(SAFE_SETTING_PREFIXES) and not any(w in lk for w in SECRET_WORDS):conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(k,str(r.get('value') or '')))
            conn.commit()
        except Exception:
            conn.rollback();raise
        finally:conn.execute('PRAGMA foreign_keys=ON')
    return counts


def _validate_update_zip(path: Path) -> tuple[str,list[str]]:
    warnings=[];version=''
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        for raw in names:
            n=raw.replace('\\','/').lstrip('/')
            parts=[p for p in n.split('/') if p]
            if '..' in parts:raise ValueError('Unsafe path traversal in update ZIP')
            low=n.casefold()
            if any(p.casefold() in FORBIDDEN_UPDATE_PARTS for p in parts) or '/data/' in '/'+low or '/backups/' in '/'+low or low.endswith('.db'):
                raise ValueError(f'Unsafe persistent/config file in update ZIP: {raw}')
        candidates=[n for n in names if n.rstrip('/').endswith('VERSION')]
        if candidates:
            try:version=z.read(candidates[0]).decode().strip()
            except Exception:pass
        if not any(n.replace('\\','/').endswith('app/main.py') for n in names):warnings.append('Package does not contain app/main.py')
    return version,warnings


def _stage_update_bytes(raw: bytes, filename: str, expected_sha: str='') -> dict[str,Any]:
    root=Path(G['DATA_DIR'])/'update-cache';root.mkdir(parents=True,exist_ok=True)
    safe=Path(filename).name or 'vipertv-update.zip';dest=root/safe;dest.write_bytes(raw);sha=hashlib.sha256(raw).hexdigest()
    if expected_sha and sha.casefold()!=expected_sha.strip().casefold():dest.unlink(missing_ok=True);raise ValueError('SHA-256 does not match release manifest')
    version,warnings=_validate_update_zip(dest)
    with _db() as conn:
        conn.execute('INSERT OR REPLACE INTO update_packages(version,filename,file_path,sha256,status,notes,created_at) VALUES(?,?,?,?,?,?,?)',(version,safe,str(dest),sha,'staged','; '.join(warnings),_now()));conn.commit()
    return {'version':version,'path':str(dest),'sha256':sha,'warnings':warnings}


def _writable_source_root() -> Path|None:
    raw=os.getenv('VIPERTV_SOURCE_ROOT','').strip()
    if not raw:return None
    p=Path(raw).resolve()
    return p if (p/'app'/'main.py').is_file() and os.access(p,os.W_OK) else None


def _overlay_update(pkg: Path) -> tuple[int,Path]:
    root=_writable_source_root()
    if not root:raise RuntimeError('No writable VIPERTV_SOURCE_ROOT is configured.')
    _snapshot('before-update-overlay','Automatic database snapshot before update overlay')
    rbroot=Path(G['DATA_DIR'])/'update-rollback';rbroot.mkdir(parents=True,exist_ok=True);rb=rbroot/f"rollback-{datetime.now().strftime('%Y%m%d-%H%M%S')}.zip";count=0
    with zipfile.ZipFile(pkg) as z, zipfile.ZipFile(rb,'w',zipfile.ZIP_DEFLATED) as rz:
        names=[n for n in z.namelist() if not n.endswith('/')]
        prefixes=[]
        # accept either flat recovery ZIP or one top-level source folder
        first={n.split('/')[0] for n in names if '/' in n}
        prefix=(next(iter(first))+'/' if len(first)==1 and not any(n.startswith('app/') for n in names) else '')
        for n in names:
            rel=n[len(prefix):] if prefix and n.startswith(prefix) else n
            if not rel or rel.startswith('../') or rel in FORBIDDEN_UPDATE_PARTS or rel.endswith('.db'):continue
            if not (rel.startswith('app/') or rel.startswith('docs/') or rel in {'VERSION','README.md','CHANGELOG.md','FEATURE-MATRIX.md','HANDOFF.md','GITHUB-PUBLISHING.md'}):continue
            dst=(root/rel).resolve()
            if os.path.commonpath([str(dst),str(root)])!=str(root):raise RuntimeError('Unsafe update path')
            if dst.exists() and dst.is_file():rz.write(dst,rel)
            dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(z.read(n));count+=1
    return count,rb


def install_v150(app, main_globals: dict[str,Any]) -> None:
    global G,_BASE_PAGE_SHELL
    G=main_globals
    init_v150_db()
    _BASE_PAGE_SHELL=G['page_shell'];G['page_shell']=_nav_page_shell
    for n in ('_profiled_local_command','_profiled_external_command','_profiled_plex_part_command','_profiled_gap_command'):_wrap_command(n)
    app.middleware('http')(_admin_middleware)

    @app.get('/setup',response_class=HTMLResponse)
    def setup(step:int=1,msg:str=''):
        step=max(1,min(7,int(step)));notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
        with _db() as conn:
            libs=int(conn.execute('SELECT COUNT(*) n FROM libraries').fetchone()['n']) if _table_exists(conn,'libraries') else 0
            channels=int(conn.execute('SELECT COUNT(*) n FROM channels').fetchone()['n']) if _table_exists(conn,'channels') else 0
            sources=(int(conn.execute('SELECT COUNT(*) n FROM plex_servers').fetchone()['n']) if _table_exists(conn,'plex_servers') else 0)+(int(conn.execute('SELECT COUNT(*) n FROM media_servers').fetchone()['n']) if _table_exists(conn,'media_servers') else 0)
        nav=''.join(f"<a class='button {'secondary' if i!=step else ''}' href='/setup?step={i}'>{i}</a> " for i in range(1,8))
        if step==1:content="<h2>Welcome</h2><p>This wizard verifies the pieces needed for a working ViperTV Windows Standalone installation.</p><a class='button' href='/setup?step=2'>Begin</a>"
        elif step==2:content=f"<h2>Timezone</h2><form method='post' action='/setup/timezone'><label>ViperTV scheduling timezone</label><input name='timezone_name' value='{_e(_setting('setup_timezone',str(G.get('DEFAULT_TIMEZONE') or 'UTC')))}'><button>Save & Continue</button></form><p class='muted small'>Windows Standalone includes timezone data and uses this setting for ViperTV scheduling.</p>"
        elif step==3:content=f"<h2>Storage</h2><p><b>Database:</b> <code>{_e(G['DB_PATH'])}</code><br><b>Primary backups:</b> <code>{_e(G['BACKUP_DIR'])}</code><br><b>Secondary backups:</b> <code>{_e(G['SECONDARY_BACKUP_DIR'])}</code></p><p>{libs} local librar{'y' if libs==1 else 'ies'} configured.</p><a class='button secondary' href='/media/local'>Manage Local Sources</a> <a class='button' href='/setup?step=4'>Continue</a>"
        elif step==4:content=f"<h2>Media Servers</h2><p>{sources} Plex/Jellyfin/Emby server connection(s) configured.</p><a class='button secondary' href='/plex'>Plex</a> <a class='button secondary' href='/sources'>Jellyfin / Emby</a> <a class='button' href='/setup?step=5'>Continue</a>"
        elif step==5:content="<h2>Hardware Acceleration</h2><p>Detect and test the encoder ViperTV should use for generated channels.</p><a class='button secondary' href='/system/hardware'>Open Hardware Acceleration</a> <a class='button' href='/setup?step=6'>Continue</a>"
        elif step==6:content="<h2>Metadata & Search</h2><p>Configure metadata providers and confirm the persistent search index is ready.</p><a class='button secondary' href='/system/metadata'>Metadata Providers</a> <a class='button secondary' href='/media/search'>Search Index</a> <a class='button' href='/setup?step=7'>Continue</a>"
        else:content=f"<h2>First Channel</h2><p>{channels} channel(s) currently exist.</p><a class='button secondary' href='/channels'>Channels</a> <a class='button secondary' href='/channels/auto'>Channel Builder</a><hr><form method='post' action='/setup/complete'><button>Mark Setup Complete</button></form>"
        body=notice+_heading('First-run Setup Wizard',f'Step {step} of 7 — Welcome, timezone, storage, sources, hardware, metadata, first channel.')+f"<div class='card'><div class='toolbar' style='margin-bottom:18px'>{nav}</div>{content}</div>"
        return _page('Setup Wizard',body)

    @app.post('/setup/timezone')
    def setup_timezone(timezone_name:str=Form('UTC')):
        tz=timezone_name.strip() or 'UTC'
        try:
            from zoneinfo import ZoneInfo;ZoneInfo(tz)
        except Exception:return RedirectResponse('/setup?step=2&msg='+urllib.parse.quote('Unknown timezone.'),303)
        _set('setup_timezone',tz);G['DEFAULT_TIMEZONE']=tz
        return RedirectResponse('/setup?step=3&msg=Timezone+saved',303)

    @app.post('/setup/complete')
    def setup_complete():_set('setup_completed','1');_set('setup_completed_at',_now());return RedirectResponse('/?setup=complete',303)

    @app.get('/api/system/health',response_class=JSONResponse)
    def api_health():return JSONResponse(_health_payload())

    @app.get('/system/health',response_class=HTMLResponse)
    def health_page(msg:str=''):
        h=_health_payload();d=h['database'];disk=h['disk'];idx=h['search_index'];hw=h['hardware']
        try:probe=json.loads(_setting('health_last_probe_json','{}') or '{}')
        except Exception:probe={}
        prows=''.join(f"<tr><td>{_e(x['kind'])}</td><td>{_e(x['name'])}</td><td>{'<span class=\'badge green\'>OK</span>' if x['ok'] else '<span class=\'badge red\'>FAILED</span>'}</td><td>{x['ms']} ms</td><td>{_e(x['error'])}</td></tr>" for x in probe.get('results',[])) or "<tr><td colspan='5' class='empty'>Run a source connectivity probe.</td></tr>"
        notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
        body=notice+_heading('System Health','Database, storage, media sources, search, FFmpeg, hardware and active-stream health at a glance.',"<form class='inline' method='post' action='/system/health/probe'><button>Probe Sources</button></form>")+f"""
<div class='stats'><div class='stat'><div class='stat-value'>{_e(d['integrity'])}</div><div class='stat-label'>Database integrity</div></div><div class='stat'><div class='stat-value'>{_fmt_bytes(disk['free'])}</div><div class='stat-label'>Free data disk</div></div><div class='stat'><div class='stat-value'>{h['active_streams']}</div><div class='stat-label'>Active station producers</div></div><div class='stat'><div class='stat-value'>{int(idx.get('item_count') or 0):,}</div><div class='stat-label'>Indexed search items</div></div></div>
<div class='grid'><div class='card'><h2>Database & Storage</h2><p><b>DB:</b> <code>{_e(d['path'])}</code><br><b>Size:</b> {_fmt_bytes(d['bytes'])}<br><b>Tables:</b> {d['tables']}<br><b>Latest backup:</b> {_e(h['latest_backup'] or 'None')}</p></div><div class='card'><h2>Catalog & Hardware</h2><p>Libraries: <b>{h['catalog']['libraries']}</b><br>Channels: <b>{h['catalog']['channels']}</b><br>Plex servers: <b>{h['catalog']['plex_servers']}</b><br>Jellyfin/Emby: <b>{h['catalog']['jellyfin_emby_servers']}</b><br>Hardware: <b>{_e(hw.get('recommended') or 'software')}</b> ({hw.get('devices',0)} device(s))</p></div></div>
<div class='card'><h2>Runtime</h2><p><code>{_e(h['ffmpeg'])}</code><br><code>{_e(h['ffprobe'])}</code><br>Uptime: {h['uptime_seconds']//3600}h {(h['uptime_seconds']%3600)//60}m</p></div>
<div class='card'><h2>Source Connectivity</h2><div class='table-wrap'><table><tr><th>Type</th><th>Name</th><th>Status</th><th>Latency</th><th>Error</th></tr>{prows}</table></div></div>"""
        return _page('System Health',body)

    @app.post('/system/health/probe')
    def health_probe():
        p=_source_probe();ok=sum(1 for x in p['results'] if x['ok']);return RedirectResponse('/system/health?msg='+urllib.parse.quote(f'Connectivity probe complete: {ok}/{len(p["results"])} reachable.'),303)

    @app.get('/api/system/diagnostics',response_class=JSONResponse)
    def diagnostics_api():
        rows=[]
        for cid,s in list(G.get('SHARED_CHANNEL_STREAMS',{}).items()):
            cmd=_COMMAND_HISTORY.get(int(cid),{})
            rows.append({'channel_id':cid,'channel':G['_shared_stream_label'](cid),'viewers':len(s.get('subscribers',set())),'uptime_seconds':int(time.time()-float(s.get('started_at') or time.time())),'source_mode':s.get('source_mode'),'source_item':s.get('source_item'),'effective_profile':s.get('effective_profile'),'configured_profile':s.get('configured_profile'),'hardware_fallbacks':s.get('hardware_fallbacks',0),'error':s.get('error',''),'ffmpeg':cmd})
        return JSONResponse({'channels':rows,'count':len(rows)})

    @app.get('/system/diagnostics',response_class=HTMLResponse)
    def diagnostics_page(msg:str=''):
        rows=''
        for cid,s in list(G.get('SHARED_CHANNEL_STREAMS',{}).items()):
            cmd=_COMMAND_HISTORY.get(int(cid),{});cmdtext=' '.join(cmd.get('command') or [])
            rows+=f"<tr><td><b>{_e(G['_shared_stream_label'](cid))}</b><div class='small muted'>{_e(s.get('source_item') or '')}</div></td><td>{len(s.get('subscribers',set()))}</td><td>{_e(s.get('source_mode') or '')}</td><td>{_e(s.get('effective_profile') or '')}</td><td>{int(s.get('hardware_fallbacks') or 0)}</td><td><details><summary>FFmpeg / errors</summary><pre style='white-space:pre-wrap;max-width:900px'>{_e(cmdtext)}\n\n{_e(s.get('error') or '')}</pre></details></td><td><form method='post' action='/system/diagnostics/restart/{cid}'><button class='danger'>Restart</button></form></td></tr>"
        if not rows:rows="<tr><td colspan='7' class='empty'>No generated station producer is active.</td></tr>"
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Live Stream Diagnostics','Inspect the real station producer, viewers, source path/mode, active hardware profile, sanitized FFmpeg command and fallback errors.')+f"<div class='card'><div class='table-wrap'><table><tr><th>Channel</th><th>Viewers</th><th>Source</th><th>Encoder</th><th>Fallbacks</th><th>Command / error</th><th></th></tr>{rows}</table></div></div>"
        return _page('Stream Diagnostics',body)

    @app.post('/system/diagnostics/restart/{cid}')
    async def diagnostics_restart(cid:int):
        s=G.get('SHARED_CHANNEL_STREAMS',{}).get(cid)
        if s:
            s['stop']=True;proc=s.get('proc')
            if proc is not None and proc.returncode is None:
                try:proc.terminate()
                except Exception:pass
        return RedirectResponse('/system/diagnostics?msg=Station+producer+restart+requested',303)

    @app.get('/system/media-integrity',response_class=HTMLResponse)
    def integrity_page(msg:str=''):
        with _db() as conn:
            job=conn.execute("SELECT * FROM system_jobs WHERE kind='media-integrity' ORDER BY id DESC LIMIT 1").fetchone();issues=conn.execute('SELECT * FROM media_integrity_issues WHERE scan_id=? ORDER BY CASE severity WHEN \'error\' THEN 0 ELSE 1 END,issue_type,id LIMIT 500',(int(job['id']),)).fetchall() if job else []
        progress='No scan yet.' if not job else f"{job['status']} — {int(job['checked'] or 0):,}/{int(job['total'] or 0):,} checked — {int(job['found'] or 0):,} issue(s) — {_e(job['message'] or '')}"
        rows=''.join(f"<tr><td><span class='badge {'red' if r['severity']=='error' else 'yellow'}'>{_e(r['severity'])}</span></td><td>{_e(r['issue_type'])}</td><td>{_e(r['source_type'])}</td><td>{_e(r['title'] or '')}</td><td><code>{_e(r['path'] or '')}</code></td><td>{_e(r['details'] or '')}</td></tr>" for r in issues) or "<tr><td colspan='6' class='empty'>No issues from the latest scan.</td></tr>"
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Media Integrity','Find missing local files, zero-byte files, missing durations and broken direct-path mappings.',"<form class='inline' method='post' action='/system/media-integrity/scan'><button>Start Scan</button></form>")+f"<div class='card'><p><b>{progress}</b></p><p class='muted small'>Refresh this page while a large scan is running.</p></div><div class='card'><div class='table-wrap'><table><tr><th>Severity</th><th>Issue</th><th>Source</th><th>Title</th><th>Path</th><th>Details</th></tr>{rows}</table></div></div>"
        return _page('Media Integrity',body)

    @app.post('/system/media-integrity/scan')
    def integrity_start():
        with _db() as conn:
            running=conn.execute("SELECT id FROM system_jobs WHERE kind='media-integrity' AND status IN ('queued','running') ORDER BY id DESC LIMIT 1").fetchone()
        if running:return RedirectResponse('/system/media-integrity?msg=Scan+already+running',303)
        jid=_job_create('media-integrity');threading.Thread(target=_integrity_worker,args=(jid,),daemon=True,name='vipertv-integrity').start();return RedirectResponse('/system/media-integrity?msg=Integrity+scan+started',303)

    @app.get('/system/duplicates',response_class=HTMLResponse)
    def duplicate_page():
        groups=_duplicate_groups();blocks=''
        for g in groups[:250]:
            items=''.join(f"<li><b>{_e(x[0])}</b> #{x[1]} — {_e(x[2])}<br><code>{_e(x[3])}</code></li>" for x in g['items'])
            blocks+=f"<details><summary>{len(g['items'])} copies — {_e(g['items'][0][2])}</summary><ul>{items}</ul></details>"
        if not blocks:blocks="<p class='empty'>No obvious duplicate title/episode keys were found.</p>"
        return _page('Duplicate Detector',_heading('Duplicate Detector','Compare local, Plex, Jellyfin and Emby indexes by movie/title or show-season-episode identity.')+f"<div class='card'><p><b>{len(groups):,}</b> duplicate group(s) found.</p>{blocks}</div>")

    @app.get('/system/metadata-repair',response_class=HTMLResponse)
    def repair_page(msg:str=''):
        with _db() as conn:
            job=conn.execute("SELECT * FROM system_jobs WHERE kind='metadata-repair' ORDER BY id DESC LIMIT 1").fetchone();rows=conn.execute("SELECT * FROM metadata_repair_queue WHERE status='open' ORDER BY source_type,title,issue LIMIT 500").fetchall();count=int(conn.execute("SELECT COUNT(*) n FROM metadata_repair_queue WHERE status='open'").fetchone()['n'])
        trs=''.join(f"<tr><td>{_e(r['source_type'])}</td><td>{_e(r['title'] or '')}</td><td>{_e(r['issue'])}</td><td>{int(r['attempts'] or 0)}</td><td><form class='inline' method='post' action='/system/metadata-repair/{r['id']}/retry'><button>Retry Source</button></form> <form class='inline' method='post' action='/system/metadata-repair/{r['id']}/resolve'><button class='secondary'>Resolve</button></form></td></tr>" for r in rows) or "<tr><td colspan='5' class='empty'>Repair queue is empty.</td></tr>"
        p='' if not job else f"Latest build: {job['status']} {int(job['checked'] or 0):,}/{int(job['total'] or 0):,} — {int(job['found'] or 0):,} found"
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Metadata Repair Queue','Identify incomplete title/year/episode/duration metadata and retry the appropriate source sync.',"<form class='inline' method='post' action='/system/metadata-repair/rebuild'><button>Rebuild Queue</button></form>")+f"<div class='card'><p><b>{count:,}</b> open repair item(s). {_e(p)}</p><div class='table-wrap'><table><tr><th>Source</th><th>Title</th><th>Issue</th><th>Attempts</th><th></th></tr>{trs}</table></div></div>"
        return _page('Metadata Repair',body)

    @app.post('/system/metadata-repair/rebuild')
    def repair_rebuild():
        jid=_job_create('metadata-repair');threading.Thread(target=_metadata_worker,args=(jid,),daemon=True,name='vipertv-metadata-repair').start();return RedirectResponse('/system/metadata-repair?msg=Repair+queue+build+started',303)

    @app.post('/system/metadata-repair/{rid}/resolve')
    def repair_resolve(rid:int):
        with _db() as conn:conn.execute("UPDATE metadata_repair_queue SET status='resolved',updated_at=? WHERE id=?",(_now(),rid));conn.commit()
        return RedirectResponse('/system/metadata-repair?msg=Marked+resolved',303)

    @app.post('/system/metadata-repair/{rid}/retry')
    def repair_retry(rid:int):
        with _db() as conn:r=conn.execute('SELECT * FROM metadata_repair_queue WHERE id=?',(rid,)).fetchone()
        if not r:raise HTTPException(404)
        err='';ok=False
        try:
            if r['source_type']=='local' and r['library_id']:G['scan_library'](int(r['library_id']));ok=True
            elif r['source_type']=='plex' and r['library_id']:G['sync_plex_library'](int(r['library_id']));ok=True
            elif r['source_type']=='external' and r['library_id']:G['sync_external_library'](int(r['library_id']));ok=True
            else:err='No source library reference is available.'
        except Exception as exc:err=str(exc)
        with _db() as conn:conn.execute('UPDATE metadata_repair_queue SET attempts=attempts+1,last_error=?,status=?,updated_at=? WHERE id=?',(err,'resolved' if ok else 'open',_now(),rid));conn.commit()
        return RedirectResponse('/system/metadata-repair?msg='+urllib.parse.quote('Source refreshed.' if ok else 'Retry failed: '+err),303)

    @app.get('/system/config',response_class=HTMLResponse)
    def config_page(msg:str=''):
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Configuration Import / Export','Move channels, schedules, Collections, Playlists, graphics and reusable profiles without exporting media indexes or secrets.')+"""
<div class='grid'><div class='card'><h2>Export</h2><p>Produces a public-safe JSON bundle. Plex tokens, API keys, passwords, JWT secrets and media indexes are excluded.</p><a class='button' href='/system/config/export'>Download Configuration</a></div><div class='card'><h2>Import</h2><p>Import replaces the configuration tables contained in the bundle. ViperTV automatically creates a database snapshot first.</p><form method='post' action='/system/config/import' enctype='multipart/form-data' onsubmit='return confirm("Replace matching ViperTV configuration with this bundle?")'><input type='file' name='file' accept='.json' required><button class='danger'>Import Configuration</button></form></div></div>"""
        return _page('Import / Export',body)

    @app.get('/system/config/export')
    def config_export():
        raw=json.dumps(_config_bundle(),indent=2,ensure_ascii=False).encode();return Response(raw,media_type='application/json',headers={'Content-Disposition':f'attachment; filename="ViperTV-config-{G.get("APP_VERSION")}.json"'})

    @app.post('/system/config/import')
    async def config_import(file:UploadFile=File(...)):
        try:data=json.loads((await file.read()).decode());counts=_import_config(data);msg='Imported '+', '.join(f'{k}:{v}' for k,v in counts.items())
        except Exception as exc:msg='Import failed: '+str(exc)
        return RedirectResponse('/system/config?msg='+urllib.parse.quote(msg),303)

    @app.get('/system/snapshots',response_class=HTMLResponse)
    def snapshots_page(msg:str=''):
        with _db() as conn:rows=conn.execute('SELECT * FROM named_snapshots ORDER BY id DESC').fetchall()
        trs=''.join(f"<tr><td><b>{_e(r['name'])}</b><div class='small muted'>{_e(r['note'] or '')}</div></td><td>{_e(r['created_at'])}</td><td>{_fmt_bytes(r['size_bytes'])}</td><td><a class='button secondary' href='/system/snapshots/{r['id']}/download'>Download</a> <form class='inline' method='post' action='/system/snapshots/{r['id']}/restore' onsubmit='return confirm(\"Restore this complete database snapshot?\")'><button class='danger'>Restore</button></form></td></tr>" for r in rows) or "<tr><td colspan='4' class='empty'>No named snapshots yet.</td></tr>"
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Database Snapshots','Create named point-in-time copies before major scheduling, metadata or configuration changes.')+f"<div class='card'><form method='post' action='/system/snapshots/create'><div class='grid'><div><label>Snapshot name</label><input name='name' required placeholder='Before Christmas Schedule'></div><div><label>Note</label><input name='note'></div></div><button>Create Snapshot</button></form></div><div class='card'><table><tr><th>Name</th><th>Created</th><th>Size</th><th></th></tr>{trs}</table></div>"
        return _page('Snapshots',body)

    @app.post('/system/snapshots/create')
    def snapshot_create(name:str=Form(...),note:str=Form('')):
        p=_snapshot(name,note);return RedirectResponse('/system/snapshots?msg='+urllib.parse.quote('Snapshot created: '+p.name),303)

    @app.get('/system/snapshots/{sid}/download')
    def snapshot_download(sid:int):
        with _db() as conn:r=conn.execute('SELECT * FROM named_snapshots WHERE id=?',(sid,)).fetchone()
        if not r or not Path(r['file_path']).exists():raise HTTPException(404)
        return FileResponse(r['file_path'],filename=Path(r['file_path']).name,media_type='application/octet-stream')

    @app.post('/system/snapshots/{sid}/restore')
    def snapshot_restore(sid:int):
        with _db() as conn:r=conn.execute('SELECT * FROM named_snapshots WHERE id=?',(sid,)).fetchone()
        if not r or not Path(r['file_path']).exists():raise HTTPException(404)
        G['backup_all']('before-named-snapshot-restore');src=sqlite3.connect(r['file_path']);dst=sqlite3.connect(G['DB_PATH'])
        try:src.backup(dst)
        finally:src.close();dst.close()
        return RedirectResponse('/system/snapshots?msg=Snapshot+restored',303)

    @app.get('/admin/users',response_class=HTMLResponse)
    def users_page(msg:str=''):
        with _db() as conn:rows=conn.execute('SELECT * FROM admin_users ORDER BY username COLLATE NOCASE').fetchall()
        trs=''.join(f"<tr><td><b>{_e(r['username'])}</b></td><td>{_e(r['role'])}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td><td>{_e(r['last_login'] or 'Never')}</td><td><form class='inline' method='post' action='/admin/users/{r['id']}/delete' onsubmit='return confirm(\"Delete this account?\")'><button class='danger'>Delete</button></form></td></tr>" for r in rows) or "<tr><td colspan='5'>No role accounts yet. The legacy administrator login still works.</td></tr>"
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Users & Roles','Admin has full control; Editor manages programming; Viewer is read-only.')+f"""
<div class='grid'><div class='card'><h2>Add Local User</h2><form method='post' action='/admin/users/add'><label>Username</label><input name='username' required><label>Password</label><input type='password' name='password' required minlength='8'><label>Role</label><select name='role'><option>viewer</option><option>editor</option><option>admin</option></select><button>Add User</button></form></div><div class='card'><h2>OIDC default role</h2><form method='post' action='/admin/users/oidc-role'><select name='role'><option {'selected' if _setting('oidc_default_role','viewer')=='viewer' else ''}>viewer</option><option {'selected' if _setting('oidc_default_role')=='editor' else ''}>editor</option><option {'selected' if _setting('oidc_default_role')=='admin' else ''}>admin</option></select><button>Save</button></form><p class='muted small'>Explicit local usernames always use their saved role. Unknown OIDC users receive this default.</p></div></div><div class='card'><table><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr>{trs}</table></div>"""
        return _page('Users & Roles',body)

    @app.post('/admin/users/add')
    def user_add(username:str=Form(...),password:str=Form(...),role:str=Form('viewer')):
        role=role if role in {'admin','editor','viewer'} else 'viewer'
        try:
            with _db() as conn:conn.execute('INSERT INTO admin_users(username,password_hash,role,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?)',(username.strip(),sec._password_hash(password),role,1,_now(),_now()));conn.commit()
            msg='User added.'
        except Exception as exc:msg='Unable to add user: '+str(exc)
        return RedirectResponse('/admin/users?msg='+urllib.parse.quote(msg),303)

    @app.post('/admin/users/{uid}/delete')
    def user_delete(uid:int):
        with _db() as conn:
            r=conn.execute('SELECT * FROM admin_users WHERE id=?',(uid,)).fetchone()
            if not r:raise HTTPException(404)
            if r['role']=='admin' and int(conn.execute("SELECT COUNT(*) n FROM admin_users WHERE role='admin' AND enabled=1").fetchone()['n'])<=1:return RedirectResponse('/admin/users?msg=Cannot+delete+the+last+role+administrator',303)
            conn.execute('DELETE FROM admin_users WHERE id=?',(uid,));conn.commit()
        return RedirectResponse('/admin/users?msg=User+deleted',303)

    @app.post('/admin/users/oidc-role')
    def oidc_role(role:str=Form('viewer')):_set('oidc_default_role',role if role in {'viewer','editor','admin'} else 'viewer');return RedirectResponse('/admin/users?msg=OIDC+default+role+saved',303)

    @app.get('/admin/audit',response_class=HTMLResponse)
    def audit_page(limit:int=250):
        limit=max(25,min(1000,int(limit)))
        with _db() as conn:rows=conn.execute('SELECT * FROM audit_log ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        trs=''.join(f"<tr><td>{_e(r['created_at'])}</td><td>{_e(r['username'] or 'anonymous')}</td><td>{_e(r['role'] or '')}</td><td>{_e(r['method'])}</td><td><code>{_e(r['path'])}</code></td><td>{r['status_code'] or ''}</td><td>{_e(r['remote_addr'] or '')}</td></tr>" for r in rows) or "<tr><td colspan='7'>No audited mutations yet.</td></tr>"
        return _page('Audit Log',_heading('SYSOP Audit Log','Track management mutations, logins, roles, paths, response status and remote address.')+f"<div class='card'><div class='table-wrap'><table><tr><th>Time</th><th>User</th><th>Role</th><th>Method</th><th>Path</th><th>Status</th><th>Remote</th></tr>{trs}</table></div></div>")

    @app.get('/system/update',response_class=HTMLResponse)
    def update_page(msg:str=''):
        with _db() as conn:rows=conn.execute('SELECT * FROM update_packages ORDER BY id DESC').fetchall()
        root=_writable_source_root();trs=''.join(f"<tr><td>{_e(r['version'] or '?')}</td><td>{_e(r['filename'])}</td><td><code>{_e(r['sha256'])}</code></td><td>{_e(r['status'])}</td><td><form class='inline' method='post' action='/system/update/{r['id']}/apply'><button {'disabled' if not root else ''}>Overlay Source</button></form></td></tr>" for r in rows) or "<tr><td colspan='5'>No update packages staged.</td></tr>"
        mode=(f"Writable application root: <code>{_e(root)}</code>. Windows Standalone can overlay a validated update in place; restart ViperTV afterward." if os.environ.get('VIPERTV_WINDOWS_STANDALONE')=='1' and root else (f"Writable source root: <code>{_e(root)}</code>. Overlay can be automated; rebuild/restart your deployment afterward." if root else "No writable application source root is configured. ViperTV can still check, validate and stage updates and snapshot the database."))
        try:avail=json.loads(_setting('update_available_json','{}') or '{}')
        except Exception:avail={}
        body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Update Manager','Check, validate and stage recovery-safe releases with automatic pre-update snapshots and rollback files.')+f"""
<div class='card'><h2>Deployment Mode</h2><p>{mode}</p></div><div class='grid'><div class='card'><h2>Release Feed</h2><form method='post' action='/system/update/check'><label>Manifest URL</label><input name='url' value='{_e(_setting('update_manifest_url'))}' placeholder='https://example/vipertv/latest.json'><button>Check for Update</button></form><pre>{_e(json.dumps(avail,indent=2) if avail else 'No release manifest checked yet.')}</pre></div><div class='card'><h2>Upload Recovery-safe ZIP</h2><form method='post' action='/system/update/upload' enctype='multipart/form-data'><input type='file' name='file' accept='.zip' required><button>Validate & Stage</button></form><p class='muted small'>Packages containing Compose files, .env, databases, data/backups or path traversal are rejected.</p></div></div><div class='card'><table><tr><th>Version</th><th>Package</th><th>SHA-256</th><th>Status</th><th></th></tr>{trs}</table></div>"""
        return _page('Update Manager',body)

    @app.post('/system/update/check')
    def update_check(url:str=Form('')):
        url=url.strip();_set('update_manifest_url',url)
        try:
            if not url:raise ValueError('Enter a release manifest URL')
            with urllib.request.urlopen(url,timeout=12) as r:data=json.loads(r.read().decode())
            if not isinstance(data,dict) or not data.get('version'):raise ValueError('Manifest must contain version')
            _set('update_available_json',json.dumps(data));msg=f"Latest manifest reports {data.get('version')}"
        except Exception as exc:msg='Update check failed: '+str(exc)
        return RedirectResponse('/system/update?msg='+urllib.parse.quote(msg),303)

    @app.post('/system/update/upload')
    async def update_upload(file:UploadFile=File(...)):
        try:r=_stage_update_bytes(await file.read(),file.filename or 'vipertv-update.zip');msg=f"Staged {r['version'] or file.filename}; SHA-256 {r['sha256']}"
        except Exception as exc:msg='Package rejected: '+str(exc)
        return RedirectResponse('/system/update?msg='+urllib.parse.quote(msg),303)

    @app.post('/system/update/{pid}/apply')
    def update_apply(pid:int):
        with _db() as conn:r=conn.execute('SELECT * FROM update_packages WHERE id=?',(pid,)).fetchone()
        if not r:raise HTTPException(404)
        try:
            count,rb=_overlay_update(Path(r['file_path']))
            with _db() as conn:conn.execute("UPDATE update_packages SET status='overlaid',notes=? WHERE id=?",(f'{count} files; rollback {rb}',pid));conn.commit()
            msg=(f'Overlaid {count} application files. Rollback archive: {rb.name}. Restart ViperTV to activate the update.' if os.environ.get('VIPERTV_WINDOWS_STANDALONE')=='1' else f'Overlaid {count} source files. Rollback archive: {rb.name}. Rebuild/restart the deployment to activate it.')
        except Exception as exc:msg='Apply unavailable: '+str(exc)
        return RedirectResponse('/system/update?msg='+urllib.parse.quote(msg),303)

    @app.get('/system/about',response_class=HTMLResponse)
    def about_page():
        h=_health_payload()
        try:fastapi_ver=importlib.metadata.version('fastapi')
        except Exception:fastapi_ver='unknown'
        body=_heading('About ViperTV','System identity, runtime versions and durable-storage information.')+f"""
<div class='grid'><div class='card'><h2>ViperTV</h2><p><b>Version:</b> {_e(G.get('APP_VERSION'))}<br><b>Created by:</b> Darren “The Viper” Crawford<br><b>Runtime:</b> Python {_e(platform.python_version())} / FastAPI {_e(fastapi_ver)}<br><b>Platform:</b> {_e(platform.platform())}</p></div><div class='card'><h2>Storage</h2><p><b>Database:</b> <code>{_e(G['DB_PATH'])}</code><br><b>DB size:</b> {_fmt_bytes(h['database']['bytes'])}<br><b>Primary backups:</b> <code>{_e(G['BACKUP_DIR'])}</code><br><b>Secondary backups:</b> <code>{_e(G['SECONDARY_BACKUP_DIR'])}</code></p></div></div><div class='card'><h2>Media Runtime</h2><p><code>{_e(h['ffmpeg'])}</code><br><code>{_e(h['ffprobe'])}</code></p><p>Database integrity: <span class='badge'>{_e(h['database']['integrity'])}</span> &nbsp; Search index: {int(h['search_index'].get('item_count') or 0):,} items &nbsp; Active stations: {h['active_streams']}</p></div>"""
        return _page('About / System Info',body)
