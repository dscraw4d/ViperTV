from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import advanced_scheduling as adv

G: dict[str, Any] = {}
_BASE_LOCAL = None
_BASE_PLEX = None
_BASE_EXTERNAL = None
_BASE_PLEX_SOURCE = None
_BASE_PLEX_PAGE = None
_STREAM_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_PLEX_INFO_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _db():
    return G['db']()


def _e(v: Any) -> str:
    return G['e'](v)


def _now() -> str:
    return G['utcnow_iso']()


def _page(title: str, body: str) -> str:
    return G['page_shell'](title, body)


def _heading(title: str, subtitle: str, actions: str = '') -> str:
    return G['_page_heading'](title, subtitle, actions)


def _hm(v: int | None) -> str:
    if v is None:
        return ''
    v = int(v) % 1440
    return f'{v//60:02d}:{v%60:02d}'


def _hm_to_min(v: str | None) -> int | None:
    s = str(v or '').strip()
    if not s:
        return None
    try:
        h, m = [int(x) for x in s.split(':', 1)]
        return (max(0, min(23, h)) * 60) + max(0, min(59, m))
    except Exception:
        return None


def init_v129_db() -> None:
    """Additive v1.2.9 schema. Never drops or replaces existing user data."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS stream_selector_profiles(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              description TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stream_selector_rules(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              profile_id INTEGER NOT NULL REFERENCES stream_selector_profiles(id) ON DELETE CASCADE,
              kind TEXT NOT NULL CHECK(kind IN ('audio','subtitle')),
              priority INTEGER NOT NULL DEFAULT 100,
              language TEXT,
              title_contains TEXT,
              codec TEXT,
              min_channels INTEGER,
              max_channels INTEGER,
              forced INTEGER NOT NULL DEFAULT -1,
              default_flag INTEGER NOT NULL DEFAULT -1,
              sdh INTEGER NOT NULL DEFAULT -1,
              external_only INTEGER NOT NULL DEFAULT -1,
              channel_id INTEGER REFERENCES channels(id) ON DELETE CASCADE,
              start_minute INTEGER,
              end_minute INTEGER,
              action TEXT NOT NULL DEFAULT 'select',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_stream_selector_rules
              ON stream_selector_rules(profile_id,kind,priority DESC,id);
            CREATE TABLE IF NOT EXISTS channel_stream_selectors(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              profile_id INTEGER NOT NULL REFERENCES stream_selector_profiles(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS plex_path_replacements(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              server_id INTEGER NOT NULL REFERENCES plex_servers(id) ON DELETE CASCADE,
              remote_prefix TEXT NOT NULL,
              local_prefix TEXT NOT NULL,
              priority INTEGER NOT NULL DEFAULT 100,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plex_path_replacements
              ON plex_path_replacements(server_id,enabled,priority DESC,id);
            """
        )
        # Cache the original Plex Part path and the translated container path.
        G['add_column_if_missing'](conn, 'plex_media', 'part_file', 'TEXT')
        G['add_column_if_missing'](conn, 'plex_media', 'direct_local_path', 'TEXT')
        G['add_column_if_missing'](conn, 'plex_media', 'part_info_at', 'TEXT')
        # Extend the existing graphics table without replacing old graphics.
        G['add_column_if_missing'](conn, 'graphics_elements', 'loop_asset', 'INTEGER NOT NULL DEFAULT 1')
        G['add_column_if_missing'](conn, 'graphics_elements', 'subtitle_style', 'TEXT')
        G['add_column_if_missing'](conn, 'graphics_elements', 'template_mode', "TEXT NOT NULL DEFAULT 'normal'")
        conn.commit()


# --------------------- Advanced stream selector ---------------------

def _json_streams_from_ffprobe(source: str, headers: str = '') -> list[dict[str, Any]]:
    key = f'{source}|{headers}'
    now = time.monotonic()
    cached = _STREAM_CACHE.get(key)
    if cached and now - cached[0] < 600:
        return [dict(x) for x in cached[1]]
    args = ['ffprobe', '-v', 'error']
    if headers:
        args += ['-headers', headers]
    args += ['-show_streams', '-of', 'json', source]
    try:
        cp = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20, check=False)
        data = json.loads(cp.stdout or '{}') if cp.returncode == 0 else {}
    except Exception:
        data = {}
    out: list[dict[str, Any]] = []
    subtitle_ordinal = 0
    audio_ordinal = 0
    for s in data.get('streams') or []:
        typ = str(s.get('codec_type') or '')
        if typ not in ('audio', 'subtitle'):
            continue
        tags = s.get('tags') or {}
        disp = s.get('disposition') or {}
        title = str(tags.get('title') or '')
        row = {
            'type': typ,
            'index': int(s.get('index') or 0),
            'ordinal': audio_ordinal if typ == 'audio' else subtitle_ordinal,
            'language': str(tags.get('language') or '').strip().lower(),
            'title': title,
            'codec': str(s.get('codec_name') or '').strip().lower(),
            'channels': int(s.get('channels') or 0),
            'forced': 1 if int(disp.get('forced') or 0) else 0,
            'default': 1 if int(disp.get('default') or 0) else 0,
            'sdh': 1 if re.search(r'\b(SDH|HI|HEARING[ -]?IMPAIRED|CC)\b', title, re.I) else 0,
            'external': 0,
            'path': None,
        }
        if typ == 'audio':
            audio_ordinal += 1
        else:
            subtitle_ordinal += 1
        out.append(row)
    # Sidecar subtitle files are explicit external subtitle candidates.
    try:
        p = Path(source)
        if p.exists():
            for ext in ('.srt', '.ass', '.ssa', '.vtt', '.sub'):
                for side in sorted(p.parent.glob(p.stem + '*' + ext)):
                    suffix = side.stem[len(p.stem):].strip('. _-')
                    lang = suffix.split('.')[0].lower() if suffix else ''
                    out.append({
                        'type':'subtitle','index':None,'ordinal':None,'language':lang,'title':side.name,
                        'codec':ext.lstrip('.'),'channels':0,'forced':1 if 'forced' in suffix.casefold() else 0,
                        'default':0,'sdh':1 if re.search(r'\b(sdh|hi|cc)\b', suffix, re.I) else 0,
                        'external':1,'path':str(side),
                    })
    except Exception:
        pass
    _STREAM_CACHE[key] = (now, [dict(x) for x in out])
    return out


def _plex_server_for_item(item: dict[str, Any]):
    with _db() as conn:
        return conn.execute(
            '''SELECT ps.* FROM plex_servers ps JOIN plex_libraries pl ON pl.server_id=ps.id WHERE pl.id=?''',
            (int(item.get('plex_library_id') or 0),)
        ).fetchone()


