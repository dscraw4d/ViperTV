from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

G: dict[str, Any] = {}
AUDIO_EXTS={'.mp3','.flac','.m4a','.aac','.ogg','.opus','.wav','.wma','.ape','.alac'}
IMAGE_EXTS={'.jpg','.jpeg','.png','.webp','.bmp','.gif'}


def _jload(value: Any) -> list[str]:
    if value in (None,''): return []
    if isinstance(value,list): return [str(x) for x in value if str(x).strip()]
    try:
        x=json.loads(str(value))
        if isinstance(x,list): return [str(v) for v in x if str(v).strip()]
    except Exception: pass
    return [x.strip() for x in str(value).split(',') if x.strip()]


def _jdump(values: list[str]) -> str:
    seen=[]
    for v in values:
        v=str(v or '').strip()
        if v and v.casefold() not in {x.casefold() for x in seen}: seen.append(v)
    return json.dumps(seen,ensure_ascii=False)


def _first_mapping(value: Any) -> dict[str,Any]:
    if isinstance(value,dict): return value
    if isinstance(value,list):
        for x in value:
            if isinstance(x,dict): return x
    return {}


def _tag_values(item: dict[str,Any], *keys: str) -> list[str]:
    out=[]
    for key in keys:
        raw=item.get(key)
        vals=raw if isinstance(raw,list) else [raw] if raw is not None else []
        for x in vals:
            if isinstance(x,dict): v=str(x.get('tag') or x.get('name') or x.get('title') or '').strip()
            else: v=str(x or '').strip()
            if v: out.append(v)
    return list(dict.fromkeys(out))


def _epoch_iso(value: Any) -> str | None:
    try:
        n=float(value)
        if n>0: return datetime.fromtimestamp(n,tz=timezone.utc).isoformat()
    except Exception: pass
    s=str(value or '').strip()
    return s or None


def _media_kind(library_name:str, show_title:str|None, path:str|None='', declared:str|None='') -> str:
    d=str(declared or '').casefold()
    if d in {'episode','movie','music_video','other_video','song','image','remote_stream'}: return d
    ext=Path(str(path or '')).suffix.casefold()
    if ext in IMAGE_EXTS:return 'image'
    if ext in AUDIO_EXTS:return 'song'
    folded=str(library_name or '').casefold()
    if 'music video' in folded:return 'music_video'
    if 'other video' in folded or 'youtube' in folded:return 'other_video'
    if show_title:return 'episode'
    return 'movie'


def _hdr_label(stream:dict[str,Any]) -> str:
    transfer=str(stream.get('color_transfer') or '').casefold()
    side=' '.join(str(x) for x in stream.get('side_data_list') or []).casefold()
    if 'dovi' in side or 'dolby vision' in side:return 'Dolby Vision'
    if transfer in {'smpte2084','smpte-st-2084'}:return 'HDR10/PQ'
    if transfer in {'arib-std-b67','hlg'}:return 'HLG'
    return 'SDR'


def probe_details(path:str) -> dict[str,Any]:
    try:
        cp=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',path],capture_output=True,text=True,timeout=45,check=False)
        if cp.returncode!=0:return {}
        data=json.loads(cp.stdout or '{}')
    except Exception:return {}
    streams=data.get('streams') or []; fmt=data.get('format') or {}; tags={str(k).casefold():v for k,v in (fmt.get('tags') or {}).items()}
    video=next((x for x in streams if x.get('codec_type')=='video'),{})
    audio=next((x for x in streams if x.get('codec_type')=='audio'),{})
    aud_lang=[]; sub_lang=[]
    for s in streams:
        lang=str((s.get('tags') or {}).get('language') or '').strip()
        if not lang:continue
        if s.get('codec_type')=='audio':aud_lang.append(lang)
        if s.get('codec_type')=='subtitle':sub_lang.append(lang)
    bits=G['safe_int'](video.get('bits_per_raw_sample') or video.get('bits_per_sample'))
    if not bits:
        m=re.search(r'(?:p|yuv\w*?)(10|12|16)(?:le|be)?$',str(video.get('pix_fmt') or ''),re.I)
        bits=int(m.group(1)) if m else None
    width=G['safe_int'](video.get('width'));height=G['safe_int'](video.get('height'))
    genres=[]
    for k in ('genre','genres','style','mood'):
        if tags.get(k):genres += re.split(r'\s*[;,/]\s*',str(tags[k]))
    writer=str(tags.get('writer') or tags.get('composer') or '').strip()
    chapter_starts=[]
    for ch in data.get('chapters') or []:
        try:
            start=float(ch.get('start_time') if ch.get('start_time') is not None else ch.get('start') or 0)
            if start>=0: chapter_starts.append(start)
        except Exception:
            pass
    return {
        'duration':G['safe_float'](fmt.get('duration')),
        'writers_json':_jdump([writer] if writer else []),
        'content_rating':str(tags.get('content_rating') or tags.get('rating') or '').strip() or None,
        'audio_languages_json':_jdump(aud_lang),'subtitle_languages_json':_jdump(sub_lang),'tags_json':_jdump(genres),
        'chapter_count':len(data.get('chapters') or []),'chapters_json':_jdump(chapter_starts),'video_width':width,'video_height':height,
        'video_resolution':f'{width}x{height}' if width and height else None,'video_codec':video.get('codec_name'),
        'audio_codec':audio.get('codec_name'),'bit_depth':bits,'dynamic_range':_hdr_label(video) if video else None,
        'artist':str(tags.get('artist') or tags.get('album_artist') or '').strip() or None,
        'album':str(tags.get('album') or '').strip() or None,
        'added_at':str(tags.get('date') or '').strip() or None,
    }


def _plex_fields(item:dict[str,Any], library_name:str='') -> dict[str,Any]:
    media=_first_mapping(item.get('Media')); part=_first_mapping(media.get('Part')); streams=part.get('Stream') if isinstance(part,dict) else []
    if isinstance(streams,dict):streams=[streams]
    if not isinstance(streams,list):streams=[]
    aud=[];subs=[]
    for s in streams:
        if not isinstance(s,dict):continue
        lang=str(s.get('languageCode') or s.get('language') or '').strip()
        if G['safe_int'](s.get('streamType'))==2 and lang:aud.append(lang)
        if G['safe_int'](s.get('streamType'))==3 and lang:subs.append(lang)
    width=G['safe_int'](media.get('width'));height=G['safe_int'](media.get('height'))
    writers=_tag_values(item,'Writer','writer','writers')
    tags=_tag_values(item,'Genre','Label','Collection','Mood','Style','Tag')
    mtype=str(item.get('type') or '')
    declared='song' if mtype in {'track','song'} else 'image' if mtype in {'photo','image'} else None
    artist=(str(item.get('grandparentTitle') or '').strip() if mtype in {'track','song'} else '') or (_tag_values(item,'Artist') or [None])[0]
    album=str(item.get('parentTitle') or '').strip() if mtype in {'track','song'} else None
    chapters=item.get('Chapter') or []
    if isinstance(chapters,dict): chapters=[chapters]
    chapter_starts=[]
    if isinstance(chapters,list):
        for ch in chapters:
            if not isinstance(ch,dict): continue
            try:
                # Plex chapter offsets are milliseconds.
                v=float(ch.get('startTimeOffset') if ch.get('startTimeOffset') is not None else ch.get('start') or 0)/1000.0
                if v>=0: chapter_starts.append(v)
            except Exception: pass
    return {'writers_json':_jdump(writers),'content_rating':str(item.get('contentRating') or '').strip() or None,
            'audio_languages_json':_jdump(aud),'subtitle_languages_json':_jdump(subs),'tags_json':_jdump(tags),
            'added_at':_epoch_iso(item.get('addedAt')),'chapter_count':len(chapter_starts),'chapters_json':_jdump(chapter_starts),
            'video_width':width,'video_height':height,'video_resolution':str(media.get('videoResolution') or (f'{width}x{height}' if width and height else '')).strip() or None,
            'video_codec':media.get('videoCodec'),'audio_codec':media.get('audioCodec'),'bit_depth':G['safe_int'](media.get('bitDepth')),
            'dynamic_range':str(media.get('videoDynamicRange') or media.get('videoDynamicRangeType') or '').strip() or None,
            'artist':artist,'album':album,'declared_kind':declared}


def init_media_power_db() -> None:
    with G['db']() as conn:
        for table in ('media','plex_media','external_media'):
            for col,ddl in [
                ('writers_json',"TEXT NOT NULL DEFAULT '[]'"),('content_rating','TEXT'),('audio_languages_json',"TEXT NOT NULL DEFAULT '[]'"),
                ('subtitle_languages_json',"TEXT NOT NULL DEFAULT '[]'"),('tags_json',"TEXT NOT NULL DEFAULT '[]'"),('added_at','TEXT'),('chapter_count','INTEGER NOT NULL DEFAULT 0'),('chapters_json',"TEXT NOT NULL DEFAULT '[]'"),
                ('video_width','INTEGER'),('video_height','INTEGER'),('video_resolution','TEXT'),('video_codec','TEXT'),('audio_codec','TEXT'),('bit_depth','INTEGER'),
                ('dynamic_range','TEXT'),('artist','TEXT'),('album','TEXT'),('media_kind','TEXT'),('tech_meta_at','TEXT'),('tech_meta_plex_updated_at','INTEGER')]:
                G['add_column_if_missing'](conn,table,col,ddl)
        for col,ddl in [('play_all','INTEGER NOT NULL DEFAULT 1'),('show_in_epg','INTEGER NOT NULL DEFAULT 1')]:
            G['add_column_if_missing'](conn,'playlist_items',col,ddl)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_media_kind ON media(media_kind)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_plex_media_kind ON plex_media(media_kind)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_external_media_kind ON external_media(media_kind)')
        conn.commit()


def _update_meta(conn,table:str,id_col:str,id_val:Any,fields:dict[str,Any],kind:str|None=None) -> None:
    vals={k:v for k,v in fields.items() if k!='duration'}
    if kind:vals['media_kind']=kind
    vals['tech_meta_at']=G['utcnow_iso']()
    cols=list(vals); conn.execute(f"UPDATE {table} SET "+','.join(f'{c}=?' for c in cols)+f' WHERE {id_col}=?',[vals[c] for c in cols]+[id_val])


def enrich_local_search_metadata(library_id:int) -> dict[str,int]:
    with G['db']() as conn:
        lib=conn.execute('SELECT * FROM libraries WHERE id=?',(library_id,)).fetchone()
        if not lib:return {'checked':0}
        rows=conn.execute('SELECT * FROM media WHERE library_id=? ORDER BY id',(library_id,)).fetchall()
    checked=0
    with G['db']() as conn:
        for row in rows:
            path=str(row['path']); p=Path(path); kind=_media_kind(str(lib['name']),row['show_title'] if 'show_title' in row.keys() else None,path,row['media_kind'] if 'media_kind' in row.keys() else None)
            if not row['tech_meta_at'] or not row['media_kind']:
                fields=probe_details(path) if p.exists() else {}
                if not fields:fields={}
                # NFO fields complement ffprobe container tags.
                nfo=p.with_suffix('.nfo')
                if nfo.exists():
                    try:
                        root=G['ElementTree'].parse(nfo).getroot()
                        writers=[]
                        for w in root.findall('.//writer')+root.findall('.//credits'):
                            txt=(w.text or '').strip()
                            if txt:writers += [x.strip() for x in re.split(r'\s*[|,;/]\s*',txt) if x.strip()]
                        if writers:fields['writers_json']=_jdump(writers)
                        rating=G['_xml_text'](root,'mpaa','certification','contentrating')
                        if rating:fields['content_rating']=rating
                        tags=[]
                        for tagname in ('genre','tag'):
                            for el in root.findall('.//'+tagname):
                                if el.text and el.text.strip():tags.append(el.text.strip())
                        if tags:fields['tags_json']=_jdump(tags)
                        date_added=G['_xml_text'](root,'dateadded','aired','premiered')
                        if date_added:fields['added_at']=date_added
                    except Exception:pass
                if not fields.get('added_at'):fields['added_at']=row['updated_at'] if 'updated_at' in row.keys() else None
                _update_meta(conn,'media','id',row['id'],fields,kind)
                checked+=1
            elif row['media_kind']!=kind:
                conn.execute('UPDATE media SET media_kind=? WHERE id=?',(kind,row['id']))
        conn.commit()
    return {'checked':checked}


