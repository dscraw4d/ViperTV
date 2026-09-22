from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import stream_graphics_paths as sgp
from . import advanced_scheduling as adv

G: dict[str, Any] = {}
_BASE_INIT = None
_BASE_LOCAL = None
_BASE_PLEX = None
_BASE_EXTERNAL = None
_BASE_SYNC_EXTERNAL = None


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


def _norm_remote_path(p: str) -> str:
    return str(p or '').replace('\\', '/').rstrip('/')


def init_v130_db() -> None:
    """Additive v1.3.0 schema. Never drops/replaces user configuration or media."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS external_path_replacements(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              server_id INTEGER NOT NULL REFERENCES media_servers(id) ON DELETE CASCADE,
              remote_prefix TEXT NOT NULL,
              local_prefix TEXT NOT NULL,
              priority INTEGER NOT NULL DEFAULT 100,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_external_path_replacements
              ON external_path_replacements(server_id,enabled,priority DESC,id);

            CREATE TABLE IF NOT EXISTS ffmpeg_profiles(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              description TEXT,
              hardware_profile TEXT NOT NULL DEFAULT 'inherit',
              video_codec TEXT NOT NULL DEFAULT 'h264',
              audio_codec TEXT NOT NULL DEFAULT 'aac',
              resolution TEXT NOT NULL DEFAULT 'inherit',
              video_bitrate TEXT NOT NULL DEFAULT 'inherit',
              audio_bitrate TEXT NOT NULL DEFAULT '192k',
              frame_rate TEXT,
              preset TEXT,
              pixel_format TEXT NOT NULL DEFAULT 'yuv420p',
              sample_rate INTEGER NOT NULL DEFAULT 48000,
              audio_channels INTEGER NOT NULL DEFAULT 2,
              maxrate TEXT,
              bufsize TEXT,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS channel_ffmpeg_profiles(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              profile_id INTEGER NOT NULL REFERENCES ffmpeg_profiles(id) ON DELETE CASCADE
            );
            """
        )
        G['add_column_if_missing'](conn, 'external_media', 'direct_local_path', 'TEXT')
        G['add_column_if_missing'](conn, 'external_media', 'direct_path_checked_at', 'TEXT')
        conn.commit()


def _translate_external_path(server_id: int, remote_path: str) -> str | None:
    rp = _norm_remote_path(remote_path)
    if not rp:
        return None
    with _db() as conn:
        rules = conn.execute(
            '''SELECT * FROM external_path_replacements
               WHERE server_id=? AND enabled=1
               ORDER BY priority DESC,LENGTH(remote_prefix) DESC,id''',
            (int(server_id),),
        ).fetchall()
    folded = rp.casefold()
    for r in rules:
        prefix = _norm_remote_path(str(r['remote_prefix']))
        if not prefix or not folded.startswith(prefix.casefold()):
            continue
        if len(rp) > len(prefix) and rp[len(prefix)] != '/':
            continue
        suffix = rp[len(prefix):].lstrip('/')
        local = str(r['local_prefix'] or '').rstrip('/\\')
        candidate = os.path.join(local, *[x for x in suffix.split('/') if x]) if suffix else local
        if Path(candidate).is_file():
            return candidate
    return None


def _server_for_external_item(item: dict[str, Any]):
    sid = item.get('server_id')
    if sid:
        with _db() as conn:
            row = conn.execute('SELECT * FROM media_servers WHERE id=?', (int(sid),)).fetchone()
        if row:
            return row
    lib = int(item.get('library_id') or item.get('external_library_id') or 0)
    if not lib:
        return None
    with _db() as conn:
        return conn.execute(
            '''SELECT ms.* FROM media_servers ms
               JOIN external_libraries el ON el.server_id=ms.id WHERE el.id=?''',
            (lib,),
        ).fetchone()


def _direct_external_path(item: dict[str, Any]) -> str | None:
    remote = str(item.get('path') or '')
    if not remote:
        return None
    server = _server_for_external_item(item)
    if not server:
        return None
    local = _translate_external_path(int(server['id']), remote)
    try:
        with _db() as conn:
            conn.execute(
                'UPDATE external_media SET direct_local_path=?,direct_path_checked_at=? WHERE library_id=? AND external_id=?',
                (local, _now(), int(item.get('library_id') or item.get('external_library_id') or 0), str(item.get('external_id') or '')),
            )
            conn.commit()
    except Exception:
        pass
    return local