def _plex_part_info(item: dict[str, Any]) -> dict[str, Any]:
    key = f"{item.get('plex_library_id')}:{item.get('rating_key') or item.get('plex_key')}"
    now = time.monotonic()
    cached = _PLEX_INFO_CACHE.get(key)
    if cached and now - cached[0] < 900:
        return dict(cached[1])
    server = _plex_server_for_item(item)
    if not server:
        raise RuntimeError('Plex server for media item no longer exists')
    root = G['plex_request_xml'](server, str(item.get('plex_key') or f"/library/metadata/{item.get('rating_key')}"), {'includeMedia': 1}, timeout=30)
    part = next((el for el in root.iter() if el.tag.lower().endswith('part') and (el.attrib.get('key') or el.attrib.get('file'))), None)
    if part is None:
        raise RuntimeError('Plex metadata did not include a Media Part')
    part_key = str(part.attrib.get('key') or '')
    if part_key.startswith('http://') or part_key.startswith('https://'):
        url = part_key
    else:
        url = str(server['base_url']).rstrip('/') + ('/' if part_key and not part_key.startswith('/') else '') + part_key
    headers = (
        f"X-Plex-Token: {server['token']}\r\n"
        f"X-Plex-Product: {G['APP_NAME']}\r\n"
        f"X-Plex-Version: {G['APP_VERSION']}\r\n"
        "X-Plex-Client-Identifier: vipertv-server\r\n"
    )
    streams: list[dict[str, Any]] = []
    audio_ord = subtitle_ord = 0
    for el in part.iter():
        if not el.tag.lower().endswith('stream'):
            continue
        a = el.attrib
        st = int(a.get('streamType') or 0)
        typ = 'audio' if st == 2 else 'subtitle' if st == 3 else ''
        if not typ:
            continue
        title = str(a.get('title') or a.get('displayTitle') or '')
        streams.append({
            'type':typ,
            'index':int(a.get('index') or 0),
            'ordinal': audio_ord if typ == 'audio' else subtitle_ord,
            'language':str(a.get('languageCode') or a.get('language') or '').strip().lower(),
            'title':title,
            'codec':str(a.get('codec') or '').strip().lower(),
            'channels':int(float(a.get('channels') or 0)),
            'forced':1 if str(a.get('forced') or '0') in ('1','true','True') else 0,
            'default':1 if str(a.get('default') or '0') in ('1','true','True') else 0,
            'sdh':1 if re.search(r'\b(SDH|HI|HEARING[ -]?IMPAIRED|CC)\b', title, re.I) else 0,
            'external':1 if typ == 'subtitle' and bool(a.get('key')) else 0,
            'path': (
                (str(server['base_url']).rstrip('/') + ('/' if not str(a.get('key') or '').startswith('/') else '') + str(a.get('key') or '') +
                 ('&' if '?' in str(a.get('key') or '') else '?') + 'X-Plex-Token=' + quote(str(server['token'])))
                if typ == 'subtitle' and bool(a.get('key')) else None
            ),
        })
        if typ == 'audio': audio_ord += 1
        else: subtitle_ord += 1
    info = {
        'server_id':int(server['id']), 'url':url, 'headers':headers,
        'part_file':str(part.attrib.get('file') or '').strip(), 'streams':streams,
    }
    local = _translate_plex_path(info['server_id'], info['part_file']) if info['part_file'] else None
    info['local_path'] = local or ''
    # Cache path information in ViperTV only; Plex is never modified.
    try:
        with _db() as conn:
            conn.execute('UPDATE plex_media SET part_file=?,direct_local_path=?,part_info_at=? WHERE plex_library_id=? AND rating_key=?',
                         (info['part_file'] or None, local or None, _now(), int(item.get('plex_library_id') or 0), str(item.get('rating_key') or '')))
            conn.commit()
    except Exception:
        pass
    _PLEX_INFO_CACHE[key] = (now, dict(info))
    return info


def _norm_remote_path(p: str) -> str:
    return str(p or '').replace('\\', '/').rstrip('/')


def _translate_plex_path(server_id: int, remote_path: str) -> str | None:
    rp = _norm_remote_path(remote_path)
    if not rp:
        return None
    with _db() as conn:
        rules = conn.execute('SELECT * FROM plex_path_replacements WHERE server_id=? AND enabled=1 ORDER BY priority DESC,LENGTH(remote_prefix) DESC,id', (server_id,)).fetchall()
    folded = rp.casefold()
    for r in rules:
        prefix = _norm_remote_path(str(r['remote_prefix']))
        if not prefix or not folded.startswith(prefix.casefold()):
            continue
        # Only match a path boundary, not /Movies against /Movies2.
        if len(rp) > len(prefix) and rp[len(prefix)] != '/':
            continue
        suffix = rp[len(prefix):].lstrip('/')
        candidate = os.path.join(str(r['local_prefix']), *([x for x in suffix.split('/') if x])) if suffix else str(r['local_prefix'])
        if Path(candidate).exists():
            return candidate
    return None


def _plex_direct_part_source_v129(item: dict[str, Any]) -> tuple[str, str]:
    info = _plex_part_info(item)
    return str(info['url']), str(info['headers'])


def _active_profile(channel_id: int):
    with _db() as conn:
        r = conn.execute('''SELECT p.* FROM channel_stream_selectors cs JOIN stream_selector_profiles p ON p.id=cs.profile_id WHERE cs.channel_id=? AND p.enabled=1''', (channel_id,)).fetchone()
        if r:
            return r
        gid = str(G['get_setting']('stream_selector_default_profile_id', '') or '')
        if gid.isdigit():
            return conn.execute('SELECT * FROM stream_selector_profiles WHERE id=? AND enabled=1', (int(gid),)).fetchone()
    return None


def _time_match(start: int | None, end: int | None, minute: int) -> bool:
    if start is None and end is None:
        return True
    if start is None: start = 0
    if end is None: end = 1440
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end


def _rule_matches_stream(rule, s: dict[str, Any]) -> bool:
    lang = str(rule['language'] or '').strip().casefold()
    if lang:
        candidates = {str(s.get('language') or '').casefold()}
        aliases = {
            'english':{'eng','en','english'},'spanish':{'spa','es','spanish'},'french':{'fra','fre','fr','french'},
            'japanese':{'jpn','ja','japanese'},'german':{'deu','ger','de','german'},'italian':{'ita','it','italian'},
            'portuguese':{'por','pt','portuguese'},'dutch':{'nld','dut','nl','dutch'},'korean':{'kor','ko','korean'},
            'chinese':{'zho','chi','zh','chinese'},'russian':{'rus','ru','russian'}
        }
        want = aliases.get(lang, {lang})
        if not candidates.intersection(want): return False
    title = str(rule['title_contains'] or '').strip().casefold()
    if title and title not in str(s.get('title') or '').casefold(): return False
    codec = str(rule['codec'] or '').strip().casefold()
    if codec and codec not in str(s.get('codec') or '').casefold(): return False
    if rule['min_channels'] is not None and int(s.get('channels') or 0) < int(rule['min_channels']): return False
    if rule['max_channels'] is not None and int(s.get('channels') or 0) > int(rule['max_channels']): return False
    for col,key in (('forced','forced'),('default_flag','default'),('sdh','sdh'),('external_only','external')):
        rv = int(rule[col])
        if rv in (0,1) and int(bool(s.get(key))) != rv: return False
    return True