def _index_local_nonvideo(library_id:int) -> int:
    with G['db']() as conn:
        lib=conn.execute('SELECT * FROM libraries WHERE id=?',(library_id,)).fetchone()
        if not lib:return 0
    root=Path(str(lib['path']));count=0
    if not root.exists():return 0
    with G['db']() as conn:
        for dirpath,_,files in os.walk(root):
            for name in files:
                p=Path(dirpath)/name; ext=p.suffix.casefold()
                if ext not in AUDIO_EXTS|IMAGE_EXTS:continue
                try:st=p.stat()
                except OSError:continue
                existing=conn.execute('SELECT * FROM media WHERE path=?',(str(p),)).fetchone()
                if existing and existing['size']==st.st_size and abs(existing['mtime']-st.st_mtime)<0.01 and existing['media_kind'] in ('song','image') and float(existing['duration'] or 0)>0:continue
                details=probe_details(str(p)) if ext in AUDIO_EXTS else {}
                duration=max(1.0,float(details.get('duration') or (float(G['get_setting']('image_default_duration_seconds','10') or 10) if ext in IMAGE_EXTS else 0)))
                kind='image' if ext in IMAGE_EXTS else 'song'
                title=G['clean_title'](p.stem)
                now=G['utcnow_iso']()
                conn.execute('''INSERT INTO media(library_id,path,title,duration,size,mtime,updated_at,media_kind,tech_meta_at,artist,album,video_width,video_height,video_resolution,video_codec,audio_codec,bit_depth,dynamic_range,audio_languages_json,subtitle_languages_json,tags_json,writers_json,added_at,chapter_count)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(path) DO UPDATE SET library_id=excluded.library_id,title=excluded.title,duration=excluded.duration,size=excluded.size,mtime=excluded.mtime,updated_at=excluded.updated_at,media_kind=excluded.media_kind,tech_meta_at=excluded.tech_meta_at,artist=excluded.artist,album=excluded.album,audio_codec=excluded.audio_codec,audio_languages_json=excluded.audio_languages_json,tags_json=excluded.tags_json,added_at=COALESCE(media.added_at,excluded.added_at),chapter_count=excluded.chapter_count,show_title=NULL,season_number=NULL,episode_number=NULL,episode_title=NULL''',
                  (library_id,str(p),title,duration,st.st_size,st.st_mtime,now,kind,now,details.get('artist'),details.get('album'),details.get('video_width'),details.get('video_height'),details.get('video_resolution'),details.get('video_codec'),details.get('audio_codec'),details.get('bit_depth'),details.get('dynamic_range'),details.get('audio_languages_json','[]'),details.get('subtitle_languages_json','[]'),details.get('tags_json','[]'),details.get('writers_json','[]'),details.get('added_at') or now,details.get('chapter_count',0)))
                count+=1
        conn.commit()
    return count


def enrich_plex_search_metadata(library_id:int,force:bool=False) -> dict[str,int]:
    with G['db']() as conn:
        lib=conn.execute('''SELECT pl.*,ps.base_url,ps.token,ps.name server_name FROM plex_libraries pl JOIN plex_servers ps ON ps.id=pl.server_id WHERE pl.id=?''',(library_id,)).fetchone()
        if not lib:return {'checked':0}
        q='SELECT rating_key,plex_updated_at,tech_meta_at,tech_meta_plex_updated_at FROM plex_media WHERE plex_library_id=?'
        rows=conn.execute(q,(library_id,)).fetchall()
    todo=[r for r in rows if force or not r['tech_meta_at'] or G['safe_int'](r['tech_meta_plex_updated_at'])!=G['safe_int'](r['plex_updated_at'])]
    checked=0
    for pos in range(0,len(todo),max(10,int(G.get('PLEX_RICH_EPISODE_BATCH_SIZE',40)))):
        batch=todo[pos:pos+max(10,int(G.get('PLEX_RICH_EPISODE_BATCH_SIZE',40)))]
        details=G['_plex_full_metadata_items'](lib,[str(r['rating_key']) for r in batch])
        with G['db']() as conn:
            for r in batch:
                item=details.get(str(r['rating_key']))
                if not item:continue
                f=_plex_fields(item,str(lib['title']))
                row=conn.execute('SELECT id,show_title,media_type FROM plex_media WHERE plex_library_id=? AND rating_key=?',(library_id,str(r['rating_key']))).fetchone()
                kind=_media_kind(str(lib['title']),row['show_title'] if row else None,'',f.pop('declared_kind',None) or (row['media_type'] if row else None))
                f['tech_meta_plex_updated_at']=G['safe_int'](r['plex_updated_at'])
                _update_meta(conn,'plex_media','id',row['id'],f,kind)
                checked+=1
            conn.commit()
    return {'checked':checked}