def _refresh_external_direct_paths(server_id: int | None = None) -> tuple[int, int]:
    with _db() as conn:
        q = '''SELECT em.id,em.path,el.server_id FROM external_media em
               JOIN external_libraries el ON el.id=em.library_id'''
        args: list[Any] = []
        if server_id is not None:
            q += ' WHERE el.server_id=?'; args.append(int(server_id))
        rows = conn.execute(q, args).fetchall()
        matched = 0
        for r in rows:
            local = _translate_external_path(int(r['server_id']), str(r['path'] or ''))
            if local:
                matched += 1
            conn.execute('UPDATE external_media SET direct_local_path=?,direct_path_checked_at=? WHERE id=?', (local, _now(), int(r['id'])))
        conn.commit()
    return len(rows), matched


# -------------------------- Reusable FFmpeg profiles --------------------------


def _ffmpeg_profile_for_channel(channel_id: int):
    with _db() as conn:
        row = conn.execute(
            '''SELECT p.* FROM channel_ffmpeg_profiles cfp
               JOIN ffmpeg_profiles p ON p.id=cfp.profile_id
               WHERE cfp.channel_id=? AND p.enabled=1''',
            (int(channel_id),),
        ).fetchone()
        if row:
            return row
        gid = str(G['get_setting']('ffmpeg_default_profile_id', '') or '')
        if gid.isdigit():
            return conn.execute('SELECT * FROM ffmpeg_profiles WHERE id=? AND enabled=1', (int(gid),)).fetchone()
    return None


def _channel_proxy(channel: Any, profile: Any) -> dict[str, Any]:
    c = dict(channel)
    if not profile:
        return c
    resolution = str(profile['resolution'] or 'inherit').strip()
    bitrate = str(profile['video_bitrate'] or 'inherit').strip()
    fps = str(profile['frame_rate'] or '').strip()
    if resolution and resolution.casefold() != 'inherit':
        c['resolution'] = resolution
    if bitrate and bitrate.casefold() != 'inherit':
        c['video_bitrate'] = bitrate
    if fps and fps.casefold() != 'inherit':
        c['frame_rate'] = fps
    return c


def _profile_hw_override(profile: Any) -> str | None:
    if not profile:
        return None
    hw = str(profile['hardware_profile'] or 'inherit').strip().lower()
    if hw == 'inherit':
        return None
    return hw if hw in {'global','auto','software','vaapi','qsv','nvenc','direct'} else None


def _remove_pair(cmd: list[str], flag: str) -> None:
    while flag in cmd:
        i = cmd.index(flag)
        del cmd[i:i+2]


def _set_pair(cmd: list[str], flag: str, value: str, before_flag: str = '-dn') -> None:
    if flag in cmd:
        i = cmd.index(flag)
        if i + 1 < len(cmd):
            cmd[i+1] = str(value)
            return
    try:
        i = cmd.index(before_flag)
    except ValueError:
        i = max(0, len(cmd)-2)
    cmd[i:i] = [flag, str(value)]