def _select_streams(channel, item: dict[str, Any], source: str, headers: str = '', plex_streams: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    profile = _active_profile(int(channel['id']))
    streams = [dict(x) for x in (plex_streams or _json_streams_from_ffprobe(source, headers))]
    audio = [x for x in streams if x.get('type') == 'audio']
    subs = [x for x in streams if x.get('type') == 'subtitle']
    result = {'audio': audio[0] if audio else None, 'subtitle': None, 'subtitle_action': 'none', 'profile': None, 'streams': streams}
    if not profile:
        # Preserve the legacy channel subtitle preference when no advanced profile is assigned.
        legacy = str(channel['subtitle_mode'] or 'none') if 'subtitle_mode' in channel.keys() else 'none'
        if legacy in ('burn','copy') and subs:
            result['subtitle'] = subs[0]; result['subtitle_action'] = legacy
        return result
    result['profile'] = str(profile['name'])
    minute = datetime.now().astimezone().hour * 60 + datetime.now().astimezone().minute
    with _db() as conn:
        rules = conn.execute('SELECT * FROM stream_selector_rules WHERE profile_id=? ORDER BY priority DESC,id', (int(profile['id']),)).fetchall()
    for kind, pool in (('audio', audio), ('subtitle', subs)):
        for r in rules:
            if str(r['kind']) != kind: continue
            if r['channel_id'] is not None and int(r['channel_id']) != int(channel['id']): continue
            if not _time_match(r['start_minute'], r['end_minute'], minute): continue
            action = str(r['action'] or 'select')
            if action == 'none':
                # An unconditional None rule disables subtitles for this channel/time.
                # If stream predicates were supplied, disable only when one of those streams exists.
                has_predicates = any((r['language'], r['title_contains'], r['codec'], r['min_channels'], r['max_channels'])) or any(int(r[x]) in (0,1) for x in ('forced','default_flag','sdh','external_only'))
                if (not has_predicates) or any(_rule_matches_stream(r, s) for s in pool):
                    if kind == 'subtitle': result['subtitle'] = None; result['subtitle_action'] = 'none'
                    break
                continue
            match = next((s for s in pool if _rule_matches_stream(r, s)), None)
            if match is None: continue
            if kind == 'audio': result['audio'] = match
            else:
                result['subtitle'] = match
                result['subtitle_action'] = action if action in ('burn','copy') else 'burn'
            break
    return result


def _template_text(template: str, channel, item: dict[str, Any]) -> str:
    now = datetime.now().astimezone()
    season = item.get('season_number'); episode = item.get('episode_number')
    code = f"S{int(season):02d}E{int(episode):02d}" if season is not None and episode is not None else ''
    values = {
        'channel_name':str(channel['name']), 'channel_number':str(channel['number']),
        'title':str(item.get('title') or ''), 'show_title':str(item.get('show_title') or ''),
        'episode_title':str(item.get('episode_title') or item.get('title') or ''), 'episode_code':code,
        'season':str(season if season is not None else ''), 'episode':str(episode if episode is not None else ''),
        'year':str(item.get('year') or item.get('show_year') or ''), 'air_date':str(item.get('air_date') or ''),
        'rating':str(item.get('content_rating') or ''), 'network':str(item.get('original_network') or ''),
        'artist':str(item.get('artist') or ''), 'album':str(item.get('album') or ''), 'library':str(item.get('library_name') or ''),
        'time':now.strftime('%H:%M'), 'now':now.strftime('%H:%M'), 'date':now.strftime('%Y-%m-%d'), 'weekday':now.strftime('%A'),
    }
    out = str(template or '')
    for k,v in values.items(): out = out.replace('{{'+k+'}}', v).replace('{'+k+'}', v)
    return out


def _escape_drawtext(text: str) -> str:
    return str(text).replace('\\','\\\\').replace(':','\\:').replace("'","\\'").replace('%','\\%').replace(',','\\,').replace('\n','\\n')


def _subtitle_alignment(location: str) -> int:
    loc = str(location or 'BottomCenter').casefold()
    row = 7 if 'top' in loc else 4 if ('middle' in loc or 'center' in loc and 'bottom' not in loc and 'top' not in loc) else 1
    col = 1 if 'left' in loc else 3 if 'right' in loc else 2
    return row + col - 1


def _subtitle_copy_supported(codec: str) -> bool:
    # MPEG-TS cannot carry common text subtitle codecs such as SRT/ASS/WebVTT.
    # Preserve a usable station by burning those when a Copy rule selects them.
    return str(codec or '').casefold() in {'dvb_subtitle','dvb_teletext','hdmv_pgs_subtitle','pgssub'}


def _advanced_media_command_v129(channel, item: dict[str, Any], offset: float, input_args: list[str], profile_override: str | None = None) -> list[str]:
    profile, _configured, _warning = G['effective_stream_profile'](channel, profile_override)
    bitrate = str(channel['video_bitrate'] or G['VIDEO_BITRATE'])
    resolution = str(channel['resolution'] or '1920x1080')
    try: width, height = [int(x) for x in resolution.lower().split('x',1)]
    except Exception: width, height = 1920,1080
    actual_offset = max(0.0, float(offset or 0.0) + float(item.get('_segment_start') or 0.0))
    source = ''
    try:
        i = max(idx for idx,x in enumerate(input_args) if x == '-i')
        source = str(input_args[i+1])
    except Exception: pass
    headers = ''
    try:
        hi = input_args.index('-headers'); headers = str(input_args[hi+1])
    except Exception: pass
    selected = _select_streams(channel, item, source, headers, item.get('_v129_streams')) if source else {'audio':None,'subtitle':None,'subtitle_action':'none','profile':None,'streams':[]}
    item['_stream_selector_profile'] = selected.get('profile')
    if selected.get('audio'): item['_selected_audio'] = dict(selected['audio'])
    if selected.get('subtitle'): item['_selected_subtitle'] = dict(selected['subtitle'])
    item['_selected_subtitle_action'] = selected.get('subtitle_action') or 'none'
    if selected.get('subtitle') and selected.get('subtitle_action') == 'copy' and not _subtitle_copy_supported(str(selected['subtitle'].get('codec') or '')):
        selected['subtitle_action'] = 'burn'
        item['_selected_subtitle_action'] = 'burn'
        item['_subtitle_copy_fallback'] = 'Selected subtitle codec is not MPEG-TS pass-through compatible; burned instead.'

    base = ['ffmpeg','-hide_banner','-loglevel','error']
    preferred = G['hardware_preferred_vaapi_device']() or None
    base += G['hwaccel'].ffmpeg_device_args(profile, preferred)
    base += ['-re','-ss',f'{actual_offset:.3f}',*input_args]

    graphics = adv._graphics_for_item(channel, item)
    if item.get('_graphics_names'):
        extra_ids = adv._graphics_names_to_ids([str(x) for x in item.get('_graphics_names') or []])
        if extra_ids:
            with _db() as conn:
                q='SELECT * FROM graphics_elements WHERE enabled=1 AND id IN (%s)' % ','.join('?'*len(extra_ids))
                more=conn.execute(q,tuple(extra_ids)).fetchall()
            by={int(r['id']):r for r in graphics}; by.update({int(r['id']):r for r in more}); graphics=sorted(by.values(),key=lambda r:(int(r['z_index'] or 0),int(r['id'])))

    legacy_logo = None
    try:
        if channel['watermark_enabled'] and not item.get('_disable_watermark'):
            p=str(channel['logo_path'] or '')
            if p and Path(p).exists(): legacy_logo=p
    except Exception: pass

    # Add image/motion assets as extra FFmpeg inputs in exact z-index order.
    assets: dict[int,int] = {}
    input_index = 1
    for r in graphics:
        kind=str(r['kind'] or '')
        p=str(r['image_path'] or '')
        if kind == 'image' and p and Path(p).exists():
            base += ['-loop','1','-i',p]; assets[int(r['id'])]=input_index; input_index+=1
        elif kind == 'video' and p and Path(p).exists():
            if int(r['loop_asset'] or 0): base += ['-stream_loop','-1']
            base += ['-i',p]; assets[int(r['id'])]=input_index; input_index+=1
    if legacy_logo:
        base += ['-loop','1','-i',legacy_logo]; legacy_index=input_index; input_index+=1
    else: legacy_index=None

    filters: list[str] = []
    vin='[0:v]'
    # Advanced selector subtitle burn happens before the reusable graphics stack,
    # unless a dedicated Subtitle Graphic is present (that element owns styling/timing).
    sub = selected.get('subtitle'); sub_action=str(selected.get('subtitle_action') or 'none')
    has_subtitle_graphic = any(str(r['kind'] or '') == 'subtitle' for r in graphics)
    if sub and sub_action == 'burn' and not has_subtitle_graphic:
        subpath = str(sub.get('path') or '')
        if not subpath and source and not source.startswith(('http://','https://')):
            subpath = source
        if subpath:
            esc=subpath.replace('\\','/').replace(':','\\:').replace("'","\\'")
            si = sub.get('ordinal')
            opt = f':si={int(si)}' if si is not None and not sub.get('external') else ''
            filters.append(f"{vin}subtitles='{esc}'{opt}[vsel]"); vin='[vsel]'
    elif str(channel['subtitle_mode'] or 'none') == 'burn' and item.get('subtitle_path'):
        esc=str(item['subtitle_path']).replace('\\','/').replace(':','\\:').replace("'","\\'")
        filters.append(f"{vin}subtitles='{esc}'[vlegacy_sub]"); vin='[vlegacy_sub]'

    for n,r in enumerate(graphics):
        kind=str(r['kind'] or '')
        start=max(0.0,float(r['start_seconds'] or 0)); end=r['end_seconds']
        enable=f":enable='between(t,{start:.3f},{float(end):.3f})'" if end is not None and float(end)>start else (f":enable='gte(t,{start:.3f})'" if start>0 else '')
        if kind in ('image','video') and int(r['id']) in assets:
            idx=assets[int(r['id'])]
            target=max(8,int(width*float(r['scale_width_percent'] or 12)/100.0)); opacity=max(0,min(1,float(r['opacity_percent'] or 100)/100.0))
            lab=f'g{n}'
            chain=f'[{idx}:v]scale={target}:-1,format=rgba'
            if opacity < .999: chain += f',colorchannelmixer=aa={opacity:.3f}'
            if kind == 'video': chain += f',setpts=PTS-STARTPTS+{start:.3f}/TB'
            filters.append(chain+f'[{lab}]')
            x,y=adv._xy(str(r['location']),float(r['horizontal_margin_percent']),float(r['vertical_margin_percent']),width,height)
            out=f'vg{n}'; filters.append(f'{vin}[{lab}]overlay={x}:{y}:shortest=0:eof_action=repeat{enable}[{out}]');vin=f'[{out}]'
        elif kind == 'text' and str(r['text_template'] or '').strip():
            txt=_escape_drawtext(_template_text(str(r['text_template']),channel,item));x,y=adv._text_xy(str(r['location']),float(r['horizontal_margin_percent']),float(r['vertical_margin_percent']),width,height)
            op=max(0,min(1,float(r['opacity_percent'] or 100)/100.0));box=':box=1:boxcolor=black@0.45:boxborderw=10' if r['box_enabled'] else ''
            out=f'vt{n}';filters.append(f"{vin}drawtext=text='{txt}':x={x}:y={y}:fontsize={int(r['font_size'] or 32)}:fontcolor={str(r['text_color'] or 'white')}@{op:.3f}{box}{enable}[{out}]");vin=f'[{out}]'
        elif kind == 'subtitle':
            # Dedicated subtitle graphic: render the stream chosen by the selector with its own ASS style.
            s=selected.get('subtitle')
            subpath=str((s or {}).get('path') or '')
            if not subpath and source and not source.startswith(('http://','https://')): subpath=source
            if subpath:
                esc=subpath.replace('\\','/').replace(':','\\:').replace("'","\\'")
                si=(s or {}).get('ordinal'); opt=f':si={int(si)}' if si is not None and not (s or {}).get('external') else ''
                align=_subtitle_alignment(str(r['location'])); margin=max(8,int(height*float(r['vertical_margin_percent'] or 3)/100.0))
                style=str(r['subtitle_style'] or '').strip() or f"FontSize={int(r['font_size'] or 32)},Alignment={align},MarginV={margin}"
                style=style.replace("'","\\'")
                out=f'vs{n}'; filters.append(f"{vin}subtitles='{esc}'{opt}:force_style='{style}'[{out}]");vin=f'[{out}]'

    if legacy_index is not None:
        target=max(8,int(width*.12));filters.append(f'[{legacy_index}:v]scale={target}:-1,format=rgba,colorchannelmixer=aa=0.90[legacylogo]');filters.append(f'{vin}[legacylogo]overlay=main_w-overlay_w-24:24[vlegacy]');vin='[vlegacy]'

    has_filters=bool(filters)
    audio=selected.get('audio')
    audio_map=f"0:{int(audio['index'])}?" if audio and audio.get('index') is not None else '0:a:0?'
    subtitle_copy = sub if sub and sub_action == 'copy' and sub.get('index') is not None else None
    if has_filters:
        base += ['-filter_complex',';'.join(filters),'-map',vin,'-map',audio_map]
        profile='software'; item['_actual_stream_profile']='software'
    else:
        item['_actual_stream_profile']=profile;base += ['-map','0:v:0?','-map',audio_map]
        if subtitle_copy: base += ['-map',f"0:{int(subtitle_copy['index'])}?"]

    if profile=='direct' and not has_filters:
        base += ['-c:v','copy','-c:a','copy']
    elif profile=='qsv' and not has_filters:
        base += ['-vf',f"scale={resolution.replace('x',':')},format=nv12",'-c:v','h264_qsv','-b:v',bitrate,'-c:a','aac','-b:a',G['AUDIO_BITRATE']]
    elif profile=='vaapi' and not has_filters:
        base += ['-vf',f"scale={resolution.replace('x',':')},format=nv12,hwupload",'-c:v','h264_vaapi','-b:v',bitrate,'-c:a','aac','-b:a',G['AUDIO_BITRATE']]
    elif profile=='nvenc' and not has_filters:
        base += ['-vf',f"scale={resolution.replace('x',':')},format=yuv420p",'-c:v','h264_nvenc','-preset','p4','-tune','ll','-b:v',bitrate,'-c:a','aac','-b:a',G['AUDIO_BITRATE']]
    elif profile=='amf' and not has_filters:
        base += ['-vf',f"scale={resolution.replace('x',':')},format=nv12",'-c:v','h264_amf','-quality','speed','-b:v',bitrate,'-c:a','aac','-b:a',G['AUDIO_BITRATE']]
    else:
        base += ['-c:v','libx264','-preset',G['TRANSCODE_PRESET'],'-s',resolution,'-pix_fmt','yuv420p','-b:v',bitrate,'-c:a','aac','-b:a',G['AUDIO_BITRATE'],'-ar','48000']
    if subtitle_copy: base += ['-c:s','copy']
    else: base += ['-sn']
    if channel['frame_rate']: base += ['-r',str(channel['frame_rate'])]
    base += ['-dn','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
    return base


def _local_command_v129(channel, item: dict[str, Any], offset: float, profile_override: str | None = None) -> list[str]:
    path=str(item.get('path') or channel['offline_media'] or '')
    if not path: return ['false']
    if _active_profile(int(channel['id'])) or adv._item_needs_advanced_graphics(channel,item) or float(item.get('_segment_start') or 0)>0:
        return _advanced_media_command_v129(channel,item,offset,['-i',path],profile_override)
    return _BASE_LOCAL(channel,item,offset,profile_override)


def _plex_command_v129(channel, item: dict[str, Any], offset: float, url: str, headers: str, profile_override: str | None = None) -> list[str]:
    try:
        info=_plex_part_info(item); item['_v129_streams']=[dict(x) for x in info.get('streams') or []]
        local=str(info.get('local_path') or '')
        if local and Path(local).exists():
            clone=dict(item); clone['path']=local; clone['_v129_streams']=item['_v129_streams']; clone['_plex_direct_disk']=True
            return _advanced_media_command_v129(channel,clone,offset,['-i',local],profile_override) if (_active_profile(int(channel['id'])) or adv._item_needs_advanced_graphics(channel,clone) or float(clone.get('_segment_start') or 0)>0) else _BASE_LOCAL(channel,clone,offset,profile_override)
    except Exception:
        pass
    if _active_profile(int(channel['id'])) or adv._item_needs_advanced_graphics(channel,item) or float(item.get('_segment_start') or 0)>0:
        return _advanced_media_command_v129(channel,item,offset,['-headers',headers,'-i',url],profile_override)
    return _BASE_PLEX(channel,item,offset,url,headers,profile_override)


def _external_command_v129(channel, item: dict[str, Any], offset: float) -> list[str]:
    if _active_profile(int(channel['id'])) or adv._item_needs_advanced_graphics(channel,item) or float(item.get('_segment_start') or 0)>0:
        url=G['_external_stream_url'](item); return _advanced_media_command_v129(channel,item,offset,['-i',url])
    return _BASE_EXTERNAL(channel,item,offset)


# --------------------- UI helpers ---------------------

def _tri(name: str, value: int = -1) -> str:
    return f"<select name='{name}'><option value='-1' {'selected' if value==-1 else ''}>Any</option><option value='1' {'selected' if value==1 else ''}>Yes</option><option value='0' {'selected' if value==0 else ''}>No</option></select>"


def _selector_page(msg: str = '') -> str:
    with _db() as conn:
        profiles=conn.execute('SELECT * FROM stream_selector_profiles ORDER BY name COLLATE NOCASE').fetchall()
        channels=conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
        assigned={int(r['channel_id']):int(r['profile_id']) for r in conn.execute('SELECT * FROM channel_stream_selectors').fetchall()}
    default=str(G['get_setting']('stream_selector_default_profile_id','') or '')
    rows=''.join(f"<tr><td><b>{_e(p['name'])}</b></td><td>{_e(p['description'] or '')}</td><td>{'Enabled' if p['enabled'] else 'Disabled'}</td><td><a class='button secondary' href='/system/stream-selectors/{p['id']}'>Rules</a></td></tr>" for p in profiles) or "<tr><td colspan='4' class='empty'>No selector profiles yet.</td></tr>"
    popts="<option value=''>Legacy channel behavior</option>"+''.join(f"<option value='{p['id']}'>{_e(p['name'])}</option>" for p in profiles if p['enabled'])
    assignment_rows=[]
    for c in channels:
        opts="<option value=''>Use global / legacy</option>"
        for p in profiles:
            if not p['enabled']:
                continue
            sel='selected' if assigned.get(int(c['id'])) == int(p['id']) else ''
            opts += f"<option value='{p['id']}' {sel}>{_e(p['name'])}</option>"
        assignment_rows.append(f"<tr><td>{_e(c['number'])} {_e(c['name'])}</td><td><form method='post' action='/system/stream-selectors/assign' class='inline'><input type='hidden' name='channel_id' value='{c['id']}'><select name='profile_id' style='width:260px'>{opts}</select><button>Save</button></form></td></tr>")
    assignments=''.join(assignment_rows) or "<tr><td colspan='2'>No channels.</td></tr>"
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Audio / Subtitle Stream Selector','Prioritized audio and subtitle selection by language, title, codec, channels, forced/default, SDH, external status, channel and time of day.')+f"""
<div class='grid'><div class='card'><h2>Create Profile</h2><form method='post' action='/system/stream-selectors/add'><label>Name</label><input name='name' required placeholder='English 5.1 + Forced Subs'><label>Description</label><input name='description'><button>Create Profile</button></form></div>
<div class='card'><h2>Global Default</h2><form method='post' action='/system/stream-selectors/default'><label>Profile</label><select name='profile_id'>{popts.replace("value='"+default+"'", "value='"+default+"' selected") if default else popts}</select><button>Save Global Default</button></form><p class='muted small'>A channel-specific assignment overrides the global profile. With neither assigned, ViperTV keeps the existing channel subtitle behavior.</p></div></div>
<div class='card'><h2>Profiles</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Description</th><th>Status</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Per-Channel Assignment</h2><div class='table-wrap'><table><thead><tr><th>Channel</th><th>Profile</th></tr></thead><tbody>{assignments}</tbody></table></div></div>"""
    return _page('Stream Selector',body)


def _selector_edit(pid: int, msg: str = '') -> str:
    with _db() as conn:
        p=conn.execute('SELECT * FROM stream_selector_profiles WHERE id=?',(pid,)).fetchone()
        if not p: raise HTTPException(404,'Selector profile not found')
        rules=conn.execute('''SELECT r.*,c.number channel_number,c.name channel_name FROM stream_selector_rules r LEFT JOIN channels c ON c.id=r.channel_id WHERE r.profile_id=? ORDER BY r.kind,r.priority DESC,r.id''',(pid,)).fetchall()
        channels=conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
    def yn(v:int)->str:return 'Any' if int(v)==-1 else 'Yes' if int(v)==1 else 'No'
    rows=''.join(f"<tr><td>{_e(r['kind'])}</td><td>{r['priority']}</td><td>{_e(r['language'] or '*')}</td><td>{_e(r['title_contains'] or '*')}</td><td>{_e(r['codec'] or '*')}</td><td>{_e((str(r['min_channels'])+'+') if r['min_channels'] is not None else '*')}</td><td>forced:{yn(r['forced'])} default:{yn(r['default_flag'])} SDH:{yn(r['sdh'])} ext:{yn(r['external_only'])}</td><td>{_e((str(r['channel_number'])+' '+str(r['channel_name'])) if r['channel_id'] else 'Any')}</td><td>{_e((_hm(r['start_minute'])+'–'+_hm(r['end_minute'])) if r['start_minute'] is not None or r['end_minute'] is not None else 'Any')}</td><td>{_e(r['action'])}</td><td><form method='post' action='/system/stream-selectors/{pid}/rules/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for r in rules) or "<tr><td colspan='11' class='empty'>No rules yet. Without rules, the first audio stream is used and subtitles are off.</td></tr>"
    copts="<option value=''>Any channel</option>"+''.join(f"<option value='{c['id']}'>{_e(c['number'])} {_e(c['name'])}</option>" for c in channels)
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Stream Selector Profile',str(p['name']),"<a class='button secondary' href='/system/stream-selectors'>Back</a>")+f"""
<div class='card'><form method='post' action='/system/stream-selectors/{pid}/save'><div class='grid'><div><label>Name</label><input name='name' value='{_e(p['name'])}' required></div><div><label>Description</label><input name='description' value='{_e(p['description'] or '')}'></div></div><label><input type='checkbox' name='enabled' value='1' {'checked' if p['enabled'] else ''}> Enabled</label><button>Save Profile</button></form></div>
<div class='card'><h2>Prioritized Rules</h2><p class='muted'>Highest priority matching rule wins independently for Audio and Subtitles. Leave a field blank/Any when it should not restrict a match.</p><div class='table-wrap'><table><thead><tr><th>Type</th><th>Priority</th><th>Language</th><th>Title</th><th>Codec</th><th>Channels</th><th>Flags</th><th>Channel</th><th>Time</th><th>Action</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Add Rule</h2><form method='post' action='/system/stream-selectors/{pid}/rules/add'><div class='grid3'><div><label>Type</label><select name='kind'><option value='audio'>Audio</option><option value='subtitle'>Subtitle</option></select><label>Priority</label><input type='number' name='priority' value='100'><label>Language</label><input name='language' placeholder='eng or English'><label>Title contains</label><input name='title_contains' placeholder='Commentary / Forced'><label>Codec</label><input name='codec' placeholder='aac / ac3 / srt'></div><div><label>Minimum channels</label><input type='number' name='min_channels' min='1' max='32' placeholder='6'><label>Maximum channels</label><input type='number' name='max_channels' min='1' max='32'><label>Forced</label>{_tri('forced')}<label>Default</label>{_tri('default_flag')}<label>SDH / Hearing Impaired</label>{_tri('sdh')}<label>External subtitle</label>{_tri('external_only')}</div><div><label>Only on channel</label><select name='channel_id'>{copts}</select><label>Start time</label><input type='time' name='start_time'><label>End time</label><input type='time' name='end_time'><label>Subtitle action</label><select name='action'><option value='select'>Select (audio) / Burn (subtitle)</option><option value='burn'>Burn subtitle</option><option value='copy'>Copy subtitle stream</option><option value='none'>Disable subtitles</option></select></div></div><button>Add Rule</button></form></div>
<div class='card'><form method='post' action='/system/stream-selectors/{pid}/delete' onsubmit="return confirm('Delete this selector profile?');"><button class='danger'>Delete Profile</button></form></div>"""
    return _page('Stream Selector Profile',body)


def _path_page(msg: str = '') -> str:
    with _db() as conn:
        servers=conn.execute('SELECT id,name,base_url FROM plex_servers ORDER BY name').fetchall()
        rows=conn.execute('''SELECT pr.*,ps.name server_name FROM plex_path_replacements pr JOIN plex_servers ps ON ps.id=pr.server_id ORDER BY ps.name,pr.priority DESC,pr.id''').fetchall()
        cached=conn.execute("SELECT COUNT(*) n FROM plex_media WHERE COALESCE(part_file,'')<>''").fetchone()['n']
        direct=conn.execute("SELECT COUNT(*) n FROM plex_media WHERE COALESCE(direct_local_path,'')<>''").fetchone()['n']
    ro=''.join(f"<tr><td>{_e(r['server_name'])}</td><td><code>{_e(r['remote_prefix'])}</code></td><td><code>{_e(r['local_prefix'])}</code></td><td>{r['priority']}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td><td><form method='post' action='/plex/path-replacements/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for r in rows) or "<tr><td colspan='6' class='empty'>No path replacements configured.</td></tr>"
    sopts=''.join(f"<option value='{s['id']}'>{_e(s['name'])}</option>" for s in servers)
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Plex Stream From Disk / Path Replacements','Translate the path stored by Plex into a local Windows path visible to ViperTV. Plex metadata stays authoritative, but FFmpeg reads the media directly from disk when the translated file exists.',"<a class='button secondary' href='/plex'>Back to Plex</a>")+f"""
<div class='stats'><div class='stat'><div class='stat-label'>Rules</div><div class='stat-value'>{len(rows)}</div></div><div class='stat'><div class='stat-label'>Plex Part Paths Cached</div><div class='stat-value'>{int(cached):,}</div></div><div class='stat'><div class='stat-label'>Direct Paths Resolved</div><div class='stat-value'>{int(direct):,}</div></div></div>
<div class='card'><h2>Add Replacement</h2><form method='post' action='/plex/path-replacements/add'><div class='grid'><div><label>Plex Server</label><select name='server_id' required>{sopts}</select><label>Plex path prefix</label><input name='remote_prefix' required placeholder='/volume1/Media or D:\\Media'></div><div><label>ViperTV local path prefix</label><input name='local_prefix' required placeholder='D:\\Media\\TV or \\\\server\\share\\TV'><label>Priority</label><input type='number' name='priority' value='100'></div></div><button>Add Replacement</button></form><p class='muted small'>The destination path must already be accessible to the Windows account running ViperTV. Mapped drives and UNC paths are supported.</p></div>
<div class='card'><h2>Replacement Rules</h2><div class='table-wrap'><table><thead><tr><th>Server</th><th>Plex Prefix</th><th>Local Prefix</th><th>Priority</th><th>Status</th><th></th></tr></thead><tbody>{ro}</tbody></table></div></div>
<div class='card'><h2>Test Translation</h2><form method='post' action='/plex/path-replacements/test'><div class='grid'><div><label>Plex Server</label><select name='server_id' required>{sopts}</select></div><div><label>Example Plex file path</label><input name='remote_path' required placeholder='/volume1/Media/TV/MASH/S02E13.mkv'></div></div><button class='secondary'>Test Path</button></form></div>"""
    return _page('Plex Path Replacements',body)


def _graphics_page_v129(msg: str = '') -> str:
    with _db() as conn:
        graphics=conn.execute('SELECT * FROM graphics_elements ORDER BY z_index,name').fetchall();channels=conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall();assigns=conn.execute('SELECT cg.*,c.number,c.name channel_name,ge.name graphic_name FROM channel_graphics cg JOIN channels c ON c.id=cg.channel_id JOIN graphics_elements ge ON ge.id=cg.graphic_id ORDER BY CAST(c.number AS REAL),c.number,ge.z_index,ge.name').fetchall()
    rows=''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{_e(x['kind'])}</td><td>{int(x['z_index'] or 0)}</td><td>{_e(x['location'])}</td><td>{x['start_seconds']}–{_e(x['end_seconds'] if x['end_seconds'] is not None else 'end')}</td><td>{_e(x['image_path'] or x['text_template'] or '')}</td><td><a class='button secondary' href='/system/graphics/{x['id']}/edit'>Edit</a> <form class='inline' method='post' action='/system/graphics/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for x in graphics) or "<tr><td colspan='7'>No graphics.</td></tr>"
    arows=''.join(f"<tr><td>{_e(x['number'])} {_e(x['channel_name'])}</td><td>{_e(x['graphic_name'])}</td><td>{_e(x['scope'])}</td><td><form class='inline' method='post' action='/system/graphics/assignment/delete'><input type='hidden' name='channel_id' value='{x['channel_id']}'><input type='hidden' name='graphic_id' value='{x['graphic_id']}'><button class='danger'>Remove</button></form></td></tr>" for x in assigns) or "<tr><td colspan='4'>No assignments.</td></tr>"
    copts=''.join(f"<option value='{x['id']}'>{_e(x['number'])} {_e(x['name'])}</option>" for x in channels);gopts=''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in graphics)
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Graphics Engine 2.0','Image bugs, dynamic text, dedicated subtitle rendering and looping motion/video overlays. Every reusable graphic has z-index and timing controls.')+f"""
<div class='card'><h2>Create Graphic</h2><form method='post' action='/system/graphics/v129/add'><div class='grid3'><div><label>Name</label><input name='name' required><label>Type</label><select name='kind'><option value='image'>Image</option><option value='text'>Dynamic Text</option><option value='subtitle'>Subtitle Graphic</option><option value='video'>Motion / Video Overlay</option></select><label>Asset path</label><input name='image_path' placeholder='C:\\Media\\logos\\bug.png or C:\\Media\\overlays\\animated.webm'><label>Text template</label><textarea name='text_template' rows='3' placeholder='Up Next: {{show_title}} {{episode_code}}'></textarea><label>Subtitle ASS style (optional)</label><input name='subtitle_style' placeholder='FontName=Arial,FontSize=32,Outline=2'></div><div><label>Location</label><select name='location'><option>TopLeft</option><option>TopCenter</option><option>TopRight</option><option>MiddleLeft</option><option>Center</option><option>MiddleRight</option><option>BottomLeft</option><option>BottomCenter</option><option selected>BottomRight</option></select><label>Scale width %</label><input type='number' step='0.1' name='scale_width_percent' value='12'><label>Opacity %</label><input type='number' name='opacity_percent' value='90'><label>Font size</label><input type='number' name='font_size' value='32'><label>Text color</label><input name='text_color' value='white'><label><input type='checkbox' name='box_enabled' value='1'> Text box</label></div><div><label>Horizontal margin %</label><input type='number' step='0.1' name='horizontal_margin_percent' value='3'><label>Vertical margin %</label><input type='number' step='0.1' name='vertical_margin_percent' value='3'><label>Start seconds</label><input type='number' step='0.1' name='start_seconds' value='0'><label>End seconds (blank = end)</label><input name='end_seconds'><label>Z-index</label><input type='number' name='z_index' value='1'><label><input type='checkbox' name='loop_asset' value='1' checked> Loop motion/video asset</label></div></div><p class='muted small'>Templates: {{channel_name}}, {{channel_number}}, {{title}}, {{show_title}}, {{episode_title}}, {{episode_code}}, {{season}}, {{episode}}, {{year}}, {{air_date}}, {{rating}}, {{network}}, {{artist}}, {{album}}, {{library}}, {{time}}, {{date}}, {{weekday}}.</p><button>Create Graphic</button></form></div>
<div class='card'><h2>Graphics</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Type</th><th>Z</th><th>Location</th><th>Timing</th><th>Content / Asset</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='grid'><div class='card'><h2>Assign to Channel</h2><form method='post' action='/system/graphics/assign'><label>Channel</label><select name='channel_id'>{copts}</select><label>Graphic</label><select name='graphic_id'>{gopts}</select><label>Scope</label><select name='scope'><option value='all'>All programming</option><option value='primary'>Primary only</option><option value='filler'>Filler only</option></select><button>Assign</button></form></div><div class='card'><h2>Assignments</h2><div class='table-wrap'><table><thead><tr><th>Channel</th><th>Graphic</th><th>Scope</th><th></th></tr></thead><tbody>{arows}</tbody></table></div></div></div>"""
    return _page('Graphics & Branding',body)


def _graphics_edit_v129(gid: int, msg: str = '') -> str:
    with _db() as conn:r=conn.execute('SELECT * FROM graphics_elements WHERE id=?',(gid,)).fetchone()
    if not r: raise HTTPException(404,'Graphic not found')
    opts=''.join(f"<option value='{k}' {'selected' if str(r['kind'])==k else ''}>{lab}</option>" for k,lab in [('image','Image'),('text','Dynamic Text'),('subtitle','Subtitle Graphic'),('video','Motion / Video Overlay')])
    locs=['TopLeft','TopCenter','TopRight','MiddleLeft','Center','MiddleRight','BottomLeft','BottomCenter','BottomRight'];lopts=''.join(f"<option {'selected' if str(r['location'])==x else ''}>{x}</option>" for x in locs)
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Edit Graphic',str(r['name']),"<a class='button secondary' href='/system/graphics'>Back</a>")+f"""
<div class='card'><form method='post' action='/system/graphics/{gid}/v129-save'><div class='grid3'><div><label>Name</label><input name='name' value='{_e(r['name'])}' required><label>Type</label><select name='kind'>{opts}</select><label>Asset path</label><input name='image_path' value='{_e(r['image_path'] or '')}'><label>Text template</label><textarea name='text_template' rows='4'>{_e(r['text_template'] or '')}</textarea><label>Subtitle ASS style</label><input name='subtitle_style' value='{_e(r['subtitle_style'] or '')}'></div><div><label>Location</label><select name='location'>{lopts}</select><label>Scale width %</label><input type='number' step='.1' name='scale_width_percent' value='{r['scale_width_percent']}'><label>Opacity %</label><input type='number' name='opacity_percent' value='{r['opacity_percent']}'><label>Font size</label><input type='number' name='font_size' value='{r['font_size']}'><label>Text color</label><input name='text_color' value='{_e(r['text_color'])}'><label><input type='checkbox' name='box_enabled' value='1' {'checked' if r['box_enabled'] else ''}> Text box</label></div><div><label>Horizontal margin %</label><input type='number' step='.1' name='horizontal_margin_percent' value='{r['horizontal_margin_percent']}'><label>Vertical margin %</label><input type='number' step='.1' name='vertical_margin_percent' value='{r['vertical_margin_percent']}'><label>Start seconds</label><input type='number' step='.1' name='start_seconds' value='{r['start_seconds']}'><label>End seconds</label><input name='end_seconds' value='{_e(r['end_seconds'] if r['end_seconds'] is not None else '')}'><label>Z-index</label><input type='number' name='z_index' value='{r['z_index']}'><label><input type='checkbox' name='loop_asset' value='1' {'checked' if r['loop_asset'] else ''}> Loop motion/video asset</label><label><input type='checkbox' name='enabled' value='1' {'checked' if r['enabled'] else ''}> Enabled</label></div></div><button>Save Graphic</button></form></div>"""
    return _page('Edit Graphic',body)


def _save_graphic(gid: int | None, **kw):
    kind=str(kw['kind']); kind=kind if kind in ('image','text','subtitle','video') else 'image'
    vals=(str(kw['name']).strip(),kind,str(kw['image_path']).strip() or None,str(kw['text_template']).strip() or None,str(kw['location']),float(kw['horizontal_margin_percent']),float(kw['vertical_margin_percent']),float(kw['scale_width_percent']),max(0,min(100,float(kw['opacity_percent']))),max(8,int(kw['font_size'])),str(kw['text_color']).strip() or 'white',1 if kw['box_enabled'] else 0,max(0,float(kw['start_seconds'])),float(kw['end_seconds']) if str(kw['end_seconds']).strip() else None,int(kw['z_index']),1 if kw['enabled'] else 0,1 if kw['loop_asset'] else 0,str(kw['subtitle_style']).strip() or None,_now())
    with _db() as conn:
        if gid is None:
            conn.execute('''INSERT INTO graphics_elements(name,kind,image_path,text_template,location,horizontal_margin_percent,vertical_margin_percent,scale_width_percent,opacity_percent,font_size,text_color,box_enabled,start_seconds,end_seconds,z_index,enabled,loop_asset,subtitle_style,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',vals[:-1]+(_now(),_now()))
        else:
            conn.execute('''UPDATE graphics_elements SET name=?,kind=?,image_path=?,text_template=?,location=?,horizontal_margin_percent=?,vertical_margin_percent=?,scale_width_percent=?,opacity_percent=?,font_size=?,text_color=?,box_enabled=?,start_seconds=?,end_seconds=?,z_index=?,enabled=?,loop_asset=?,subtitle_style=?,updated_at=? WHERE id=?''',vals+(gid,))
        conn.commit()
    adv.BLOCK_DAY_CACHE.clear();adv.SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate']()


def install_v129(app, main_globals: dict[str, Any]) -> None:
    global G,_BASE_LOCAL,_BASE_PLEX,_BASE_EXTERNAL,_BASE_PLEX_SOURCE,_BASE_PLEX_PAGE
    G=main_globals
    base_init=G['init_v12_db']
    def init_all():
        base_init();init_v129_db()
    G['init_v12_db']=init_all

    _BASE_LOCAL=G['_profiled_local_command'];_BASE_PLEX=G['_profiled_plex_part_command'];_BASE_EXTERNAL=G['_profiled_external_command'];_BASE_PLEX_SOURCE=G['_plex_direct_part_source'];_BASE_PLEX_PAGE=G['plex_page']
    # The v1.2 advanced scheduling wrappers resolve this function by module name at runtime.
    adv._advanced_media_command=_advanced_media_command_v129
    G['_profiled_local_command']=_local_command_v129
    G['_profiled_plex_part_command']=_plex_command_v129
    G['_profiled_external_command']=_external_command_v129
    G['_plex_direct_part_source']=_plex_direct_part_source_v129
    adv._graphics_page=_graphics_page_v129
    adv._graphics_edit_page=_graphics_edit_v129

    def plex_page_v129(message: str=''):
        html=_BASE_PLEX_PAGE(message)
        marker="<div class='card'><h2>Plex Servers</h2>"
        button="<div class='card'><h2>Direct Media Paths</h2><p>Optionally translate Plex's original file paths to Windows paths visible to ViperTV so FFmpeg reads media directly from disk while Plex remains the metadata source.</p><a class='button secondary' href='/plex/path-replacements'>Manage Path Replacements</a></div>"
        return html.replace(marker,button+marker,1)
    G['plex_page']=plex_page_v129

    @app.get('/system/stream-selectors',response_class=HTMLResponse)
    def v129_selector_index(msg:str=''):return _selector_page(msg)
    @app.post('/system/stream-selectors/add')
    def v129_selector_add(name:str=Form(...),description:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO stream_selector_profiles(name,description,enabled,created_at,updated_at) VALUES(?,?,?,?,?)',(name.strip(),description.strip() or None,1,_now(),_now()));conn.commit();pid=int(cur.lastrowid)
            return RedirectResponse(f'/system/stream-selectors/{pid}',303)
        except sqlite3.IntegrityError:return RedirectResponse('/system/stream-selectors?msg='+quote('That profile name already exists.'),303)
    @app.post('/system/stream-selectors/default')
    def v129_selector_default(profile_id:str=Form('')):
        G['set_setting']('stream_selector_default_profile_id',profile_id if profile_id.isdigit() else '')
        return RedirectResponse('/system/stream-selectors?msg=Global+default+saved',303)
    @app.post('/system/stream-selectors/assign')
    def v129_selector_assign(channel_id:int=Form(...),profile_id:str=Form('')):
        G['safe_backup_before_change']()
        with _db() as conn:
            if profile_id.isdigit():conn.execute('INSERT INTO channel_stream_selectors(channel_id,profile_id) VALUES(?,?) ON CONFLICT(channel_id) DO UPDATE SET profile_id=excluded.profile_id',(channel_id,int(profile_id)))
            else:conn.execute('DELETE FROM channel_stream_selectors WHERE channel_id=?',(channel_id,))
            conn.commit()
        return RedirectResponse('/system/stream-selectors?msg=Channel+selector+saved',303)
    @app.get('/system/stream-selectors/{pid}',response_class=HTMLResponse)
    def v129_selector_edit(pid:int,msg:str=''):return _selector_edit(pid,msg)
    @app.post('/system/stream-selectors/{pid}/save')
    def v129_selector_save(pid:int,name:str=Form(...),description:str=Form(''),enabled:int=Form(0)):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:conn.execute('UPDATE stream_selector_profiles SET name=?,description=?,enabled=?,updated_at=? WHERE id=?',(name.strip(),description.strip() or None,1 if enabled else 0,_now(),pid));conn.commit()
        except sqlite3.IntegrityError:return RedirectResponse(f'/system/stream-selectors/{pid}?msg='+quote('That name is already in use.'),303)
        return RedirectResponse(f'/system/stream-selectors/{pid}?msg=Profile+saved',303)
    @app.post('/system/stream-selectors/{pid}/rules/add')
    def v129_rule_add(pid:int,kind:str=Form('audio'),priority:int=Form(100),language:str=Form(''),title_contains:str=Form(''),codec:str=Form(''),min_channels:str=Form(''),max_channels:str=Form(''),forced:int=Form(-1),default_flag:int=Form(-1),sdh:int=Form(-1),external_only:int=Form(-1),channel_id:str=Form(''),start_time:str=Form(''),end_time:str=Form(''),action:str=Form('select')):
        kind=kind if kind in ('audio','subtitle') else 'audio';action=action if action in ('select','burn','copy','none') else 'select'
        if kind=='audio':action='select'
        G['safe_backup_before_change']()
        with _db() as conn:
            conn.execute('''INSERT INTO stream_selector_rules(profile_id,kind,priority,language,title_contains,codec,min_channels,max_channels,forced,default_flag,sdh,external_only,channel_id,start_minute,end_minute,action,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(pid,kind,int(priority),language.strip() or None,title_contains.strip() or None,codec.strip() or None,int(min_channels) if min_channels.isdigit() else None,int(max_channels) if max_channels.isdigit() else None,int(forced),int(default_flag),int(sdh),int(external_only),int(channel_id) if channel_id.isdigit() else None,_hm_to_min(start_time),_hm_to_min(end_time),action,_now(),_now()));conn.commit()
        return RedirectResponse(f'/system/stream-selectors/{pid}?msg=Rule+added',303)
    @app.post('/system/stream-selectors/{pid}/rules/{rid}/delete')
    def v129_rule_delete(pid:int,rid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM stream_selector_rules WHERE id=? AND profile_id=?',(rid,pid));conn.commit()
        return RedirectResponse(f'/system/stream-selectors/{pid}?msg=Rule+deleted',303)
    @app.post('/system/stream-selectors/{pid}/delete')
    def v129_selector_delete(pid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM stream_selector_profiles WHERE id=?',(pid,));conn.commit()
        if str(G['get_setting']('stream_selector_default_profile_id','') or '')==str(pid):G['set_setting']('stream_selector_default_profile_id','')
        return RedirectResponse('/system/stream-selectors?msg=Profile+deleted',303)

    @app.get('/plex/path-replacements',response_class=HTMLResponse)
    def v129_path_index(msg:str=''):return _path_page(msg)
    @app.post('/plex/path-replacements/add')
    def v129_path_add(server_id:int=Form(...),remote_prefix:str=Form(...),local_prefix:str=Form(...),priority:int=Form(100)):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('INSERT INTO plex_path_replacements(server_id,remote_prefix,local_prefix,priority,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(server_id,remote_prefix.strip(),local_prefix.strip(),priority,1,_now(),_now()));conn.commit()
        _PLEX_INFO_CACHE.clear();return RedirectResponse('/plex/path-replacements?msg=Replacement+added',303)
    @app.post('/plex/path-replacements/{rid}/delete')
    def v129_path_delete(rid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM plex_path_replacements WHERE id=?',(rid,));conn.execute('UPDATE plex_media SET direct_local_path=NULL');conn.commit()
        _PLEX_INFO_CACHE.clear();return RedirectResponse('/plex/path-replacements?msg=Replacement+deleted',303)
    @app.post('/plex/path-replacements/test')
    def v129_path_test(server_id:int=Form(...),remote_path:str=Form(...)):
        x=_translate_plex_path(server_id,remote_path)
        msg=('Matched: '+x) if x else 'No enabled rule produced an existing file accessible to ViperTV.'
        return RedirectResponse('/plex/path-replacements?msg='+quote(msg),303)

    @app.post('/system/graphics/v129/add')
    def v129_graphic_add(name:str=Form(...),kind:str=Form('image'),image_path:str=Form(''),text_template:str=Form(''),location:str=Form('BottomRight'),horizontal_margin_percent:float=Form(3),vertical_margin_percent:float=Form(3),scale_width_percent:float=Form(12),opacity_percent:float=Form(90),font_size:int=Form(32),text_color:str=Form('white'),box_enabled:int=Form(0),start_seconds:float=Form(0),end_seconds:str=Form(''),z_index:int=Form(1),loop_asset:int=Form(0),subtitle_style:str=Form('')):
        try:_save_graphic(None,name=name,kind=kind,image_path=image_path,text_template=text_template,location=location,horizontal_margin_percent=horizontal_margin_percent,vertical_margin_percent=vertical_margin_percent,scale_width_percent=scale_width_percent,opacity_percent=opacity_percent,font_size=font_size,text_color=text_color,box_enabled=box_enabled,start_seconds=start_seconds,end_seconds=end_seconds,z_index=z_index,enabled=1,loop_asset=loop_asset,subtitle_style=subtitle_style)
        except sqlite3.IntegrityError:return RedirectResponse('/system/graphics?msg='+quote('A graphic with that name already exists.'),303)
        return RedirectResponse('/system/graphics?msg=Graphic+created',303)
    @app.post('/system/graphics/{gid}/v129-save')
    def v129_graphic_save(gid:int,name:str=Form(...),kind:str=Form('image'),image_path:str=Form(''),text_template:str=Form(''),location:str=Form('BottomRight'),horizontal_margin_percent:float=Form(3),vertical_margin_percent:float=Form(3),scale_width_percent:float=Form(12),opacity_percent:float=Form(90),font_size:int=Form(32),text_color:str=Form('white'),box_enabled:int=Form(0),start_seconds:float=Form(0),end_seconds:str=Form(''),z_index:int=Form(1),loop_asset:int=Form(0),subtitle_style:str=Form(''),enabled:int=Form(0)):
        try:_save_graphic(gid,name=name,kind=kind,image_path=image_path,text_template=text_template,location=location,horizontal_margin_percent=horizontal_margin_percent,vertical_margin_percent=vertical_margin_percent,scale_width_percent=scale_width_percent,opacity_percent=opacity_percent,font_size=font_size,text_color=text_color,box_enabled=box_enabled,start_seconds=start_seconds,end_seconds=end_seconds,z_index=z_index,enabled=enabled,loop_asset=loop_asset,subtitle_style=subtitle_style)
        except sqlite3.IntegrityError:return RedirectResponse(f'/system/graphics/{gid}/edit?msg='+quote('A graphic with that name already exists.'),303)
        return RedirectResponse(f'/system/graphics/{gid}/edit?msg=Graphic+saved',303)
