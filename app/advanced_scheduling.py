from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
from datetime import datetime, timezone, time as dt_time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import yaml
from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

G: dict[str, Any] = {}
BLOCK_DAY_CACHE: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
SEQUENTIAL_DAY_CACHE: dict[tuple[Any, ...], list[dict[str, Any]]] = {}


def install_advanced_scheduling(app, main_globals: dict[str, Any]) -> None:
    """Install ViperTV v1.2 advanced scheduling without disturbing the proven stream core."""
    global G
    G = main_globals
    _install_routes(app)
    # Existing route /scheduling/blocks resolves this global at request time.
    G['blocks_index_page'] = blocks_index_page

    base_channel_media = G['channel_media']
    base_scheduled_cursor = G['_scheduled_cursor']
    base_local_command = G['_profiled_local_command']
    base_plex_command = G['_profiled_plex_part_command']
    base_external_command = G['_profiled_external_command']
    base_plex_universal = G.get('plex_ffmpeg_command')

    def _tag_channel(items, channel_id):
        tagged = []
        for raw in items:
            x = dict(raw)
            x['_v12_channel_id'] = int(channel_id)
            tagged.append(x)
        return tagged

    def channel_media_v12(channel_id: int):
        ch, base_items = base_channel_media(channel_id)
        seq = sequential_day_items(channel_id)
        if seq:
            return ch, _tag_channel(seq, channel_id)
        block = block_day_items(channel_id)
        if block:
            return ch, _tag_channel(block, channel_id)
        # Classic schedules remain the normal v1.1.46 engine. v1.2 adds
        # preset filler and graphics as a post-processing layer.
        if any(x.get('_classic_schedule_item_id') for x in base_items):
            base_items = _apply_classic_extras(base_items)
            _set_cycle_anchor(base_items)
        return ch, _tag_channel(base_items, channel_id)

    def scheduled_cursor_v12(channel_id: int):
        ass = _sequential_assignment(channel_id)
        if ass:
            key = f"sequential:{ass['schedule_id']}:{ass['generation']}"
            with G['db']() as conn:
                r = conn.execute('SELECT cursor FROM playout_state WHERE channel_id=? AND source_key=?', (channel_id, key)).fetchone()
            return key, int(r['cursor']) if r else 0
        ass = _block_assignment(channel_id)
        if ass:
            key = f"block:{ass['template_id']}:{ass['generation']}"
            with G['db']() as conn:
                r = conn.execute('SELECT cursor FROM playout_state WHERE channel_id=? AND source_key=?', (channel_id, key)).fetchone()
            return key, int(r['cursor']) if r else 0
        return base_scheduled_cursor(channel_id)

    def local_command_v12(channel, item, offset, profile_override=None):
        item.pop('_actual_stream_profile', None)
        if _item_needs_advanced_graphics(channel, item) or float(item.get('_segment_start') or 0) > 0:
            return _advanced_local_command(channel, item, offset, profile_override)
        return base_local_command(channel, item, offset, profile_override)

    def plex_command_v12(channel, item, offset, url, headers, profile_override=None):
        item.pop('_actual_stream_profile', None)
        if _item_needs_advanced_graphics(channel, item) or float(item.get('_segment_start') or 0) > 0:
            return _advanced_plex_command(channel, item, offset, url, headers, profile_override)
        return base_plex_command(channel, item, offset, url, headers, profile_override)

    def external_command_v12(channel, item, offset):
        if _item_needs_advanced_graphics(channel, item) or float(item.get('_segment_start') or 0) > 0:
            return _advanced_external_command(channel, item, offset)
        return base_external_command(channel, item, offset)

    def plex_universal_v12(item, offset):
        # The normal producer prefers the direct Plex Media/Part source. If it
        # has to fall back to Plex's universal transcoder, preserve v1.2 segment
        # offsets and branding instead of replaying split programmes from zero.
        segment_start = float(item.get('_segment_start') or 0)
        cid = item.get('_v12_channel_id')
        if cid:
            with _db() as conn:
                channel = conn.execute('SELECT * FROM channels WHERE id=?', (int(cid),)).fetchone()
            if channel and (_item_needs_advanced_graphics(channel, item) or segment_start > 0):
                actual = max(0.0, float(offset or 0) + segment_start)
                url = G['plex_transcode_url'](item, actual)
                clone = dict(item); clone['_segment_start'] = 0
                return _advanced_media_command(channel, clone, 0.0, ['-i', url])
        if base_plex_universal:
            return base_plex_universal(item, max(0.0, float(offset or 0) + segment_start))
        return ['false']

    # Add a commercial/graphics entry point to the existing Classic item editor
    # without rewriting the proven v1.1.46 form. Existing routes resolve this
    # global at request time.
    base_classic_item_form = G.get('_classic_item_form')
    if base_classic_item_form:
        def classic_item_form_v12(schedule_id, item=None):
            html = base_classic_item_form(schedule_id, item)
            if item is not None:
                try:
                    iid = int(item['id'])
                    html += (f"<hr><div class='toolbar'><a class='button secondary' "
                             f"href='/scheduling/classic-item/{iid}/extras'>Commercials / Filler & Graphics</a></div>")
                except Exception:
                    pass
            return html
        G['_classic_item_form'] = classic_item_form_v12

    G['channel_media'] = channel_media_v12
    G['_scheduled_cursor'] = scheduled_cursor_v12
    G['_profiled_local_command'] = local_command_v12
    G['_profiled_plex_part_command'] = plex_command_v12
    G['_profiled_external_command'] = external_command_v12
    G['plex_ffmpeg_command'] = plex_universal_v12


def _db():
    return G['db']()


def _e(v: Any) -> str:
    return G['e'](v)


def _page(title: str, body: str) -> str:
    return G['page_shell'](title, body)


def _heading(title: str, subtitle: str, actions: str = '') -> str:
    return G['_page_heading'](title, subtitle, actions)


def _now() -> str:
    return G['utcnow_iso']()


