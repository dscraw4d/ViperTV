from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from fastapi import Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, StreamingResponse

G: dict[str, Any] = {}
STREAM_MODES = {
    'mpegts': 'MPEG-TS — Sanitized',
    'mpegts_legacy': 'MPEG-TS Legacy — Direct shared feed',
    'hls': 'HLS Segmenter — Compatibility',
    'hls_direct': 'HLS Direct — Low latency',
}


def _e(v: Any) -> str:
    return G['e'](v)


def _db():
    return G['db']()


def _mode_label(v: Any) -> str:
    return STREAM_MODES.get(str(v or 'mpegts').lower(), str(v or 'mpegts'))


def init_v126_db() -> None:
    # stream_mode already exists in the channels table. Keep this migration
    # deliberately additive: normalize legacy values and seed image duration.
    with _db() as conn:
        try:
            conn.execute("UPDATE channels SET stream_mode='mpegts' WHERE stream_mode IS NULL OR TRIM(stream_mode)='' OR stream_mode NOT IN ('mpegts','mpegts_legacy','hls','hls_direct')")
        except Exception:
            pass
        try:
            row=conn.execute("SELECT value FROM settings WHERE key='image_default_duration_seconds'").fetchone()
            if not row:
                conn.execute("INSERT INTO settings(key,value) VALUES('image_default_duration_seconds','10')")
        except Exception:
            pass
        conn.commit()


def _local_image_rows(limit: int | None = None):
    sql="""SELECT m.*,l.name library_name FROM media m JOIN libraries l ON l.id=m.library_id
           WHERE COALESCE(m.media_kind,'')='image' ORDER BY l.name COLLATE NOCASE,m.title COLLATE NOCASE,m.id"""
    if limit:
        sql += f' LIMIT {int(limit)}'
    with _db() as conn:
        return conn.execute(sql).fetchall()


def _image_token(row: Any) -> str:
    return G['encode_selection']({'source_type':'local','library_id':int(row['library_id']),'selection_type':'item','media_id':int(row['id'])})


def images_page(msg: str = '') -> str:
    rows=_local_image_rows()
    default=float(G['get_setting']('image_default_duration_seconds','10') or 10)
    notice=f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    trs=[]
    for r in rows:
        p=str(r['path'] or '')
        trs.append(
            f"<tr><td><b>{_e(r['title'])}</b><div class='muted small'>{_e(r['library_name'])}</div></td>"
            f"<td><code>{_e(p)}</code></td><td>{float(r['duration'] or default):g} sec</td>"
            f"<td><form class='inline' method='post' action='/media/images/{int(r['id'])}/duration'>"
            f"<input style='width:90px' type='number' step='0.5' min='1' max='86400' name='seconds' value='{float(r['duration'] or default):g}'>"
            f"<button>Save</button></form></td></tr>"
        )
    table=''.join(trs) or "<tr><td colspan='4' class='empty'>No local images are indexed. Add JPG, JPEG, PNG, WebP, BMP or GIF files to a Local library and scan it.</td></tr>"
    body=notice+G['_page_heading']('Images','Still images are first-class scheduled media. Each image becomes a normal timed programme with silent audio.')+f"""
<div class='grid'><div class='card'><h2>Default image duration</h2><form method='post' action='/media/images/default-duration'><label>Seconds</label><input type='number' step='0.5' min='1' max='86400' name='seconds' value='{default:g}'><label><input type='checkbox' name='apply_existing' value='1'> Apply this duration to all currently indexed local images</label><button>Save Default</button></form><p class='muted small'>Newly scanned images use this value. Individual images can override it below.</p></div>
<div class='card'><h2>Scheduling</h2><p>Images can be added directly to <b>Classic Schedules</b> and <b>Block Scheduling</b>, selected in mixed-media Playlists/Collections, or referenced in Sequential YAML with <code>image: "Title"</code>.</p><p class='muted small'>The image is scaled to fit the channel resolution with its aspect ratio preserved and letter/pillar boxing as required.</p></div></div>
<div class='card'><h2>Indexed Images <span class='badge blue'>{len(rows):,}</span></h2><div class='table-wrap'><table><thead><tr><th>Image</th><th>Path</th><th>Duration</th><th></th></tr></thead><tbody>{table}</tbody></table></div></div>"""
    return G['page_shell']('Images',body)