def enrich_external_search_metadata(library_id:int) -> dict[str,int]:
    with G['db']() as conn:
        lib=conn.execute('SELECT el.*,ms.kind,ms.base_url,ms.api_key FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id WHERE el.id=?',(library_id,)).fetchone()
    if not lib:return {'checked':0}
    fields='Path,Overview,PremiereDate,DateCreated,ProductionYear,RunTimeTicks,SeriesName,ParentIndexNumber,IndexNumber,Genres,Tags,OfficialRating,Studios,MediaStreams,MediaSources,Chapters,Artists,Album,AlbumArtist'
    try:data=G['_server_json'](lib,'/Items',{'ParentId':lib['external_id'],'Recursive':'true','IncludeItemTypes':'Episode,Movie,Audio,MusicVideo,Video,Photo','Fields':fields,'Limit':'100000'})
    except Exception:return {'checked':0}
    items=data.get('Items',data if isinstance(data,list) else []);checked=0
    with G['db']() as conn:
        for x in items:
            eid=str(x.get('Id') or ''); row=conn.execute('SELECT * FROM external_media WHERE library_id=? AND external_id=?',(library_id,eid)).fetchone()
            if not eid:continue
            if not row:
                dur=float(x.get('RunTimeTicks') or 0)/10_000_000
                mtype=str(x.get('Type') or '').casefold()
                if mtype in {'photo','image'}:dur=max(1.0,float(G['get_setting']('image_default_duration_seconds','10') or 10))
                conn.execute('''INSERT OR REPLACE INTO external_media(library_id,external_id,title,media_type,path,show_title,season_number,episode_number,duration,summary,year,thumb,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',(library_id,eid,x.get('Name') or 'Untitled',mtype,x.get('Path'),x.get('SeriesName'),G['safe_int'](x.get('ParentIndexNumber')),G['safe_int'](x.get('IndexNumber')),dur,x.get('Overview'),G['safe_int'](x.get('ProductionYear')),None,G['utcnow_iso']()))
                row=conn.execute('SELECT * FROM external_media WHERE library_id=? AND external_id=?',(library_id,eid)).fetchone()
            streams=x.get('MediaStreams') or [];aud=[];subs=[];video={};audio={}
            for s in streams:
                typ=str(s.get('Type') or '').casefold();lang=str(s.get('Language') or s.get('LanguageCode') or '').strip()
                if typ=='audio':audio=audio or s; aud += [lang] if lang else []
                elif typ=='subtitle':subs += [lang] if lang else []
                elif typ=='video':video=video or s
            width=G['safe_int'](video.get('Width'));height=G['safe_int'](video.get('Height'));bits=G['safe_int'](video.get('BitDepth'))
            mtype=str(x.get('Type') or '').casefold();declared='song' if mtype=='audio' else 'image' if mtype in {'photo','image'} else 'music_video' if mtype=='musicvideo' else None
            kind=_media_kind(str(lib['name']),x.get('SeriesName'),x.get('Path'),declared or row['media_type'])
            chapter_starts=[]
            for ch in x.get('Chapters') or []:
                if not isinstance(ch,dict): continue
                try:
                    v=float(ch.get('StartPositionTicks') or ch.get('StartPosition') or 0)/10_000_000.0
                    if v>=0: chapter_starts.append(v)
                except Exception: pass
            f={'writers_json':_jdump([str(v) for v in x.get('Writers') or []]),'content_rating':x.get('OfficialRating'),'audio_languages_json':_jdump(aud),'subtitle_languages_json':_jdump(subs),'tags_json':_jdump(list(x.get('Genres') or [])+list(x.get('Tags') or [])),'added_at':x.get('DateCreated'),'chapter_count':len(chapter_starts),'chapters_json':_jdump(chapter_starts),'video_width':width,'video_height':height,'video_resolution':f'{width}x{height}' if width and height else None,'video_codec':video.get('Codec'),'audio_codec':audio.get('Codec'),'bit_depth':bits,'dynamic_range':video.get('VideoRangeType') or video.get('VideoRange'),'artist':(x.get('AlbumArtist') or ((x.get('Artists') or [None])[0])),'album':x.get('Album')}
            _update_meta(conn,'external_media','id',row['id'],f,kind);checked+=1
        conn.commit()
    return {'checked':checked}


def _wrap_scan_library(base):
    def scan(library_id:int):
        result=base(library_id)
        try: result['nonvideo_indexed']=_index_local_nonvideo(library_id); result['technical_metadata']=enrich_local_search_metadata(library_id)['checked']
        except Exception as exc: result['technical_metadata_error']=str(exc)[:400]
        return result
    return scan


def _wrap_sync_plex(base):
    def sync(library_id:int):
        result=base(library_id)
        try:result['search_metadata']=enrich_plex_search_metadata(library_id)['checked']
        except Exception as exc:result['search_metadata_error']=str(exc)[:400]
        return result
    return sync


def _wrap_sync_external(base):
    def sync(library_id:int):
        n=base(library_id)
        try:enrich_external_search_metadata(library_id)
        except Exception:pass
        return n
    return sync


def _decorate_search_item(x:dict[str,Any]) -> dict[str,Any]:
    for src,dst in [('writers_json','writers'),('audio_languages_json','audio_languages'),('subtitle_languages_json','subtitle_languages'),('tags_json','tags')]:x[dst]=_jload(x.get(src))
    if not x.get('media_kind'):x['media_kind']=_media_kind(str(x.get('library_name') or ''),x.get('show_title'),x.get('path'),x.get('media_type'))
    return x


def collection_search_items() -> list[dict[str,Any]]:
    # Reuse mature people/network merging from v1.2, then append live streams and normalize new fields.
    items=G['_media_power_base_collection_search_items']()
    out=[_decorate_search_item(dict(x)) for x in items]
    with G['db']() as conn:
        try:live=conn.execute('SELECT * FROM live_streams WHERE enabled=1 ORDER BY number,name').fetchall()
        except sqlite3.Error:live=[]
    for r in live:
        d=dict(r);d.update({'source_type':'live','uid':f"live:{r['id']}",'media_type':'remote_stream','media_kind':'remote_stream','title':r['name'],'duration':3600.0,'library_name':'Live IPTV','source_url':r['stream_url'],'writers':[],'audio_languages':[],'subtitle_languages':[],'tags':[str(r['group_name'])] if r['group_name'] else [],'search_year':None,'release_date':'','artist':None,'album':None,'added_at':None,'chapter_count':0})
        out.append(d)
    return out


# -------- v1.2.2 Smart Search -----------------------------------------------
_SMART_LANGUAGE_ALIASES={
    'english':{'en','eng','english'},'spanish':{'es','spa','esp','spanish'},
    'french':{'fr','fra','fre','french'},'german':{'de','deu','ger','german'},
    'italian':{'it','ita','italian'},'portuguese':{'pt','por','portuguese'},
    'japanese':{'ja','jpn','japanese'},'korean':{'ko','kor','korean'},
    'chinese':{'zh','zho','chi','chinese'},'dutch':{'nl','nld','dut','dutch'},
    'russian':{'ru','rus','russian'},'arabic':{'ar','ara','arabic'},
}
_SMART_TYPE_ALIASES={
    'movie':{'movie'},'movies':{'movie'},'film':{'movie'},'films':{'movie'},
    'episode':{'episode'},'episodes':{'episode'},'tv':{'episode'},
    'song':{'song'},'songs':{'song'},'audio':{'song','music_video'},
    'image':{'image'},'images':{'image'},'photo':{'image'},'photos':{'image'},
    'musicvideo':{'music_video'},'musicvideos':{'music_video'},
    'stream':{'remote_stream'},'streams':{'remote_stream'},
}


def _smart_norm(value:Any)->str:
    return re.sub(r'[^a-z0-9]+',' ',str(value or '').casefold()).strip()


def _smart_compact(value:Any)->str:
    return re.sub(r'[^a-z0-9]+','',str(value or '').casefold())


def _smart_text_match(candidate:Any,wanted:str)->bool:
    c=_smart_norm(candidate);w=_smart_norm(wanted)
    if w and w in c:return True
    cc=_smart_compact(candidate);ww=_smart_compact(wanted)
    return bool(ww) and ww in cc


def _smart_values(item:dict[str,Any],keys:tuple[str,...])->list[str]:
    out=[]
    for key in keys:
        raw=item.get(key)
        vals=raw if isinstance(raw,(list,tuple,set)) else [raw]
        for v in vals:
            if v not in (None,''):out.append(str(v))
    return out


def _smart_years(item:dict[str,Any])->set[int]:
    out=set()
    for key in ('search_year','show_year','year'):
        y=G['safe_int'](item.get(key))
        if y and 1800<=y<=2200:out.add(y)
    for key in ('release_date','air_date','added_at'):
        m=re.match(r'^(\d{4})',str(item.get(key) or ''))
        if m:out.add(int(m.group(1)))
    return out


def _smart_language_match(item:dict[str,Any],token:str)->bool:
    wanted=_SMART_LANGUAGE_ALIASES.get(_smart_norm(token))
    if not wanted:return False
    langs=[_smart_norm(x) for x in _smart_values(item,('audio_languages','subtitle_languages'))]
    return any(x in wanted for x in langs)


def _smart_token_match(item:dict[str,Any],token:str)->bool:
    raw=str(token or '').strip().strip('"')
    if not raw:return True
    n=_smart_norm(raw);compact=_smart_compact(raw)
    years=_smart_years(item)
    if re.fullmatch(r'(?:18|19|20|21)\d{2}',n):
        return int(n) in years or _smart_text_match(item.get('title'),raw) or _smart_text_match(item.get('show_title'),raw)
    m=re.fullmatch(r'((?:18|19|20|21)\d{2})\s*-\s*((?:18|19|20|21)\d{2})',raw)
    if m:
        lo,hi=map(int,m.groups());return any(lo<=y<=hi for y in years)
    m=re.fullmatch(r'((?:18|19|20|21)\d)0s',compact)
    if m:
        lo=int(m.group(1))*10;return any(lo<=y<=lo+9 for y in years)
    m=re.fullmatch(r'(\d{2})s',compact)
    if m:
        yy=int(m.group(1));lo=(1900+yy if yy>=30 else 2000+yy);return any(lo<=y<=lo+9 for y in years)
    kind=str(item.get('media_kind') or item.get('media_type') or '').casefold()
    aliases=_SMART_TYPE_ALIASES.get(compact)
    if aliases and kind in aliases:return True
    width=G['safe_int'](item.get('video_width'));height=G['safe_int'](item.get('video_height'))
    if compact in {'4k','uhd','2160p'} and ((width and width>=3500) or (height and height>=2000) or _smart_text_match(item.get('video_resolution'),'2160')):return True
    if compact in {'1080','1080p','fullhd','fhd'} and ((height and 1000<=height<1400) or _smart_text_match(item.get('video_resolution'),'1080')):return True
    if compact in {'720','720p','hd'} and ((height and 700<=height<1000) or _smart_text_match(item.get('video_resolution'),'720')):return True
    dr=str(item.get('dynamic_range') or '')
    if compact=='hdr' and dr and _smart_norm(dr)!='sdr':return True
    if compact=='sdr' and (not dr or _smart_norm(dr)=='sdr'):return True
    m=re.fullmatch(r'(8|10|12|16)(?:bit)?',compact)
    if m and G['safe_int'](item.get('bit_depth'))==int(m.group(1)):return True
    codec_alias={'h264':{'h264','avc','avc1'},'x264':{'h264','avc','avc1'},'h265':{'hevc','h265'},'x265':{'hevc','h265'},'hevc':{'hevc','h265'},'av1':{'av1'}}.get(compact)
    if codec_alias and _smart_compact(item.get('video_codec')) in {_smart_compact(x) for x in codec_alias}:return True
    if _smart_language_match(item,raw):return True
    if compact=='audio' and (item.get('audio_codec') or item.get('audio_languages')):return True
    if compact in {'subtitle','subtitles','subs'} and item.get('subtitle_languages'):return True
    keys=('title','episode_title','show_title','summary','network','original_network','library_name','source_type','content_rating',
          'artist','album','video_resolution','video_codec','audio_codec','dynamic_range','media_kind','media_type')
    if any(_smart_text_match(v,raw) for v in _smart_values(item,keys)):return True
    list_keys=('actors','directors','writers','genres','tags','audio_languages','subtitle_languages')
    return any(_smart_text_match(v,raw) for v in _smart_values(item,list_keys))


def _smart_query_terms(query:str)->list[str]:
    terms=[]
    for m in re.finditer(r'"([^"\\]*(?:\\.[^"\\]*)*)"|(\S+)',str(query or '')):
        val=(m.group(1) if m.group(1) is not None else m.group(2) or '').replace('\\"','"').strip()
        if val:terms.append(val)
    return terms


def _smart_is_advanced(query:str)->bool:
    q=str(query or '')
    return bool(re.search(r'(?i)(?:^|\s|\()\w+\s*:',q) or re.search(r'(?i)(?:^|\s)(?:AND|OR|NOT)(?:\s|$)',q) or '(' in q or ')' in q)


def _smart_natural_match(item:dict[str,Any],query:str)->bool:
    terms=_smart_query_terms(query)
    return bool(terms) and all(_smart_token_match(item,t) for t in terms)


def _smart_relevance(item:dict[str,Any],query:str)->int:
    phrase=str(query or '').strip().strip('"')
    if not phrase:return 0
    score=0
    titles=_smart_values(item,('title','episode_title','show_title'))
    people=_smart_values(item,('actors','directors','writers'))
    artist=_smart_values(item,('artist','album'))
    primary=[*titles,*people,*artist]
    qn=_smart_norm(phrase);qc=_smart_compact(phrase)
    for v in titles:
        if _smart_norm(v)==qn or _smart_compact(v)==qc:score=max(score,1200)
        elif _smart_text_match(v,phrase):score=max(score,850)
    for v in people:
        if _smart_norm(v)==qn or _smart_compact(v)==qc:score=max(score,1100)
        elif _smart_text_match(v,phrase):score=max(score,800)
    for v in artist:
        if _smart_norm(v)==qn or _smart_compact(v)==qc:score=max(score,1050)
        elif _smart_text_match(v,phrase):score=max(score,760)
    if re.fullmatch(r'(?:18|19|20|21)\d{2}',qn) and int(qn) in _smart_years(item):score=max(score,900)
    for key,pts in (('network',500),('original_network',500),('content_rating',440),('library_name',300),('video_resolution',300),('video_codec',280),('dynamic_range',280)):
        if _smart_text_match(item.get(key),phrase):score=max(score,pts)
    for key,pts in (('genres',520),('tags',480),('audio_languages',300),('subtitle_languages',300)):
        if any(_smart_text_match(v,phrase) for v in _smart_values(item,(key,))):score=max(score,pts)
    if _smart_text_match(item.get('summary'),phrase):score=max(score,120)
    for term in _smart_query_terms(query):
        if any(_smart_text_match(v,term) for v in primary):score+=35
        elif _smart_token_match(item,term):score+=10
    return score


def smart_media_search_playable(query:str,limit:int|None=None)->list[dict[str,Any]]:
    q=str(query or '').strip()
    if not q:return G['_media_power_base_media_search_playable'](q,limit)
    if _smart_is_advanced(q):return G['_media_power_base_media_search_playable'](q,limit)
    out=[]
    for x in collection_search_items():
        try:ok=_smart_natural_match(x,q)
        except Exception:ok=False
        if ok:out.append(x)
    out.sort(key=lambda x:(-_smart_relevance(x,q),str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    return out[:limit] if limit else out


def _num_compare(actual:float|int|None,value:str,unit:float=1.0) -> bool:
    if actual is None:return False
    m=re.match(r'^(<=|>=|<|>|=)?\s*([0-9.]+)(?:-([0-9.]+))?$',value.strip())
    if not m:return False
    a=float(actual)/unit;lo=float(m.group(2));hi=float(m.group(3)) if m.group(3) else None;op=m.group(1) or '='
    if hi is not None:return lo<=a<=hi
    return {'<':a<lo,'<=':a<=lo,'>':a>lo,'>=':a>=lo,'=':abs(a-lo)<1e-9}[op]


def search_atom(item:dict[str,Any],token:str)->bool:
    if ':' not in token:return _smart_token_match(item,token)
    field,value=token.split(':',1);field=field.casefold();value=value.strip().strip('"')
    if field in ('type','media_type'):
        wanted=value.casefold().replace(' ','_')
        kind=str(item.get('media_kind') or item.get('media_type') or '').casefold()
        if wanted=='show':return bool(item.get('show_title')) and kind=='episode'
        if wanted=='season':return bool(item.get('show_title')) and item.get('season_number') is not None
        if wanted=='artist':return bool(item.get('artist'))
        aliases={'tv':'episode','musicvideo':'music_video','other':'other_video','remote':'remote_stream','stream':'remote_stream'}
        wanted=aliases.get(wanted,wanted)
        return kind==wanted or str(item.get('media_type') or '').casefold()==wanted
    lists={'writer':'writers','writers':'writers','audio_language':'audio_languages','audio_lang':'audio_languages','subtitle_language':'subtitle_languages','subtitle_lang':'subtitle_languages','tag':'tags','tags':'tags'}
    if field in lists:return any(G['_search_text_match'](x,value) for x in item.get(lists[field]) or [])
    if field in ('rating','content_rating'):return G['_search_text_match'](item.get('content_rating'),value)
    if field in ('artist','artist_exact'):
        return (str(item.get('artist') or '').casefold()==value.casefold()) if field.endswith('_exact') else G['_search_text_match'](item.get('artist'),value)
    if field=='album':return G['_search_text_match'](item.get('album'),value)
    if field in ('added','added_date','date_added'):
        d=re.sub(r'[^0-9]','',str(item.get('added_at') or ''))[:8];want=re.sub(r'[^0-9]','',value)
        rng=re.match(r'^\[(\d{4,8})\s+TO\s+(\d{4,8})\]$',value,re.I)
        if rng:return (rng.group(1)+'00000000')[:8]<=d<=(rng.group(2)+'99999999')[:8] if d else False
        return bool(d) and d.startswith(want)
    if field in ('chapters','chapter_count'):return _num_compare(G['safe_int'](item.get('chapter_count')),value)
    if field in ('duration','duration_minutes'):return _num_compare(G['safe_float'](item.get('duration')),value,60.0)
    if field in ('duration_seconds',):return _num_compare(G['safe_float'](item.get('duration')),value)
    if field in ('width','video_width'):return _num_compare(G['safe_int'](item.get('video_width')),value)
    if field in ('height','video_height'):return _num_compare(G['safe_int'](item.get('video_height')),value)
    if field in ('resolution','video_resolution'):return G['_search_text_match'](item.get('video_resolution'),value)
    if field in ('codec','video_codec'):return G['_search_text_match'](item.get('video_codec'),value)
    if field=='audio_codec':return G['_search_text_match'](item.get('audio_codec'),value)
    if field in ('bit_depth','bitdepth'):return _num_compare(G['safe_int'](item.get('bit_depth')),value)
    if field in ('hdr','dynamic_range'):
        dr=str(item.get('dynamic_range') or '')
        if field=='hdr' and value.casefold() in ('true','yes','1'):return bool(dr and dr.casefold()!='sdr')
        if field=='hdr' and value.casefold() in ('false','no','0'):return not dr or dr.casefold()=='sdr'
        return G['_search_text_match'](dr,value)
    return G['_media_power_base_search_atom'](item,token)


def _artist_selection_token(item:dict[str,Any])->str:
    st=str(item.get('source_type') or ''); artist=str(item.get('artist') or '')
    payload={'source_type':st,'selection_type':'artist','artist':artist}
    if st=='local':payload['library_id']=int(item.get('library_id'))
    elif st=='plex':payload['plex_library_id']=int(item.get('plex_library_id') or item.get('library_id'))
    elif st=='external':payload['external_library_id']=int(item.get('library_id'))
    return G['encode_selection'](payload)


def _season_selection_token(item:dict[str,Any])->str:
    st=str(item.get('source_type') or '')
    if st=='local':return G['encode_selection']({'source_type':'local','library_id':int(item.get('library_id')),'selection_type':'season','show_title':str(item.get('show_title') or ''),'season_number':G['safe_int'](item.get('season_number'))})
    if st=='plex':return G['encode_selection']({'source_type':'plex','plex_library_id':int(item.get('plex_library_id') or item.get('library_id')),'selection_type':'season','show_key':str(item.get('show_rating_key') or item.get('show_key') or ''),'show_title':str(item.get('show_title') or ''),'season_number':G['safe_int'](item.get('season_number'))})
    return G['encode_selection']({'source_type':'external','external_library_id':int(item.get('library_id')),'selection_type':'season','show_title':str(item.get('show_title') or ''),'season_number':G['safe_int'](item.get('season_number'))})


def item_selection_token(item:dict[str,Any])->str:
    if item.get('source_type')=='live':return G['encode_selection']({'source_type':'live','selection_type':'item','live_stream_id':int(item.get('id'))})
    return G['_media_power_base_item_selection_token'](item)


def selection_items(token:str)->list[dict[str,Any]]:
    try:p=G['decode_selection'](token)
    except Exception:return []
    st=str(p.get('source_type') or '');typ=str(p.get('selection_type') or '')
    if st=='live':
        with G['db']() as conn:r=conn.execute('SELECT * FROM live_streams WHERE id=? AND enabled=1',(G['safe_int'](p.get('live_stream_id')),)).fetchone()
        if not r:return []
        d=dict(r);d.update({'source_type':'live','uid':f"live:{r['id']}",'media_type':'remote_stream','media_kind':'remote_stream','title':r['name'],'duration':3600.0,'source_url':r['stream_url'],'library_name':'Live IPTV','user_agent':r['user_agent'],'referer':r['referer'],'_trim_limit':3600.0})
        return [d]
    if typ=='artist':
        artist=str(p.get('artist') or '').casefold();base=collection_search_items();out=[]
        for x in base:
            if str(x.get('source_type'))!=st or str(x.get('artist') or '').casefold()!=artist:continue
            lid=G['safe_int'](x.get('library_id') or x.get('plex_library_id'))
            wanted=G['safe_int'](p.get('library_id') or p.get('plex_library_id') or p.get('external_library_id'))
            if wanted and lid!=wanted:continue
            out.append(x)
        return out
    return G['_media_power_base_selection_items'](token)


def selection_description(token:str)->str:
    try:p=G['decode_selection'](token)
    except Exception:return 'Unknown selection'
    if p.get('source_type')=='live':
        with G['db']() as conn:r=conn.execute('SELECT name FROM live_streams WHERE id=?',(G['safe_int'](p.get('live_stream_id')),)).fetchone()
        return 'Remote Stream / '+(str(r['name']) if r else 'Missing stream')
    if p.get('selection_type')=='artist':return f"Artist / {p.get('artist') or 'Unknown'}"
    return G['_media_power_base_selection_description'](token)


def playlist_media(playlist_id:int)->list[dict[str,Any]]:
    with G['db']() as conn:rows=conn.execute('SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall()
    out=[]; day=datetime.now().astimezone().date().toordinal()
    for row in rows:
        try:p=G['decode_selection'](str(row['token']))
        except Exception:continue
        if p.get('source_type')=='collection' and p.get('collection_id'):items=G['collection_media'](int(p['collection_id']))
        else:items=selection_items(str(row['token']))
        items=G['_playlist_order_items'](items,str(row['playback_order'] or 'season_episode'),f'{playlist_id}:{row["id"]}')
        if not int(row['play_all'] or 0) and items:
            idx=(day+int(row['id']))%len(items);items=[items[idx]]
        for raw in items:
            x=dict(raw)
            if not int(row['show_in_epg'] or 0):x['_guide_hidden']=True
            x['_playlist_item_id']=int(row['id']);x['_playlist_id']=playlist_id
            out.append(x)
    return out


def playlists_index_page(msg:str='')->str:
    e=G['e']
    with G['db']() as conn:pls=conn.execute('''SELECT p.*,COUNT(pi.id) item_count FROM playlists p LEFT JOIN playlist_items pi ON pi.playlist_id=p.id GROUP BY p.id ORDER BY p.name COLLATE NOCASE''').fetchall()
    rows=[]
    for p in pls:rows.append(f"<tr><td><b>{e(p['name'])}</b></td><td>{int(p['item_count'] or 0)}</td><td>{len(playlist_media(int(p['id']))):,}</td><td>{e((p['updated_at'] or '')[:19].replace('T',' '))}</td><td><a class='button secondary' href='/studio/playlists/{p['id']}'>Edit</a></td></tr>")
    rows_html=''.join(rows) or "<tr><td colspan='5' class='empty'>No playlists yet.</td></tr>"
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+G['_page_heading']('Playlists','Ordered mixed-media programming lists: shows, seasons, episodes, artists, movies, music videos, other videos, songs, images, Collections and remote streams.')+f"""<div class='card'><h2>Add Playlist</h2><form method='post' action='/studio/playlists/add'><div class='grid'><div><label>Name</label><input name='name' required placeholder='Saturday Night Mix'></div><div style='align-self:end'><button>Create Playlist</button></div></div></form></div><div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Entries</th><th>Playable Media</th><th>Updated</th><th></th></tr></thead><tbody>{rows_html}</tbody></table></div></div>"""
    return G['page_shell']('Playlists',body)


def playlist_edit_page(playlist_id:int,msg:str='')->str:
    e=G['e']
    with G['db']() as conn:
        p=conn.execute('SELECT * FROM playlists WHERE id=?',(playlist_id,)).fetchone()
        if not p:raise HTTPException(404,'Playlist not found')
        rows=conn.execute('SELECT * FROM playlist_items WHERE playlist_id=? ORDER BY position,id',(playlist_id,)).fetchall();cols=conn.execute('SELECT id,name,kind FROM collections ORDER BY name COLLATE NOCASE').fetchall()
    trs=[]
    for idx,r in enumerate(rows):
        desc=selection_description(str(r['token']))
        try:
            pay=G['decode_selection'](str(r['token']))
            if pay.get('source_type')=='collection':
                with G['db']() as conn:c=conn.execute('SELECT name,kind FROM collections WHERE id=?',(G['safe_int'](pay.get('collection_id')),)).fetchone()
                desc=f"{str(c['kind']).title()} Collection / {c['name']}" if c else 'Missing Collection'
        except Exception:pass
        up="<button class='secondary' name='direction' value='up'>↑</button>" if idx>0 else '';down="<button class='secondary' name='direction' value='down'>↓</button>" if idx<len(rows)-1 else ''
        play='Yes' if r['play_all'] else 'One';epg='Show' if r['show_in_epg'] else 'Hide'
        trs.append(f"<tr><td>{idx+1}</td><td><b>{e(desc)}</b></td><td>{e(str(r['playback_order']).replace('_',' ').title())}</td><td>{play}</td><td>{epg}</td><td><form class='inline' method='post' action='/studio/playlists/{playlist_id}/items/{r['id']}/settings'><label class='small'><input type='checkbox' name='play_all' value='1' {'checked' if r['play_all'] else ''}> Play All</label> <label class='small'><input type='checkbox' name='show_in_epg' value='1' {'checked' if r['show_in_epg'] else ''}> EPG</label> <button class='secondary'>Save</button></form> <form class='inline' method='post' action='/studio/playlists/{playlist_id}/items/{r['id']}/move'>{up}{down}</form> <form class='inline' method='post' action='/studio/playlists/{playlist_id}/items/{r['id']}/delete'><button class='danger'>Remove</button></form></td></tr>")
    rows_html=''.join(trs) or "<tr><td colspan='6' class='empty'>This playlist is empty. Use Media → Search to add exact media, seasons, artists or streams.</td></tr>"
    colopts=''.join(f"<option value='{c['id']}'>{e(c['name'])} ({e(c['kind'])})</option>" for c in cols)
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    body=notice+G['_page_heading'](str(p['name']),'Entries play top-to-bottom. Play All expands a source completely; off means one item before advancing.',f"<a class='button secondary' href='/lists/playlists'>All Playlists</a> <a class='button' href='/media/search'>Add Media From Search</a>")+f"""
<div class='card'><form method='post' action='/studio/playlists/{playlist_id}/rename'><div class='grid'><div><label>Name</label><input name='name' value='{e(p['name'])}' required></div><div style='align-self:end'><button>Rename</button></div></div></form></div>
<div class='card'><h2>Playlist Entries</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Source</th><th>Order</th><th>Play All</th><th>EPG</th><th>Actions</th></tr></thead><tbody>{rows_html}</tbody></table></div></div>
<div class='card'><h2>Add Collection</h2><form method='post' action='/studio/playlists/{playlist_id}/add-source'><div class='grid3'><div><label>Collection</label><select name='collection_id'>{colopts}</select></div><div><label>Playback Order</label><select name='playback_order'><option value='season_episode'>Season / Episode</option><option value='chronological'>Chronological</option><option value='shuffle'>Shuffle</option><option value='random'>Random Daily Order</option></select></div><div><label><input type='checkbox' name='play_all' value='1' checked> Play All</label><label><input type='checkbox' name='show_in_epg' value='1' checked> Show in EPG</label><button>Add Collection</button></div></div></form></div>
<div class='card'><h2>Search-driven entries</h2><p>Media → Search can now add individual episodes, movies, songs, images, music videos and remote streams, or grouped <code>type:season</code> and <code>type:artist</code> selections directly to this playlist.</p></div>
<div class='card'><h2>Danger Zone</h2><form method='post' action='/studio/playlists/{playlist_id}/delete' onsubmit=\"return confirm('Delete this playlist?');\"><button class='danger'>Delete Playlist</button></form></div>"""
    return G['page_shell']('Playlist',body)


def _render_media_search_results(q:str,results:list[dict[str,Any]],msg:str='')->str:
    e=G['e'];q=(q or '').strip();results=list(results or [])
    mode='show' if re.search(r'(?i)(?:^|\s|\()type:show(?:\s|\)|$)',q) else 'season' if re.search(r'(?i)(?:^|\s|\()type:season(?:\s|\)|$)',q) else 'artist' if re.search(r'(?i)(?:^|\s|\()type:artist(?:\s|\)|$)',q) else 'item'
    display=[]
    if mode!='item':
        grouped={}
        for x in results:
            if mode=='show' and not x.get('show_title'):continue
            if mode=='season' and (not x.get('show_title') or x.get('season_number') is None):continue
            if mode=='artist' and not x.get('artist'):continue
            if mode=='show':key=(x.get('source_type'),x.get('library_id') or x.get('plex_library_id'),x.get('show_key') or x.get('show_title'))
            elif mode=='season':key=(x.get('source_type'),x.get('library_id') or x.get('plex_library_id'),x.get('show_key') or x.get('show_title'),x.get('season_number'))
            else:key=(x.get('source_type'),x.get('library_id') or x.get('plex_library_id'),str(x.get('artist')).casefold())
            grouped.setdefault(key,{'item':x,'count':0})['count']+=1
        display=list(grouped.values())
    else:display=[{'item':x,'count':1} for x in results]
    with G['db']() as conn:
        manual=conn.execute("SELECT id,name FROM collections WHERE kind='manual' ORDER BY name").fetchall();pls=conn.execute('SELECT id,name FROM playlists ORDER BY name').fetchall()
    rows=[]
    for g in display:
        x=g['item']
        if mode=='show':token=G['_show_selection_token'](x);title=str(x.get('show_title') or '');typ='Show'
        elif mode=='season':token=_season_selection_token(x);title=f"{x.get('show_title')} — Season {x.get('season_number')}";typ='Season'
        elif mode=='artist':token=_artist_selection_token(x);title=str(x.get('artist') or '');typ='Artist'
        else:token=item_selection_token(x);title=str(x.get('title') or '');typ=str(x.get('media_kind') or x.get('media_type') or 'Media').replace('_',' ').title(); title=f"{x.get('show_title')} — {title}" if x.get('show_title') else title
        details=[]
        if mode!='item':details.append(f"{g['count']} matching item(s)")
        if x.get('search_year'):details.append(str(x['search_year']))
        if x.get('video_resolution'):details.append(str(x['video_resolution']))
        if x.get('video_codec'):details.append(str(x['video_codec']).upper())
        if x.get('dynamic_range'):details.append(str(x['dynamic_range']))
        if x.get('bit_depth'):details.append(f"{x['bit_depth']}-bit")
        if x.get('content_rating'):details.append(str(x['content_rating']))
        rows.append(f"<tr><td><input type='checkbox' name='token' value='{e(token)}'></td><td><b>{e(title)}</b><div class='muted small'>{e(' · '.join(details))}</div></td><td>{e(typ)}</td><td>{e(str(x.get('source_type') or '').title())}</td><td>{e(x.get('library_name') or '')}</td><td>{e(', '.join((x.get('writers') or [])[:2]) or ', '.join((x.get('actors') or [])[:2]))}</td></tr>")
    result_html=''.join(rows) or ("<tr><td colspan='6' class='empty'>No media matched this search.</td></tr>" if q else "<tr><td colspan='6' class='empty'>Enter a search above.</td></tr>")
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    save=''
    if q:save=f"<div class='card'><h2>Save As Smart Collection</h2><form method='post' action='/media/search/save-smart'><input type='hidden' name='query' value='{e(q)}'><div class='grid'><input name='name' required placeholder='My Smart Collection'><button>Save Smart Collection</button></div></form></div>"
    manopts=''.join(f"<option value='{r['id']}'>{e(r['name'])}</option>" for r in manual);plopts=''.join(f"<option value='{r['id']}'>{e(r['name'])}</option>" for r in pls)
    controls=''
    if q:controls=f"""<div class='card'><h2>Add selected results</h2><div class='grid'><div><label>Manual Collection</label><select name='collection_id'><option value=''>— choose —</option>{manopts}</select><input name='new_name' placeholder='Or new Collection name'><button formaction='/media/search/add-to-collection'>Add To Collection</button></div><div><label>Playlist</label><select name='playlist_id'><option value=''>— choose —</option>{plopts}</select><input name='new_playlist_name' placeholder='Or new Playlist name'><label>Order</label><select name='playback_order'><option value='season_episode'>Season / Episode</option><option value='chronological'>Chronological</option><option value='shuffle'>Shuffle</option><option value='random'>Random Daily</option></select><label><input type='checkbox' name='play_all' value='1' checked> Play All for grouped selections</label><label><input type='checkbox' name='show_in_epg' value='1' checked> Show in EPG</label><button formaction='/media/search/add-to-playlist'>Add To Playlist</button></div></div></div>"""
    helptext="""<b>Normally, just type what you remember.</b> Examples: <code>John Ritter</code> · <code>M*A*S*H</code> · <code>1984</code> · <code>1980s comedy</code> · <code>NBC</code> · <code>Star Trek 1990s</code> · <code>4K HDR</code> · <code>Spanish audio</code>. ViperTV searches titles, show names, actors, directors, writers, years, networks, genres, tags, artists, albums, ratings, libraries, languages and technical media details automatically.<br><br><b>Advanced syntax is optional.</b> You can still use precise fields such as <code>actor:&quot;John Ritter&quot;</code>, <code>writer:&quot;Aaron Sorkin&quot;</code>, <code>year:1980-1989</code>, <code>rating:TV-14</code>, <code>audio_language:eng</code>, <code>duration:&gt;=45</code>, <code>resolution:1920x1080</code>, <code>video_codec:h264</code>, <code>bit_depth:10</code>, <code>hdr:true</code>, <code>type:season</code>, <code>type:artist</code>, <code>type:song</code>, <code>type:image</code> and <code>type:remote_stream</code>, together with AND / OR / NOT."""
    body=notice+G['_page_heading']('Search','Smart global search — type a person, title, year, genre, network or anything you remember.')+f"""<div class='card'><form method='get' action='/media/search'><label>Search</label><div class='grid'><input name='q' value='{e(q)}' placeholder='John Ritter, M*A*S*H, 1984, comedy, NBC, 4K HDR...'><div class='toolbar'><button>Search</button><a class='button secondary' href='/media/search'>Clear</a></div></div></form><p class='small muted'>No field names required. Multiple words narrow the results automatically.</p><details><summary>Advanced search help (optional)</summary><p class='small muted'>{helptext}</p></details></div>{save}<form method='post'><input type='hidden' name='return_query' value='{e(q)}'><div class='card'><div class='page-heading'><div><h2>Results</h2><p>{len(display):,} shown</p></div><button type='button' class='secondary' onclick=\"document.querySelectorAll('input[name=token]').forEach(x=>x.checked=true)\">Select All</button></div><div class='table-wrap'><table><thead><tr><th></th><th>Title</th><th>Type</th><th>Source</th><th>Library</th><th>Writer / People</th></tr></thead><tbody>{result_html}</tbody></table></div></div>{controls}</form>"""
    return G['page_shell']('Search',body)


# -------- v1.2.3 asynchronous Search Progress -------------------------------
_SEARCH_JOBS: dict[str,dict[str,Any]] = {}
_SEARCH_JOB_LOCK = threading.RLock()
_SEARCH_JOB_TTL = 30 * 60
_SEARCH_JOB_LIMIT = 32


def _search_job_cleanup() -> None:
    now=time.time()
    with _SEARCH_JOB_LOCK:
        for jid in list(_SEARCH_JOBS):
            if now-float(_SEARCH_JOBS[jid].get('touched') or 0)>_SEARCH_JOB_TTL:
                _SEARCH_JOBS.pop(jid,None)
        if len(_SEARCH_JOBS)>_SEARCH_JOB_LIMIT:
            ordered=sorted(_SEARCH_JOBS.items(),key=lambda kv:float(kv[1].get('touched') or 0))
            for jid,_ in ordered[:len(_SEARCH_JOBS)-_SEARCH_JOB_LIMIT]:
                _SEARCH_JOBS.pop(jid,None)


def _search_job_update(job_id:str,**values:Any) -> None:
    with _SEARCH_JOB_LOCK:
        job=_SEARCH_JOBS.get(job_id)
        if not job:return
        job.update(values);job['touched']=time.time()


def _search_job_snapshot(job_id:str) -> dict[str,Any]|None:
    with _SEARCH_JOB_LOCK:
        job=_SEARCH_JOBS.get(job_id)
        if not job:return None
        job['touched']=time.time()
        return {k:v for k,v in job.items() if k!='results'}


def _run_search_job(job_id:str,query:str) -> None:
    try:
        _search_job_update(job_id,state='running',stage='Preparing searchable catalog',message='Loading titles, people and metadata…',percent=4,current=0,total=0,matches=0)
        items=collection_search_items()
        total=len(items)
        _search_job_update(job_id,stage='Searching media',message=f'Checking {total:,} searchable items…',percent=10,total=total,current=0,matches=0)
        advanced=_smart_is_advanced(query)
        pred=G['_compile_search_query'](query) if advanced else None
        found=[];match_count=0
        tick=max(1,min(250,total//250 if total else 1))
        for idx,x in enumerate(items,1):
            try:ok=bool(pred(x)) if advanced else _smart_natural_match(x,query)
            except Exception:ok=False
            if ok:
                match_count+=1
                # Natural search needs all matches until ranking; advanced results retain
                # the historical first-500 display cap while still scanning for progress/count.
                if not advanced or len(found)<500:found.append(x)
            if idx==total or idx%tick==0:
                pct=10+(82*idx/max(1,total))
                _search_job_update(job_id,current=idx,matches=match_count,percent=round(min(92,pct),1),message=f'{idx:,} / {total:,} items checked · {match_count:,} match'+('es' if match_count!=1 else ''))
        _search_job_update(job_id,stage='Ranking results',message=f'Ranking {match_count:,} match'+('es' if match_count!=1 else '')+'…',percent=96,current=total,matches=match_count)
        if advanced:
            found.sort(key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
            results=found[:500]
        else:
            found.sort(key=lambda x:(-_smart_relevance(x,query),str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
            results=found[:500]
        _search_job_update(job_id,state='done',stage='Complete',message=f'{match_count:,} match'+('es' if match_count!=1 else '')+f' found · showing up to {len(results):,}',percent=100,current=total,total=total,matches=match_count,results=results,finished=time.time())
    except Exception as exc:
        _search_job_update(job_id,state='error',stage='Search failed',message=str(exc)[:500],percent=100,error=str(exc)[:1000],finished=time.time())


def _search_help_text() -> str:
    return """<b>Normally, just type what you remember.</b> Examples: <code>John Ritter</code> · <code>M*A*S*H</code> · <code>1984</code> · <code>1980s comedy</code> · <code>NBC</code> · <code>Star Trek 1990s</code> · <code>4K HDR</code> · <code>Spanish audio</code>. ViperTV searches titles, show names, actors, directors, writers, years, networks, genres, tags, artists, albums, ratings, libraries, languages and technical media details automatically.<br><br><b>Advanced syntax is optional.</b> You can still use precise fields such as <code>actor:&quot;John Ritter&quot;</code>, <code>writer:&quot;Aaron Sorkin&quot;</code>, <code>year:1980-1989</code>, <code>rating:TV-14</code>, <code>audio_language:eng</code>, <code>duration:&gt;=45</code>, <code>resolution:1920x1080</code>, <code>video_codec:h264</code>, <code>bit_depth:10</code>, <code>hdr:true</code>, <code>type:season</code>, <code>type:artist</code>, <code>type:song</code>, <code>type:image</code> and <code>type:remote_stream</code>, together with AND / OR / NOT."""


def media_search_page(q:str='',msg:str='')->str:
    e=G['e'];q=(q or '').strip()
    notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
    if not q:
        body=notice+G['_page_heading']('Search','Smart global search — type a person, title, year, genre, network or anything you remember.')+f"""<div class='card'><form method='get' action='/media/search'><label>Search</label><div class='grid'><input name='q' value='' autofocus placeholder='John Ritter, M*A*S*H, 1984, comedy, NBC, 4K HDR...'><div class='toolbar'><button>Search</button><a class='button secondary' href='/media/search'>Clear</a></div></div></form><p class='small muted'>No field names required. Multiple words narrow the results automatically.</p><details><summary>Advanced search help (optional)</summary><p class='small muted'>{_search_help_text()}</p></details></div>"""
        return G['page_shell']('Search',body)
    qjs=json.dumps(q)
    body=notice+G['_page_heading']('Search','Searching your ViperTV media catalog…')+f"""
<div class='card'>
  <form method='get' action='/media/search'><label>Search</label><div class='grid'><input name='q' value='{e(q)}' placeholder='John Ritter, M*A*S*H, 1984, comedy, NBC, 4K HDR...'><div class='toolbar'><button>Search</button><a class='button secondary' href='/media/search'>Cancel / Clear</a></div></div></form>
</div>
<div class='card' id='search-progress-card'>
  <div class='page-heading'><div><h2 id='search-stage'>Starting search…</h2><p class='muted' id='search-message'>Preparing your media catalog.</p></div><div><b id='search-percent'>0%</b></div></div>
  <progress id='search-progress' max='100' value='0' style='width:100%;height:24px'></progress>
  <div class='grid' style='margin-top:12px'><div><span class='muted small'>Items checked</span><div><b id='search-count'>0</b></div></div><div><span class='muted small'>Matches found</span><div><b id='search-matches'>0</b></div></div></div>
  <p class='small muted' style='margin-bottom:0'>You can leave this page; the search continues on the server until it finishes or ViperTV restarts.</p>
</div>
<script>
(async function(){{
  const query={qjs};
  const stage=document.getElementById('search-stage'), message=document.getElementById('search-message');
  const bar=document.getElementById('search-progress'), pct=document.getElementById('search-percent');
  const count=document.getElementById('search-count'), matches=document.getElementById('search-matches');
  function fmt(n){{return Number(n||0).toLocaleString();}}
  function show(s){{
    stage.textContent=s.stage||'Searching…';message.textContent=s.message||'';
    const p=Math.max(0,Math.min(100,Number(s.percent||0)));bar.value=p;pct.textContent=Math.round(p)+'%';
    count.textContent=s.total ? fmt(s.current)+' / '+fmt(s.total) : fmt(s.current);
    matches.textContent=fmt(s.matches);
  }}
  try{{
    const r=await fetch('/api/media/search/start?q='+encodeURIComponent(query),{{method:'POST',cache:'no-store'}});
    if(!r.ok)throw new Error('Unable to start search ('+r.status+')');
    const started=await r.json();const job=started.job_id;
    while(true){{
      await new Promise(resolve=>setTimeout(resolve,250));
      const sr=await fetch('/api/media/search/status/'+encodeURIComponent(job),{{cache:'no-store'}});
      if(!sr.ok)throw new Error('Search status unavailable ('+sr.status+')');
      const s=await sr.json();show(s);
      if(s.state==='done'){{window.location.replace('/media/search/results?job='+encodeURIComponent(job));return;}}
      if(s.state==='error')throw new Error(s.error||s.message||'Search failed');
    }}
  }}catch(err){{stage.textContent='Search failed';message.textContent=String(err&&err.message||err);bar.value=100;pct.textContent='Error';}}
}})();
</script>"""
    return G['page_shell']('Search',body)


def local_command(channel,item,offset,profile_override=None):
    kind=str(item.get('media_kind') or item.get('media_type') or '')
    if item.get('source_type')=='live':
        item['_actual_stream_profile']='direct'
        src=str(item.get('source_url') or '');headers=[]
        if item.get('user_agent'):headers += ['-user_agent',str(item['user_agent'])]
        if item.get('referer'):headers += ['-headers',f"Referer: {item['referer']}\r\n"]
        return ['ffmpeg','-hide_banner','-loglevel','error',*headers,'-i',src,'-map','0:v:0?','-map','0:a:0?','-c','copy','-sn','-dn','-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
    if kind in {'image','song'}:
        profile,_configured,_warning=G['effective_stream_profile'](channel,profile_override)
        if profile=='direct':profile='software'
        item['_actual_stream_profile']=profile
        res=str(channel['resolution'] or '1920x1080'); scale=res.replace('x',':')
        preferred=G['hardware_preferred_vaapi_device']() or None
        prereq=G['hwaccel'].profile_prerequisites(profile,preferred) if profile in {'vaapi','qsv','nvenc'} else {}
        prefix=['ffmpeg','-hide_banner','-loglevel','error']
        if profile=='vaapi':prefix += ['-vaapi_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
        elif profile=='qsv':prefix += ['-qsv_device',str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
        if kind=='image':
            path=str(item.get('path') or '');dur=max(1.0,float(item.get('duration') or 10)-max(0.0,float(offset or 0)))
            prefix += ['-re','-stream_loop','-1','-framerate','30','-i',path,'-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',f'{dur:.3f}']
            filters=f"scale={scale}:force_original_aspect_ratio=decrease,pad={scale}:(ow-iw)/2:(oh-ih)/2"
            if profile=='vaapi':filters += ',format=nv12,hwupload'
            elif profile=='qsv':filters += ',format=nv12'
            elif profile=='nvenc':filters += ',format=yuv420p'
            prefix += ['-vf',filters,'-map','0:v:0','-map','1:a:0']
        else:
            path=str(item.get('path') or '')
            prefix += ['-re','-ss',f'{max(0.0,float(offset or 0)):.3f}','-i',path,'-f','lavfi','-i',f"color=c=black:s={res}:r=30",'-map','1:v:0','-map','0:a:0']
            if profile=='vaapi':prefix += ['-vf','format=nv12,hwupload']
            elif profile=='qsv':prefix += ['-vf','format=nv12']
            elif profile=='nvenc':prefix += ['-vf','format=yuv420p']
        if profile=='vaapi':prefix += ['-c:v','h264_vaapi','-b:v',str(channel['video_bitrate'] or G['VIDEO_BITRATE'])]
        elif profile=='qsv':prefix += ['-c:v','h264_qsv','-b:v',str(channel['video_bitrate'] or G['VIDEO_BITRATE'])]
        elif profile=='nvenc':prefix += ['-c:v','h264_nvenc','-preset','p4','-tune','ll','-b:v',str(channel['video_bitrate'] or G['VIDEO_BITRATE'])]
        else:prefix += ['-c:v','libx264','-preset',G['TRANSCODE_PRESET'],'-pix_fmt','yuv420p']
        prefix += ['-c:a','aac','-b:a',G['AUDIO_BITRATE']]
        if kind!='image':prefix += ['-shortest']
        prefix += ['-mpegts_flags','+resend_headers+initial_discontinuity','-f','mpegts','pipe:1']
        return prefix
    return G['_media_power_base_local_command'](channel,item,offset,profile_override)


def _routes(app):
    @app.post('/api/media/search/start')
    def media_search_start(q:str=''):
        query=str(q or '').strip()
        if not query:return JSONResponse({'error':'Search query is required.'},status_code=400)
        _search_job_cleanup();job_id=uuid.uuid4().hex
        with _SEARCH_JOB_LOCK:
            _SEARCH_JOBS[job_id]={'job_id':job_id,'query':query,'state':'queued','stage':'Queued','message':'Waiting to start…','percent':0,'current':0,'total':0,'matches':0,'created':time.time(),'touched':time.time(),'results':[]}
        threading.Thread(target=_run_search_job,args=(job_id,query),name=f'vipertv-search-{job_id[:8]}',daemon=True).start()
        return {'job_id':job_id,'state':'queued'}

    @app.get('/api/media/search/status/{job_id}')
    def media_search_status(job_id:str):
        snap=_search_job_snapshot(job_id)
        if not snap:return JSONResponse({'error':'Search job expired or was not found.','state':'missing'},status_code=404)
        return snap

    @app.get('/media/search/results',response_class=HTMLResponse)
    def media_search_results(job:str,msg:str=''):
        with _SEARCH_JOB_LOCK:
            data=_SEARCH_JOBS.get(job)
            if data:data['touched']=time.time();state=str(data.get('state'));query=str(data.get('query') or '');results=list(data.get('results') or [])
            else:state='missing';query='';results=[]
        if state=='missing':return RedirectResponse('/media/search?msg='+G['quote']('That search result expired. Please run the search again.'),303)
        if state!='done':return RedirectResponse('/media/search?q='+G['quote'](query),303)
        suffix=f"{int(data.get('matches') or len(results)):,} total match"+('es' if int(data.get('matches') or len(results))!=1 else '')
        return _render_media_search_results(query,results,msg or suffix)

    @app.post('/media/search/add-to-playlist')
    def add_search_to_playlist(token:list[str]=Form(default=[]),playlist_id:str=Form(''),new_playlist_name:str=Form(''),playback_order:str=Form('season_episode'),play_all:str|None=Form(None),show_in_epg:str|None=Form(None),return_query:str=Form('')):
        if not token:return RedirectResponse('/media/search?q='+G['quote'](return_query)+'&msg='+G['quote']('Select at least one result first.'),303)
        G['safe_backup_before_change']();pid=G['safe_int'](playlist_id)
        if playback_order not in ('season_episode','chronological','shuffle','random'):playback_order='season_episode'
        with G['db']() as conn:
            if new_playlist_name.strip():
                old=conn.execute('SELECT id FROM playlists WHERE name=?',(new_playlist_name.strip(),)).fetchone();pid=int(old['id']) if old else int(conn.execute('INSERT INTO playlists(name,created_at,updated_at) VALUES(?,?,?)',(new_playlist_name.strip(),G['utcnow_iso'](),G['utcnow_iso']())).lastrowid)
            p=conn.execute('SELECT id,name FROM playlists WHERE id=?',(pid,)).fetchone() if pid else None
            if not p:return RedirectResponse('/media/search?q='+G['quote'](return_query)+'&msg='+G['quote']('Choose a playlist or enter a new playlist name.'),303)
            pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playlist_items WHERE playlist_id=?',(pid,)).fetchone()['p']);added=0
            for t in token:
                try:G['decode_selection'](t)
                except Exception:continue
                conn.execute('INSERT INTO playlist_items(playlist_id,position,token,playback_order,play_all,show_in_epg,created_at) VALUES(?,?,?,?,?,?,?)',(pid,pos,t,playback_order,1 if play_all else 0,1 if show_in_epg else 0,G['utcnow_iso']()));pos+=1;added+=1
            conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(G['utcnow_iso'](),pid));conn.commit();name=str(p['name'])
        return RedirectResponse('/media/search?q='+G['quote'](return_query)+'&msg='+G['quote'](f'Added {added} selection(s) to playlist {name}.'),303)

    @app.post('/studio/playlists/{playlist_id}/items/{item_id}/settings')
    def playlist_item_settings(playlist_id:int,item_id:int,play_all:str|None=Form(None),show_in_epg:str|None=Form(None)):
        G['safe_backup_before_change']()
        with G['db']() as conn:conn.execute('UPDATE playlist_items SET play_all=?,show_in_epg=? WHERE id=? AND playlist_id=?',(1 if play_all else 0,1 if show_in_epg else 0,item_id,playlist_id));conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(G['utcnow_iso'](),playlist_id));conn.commit()
        return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+G['quote']('Playlist entry settings saved.'),303)

    @app.post('/studio/playlists/{playlist_id}/add-source')
    def playlist_add_collection_advanced(playlist_id:int,collection_id:int=Form(...),playback_order:str=Form('season_episode'),play_all:str|None=Form(None),show_in_epg:str|None=Form(None)):
        G['safe_backup_before_change']()
        with G['db']() as conn:
            if not conn.execute('SELECT id FROM playlists WHERE id=?',(playlist_id,)).fetchone() or not conn.execute('SELECT id FROM collections WHERE id=?',(collection_id,)).fetchone():raise HTTPException(404)
            token=G['encode_selection']({'source_type':'collection','selection_type':'collection','collection_id':collection_id});pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playlist_items WHERE playlist_id=?',(playlist_id,)).fetchone()['p'])
            conn.execute('INSERT INTO playlist_items(playlist_id,position,token,playback_order,play_all,show_in_epg,created_at) VALUES(?,?,?,?,?,?,?)',(playlist_id,pos,token,playback_order,1 if play_all else 0,1 if show_in_epg else 0,G['utcnow_iso']()));conn.execute('UPDATE playlists SET updated_at=? WHERE id=?',(G['utcnow_iso'](),playlist_id));conn.commit()
        return RedirectResponse(f'/studio/playlists/{playlist_id}?msg='+G['quote']('Collection added to playlist.'),303)


def install_media_power(app,main_globals:dict[str,Any])->None:
    global G;G=main_globals
    # Startup migration wraps the v1.2 migration already called by lifespan.
    base_init=G['init_v12_db']
    def init_all():base_init();init_media_power_db()
    G['init_v12_db']=init_all

    # Preserve mature v1.2 helpers, then swap in additive versions used dynamically by routes/schedulers.
    G['_media_power_base_collection_search_items']=G['_collection_search_items'];G['_media_power_base_search_atom']=G['_search_atom'];G['_media_power_base_media_search_playable']=G['media_search_playable'];G['_media_power_base_selection_items']=G['_selection_items'];G['_media_power_base_item_selection_token']=G['_item_selection_token'];G['_media_power_base_selection_description']=G['_selection_description'];G['_media_power_base_local_command']=G['_profiled_local_command']
    G['_collection_search_items']=collection_search_items;G['_search_atom']=search_atom;G['media_search_playable']=smart_media_search_playable;G['_selection_items']=selection_items;G['_item_selection_token']=item_selection_token;G['_selection_description']=selection_description;G['playlist_media']=playlist_media;G['playlists_index_page']=playlists_index_page;G['playlist_edit_page']=playlist_edit_page;G['media_search_page']=media_search_page;G['_profiled_local_command']=local_command
    G['VIDEO_EXTS']=set(G.get('VIDEO_EXTS') or set())|AUDIO_EXTS|IMAGE_EXTS
    G['scan_library']=_wrap_scan_library(G['scan_library']);G['sync_plex_library']=_wrap_sync_plex(G['sync_plex_library']);G['sync_external_library']=_wrap_sync_external(G['sync_external_library'])
    _routes(app)

# -------- v1.2.4 persistent SQLite indexed search ---------------------------
# v1.2.3 made search asynchronous, but still rebuilt the complete merged media
# catalog for every query.  v1.2.4 materializes that merged catalog once into a
# persistent SQLite search index.  FTS5 handles normal smart searches; complex
# advanced expressions evaluate against the already-materialized payloads, so
# neither path has to rebuild People/TVDB/library relationships on each search.

_V124_INDEX_VERSION = '1.2.4'
_V124_INDEX_BUILD_LOCK = threading.Lock()
_V124_INDEX_SCHEDULE_LOCK = threading.RLock()
_V124_INDEX_SCHEDULE_GENERATION = 0
_V124_INDEX_RUNTIME_LOCK = threading.RLock()
_V124_INDEX_RUNTIME: dict[str, Any] = {
    'building': False, 'stage': 'Idle', 'current': 0, 'total': 0,
    'message': '', 'reason': '', 'started': None,
}

_v124_init_media_power_db_v123 = init_media_power_db


def init_media_power_db() -> None:
    _v124_init_media_power_db_v123()
    with G['db']() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS search_index_items(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          uid TEXT NOT NULL UNIQUE,
          source_type TEXT,
          media_kind TEXT,
          search_year INTEGER,
          duration REAL,
          added_at TEXT,
          bit_depth INTEGER,
          chapter_count INTEGER NOT NULL DEFAULT 0,
          video_width INTEGER,
          video_height INTEGER,
          dynamic_range TEXT,
          search_text TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          indexed_at TEXT NOT NULL
        )''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_search_index_source ON search_index_items(source_type)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_search_index_kind ON search_index_items(media_kind)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_search_index_year ON search_index_items(search_year)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_search_index_added ON search_index_items(added_at)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_search_index_bitdepth ON search_index_items(bit_depth)')
        conn.execute('''CREATE TABLE IF NOT EXISTS search_index_state(
          id INTEGER PRIMARY KEY CHECK(id=1),
          ready INTEGER NOT NULL DEFAULT 0,
          dirty INTEGER NOT NULL DEFAULT 1,
          building INTEGER NOT NULL DEFAULT 0,
          change_version INTEGER NOT NULL DEFAULT 1,
          built_version INTEGER NOT NULL DEFAULT 0,
          item_count INTEGER NOT NULL DEFAULT 0,
          built_at TEXT,
          reason TEXT,
          error TEXT,
          fts_enabled INTEGER NOT NULL DEFAULT 0,
          index_version TEXT NOT NULL DEFAULT ''
        )''')
        fts_enabled=1
        try:
            conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS search_index_fts USING fts5(
              uid UNINDEXED,
              title,
              show_title,
              people,
              search_text,
              tokenize='unicode61 remove_diacritics 2'
            )""")
        except sqlite3.Error:
            fts_enabled=0
        conn.execute('''INSERT OR IGNORE INTO search_index_state
          (id,ready,dirty,building,change_version,built_version,item_count,fts_enabled,index_version)
          VALUES(1,0,1,0,1,0,0,?,?)''',(fts_enabled,_V124_INDEX_VERSION))
        row=conn.execute('SELECT index_version FROM search_index_state WHERE id=1').fetchone()
        if not row or str(row['index_version'] or '')!=_V124_INDEX_VERSION:
            conn.execute('''UPDATE search_index_state
                            SET dirty=1,change_version=change_version+1,building=0,
                                index_version=?,fts_enabled=?,reason=?,error=NULL
                            WHERE id=1''',(_V124_INDEX_VERSION,fts_enabled,'Search index format upgraded'))
        else:
            conn.execute('UPDATE search_index_state SET building=0,fts_enabled=? WHERE id=1',(fts_enabled,))
        conn.commit()


def _v124_runtime_update(**values: Any) -> None:
    with _V124_INDEX_RUNTIME_LOCK:
        _V124_INDEX_RUNTIME.update(values)


def _v124_index_state() -> dict[str, Any]:
    with G['db']() as conn:
        row=conn.execute('SELECT * FROM search_index_state WHERE id=1').fetchone()
    data=dict(row) if row else {'ready':0,'dirty':1,'building':0,'item_count':0,'fts_enabled':0}
    with _V124_INDEX_RUNTIME_LOCK:
        runtime=dict(_V124_INDEX_RUNTIME)
    if runtime.get('building'):
        data.update({
            'building':1,
            'build_stage':runtime.get('stage') or 'Building Search Index',
            'build_current':int(runtime.get('current') or 0),
            'build_total':int(runtime.get('total') or 0),
            'build_message':runtime.get('message') or '',
            'build_reason':runtime.get('reason') or '',
            'build_started':runtime.get('started'),
        })
    return data


def _v124_index_ready() -> bool:
    try:
        st=_v124_index_state()
        return bool(int(st.get('ready') or 0))
    except Exception:
        return False


def _v124_mark_index_dirty(reason: str) -> None:
    try:
        with G['db']() as conn:
            conn.execute('''UPDATE search_index_state
                            SET dirty=1,change_version=change_version+1,reason=?,error=NULL
                            WHERE id=1''',(str(reason or 'Media catalog changed')[:240],))
            conn.commit()
    except Exception:
        pass


def _v124_schedule_index_rebuild(reason: str='Media catalog changed', delay: float=8.0, force: bool=False) -> None:
    global _V124_INDEX_SCHEDULE_GENERATION
    try:
        if force:_v124_mark_index_dirty(reason)
        st=_v124_index_state()
        if not force and not int(st.get('dirty') or 0) and int(st.get('ready') or 0):return
    except Exception:
        return
    with _V124_INDEX_SCHEDULE_LOCK:
        _V124_INDEX_SCHEDULE_GENERATION += 1
        generation=_V124_INDEX_SCHEDULE_GENERATION

    def worker() -> None:
        if delay>0:time.sleep(delay)
        with _V124_INDEX_SCHEDULE_LOCK:
            if generation!=_V124_INDEX_SCHEDULE_GENERATION:return
        try:
            st2=_v124_index_state()
            if int(st2.get('dirty') or 0) or not int(st2.get('ready') or 0):
                _v124_rebuild_search_index(reason)
        except Exception:
            pass
    threading.Thread(target=worker,name='vipertv-search-index-scheduler',daemon=True).start()


def _v124_language_aliases(values: list[str]) -> list[str]:
    out=[]
    for value in values:
        n=_smart_norm(value)
        if n:out.append(n)
        for canonical,aliases in _SMART_LANGUAGE_ALIASES.items():
            if n in {_smart_norm(x) for x in aliases}:
                out.append(canonical)
    return list(dict.fromkeys(out))


def _v124_search_text(item: dict[str, Any]) -> str:
    parts=[]
    scalar_keys=(
        'title','episode_title','show_title','summary','network','original_network','library_name','source_type',
        'content_rating','artist','album','video_resolution','video_codec','audio_codec','dynamic_range','media_kind','media_type',
    )
    list_keys=('actors','directors','writers','genres','tags','audio_languages','subtitle_languages')
    values=_smart_values(item,scalar_keys)+_smart_values(item,list_keys)
    for value in values:
        n=_smart_norm(value);c=_smart_compact(value)
        if n:parts.append(n)
        if c and c!=n and len(c)>=2:parts.append(c)
    for y in sorted(_smart_years(item)):
        parts.extend([str(y),f'{(y//10)*10}s'])
    kind=str(item.get('media_kind') or item.get('media_type') or '').casefold()
    reverse_types={
        'movie':['movie','movies','film','films'], 'episode':['episode','episodes','tv','television'],
        'song':['song','songs','audio','music'], 'image':['image','images','photo','photos'],
        'music_video':['musicvideo','musicvideos','music','video'], 'other_video':['othervideo','video'],
        'remote_stream':['stream','streams','remote','live'],
    }
    parts.extend(reverse_types.get(kind,[kind] if kind else []))
    width=G['safe_int'](item.get('video_width'));height=G['safe_int'](item.get('video_height'))
    if (width and width>=3500) or (height and height>=2000):parts += ['4k','uhd','2160p']
    elif height and height>=1000:parts += ['1080','1080p','fullhd','fhd']
    elif height and height>=700:parts += ['720','720p','hd']
    dr=_smart_norm(item.get('dynamic_range'))
    if dr and dr!='sdr':parts += ['hdr',dr,_smart_compact(dr)]
    else:parts += ['sdr']
    bits=G['safe_int'](item.get('bit_depth'))
    if bits:parts += [str(bits),f'{bits}bit']
    vc=_smart_compact(item.get('video_codec'))
    if vc in {'hevc','h265','x265'}:parts += ['hevc','h265','x265']
    elif vc in {'h264','avc','avc1','x264'}:parts += ['h264','avc','x264']
    elif vc=='av1':parts += ['av1']
    aud=_v124_language_aliases([str(x) for x in item.get('audio_languages') or []])
    subs=_v124_language_aliases([str(x) for x in item.get('subtitle_languages') or []])
    if aud:parts += aud+['audio']
    if subs:parts += subs+['subtitle','subtitles','subs']
    chapters=G['safe_int'](item.get('chapter_count')) or 0
    if chapters>0:parts += ['chapter','chapters',str(chapters)]
    # De-duplicate while preserving order. FTS does not benefit from repeated
    # tokens and keeping this compact makes rebuilds faster and the DB smaller.
    seen=set();out=[]
    for p in parts:
        p=_smart_norm(p)
        if p and p not in seen:
            seen.add(p);out.append(p)
    return ' '.join(out)


def _v124_safe_payload(item: dict[str, Any]) -> dict[str, Any]:
    # Search payloads live in the same SQLite DB, but avoid duplicating credentials
    # or signed source URLs. Runtime playback fields are reattached after a match.
    d=dict(item)
    for key in ('api_key','plex_token','access_token','token','source_url','stream_url','user_agent','referer'):
        d.pop(key,None)
    clean={}
    for k,v in d.items():
        if isinstance(v,sqlite3.Row):v=dict(v)
        if isinstance(v,set):v=sorted(v)
        clean[k]=v
    return clean


def _v124_rehydrate_runtime_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not items:return items
    ext_ids=sorted({G['safe_int'](x.get('library_id') or x.get('external_library_id')) for x in items if x.get('source_type')=='external' and G['safe_int'](x.get('library_id') or x.get('external_library_id'))})
    live_ids=sorted({G['safe_int'](x.get('id')) for x in items if x.get('source_type')=='live' and G['safe_int'](x.get('id'))})
    ext={};live={}
    with G['db']() as conn:
        if ext_ids:
            ph=','.join('?' for _ in ext_ids)
            for r in conn.execute(f'''SELECT el.id,ms.kind,ms.base_url,ms.api_key
                                      FROM external_libraries el JOIN media_servers ms ON ms.id=el.server_id
                                      WHERE el.id IN ({ph})''',ext_ids):ext[int(r['id'])]=dict(r)
        if live_ids:
            ph=','.join('?' for _ in live_ids)
            for r in conn.execute(f'SELECT * FROM live_streams WHERE id IN ({ph})',live_ids):live[int(r['id'])]=dict(r)
    for x in items:
        if x.get('source_type')=='external':
            m=ext.get(G['safe_int'](x.get('library_id') or x.get('external_library_id')))
            if m:x.update({'kind':m.get('kind'),'base_url':m.get('base_url'),'api_key':m.get('api_key')})
        elif x.get('source_type')=='live':
            m=live.get(G['safe_int'](x.get('id')))
            if m:x.update({'source_url':m.get('stream_url'),'stream_url':m.get('stream_url'),'user_agent':m.get('user_agent'),'referer':m.get('referer')})
    return items


def _v124_rebuild_search_index(reason: str='Manual rebuild', progress_cb=None) -> dict[str, Any]:
    # If another build is already active, wait for it rather than launching a
    # duplicate catalog merge. The waiting search can still surface live progress.
    while not _V124_INDEX_BUILD_LOCK.acquire(timeout=0.25):
        st=_v124_index_state()
        if progress_cb:
            progress_cb('Building Search Index',int(st.get('build_current') or 0),int(st.get('build_total') or 0),str(st.get('build_message') or 'Another index build is already running…'))
        if not int(st.get('building') or 0) and int(st.get('ready') or 0):return st
    try:
        st=_v124_index_state()
        # Another builder may have completed between the wait and lock acquisition.
        if int(st.get('ready') or 0) and not int(st.get('dirty') or 0) and reason!='Manual rebuild':return st
        target_version=int(st.get('change_version') or 0)
        now=time.time()
        _v124_runtime_update(building=True,stage='Preparing searchable catalog',current=0,total=0,message='Loading titles, People metadata and technical metadata once for the persistent index…',reason=reason,started=now)
        with G['db']() as conn:
            conn.execute('UPDATE search_index_state SET building=1,reason=?,error=NULL WHERE id=1',(str(reason)[:240],));conn.commit()
        if progress_cb:progress_cb('Preparing searchable catalog',0,0,'Loading the merged media catalog…')
        items=collection_search_items()
        total=len(items);indexed_at=G['utcnow_iso']()
        _v124_runtime_update(stage='Building Search Index',current=0,total=total,message=f'Indexing {total:,} media items…')
        if progress_cb:progress_cb('Building Search Index',0,total,f'Indexing {total:,} media items…')
        rows=[]
        tick=max(1,min(250,total//200 if total else 1))
        for idx,item in enumerate(items,1):
            payload=_v124_safe_payload(item)
            uid=str(item.get('uid') or f"{item.get('source_type')}:{item.get('library_id') or item.get('plex_library_id')}:{item.get('id') or item.get('rating_key') or item.get('external_id')}")
            text=_v124_search_text(item)
            years=sorted(_smart_years(item));search_year=(G['safe_int'](item.get('search_year')) or (years[0] if years else None))
            rows.append((uid,str(item.get('source_type') or ''),str(item.get('media_kind') or item.get('media_type') or ''),search_year,G['safe_float'](item.get('duration')),str(item.get('added_at') or '') or None,G['safe_int'](item.get('bit_depth')),G['safe_int'](item.get('chapter_count')) or 0,G['safe_int'](item.get('video_width')),G['safe_int'](item.get('video_height')),str(item.get('dynamic_range') or '') or None,text,json.dumps(payload,ensure_ascii=False,default=str,separators=(',',':')),indexed_at))
            if idx==total or idx%tick==0:
                msg=f'{idx:,} / {total:,} items prepared for the search index'
                _v124_runtime_update(current=idx,total=total,message=msg)
                if progress_cb:progress_cb('Building Search Index',idx,total,msg)
        with G['db']() as conn:
            fts_enabled=int(conn.execute('SELECT fts_enabled FROM search_index_state WHERE id=1').fetchone()['fts_enabled'] or 0)
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM search_index_items')
            if fts_enabled:
                conn.execute('DELETE FROM search_index_fts')
            conn.executemany('''INSERT INTO search_index_items
              (uid,source_type,media_kind,search_year,duration,added_at,bit_depth,chapter_count,video_width,video_height,dynamic_range,search_text,payload_json,indexed_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',rows)
            if fts_enabled:
                # Keep high-value identity fields in their own FTS columns so
                # bm25 can rank title/person matches above incidental metadata.
                fts_rows=[]
                for dbrow,payload_tuple in zip(conn.execute('SELECT id,uid,payload_json,search_text FROM search_index_items ORDER BY id').fetchall(),rows):
                    try:p=json.loads(str(dbrow['payload_json'] or '{}'))
                    except Exception:p={}
                    title=' '.join(x for x in [str(p.get('title') or ''),str(p.get('episode_title') or '')] if x)
                    show=str(p.get('show_title') or '')
                    people=' '.join(str(v) for key in ('actors','directors','writers','artist') for v in (p.get(key) if isinstance(p.get(key),list) else [p.get(key)]) if v)
                    fts_rows.append((int(dbrow['id']),str(dbrow['uid']),title,show,people,str(dbrow['search_text'] or '')))
                conn.executemany('INSERT INTO search_index_fts(rowid,uid,title,show_title,people,search_text) VALUES(?,?,?,?,?,?)',fts_rows)
            current_version=int(conn.execute('SELECT change_version FROM search_index_state WHERE id=1').fetchone()['change_version'] or 0)
            dirty=1 if current_version>target_version else 0
            conn.execute('''UPDATE search_index_state
                            SET ready=1,dirty=?,building=0,built_version=?,item_count=?,built_at=?,reason=?,error=NULL,index_version=?
                            WHERE id=1''',(dirty,target_version,total,indexed_at,str(reason)[:240],_V124_INDEX_VERSION))
            conn.commit()
        _v124_runtime_update(building=False,stage='Ready',current=total,total=total,message=f'{total:,} items indexed',reason=reason)
        result=_v124_index_state()
        if int(result.get('dirty') or 0):_v124_schedule_index_rebuild('Media changed during index build',delay=5.0)
        return result
    except Exception as exc:
        try:
            with G['db']() as conn:
                conn.execute('UPDATE search_index_state SET building=0,error=?,dirty=1 WHERE id=1',(str(exc)[:1000],));conn.commit()
        except Exception:pass
        _v124_runtime_update(building=False,stage='Failed',message=str(exc)[:500])
        raise
    finally:
        _V124_INDEX_BUILD_LOCK.release()


def _v124_fts_expression(query: str) -> str:
    clauses=[]
    for raw in _smart_query_terms(query):
        raw=str(raw or '').strip()
        if not raw:continue
        norm_words=re.findall(r'[a-z0-9]+',_smart_norm(raw))
        compact=_smart_compact(raw)
        yrange=re.fullmatch(r'((?:18|19|20|21)\d{2})\s*[-–—]\s*((?:18|19|20|21)\d{2})',raw)
        if yrange:
            lo,hi=map(int,yrange.groups());lo,hi=min(lo,hi),max(lo,hi)
            if hi-lo<=40:
                clauses.append('('+' OR '.join(str(y) for y in range(lo,hi+1))+')')
                continue
        decade=re.fullmatch(r'((?:18|19|20|21)\d)0s',compact)
        if decade:
            clauses.append(str(int(decade.group(1))*10)+'s');continue
        short_decade=re.fullmatch(r'(\d{2})s',compact)
        if short_decade:
            yy=int(short_decade.group(1));clauses.append(str(1900+yy if yy>=30 else 2000+yy)+'s');continue
        # Punctuation-heavy names such as M*A*S*H and Three's are indexed with
        # compact aliases. Prefix matching also keeps partial-name searches useful.
        if compact and re.search(r'[^A-Za-z0-9\s]',raw) and len(compact)>=2:
            clauses.append(compact+('*' if len(compact)>=3 else ''));continue
        if len(norm_words)>1:
            clauses.append('"'+' '.join(norm_words).replace('"','')+'"')
        elif norm_words:
            token=norm_words[0].replace('"','');clauses.append(token+('*' if len(token)>=3 else ''))
        elif compact:
            clauses.append(compact+('*' if len(compact)>=3 else ''))
    return ' AND '.join(clauses)


def _v124_load_index_payload_rows(query: str, advanced: bool) -> list[sqlite3.Row]:
    with G['db']() as conn:
        st=conn.execute('SELECT fts_enabled FROM search_index_state WHERE id=1').fetchone();fts_enabled=int(st['fts_enabled'] or 0) if st else 0
        if not advanced and fts_enabled:
            expr=_v124_fts_expression(query)
            if expr:
                try:
                    return conn.execute('''SELECT si.payload_json,si.id
                                           FROM search_index_fts f
                                           JOIN search_index_items si ON si.id=f.rowid
                                           WHERE search_index_fts MATCH ?''',(expr,)).fetchall()
                except sqlite3.Error:
                    pass
        if not advanced:
            terms=[_smart_norm(x) for x in _smart_query_terms(query) if _smart_norm(x)]
            if terms:
                where=' AND '.join('search_text LIKE ?' for _ in terms)
                return conn.execute(f'SELECT payload_json,id FROM search_index_items WHERE {where}',[f'%{t}%' for t in terms]).fetchall()
        return conn.execute('SELECT payload_json,id FROM search_index_items').fetchall()


def _v124_indexed_search(query: str, limit: int|None=None, progress_cb=None) -> tuple[list[dict[str,Any]],int,int]:
    q=str(query or '').strip();advanced=_smart_is_advanced(q)
    # Interactive natural searches only need the best 500 display results. Let
    # FTS5 count all matches in SQL, then rank a bounded high-quality candidate
    # window instead of JSON-decoding tens of thousands of broad matches. Smart
    # Collections (limit=None) still expand every indexed match.
    if not advanced and limit:
        expr=_v124_fts_expression(q)
        with G['db']() as conn:
            st=conn.execute('SELECT fts_enabled FROM search_index_state WHERE id=1').fetchone();fts_enabled=int(st['fts_enabled'] or 0) if st else 0
            if fts_enabled and expr:
                try:
                    match_count=int(conn.execute('SELECT COUNT(*) c FROM search_index_fts WHERE search_index_fts MATCH ?',(expr,)).fetchone()['c'] or 0)
                    fetch_limit=min(max(int(limit)*6,2000),10000)
                    rows=conn.execute('''SELECT si.payload_json,si.id,
                                                bm25(search_index_fts,0.0,12.0,10.0,8.0,1.0) AS fts_rank
                                         FROM search_index_fts f
                                         JOIN search_index_items si ON si.id=f.rowid
                                         WHERE search_index_fts MATCH ?
                                         ORDER BY fts_rank
                                         LIMIT ?''',(expr,fetch_limit)).fetchall()
                except sqlite3.Error:
                    rows=[];match_count=-1
                if match_count>=0:
                    found=[];scanned=len(rows);tick=max(1,min(250,scanned//50 if scanned else 1))
                    for idx,row in enumerate(rows,1):
                        try:item=json.loads(str(row['payload_json'] or '{}'))
                        except Exception:continue
                        try:ok=_smart_natural_match(item,q)
                        except Exception:ok=False
                        if ok:found.append(item)
                        if progress_cb and (idx==scanned or idx%tick==0):progress_cb(idx,scanned,min(match_count,len(found)))
                    found.sort(key=lambda x:(-_smart_relevance(x,q),str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
                    # If post-filter semantics removed too many of the bounded FTS
                    # candidates, fall through to the exhaustive indexed path.
                    if len(found)>=min(int(limit),match_count) or match_count<=scanned:
                        out=found[:int(limit)];_v124_rehydrate_runtime_fields(out);return out,match_count,match_count
    rows=_v124_load_index_payload_rows(q,advanced);candidate_total=len(rows)
    pred=G['_compile_search_query'](q) if advanced else None
    found=[];matches=0;tick=max(1,min(500,candidate_total//100 if candidate_total else 1))
    for idx,row in enumerate(rows,1):
        try:item=json.loads(str(row['payload_json'] or '{}'))
        except Exception:continue
        try:ok=bool(pred(item)) if advanced else _smart_natural_match(item,q)
        except Exception:ok=False
        if ok:
            matches+=1;found.append(item)
        if progress_cb and (idx==candidate_total or idx%tick==0):progress_cb(idx,candidate_total,matches)
    if advanced:
        found.sort(key=lambda x:(str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    else:
        found.sort(key=lambda x:(-_smart_relevance(x,q),str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1,str(x.get('title') or '').casefold()))
    if limit:found=found[:limit]
    _v124_rehydrate_runtime_fields(found)
    return found,matches,candidate_total


_v124_smart_media_search_playable_v123 = smart_media_search_playable


def smart_media_search_playable(query:str,limit:int|None=None)->list[dict[str,Any]]:
    q=str(query or '').strip()
    if not q:return G['_media_power_base_media_search_playable'](q,limit)
    if _v124_index_ready():
        try:return _v124_indexed_search(q,limit)[0]
        except Exception:pass
    # The index is intentionally not built synchronously from a playout thread.
    # Until the first background build completes, preserve v1.2.3 behavior.
    return _v124_smart_media_search_playable_v123(q,limit)


def _v124_search_index_card() -> str:
    e=G['e'];st=_v124_index_state();ready=bool(int(st.get('ready') or 0));dirty=bool(int(st.get('dirty') or 0));building=bool(int(st.get('building') or 0));count=int(st.get('item_count') or 0)
    if building:
        cur=int(st.get('build_current') or 0);total=int(st.get('build_total') or 0);pct=round(100*cur/max(1,total)) if total else 0
        status=f"Updating · {cur:,} / {total:,}" if total else 'Preparing index…'
        bar=f"<div class='progress'><span style='width:{pct}%'></span></div>"
    elif ready and dirty:
        status=f'Ready · {count:,} items · refresh queued';bar=''
    elif ready:
        status=f'Ready · {count:,} indexed items';bar=''
    else:
        status='Index build required';bar=''
    built=str(st.get('built_at') or '')[:19].replace('T',' ')
    err=str(st.get('error') or '')
    note=(f"Last built {e(built)}." if built else 'The first build runs once in the background. Searches become fast after it completes.')
    if dirty and ready:note+=' Searches continue using the current index while the refresh is built.'
    return f"""<div class='card' id='search-index-card'><div class='page-heading'><div><h2>Indexed Search</h2><p class='muted'>{e(status)}</p></div><form method='post' action='/media/search/rebuild-index'><button class='secondary'>Rebuild Search Index</button></form></div>{bar}<p class='small muted'>{note}</p>{('<p class=\'small\' style=\'color:#ff9da4\'>'+e(err)+'</p>') if err else ''}</div>"""


_v124_media_search_page_v123 = media_search_page


def media_search_page(q:str='',msg:str='')->str:
    q=(q or '').strip()
    if not q:
        e=G['e'];notice=f"<div class='msg'>{e(msg)}</div>" if msg else ''
        body=notice+G['_page_heading']('Search','Smart indexed search — type a person, title, year, genre, network or anything you remember.')+f"""<div class='card'><form method='get' action='/media/search'><label>Search</label><div class='grid'><input name='q' value='' autofocus placeholder='John Ritter, M*A*S*H, 1984, comedy, NBC, 4K HDR...'><div class='toolbar'><button>Search</button><a class='button secondary' href='/media/search'>Clear</a></div></div></form><p class='small muted'>No field names required. Normal searches use ViperTV's persistent SQLite index instead of rebuilding the catalog every time.</p><details><summary>Advanced search help (optional)</summary><p class='small muted'>{_search_help_text()}</p></details></div>{_v124_search_index_card()}"""
        return G['page_shell']('Search',body)
    return _v124_media_search_page_v123(q,msg)


_v124_wrap_scan_library_v123 = _wrap_scan_library
_v124_wrap_sync_plex_v123 = _wrap_sync_plex
_v124_wrap_sync_external_v123 = _wrap_sync_external


def _wrap_scan_library(base):
    wrapped=_v124_wrap_scan_library_v123(base)
    def scan(library_id:int):
        result=wrapped(library_id);_v124_mark_index_dirty(f'Local library {library_id} scanned');_v124_schedule_index_rebuild('Local library scan completed',delay=8.0);return result
    return scan


def _wrap_sync_plex(base):
    wrapped=_v124_wrap_sync_plex_v123(base)
    def sync(library_id:int):
        result=wrapped(library_id);_v124_mark_index_dirty(f'Plex library {library_id} synced');_v124_schedule_index_rebuild('Plex sync completed',delay=12.0);return result
    return sync


def _wrap_sync_external(base):
    wrapped=_v124_wrap_sync_external_v123(base)
    def sync(library_id:int):
        result=wrapped(library_id);_v124_mark_index_dirty(f'External library {library_id} synced');_v124_schedule_index_rebuild('Jellyfin / Emby sync completed',delay=12.0);return result
    return sync


def _v124_wrap_metadata_mutator(base,reason:str):
    def wrapped(*args,**kwargs):
        result=base(*args,**kwargs);_v124_mark_index_dirty(reason);_v124_schedule_index_rebuild(reason,delay=10.0);return result
    return wrapped


def _run_search_job(job_id:str,query:str) -> None:
    try:
        def build_progress(stage,current,total,message):
            if total:
                pct=5+(68*current/max(1,total))
            else:pct=5
            _search_job_update(job_id,state='running',stage=stage,message=message,percent=round(min(73,pct),1),current=current,total=total,matches=0)
        st=_v124_index_state()
        if not int(st.get('ready') or 0):
            _search_job_update(job_id,state='running',stage='Building Search Index',message='This one-time index build makes future searches much faster…',percent=4,current=0,total=int(st.get('build_total') or 0),matches=0)
            _v124_rebuild_search_index('First indexed search',build_progress)
        elif int(st.get('dirty') or 0) and not int(st.get('building') or 0):
            # Do not block the search on a refresh. Existing committed index rows
            # remain valid while a fresh generation is built in the background.
            _v124_schedule_index_rebuild('Refreshing search index',delay=1.0)
        st=_v124_index_state();idx_count=int(st.get('item_count') or 0)
        _search_job_update(job_id,state='running',stage='Searching index',message=f'Querying {idx_count:,} indexed media items…',percent=80,current=0,total=0,matches=0)
        def search_progress(current,total,matches):
            pct=80+(17*current/max(1,total)) if total else 95
            _search_job_update(job_id,current=current,total=total,matches=matches,percent=round(min(97,pct),1),message=f'{current:,} / {total:,} indexed candidates checked · {matches:,} match'+('es' if matches!=1 else ''))
        results,match_count,candidates=_v124_indexed_search(query,500,search_progress)
        _search_job_update(job_id,stage='Ranking results',message=f'Ranking {match_count:,} match'+('es' if match_count!=1 else '')+'…',percent=98,current=candidates,total=candidates,matches=match_count)
        _search_job_update(job_id,state='done',stage='Complete',message=f'{match_count:,} match'+('es' if match_count!=1 else '')+f' found · showing up to {len(results):,}',percent=100,current=candidates,total=candidates,matches=match_count,results=results,finished=time.time(),indexed=True,index_items=idx_count)
    except Exception as exc:
        # Index failures must not make Search unusable. Fall back to the proven
        # v1.2.3 worker for this request and preserve the error in index state.
        try:
            _search_job_update(job_id,stage='Indexed search unavailable',message='Falling back to catalog search for this request…',percent=5)
            items=collection_search_items();total=len(items);advanced=_smart_is_advanced(query);pred=G['_compile_search_query'](query) if advanced else None;found=[];match_count=0
            tick=max(1,min(250,total//250 if total else 1))
            for idx,x in enumerate(items,1):
                try:ok=bool(pred(x)) if advanced else _smart_natural_match(x,query)
                except Exception:ok=False
                if ok:match_count+=1;found.append(x)
                if idx==total or idx%tick==0:_search_job_update(job_id,current=idx,total=total,matches=match_count,percent=5+90*idx/max(1,total),message=f'{idx:,} / {total:,} items checked')
            found.sort(key=lambda x:(-_smart_relevance(x,query) if not advanced else 0,str(x.get('show_title') or x.get('title') or '').casefold(),G['safe_int'](x.get('season_number')) or -1,G['safe_int'](x.get('episode_number')) or -1))
            _search_job_update(job_id,state='done',stage='Complete (fallback)',message=f'{match_count:,} matches found',percent=100,current=total,total=total,matches=match_count,results=found[:500],finished=time.time(),indexed=False,index_error=str(exc)[:500])
        except Exception as exc2:
            _search_job_update(job_id,state='error',stage='Search failed',message=str(exc2)[:500],percent=100,error=str(exc2)[:1000],finished=time.time())


def _v124_install_index_routes(app) -> None:
    @app.get('/api/media/search/index-status')
    def media_search_index_status():
        return _v124_index_state()

    @app.post('/media/search/rebuild-index')
    def media_search_rebuild_index():
        _v124_mark_index_dirty('Manual rebuild requested')
        _v124_schedule_index_rebuild('Manual rebuild requested',delay=0.05)
        return RedirectResponse('/media/search?msg='+G['quote']('Search index rebuild started in the background.'),303)


# Reinstall the v1.2.x integration using the v1.2.4 wrappers above. This second
# definition intentionally supersedes the v1.2.3 installer earlier in this file.
def install_media_power(app,main_globals:dict[str,Any])->None:
    global G;G=main_globals
    base_init=G['init_v12_db']
    def init_all():
        base_init();init_media_power_db();_v124_schedule_index_rebuild('Startup index check',delay=2.0)
    G['init_v12_db']=init_all

    G['_media_power_base_collection_search_items']=G['_collection_search_items'];G['_media_power_base_search_atom']=G['_search_atom'];G['_media_power_base_media_search_playable']=G['media_search_playable'];G['_media_power_base_selection_items']=G['_selection_items'];G['_media_power_base_item_selection_token']=G['_item_selection_token'];G['_media_power_base_selection_description']=G['_selection_description'];G['_media_power_base_local_command']=G['_profiled_local_command']
    G['_collection_search_items']=collection_search_items;G['_search_atom']=search_atom;G['media_search_playable']=smart_media_search_playable;G['_selection_items']=selection_items;G['_item_selection_token']=item_selection_token;G['_selection_description']=selection_description;G['playlist_media']=playlist_media;G['playlists_index_page']=playlists_index_page;G['playlist_edit_page']=playlist_edit_page;G['media_search_page']=media_search_page;G['_profiled_local_command']=local_command
    G['VIDEO_EXTS']=set(G.get('VIDEO_EXTS') or set())|AUDIO_EXTS|IMAGE_EXTS
    G['scan_library']=_wrap_scan_library(G['scan_library']);G['sync_plex_library']=_wrap_sync_plex(G['sync_plex_library']);G['sync_external_library']=_wrap_sync_external(G['sync_external_library'])
    for name,reason in [('enrich_tvdb_metadata','TheTVDB metadata changed'),('enrich_plex_episode_credits','Plex rich credits changed'),('enrich_all_local_metadata','Local metadata changed')]:
        if callable(G.get(name)):G[name]=_v124_wrap_metadata_mutator(G[name],reason)
    _routes(app);_v124_install_index_routes(app)