def init_v12_db() -> None:
    """Additive v1.2 schema. Never drops or rewrites existing user data."""
    if not G:
        return
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS graphics_elements(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              kind TEXT NOT NULL DEFAULT 'image',
              image_path TEXT,
              text_template TEXT,
              location TEXT NOT NULL DEFAULT 'BottomRight',
              horizontal_margin_percent REAL NOT NULL DEFAULT 3,
              vertical_margin_percent REAL NOT NULL DEFAULT 3,
              scale_width_percent REAL NOT NULL DEFAULT 12,
              opacity_percent REAL NOT NULL DEFAULT 100,
              font_size INTEGER NOT NULL DEFAULT 32,
              text_color TEXT NOT NULL DEFAULT 'white',
              box_enabled INTEGER NOT NULL DEFAULT 0,
              start_seconds REAL NOT NULL DEFAULT 0,
              end_seconds REAL,
              z_index INTEGER NOT NULL DEFAULT 1,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS channel_graphics(
              channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
              graphic_id INTEGER NOT NULL REFERENCES graphics_elements(id) ON DELETE CASCADE,
              scope TEXT NOT NULL DEFAULT 'all',
              PRIMARY KEY(channel_id,graphic_id)
            );

            CREATE TABLE IF NOT EXISTS blocks(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              duration_minutes INTEGER NOT NULL DEFAULT 30,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS block_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
              position INTEGER NOT NULL DEFAULT 0,
              source_kind TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              playback_order TEXT NOT NULL DEFAULT 'chronological',
              show_in_epg INTEGER NOT NULL DEFAULT 1,
              disable_watermarks INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_block_items_position ON block_items(block_id,position,id);
            CREATE TABLE IF NOT EXISTS block_item_fillers(
              block_item_id INTEGER NOT NULL REFERENCES block_items(id) ON DELETE CASCADE,
              filler_id INTEGER NOT NULL REFERENCES filler_presets(id) ON DELETE CASCADE,
              PRIMARY KEY(block_item_id,filler_id)
            );
            CREATE TABLE IF NOT EXISTS block_item_graphics(
              block_item_id INTEGER NOT NULL REFERENCES block_items(id) ON DELETE CASCADE,
              graphic_id INTEGER NOT NULL REFERENCES graphics_elements(id) ON DELETE CASCADE,
              PRIMARY KEY(block_item_id,graphic_id)
            );
            CREATE TABLE IF NOT EXISTS decos(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              watermark_mode TEXT NOT NULL DEFAULT 'inherit',
              watermark_graphic_id INTEGER REFERENCES graphics_elements(id) ON DELETE SET NULL,
              use_watermark_during_filler INTEGER NOT NULL DEFAULT 0,
              default_filler_mode TEXT NOT NULL DEFAULT 'inherit',
              default_filler_id INTEGER REFERENCES filler_presets(id) ON DELETE SET NULL,
              trim_to_fit INTEGER NOT NULL DEFAULT 1,
              dead_air_mode TEXT NOT NULL DEFAULT 'inherit',
              dead_air_filler_id INTEGER REFERENCES filler_presets(id) ON DELETE SET NULL,
              graphics_ids_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS block_templates(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS block_template_slots(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              template_id INTEGER NOT NULL REFERENCES block_templates(id) ON DELETE CASCADE,
              day_mask INTEGER NOT NULL DEFAULT 127,
              start_minute INTEGER NOT NULL,
              block_id INTEGER NOT NULL REFERENCES blocks(id) ON DELETE CASCADE,
              deco_id INTEGER REFERENCES decos(id) ON DELETE SET NULL,
              position INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_block_template_slots ON block_template_slots(template_id,start_minute,position,id);
            CREATE TABLE IF NOT EXISTS block_playouts(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              template_id INTEGER NOT NULL REFERENCES block_templates(id) ON DELETE CASCADE,
              default_deco_id INTEGER REFERENCES decos(id) ON DELETE SET NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              generation INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sequential_schedules(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              yaml_text TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sequential_playouts(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              schedule_id INTEGER NOT NULL REFERENCES sequential_schedules(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL DEFAULT 1,
              generation INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        add = G['add_column_if_missing']
        for col, ddl in [
            ('collection_id', 'INTEGER REFERENCES collections(id) ON DELETE SET NULL'),
            ('filler_kind', "TEXT NOT NULL DEFAULT 'postroll'"),
            ('fill_mode', "TEXT NOT NULL DEFAULT 'count'"),
            ('count_items', 'INTEGER NOT NULL DEFAULT 1'),
            ('duration_seconds', 'INTEGER NOT NULL DEFAULT 120'),
            ('pad_minutes', 'INTEGER NOT NULL DEFAULT 30'),
            ('trim_to_fit', 'INTEGER NOT NULL DEFAULT 1'),
            ('midroll_breaks', 'INTEGER NOT NULL DEFAULT 1'),
        ]:
            add(conn, 'filler_presets', col, ddl)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS classic_item_fillers(
              schedule_item_id INTEGER NOT NULL REFERENCES classic_schedule_items(id) ON DELETE CASCADE,
              filler_id INTEGER NOT NULL REFERENCES filler_presets(id) ON DELETE CASCADE,
              PRIMARY KEY(schedule_item_id,filler_id)
            );
            CREATE TABLE IF NOT EXISTS classic_item_graphics(
              schedule_item_id INTEGER NOT NULL REFERENCES classic_schedule_items(id) ON DELETE CASCADE,
              graphic_id INTEGER NOT NULL REFERENCES graphics_elements(id) ON DELETE CASCADE,
              PRIMARY KEY(schedule_item_id,graphic_id)
            );
            """
        )
        conn.commit()


# ------------------------------ utilities ---------------------------------

def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(str(G.get('DEFAULT_TIMEZONE') or 'UTC'))
    except Exception:
        return ZoneInfo('UTC')


def _day_anchor(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    today = datetime.now(_tz()).date()
    items[0]['_cycle_anchor_utc'] = datetime.combine(today, dt_time(0, 0), tzinfo=_tz()).astimezone(timezone.utc).isoformat()


def _set_cycle_anchor(items: list[dict[str, Any]]) -> None:
    if items and not items[0].get('_cycle_anchor_utc'):
        _day_anchor(items)


def _gap(seconds: float, label: str = 'Off Air', hidden: bool = False) -> dict[str, Any]:
    return {
        'source_type': 'gap', 'uid': f'v12-gap:{hashlib.sha1(f"{seconds}|{label}|{random.random()}".encode()).hexdigest()}',
        'title': label, 'duration': max(1.0, float(seconds)), '_guide_hidden': hidden,
        '_guide_custom_title': label, 'summary': 'Unscheduled time'
    }


def _hm_to_min(value: str) -> int:
    return G['_hm_to_min'](value)


def _min_to_hm(value: int) -> str:
    return G['_min_to_hm'](value)


def _daymask(days: list[str]) -> int:
    mask = 0
    for d in days:
        try:
            n = int(d)
            if 0 <= n <= 6:
                mask |= 1 << n
        except Exception:
            pass
    return mask or 127


def _source_options(selected_kind: str = '', selected_ref: str = '') -> str:
    return G['_classic_source_options'](selected_kind, selected_ref)


def _source_label(kind: str, ref: str) -> str:
    return G['_classic_source_label'](kind, ref)


def _source_items(kind: str, ref: str) -> list[dict[str, Any]]:
    class Row(dict):
        __getattr__ = dict.get
    try:
        return G['_classic_source_items'](Row(source_kind=kind, source_ref=ref))
    except Exception:
        if kind in ('collection', 'smart_collection', 'multi_collection'):
            return G['collection_media'](int(ref))
        if kind == 'playlist':
            return G['playlist_media'](int(ref))
        if kind in ('tv_show', 'tv_season'):
            return G['_selection_items'](ref)
        return []


def _order_pool(items: list[dict[str, Any]], order: str, seed: str) -> list[dict[str, Any]]:
    return G['_classic_order_pool'](items, order, seed)


def _collection_by_name(name: str):
    with _db() as conn:
        return conn.execute('SELECT * FROM collections WHERE name=? COLLATE NOCASE', (name.strip(),)).fetchone()


def _playlist_by_name(name: str):
    with _db() as conn:
        return conn.execute('SELECT * FROM playlists WHERE name=? COLLATE NOCASE', (name.strip(),)).fetchone()


def _graphic_by_name(name: str):
    with _db() as conn:
        return conn.execute('SELECT * FROM graphics_elements WHERE name=? COLLATE NOCASE AND enabled=1', (name.strip(),)).fetchone()


def _graphics_names_to_ids(names: list[str]) -> list[int]:
    ids: list[int] = []
    with _db() as conn:
        for name in names:
            row = conn.execute('SELECT id FROM graphics_elements WHERE name=? COLLATE NOCASE AND enabled=1', (str(name).strip(),)).fetchone()
            if row:
                ids.append(int(row['id']))
    return ids


# --------------------------- filler engine --------------------------------

def _filler_presets_for(kind: str, assoc_id: int) -> list[sqlite3.Row]:
    table = 'classic_item_fillers' if kind == 'classic' else 'block_item_fillers'
    key = 'schedule_item_id' if kind == 'classic' else 'block_item_id'
    with _db() as conn:
        return conn.execute(
            f'''SELECT fp.* FROM {table} x JOIN filler_presets fp ON fp.id=x.filler_id
                WHERE x.{key}=? AND fp.enabled=1 ORDER BY fp.id''', (assoc_id,)
        ).fetchall()


def _filler_media(preset: sqlite3.Row, seed: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        if preset['collection_id']:
            items = G['collection_media'](int(preset['collection_id']))
        elif preset['library_id']:
            with _db() as conn:
                items = [{**dict(r), 'source_type': 'local', 'air_date': None}
                         for r in conn.execute('SELECT * FROM media WHERE library_id=? AND duration>0 ORDER BY id', (int(preset['library_id']),))]
    except Exception:
        items = []
    items = [dict(x) for x in items if float(x.get('duration') or 0) > 0]
    items.sort(key=lambda x: hashlib.sha256(f"{seed}|{x.get('uid')}|{x.get('id')}|{x.get('rating_key')}|{x.get('external_id')}".encode()).hexdigest())
    return items


def _mark_filler(item: dict[str, Any], kind: str) -> dict[str, Any]:
    x = dict(item)
    x['_guide_hidden'] = True
    x['_filler_kind'] = kind
    x['_schedule_label'] = kind.replace('roll', '-roll').title()
    return x


def _clip_fill(preset: sqlite3.Row, seed: str, budget: float | None = None) -> list[dict[str, Any]]:
    pool = _filler_media(preset, seed)
    if not pool:
        return []
    mode = str(preset['fill_mode'] or 'count')
    out: list[dict[str, Any]] = []
    if mode == 'count':
        count = max(1, int(preset['count_items'] or preset['max_items'] or 1))
        spent = 0.0
        for i in range(count):
            src = pool[i % len(pool)]
            dur = max(1.0, float(src.get('duration') or 0))
            if budget is not None:
                remaining = max(0.0, budget - spent)
                if remaining <= 0.5:
                    break
                if dur > remaining + 0.5:
                    if preset['trim_to_fit']:
                        x = _mark_filler(src, str(preset['filler_kind']))
                        x['_source_duration'] = dur
                        x['_trim_limit'] = remaining
                        x['duration'] = remaining
                        out.append(x)
                    break
            out.append(_mark_filler(src, str(preset['filler_kind'])))
            spent += dur
        return out
    target = float(preset['duration_seconds'] or 120)
    if budget is not None:
        target = max(0.0, min(target if mode == 'duration' else budget, budget))
    if mode == 'pad' and budget is not None:
        target = max(0.0, budget)
    spent = 0.0
    i = 0
    max_iter = max(20, len(pool) * 4)
    while i < max_iter and spent < target - 0.5:
        src = pool[i % len(pool)]
        dur = max(1.0, float(src.get('duration') or 0))
        remaining = target - spent
        if dur <= remaining + 0.5:
            out.append(_mark_filler(src, str(preset['filler_kind'])))
            spent += dur
        elif preset['trim_to_fit'] and remaining > 0.5:
            x = _mark_filler(src, str(preset['filler_kind']))
            x['_source_duration'] = dur
            x['_trim_limit'] = remaining
            x['duration'] = remaining
            out.append(x)
            spent += remaining
            break
        i += 1
    return out


def _split_midroll(item: dict[str, Any], preset: sqlite3.Row, seed: str) -> list[dict[str, Any]]:
    duration = max(1.0, float(item.get('duration') or 0))
    breaks = max(1, min(8, int(preset['midroll_breaks'] or 1)))
    # Don't shred very short clips into ad breaks.
    if duration < 300 or duration / (breaks + 1) < 120:
        return [item]
    filler = _clip_fill(preset, seed)
    if not filler:
        return [item]
    seg = duration / (breaks + 1)
    out: list[dict[str, Any]] = []
    guide_total = duration + sum(float(x.get('duration') or 0) for x in filler) * breaks
    for n in range(breaks + 1):
        x = dict(item)
        x['_segment_start'] = seg * n
        x['_source_duration'] = duration
        x['_trim_limit'] = seg
        x['duration'] = seg
        if n == 0:
            x['_guide_duration'] = guide_total
        else:
            x['_guide_hidden'] = True
        out.append(x)
        if n < breaks:
            out.extend(dict(y) for y in filler)
    return out


def _decorate_with_presets(item: dict[str, Any], presets: list[sqlite3.Row], seed: str, cursor: float) -> tuple[list[dict[str, Any]], float]:
    if item.get('source_type') == 'gap':
        return [item], cursor + float(item.get('duration') or 0)
    by_kind: dict[str, list[sqlite3.Row]] = {}
    for p in presets:
        by_kind.setdefault(str(p['filler_kind'] or 'postroll'), []).append(p)
    out: list[dict[str, Any]] = []
    for p in by_kind.get('preroll', []):
        clips = _clip_fill(p, seed + '|pre')
        out.extend(clips)
        cursor += sum(float(x.get('duration') or 0) for x in clips)

    primary_parts = [dict(item)]
    for p in by_kind.get('midroll', []):
        # One mid-roll preset can create one or more breaks. If multiple are attached,
        # apply the first to avoid recursively splitting an already split programme.
        primary_parts = _split_midroll(primary_parts[0], p, seed + '|mid') if len(primary_parts) == 1 else primary_parts
        break
    out.extend(primary_parts)
    cursor += sum(float(x.get('duration') or 0) for x in primary_parts)

    for p in by_kind.get('postroll', []):
        if str(p['fill_mode']) == 'pad':
            minutes = max(1, int(p['pad_minutes'] or 30))
            target = math.ceil(cursor / (minutes * 60.0)) * minutes * 60.0
            clips = _clip_fill(p, seed + '|postpad', max(0.0, target - cursor))
        else:
            clips = _clip_fill(p, seed + '|post')
        out.extend(clips)
        cursor += sum(float(x.get('duration') or 0) for x in clips)
    return out, cursor



def _clip_to_broadcast_day(items: list[dict[str, Any]], seconds: float = 86400.0) -> list[dict[str, Any]]:
    """Return a schedule clipped to a hard broadcast-day boundary.

    Filler and commercials are real playout time, so they can shift later dynamic
    programming, but they may never make the generated day exceed its fixed
    day boundary. The final clip is trimmed only when its source is long enough.
    """
    out: list[dict[str, Any]] = []
    total = 0.0
    for raw in items:
        if total >= seconds - 0.5:
            break
        x = dict(raw)
        dur = max(1.0, float(x.get('duration') or 0))
        remain = seconds - total
        if dur > remain + 0.5:
            x['_source_duration'] = float(x.get('_source_duration') or dur)
            x['_trim_limit'] = remain
            x['duration'] = remain
            dur = remain
        out.append(x)
        total += dur
    return out

def _apply_classic_extras(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = 0.0
    previous_assoc: int | None = None
    previous_presets: list[sqlite3.Row] = []
    for idx, raw in enumerate(items):
        item = dict(raw)
        assoc = int(item.get('_classic_schedule_item_id') or 0)
        if item.get('source_type') == 'gap' and previous_assoc:
            fallback = next((p for p in previous_presets if str(p['filler_kind']) == 'fallback'), None)
            if fallback:
                budget = float(item.get('duration') or 0)
                clips = _clip_fill(fallback, f'classic|{previous_assoc}|fallback|{idx}', budget)
                spent = sum(float(x.get('duration') or 0) for x in clips)
                out.extend(clips)
                if spent < budget - 0.5:
                    out.append(_gap(budget - spent, 'Off Air'))
                cursor += budget
                continue
        presets = _filler_presets_for('classic', assoc) if assoc else []
        if assoc:
            with _db() as conn:
                gids = [int(r['graphic_id']) for r in conn.execute('SELECT graphic_id FROM classic_item_graphics WHERE schedule_item_id=?', (assoc,))]
            if gids:
                item['_graphics_ids'] = sorted(set([*item.get('_graphics_ids', []), *gids]))
        decorated, cursor = _decorate_with_presets(item, presets, f'classic|{assoc}|{idx}', cursor)
        out.extend(decorated)
        # Tail runs when this schedule-item run ends.
        next_assoc = int(items[idx + 1].get('_classic_schedule_item_id') or 0) if idx + 1 < len(items) else 0
        if assoc and next_assoc != assoc:
            for p in (x for x in presets if str(x['filler_kind']) == 'tail'):
                clips = _clip_fill(p, f'classic|{assoc}|tail|{idx}')
                out.extend(clips)
                cursor += sum(float(x.get('duration') or 0) for x in clips)
        previous_assoc, previous_presets = assoc or previous_assoc, presets or previous_presets
    return _clip_to_broadcast_day(out)


# --------------------------- graphics engine -------------------------------

def _graphics_for_item(channel, item: dict[str, Any]) -> list[sqlite3.Row]:
    ids = {int(x) for x in (item.get('_graphics_ids') or []) if str(x).isdigit()}
    filler = bool(item.get('_filler_kind') or item.get('_guide_hidden'))
    with _db() as conn:
        rows = conn.execute(
            '''SELECT ge.*,cg.scope FROM channel_graphics cg JOIN graphics_elements ge ON ge.id=cg.graphic_id
               WHERE cg.channel_id=? AND ge.enabled=1 ORDER BY ge.z_index,ge.id''', (int(channel['id']),)
        ).fetchall()
        for r in rows:
            scope = str(r['scope'] or 'all')
            if scope == 'all' or (scope == 'filler' and filler) or (scope == 'primary' and not filler):
                ids.add(int(r['id']))
        if ids:
            q = 'SELECT * FROM graphics_elements WHERE enabled=1 AND id IN (%s) ORDER BY z_index,id' % ','.join('?' * len(ids))
            explicit = conn.execute(q, tuple(sorted(ids))).fetchall()
        else:
            explicit = []
    unique: dict[int, sqlite3.Row] = {int(r['id']): r for r in explicit}
    for r in rows:
        scope = str(r['scope'] or 'all')
        if scope == 'all' or (scope == 'filler' and filler) or (scope == 'primary' and not filler):
            unique[int(r['id'])] = r
    return sorted(unique.values(), key=lambda r: (int(r['z_index'] or 0), int(r['id'])))


def _item_needs_advanced_graphics(channel, item: dict[str, Any]) -> bool:
    if item.get('_disable_watermark') or item.get('_graphics_ids') or item.get('_graphics_names'):
        return True
    try:
        with _db() as conn:
            if conn.execute('SELECT 1 FROM channel_graphics WHERE channel_id=? LIMIT 1', (int(channel['id']),)).fetchone():
                return True
    except Exception:
        pass
    return False


def _expand_graphic_text(template: str, channel, item: dict[str, Any]) -> str:
    values = {
        'channel_name': str(channel['name']), 'channel_number': str(channel['number']),
        'title': str(item.get('title') or ''), 'show_title': str(item.get('show_title') or ''),
        'episode_title': str(item.get('episode_title') or item.get('title') or ''),
        'season': str(item.get('season_number') or ''), 'episode': str(item.get('episode_number') or ''),
        'year': str(item.get('year') or item.get('show_year') or ''),
        'now': datetime.now(_tz()).strftime('%H:%M'),
    }
    out = str(template or '')
    for k, v in values.items():
        out = out.replace('{{' + k + '}}', v).replace('{' + k + '}', v)
    return out


def _escape_drawtext(text: str) -> str:
    return str(text).replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'").replace('%', '\\%').replace(',', '\\,')


def _xy(location: str, h: float, v: float, width: int, height: int, overlay_w: str = 'overlay_w', overlay_h: str = 'overlay_h') -> tuple[str, str]:
    hm = max(0, int(width * h / 100.0)); vm = max(0, int(height * v / 100.0))
    loc = str(location or 'BottomRight').lower()
    if 'right' in loc:
        x = f'main_w-{overlay_w}-{hm}'
    elif 'center' in loc and not ('left' in loc or 'right' in loc):
        x = f'(main_w-{overlay_w})/2'
    else:
        x = str(hm)
    if 'bottom' in loc:
        y = f'main_h-{overlay_h}-{vm}'
    elif 'middle' in loc or ('center' in loc and not ('top' in loc or 'bottom' in loc)):
        y = f'(main_h-{overlay_h})/2'
    else:
        y = str(vm)
    return x, y


def _text_xy(location: str, h: float, v: float, width: int, height: int) -> tuple[str, str]:
    hm = max(0, int(width * h / 100.0)); vm = max(0, int(height * v / 100.0))
    loc = str(location or 'BottomLeft').lower()
    if 'right' in loc:
        x = f'w-text_w-{hm}'
    elif 'center' in loc and not ('left' in loc or 'right' in loc):
        x = '(w-text_w)/2'
    else:
        x = str(hm)
    if 'bottom' in loc:
        y = f'h-text_h-{vm}'
    elif 'middle' in loc or ('center' in loc and not ('top' in loc or 'bottom' in loc)):
        y = '(h-text_h)/2'
    else:
        y = str(vm)
    return x, y


def _advanced_media_command(channel, item: dict[str, Any], offset: float, input_args: list[str], profile_override: str | None = None) -> list[str]:
    profile, _configured, _warning = G['effective_stream_profile'](channel, profile_override)
    bitrate = str(channel['video_bitrate'] or G['VIDEO_BITRATE'])
    resolution = str(channel['resolution'] or '1920x1080')
    try:
        width, height = [int(x) for x in resolution.lower().split('x', 1)]
    except Exception:
        width, height = 1920, 1080
    actual_offset = max(0.0, float(offset or 0.0) + float(item.get('_segment_start') or 0.0))
    base = ['ffmpeg', '-hide_banner', '-loglevel', 'error']
    if profile in {'vaapi','qsv'}:
        preferred = G['hardware_preferred_vaapi_device']() or None
        prereq = G['hwaccel'].profile_prerequisites(profile, preferred)
        if profile == 'vaapi':
            base += ['-vaapi_device', str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
        else:
            base += ['-qsv_device', str(prereq.get('device') or preferred or '/dev/dri/renderD128')]
    base += ['-re', '-ss', f'{actual_offset:.3f}', *input_args]

    graphics = _graphics_for_item(channel, item)
    # Sequential names are resolved lazily so renaming/deleting graphics is safe.
    if item.get('_graphics_names'):
        extra_ids = _graphics_names_to_ids([str(x) for x in item.get('_graphics_names') or []])
        if extra_ids:
            with _db() as conn:
                q = 'SELECT * FROM graphics_elements WHERE enabled=1 AND id IN (%s)' % ','.join('?' * len(extra_ids))
                more = conn.execute(q, tuple(extra_ids)).fetchall()
            by_id = {int(r['id']): r for r in graphics}
            for r in more:
                by_id[int(r['id'])] = r
            graphics = sorted(by_id.values(), key=lambda r: (int(r['z_index'] or 0), int(r['id'])))

    # Existing channel logo remains a first-class legacy station bug unless a
    # schedule/deco explicitly disables watermarks.
    legacy_logo = None
    try:
        if channel['watermark_enabled'] and not item.get('_disable_watermark'):
            p = str(channel['logo_path'] or '')
            if p and Path(p).exists():
                legacy_logo = p
    except Exception:
        legacy_logo = None

    image_graphics = [r for r in graphics if str(r['kind']) == 'image' and r['image_path'] and Path(str(r['image_path'])).exists()]
    for r in image_graphics:
        base += ['-loop', '1', '-i', str(r['image_path'])]
    if legacy_logo:
        base += ['-loop', '1', '-i', legacy_logo]

    filters: list[str] = []
    vin = '[0:v]'
    if str(channel['subtitle_mode']) == 'burn' and item.get('subtitle_path'):
        sub = str(item['subtitle_path']).replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        filters.append(f"{vin}subtitles='{sub}'[vsub]")
        vin = '[vsub]'

    input_index = 1
    for n, r in enumerate(image_graphics):
        target_w = max(8, int(width * float(r['scale_width_percent'] or 12) / 100.0))
        opacity = max(0.0, min(1.0, float(r['opacity_percent'] or 100) / 100.0))
        img_label = f'gimg{n}'
        filters.append(f'[{input_index}:v]scale={target_w}:-1,format=rgba,colorchannelmixer=aa={opacity:.3f}[{img_label}]')
        x, y = _xy(str(r['location']), float(r['horizontal_margin_percent']), float(r['vertical_margin_percent']), width, height)
        start = max(0.0, float(r['start_seconds'] or 0)); end = r['end_seconds']
        enable = f":enable='between(t,{start:.3f},{float(end):.3f})'" if end is not None and float(end) > start else (f":enable='gte(t,{start:.3f})'" if start > 0 else '')
        out_label = f'vimg{n}'
        filters.append(f'{vin}[{img_label}]overlay={x}:{y}{enable}[{out_label}]')
        vin = f'[{out_label}]'; input_index += 1

    if legacy_logo:
        target_w = max(8, int(width * 0.12))
        filters.append(f'[{input_index}:v]scale={target_w}:-1,format=rgba,colorchannelmixer=aa=0.90[legacylogo]')
        filters.append(f'{vin}[legacylogo]overlay=main_w-overlay_w-24:24[vlegacy]')
        vin = '[vlegacy]'; input_index += 1

    text_graphics = [r for r in graphics if str(r['kind']) == 'text' and str(r['text_template'] or '').strip()]
    for n, r in enumerate(text_graphics):
        txt = _escape_drawtext(_expand_graphic_text(str(r['text_template']), channel, item))
        x, y = _text_xy(str(r['location']), float(r['horizontal_margin_percent']), float(r['vertical_margin_percent']), width, height)
        opacity = max(0.0, min(1.0, float(r['opacity_percent'] or 100) / 100.0))
        color = str(r['text_color'] or 'white')
        start = max(0.0, float(r['start_seconds'] or 0)); end = r['end_seconds']
        enable = f":enable='between(t,{start:.3f},{float(end):.3f})'" if end is not None and float(end) > start else (f":enable='gte(t,{start:.3f})'" if start > 0 else '')
        box = ':box=1:boxcolor=black@0.45:boxborderw=10' if r['box_enabled'] else ''
        out_label = f'vtxt{n}'
        filters.append(f"{vin}drawtext=text='{txt}':x={x}:y={y}:fontsize={int(r['font_size'] or 32)}:fontcolor={color}@{opacity:.3f}{box}{enable}[{out_label}]")
        vin = f'[{out_label}]'

    has_filters = bool(filters)
    if has_filters:
        base += ['-filter_complex', ';'.join(filters), '-map', vin, '-map', '0:a:0?']
        profile = 'software'  # graphics remain CPU-filtered for cross-host reliability
        item['_actual_stream_profile'] = 'software'
    else:
        item['_actual_stream_profile'] = profile
        base += ['-map', '0:v:0?', '-map', '0:a:0?']

    if profile == 'direct' and not has_filters:
        base += ['-c', 'copy']
    elif profile == 'qsv' and not has_filters:
        base += ['-vf', f"scale={resolution.replace('x', ':')},format=nv12", '-c:v', 'h264_qsv', '-b:v', bitrate, '-c:a', 'aac', '-b:a', G['AUDIO_BITRATE']]
    elif profile == 'vaapi' and not has_filters:
        base += ['-vf', f"scale={resolution.replace('x', ':')},format=nv12,hwupload", '-c:v', 'h264_vaapi', '-b:v', bitrate, '-c:a', 'aac', '-b:a', G['AUDIO_BITRATE']]
    elif profile == 'nvenc' and not has_filters:
        base += ['-vf', f"scale={resolution.replace('x', ':')},format=yuv420p", '-c:v', 'h264_nvenc', '-preset', 'p4', '-tune', 'll', '-b:v', bitrate, '-c:a', 'aac', '-b:a', G['AUDIO_BITRATE']]
    else:
        base += ['-c:v', 'libx264', '-preset', G['TRANSCODE_PRESET'], '-s', resolution, '-pix_fmt', 'yuv420p', '-b:v', bitrate,
                 '-c:a', 'aac', '-b:a', G['AUDIO_BITRATE'], '-ar', '48000']
    if channel['frame_rate']:
        base += ['-r', str(channel['frame_rate'])]
    base += ['-sn', '-dn', '-mpegts_flags', '+resend_headers+initial_discontinuity', '-f', 'mpegts', 'pipe:1']
    return base


def _advanced_local_command(channel, item: dict[str, Any], offset: float, profile_override: str | None = None) -> list[str]:
    path = str(item.get('path') or channel['offline_media'] or '')
    if not path:
        return ['false']
    return _advanced_media_command(channel, item, offset, ['-i', path], profile_override)


def _advanced_plex_command(channel, item: dict[str, Any], offset: float, url: str, headers: str, profile_override: str | None = None) -> list[str]:
    return _advanced_media_command(channel, item, offset, ['-headers', headers, '-i', url], profile_override)


def _advanced_external_command(channel, item: dict[str, Any], offset: float) -> list[str]:
    url = G['_external_stream_url'](item)
    return _advanced_media_command(channel, item, offset, ['-i', url])


# ---------------------------- block scheduling -----------------------------

def _block_assignment(channel_id: int):
    try:
        with _db() as conn:
            return conn.execute(
                '''SELECT bp.channel_id,bp.template_id,bp.default_deco_id,bp.generation,bp.updated_at playout_updated,bt.name template_name,bt.updated_at
                   FROM block_playouts bp JOIN block_templates bt ON bt.id=bp.template_id
                   WHERE bp.channel_id=? AND bp.enabled=1''', (channel_id,)
            ).fetchone()
    except sqlite3.Error:
        return None


def _deco(deco_id: int | None):
    if not deco_id:
        return None
    with _db() as conn:
        return conn.execute('SELECT * FROM decos WHERE id=?', (int(deco_id),)).fetchone()


def _deco_graphics(row) -> list[int]:
    if not row:
        return []
    try:
        return [int(x) for x in json.loads(row['graphics_ids_json'] or '[]') if str(x).isdigit()]
    except Exception:
        return []


def _block_primary_item(src: dict[str, Any], block_item, deco_row, limit: float | None = None) -> dict[str, Any]:
    x = dict(src)
    dur = max(1.0, float(x.get('duration') or 0))
    if limit is not None and limit < dur:
        x['_source_duration'] = dur; x['_trim_limit'] = max(1.0, limit); x['duration'] = max(1.0, limit)
    x['_block_item_id'] = int(block_item['id'])
    x['_guide_hidden'] = not bool(block_item['show_in_epg'])
    x['_disable_watermark'] = bool(block_item['disable_watermarks'])
    gids = _deco_graphics(deco_row)
    with _db() as conn:
        gids += [int(r['graphic_id']) for r in conn.execute('SELECT graphic_id FROM block_item_graphics WHERE block_item_id=?', (int(block_item['id']),))]
    if deco_row and str(deco_row['watermark_mode']) == 'disable':
        x['_disable_watermark'] = True
    if deco_row and str(deco_row['watermark_mode']) == 'override' and deco_row['watermark_graphic_id']:
        gids.append(int(deco_row['watermark_graphic_id']))
        x['_disable_watermark'] = True
    if gids:
        x['_graphics_ids'] = sorted(set(gids))
    return x



def _decorate_block_filler_for_deco(item: dict[str, Any], deco_row) -> dict[str, Any]:
    """Apply Deco branding rules to filler/dead-air media."""
    x = dict(item)
    if not deco_row:
        return x
    gids = list(x.get('_graphics_ids') or [])
    gids.extend(_deco_graphics(deco_row))
    use_watermark = bool(deco_row['use_watermark_during_filler'])
    mode = str(deco_row['watermark_mode'] or 'inherit')
    if not use_watermark:
        x['_disable_watermark'] = True
    elif mode == 'disable':
        x['_disable_watermark'] = True
    elif mode == 'override' and deco_row['watermark_graphic_id']:
        gids.append(int(deco_row['watermark_graphic_id']))
        x['_disable_watermark'] = True
    if gids:
        x['_graphics_ids'] = sorted(set(int(g) for g in gids if str(g).isdigit()))
    return x

def _fill_gap_with_deco(seconds: float, deco_row, seed: str) -> list[dict[str, Any]]:
    seconds = max(0.0, seconds)
    if seconds <= 0.5:
        return []
    if deco_row and str(deco_row['default_filler_mode']) == 'override' and deco_row['default_filler_id']:
        with _db() as conn:
            p = conn.execute('SELECT * FROM filler_presets WHERE id=? AND enabled=1', (int(deco_row['default_filler_id']),)).fetchone()
        if p:
            clips = _clip_fill(p, seed + '|default', seconds)
            spent = sum(float(x.get('duration') or 0) for x in clips)
            if spent < seconds - 0.5 and deco_row['trim_to_fit']:
                # Try a fallback clip trimmed to the exact boundary.
                pool = _filler_media(p, seed + '|default-tail')
                if pool:
                    x = _mark_filler(pool[0], 'tail')
                    remain = seconds - spent
                    x['_source_duration'] = float(x.get('duration') or remain); x['_trim_limit'] = remain; x['duration'] = remain
                    clips.append(x); spent += remain
            if spent >= seconds - 0.5:
                return [_decorate_block_filler_for_deco(x, deco_row) for x in clips]
            seconds -= spent
            out = clips
        else:
            out = []
    else:
        out = []
    if deco_row and str(deco_row['dead_air_mode']) == 'override' and deco_row['dead_air_filler_id']:
        with _db() as conn:
            p = conn.execute('SELECT * FROM filler_presets WHERE id=? AND enabled=1', (int(deco_row['dead_air_filler_id']),)).fetchone()
        if p:
            pool = _filler_media(p, seed + '|dead-air')
            if pool:
                x = _mark_filler(pool[0], 'fallback')
                x['_source_duration'] = float(x.get('duration') or seconds)
                x['_trim_limit'] = seconds; x['duration'] = seconds
                out.append(x)
                return [_decorate_block_filler_for_deco(y, deco_row) for y in out]
    out.append(_gap(seconds, 'Off Air'))
    return [_decorate_block_filler_for_deco(y, deco_row) for y in out]


def block_day_items(channel_id: int) -> list[dict[str, Any]]:
    ass = _block_assignment(channel_id)
    if not ass:
        return []
    today = datetime.now(_tz()).date()
    key = (channel_id, int(ass['template_id']), int(ass['generation']), str(ass['updated_at']), str(ass['playout_updated']), today.isoformat())
    if key in BLOCK_DAY_CACHE:
        return [dict(x) for x in BLOCK_DAY_CACHE[key]]
    weekday_bit = 1 << today.weekday()
    with _db() as conn:
        slots = conn.execute(
            '''SELECT s.*,b.name block_name,b.duration_minutes FROM block_template_slots s
               JOIN blocks b ON b.id=s.block_id WHERE s.template_id=? AND (s.day_mask & ?) != 0
               ORDER BY s.start_minute,s.position,s.id''', (int(ass['template_id']), weekday_bit)
        ).fetchall()
    if not slots:
        return []
    default_deco = _deco(int(ass['default_deco_id'])) if ass['default_deco_id'] else None
    out: list[dict[str, Any]] = []
    cursor = 0.0
    seed_base = f"block|{channel_id}|{ass['template_id']}|{ass['generation']}|{today.isoformat()}"
    for si, slot in enumerate(slots):
        start = float(int(slot['start_minute']) * 60)
        deco_row = _deco(int(slot['deco_id'])) if slot['deco_id'] else default_deco
        if start > cursor + 0.5:
            gap = _fill_gap_with_deco(start - cursor, default_deco, f'{seed_base}|pre|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
        if cursor > start + 0.5:
            # Overlapping slot; exact block start wins by truncating previous conceptual time.
            start = cursor
        next_start = float(int(slots[si + 1]['start_minute']) * 60) if si + 1 < len(slots) else 86400.0
        block_end = min(86400.0, start + max(1, int(slot['duration_minutes'])) * 60.0, next_start)
        with _db() as conn:
            bis = conn.execute('SELECT * FROM block_items WHERE block_id=? ORDER BY position,id', (int(slot['block_id']),)).fetchall()
        if not bis:
            gap = _fill_gap_with_deco(block_end - cursor, deco_row, f'{seed_base}|empty|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
            continue
        pools: dict[int, list[dict[str, Any]]] = {}
        positions: dict[int, int] = {}
        for bi in bis:
            pool = _order_pool(_source_items(str(bi['source_kind']), str(bi['source_ref'])), str(bi['playback_order']), f'{seed_base}|slot{si}|item{bi["id"]}')
            pools[int(bi['id'])] = pool; positions[int(bi['id'])] = 0
        rounds = 0
        while cursor < block_end - 0.5 and rounds < 10000:
            made = False
            for bi in bis:
                pool = pools.get(int(bi['id'])) or []
                if not pool or cursor >= block_end - 0.5:
                    continue
                pos = positions[int(bi['id'])] % len(pool)
                src = pool[pos]; positions[int(bi['id'])] += 1
                remaining = block_end - cursor
                primary = _block_primary_item(src, bi, deco_row, remaining)
                presets = _filler_presets_for('block', int(bi['id']))
                decorated, new_cursor = _decorate_with_presets(primary, presets, f'{seed_base}|slot{si}|bi{bi["id"]}|{positions[int(bi["id"])]}', cursor)
                # Tail filler is supported for Block items as well as Classic items.
                # It still obeys the Block's hard stop below.
                for p in (x for x in presets if str(x['filler_kind']) == 'tail'):
                    decorated.extend(_clip_fill(p, f'{seed_base}|slot{si}|bi{bi["id"]}|tail|{positions[int(bi["id"])]}', max(0.0, block_end - new_cursor)))
                decorated = [_decorate_block_filler_for_deco(x, deco_row) if x.get('_filler_kind') else x for x in decorated]
                # Never allow filler to push the next block off its fixed boundary.
                for x in decorated:
                    dur = max(1.0, float(x.get('duration') or 0))
                    rem = block_end - cursor
                    if rem <= 0.5:
                        break
                    if dur > rem + 0.5:
                        x = dict(x); x['_source_duration'] = float(x.get('_source_duration') or dur); x['_trim_limit'] = rem; x['duration'] = rem
                        out.append(x); cursor += rem
                        break
                    out.append(x); cursor += dur
                made = True
            rounds += 1
            if not made:
                break
        if cursor < block_end - 0.5:
            gap = _fill_gap_with_deco(block_end - cursor, deco_row, f'{seed_base}|tail|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
    if cursor < 86400 - 0.5:
        gap = _fill_gap_with_deco(86400 - cursor, default_deco, f'{seed_base}|daytail')
        out.extend(gap)
    # Clip any accidental overflow exactly to the broadcast day.
    total = 0.0; clipped: list[dict[str, Any]] = []
    for x in out:
        dur = max(1.0, float(x.get('duration') or 0))
        if total >= 86400 - 0.5:
            break
        if total + dur > 86400:
            x = dict(x); x['_source_duration'] = float(x.get('_source_duration') or dur); x['_trim_limit'] = 86400 - total; x['duration'] = 86400 - total
        clipped.append(x); total += float(x.get('duration') or 0)
    _day_anchor(clipped)
    for k in list(BLOCK_DAY_CACHE):
        if k and k[0] == channel_id:
            BLOCK_DAY_CACHE.pop(k, None)
    BLOCK_DAY_CACHE[key] = [dict(x) for x in clipped]
    return [dict(x) for x in clipped]


# -------------------------- sequential engine ------------------------------

SAMPLE_SEQUENTIAL_YAML = '''# ViperTV Sequential Schedule\ncontent:\n  - collection: "My Shows"\n    key: SHOWS\n    order: chronological\n  - collection: "Commercials"\n    key: ADS\n    order: shuffle\n\nsequences:\n  PRIME:\n    - count: 1\n      content: SHOWS\n    - count: 2\n      content: ADS\n      filler_kind: midroll\n\nreset:\n  - wait_until: "06:00"\n\nplayout:\n  - sequence: PRIME\n    repeat: 8\n  - pad_to_next: 30\n    content: ADS\n    trim: true\n    filler_kind: postroll\n  - repeat: true\n'''


def _parse_yaml(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text or '')
    if not isinstance(data, dict):
        raise ValueError('Sequential YAML must contain a top-level mapping.')
    if not isinstance(data.get('content', []), list):
        raise ValueError('content must be a YAML list.')
    if not isinstance(data.get('playout', []), list) or not data.get('playout'):
        raise ValueError('playout must be a non-empty YAML list.')
    seq = data.get('sequences', {})
    if seq is not None and not isinstance(seq, (dict, list)):
        raise ValueError('sequences must be a mapping or list.')
    return data


def _seq_content_sources(data: dict[str, Any], seed: str) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in data.get('content', []):
        if not isinstance(entry, dict):
            continue
        kind = None; cfg: dict[str, Any] = entry
        for candidate in ('search', 'collection', 'smart_collection', 'multi_collection', 'playlist', 'show', 'image', 'marathon'):
            if candidate in entry:
                kind = candidate
                value = entry[candidate]
                if isinstance(value, dict):
                    cfg = {**entry, **value}
                elif candidate in ('collection', 'smart_collection', 'multi_collection', 'playlist', 'show', 'image'):
                    cfg = {**entry, candidate: value}
                break
        key = str(cfg.get('key') or entry.get('key') or '').strip()
        if not key:
            continue
        order = str(cfg.get('order') or cfg.get('item_order') or 'chronological')
        items: list[dict[str, Any]] = []
        if kind == 'search':
            query = str(cfg.get('query') or '').strip()
            if query:
                items = G['media_search_playable'](query)
        elif kind in ('collection', 'smart_collection', 'multi_collection'):
            name = str(cfg.get(kind) or cfg.get('name') or '').strip()
            row = _collection_by_name(name)
            if row:
                items = G['collection_media'](int(row['id']))
        elif kind == 'playlist':
            row = _playlist_by_name(str(cfg.get('playlist') or cfg.get('name') or ''))
            if row:
                items = G['playlist_media'](int(row['id']))
        elif kind == 'show':
            title = str(cfg.get('show') or cfg.get('title') or '').strip().replace('"', '\\"')
            if title:
                items = G['media_search_playable'](f'type:episode AND show_title:"{title}"')
        elif kind == 'image':
            title = str(cfg.get('image') or cfg.get('title') or '').strip().replace('\"', '\\\"')
            if title:
                items = G['media_search_playable'](f'type:image AND title:"{title}"')
        elif kind == 'marathon':
            combined: list[dict[str, Any]] = []
            searches = cfg.get('searches') or []
            if isinstance(searches, str):
                searches = [searches]
            for q in searches:
                combined.extend(G['media_search_playable'](str(q)))
            group_by = str(cfg.get('group_by') or 'show')
            groups: dict[str, list[dict[str, Any]]] = {}
            for x in combined:
                if group_by == 'season':
                    gk = f"{x.get('show_title')}|{x.get('season_number')}"
                elif group_by == 'artist':
                    gk = str(x.get('artist') or x.get('show_title') or x.get('title') or '')
                elif group_by == 'album':
                    gk = str(x.get('album') or x.get('show_title') or '')
                else:
                    gk = str(x.get('show_title') or x.get('title') or '')
                groups.setdefault(gk, []).append(x)
            keys = sorted(groups)
            if cfg.get('shuffle_groups'):
                keys.sort(key=lambda k: hashlib.sha256(f'{seed}|marathon|{key}|{k}'.encode()).hexdigest())
            play_all = bool(cfg.get('play_all_items', False))
            ordered_groups = [_order_pool(groups[k], order, f'{seed}|marathon-items|{key}|{k}') for k in keys]
            if play_all:
                for group in ordered_groups:
                    items.extend(group)
            else:
                max_len = max([len(g) for g in ordered_groups] or [0])
                for i in range(max_len):
                    for group in ordered_groups:
                        if i < len(group):
                            items.append(group[i])
        if kind != 'marathon':
            items = _order_pool(items, order, f'{seed}|content|{key}')
        out[key] = [dict(x) for x in items]
    return out


def _sequences_map(data: dict[str, Any]) -> dict[str, list[Any]]:
    raw = data.get('sequences') or {}
    if isinstance(raw, dict):
        return {str(k): v if isinstance(v, list) else [] for k, v in raw.items()}
    result: dict[str, list[Any]] = {}
    if isinstance(raw, list):
        for x in raw:
            if not isinstance(x, dict):
                continue
            key = str(x.get('key') or x.get('name') or '')
            items = x.get('items') or x.get('playout') or []
            if key and isinstance(items, list):
                result[key] = items
    return result


def _sequential_assignment(channel_id: int):
    try:
        with _db() as conn:
            return conn.execute(
                '''SELECT sp.channel_id,sp.schedule_id,sp.generation,sp.updated_at playout_updated,ss.name,ss.yaml_text,ss.updated_at
                   FROM sequential_playouts sp JOIN sequential_schedules ss ON ss.id=sp.schedule_id
                   WHERE sp.channel_id=? AND sp.enabled=1''', (channel_id,)
            ).fetchone()
    except sqlite3.Error:
        return None


def _seq_parse_time(value: Any) -> int:
    text = str(value or '').strip()
    m = re.match(r'^(\d{1,2}):(\d{2})(?:\s*([AP]M))?$', text, re.I)
    if not m:
        raise ValueError(f'Invalid clock time: {text}')
    h = int(m.group(1)); minute = int(m.group(2)); ap = (m.group(3) or '').upper()
    if ap:
        h %= 12
        if ap == 'PM': h += 12
    return max(0, min(1439, h * 60 + minute))


def _seq_parse_duration(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(1.0, float(value) * 60.0)
    text = str(value or '').strip().lower()
    m = re.match(r'^([0-9.]+)\s*(second|seconds|sec|s|minute|minutes|min|m|hour|hours|hr|h)?$', text)
    if not m:
        raise ValueError(f'Invalid duration: {value}')
    n = float(m.group(1)); unit = m.group(2) or 'minutes'
    if unit.startswith('h'): return max(1.0, n * 3600)
    if unit.startswith('s'): return max(1.0, n)
    return max(1.0, n * 60)


def _seq_decorate(src: dict[str, Any], inst: dict[str, Any], active_graphics: set[str], watermark_enabled: bool, limit: float | None = None) -> dict[str, Any]:
    x = dict(src); dur = max(1.0, float(x.get('duration') or 0))
    if limit is not None and limit < dur:
        x['_source_duration'] = dur; x['_trim_limit'] = max(1.0, limit); x['duration'] = max(1.0, limit)
    filler_kind = str(inst.get('filler_kind') or 'none')
    if filler_kind != 'none':
        x['_guide_hidden'] = True; x['_filler_kind'] = filler_kind
    if inst.get('custom_title'):
        x['_guide_custom_title'] = str(inst.get('custom_title'))
    if active_graphics:
        x['_graphics_names'] = sorted(active_graphics)
    if not watermark_enabled:
        x['_disable_watermark'] = True
    return x


def sequential_day_items(channel_id: int) -> list[dict[str, Any]]:
    ass = _sequential_assignment(channel_id)
    if not ass:
        return []
    today = datetime.now(_tz()).date()
    key = (channel_id, int(ass['schedule_id']), int(ass['generation']), str(ass['updated_at']), str(ass['playout_updated']), today.isoformat())
    if key in SEQUENTIAL_DAY_CACHE:
        return [dict(x) for x in SEQUENTIAL_DAY_CACHE[key]]
    try:
        data = _parse_yaml(str(ass['yaml_text']))
    except Exception:
        return []
    seed = f"seq|{channel_id}|{ass['schedule_id']}|{ass['generation']}|{today.isoformat()}"
    content = _seq_content_sources(data, seed)
    sequences = _sequences_map(data)
    positions = {k: 0 for k in content}
    active_graphics: set[str] = set()
    watermark_enabled = True
    out: list[dict[str, Any]] = []
    cursor = 0.0
    guard = 0

    def next_item(key_name: str) -> dict[str, Any] | None:
        pool = content.get(key_name) or []
        if not pool:
            return None
        pos = positions.get(key_name, 0)
        item = dict(pool[pos % len(pool)])
        positions[key_name] = pos + 1
        return item

    def fill_budget(inst: dict[str, Any], budget: float, trim: bool, stop_before_end: bool = True, fallback: str = '') -> float:
        nonlocal cursor, guard
        key_name = str(inst.get('content') or '')
        start_cursor = cursor
        discards = max(0, int(inst.get('discard_attempts') or 0))
        attempts = 0
        while cursor - start_cursor < budget - 0.5 and cursor < 86400 - 0.5 and guard < 50000:
            guard += 1
            src = next_item(key_name)
            if not src:
                break
            dur = max(1.0, float(src.get('duration') or 0))
            remaining = min(budget - (cursor - start_cursor), 86400 - cursor)
            if dur <= remaining + 0.5:
                x = _seq_decorate(src, inst, active_graphics, watermark_enabled)
                out.append(x); cursor += dur; attempts = 0
                continue
            if trim and remaining > 0.5:
                x = _seq_decorate(src, inst, active_graphics, watermark_enabled, remaining)
                out.append(x); cursor += remaining
                break
            if attempts < discards:
                attempts += 1
                continue
            if not stop_before_end:
                x = _seq_decorate(src, inst, active_graphics, watermark_enabled)
                out.append(x); cursor += dur
            break
        remain = max(0.0, budget - (cursor - start_cursor))
        if remain > 0.5 and fallback:
            src = next_item(fallback)
            if src:
                x = _seq_decorate(src, {**inst, 'filler_kind': inst.get('filler_kind') or 'postroll'}, active_graphics, watermark_enabled, remain)
                out.append(x); cursor += remain; remain = 0.0
        if remain > 0.5 and bool(inst.get('offline_tail', False)):
            out.append(_gap(remain, 'Off Air')); cursor += remain; remain = 0.0
        return remain

    def run_instructions(instructions: list[Any], depth: int = 0) -> bool:
        nonlocal cursor, guard, watermark_enabled
        if depth > 12:
            return False
        i = 0
        while i < len(instructions) and cursor < 86400 - 0.5 and guard < 50000:
            guard += 1
            raw = instructions[i]
            i += 1
            if not isinstance(raw, dict):
                continue
            inst = dict(raw)
            # normalize {count: {content:X, value:2}} and {count:2, content:X}
            op = None
            for candidate in ('all', 'count', 'duration', 'pad_to_next', 'pad_until', 'sequence', 'epg_group', 'graphics_on', 'graphics_off', 'repeat', 'shuffle_sequence', 'skip_items', 'skip_to_item', 'wait_until', 'watermark'):
                if candidate in inst:
                    op = candidate; break
            if not op:
                continue
            val = inst.get(op)
            if isinstance(val, dict):
                inst = {**inst, **val}
                val = inst.get('value', inst.get(op))
            if op == 'graphics_on':
                vals = val if isinstance(val, list) else [val]
                active_graphics.update(str(x) for x in vals if x)
                continue
            if op == 'graphics_off':
                if val in (None, '', False): active_graphics.clear()
                else:
                    vals = val if isinstance(val, list) else [val]
                    for x in vals: active_graphics.discard(str(x))
                continue
            if op == 'watermark':
                watermark_enabled = str(val).lower() not in ('off', 'false', 'disable', 'disabled', '0')
                continue
            if op == 'skip_items':
                key_name = str(inst.get('content') or '')
                positions[key_name] = positions.get(key_name, 0) + max(0, int(inst.get('count') or val or 1))
                continue
            if op == 'skip_to_item':
                key_name = str(inst.get('content') or '')
                positions[key_name] = max(0, int(inst.get('index') or val or 0))
                continue
            if op == 'shuffle_sequence':
                name = str(val or inst.get('sequence') or '')
                if name in sequences:
                    seq = list(sequences[name])
                    rnd = random.Random(int(hashlib.sha256(f'{seed}|shuffle-seq|{name}|{cursor}'.encode()).hexdigest()[:16], 16))
                    rnd.shuffle(seq); sequences[name] = seq
                continue
            if op == 'wait_until':
                target = float(_seq_parse_time(val if not isinstance(val, dict) else inst.get('time')) * 60)
                if target > cursor + 0.5:
                    out.append(_gap(target - cursor, 'Off Air')); cursor = target
                continue
            if op == 'epg_group':
                # Subsequent instructions may explicitly set a custom title. The YAML
                # control is accepted so schedules remain portable; hidden filler already
                # collapses out of the guide in ViperTV.
                continue
            if op == 'sequence':
                name = str(val or inst.get('name') or '')
                repeat_count = max(1, min(1000, int(inst.get('repeat') or 1)))
                for _ in range(repeat_count):
                    if not run_instructions(list(sequences.get(name) or []), depth + 1):
                        break
                continue
            if op == 'repeat':
                return True
            if op == 'all':
                key_name = str(inst.get('content') or '')
                pool = content.get(key_name) or []
                for _ in range(len(pool)):
                    if cursor >= 86400 - 0.5: break
                    src = next_item(key_name)
                    if not src: break
                    dur = max(1.0, float(src.get('duration') or 0)); rem = 86400 - cursor
                    x = _seq_decorate(src, inst, active_graphics, watermark_enabled, rem if dur > rem else None)
                    out.append(x); cursor += min(dur, rem)
                continue
            if op == 'count':
                count = max(0, min(10000, int(val if isinstance(val, (int, float)) else inst.get('count_value') or inst.get('n') or 1)))
                key_name = str(inst.get('content') or '')
                for _ in range(count):
                    if cursor >= 86400 - 0.5: break
                    src = next_item(key_name)
                    if not src: break
                    dur = max(1.0, float(src.get('duration') or 0)); rem = 86400 - cursor
                    x = _seq_decorate(src, inst, active_graphics, watermark_enabled, rem if dur > rem else None)
                    out.append(x); cursor += min(dur, rem)
                continue
            if op == 'duration':
                budget = _seq_parse_duration(val)
                fill_budget(inst, min(budget, 86400 - cursor), bool(inst.get('trim', False)), bool(inst.get('stop_before_end', True)), str(inst.get('fallback') or ''))
                continue
            if op == 'pad_to_next':
                minutes = max(1, int(val or 30)); boundary = minutes * 60.0
                target = math.ceil((cursor + 0.001) / boundary) * boundary
                fill_budget(inst, max(0.0, min(target, 86400.0) - cursor), bool(inst.get('trim', True)), True, str(inst.get('fallback') or ''))
                continue
            if op == 'pad_until':
                target = float(_seq_parse_time(val) * 60)
                if target <= cursor + 0.5:
                    if bool(inst.get('tomorrow', False)): target += 86400.0
                    else: continue
                budget = min(86400.0, target) - cursor
                if budget > 0:
                    fill_budget(inst, budget, bool(inst.get('trim', True)), bool(inst.get('stop_before_end', True)), str(inst.get('fallback') or ''))
                continue
        return False

    reset = data.get('reset') or []
    if isinstance(reset, list):
        run_instructions(reset)
    main = data.get('playout') or []
    loops = 0
    while cursor < 86400 - 0.5 and loops < 2000 and guard < 50000:
        do_repeat = run_instructions(main)
        loops += 1
        if not do_repeat:
            # Sequential playout instructions loop indefinitely by design.
            if cursor < 86400 - 0.5:
                continue
            break
    if cursor < 86400 - 0.5:
        out.append(_gap(86400 - cursor, 'Off Air'))
    _day_anchor(out)
    for k in list(SEQUENTIAL_DAY_CACHE):
        if k and k[0] == channel_id:
            SEQUENTIAL_DAY_CACHE.pop(k, None)
    SEQUENTIAL_DAY_CACHE[key] = [dict(x) for x in out]
    return [dict(x) for x in out]


# ------------------------------- UI ----------------------------------------

def blocks_index_page() -> str:
    with _db() as conn:
        blocks = conn.execute('SELECT b.*,(SELECT COUNT(*) FROM block_items bi WHERE bi.block_id=b.id) item_count FROM blocks b ORDER BY b.name').fetchall()
        templates = conn.execute('SELECT bt.*,(SELECT COUNT(*) FROM block_template_slots s WHERE s.template_id=bt.id) slot_count FROM block_templates bt ORDER BY bt.name').fetchall()
        decos = conn.execute('SELECT * FROM decos ORDER BY name').fetchall()
        channels = conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall()
        assigned = {int(r['channel_id']): r for r in conn.execute('SELECT bp.*,bt.name template_name FROM block_playouts bp JOIN block_templates bt ON bt.id=bp.template_id')}
    block_rows = ''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{x['duration_minutes']} min</td><td>{x['item_count']}</td><td><a class='button secondary' href='/scheduling/blocks/{x['id']}'>Edit</a></td></tr>" for x in blocks) or "<tr><td colspan='4' class='empty'>No Blocks yet.</td></tr>"
    template_rows = ''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{x['slot_count']}</td><td><a class='button secondary' href='/scheduling/block-templates/{x['id']}'>Edit</a></td></tr>" for x in templates) or "<tr><td colspan='3' class='empty'>No Block Templates yet.</td></tr>"
    deco_rows = ''.join(f"<tr><td>{_e(x['name'])}</td><td>{_e(x['watermark_mode'])}</td><td>{_e(x['default_filler_mode'])}</td><td>{_e(x['dead_air_mode'])}</td></tr>" for x in decos) or "<tr><td colspan='4' class='empty'>No Decos yet.</td></tr>"
    template_opts = ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in templates)
    deco_opts = "<option value=''>— None —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in decos)
    assign_rows = []
    for c in channels:
        a = assigned.get(int(c['id']))
        assign_rows.append(f"<tr><td>{_e(c['number'])}</td><td>{_e(c['name'])}</td><td>{_e(a['template_name']) if a else 'Not assigned'}</td><td><form class='inline' method='post' action='/scheduling/block-playouts/{c['id']}/assign'><select name='template_id'><option value=''>— No Block Schedule —</option>" + ''.join(f"<option value='{x['id']}' {'selected' if a and int(a['template_id'])==int(x['id']) else ''}>{_e(x['name'])}</option>" for x in templates) + f"</select><select name='default_deco_id'>{deco_opts}</select><button>Assign</button></form>" + (f" <form class='inline' method='post' action='/scheduling/block-playouts/{c['id']}/reset'><button class='secondary'>Reset</button></form>" if a else '') + "</td></tr>")
    body = _heading('Block Scheduling', 'Build fixed-duration Blocks, place them on day Templates, decorate them with filler/branding Decos, then assign a Block Playout to a channel.', "<a class='button secondary' href='/scheduling/sequential'>Sequential</a>") + f"""
<div class='grid'><div class='card'><h2>Create Block</h2><form method='post' action='/scheduling/blocks/add'><label>Name</label><input name='name' required placeholder='Prime Time Sitcom'><label>Duration (minutes)</label><input type='number' name='duration_minutes' min='1' max='1440' value='30'><button>Create Block</button></form></div>
<div class='card'><h2>Create Template</h2><form method='post' action='/scheduling/block-templates/add'><label>Name</label><input name='name' required placeholder='Weekday'><button>Create Template</button></form></div></div>
<div class='card'><h2>Blocks</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Duration</th><th>Items</th><th></th></tr></thead><tbody>{block_rows}</tbody></table></div></div>
<div class='card'><h2>Templates</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Slots</th><th></th></tr></thead><tbody>{template_rows}</tbody></table></div></div>
<div class='card'><h2>Decos</h2><p class='muted'>Decos control block-level watermark overrides, default filler, dead-air fallback and extra graphics.</p><a class='button' href='/scheduling/decos'>Manage Decos</a><div class='table-wrap'><table><thead><tr><th>Name</th><th>Watermark</th><th>Default Filler</th><th>Dead Air</th></tr></thead><tbody>{deco_rows}</tbody></table></div></div>
<div class='card'><h2>Block Playouts</h2><p class='muted'>Assigning a Block Playout disables any Sequential or Classic Playout on that channel so scheduling mode is unambiguous.</p><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Template</th><th></th></tr></thead><tbody>{''.join(assign_rows) or "<tr><td colspan='4'>No channels.</td></tr>"}</tbody></table></div></div>"""
    return _page('Block Scheduling', body)


def _block_editor(block_id: int, msg: str = '') -> str:
    with _db() as conn:
        block = conn.execute('SELECT * FROM blocks WHERE id=?', (block_id,)).fetchone()
        if not block: raise HTTPException(404, 'Block not found')
        items = conn.execute('SELECT * FROM block_items WHERE block_id=? ORDER BY position,id', (block_id,)).fetchall()
        fillers = conn.execute('SELECT * FROM filler_presets WHERE enabled=1 ORDER BY name').fetchall()
        graphics = conn.execute('SELECT * FROM graphics_elements WHERE enabled=1 ORDER BY name').fetchall()
    rows = []
    for i in items:
        with _db() as conn:
            fp = {int(r['filler_id']) for r in conn.execute('SELECT filler_id FROM block_item_fillers WHERE block_item_id=?', (i['id'],))}
            gp = {int(r['graphic_id']) for r in conn.execute('SELECT graphic_id FROM block_item_graphics WHERE block_item_id=?', (i['id'],))}
        rows.append(f"<tr><td>{int(i['position'])+1}</td><td>{_e(_source_label(str(i['source_kind']),str(i['source_ref'])))}</td><td>{_e(i['playback_order'])}</td><td>{'Yes' if i['show_in_epg'] else 'No'}</td><td>{', '.join(_e(f['name']) for f in fillers if int(f['id']) in fp) or '—'}</td><td>{', '.join(_e(g['name']) for g in graphics if int(g['id']) in gp) or '—'}</td><td><a class='button secondary' href='/scheduling/block-items/{i['id']}/edit'>Edit</a> <form class='inline' method='post' action='/scheduling/block-items/{i['id']}/move'><input type='hidden' name='direction' value='up'><button class='secondary'>↑</button></form> <form class='inline' method='post' action='/scheduling/block-items/{i['id']}/move'><input type='hidden' name='direction' value='down'><button class='secondary'>↓</button></form> <form class='inline' method='post' action='/scheduling/block-items/{i['id']}/delete'><button class='danger'>Delete</button></form></td></tr>")
    filler_checks = ''.join(f"<label style='display:block'><input type='checkbox' name='filler_id' value='{x['id']}'>{_e(x['name'])} <span class='badge'>{_e(x['filler_kind'])}</span></label>" for x in fillers) or '<span class="muted">Create Filler presets first.</span>'
    graphic_checks = ''.join(f"<label style='display:block'><input type='checkbox' name='graphic_id' value='{x['id']}'>{_e(x['name'])}</label>" for x in graphics) or '<span class="muted">Create Graphics first.</span>'
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(str(block['name']), 'Each Block item implicitly plays one media item per rotation until the fixed Block duration is filled.', "<a class='button secondary' href='/scheduling/blocks'>Back</a>") + f"""
<div class='card'><form method='post' action='/scheduling/blocks/{block_id}/settings'><div class='grid'><div><label>Name</label><input name='name' value='{_e(block['name'])}'></div><div><label>Duration (minutes)</label><input type='number' name='duration_minutes' min='1' max='1440' value='{block['duration_minutes']}'></div></div><button>Save Block</button></form><hr><form method='post' action='/scheduling/blocks/{block_id}/delete' onsubmit="return confirm('Delete this Block? Template slots using it will also be removed.');"><button class='danger'>Delete Block</button></form></div>
<div class='card'><h2>Block Items</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Source</th><th>Order</th><th>EPG</th><th>Filler</th><th>Graphics</th><th></th></tr></thead><tbody>{''.join(rows) or "<tr><td colspan='7' class='empty'>No items.</td></tr>"}</tbody></table></div></div>
<div class='card'><h2>Add Block Item</h2><form method='post' action='/scheduling/blocks/{block_id}/items/add'><label>Content Source</label><select name='source_choice' required>{_source_options()}</select><div class='grid3'><div><label>Playback Order</label><select name='playback_order'><option value='chronological'>Chronological</option><option value='season_episode'>Season / Episode</option><option value='shuffle'>Shuffle</option><option value='random'>Random</option><option value='shuffle_in_order'>Shuffle In Order</option></select></div><div><label><input type='checkbox' name='show_in_epg' value='1' checked> Show in EPG</label><label><input type='checkbox' name='disable_watermarks' value='1'> Disable watermarks</label></div><div></div></div><div class='grid'><div><h3>Filler Presets</h3>{filler_checks}</div><div><h3>Graphics</h3>{graphic_checks}</div></div><button>Add Block Item</button></form></div>"""
    return _page('Edit Block', body)



def _block_item_edit_page(item_id: int, msg: str = '') -> str:
    with _db() as conn:
        i = conn.execute('SELECT bi.*,b.name block_name FROM block_items bi JOIN blocks b ON b.id=bi.block_id WHERE bi.id=?', (item_id,)).fetchone()
        if not i:
            raise HTTPException(404, 'Block item not found')
        fillers = conn.execute('SELECT * FROM filler_presets WHERE enabled=1 ORDER BY name').fetchall()
        graphics = conn.execute('SELECT * FROM graphics_elements WHERE enabled=1 ORDER BY name').fetchall()
        fp = {int(r['filler_id']) for r in conn.execute('SELECT filler_id FROM block_item_fillers WHERE block_item_id=?', (item_id,))}
        gp = {int(r['graphic_id']) for r in conn.execute('SELECT graphic_id FROM block_item_graphics WHERE block_item_id=?', (item_id,))}
    filler_checks = ''.join(f"<label style='display:block'><input type='checkbox' name='filler_id' value='{x['id']}' {'checked' if int(x['id']) in fp else ''}>{_e(x['name'])} <span class='badge'>{_e(x['filler_kind'])}</span></label>" for x in fillers) or '<span class="muted">No filler presets.</span>'
    graphic_checks = ''.join(f"<label style='display:block'><input type='checkbox' name='graphic_id' value='{x['id']}' {'checked' if int(x['id']) in gp else ''}>{_e(x['name'])}</label>" for x in graphics) or '<span class="muted">No graphics.</span>'
    orders = ''.join(f"<option value='{o}' {'selected' if str(i['playback_order'])==o else ''}>{label}</option>" for o,label in [('chronological','Chronological'),('season_episode','Season / Episode'),('shuffle','Shuffle'),('random','Random'),('shuffle_in_order','Shuffle In Order')])
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Block Item', str(i['block_name']), f"<a class='button secondary' href='/scheduling/blocks/{i['block_id']}'>Back to Block</a>") + f"""
<div class='card'><form method='post' action='/scheduling/block-items/{item_id}/save'><label>Content Source</label><select name='source_choice' required>{_source_options(str(i['source_kind']),str(i['source_ref']))}</select><div class='grid3'><div><label>Playback Order</label><select name='playback_order'>{orders}</select></div><div><label><input type='checkbox' name='show_in_epg' value='1' {'checked' if i['show_in_epg'] else ''}> Show in EPG</label><label><input type='checkbox' name='disable_watermarks' value='1' {'checked' if i['disable_watermarks'] else ''}> Disable watermarks</label></div><div></div></div><div class='grid'><div><h3>Filler Presets</h3>{filler_checks}</div><div><h3>Graphics</h3>{graphic_checks}</div></div><button>Save Block Item</button></form></div>"""
    return _page('Edit Block Item', body)

def _template_editor(template_id: int, msg: str = '') -> str:
    with _db() as conn:
        t = conn.execute('SELECT * FROM block_templates WHERE id=?', (template_id,)).fetchone()
        if not t: raise HTTPException(404, 'Template not found')
        slots = conn.execute('''SELECT s.*,b.name block_name,d.name deco_name FROM block_template_slots s JOIN blocks b ON b.id=s.block_id LEFT JOIN decos d ON d.id=s.deco_id WHERE s.template_id=? ORDER BY s.start_minute,s.position,s.id''', (template_id,)).fetchall()
        blocks = conn.execute('SELECT * FROM blocks ORDER BY name').fetchall(); decos = conn.execute('SELECT * FROM decos ORDER BY name').fetchall()
    days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    rows = ''.join(f"<tr><td>{_min_to_hm(int(s['start_minute']))}</td><td>{_e(s['block_name'])}</td><td>{_e(s['deco_name'] or 'Default')}</td><td>{' '.join(days[i] for i in range(7) if int(s['day_mask']) & (1<<i))}</td><td><form class='inline' method='post' action='/scheduling/block-slots/{s['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for s in slots) or "<tr><td colspan='5'>No slots.</td></tr>"
    block_opts = ''.join(f"<option value='{b['id']}'>{_e(b['name'])} ({b['duration_minutes']} min)</option>" for b in blocks)
    deco_opts = "<option value=''>Default Playout Deco</option>" + ''.join(f"<option value='{d['id']}'>{_e(d['name'])}</option>" for d in decos)
    checks = ' '.join(f"<label><input type='checkbox' name='days' value='{i}' checked>{d}</label>" for i,d in enumerate(days))
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(str(t['name']), 'Place Blocks at fixed wall-clock starts on one or more days.', "<a class='button secondary' href='/scheduling/blocks'>Back</a>") + f"""
<div class='card'><h2>Template Settings</h2><form method='post' action='/scheduling/block-templates/{template_id}/settings'><label>Name</label><input name='name' value='{_e(t['name'])}' required><button>Save Template</button></form><hr><form method='post' action='/scheduling/block-templates/{template_id}/delete' onsubmit="return confirm('Delete this Template and detach its Block Playouts?');"><button class='danger'>Delete Template</button></form></div>
<div class='card'><h2>Template Slots</h2><div class='table-wrap'><table><thead><tr><th>Start</th><th>Block</th><th>Deco</th><th>Days</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Add Slot</h2><form method='post' action='/scheduling/block-templates/{template_id}/slots/add'><div class='grid3'><div><label>Start</label><input type='time' name='start_time' value='18:00'></div><div><label>Block</label><select name='block_id'>{block_opts}</select></div><div><label>Deco</label><select name='deco_id'>{deco_opts}</select></div></div><p>{checks}</p><button>Add Slot</button></form></div>"""
    return _page('Block Template', body)


def _decos_page(msg: str = '') -> str:
    with _db() as conn:
        rows = conn.execute('SELECT * FROM decos ORDER BY name').fetchall(); fillers = conn.execute('SELECT * FROM filler_presets WHERE enabled=1 ORDER BY name').fetchall(); graphics = conn.execute('SELECT * FROM graphics_elements WHERE enabled=1 ORDER BY name').fetchall()
    tr = ''.join(f"<tr><td>{_e(x['name'])}</td><td>{_e(x['watermark_mode'])}</td><td>{_e(x['default_filler_mode'])}</td><td>{_e(x['dead_air_mode'])}</td><td><a class='button secondary' href='/scheduling/decos/{x['id']}/edit'>Edit</a> <form class='inline' method='post' action='/scheduling/decos/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for x in rows) or '<tr><td colspan="5">No Decos.</td></tr>'
    fopts = "<option value=''>— None —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in fillers)
    gopts = "<option value=''>— None —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in graphics)
    gchecks = ''.join(f"<label style='display:block'><input type='checkbox' name='graphic_id' value='{x['id']}'>{_e(x['name'])}</label>" for x in graphics)
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Block Decos', 'Reusable decorations separate filler and branding behavior from primary Block content.', "<a class='button secondary' href='/scheduling/blocks'>Blocks</a>") + f"""
<div class='card'><h2>Create Deco</h2><form method='post' action='/scheduling/decos/add'><label>Name</label><input name='name' required placeholder='Prime Time Branding'><div class='grid3'><div><label>Watermark Mode</label><select name='watermark_mode'><option>inherit</option><option>disable</option><option>override</option></select><label>Override Graphic</label><select name='watermark_graphic_id'>{gopts}</select><label><input type='checkbox' name='use_watermark_during_filler' value='1'> Use watermark during filler</label></div><div><label>Default Filler Mode</label><select name='default_filler_mode'><option>inherit</option><option>disable</option><option>override</option></select><label>Default Filler</label><select name='default_filler_id'>{fopts}</select><label><input type='checkbox' name='trim_to_fit' value='1' checked> Trim filler to exact Block boundary</label></div><div><label>Dead Air Fallback Mode</label><select name='dead_air_mode'><option>inherit</option><option>disable</option><option>override</option></select><label>Dead Air Fallback</label><select name='dead_air_filler_id'>{fopts}</select></div></div><h3>Additional Graphics</h3>{gchecks}<button>Create Deco</button></form></div>
<div class='card'><div class='table-wrap'><table><thead><tr><th>Name</th><th>Watermark</th><th>Default Filler</th><th>Dead Air</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></div>"""
    return _page('Block Decos', body)



def _deco_edit_page(deco_id: int, msg: str = '') -> str:
    with _db() as conn:
        x = conn.execute('SELECT * FROM decos WHERE id=?', (deco_id,)).fetchone()
        if not x:
            raise HTTPException(404, 'Deco not found')
        fillers = conn.execute('SELECT * FROM filler_presets WHERE enabled=1 ORDER BY name').fetchall()
        graphics = conn.execute('SELECT * FROM graphics_elements WHERE enabled=1 ORDER BY name').fetchall()
    selected = set(_deco_graphics(x))
    fopts_default = "<option value=''>— None —</option>" + ''.join(f"<option value='{f['id']}' {'selected' if x['default_filler_id']==f['id'] else ''}>{_e(f['name'])}</option>" for f in fillers)
    fopts_dead = "<option value=''>— None —</option>" + ''.join(f"<option value='{f['id']}' {'selected' if x['dead_air_filler_id']==f['id'] else ''}>{_e(f['name'])}</option>" for f in fillers)
    gopts = "<option value=''>— None —</option>" + ''.join(f"<option value='{g['id']}' {'selected' if x['watermark_graphic_id']==g['id'] else ''}>{_e(g['name'])}</option>" for g in graphics)
    gchecks = ''.join(f"<label style='display:block'><input type='checkbox' name='graphic_id' value='{g['id']}' {'checked' if int(g['id']) in selected else ''}>{_e(g['name'])}</label>" for g in graphics)
    def modes(current):
        return ''.join(f"<option {'selected' if str(current)==m else ''}>{m}</option>" for m in ['inherit','disable','override'])
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Block Deco', str(x['name']), "<a class='button secondary' href='/scheduling/decos'>Back to Decos</a>") + f"""
<div class='card'><form method='post' action='/scheduling/decos/{deco_id}/save'><label>Name</label><input name='name' value='{_e(x['name'])}' required><div class='grid3'><div><label>Watermark Mode</label><select name='watermark_mode'>{modes(x['watermark_mode'])}</select><label>Override Graphic</label><select name='watermark_graphic_id'>{gopts}</select><label><input type='checkbox' name='use_watermark_during_filler' value='1' {'checked' if x['use_watermark_during_filler'] else ''}> Use watermark during filler</label></div><div><label>Default Filler Mode</label><select name='default_filler_mode'>{modes(x['default_filler_mode'])}</select><label>Default Filler</label><select name='default_filler_id'>{fopts_default}</select><label><input type='checkbox' name='trim_to_fit' value='1' {'checked' if x['trim_to_fit'] else ''}> Trim filler to Block boundary</label></div><div><label>Dead Air Fallback Mode</label><select name='dead_air_mode'>{modes(x['dead_air_mode'])}</select><label>Dead Air Fallback</label><select name='dead_air_filler_id'>{fopts_dead}</select></div></div><h3>Additional Graphics</h3>{gchecks}<button>Save Deco</button></form></div>"""
    return _page('Edit Deco', body)

def _filler_page(msg: str = '') -> str:
    with _db() as conn:
        presets = conn.execute('''SELECT fp.*,c.name collection_name,l.name library_name FROM filler_presets fp LEFT JOIN collections c ON c.id=fp.collection_id LEFT JOIN libraries l ON l.id=fp.library_id ORDER BY fp.name''').fetchall()
        cols = conn.execute("SELECT * FROM collections WHERE kind IN ('manual','smart','multi') ORDER BY name").fetchall(); libs = conn.execute('SELECT * FROM libraries ORDER BY name').fetchall()
    rows = ''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{_e(x['filler_kind'])}</td><td>{_e(x['fill_mode'])}</td><td>{_e(x['collection_name'] or x['library_name'] or '')}</td><td>{x['count_items'] if x['fill_mode']=='count' else str(x['duration_seconds'])+' sec' if x['fill_mode']=='duration' else 'to '+str(x['pad_minutes'])+' min'}</td><td><a class='button secondary' href='/lists/filler/{x['id']}/edit'>Edit</a> <form class='inline' method='post' action='/lists/filler/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for x in presets) or '<tr><td colspan="6">No filler presets.</td></tr>'
    copts = "<option value=''>— Choose Collection —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])} ({_e(x['kind'])})</option>" for x in cols)
    lopts = "<option value=''>— Legacy local library fallback —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in libs)
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Filler Presets', 'Commercials, bumpers, promos and station IDs with Pre-roll, Mid-roll, Post-roll, Tail and Fallback behavior.') + f"""
<div class='card'><h2>Create Filler Preset</h2><form method='post' action='/lists/filler/v12/add'><div class='grid3'><div><label>Name</label><input name='name' required placeholder='Commercial Break'><label>Filler Kind</label><select name='filler_kind'><option value='preroll'>Pre-roll</option><option value='midroll'>Mid-roll</option><option value='postroll' selected>Post-roll</option><option value='tail'>Tail</option><option value='fallback'>Fallback</option></select></div><div><label>Collection</label><select name='collection_id'>{copts}</select><label>Local Library (optional legacy source)</label><select name='library_id'>{lopts}</select></div><div><label>Mode</label><select name='fill_mode'><option value='count'>Count</option><option value='duration'>Duration</option><option value='pad'>Pad to wall-clock multiple</option></select><label>Count clips</label><input type='number' name='count_items' value='2' min='1' max='100'><label>Duration seconds</label><input type='number' name='duration_seconds' value='120' min='1' max='3600'><label>Pad minutes</label><input type='number' name='pad_minutes' value='30' min='1' max='180'><label>Mid-roll breaks</label><input type='number' name='midroll_breaks' value='1' min='1' max='8'></div></div><label><input type='checkbox' name='trim_to_fit' value='1' checked> Trim final filler clip when an exact boundary is required</label><button>Create Filler Preset</button></form></div>
<div class='card'><h2>Presets</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Kind</th><th>Mode</th><th>Source</th><th>Amount</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>How filler works</h2><p><b>Pre-roll</b> runs before primary media, <b>Mid-roll</b> splits long programmes into one or more commercial breaks, <b>Post-roll</b> follows each item, <b>Tail</b> runs when a schedule-item group ends, and <b>Fallback</b> replaces otherwise unscheduled gaps. Count, Duration and Pad modes are reusable across Classic, Block and Sequential programming.</p></div>"""
    return _page('Filler', body)



def _filler_edit_page(filler_id: int, msg: str = '') -> str:
    with _db() as conn:
        x = conn.execute('SELECT * FROM filler_presets WHERE id=?', (filler_id,)).fetchone()
        if not x:
            raise HTTPException(404, 'Filler preset not found')
        cols = conn.execute("SELECT * FROM collections WHERE kind IN ('manual','smart','multi') ORDER BY name").fetchall()
        libs = conn.execute('SELECT * FROM libraries ORDER BY name').fetchall()
    copts = "<option value=''>— None —</option>" + ''.join(f"<option value='{c['id']}' {'selected' if x['collection_id']==c['id'] else ''}>{_e(c['name'])} ({_e(c['kind'])})</option>" for c in cols)
    lopts = "<option value=''>— None —</option>" + ''.join(f"<option value='{l['id']}' {'selected' if x['library_id']==l['id'] else ''}>{_e(l['name'])}</option>" for l in libs)
    kinds = ''.join(f"<option value='{k}' {'selected' if str(x['filler_kind'])==k else ''}>{label}</option>" for k,label in [('preroll','Pre-roll'),('midroll','Mid-roll'),('postroll','Post-roll'),('tail','Tail'),('fallback','Fallback')])
    modes = ''.join(f"<option value='{k}' {'selected' if str(x['fill_mode'])==k else ''}>{label}</option>" for k,label in [('count','Count'),('duration','Duration'),('pad','Pad to wall-clock multiple')])
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Filler Preset', str(x['name']), "<a class='button secondary' href='/lists/filler'>Back to Filler</a>") + f"""
<div class='card'><form method='post' action='/lists/filler/{filler_id}/save'><div class='grid3'><div><label>Name</label><input name='name' value='{_e(x['name'])}' required><label>Filler Kind</label><select name='filler_kind'>{kinds}</select><label><input type='checkbox' name='enabled' value='1' {'checked' if x['enabled'] else ''}> Enabled</label></div><div><label>Collection</label><select name='collection_id'>{copts}</select><label>Local Library (legacy source)</label><select name='library_id'>{lopts}</select></div><div><label>Mode</label><select name='fill_mode'>{modes}</select><label>Count clips</label><input type='number' name='count_items' value='{int(x['count_items'] or 1)}' min='1' max='100'><label>Duration seconds</label><input type='number' name='duration_seconds' value='{int(x['duration_seconds'] or 120)}' min='1' max='3600'><label>Pad minutes</label><input type='number' name='pad_minutes' value='{int(x['pad_minutes'] or 30)}' min='1' max='180'><label>Mid-roll breaks</label><input type='number' name='midroll_breaks' value='{int(x['midroll_breaks'] or 1)}' min='1' max='8'></div></div><label><input type='checkbox' name='trim_to_fit' value='1' {'checked' if x['trim_to_fit'] else ''}> Trim final filler clip at exact boundaries</label><button>Save Filler Preset</button></form></div>"""
    return _page('Edit Filler', body)

def _graphics_page(msg: str = '') -> str:
    with _db() as conn:
        graphics = conn.execute('SELECT * FROM graphics_elements ORDER BY name').fetchall(); channels = conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall(); assigns = conn.execute('SELECT cg.*,c.number,c.name channel_name,ge.name graphic_name FROM channel_graphics cg JOIN channels c ON c.id=cg.channel_id JOIN graphics_elements ge ON ge.id=cg.graphic_id ORDER BY CAST(c.number AS REAL),c.number,ge.name').fetchall()
    rows = ''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{_e(x['kind'])}</td><td>{_e(x['location'])}</td><td>{x['opacity_percent']}%</td><td>{_e(x['image_path'] or x['text_template'] or '')}</td><td><a class='button secondary' href='/system/graphics/{x['id']}/edit'>Edit</a> <form class='inline' method='post' action='/system/graphics/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for x in graphics) or '<tr><td colspan="6">No graphics.</td></tr>'
    arows = ''.join(f"<tr><td>{_e(x['number'])} {_e(x['channel_name'])}</td><td>{_e(x['graphic_name'])}</td><td>{_e(x['scope'])}</td><td><form class='inline' method='post' action='/system/graphics/assignment/delete'><input type='hidden' name='channel_id' value='{x['channel_id']}'><input type='hidden' name='graphic_id' value='{x['graphic_id']}'><button class='danger'>Remove</button></form></td></tr>" for x in assigns) or '<tr><td colspan="4">No channel graphics assigned.</td></tr>'
    copts = ''.join(f"<option value='{x['id']}'>{_e(x['number'])} {_e(x['name'])}</option>" for x in channels); gopts = ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in graphics)
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Graphics & Branding', 'Reusable station bugs, lower-thirds and dynamic text overlays. Graphics can be assigned globally to channels, Blocks/Decos, or toggled by Sequential schedules.') + f"""
<div class='card'><h2>Create Graphic</h2><form method='post' action='/system/graphics/add'><div class='grid3'><div><label>Name</label><input name='name' required placeholder='ViperTV Bug'><label>Type</label><select name='kind'><option value='image'>Image</option><option value='text'>Dynamic Text</option></select><label>Image path</label><input name='image_path' placeholder='/data/logos/vipertv.png'><label>Text template</label><textarea name='text_template' rows='3' placeholder='Up Next: {{show_title}}'></textarea></div><div><label>Location</label><select name='location'><option>TopLeft</option><option>TopRight</option><option>BottomLeft</option><option selected>BottomRight</option><option>Center</option></select><label>Horizontal margin %</label><input type='number' step='0.1' name='horizontal_margin_percent' value='3'><label>Vertical margin %</label><input type='number' step='0.1' name='vertical_margin_percent' value='3'><label>Image width %</label><input type='number' step='0.1' name='scale_width_percent' value='12'><label>Opacity %</label><input type='number' step='1' name='opacity_percent' value='90'></div><div><label>Font size</label><input type='number' name='font_size' value='32'><label>Text color</label><input name='text_color' value='white'><label><input type='checkbox' name='box_enabled' value='1'> Text background box</label><label>Start seconds</label><input type='number' step='0.1' name='start_seconds' value='0'><label>End seconds (blank = persistent)</label><input type='number' step='0.1' name='end_seconds'><label>Z-index</label><input type='number' name='z_index' value='1'></div></div><p class='muted small'>Dynamic text variables: {{channel_name}}, {{channel_number}}, {{title}}, {{show_title}}, {{episode_title}}, {{season}}, {{episode}}, {{year}}, {{now}}.</p><button>Create Graphic</button></form></div>
<div class='card'><h2>Graphics Library</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Type</th><th>Location</th><th>Opacity</th><th>Source / Text</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='grid'><div class='card'><h2>Assign To Channel</h2><form method='post' action='/system/graphics/assign'><label>Channel</label><select name='channel_id'>{copts}</select><label>Graphic</label><select name='graphic_id'>{gopts}</select><label>Scope</label><select name='scope'><option value='all'>All content</option><option value='primary'>Primary only</option><option value='filler'>Filler only</option></select><button>Assign</button></form></div><div class='card'><h2>Assignments</h2><div class='table-wrap'><table><thead><tr><th>Channel</th><th>Graphic</th><th>Scope</th><th></th></tr></thead><tbody>{arows}</tbody></table></div></div></div>"""
    return _page('Graphics & Branding', body)



def _graphics_edit_page(graphic_id: int, msg: str = '') -> str:
    with _db() as conn:
        x = conn.execute('SELECT * FROM graphics_elements WHERE id=?', (graphic_id,)).fetchone()
    if not x:
        raise HTTPException(404, 'Graphic not found')
    locs = ''.join(f"<option {'selected' if str(x['location'])==loc else ''}>{loc}</option>" for loc in ['TopLeft','TopRight','BottomLeft','BottomRight','Center'])
    kinds = ''.join(f"<option value='{k}' {'selected' if str(x['kind'])==k else ''}>{label}</option>" for k,label in [('image','Image'),('text','Dynamic Text')])
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Graphic', str(x['name']), "<a class='button secondary' href='/system/graphics'>Back to Graphics</a>") + f"""
<div class='card'><form method='post' action='/system/graphics/{graphic_id}/save'><div class='grid3'><div><label>Name</label><input name='name' value='{_e(x['name'])}' required><label>Type</label><select name='kind'>{kinds}</select><label>Image path</label><input name='image_path' value='{_e(x['image_path'] or '')}'><label>Text template</label><textarea name='text_template' rows='3'>{_e(x['text_template'] or '')}</textarea><label><input type='checkbox' name='enabled' value='1' {'checked' if x['enabled'] else ''}> Enabled</label></div><div><label>Location</label><select name='location'>{locs}</select><label>Horizontal margin %</label><input type='number' step='0.1' name='horizontal_margin_percent' value='{x['horizontal_margin_percent']}'><label>Vertical margin %</label><input type='number' step='0.1' name='vertical_margin_percent' value='{x['vertical_margin_percent']}'><label>Image width %</label><input type='number' step='0.1' name='scale_width_percent' value='{x['scale_width_percent']}'><label>Opacity %</label><input type='number' step='1' name='opacity_percent' value='{x['opacity_percent']}'></div><div><label>Font size</label><input type='number' name='font_size' value='{x['font_size']}'><label>Text color</label><input name='text_color' value='{_e(x['text_color'])}'><label><input type='checkbox' name='box_enabled' value='1' {'checked' if x['box_enabled'] else ''}> Text background box</label><label>Start seconds</label><input type='number' step='0.1' name='start_seconds' value='{x['start_seconds']}'><label>End seconds</label><input type='number' step='0.1' name='end_seconds' value='{'' if x['end_seconds'] is None else x['end_seconds']}'><label>Z-index</label><input type='number' name='z_index' value='{x['z_index']}'></div></div><button>Save Graphic</button></form></div>"""
    return _page('Edit Graphic', body)

def _sequential_index(msg: str = '') -> str:
    with _db() as conn:
        schedules = conn.execute('SELECT * FROM sequential_schedules ORDER BY name').fetchall(); channels = conn.execute('SELECT id,number,name FROM channels ORDER BY CAST(number AS REAL),number').fetchall(); assigned = {int(r['channel_id']): r for r in conn.execute('SELECT sp.*,ss.name schedule_name FROM sequential_playouts sp JOIN sequential_schedules ss ON ss.id=sp.schedule_id')}
    rows = ''.join(f"<tr><td><b>{_e(x['name'])}</b></td><td>{_e(x['updated_at'][:19].replace('T',' '))}</td><td><a class='button secondary' href='/scheduling/sequential/{x['id']}'>Edit YAML</a> <form class='inline' method='post' action='/scheduling/sequential/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>" for x in schedules) or '<tr><td colspan="3">No Sequential schedules.</td></tr>'
    assign_rows = []
    for c in channels:
        a = assigned.get(int(c['id']))
        opts = "<option value=''>— No Sequential Schedule —</option>" + ''.join(f"<option value='{x['id']}' {'selected' if a and int(a['schedule_id'])==int(x['id']) else ''}>{_e(x['name'])}</option>" for x in schedules)
        assign_rows.append(f"<tr><td>{_e(c['number'])}</td><td>{_e(c['name'])}</td><td>{_e(a['schedule_name']) if a else 'Not assigned'}</td><td><form class='inline' method='post' action='/scheduling/sequential-playouts/{c['id']}/assign'><select name='schedule_id'>{opts}</select><button>Assign</button></form>" + (f" <form class='inline' method='post' action='/scheduling/sequential-playouts/{c['id']}/reset'><button class='secondary'>Reset</button></form>" if a else '') + '</td></tr>')
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Sequential Scheduling', 'Power-user YAML schedules with reusable content sources, sequences, reset instructions and looping playout instructions.', "<a class='button secondary' href='/scheduling/blocks'>Blocks</a>") + f"""
<div class='card'><h2>Create Sequential Schedule</h2><form method='post' action='/scheduling/sequential/add'><label>Name</label><input name='name' required placeholder='Saturday Network'><button>Create With Starter YAML</button></form></div>
<div class='card'><h2>Schedules</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Updated</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Sequential Playouts</h2><p class='muted'>Assigning Sequential disables Block and Classic Playouts for that channel.</p><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Schedule</th><th></th></tr></thead><tbody>{''.join(assign_rows) or '<tr><td colspan="4">No channels.</td></tr>'}</tbody></table></div></div>"""
    return _page('Sequential Scheduling', body)


def _sequential_edit(schedule_id: int, msg: str = '') -> str:
    with _db() as conn:
        row = conn.execute('SELECT * FROM sequential_schedules WHERE id=?', (schedule_id,)).fetchone()
    if not row: raise HTTPException(404, 'Sequential schedule not found')
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(str(row['name']), 'Edit YAML. Save validates syntax and required top-level sections before replacing the active definition.', "<a class='button secondary' href='/scheduling/sequential'>Back</a>") + f"""
<div class='card'><form method='post' action='/scheduling/sequential/{schedule_id}/save'><label>Name</label><input name='name' value='{_e(row['name'])}' required><label>Sequential YAML</label><textarea name='yaml_text' rows='32' style='font-family:monospace'>{_e(row['yaml_text'])}</textarea><button>Validate & Save</button></form></div>
<div class='card'><h2>Supported Instructions</h2><p><b>Content:</b> search, collection, smart_collection, multi_collection, playlist, show, image and marathon. <b>Scheduling:</b> all, count, duration, pad_to_next, pad_until and sequence. <b>Control:</b> graphics_on/off, watermark, repeat, shuffle_sequence, skip_items, skip_to_item, wait_until and epg_group. Reset instructions run once before the playout loop.</p></div>"""
    return _page('Edit Sequential Schedule', body)



def _classic_extras_page(item_id: int, msg: str = '') -> str:
    with _db() as conn:
        item = conn.execute("SELECT csi.*,cs.name schedule_name FROM classic_schedule_items csi JOIN classic_schedules cs ON cs.id=csi.schedule_id WHERE csi.id=?", (item_id,)).fetchone()
        if not item:
            raise HTTPException(404, 'Classic schedule item not found')
        fillers = conn.execute('SELECT * FROM filler_presets WHERE enabled=1 ORDER BY name').fetchall()
        graphics = conn.execute('SELECT * FROM graphics_elements WHERE enabled=1 ORDER BY name').fetchall()
        selected_fillers = {int(r['filler_id']) for r in conn.execute('SELECT filler_id FROM classic_item_fillers WHERE schedule_item_id=?', (item_id,))}
        selected_graphics = {int(r['graphic_id']) for r in conn.execute('SELECT graphic_id FROM classic_item_graphics WHERE schedule_item_id=?', (item_id,))}
    filler_checks = ''.join(
        f"<label style='display:block;padding:6px 0'><input type='checkbox' name='filler_id' value='{x['id']}' {'checked' if int(x['id']) in selected_fillers else ''}>"
        f"<b>{_e(x['name'])}</b> <span class='badge'>{_e(x['filler_kind'])}</span> <span class='muted'>{_e(x['fill_mode'])}</span></label>"
        for x in fillers
    ) or "<div class='empty'>No filler presets exist yet. Create them under Lists → Filler.</div>"
    graphic_checks = ''.join(
        f"<label style='display:block;padding:6px 0'><input type='checkbox' name='graphic_id' value='{x['id']}' {'checked' if int(x['id']) in selected_graphics else ''}>"
        f"<b>{_e(x['name'])}</b> <span class='badge'>{_e(x['kind'])}</span></label>"
        for x in graphics
    ) or "<div class='empty'>No graphics exist yet. Create them under System → Graphics & Branding.</div>"
    title = str(item['label'] or _source_label(str(item['source_kind']), str(item['source_ref'])))
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Commercials / Filler & Graphics',
        f"Classic Schedule: {item['schedule_name']} — {title}",
        f"<a class='button secondary' href='/scheduling/schedule-item/{item_id}'>Back to Item</a> <a class='button secondary' href='/lists/filler'>Filler Presets</a> <a class='button secondary' href='/system/graphics'>Graphics</a>"
    ) + f"""
<div class='card'><form method='post' action='/scheduling/classic-item/{item_id}/extras/save'>
<div class='grid'><div><h2>Commercials / Filler</h2><p class='muted'>Attach any combination of Pre-roll, Mid-roll, Post-roll, Tail and Fallback presets. Mid-roll presets split long programmes; Tail runs when this Classic item group ends; Fallback replaces Off Air gaps associated with the item.</p>{filler_checks}</div>
<div><h2>Graphics / Branding</h2><p class='muted'>These graphics apply to primary programming from this schedule item. Channel graphics still apply according to their channel scope.</p>{graphic_checks}</div></div>
<button>Save Extras</button></form></div>"""
    return _page('Classic Item Extras', body)

def _install_routes(app) -> None:
    @app.get('/scheduling/classic-item/{item_id}/extras', response_class=HTMLResponse)
    def v12_classic_extras(item_id: int, msg: str = ''):
        return _classic_extras_page(item_id, msg)

    @app.post('/scheduling/classic-item/{item_id}/extras/save')
    def v12_classic_extras_save(item_id: int, filler_id: list[int] = Form(default=[]), graphic_id: list[int] = Form(default=[])):
        with _db() as conn:
            row = conn.execute('SELECT schedule_id FROM classic_schedule_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Classic schedule item not found')
            conn.execute('DELETE FROM classic_item_fillers WHERE schedule_item_id=?', (item_id,))
            conn.execute('DELETE FROM classic_item_graphics WHERE schedule_item_id=?', (item_id,))
            for fid in filler_id:
                conn.execute('INSERT OR IGNORE INTO classic_item_fillers(schedule_item_id,filler_id) VALUES(?,?)', (item_id, int(fid)))
            for gid in graphic_id:
                conn.execute('INSERT OR IGNORE INTO classic_item_graphics(schedule_item_id,graphic_id) VALUES(?,?)', (item_id, int(gid)))
            conn.execute('UPDATE classic_schedules SET updated_at=? WHERE id=?', (_now(), int(row['schedule_id'])))
            conn.commit()
        G['_classic_invalidate']()
        return RedirectResponse(f'/scheduling/classic-item/{item_id}/extras?msg=Extras+saved', 303)

    @app.get('/scheduling/blocks/{block_id}', response_class=HTMLResponse)
    def v12_block_edit(block_id: int, msg: str = ''): return _block_editor(block_id, msg)

    @app.post('/scheduling/blocks/add')
    def v12_block_add(name: str = Form(...), duration_minutes: int = Form(30)):
        try:
            with _db() as conn:
                cur = conn.execute('INSERT INTO blocks(name,duration_minutes,created_at,updated_at) VALUES(?,?,?,?)', (name.strip(), max(1,min(1440,duration_minutes)), _now(), _now())); conn.commit(); bid = cur.lastrowid
            return RedirectResponse(f'/scheduling/blocks/{bid}', 303)
        except sqlite3.IntegrityError:
            return RedirectResponse('/scheduling/blocks?msg=' + quote('A Block with that name already exists.'), 303)

    @app.post('/scheduling/blocks/{block_id}/settings')
    def v12_block_settings(block_id: int, name: str = Form(...), duration_minutes: int = Form(30)):
        with _db() as conn:
            conn.execute('UPDATE blocks SET name=?,duration_minutes=?,updated_at=? WHERE id=?', (name.strip(), max(1,min(1440,duration_minutes)), _now(), block_id)); conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/blocks/{block_id}?msg=Saved', 303)

    @app.post('/scheduling/blocks/{block_id}/delete')
    def v12_block_delete(block_id: int):
        with _db() as conn:
            conn.execute('DELETE FROM blocks WHERE id=?', (block_id,)); conn.commit()
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse('/scheduling/blocks?msg=Block+deleted', 303)

    @app.post('/scheduling/blocks/{block_id}/items/add')
    def v12_block_item_add(block_id: int, source_choice: str = Form(...), playback_order: str = Form('chronological'), show_in_epg: int = Form(0), disable_watermarks: int = Form(0), filler_id: list[int] = Form(default=[]), graphic_id: list[int] = Form(default=[])):
        try: kind, ref = source_choice.split('|', 1)
        except Exception: raise HTTPException(400, 'Invalid source')
        with _db() as conn:
            pos = int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM block_items WHERE block_id=?', (block_id,)).fetchone()['p'])
            cur = conn.execute('INSERT INTO block_items(block_id,position,source_kind,source_ref,playback_order,show_in_epg,disable_watermarks,created_at) VALUES(?,?,?,?,?,?,?,?)', (block_id,pos,kind,ref,playback_order,1 if show_in_epg else 0,1 if disable_watermarks else 0,_now())); iid=cur.lastrowid
            for fid in filler_id: conn.execute('INSERT OR IGNORE INTO block_item_fillers(block_item_id,filler_id) VALUES(?,?)', (iid,int(fid)))
            for gid in graphic_id: conn.execute('INSERT OR IGNORE INTO block_item_graphics(block_item_id,graphic_id) VALUES(?,?)', (iid,int(gid)))
            conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/blocks/{block_id}?msg=Item+added', 303)

    @app.get('/scheduling/block-items/{item_id}/edit', response_class=HTMLResponse)
    def v12_block_item_edit(item_id: int, msg: str = ''):
        return _block_item_edit_page(item_id, msg)

    @app.post('/scheduling/block-items/{item_id}/save')
    def v12_block_item_save(item_id:int,source_choice:str=Form(...),playback_order:str=Form('chronological'),show_in_epg:int=Form(0),disable_watermarks:int=Form(0),filler_id:list[int]=Form(default=[]),graphic_id:list[int]=Form(default=[])):
        try: kind, ref = source_choice.split('|', 1)
        except Exception: raise HTTPException(400, 'Invalid source')
        with _db() as conn:
            cur=conn.execute('SELECT block_id FROM block_items WHERE id=?',(item_id,)).fetchone()
            if not cur: raise HTTPException(404, 'Block item not found')
            conn.execute('UPDATE block_items SET source_kind=?,source_ref=?,playback_order=?,show_in_epg=?,disable_watermarks=? WHERE id=?',(kind,ref,playback_order,1 if show_in_epg else 0,1 if disable_watermarks else 0,item_id))
            conn.execute('DELETE FROM block_item_fillers WHERE block_item_id=?',(item_id,));conn.execute('DELETE FROM block_item_graphics WHERE block_item_id=?',(item_id,))
            for fid in filler_id: conn.execute('INSERT OR IGNORE INTO block_item_fillers(block_item_id,filler_id) VALUES(?,?)',(item_id,int(fid)))
            for gid in graphic_id: conn.execute('INSERT OR IGNORE INTO block_item_graphics(block_item_id,graphic_id) VALUES(?,?)',(item_id,int(gid)))
            conn.execute('UPDATE blocks SET updated_at=? WHERE id=?',(_now(),int(cur['block_id'])));conn.commit()
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse(f'/scheduling/block-items/{item_id}/edit?msg=Block+item+saved',303)

    @app.post('/scheduling/block-items/{item_id}/move')
    def v12_block_item_move(item_id: int, direction: str = Form(...)):
        with _db() as conn:
            cur = conn.execute('SELECT * FROM block_items WHERE id=?', (item_id,)).fetchone()
            if not cur:
                raise HTTPException(404, 'Block item not found')
            op = '<' if direction == 'up' else '>'
            order = 'DESC' if direction == 'up' else 'ASC'
            other = conn.execute(f'SELECT * FROM block_items WHERE block_id=? AND position {op} ? ORDER BY position {order},id {order} LIMIT 1', (cur['block_id'], cur['position'])).fetchone()
            if other:
                conn.execute('UPDATE block_items SET position=? WHERE id=?', (other['position'], cur['id']))
                conn.execute('UPDATE block_items SET position=? WHERE id=?', (cur['position'], other['id']))
                conn.execute('UPDATE blocks SET updated_at=? WHERE id=?', (_now(), cur['block_id']))
                conn.commit()
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse(f"/scheduling/blocks/{cur['block_id']}", 303)

    @app.post('/scheduling/block-items/{item_id}/delete')
    def v12_block_item_delete(item_id: int):
        with _db() as conn:
            r=conn.execute('SELECT block_id FROM block_items WHERE id=?',(item_id,)).fetchone(); conn.execute('DELETE FROM block_items WHERE id=?',(item_id,));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse(f"/scheduling/blocks/{r['block_id']}" if r else '/scheduling/blocks',303)

    @app.post('/scheduling/block-templates/add')
    def v12_template_add(name: str = Form(...)):
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO block_templates(name,created_at,updated_at) VALUES(?,?,?)',(name.strip(),_now(),_now()));conn.commit();tid=cur.lastrowid
            return RedirectResponse(f'/scheduling/block-templates/{tid}',303)
        except sqlite3.IntegrityError: return RedirectResponse('/scheduling/blocks?msg='+quote('Template name already exists.'),303)

    @app.get('/scheduling/block-templates/{template_id}', response_class=HTMLResponse)
    def v12_template_edit(template_id:int,msg:str=''): return _template_editor(template_id,msg)

    @app.post('/scheduling/block-templates/{template_id}/settings')
    def v12_template_settings(template_id: int, name: str = Form(...)):
        try:
            with _db() as conn:
                conn.execute('UPDATE block_templates SET name=?,updated_at=? WHERE id=?', (name.strip(), _now(), template_id)); conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/scheduling/block-templates/{template_id}?msg=' + quote('That template name is already in use.'), 303)
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse(f'/scheduling/block-templates/{template_id}?msg=Template+saved', 303)

    @app.post('/scheduling/block-templates/{template_id}/delete')
    def v12_template_delete(template_id: int):
        with _db() as conn:
            conn.execute('DELETE FROM block_templates WHERE id=?', (template_id,)); conn.commit()
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse('/scheduling/blocks?msg=Template+deleted', 303)

    @app.post('/scheduling/block-templates/{template_id}/slots/add')
    def v12_template_slot_add(template_id:int,start_time:str=Form(...),block_id:int=Form(...),deco_id:str=Form(''),days:list[str]=Form(default=[])):
        with _db() as conn:
            pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM block_template_slots WHERE template_id=?',(template_id,)).fetchone()['p']); conn.execute('INSERT INTO block_template_slots(template_id,day_mask,start_minute,block_id,deco_id,position) VALUES(?,?,?,?,?,?)',(template_id,_daymask(days),_hm_to_min(start_time),block_id,int(deco_id) if deco_id.isdigit() else None,pos));conn.execute('UPDATE block_templates SET updated_at=? WHERE id=?',(_now(),template_id));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/block-templates/{template_id}?msg=Slot+added',303)

    @app.post('/scheduling/block-slots/{slot_id}/delete')
    def v12_slot_delete(slot_id:int):
        with _db() as conn:
            r=conn.execute('SELECT template_id FROM block_template_slots WHERE id=?',(slot_id,)).fetchone();conn.execute('DELETE FROM block_template_slots WHERE id=?',(slot_id,));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse(f"/scheduling/block-templates/{r['template_id']}" if r else '/scheduling/blocks',303)

    @app.get('/scheduling/decos', response_class=HTMLResponse)
    def v12_decos(msg:str=''): return _decos_page(msg)

    @app.post('/scheduling/decos/add')
    def v12_deco_add(name:str=Form(...),watermark_mode:str=Form('inherit'),watermark_graphic_id:str=Form(''),use_watermark_during_filler:int=Form(0),default_filler_mode:str=Form('inherit'),default_filler_id:str=Form(''),trim_to_fit:int=Form(0),dead_air_mode:str=Form('inherit'),dead_air_filler_id:str=Form(''),graphic_id:list[int]=Form(default=[])):
        with _db() as conn:
            conn.execute('''INSERT INTO decos(name,watermark_mode,watermark_graphic_id,use_watermark_during_filler,default_filler_mode,default_filler_id,trim_to_fit,dead_air_mode,dead_air_filler_id,graphics_ids_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',(name.strip(),watermark_mode,int(watermark_graphic_id) if watermark_graphic_id.isdigit() else None,1 if use_watermark_during_filler else 0,default_filler_mode,int(default_filler_id) if default_filler_id.isdigit() else None,1 if trim_to_fit else 0,dead_air_mode,int(dead_air_filler_id) if dead_air_filler_id.isdigit() else None,json.dumps(graphic_id),_now(),_now()));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse('/scheduling/decos?msg=Deco+created',303)

    @app.get('/scheduling/decos/{deco_id}/edit', response_class=HTMLResponse)
    def v12_deco_edit(deco_id:int,msg:str=''):
        return _deco_edit_page(deco_id,msg)

    @app.post('/scheduling/decos/{deco_id}/save')
    def v12_deco_save(deco_id:int,name:str=Form(...),watermark_mode:str=Form('inherit'),watermark_graphic_id:str=Form(''),use_watermark_during_filler:int=Form(0),default_filler_mode:str=Form('inherit'),default_filler_id:str=Form(''),trim_to_fit:int=Form(0),dead_air_mode:str=Form('inherit'),dead_air_filler_id:str=Form(''),graphic_id:list[int]=Form(default=[])):
        try:
            with _db() as conn:
                conn.execute('''UPDATE decos SET name=?,watermark_mode=?,watermark_graphic_id=?,use_watermark_during_filler=?,default_filler_mode=?,default_filler_id=?,trim_to_fit=?,dead_air_mode=?,dead_air_filler_id=?,graphics_ids_json=?,updated_at=? WHERE id=?''',(name.strip(),watermark_mode,int(watermark_graphic_id) if watermark_graphic_id.isdigit() else None,1 if use_watermark_during_filler else 0,default_filler_mode,int(default_filler_id) if default_filler_id.isdigit() else None,1 if trim_to_fit else 0,dead_air_mode,int(dead_air_filler_id) if dead_air_filler_id.isdigit() else None,json.dumps(graphic_id),_now(),deco_id));conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/scheduling/decos/{deco_id}/edit?msg='+quote('That Deco name is already in use.'),303)
        BLOCK_DAY_CACHE.clear()
        return RedirectResponse(f'/scheduling/decos/{deco_id}/edit?msg=Deco+saved',303)

    @app.post('/scheduling/decos/{deco_id}/delete')
    def v12_deco_delete(deco_id:int):
        with _db() as conn: conn.execute('DELETE FROM decos WHERE id=?',(deco_id,));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse('/scheduling/decos?msg=Deco+deleted',303)

    @app.post('/scheduling/block-playouts/{channel_id}/assign')
    def v12_block_assign(channel_id:int,template_id:str=Form(''),default_deco_id:str=Form('')):
        now=_now()
        with _db() as conn:
            if template_id.isdigit():
                old=conn.execute('SELECT generation,template_id FROM block_playouts WHERE channel_id=?',(channel_id,)).fetchone(); gen=(int(old['generation'])+1 if old and int(old['template_id'])!=int(template_id) else int(old['generation']) if old else 0)
                conn.execute('INSERT INTO block_playouts(channel_id,template_id,default_deco_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET template_id=excluded.template_id,default_deco_id=excluded.default_deco_id,enabled=1,generation=?,updated_at=excluded.updated_at',(channel_id,int(template_id),int(default_deco_id) if default_deco_id.isdigit() else None,1,gen,now,now,gen)); conn.execute('DELETE FROM sequential_playouts WHERE channel_id=?',(channel_id,));conn.execute('DELETE FROM classic_playouts WHERE channel_id=?',(channel_id,))
            else: conn.execute('DELETE FROM block_playouts WHERE channel_id=?',(channel_id,))
            conn.commit()
        BLOCK_DAY_CACHE.clear();SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate'](channel_id); return RedirectResponse('/scheduling/blocks?msg=Block+playout+saved',303)

    @app.post('/scheduling/block-playouts/{channel_id}/reset')
    def v12_block_reset(channel_id:int):
        with _db() as conn: conn.execute('UPDATE block_playouts SET generation=generation+1,updated_at=? WHERE channel_id=?',(_now(),channel_id));conn.execute("DELETE FROM playout_state WHERE channel_id=? AND source_key LIKE 'block:%'",(channel_id,));conn.commit()
        BLOCK_DAY_CACHE.clear(); return RedirectResponse('/scheduling/blocks?msg=Block+playout+reset',303)

    # Replace old Filler UI through the already-registered /lists/filler route.
    G['filler_index_page'] = _filler_page

    @app.post('/lists/filler/v12/add')
    def v12_filler_add(name:str=Form(...),filler_kind:str=Form('postroll'),collection_id:str=Form(''),library_id:str=Form(''),fill_mode:str=Form('count'),count_items:int=Form(1),duration_seconds:int=Form(120),pad_minutes:int=Form(30),midroll_breaks:int=Form(1),trim_to_fit:int=Form(0)):
        if filler_kind not in ('preroll','midroll','postroll','tail','fallback'): filler_kind='postroll'
        if fill_mode not in ('count','duration','pad'): fill_mode='count'
        try:
            with _db() as conn:
                conn.execute('''INSERT INTO filler_presets(name,library_id,collection_id,interval_items,max_items,mode,enabled,filler_kind,fill_mode,count_items,duration_seconds,pad_minutes,trim_to_fit,midroll_breaks) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(name.strip(),int(library_id) if library_id.isdigit() else None,int(collection_id) if collection_id.isdigit() else None,1,max(1,count_items),'advanced',1,filler_kind,fill_mode,max(1,count_items),max(1,duration_seconds),max(1,pad_minutes),1 if trim_to_fit else 0,max(1,min(8,midroll_breaks))));conn.commit()
            return RedirectResponse('/lists/filler?msg=Filler+preset+created',303)
        except sqlite3.IntegrityError: return RedirectResponse('/lists/filler?msg='+quote('A filler preset with that name already exists.'),303)

    @app.get('/lists/filler/{filler_id}/edit', response_class=HTMLResponse)
    def v12_filler_edit(filler_id: int, msg: str = ''):
        return _filler_edit_page(filler_id, msg)

    @app.post('/lists/filler/{filler_id}/save')
    def v12_filler_save(filler_id:int,name:str=Form(...),filler_kind:str=Form('postroll'),collection_id:str=Form(''),library_id:str=Form(''),fill_mode:str=Form('count'),count_items:int=Form(1),duration_seconds:int=Form(120),pad_minutes:int=Form(30),midroll_breaks:int=Form(1),trim_to_fit:int=Form(0),enabled:int=Form(0)):
        if filler_kind not in ('preroll','midroll','postroll','tail','fallback'): filler_kind='postroll'
        if fill_mode not in ('count','duration','pad'): fill_mode='count'
        try:
            with _db() as conn:
                conn.execute('''UPDATE filler_presets SET name=?,library_id=?,collection_id=?,enabled=?,filler_kind=?,fill_mode=?,count_items=?,duration_seconds=?,pad_minutes=?,trim_to_fit=?,midroll_breaks=?,max_items=? WHERE id=?''',(name.strip(),int(library_id) if library_id.isdigit() else None,int(collection_id) if collection_id.isdigit() else None,1 if enabled else 0,filler_kind,fill_mode,max(1,count_items),max(1,duration_seconds),max(1,pad_minutes),1 if trim_to_fit else 0,max(1,min(8,midroll_breaks)),max(1,count_items),filler_id));conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/lists/filler/{filler_id}/edit?msg='+quote('A filler preset with that name already exists.'),303)
        BLOCK_DAY_CACHE.clear();SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate']()
        return RedirectResponse(f'/lists/filler/{filler_id}/edit?msg=Filler+preset+saved',303)

    @app.post('/lists/filler/{filler_id}/delete')
    def v12_filler_delete(filler_id:int):
        with _db() as conn: conn.execute('DELETE FROM filler_presets WHERE id=?',(filler_id,));conn.commit()
        BLOCK_DAY_CACHE.clear();SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate'](); return RedirectResponse('/lists/filler?msg=Filler+deleted',303)

    @app.get('/system/graphics', response_class=HTMLResponse)
    def v12_graphics(msg:str=''): return _graphics_page(msg)

    @app.post('/system/graphics/add')
    def v12_graphics_add(name:str=Form(...),kind:str=Form('image'),image_path:str=Form(''),text_template:str=Form(''),location:str=Form('BottomRight'),horizontal_margin_percent:float=Form(3),vertical_margin_percent:float=Form(3),scale_width_percent:float=Form(12),opacity_percent:float=Form(90),font_size:int=Form(32),text_color:str=Form('white'),box_enabled:int=Form(0),start_seconds:float=Form(0),end_seconds:str=Form(''),z_index:int=Form(1)):
        if kind not in ('image','text'): kind='image'
        try:
            with _db() as conn:
                conn.execute('''INSERT INTO graphics_elements(name,kind,image_path,text_template,location,horizontal_margin_percent,vertical_margin_percent,scale_width_percent,opacity_percent,font_size,text_color,box_enabled,start_seconds,end_seconds,z_index,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(name.strip(),kind,image_path.strip() or None,text_template.strip() or None,location,horizontal_margin_percent,vertical_margin_percent,scale_width_percent,max(0,min(100,opacity_percent)),max(8,font_size),text_color.strip() or 'white',1 if box_enabled else 0,max(0,start_seconds),float(end_seconds) if str(end_seconds).strip() else None,z_index,1,_now(),_now()));conn.commit()
            return RedirectResponse('/system/graphics?msg=Graphic+created',303)
        except sqlite3.IntegrityError: return RedirectResponse('/system/graphics?msg='+quote('A graphic with that name already exists.'),303)

    @app.get('/system/graphics/{graphic_id}/edit', response_class=HTMLResponse)
    def v12_graphic_edit(graphic_id: int, msg: str = ''):
        return _graphics_edit_page(graphic_id, msg)

    @app.post('/system/graphics/{graphic_id}/save')
    def v12_graphic_save(graphic_id:int,name:str=Form(...),kind:str=Form('image'),image_path:str=Form(''),text_template:str=Form(''),location:str=Form('BottomRight'),horizontal_margin_percent:float=Form(3),vertical_margin_percent:float=Form(3),scale_width_percent:float=Form(12),opacity_percent:float=Form(90),font_size:int=Form(32),text_color:str=Form('white'),box_enabled:int=Form(0),start_seconds:float=Form(0),end_seconds:str=Form(''),z_index:int=Form(1),enabled:int=Form(0)):
        if kind not in ('image','text'): kind='image'
        try:
            with _db() as conn:
                conn.execute('''UPDATE graphics_elements SET name=?,kind=?,image_path=?,text_template=?,location=?,horizontal_margin_percent=?,vertical_margin_percent=?,scale_width_percent=?,opacity_percent=?,font_size=?,text_color=?,box_enabled=?,start_seconds=?,end_seconds=?,z_index=?,enabled=?,updated_at=? WHERE id=?''',(name.strip(),kind,image_path.strip() or None,text_template.strip() or None,location,horizontal_margin_percent,vertical_margin_percent,scale_width_percent,max(0,min(100,opacity_percent)),max(8,font_size),text_color.strip() or 'white',1 if box_enabled else 0,max(0,start_seconds),float(end_seconds) if str(end_seconds).strip() else None,z_index,1 if enabled else 0,_now(),graphic_id));conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/system/graphics/{graphic_id}/edit?msg='+quote('A graphic with that name already exists.'),303)
        BLOCK_DAY_CACHE.clear();SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate']()
        return RedirectResponse(f'/system/graphics/{graphic_id}/edit?msg=Graphic+saved',303)

    @app.post('/system/graphics/{graphic_id}/delete')
    def v12_graphics_delete(graphic_id:int):
        with _db() as conn: conn.execute('DELETE FROM graphics_elements WHERE id=?',(graphic_id,));conn.commit()
        BLOCK_DAY_CACHE.clear();SEQUENTIAL_DAY_CACHE.clear();G['_classic_invalidate'](); return RedirectResponse('/system/graphics?msg=Graphic+deleted',303)

    @app.post('/system/graphics/assign')
    def v12_graphics_assign(channel_id:int=Form(...),graphic_id:int=Form(...),scope:str=Form('all')):
        if scope not in ('all','primary','filler'): scope='all'
        with _db() as conn: conn.execute('INSERT INTO channel_graphics(channel_id,graphic_id,scope) VALUES(?,?,?) ON CONFLICT(channel_id,graphic_id) DO UPDATE SET scope=excluded.scope',(channel_id,graphic_id,scope));conn.commit()
        return RedirectResponse('/system/graphics?msg=Graphic+assigned',303)

    @app.post('/system/graphics/assignment/delete')
    def v12_graphics_unassign(channel_id:int=Form(...),graphic_id:int=Form(...)):
        with _db() as conn: conn.execute('DELETE FROM channel_graphics WHERE channel_id=? AND graphic_id=?',(channel_id,graphic_id));conn.commit()
        return RedirectResponse('/system/graphics?msg=Assignment+removed',303)

    @app.get('/scheduling/sequential', response_class=HTMLResponse)
    def v12_seq_index(msg:str=''): return _sequential_index(msg)

    @app.post('/scheduling/sequential/add')
    def v12_seq_add(name:str=Form(...)):
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO sequential_schedules(name,yaml_text,created_at,updated_at) VALUES(?,?,?,?)',(name.strip(),SAMPLE_SEQUENTIAL_YAML,_now(),_now()));conn.commit();sid=cur.lastrowid
            return RedirectResponse(f'/scheduling/sequential/{sid}',303)
        except sqlite3.IntegrityError: return RedirectResponse('/scheduling/sequential?msg='+quote('That Sequential schedule name already exists.'),303)

    @app.get('/scheduling/sequential/{schedule_id}', response_class=HTMLResponse)
    def v12_seq_edit(schedule_id:int,msg:str=''): return _sequential_edit(schedule_id,msg)

    @app.post('/scheduling/sequential/{schedule_id}/save')
    def v12_seq_save(schedule_id:int,name:str=Form(...),yaml_text:str=Form(...)):
        try: _parse_yaml(yaml_text)
        except Exception as exc: return RedirectResponse(f'/scheduling/sequential/{schedule_id}?msg='+quote('YAML error: '+str(exc)),303)
        try:
            with _db() as conn: conn.execute('UPDATE sequential_schedules SET name=?,yaml_text=?,updated_at=? WHERE id=?',(name.strip(),yaml_text,_now(),schedule_id));conn.commit()
        except sqlite3.IntegrityError: return RedirectResponse(f'/scheduling/sequential/{schedule_id}?msg='+quote('That name is already in use.'),303)
        SEQUENTIAL_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/sequential/{schedule_id}?msg=Validated+and+saved',303)

    @app.post('/scheduling/sequential/{schedule_id}/delete')
    def v12_seq_delete(schedule_id:int):
        with _db() as conn: conn.execute('DELETE FROM sequential_schedules WHERE id=?',(schedule_id,));conn.commit()
        SEQUENTIAL_DAY_CACHE.clear(); return RedirectResponse('/scheduling/sequential?msg=Sequential+schedule+deleted',303)

    @app.post('/scheduling/sequential-playouts/{channel_id}/assign')
    def v12_seq_assign(channel_id:int,schedule_id:str=Form('')):
        now=_now()
        with _db() as conn:
            if schedule_id.isdigit():
                old=conn.execute('SELECT schedule_id,generation FROM sequential_playouts WHERE channel_id=?',(channel_id,)).fetchone(); gen=(int(old['generation'])+1 if old and int(old['schedule_id'])!=int(schedule_id) else int(old['generation']) if old else 0)
                conn.execute('INSERT INTO sequential_playouts(channel_id,schedule_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET schedule_id=excluded.schedule_id,enabled=1,generation=?,updated_at=excluded.updated_at',(channel_id,int(schedule_id),1,gen,now,now,gen));conn.execute('DELETE FROM block_playouts WHERE channel_id=?',(channel_id,));conn.execute('DELETE FROM classic_playouts WHERE channel_id=?',(channel_id,))
            else: conn.execute('DELETE FROM sequential_playouts WHERE channel_id=?',(channel_id,))
            conn.commit()
        SEQUENTIAL_DAY_CACHE.clear();BLOCK_DAY_CACHE.clear();G['_classic_invalidate'](channel_id); return RedirectResponse('/scheduling/sequential?msg=Sequential+playout+saved',303)

    @app.post('/scheduling/sequential-playouts/{channel_id}/reset')
    def v12_seq_reset(channel_id:int):
        with _db() as conn: conn.execute('UPDATE sequential_playouts SET generation=generation+1,updated_at=? WHERE channel_id=?',(_now(),channel_id));conn.execute("DELETE FROM playout_state WHERE channel_id=? AND source_key LIKE 'sequential:%'",(channel_id,));conn.commit()
        SEQUENTIAL_DAY_CACHE.clear(); return RedirectResponse('/scheduling/sequential?msg=Sequential+playout+reset',303)