def _source_catalog_with_images(base):
    def wrapped():
        out=list(base())
        # Exact local images are intentionally first-class. Keep the catalog
        # bounded for very large photo libraries; all images remain available
        # through Playlists, Collections and Search.
        for r in _local_image_rows(1500):
            out.append({'kind':'image','ref':_image_token(r),'label':f"Image — Local / {r['library_name']} / {r['title']} ({float(r['duration'] or 10):g}s)"})
        return out
    return wrapped


def _source_label_with_images(base):
    def wrapped(kind: str, ref: str) -> str:
        if kind=='image':
            try:
                return 'Image — '+G['_selection_description'](ref)
            except Exception:
                return 'Image — missing source'
        return base(kind,ref)
    return wrapped


def _source_items_with_images(base):
    def wrapped(row):
        try:
            if str(row['source_kind'])=='image':
                return G['_selection_items'](str(row['source_ref']))
        except Exception:
            pass
        return base(row)
    return wrapped


def _stream_mode_for_channel(channel_id: int) -> str:
    with _db() as conn:
        row=conn.execute('SELECT stream_mode FROM channels WHERE id=?',(channel_id,)).fetchone()
    mode=str(row['stream_mode'] if row else 'mpegts').lower()
    return mode if mode in STREAM_MODES else 'mpegts'


def channel_stream_url(base: str, channel_number: str) -> str:
    with _db() as conn:
        row=conn.execute('SELECT stream_mode FROM channels WHERE number=?',(str(channel_number),)).fetchone()
    mode=str(row['stream_mode'] if row else 'mpegts').lower()
    ext='m3u8' if mode in {'hls','hls_direct'} else 'ts'
    return f"{base}/stream/channel/{G['quote'](str(channel_number),safe='')}.{ext}"


def _ts_response(channel_id: int):
    if not G['_retro_config_for_channel'](channel_id):
        _,items=G['channel_media'](channel_id)
        if not items:
            raise HTTPException(503,'Channel has no playable media.')
    mode=_stream_mode_for_channel(channel_id)
    gen=G['stream_channel'](channel_id) if mode=='mpegts_legacy' else G['_clean_client_ts_stream'](channel_id)
    return StreamingResponse(gen,media_type='video/mp2t',headers={'Cache-Control':'no-store','X-Accel-Buffering':'no','X-ViperTV-Stream-Mode':mode})


def _hls_profile(mode: str) -> tuple[float,int,int,str]:
    if mode=='hls_direct':
        return (1.0,10,30,'delete_segments+independent_segments+program_date_time+temp_file')
    return (4.0,12,36,'delete_segments+independent_segments+program_date_time+temp_file')


def _hls_command(channel: Any,item: dict[str,Any],offset: float,out_dir: Path) -> list[str]:
    mode=str(channel['stream_mode'] or 'hls').lower()
    seg,list_size,delete_threshold,flags=_hls_profile(mode)
    manifest=str(out_dir/'index.m3u8'); pattern=str(out_dir/'seg_%012d.ts')
    n=G['quote'](str(channel['number']),safe='')
    shared=f'http://127.0.0.1:8409/internal/stream/channel/{n}.ts'
    return ['ffmpeg','-hide_banner','-loglevel','warning','-fflags','+genpts+discardcorrupt+nobuffer','-flags','low_delay','-probesize',str(G['LIVE_PROBE_SIZE']),'-analyzeduration',str(G['LIVE_ANALYZE_US']),'-max_delay','0','-i',shared,'-map','0:v:0?','-map','0:a:0?','-sn','-dn','-c','copy','-avoid_negative_ts','make_zero','-f','hls','-hls_time',f'{seg:g}','-hls_list_size',str(list_size),'-hls_delete_threshold',str(delete_threshold),'-hls_start_number_source','epoch','-hls_flags',flags,'-hls_segment_filename',pattern,manifest]