def _apply_ffmpeg_profile_to_command(cmd: list[str], profile: Any, item: dict[str, Any]) -> list[str]:
    if not profile or not cmd or cmd[0] != 'ffmpeg':
        return cmd
    out = list(cmd)
    has_filters = '-filter_complex' in out or '-vf' in out
    video_mode = str(profile['video_codec'] or 'h264').strip().lower()
    audio_mode = str(profile['audio_codec'] or 'aac').strip().lower()
    actual_hw = str(item.get('_actual_stream_profile') or '').strip().lower()
    if actual_hw not in {'software','vaapi','qsv','nvenc','direct'}:
        actual_hw = 'software'

    # Video encoder. Stream copy is only valid when there are no graphics/subtitle filters.
    if video_mode == 'copy' and not has_filters:
        venc = 'copy'
    else:
        if video_mode == 'copy':
            video_mode = 'h264'
            item['_ffmpeg_profile_warning'] = 'Video copy requested but active filters require encoding; using H.264.'
        if video_mode == 'hevc':
            venc = {'nvenc':'hevc_nvenc','qsv':'hevc_qsv','vaapi':'hevc_vaapi'}.get(actual_hw, 'libx265')
        else:
            venc = {'nvenc':'h264_nvenc','qsv':'h264_qsv','vaapi':'h264_vaapi'}.get(actual_hw, 'libx264')
    _set_pair(out, '-c:v', venc)

    # Audio encoder.
    if audio_mode == 'copy':
        aenc = 'copy'
    elif audio_mode == 'ac3':
        aenc = 'ac3'
    else:
        aenc = 'aac'
    _set_pair(out, '-c:a', aenc)

    # Encoding-only settings. Remove options that are invalid during stream copy.
    if venc == 'copy':
        for f in ('-b:v','-maxrate','-bufsize','-pix_fmt','-preset'):
            _remove_pair(out, f)
    else:
        vb = str(profile['video_bitrate'] or '').strip()
        if vb and vb.casefold() != 'inherit':
            _set_pair(out, '-b:v', vb)
        maxrate = str(profile['maxrate'] or '').strip()
        bufsize = str(profile['bufsize'] or '').strip()
        if maxrate:
            _set_pair(out, '-maxrate', maxrate)
        if bufsize:
            _set_pair(out, '-bufsize', bufsize)
        pix = str(profile['pixel_format'] or '').strip()
        # VAAPI/QSV own their upload/format chain; forcing an output pix_fmt can be counterproductive.
        if pix and actual_hw not in {'vaapi','qsv'}:
            _set_pair(out, '-pix_fmt', pix)
        preset = str(profile['preset'] or '').strip()
        if preset and actual_hw != 'vaapi':
            _set_pair(out, '-preset', preset)

    if aenc == 'copy':
        for f in ('-b:a','-ar','-ac'):
            _remove_pair(out, f)
    else:
        ab = str(profile['audio_bitrate'] or '').strip()
        if ab and ab.casefold() != 'inherit':
            _set_pair(out, '-b:a', ab)
        sr = int(profile['sample_rate'] or 0)
        ch = int(profile['audio_channels'] or 0)
        if sr > 0:
            _set_pair(out, '-ar', str(sr))
        if ch > 0:
            _set_pair(out, '-ac', str(ch))
    item['_ffmpeg_profile_name'] = str(profile['name'])
    item['_ffmpeg_profile_id'] = int(profile['id'])
    return out


def _advanced_profiled(channel: Any, item: dict[str, Any], offset: float, input_args: list[str]) -> list[str]:
    profile = _ffmpeg_profile_for_channel(int(channel['id']))
    proxy = _channel_proxy(channel, profile)
    hw = _profile_hw_override(profile)
    if profile and str(profile['video_codec'] or '').lower() == 'copy':
        hw = 'direct'
    cmd = sgp._advanced_media_command_v129(proxy, item, offset, input_args, hw)
    return _apply_ffmpeg_profile_to_command(cmd, profile, item)


def _local_v130(channel: Any, item: dict[str, Any], offset: float, profile_override: str | None = None) -> list[str]:
    prof = _ffmpeg_profile_for_channel(int(channel['id']))
    if not prof:
        return _BASE_LOCAL(channel, item, offset, profile_override)
    kind = str(item.get('media_kind') or item.get('media_type') or '').lower()
    # Preserve the dedicated v1.2.4 image/song generators, then apply the named
    # output recipe to their FFmpeg command. Those sources are not ordinary video
    # inputs, so routing them through the generic advanced-video builder would
    # discard the still-image canvas / audio-only handling.
    if kind in {'image','song'}:
        proxy = _channel_proxy(channel, prof)
        hw = _profile_hw_override(prof)
        if str(prof['video_codec'] or '').lower() == 'copy':
            hw = 'software'  # generated video cannot be stream-copied
        cmd = _BASE_LOCAL(proxy, item, offset, hw)
        return _apply_ffmpeg_profile_to_command(cmd, prof, item)
    path = str(item.get('path') or channel['offline_media'] or '')
    if not path:
        return ['false']
    return _advanced_profiled(channel, item, offset, ['-i', path])


def _plex_v130(channel: Any, item: dict[str, Any], offset: float, url: str, headers: str, profile_override: str | None = None) -> list[str]:
    prof = _ffmpeg_profile_for_channel(int(channel['id']))
    if not prof:
        return _BASE_PLEX(channel, item, offset, url, headers, profile_override)
    try:
        info = sgp._plex_part_info(item)
        item['_v129_streams'] = [dict(x) for x in info.get('streams') or []]
        local = str(info.get('local_path') or '')
        if local and Path(local).is_file():
            clone = dict(item); clone['path'] = local; clone['_v129_streams'] = item['_v129_streams']; clone['_plex_direct_disk'] = True
            return _advanced_profiled(channel, clone, offset, ['-i', local])
    except Exception:
        pass
    return _advanced_profiled(channel, item, offset, ['-headers', headers, '-i', url])