def streaming_profiles_page() -> str:
    with _db() as conn:
        channels=conn.execute('SELECT * FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
    rows=[]
    for c in channels:
        eff,cfg,warn=G['effective_stream_profile'](c)
        url_kind='HLS (.m3u8)' if str(c['stream_mode']) in {'hls','hls_direct'} else 'MPEG-TS (.ts)'
        rows.append(f"<tr><td>{_e(c['number'])}</td><td><b>{_e(c['name'])}</b></td><td>{_e(_mode_label(c['stream_mode']))}</td><td>{_e(url_kind)}</td><td>{_e(G['hwaccel'].profile_label(cfg))}</td><td>{_e(G['hwaccel'].profile_label(eff))}</td><td>{_e(c['resolution'])}</td><td>{_e(c['video_bitrate'])}</td><td>{_e(warn)}</td><td><a class='button secondary' href='/studio/channel/{int(c['id'])}'>Configure</a></td></tr>")
    trs=''.join(rows) or "<tr><td colspan='10' class='empty'>No channels configured.</td></tr>"
    body=G['_page_heading']('Streaming Profiles','Choose a delivery mode independently for every generated channel.',"<a class='button secondary' href='/system/hardware'>Hardware Acceleration</a>")+f"""
<div class='grid'><div class='card'><h2>MPEG-TS modes</h2><p><b>Sanitized:</b> one small per-viewer copy/remux process gives clean PAT/PMT and timestamps. Recommended for Kodi/IPTV clients.</p><p><b>Legacy:</b> attaches directly to the shared station producer. Lowest overhead but clients may join mid-transport-stream.</p></div><div class='card'><h2>HLS modes</h2><p><b>Segmenter:</b> compatibility-oriented 4-second segments from the shared station feed.</p><p><b>Direct:</b> low-latency 1-second segments from the same shared station feed. Both are stream-copy/remux only and do not create another expensive source transcode.</p></div></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Delivery Mode</th><th>M3U URL Type</th><th>Configured Encoder</th><th>Effective Encoder</th><th>Resolution</th><th>Bitrate</th><th>Fallback</th><th></th></tr></thead><tbody>{trs}</tbody></table></div></div>"""
    return G['page_shell']('Streaming Profiles',body)


def install_v126(app,main_globals:dict[str,Any]) -> None:
    global G;G=main_globals
    # Additive startup migration.
    base_init=G['init_v12_db']
    def init_all():
        base_init();init_v126_db()
    G['init_v12_db']=init_all

    # First-class exact images in Classic/Block source catalogs.
    G['CLASSIC_SOURCE_KINDS'].add('image')
    G['_classic_source_catalog']=_source_catalog_with_images(G['_classic_source_catalog'])
    G['_classic_source_label']=_source_label_with_images(G['_classic_source_label'])
    G['_classic_source_items']=_source_items_with_images(G['_classic_source_items'])

    # Multiple delivery modes. Existing .ts routes resolve this function at
    # request time, and M3U generation resolves channel_stream_url at runtime.
    G['channel_stream_url']=channel_stream_url
    G['stream_response_for_channel']=_ts_response
    G['_browser_hls_command']=_hls_command
    G['streaming_profiles_page']=streaming_profiles_page

    @app.get('/media/images',response_class=HTMLResponse)
    def v126_images(msg:str=''):
        return images_page(msg)

    @app.post('/media/images/default-duration')
    def v126_image_default_duration(seconds:float=Form(10),apply_existing:int=Form(0)):
        seconds=max(1.0,min(86400.0,float(seconds)))
        G['safe_backup_before_change']();G['set_setting']('image_default_duration_seconds',f'{seconds:g}')
        if apply_existing:
            with _db() as conn:
                conn.execute("UPDATE media SET duration=? WHERE COALESCE(media_kind,'')='image'",(seconds,));conn.commit()
            try:G['_v124_mark_index_dirty']('Image durations changed')
            except Exception:pass
        return RedirectResponse('/media/images?msg='+G['quote'](f'Default image duration saved: {seconds:g} seconds.'),303)

    @app.post('/media/images/{media_id}/duration')
    def v126_image_duration(media_id:int,seconds:float=Form(...)):
        seconds=max(1.0,min(86400.0,float(seconds)));G['safe_backup_before_change']()
        with _db() as conn:
            row=conn.execute("SELECT id FROM media WHERE id=? AND COALESCE(media_kind,'')='image'",(media_id,)).fetchone()
            if not row:raise HTTPException(404,'Image not found')
            conn.execute('UPDATE media SET duration=?,updated_at=? WHERE id=?',(seconds,G['utcnow_iso'](),media_id));conn.commit()
        try:G['_classic_invalidate']()
        except Exception:pass
        try:G['_v124_mark_index_dirty']('Image duration changed')
        except Exception:pass
        return RedirectResponse('/media/images?msg='+G['quote'](f'Image duration set to {seconds:g} seconds.'),303)

    @app.api_route('/stream/channel/{channel_number}.m3u8',methods=['GET','HEAD'])
    async def v126_hls_manifest(channel_number:str,request:Request):
        channel_id=G['resolve_channel_number'](channel_number)
        if request.method=='HEAD':
            return PlainTextResponse('',media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store'})
        state=G['_start_browser_hls'](channel_id);state['last_access']=time.time();manifest=G['_browser_hls_dir'](channel_id)/'index.m3u8'
        deadline=time.time()+30.0
        while time.time()<deadline:
            if manifest.exists() and manifest.stat().st_size>60:
                try:
                    text=manifest.read_text(errors='ignore')
                    if '#EXTINF:' in text:
                        # Segment URIs in FFmpeg's manifest are relative. Rewrite
                        # them to this channel-scoped public route.
                        prefix=f"/stream/channel/{G['quote'](str(channel_number),safe='')}"
                        text='\n'.join((prefix+'/'+ln if re.fullmatch(r'seg_\d+\.ts',ln.strip()) else ln) for ln in text.splitlines())+'\n'
                        return PlainTextResponse(text,media_type='application/vnd.apple.mpegurl',headers={'Cache-Control':'no-store, no-cache, must-revalidate','X-Accel-Buffering':'no','X-ViperTV-Stream-Mode':_stream_mode_for_channel(channel_id)})
                except Exception:pass
            proc=state.get('proc')
            if proc is not None and proc.poll() is not None:
                raise HTTPException(503,'HLS segmenter stopped before producing a playlist')
            await asyncio.sleep(0.15)
        raise HTTPException(503,'HLS stream is still starting; retry shortly')

    @app.get('/stream/channel/{channel_number}/{segment_name}')
    def v126_hls_segment(channel_number:str,segment_name:str):
        channel_id=G['resolve_channel_number'](channel_number)
        if not re.fullmatch(r'seg_\d+\.ts',segment_name):raise HTTPException(404,'Segment not found')
        state=G['BROWSER_HLS_PROCESSES'].get(channel_id)
        if state:state['last_access']=time.time()
        path=G['_browser_hls_dir'](channel_id)/segment_name;deadline=time.time()+2.0
        while not path.exists() and time.time()<deadline:time.sleep(0.05)
        if not path.exists():raise HTTPException(404,'Segment expired or not ready')
        return FileResponse(path,media_type='video/mp2t',headers={'Cache-Control':'private, max-age=30'})