def _external_v130(channel: Any, item: dict[str, Any], offset: float) -> list[str]:
    local = _direct_external_path(item)
    prof = _ffmpeg_profile_for_channel(int(channel['id']))
    if local and Path(local).is_file():
        clone = dict(item); clone['path'] = local; clone['_external_direct_disk'] = True
        if prof:
            return _advanced_profiled(channel, clone, offset, ['-i', local])
        return _BASE_LOCAL(channel, clone, offset, None)
    if prof:
        url = G['_external_stream_url'](item)
        return _advanced_profiled(channel, item, offset, ['-i', url])
    return _BASE_EXTERNAL(channel, item, offset)


# ------------------------------- UI -----------------------------------------


def _external_paths_page(msg: str = '') -> str:
    with _db() as conn:
        servers = conn.execute("SELECT * FROM media_servers WHERE kind IN ('jellyfin','emby') ORDER BY name").fetchall()
        rows = conn.execute(
            '''SELECT r.*,s.name server_name,s.kind FROM external_path_replacements r
               JOIN media_servers s ON s.id=r.server_id
               ORDER BY s.name,r.priority DESC,r.id'''
        ).fetchall()
        counts = conn.execute(
            '''SELECT el.server_id,COUNT(*) total,SUM(CASE WHEN em.direct_local_path IS NOT NULL AND em.direct_local_path<>'' THEN 1 ELSE 0 END) matched
               FROM external_media em JOIN external_libraries el ON el.id=em.library_id GROUP BY el.server_id'''
        ).fetchall()
    cmap = {int(r['server_id']):(int(r['total'] or 0),int(r['matched'] or 0)) for r in counts}
    opts = ''.join(f"<option value='{s['id']}'>{_e(str(s['kind']).title())} — {_e(s['name'])}</option>" for s in servers)
    trs = ''.join(
        f"<tr><td>{_e(str(r['kind']).title())} / {_e(r['server_name'])}</td><td><code>{_e(r['remote_prefix'])}</code></td><td><code>{_e(r['local_prefix'])}</code></td><td>{r['priority']}</td><td>{'Enabled' if r['enabled'] else 'Disabled'}</td><td><form method='post' action='/sources/path-replacements/{r['id']}/delete'><button class='danger'>Delete</button></form></td></tr>"
        for r in rows
    ) or "<tr><td colspan='6' class='empty'>No Jellyfin/Emby path replacements configured.</td></tr>"
    status = ''.join(f"<tr><td>{_e(str(s['kind']).title())} / {_e(s['name'])}</td><td>{cmap.get(int(s['id']),(0,0))[1]:,}</td><td>{cmap.get(int(s['id']),(0,0))[0]:,}</td><td><form method='post' action='/sources/path-replacements/refresh'><input type='hidden' name='server_id' value='{s['id']}'><button class='secondary'>Recheck paths</button></form></td></tr>" for s in servers) or "<tr><td colspan='4'>No Jellyfin/Emby servers configured.</td></tr>"
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Jellyfin / Emby Direct Media Paths',
        'Translate media-server filesystem paths into paths that already exist inside the ViperTV container. Metadata still comes from Jellyfin/Emby; playback reads the file directly when a mapping resolves.',
        "<a class='button secondary' href='/sources'>Back to Sources</a>",
    ) + f"""
<div class='grid'><div class='card'><h2>Add Path Replacement</h2><form method='post' action='/sources/path-replacements/add'><label>Server</label><select name='server_id'>{opts}</select><label>Media server path prefix</label><input name='remote_prefix' required placeholder='D:\\Media\\TV or /srv/media/tv'><label>ViperTV container path prefix</label><input name='local_prefix' required placeholder='/mnt/share2'><label>Priority</label><input type='number' name='priority' value='100'><button>Add Replacement</button></form></div>
<div class='card'><h2>Test Translation</h2><form method='post' action='/sources/path-replacements/test'><label>Server</label><select name='server_id'>{opts}</select><label>Path reported by Jellyfin/Emby</label><input name='remote_path' required placeholder='D:\\Media\\TV\\Show\\Episode.mkv'><button>Test Path</button></form><p class='muted small'>A rule is considered usable only when the translated file actually exists inside this ViperTV container. If it does not, playback automatically falls back to the Jellyfin/Emby HTTP stream.</p></div></div>
<div class='card'><h2>Configured Replacements</h2><div class='table-wrap'><table><thead><tr><th>Server</th><th>Remote Prefix</th><th>Container Prefix</th><th>Priority</th><th>Status</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>
<div class='card'><h2>Direct-path coverage</h2><div class='table-wrap'><table><thead><tr><th>Server</th><th>Mapped files</th><th>Indexed files</th><th></th></tr></thead><tbody>{status}</tbody></table></div></div>"""
    return _page('Direct Media Paths', body)


def _profile_summary(p: Any) -> str:
    bits = [str(p['hardware_profile']), str(p['video_codec']), str(p['audio_codec'])]
    if str(p['resolution']) != 'inherit': bits.append(str(p['resolution']))
    if str(p['video_bitrate']) != 'inherit': bits.append(str(p['video_bitrate']))
    if p['frame_rate']: bits.append(f"{p['frame_rate']} fps")
    return ' · '.join(bits)


def _ffmpeg_profiles_page(msg: str = '') -> str:
    with _db() as conn:
        profiles = conn.execute('SELECT * FROM ffmpeg_profiles ORDER BY name COLLATE NOCASE').fetchall()
        channels = conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
        assigned = {int(r['channel_id']):int(r['profile_id']) for r in conn.execute('SELECT * FROM channel_ffmpeg_profiles')}
    default_id = str(G['get_setting']('ffmpeg_default_profile_id', '') or '')
    trs = ''.join(f"<tr><td><b>{_e(p['name'])}</b></td><td>{_e(p['description'] or '')}</td><td>{_e(_profile_summary(p))}</td><td>{'Enabled' if p['enabled'] else 'Disabled'}</td><td><a class='button secondary' href='/system/ffmpeg-profiles/{p['id']}'>Edit</a></td></tr>" for p in profiles) or "<tr><td colspan='5'>No reusable profiles yet.</td></tr>"
    popts = "<option value=''>No global FFmpeg profile</option>" + ''.join(f"<option value='{p['id']}' {'selected' if default_id==str(p['id']) else ''}>{_e(p['name'])}</option>" for p in profiles if p['enabled'])
    arows=[]
    for c in channels:
        opts = "<option value=''>Use global / channel settings</option>" + ''.join(f"<option value='{p['id']}' {'selected' if assigned.get(int(c['id']))==int(p['id']) else ''}>{_e(p['name'])}</option>" for p in profiles if p['enabled'])
        arows.append(f"<tr><td>{_e(c['number'])} {_e(c['name'])}</td><td><form class='inline' method='post' action='/system/ffmpeg-profiles/assign'><input type='hidden' name='channel_id' value='{c['id']}'><select name='profile_id' style='width:300px'>{opts}</select><button>Save</button></form></td></tr>")
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('FFmpeg Profiles','Reusable complete transcoding recipes. A channel-specific assignment overrides the global FFmpeg profile; hardware availability and software fallback still come from Hardware Acceleration.',"<a class='button secondary' href='/system/hardware'>Hardware Acceleration</a>")+f"""
<div class='grid'><div class='card'><h2>Create Profile</h2><form method='post' action='/system/ffmpeg-profiles/add'><label>Name</label><input name='name' required placeholder='1080p H.264 8 Mbps'><label>Description</label><input name='description'><button>Create Profile</button></form></div><div class='card'><h2>Global Default</h2><form method='post' action='/system/ffmpeg-profiles/default'><label>Profile</label><select name='profile_id'>{popts}</select><button>Save Global Default</button></form><p class='muted small'>With no reusable FFmpeg profile assigned, ViperTV keeps using each channel's existing resolution, bitrate, FPS and hardware settings.</p></div></div>
<div class='card'><h2>Profiles</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Description</th><th>Recipe</th><th>Status</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>
<div class='card'><h2>Per-channel assignment</h2><div class='table-wrap'><table><thead><tr><th>Channel</th><th>FFmpeg Profile</th></tr></thead><tbody>{''.join(arows) or '<tr><td colspan=2>No channels.</td></tr>'}</tbody></table></div></div>"""
    return _page('FFmpeg Profiles',body)


def _select(current: str, values: list[tuple[str,str]]) -> str:
    return ''.join(f"<option value='{_e(v)}' {'selected' if str(current)==v else ''}>{_e(label)}</option>" for v,label in values)


def _ffmpeg_profile_edit(pid: int, msg: str = '') -> str:
    with _db() as conn:
        p=conn.execute('SELECT * FROM ffmpeg_profiles WHERE id=?',(pid,)).fetchone()
    if not p: raise HTTPException(404,'FFmpeg profile not found')
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Edit FFmpeg Profile',str(p['name']),"<a class='button secondary' href='/system/ffmpeg-profiles'>Back</a>")+f"""
<div class='card'><form method='post' action='/system/ffmpeg-profiles/{pid}/save'><div class='grid3'><div><label>Name</label><input name='name' value='{_e(p['name'])}' required><label>Description</label><input name='description' value='{_e(p['description'] or '')}'><label>Hardware / encoder path</label><select name='hardware_profile'>{_select(str(p['hardware_profile']),[('inherit','Inherit channel hardware'),('global','Use global hardware setting'),('auto','Auto detect'),('software','Software'),('vaapi','VAAPI'),('qsv','Intel QSV'),('nvenc','NVIDIA NVENC'),('direct','Direct / copy')])}</select><label>Video mode</label><select name='video_codec'>{_select(str(p['video_codec']),[('h264','H.264'),('hevc','HEVC / H.265'),('copy','Copy video when filters allow')])}</select><label>Audio mode</label><select name='audio_codec'>{_select(str(p['audio_codec']),[('aac','AAC'),('ac3','AC-3'),('copy','Copy audio')])}</select></div><div><label>Resolution</label><input name='resolution' value='{_e(p['resolution'])}' placeholder='inherit or 1920x1080'><label>Video bitrate</label><input name='video_bitrate' value='{_e(p['video_bitrate'])}' placeholder='inherit or 8000k'><label>Maximum bitrate (optional)</label><input name='maxrate' value='{_e(p['maxrate'] or '')}' placeholder='9000k'><label>Rate-control buffer (optional)</label><input name='bufsize' value='{_e(p['bufsize'] or '')}' placeholder='16000k'><label>Frame rate</label><input name='frame_rate' value='{_e(p['frame_rate'] or '')}' placeholder='blank = inherit'></div><div><label>Encoder preset (optional)</label><input name='preset' value='{_e(p['preset'] or '')}' placeholder='veryfast / p4 / medium'><label>Pixel format</label><input name='pixel_format' value='{_e(p['pixel_format'])}' placeholder='yuv420p'><label>Audio bitrate</label><input name='audio_bitrate' value='{_e(p['audio_bitrate'])}' placeholder='192k'><label>Sample rate</label><input type='number' name='sample_rate' value='{int(p['sample_rate'])}'><label>Audio channels</label><input type='number' min='1' max='8' name='audio_channels' value='{int(p['audio_channels'])}'><label><input type='checkbox' name='enabled' value='1' {'checked' if p['enabled'] else ''}> Enabled</label></div></div><button>Save Profile</button></form></div>
<div class='card'><h2>Behavior</h2><p>Graphics/subtitle filters still take priority over direct stream-copy. If a profile requests video copy while an active graphic or burned subtitle requires filtering, ViperTV safely encodes that programme instead. Hardware encoder availability continues to use the v1.2.5 fallback system.</p><form method='post' action='/system/ffmpeg-profiles/{pid}/delete' onsubmit="return confirm('Delete this FFmpeg profile?');"><button class='danger'>Delete Profile</button></form></div>"""
    return _page('Edit FFmpeg Profile',body)


def install_v130(app, main_globals: dict[str, Any]) -> None:
    global G,_BASE_INIT,_BASE_LOCAL,_BASE_PLEX,_BASE_EXTERNAL,_BASE_SYNC_EXTERNAL
    G=main_globals
    _BASE_INIT=G['init_v12_db']
    _BASE_LOCAL=G['_profiled_local_command']
    _BASE_PLEX=G['_profiled_plex_part_command']
    _BASE_EXTERNAL=G['_profiled_external_command']
    _BASE_SYNC_EXTERNAL=G['sync_external_library']

    def init_all():
        _BASE_INIT(); init_v130_db()
    G['init_v12_db']=init_all

    def sync_external_v130(library_id: int):
        n=_BASE_SYNC_EXTERNAL(library_id)
        try:
            with _db() as conn:
                s=conn.execute('SELECT server_id FROM external_libraries WHERE id=?',(library_id,)).fetchone()
            if s:_refresh_external_direct_paths(int(s['server_id']))
        except Exception:
            pass
        return n
    G['sync_external_library']=sync_external_v130

    G['_profiled_local_command']=_local_v130
    G['_profiled_plex_part_command']=_plex_v130
    G['_profiled_external_command']=_external_v130
    G['_translate_external_path']=_translate_external_path
    G['_ffmpeg_profile_for_channel']=_ffmpeg_profile_for_channel

    @app.get('/sources/path-replacements',response_class=HTMLResponse)
    def v130_external_paths(msg:str=''):return _external_paths_page(msg)

    @app.post('/sources/path-replacements/add')
    def v130_external_path_add(server_id:int=Form(...),remote_prefix:str=Form(...),local_prefix:str=Form(...),priority:int=Form(100)):
        G['safe_backup_before_change']()
        with _db() as conn:
            server=conn.execute("SELECT * FROM media_servers WHERE id=? AND kind IN ('jellyfin','emby')",(server_id,)).fetchone()
            if not server:raise HTTPException(404,'Jellyfin/Emby server not found')
            conn.execute('INSERT INTO external_path_replacements(server_id,remote_prefix,local_prefix,priority,enabled,created_at,updated_at) VALUES(?,?,?,?,1,?,?)',(server_id,remote_prefix.strip(),local_prefix.strip(),int(priority),_now(),_now()));conn.commit()
        total,matched=_refresh_external_direct_paths(server_id)
        return RedirectResponse('/sources/path-replacements?msg='+quote(f'Replacement added. {matched:,} of {total:,} indexed files currently map to local storage.'),303)

    @app.post('/sources/path-replacements/{rid}/delete')
    def v130_external_path_delete(rid:int):
        G['safe_backup_before_change']()
        sid=None
        with _db() as conn:
            row=conn.execute('SELECT server_id FROM external_path_replacements WHERE id=?',(rid,)).fetchone();sid=int(row['server_id']) if row else None
            conn.execute('DELETE FROM external_path_replacements WHERE id=?',(rid,));conn.commit()
        if sid is not None:_refresh_external_direct_paths(sid)
        return RedirectResponse('/sources/path-replacements?msg=Replacement+deleted',303)

    @app.post('/sources/path-replacements/test')
    def v130_external_path_test(server_id:int=Form(...),remote_path:str=Form(...)):
        x=_translate_external_path(server_id,remote_path)
        msg=('Matched existing container file: '+x) if x else 'No enabled rule produced an existing file inside the ViperTV container.'
        return RedirectResponse('/sources/path-replacements?msg='+quote(msg),303)

    @app.post('/sources/path-replacements/refresh')
    def v130_external_path_refresh(server_id:int=Form(...)):
        total,matched=_refresh_external_direct_paths(server_id)
        return RedirectResponse('/sources/path-replacements?msg='+quote(f'Rechecked {total:,} items; {matched:,} resolve to direct local files.'),303)

    @app.get('/system/ffmpeg-profiles',response_class=HTMLResponse)
    def v130_profiles(msg:str=''):return _ffmpeg_profiles_page(msg)

    @app.post('/system/ffmpeg-profiles/add')
    def v130_profile_add(name:str=Form(...),description:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('''INSERT INTO ffmpeg_profiles(name,description,hardware_profile,video_codec,audio_codec,resolution,video_bitrate,audio_bitrate,frame_rate,preset,pixel_format,sample_rate,audio_channels,maxrate,bufsize,enabled,created_at,updated_at)
                                    VALUES(?,?, 'inherit','h264','aac','inherit','inherit','192k',NULL,NULL,'yuv420p',48000,2,NULL,NULL,1,?,?)''',(name.strip(),description.strip() or None,_now(),_now()));conn.commit();pid=int(cur.lastrowid)
            return RedirectResponse(f'/system/ffmpeg-profiles/{pid}',303)
        except sqlite3.IntegrityError:
            return RedirectResponse('/system/ffmpeg-profiles?msg='+quote('That FFmpeg profile name already exists.'),303)

    @app.get('/system/ffmpeg-profiles/{pid}',response_class=HTMLResponse)
    def v130_profile_edit(pid:int,msg:str=''):return _ffmpeg_profile_edit(pid,msg)

    @app.post('/system/ffmpeg-profiles/{pid}/save')
    def v130_profile_save(pid:int,name:str=Form(...),description:str=Form(''),hardware_profile:str=Form('inherit'),video_codec:str=Form('h264'),audio_codec:str=Form('aac'),resolution:str=Form('inherit'),video_bitrate:str=Form('inherit'),audio_bitrate:str=Form('192k'),frame_rate:str=Form(''),preset:str=Form(''),pixel_format:str=Form('yuv420p'),sample_rate:int=Form(48000),audio_channels:int=Form(2),maxrate:str=Form(''),bufsize:str=Form(''),enabled:int=Form(0)):
        hardware_profile=hardware_profile if hardware_profile in {'inherit','global','auto','software','vaapi','qsv','nvenc','direct'} else 'inherit'
        video_codec=video_codec if video_codec in {'h264','hevc','copy'} else 'h264'
        audio_codec=audio_codec if audio_codec in {'aac','ac3','copy'} else 'aac'
        resolution=resolution.strip() or 'inherit';video_bitrate=video_bitrate.strip() or 'inherit';audio_bitrate=audio_bitrate.strip() or '192k'
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                conn.execute('''UPDATE ffmpeg_profiles SET name=?,description=?,hardware_profile=?,video_codec=?,audio_codec=?,resolution=?,video_bitrate=?,audio_bitrate=?,frame_rate=?,preset=?,pixel_format=?,sample_rate=?,audio_channels=?,maxrate=?,bufsize=?,enabled=?,updated_at=? WHERE id=?''',
                             (name.strip(),description.strip() or None,hardware_profile,video_codec,audio_codec,resolution,video_bitrate,audio_bitrate,frame_rate.strip() or None,preset.strip() or None,pixel_format.strip() or 'yuv420p',max(8000,int(sample_rate)),max(1,min(8,int(audio_channels))),maxrate.strip() or None,bufsize.strip() or None,1 if enabled else 0,_now(),pid));conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/system/ffmpeg-profiles/{pid}?msg='+quote('That profile name is already in use.'),303)
        # Restart assigned/global channels so the recipe becomes visible immediately.
        with _db() as conn:
            ids={int(r['channel_id']) for r in conn.execute('SELECT channel_id FROM channel_ffmpeg_profiles WHERE profile_id=?',(pid,))}
            if str(G['get_setting']('ffmpeg_default_profile_id','') or '')==str(pid):ids.update(int(r['id']) for r in conn.execute('SELECT id FROM channels'))
        for cid in ids:G['_restart_shared_channel_if_running'](cid)
        return RedirectResponse(f'/system/ffmpeg-profiles/{pid}?msg=Profile+saved',303)

    @app.post('/system/ffmpeg-profiles/{pid}/delete')
    def v130_profile_delete(pid:int):
        G['safe_backup_before_change']()
        with _db() as conn:
            ids=[int(r['channel_id']) for r in conn.execute('SELECT channel_id FROM channel_ffmpeg_profiles WHERE profile_id=?',(pid,))]
            conn.execute('DELETE FROM ffmpeg_profiles WHERE id=?',(pid,));conn.commit()
        if str(G['get_setting']('ffmpeg_default_profile_id','') or '')==str(pid):G['set_setting']('ffmpeg_default_profile_id','')
        for cid in ids:G['_restart_shared_channel_if_running'](cid)
        return RedirectResponse('/system/ffmpeg-profiles?msg=Profile+deleted',303)

    @app.post('/system/ffmpeg-profiles/default')
    def v130_profile_default(profile_id:str=Form('')):
        if profile_id and not profile_id.isdigit():profile_id=''
        G['set_setting']('ffmpeg_default_profile_id',profile_id)
        with _db() as conn:ids=[int(r['id']) for r in conn.execute('SELECT id FROM channels')]
        for cid in ids:G['_restart_shared_channel_if_running'](cid)
        return RedirectResponse('/system/ffmpeg-profiles?msg=Global+FFmpeg+profile+saved',303)

    @app.post('/system/ffmpeg-profiles/assign')
    def v130_profile_assign(channel_id:int=Form(...),profile_id:str=Form('')):
        G['safe_backup_before_change']()
        with _db() as conn:
            if profile_id.isdigit():
                p=conn.execute('SELECT id FROM ffmpeg_profiles WHERE id=?',(int(profile_id),)).fetchone()
                if not p:raise HTTPException(404,'FFmpeg profile not found')
                conn.execute('INSERT INTO channel_ffmpeg_profiles(channel_id,profile_id) VALUES(?,?) ON CONFLICT(channel_id) DO UPDATE SET profile_id=excluded.profile_id',(channel_id,int(profile_id)))
            else:
                conn.execute('DELETE FROM channel_ffmpeg_profiles WHERE channel_id=?',(channel_id,))
            conn.commit()
        G['_restart_shared_channel_if_running'](channel_id)
        return RedirectResponse('/system/ffmpeg-profiles?msg=Channel+FFmpeg+profile+saved',303)
