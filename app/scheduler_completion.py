from __future__ import annotations

import hashlib
import json
import math
import random
import re
import sqlite3
from typing import Any
from urllib.parse import quote

from fastapi import Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from . import advanced_scheduling as adv

G: dict[str, Any] = {}


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


def init_v127_db() -> None:
    """Additive v1.2.7 scheduler-completion schema. Never drops user data."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS marathons(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              searches_json TEXT NOT NULL DEFAULT '[]',
              group_by TEXT NOT NULL DEFAULT 'show',
              item_order TEXT NOT NULL DEFAULT 'chronological',
              play_all_items INTEGER NOT NULL DEFAULT 0,
              shuffle_groups INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_marathons_name ON marathons(name COLLATE NOCASE);
            """
        )
        add = G['add_column_if_missing']
        for col, ddl in [
            ('source_kind', "TEXT NOT NULL DEFAULT ''"),
            ('source_ref', "TEXT NOT NULL DEFAULT ''"),
            ('playback_order', "TEXT NOT NULL DEFAULT 'shuffle'"),
            ('midroll_strategy', "TEXT NOT NULL DEFAULT 'auto'"),
            ('minimum_primary_seconds', 'INTEGER NOT NULL DEFAULT 300'),
        ]:
            add(conn, 'filler_presets', col, ddl)
        # Chapter start times are optional metadata; older rows simply keep [].
        for table in ('media', 'plex_media', 'external_media'):
            add(conn, table, 'chapters_json', "TEXT NOT NULL DEFAULT '[]'")

        # Upgrade existing v1.2 filler rows into the generic reusable-source model.
        conn.execute("""UPDATE filler_presets
                        SET source_kind='collection', source_ref=CAST(collection_id AS TEXT)
                        WHERE COALESCE(source_kind,'')='' AND collection_id IS NOT NULL""")
        conn.execute("""UPDATE filler_presets
                        SET source_kind='local_library', source_ref=CAST(library_id AS TEXT)
                        WHERE COALESCE(source_kind,'')='' AND library_id IS NOT NULL""")
        conn.commit()


# ---------------------------- Marathons ----------------------------------

def _queries(row: Any) -> list[str]:
    try:
        raw = json.loads(row['searches_json'] or '[]')
        return [str(x).strip() for x in raw if str(x).strip()]
    except Exception:
        return []


def _uid(item: dict[str, Any]) -> str:
    return str(item.get('uid') or f"{item.get('source_type')}:{item.get('id') or item.get('rating_key') or item.get('external_id') or item.get('path') or item.get('title')}")


def _group_key(item: dict[str, Any], group_by: str) -> str:
    group_by = str(group_by or 'show').lower()
    if group_by == 'season':
        return f"{item.get('show_title') or item.get('title') or 'Unknown'}|S{G['safe_int'](item.get('season_number')) or 0:04d}"
    if group_by == 'artist':
        return str(item.get('artist') or item.get('show_title') or item.get('title') or 'Unknown')
    if group_by == 'album':
        return str(item.get('album') or item.get('artist') or item.get('show_title') or item.get('title') or 'Unknown')
    return str(item.get('show_title') or item.get('artist') or item.get('title') or 'Unknown')


def marathon_items(marathon_id: int, seed: str = '') -> list[dict[str, Any]]:
    with _db() as conn:
        row = conn.execute('SELECT * FROM marathons WHERE id=? AND enabled=1', (int(marathon_id),)).fetchone()
    if not row:
        return []
    combined: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in _queries(row):
        try:
            found = G['media_search_playable'](query)
        except Exception:
            found = []
        for raw in found:
            item = dict(raw)
            k = _uid(item)
            if k in seen:
                continue
            seen.add(k)
            combined.append(item)
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in combined:
        groups.setdefault(_group_key(item, str(row['group_by'])), []).append(item)
    keys = sorted(groups, key=lambda x: x.casefold())
    seed = seed or f"marathon:{marathon_id}"
    if row['shuffle_groups']:
        keys.sort(key=lambda k: hashlib.sha256(f'{seed}|group|{k}'.encode()).hexdigest())
    ordered_groups: list[list[dict[str, Any]]] = []
    for k in keys:
        ordered_groups.append(adv._order_pool(groups[k], str(row['item_order'] or 'chronological'), f'{seed}|items|{k}'))
    out: list[dict[str, Any]] = []
    if row['play_all_items']:
        for group in ordered_groups:
            out.extend(group)
    else:
        # One item from each group, then return to the first group for its next item.
        max_len = max([len(x) for x in ordered_groups] or [0])
        for i in range(max_len):
            for group in ordered_groups:
                if i < len(group):
                    out.append(group[i])
    return [dict(x) for x in out]


def _marathon_counts(row: Any) -> tuple[int, int]:
    items = marathon_items(int(row['id']), f"preview:{row['id']}")
    groups = {_group_key(x, str(row['group_by'])) for x in items}
    return len(items), len(groups)


def _marathon_page(msg: str = '') -> str:
    with _db() as conn:
        rows = conn.execute('SELECT * FROM marathons ORDER BY name COLLATE NOCASE').fetchall()
    trs = []
    for r in rows:
        queries = _queries(r)
        trs.append(
            f"<tr><td><b>{_e(r['name'])}</b><div class='muted small'>{len(queries)} search source(s)</div></td>"
            f"<td>{_e(r['group_by'])}</td><td>{_e(r['item_order'])}</td>"
            f"<td>{'All items' if r['play_all_items'] else 'One per group'}</td><td>{'Shuffled' if r['shuffle_groups'] else 'Fixed'}</td>"
            f"<td><a class='button secondary' href='/scheduling/marathons/{r['id']}'>Edit</a> "
            f"<a class='button secondary' href='/scheduling/marathons/{r['id']}/preview'>Preview</a></td></tr>"
        )
    table = ''.join(trs) or "<tr><td colspan='6' class='empty'>No reusable Marathons yet.</td></tr>"
    notice = f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    body = notice + _heading(
        'Marathons',
        'Reusable rotating content sources for Classic Schedules, Blocks and Sequential YAML.',
        "<a class='button secondary' href='/scheduling/schedules'>Classic Schedules</a> <a class='button secondary' href='/scheduling/blocks'>Blocks</a> <a class='button secondary' href='/scheduling/sequential'>Sequential</a>"
    ) + f"""
<div class='grid'><div class='card'><h2>Create Marathon</h2><form method='post' action='/scheduling/marathons/add'>
<label>Name</label><input name='name' required placeholder='Sitcom Rotation'>
<label>Search sources — one Smart Search query per line</label><textarea name='searches' rows='7' placeholder='show_title:"M*A*S*H"&#10;show_title:"Cheers"&#10;show_title:"Night Court"'></textarea>
<div class='grid'><div><label>Group By</label><select name='group_by'><option value='show'>Show</option><option value='season'>Season</option><option value='artist'>Artist</option><option value='album'>Album</option></select></div>
<div><label>Item Order</label><select name='item_order'><option value='chronological'>Chronological</option><option value='shuffle'>Shuffle</option></select></div></div>
<label><input type='checkbox' name='play_all_items' value='1'> Play every item in a group before moving to the next group</label>
<label><input type='checkbox' name='shuffle_groups' value='1'> Shuffle group order</label>
<button>Create Marathon</button></form></div>
<div class='card'><h2>How rotation works</h2><p><b>One per group</b> rotates one episode/song from each show, season, artist or album before returning to that group for its next item. <b>Play all</b> finishes a whole group before moving on.</p><p>Search sources use the same Smart Search syntax as Media → Search, so Marathons can combine any number of shows, artists, albums, genres, years or technical filters.</p></div></div>
<div class='card'><h2>Saved Marathons</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Group</th><th>Item Order</th><th>Mode</th><th>Groups</th><th></th></tr></thead><tbody>{table}</tbody></table></div></div>"""
    return _page('Marathons', body)


def _marathon_edit_page(mid: int, msg: str = '') -> str:
    with _db() as conn:
        r = conn.execute('SELECT * FROM marathons WHERE id=?', (mid,)).fetchone()
    if not r:
        raise HTTPException(404, 'Marathon not found')
    searches = '\n'.join(_queries(r))
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Edit Marathon', str(r['name']), "<a class='button secondary' href='/scheduling/marathons'>Back</a>"
    ) + f"""
<div class='card'><form method='post' action='/scheduling/marathons/{mid}/save'><label>Name</label><input name='name' value='{_e(r['name'])}' required>
<label>Search sources — one per line</label><textarea name='searches' rows='10'>{_e(searches)}</textarea>
<div class='grid'><div><label>Group By</label><select name='group_by'>""" + ''.join(f"<option value='{x}' {'selected' if str(r['group_by'])==x else ''}>{x.title()}</option>" for x in ('show','season','artist','album')) + f"""</select></div>
<div><label>Item Order</label><select name='item_order'><option value='chronological' {'selected' if r['item_order']=='chronological' else ''}>Chronological</option><option value='shuffle' {'selected' if r['item_order']=='shuffle' else ''}>Shuffle</option></select></div></div>
<label><input type='checkbox' name='play_all_items' value='1' {'checked' if r['play_all_items'] else ''}> Play every item in each group</label>
<label><input type='checkbox' name='shuffle_groups' value='1' {'checked' if r['shuffle_groups'] else ''}> Shuffle groups</label>
<label><input type='checkbox' name='enabled' value='1' {'checked' if r['enabled'] else ''}> Enabled</label><button>Save Marathon</button></form>
<hr><form method='post' action='/scheduling/marathons/{mid}/delete' onsubmit="return confirm('Delete this Marathon? Existing schedule items that reference it will become empty until changed.');"><button class='danger'>Delete Marathon</button></form></div>"""
    return _page('Edit Marathon', body)


def _marathon_preview(mid: int) -> str:
    with _db() as conn:
        r = conn.execute('SELECT * FROM marathons WHERE id=?', (mid,)).fetchone()
    if not r:
        raise HTTPException(404, 'Marathon not found')
    items = marathon_items(mid, f'preview:{mid}')
    rows = []
    for i, x in enumerate(items[:250], 1):
        rows.append(f"<tr><td>{i}</td><td>{_e(_group_key(x,str(r['group_by'])))}</td><td>{_e(x.get('show_title') or '')}</td><td>{_e(x.get('episode_title') or x.get('title') or '')}</td><td>{_e(x.get('artist') or '')}</td><td>{float(x.get('duration') or 0)/60:.1f} min</td></tr>")
    body = _heading('Marathon Preview', str(r['name']), f"<a class='button secondary' href='/scheduling/marathons/{mid}'>Edit</a>") + f"<div class='card'><p><b>{len(items):,}</b> playable items across <b>{len({_group_key(x,str(r['group_by'])) for x in items}):,}</b> groups. Showing the first {min(250,len(items)):,}.</p><div class='table-wrap'><table><thead><tr><th>#</th><th>Group</th><th>Show</th><th>Item</th><th>Artist</th><th>Duration</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=6>No matching media.</td></tr>'}</tbody></table></div></div>"
    return _page('Marathon Preview', body)


# ------------------------- Classic/Block source ----------------------------

def _wrap_sources() -> None:
    G['CLASSIC_SOURCE_KINDS'].add('marathon')
    base_catalog = G['_classic_source_catalog']
    base_label = G['_classic_source_label']
    base_items = G['_classic_source_items']

    def catalog():
        out = list(base_catalog())
        with _db() as conn:
            rows = conn.execute('SELECT id,name,group_by,item_order FROM marathons WHERE enabled=1 ORDER BY name COLLATE NOCASE').fetchall()
        for r in rows:
            out.append({'kind':'marathon','ref':str(r['id']),'label':f"Marathon — {r['name']} ({r['group_by']}, {r['item_order']})"})
        return out

    def label(kind: str, ref: str) -> str:
        if kind == 'marathon':
            try:
                with _db() as conn:
                    r = conn.execute('SELECT name FROM marathons WHERE id=?', (int(ref),)).fetchone()
                return f"Marathon — {r['name']}" if r else 'Marathon — missing source'
            except Exception:
                return 'Marathon — missing source'
        return base_label(kind, ref)

    def items(row):
        try:
            if str(row['source_kind']) == 'marathon':
                return marathon_items(int(row['source_ref']), f"schedule:{row.get('id') if hasattr(row,'get') else ''}")
        except Exception:
            pass
        return base_items(row)

    G['_classic_source_catalog'] = catalog
    G['_classic_source_label'] = label
    G['_classic_source_items'] = items


# -------------------------- Advanced Filler --------------------------------

def _fake_source_row(kind: str, ref: str):
    class R(dict):
        __getattr__ = dict.get
    return R(source_kind=kind, source_ref=ref, id=0)


def _filler_media_v127(preset: Any, seed: str) -> list[dict[str, Any]]:
    kind = str(preset['source_kind'] or '').strip() if 'source_kind' in preset.keys() else ''
    ref = str(preset['source_ref'] or '').strip() if 'source_ref' in preset.keys() else ''
    items: list[dict[str, Any]] = []
    try:
        if kind == 'local_library' and ref.isdigit():
            with _db() as conn:
                items = [{**dict(r), 'source_type':'local', 'air_date':None}
                         for r in conn.execute('SELECT * FROM media WHERE library_id=? AND duration>0 ORDER BY id', (int(ref),))]
        elif kind == 'marathon' and ref.isdigit():
            items = marathon_items(int(ref), seed)
        elif kind and ref:
            items = G['_classic_source_items'](_fake_source_row(kind, ref))
        elif preset['collection_id']:
            items = G['collection_media'](int(preset['collection_id']))
        elif preset['library_id']:
            with _db() as conn:
                items = [{**dict(r), 'source_type':'local', 'air_date':None}
                         for r in conn.execute('SELECT * FROM media WHERE library_id=? AND duration>0 ORDER BY id', (int(preset['library_id']),))]
    except Exception:
        items = []
    items = [dict(x) for x in items if float(x.get('duration') or 0) > 0]
    order = str(preset['playback_order'] or 'shuffle') if 'playback_order' in preset.keys() else 'shuffle'
    return adv._order_pool(items, order, f'{seed}|filler')


def _fallback_exact(preset: Any, seed: str, budget: float) -> list[dict[str, Any]]:
    budget = max(0.0, float(budget))
    if budget <= 0.5:
        return []
    pool = _filler_media_v127(preset, seed)
    if not pool:
        return []
    # Fallback is one deterministic item, looped and trimmed until the exact boundary.
    src = pool[0]
    src_dur = max(1.0, float(src.get('duration') or 0))
    out: list[dict[str, Any]] = []
    spent = 0.0
    loop = 0
    while spent < budget - 0.5 and loop < 10000:
        rem = budget - spent
        x = adv._mark_filler(src, 'fallback')
        x['_fallback_loop'] = loop
        if src_dur > rem + 0.5:
            x['_source_duration'] = src_dur
            x['_trim_limit'] = rem
            x['duration'] = rem
            out.append(x)
            spent += rem
            break
        out.append(x)
        spent += src_dur
        loop += 1
    return out


def _clip_fill_v127(preset: Any, seed: str, budget: float | None = None) -> list[dict[str, Any]]:
    if str(preset['filler_kind'] or '') == 'fallback' and budget is not None:
        return _fallback_exact(preset, seed, budget)
    return _BASE_CLIP_FILL(preset, seed, budget)


def _chapter_boundaries(item: dict[str, Any], duration: float) -> list[float]:
    raw = item.get('chapters_json') or '[]'
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = []
    vals: list[float] = []
    for x in data or []:
        try:
            if isinstance(x, dict):
                v = float(x.get('start') if x.get('start') is not None else x.get('start_seconds'))
            else:
                v = float(x)
        except Exception:
            continue
        if 20.0 < v < duration - 20.0:
            vals.append(v)
    vals = sorted(set(round(x, 3) for x in vals))
    return vals


def _choose_breaks(boundaries: list[float], duration: float, count: int) -> list[float]:
    count = max(1, min(8, int(count)))
    if boundaries:
        selected: list[float] = []
        available = list(boundaries)
        for n in range(1, count + 1):
            ideal = duration * n / (count + 1)
            if not available:
                break
            best = min(available, key=lambda x: abs(x - ideal))
            selected.append(best)
            available.remove(best)
        if selected:
            return sorted(selected)
    return [duration * n / (count + 1) for n in range(1, count + 1)]


def _split_midroll_v127(item: dict[str, Any], preset: Any, seed: str) -> list[dict[str, Any]]:
    duration = max(1.0, float(item.get('duration') or 0))
    min_primary = max(60, int(preset['minimum_primary_seconds'] or 300)) if 'minimum_primary_seconds' in preset.keys() else 300
    breaks = max(1, min(8, int(preset['midroll_breaks'] or 1)))
    if duration < min_primary:
        return [item]
    filler = adv._clip_fill(preset, seed)
    if not filler:
        return [item]
    strategy = str(preset['midroll_strategy'] or 'auto') if 'midroll_strategy' in preset.keys() else 'auto'
    chapter_points = _chapter_boundaries(item, duration) if strategy in ('auto','chapters') else []
    points = _choose_breaks(chapter_points if chapter_points else [], duration, breaks)
    # Avoid pathological tiny segments. If chapter metadata is poor, use even splits.
    pts = [0.0] + [p for p in points if 60.0 <= p <= duration - 60.0] + [duration]
    if len(pts) < 3 or any((pts[i+1]-pts[i]) < 45.0 for i in range(len(pts)-1)):
        points = _choose_breaks([], duration, breaks)
        pts = [0.0] + points + [duration]
    actual_breaks = max(0, len(pts) - 2)
    guide_total = duration + sum(float(x.get('duration') or 0) for x in filler) * actual_breaks
    out: list[dict[str, Any]] = []
    for n in range(len(pts)-1):
        start, end = pts[n], pts[n+1]
        seg = max(1.0, end-start)
        x = dict(item)
        x['_segment_start'] = start
        x['_source_duration'] = duration
        x['_trim_limit'] = seg
        x['duration'] = seg
        if n == 0:
            x['_guide_duration'] = guide_total
        else:
            x['_guide_hidden'] = True
        out.append(x)
        if n < len(pts)-2:
            out.extend(dict(y) for y in filler)
    return out


def _source_choice_options(selected_kind: str = '', selected_ref: str = '') -> str:
    opts = []
    for x in G['_classic_source_catalog']():
        sel = 'selected' if x['kind'] == selected_kind and str(x['ref']) == str(selected_ref) else ''
        opts.append(f"<option value='{_e(x['kind']+'|'+str(x['ref']))}' {sel}>{_e(x['label'])}</option>")
    with _db() as conn:
        libs = conn.execute('SELECT id,name FROM libraries ORDER BY name COLLATE NOCASE').fetchall()
    for l in libs:
        sel = 'selected' if selected_kind == 'local_library' and str(selected_ref) == str(l['id']) else ''
        opts.append(f"<option value='local_library|{l['id']}' {sel}>Local Library — {_e(l['name'])}</option>")
    return ''.join(opts) or "<option value=''>No reusable media sources are indexed yet</option>"


def _filler_source_label(row: Any) -> str:
    kind = str(row['source_kind'] or '') if 'source_kind' in row.keys() else ''
    ref = str(row['source_ref'] or '') if 'source_ref' in row.keys() else ''
    if kind == 'local_library' and ref.isdigit():
        with _db() as conn:
            r = conn.execute('SELECT name FROM libraries WHERE id=?', (int(ref),)).fetchone()
        return f"Local Library — {r['name']}" if r else 'Local Library — missing'
    if kind and ref:
        return G['_classic_source_label'](kind, ref)
    return ''


def _filler_page_v127(msg: str = '') -> str:
    with _db() as conn:
        presets = conn.execute('SELECT * FROM filler_presets ORDER BY name COLLATE NOCASE').fetchall()
    rows = []
    for x in presets:
        amount = str(x['count_items'])+' clip(s)' if x['fill_mode']=='count' else str(x['duration_seconds'])+' sec' if x['fill_mode']=='duration' else 'to '+str(x['pad_minutes'])+' min'
        extra = ''
        if str(x['filler_kind']) == 'midroll':
            extra = f" / {int(x['midroll_breaks'] or 1)} break(s), {_e(x['midroll_strategy'])}"
        rows.append(f"<tr><td><b>{_e(x['name'])}</b></td><td>{_e(x['filler_kind'])}</td><td>{_e(x['fill_mode'])}{extra}</td><td>{_e(_filler_source_label(x))}</td><td>{_e(amount)}</td><td><a class='button secondary' href='/lists/filler/{x['id']}/edit'>Edit</a> <form class='inline' method='post' action='/lists/filler/{x['id']}/delete'><button class='danger'>Delete</button></form></td></tr>")
    notice = f"<div class='msg'>{_e(msg)}</div>" if msg else ''
    body = notice + _heading('Advanced Filler','Reusable Pre-roll, Mid-roll, Post-roll, Tail and Fallback programming shared by Classic, Block and Sequential schedules.') + f"""
<div class='card'><h2>Create Filler Preset</h2><form method='post' action='/lists/filler/v127/add'>
<div class='grid3'><div><label>Name</label><input name='name' required placeholder='Commercial Break'><label>Filler Kind</label><select name='filler_kind'><option value='preroll'>Pre-roll</option><option value='midroll'>Mid-roll</option><option value='postroll' selected>Post-roll</option><option value='tail'>Tail</option><option value='fallback'>Fallback</option></select></div>
<div><label>Reusable Source</label><select name='source_choice' required>{_source_choice_options()}</select><label>Playback Order</label><select name='playback_order'><option value='shuffle' selected>Shuffle</option><option value='chronological'>Chronological</option><option value='random'>Random</option><option value='season_episode'>Season / Episode</option></select></div>
<div><label>Mode</label><select name='fill_mode'><option value='count'>Count</option><option value='duration'>Duration</option><option value='pad'>Pad to wall-clock multiple</option></select><label>Count clips</label><input type='number' name='count_items' value='2' min='1' max='100'><label>Duration seconds</label><input type='number' name='duration_seconds' value='120' min='1' max='7200'><label>Pad minutes</label><input type='number' name='pad_minutes' value='30' min='1' max='180'></div></div>
<div class='grid'><div><label>Mid-roll breaks</label><input type='number' name='midroll_breaks' value='1' min='1' max='8'><label>Mid-roll strategy</label><select name='midroll_strategy'><option value='auto'>Auto — chapter boundaries when available</option><option value='chapters'>Prefer chapter boundaries</option><option value='even'>Even time intervals</option></select></div><div><label>Minimum primary duration before mid-roll (seconds)</label><input type='number' name='minimum_primary_seconds' value='300' min='60' max='14400'><label><input type='checkbox' name='trim_to_fit' value='1' checked> Trim final filler clip at exact boundaries</label></div></div><button>Create Filler Preset</button></form></div>
<div class='card'><h2>Presets</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Kind</th><th>Mode</th><th>Source</th><th>Amount</th><th></th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan=6>No filler presets.</td></tr>'}</tbody></table></div></div>
<div class='grid'><div class='card'><h2>Placement</h2><p><b>Pre-roll</b> runs before each primary item. <b>Mid-roll</b> inserts breaks inside long programmes and now uses real chapter boundaries when available. <b>Post-roll</b> follows each item. <b>Tail</b> runs when the schedule-item run ends. <b>Fallback</b> loops one deterministic item and trims it exactly to fill an otherwise unscheduled gap.</p></div><div class='card'><h2>Modes</h2><p><b>Count</b> plays a set number of items. <b>Duration</b> fits complete items into a time budget. <b>Pad</b> fills to the next wall-clock multiple. Presets can use Collections, Playlists, Shows, Seasons, Images, Marathons or an entire Local Library.</p></div></div>"""
    return _page('Advanced Filler', body)


def _filler_edit_page_v127(fid: int, msg: str = '') -> str:
    with _db() as conn:
        x = conn.execute('SELECT * FROM filler_presets WHERE id=?', (fid,)).fetchone()
    if not x:
        raise HTTPException(404, 'Filler preset not found')
    kinds = ''.join(f"<option value='{k}' {'selected' if str(x['filler_kind'])==k else ''}>{label}</option>" for k,label in [('preroll','Pre-roll'),('midroll','Mid-roll'),('postroll','Post-roll'),('tail','Tail'),('fallback','Fallback')])
    modes = ''.join(f"<option value='{k}' {'selected' if str(x['fill_mode'])==k else ''}>{label}</option>" for k,label in [('count','Count'),('duration','Duration'),('pad','Pad to wall-clock multiple')])
    strategies = ''.join(f"<option value='{k}' {'selected' if str(x['midroll_strategy'])==k else ''}>{label}</option>" for k,label in [('auto','Auto — chapter boundaries when available'),('chapters','Prefer chapter boundaries'),('even','Even time intervals')])
    orders = ''.join(f"<option value='{k}' {'selected' if str(x['playback_order'])==k else ''}>{label}</option>" for k,label in [('shuffle','Shuffle'),('chronological','Chronological'),('random','Random'),('season_episode','Season / Episode')])
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Filler Preset', str(x['name']), "<a class='button secondary' href='/lists/filler'>Back to Filler</a>") + f"""
<div class='card'><form method='post' action='/lists/filler/{fid}/v127-save'><div class='grid3'><div><label>Name</label><input name='name' value='{_e(x['name'])}' required><label>Filler Kind</label><select name='filler_kind'>{kinds}</select><label><input type='checkbox' name='enabled' value='1' {'checked' if x['enabled'] else ''}> Enabled</label></div>
<div><label>Reusable Source</label><select name='source_choice'>{_source_choice_options(str(x['source_kind'] or ''),str(x['source_ref'] or ''))}</select><label>Playback Order</label><select name='playback_order'>{orders}</select></div>
<div><label>Mode</label><select name='fill_mode'>{modes}</select><label>Count clips</label><input type='number' name='count_items' value='{int(x['count_items'] or 1)}' min='1' max='100'><label>Duration seconds</label><input type='number' name='duration_seconds' value='{int(x['duration_seconds'] or 120)}' min='1' max='7200'><label>Pad minutes</label><input type='number' name='pad_minutes' value='{int(x['pad_minutes'] or 30)}' min='1' max='180'></div></div>
<div class='grid'><div><label>Mid-roll breaks</label><input type='number' name='midroll_breaks' value='{int(x['midroll_breaks'] or 1)}' min='1' max='8'><label>Mid-roll strategy</label><select name='midroll_strategy'>{strategies}</select></div><div><label>Minimum primary duration (seconds)</label><input type='number' name='minimum_primary_seconds' value='{int(x['minimum_primary_seconds'] or 300)}' min='60' max='14400'><label><input type='checkbox' name='trim_to_fit' value='1' {'checked' if x['trim_to_fit'] else ''}> Trim final filler clip at exact boundaries</label></div></div><button>Save Filler Preset</button></form></div>"""
    return _page('Edit Filler', body)


def _parse_source_choice(value: str) -> tuple[str, str]:
    if '|' not in str(value):
        raise ValueError('Choose a filler source.')
    kind, ref = str(value).split('|', 1)
    if kind not in G['CLASSIC_SOURCE_KINDS'] and kind != 'local_library':
        raise ValueError('Invalid filler source.')
    if not ref:
        raise ValueError('Choose a filler source.')
    return kind, ref


def _sequential_sources_v127(base):
    def wrapped(data: dict[str, Any], seed: str):
        # Expand references to saved Marathon objects into the inline format that
        # v1.2's sequential parser already understands.
        cloned = dict(data)
        content = []
        filler_entries = []
        for raw in data.get('content', []):
            if not isinstance(raw, dict):
                content.append(raw); continue
            entry = dict(raw)
            if 'marathon' in entry and isinstance(entry.get('marathon'), str):
                name = str(entry['marathon']).strip()
                with _db() as conn:
                    m = conn.execute('SELECT * FROM marathons WHERE name=? COLLATE NOCASE AND enabled=1', (name,)).fetchone()
                if m:
                    entry['marathon'] = {
                        'searches': _queries(m), 'group_by': str(m['group_by']),
                        'item_order': str(m['item_order']), 'play_all_items': bool(m['play_all_items']),
                        'shuffle_groups': bool(m['shuffle_groups'])
                    }
            if 'filler_preset' in entry:
                filler_entries.append(entry)
                continue
            content.append(entry)
        cloned['content'] = content
        out = base(cloned, seed)
        for entry in filler_entries:
            key = str(entry.get('key') or '').strip()
            name = str(entry.get('filler_preset') or '').strip()
            if not key or not name:
                continue
            with _db() as conn:
                p = conn.execute('SELECT * FROM filler_presets WHERE name=? COLLATE NOCASE AND enabled=1', (name,)).fetchone()
            if not p:
                out[key] = []
                continue
            items = _filler_media_v127(p, f'{seed}|filler-preset|{key}')
            marked = []
            for x in items:
                y = adv._mark_filler(x, str(p['filler_kind'] or 'postroll'))
                marked.append(y)
            out[key] = marked
        return out
    return wrapped


# ------------------------ UI finishing touches -----------------------------

def _wrap_block_editors() -> None:
    base_block = adv._block_editor
    base_template = adv._template_editor

    def block_editor(block_id: int, msg: str = '') -> str:
        html = base_block(block_id, msg)
        needle = "</div></main>"  # page shell ending, may not exist in body string
        # base returns a full page. Insert a small clone toolbar before final script/body.
        button = f"<form method='post' action='/scheduling/blocks/{block_id}/clone' style='display:inline'><button class='secondary'>Clone Block</button></form>"
        return html.replace("<a class='button secondary' href='/scheduling/blocks'>Back</a>", f"<a class='button secondary' href='/scheduling/blocks'>Back</a> {button}", 1)

    def template_editor(template_id: int, msg: str = '') -> str:
        html = base_template(template_id, msg)
        button = f"<form method='post' action='/scheduling/block-templates/{template_id}/clone' style='display:inline'><button class='secondary'>Clone Template</button></form>"
        return html.replace("<a class='button secondary' href='/scheduling/blocks'>Back</a>", f"<a class='button secondary' href='/scheduling/blocks'>Back</a> {button}", 1)

    adv._block_editor = block_editor
    adv._template_editor = template_editor


def _add_sidebar_link() -> None:
    # Sidebar is static HTML in page_shell. Safest is a targeted one-line source
    # update in main.py at build time; runtime pages then naturally include it.
    pass


def install_v127(app, main_globals: dict[str, Any]) -> None:
    global G, _BASE_CLIP_FILL
    G = main_globals

    # Additive migration chain.
    base_init = G['init_v12_db']
    def init_all():
        base_init(); init_v127_db()
    G['init_v12_db'] = init_all

    _wrap_sources()

    # Patch v1.2 filler/sequential behavior in place; the scheduling engines look
    # these names up from their module globals at runtime.
    adv._filler_media = _filler_media_v127
    _BASE_CLIP_FILL = adv._clip_fill
    adv._clip_fill = _clip_fill_v127
    adv._split_midroll = _split_midroll_v127
    adv._seq_content_sources = _sequential_sources_v127(adv._seq_content_sources)
    adv._filler_edit_page = _filler_edit_page_v127
    G['filler_index_page'] = _filler_page_v127
    G['marathon_items'] = marathon_items
    adv.SAMPLE_SEQUENTIAL_YAML = '''# ViperTV Sequential Schedule\ncontent:\n  - marathon: "Sitcom Rotation"\n    key: SHOWS\n  - filler_preset: "Commercial Break"\n    key: ADS\n\nsequences:\n  PRIME:\n    - count: 1\n      content: SHOWS\n    - count: 2\n      content: ADS\n\nreset:\n  - wait_until: "06:00"\n\nplayout:\n  - sequence: PRIME\n    repeat: 8\n  - pad_to_next: 30\n    content: ADS\n    trim: true\n  - repeat: true\n'''
    _wrap_block_editors()

    @app.get('/scheduling/marathons', response_class=HTMLResponse)
    def v127_marathons(msg: str = ''):
        return _marathon_page(msg)

    @app.post('/scheduling/marathons/add')
    def v127_marathon_add(name: str = Form(...), searches: str = Form(''), group_by: str = Form('show'), item_order: str = Form('chronological'), play_all_items: int = Form(0), shuffle_groups: int = Form(0)):
        if group_by not in ('show','season','artist','album'): group_by = 'show'
        if item_order not in ('chronological','shuffle'): item_order = 'chronological'
        qs = [x.strip() for x in searches.splitlines() if x.strip()]
        if not qs:
            return RedirectResponse('/scheduling/marathons?msg='+quote('Add at least one search source.'), 303)
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur = conn.execute('''INSERT INTO marathons(name,searches_json,group_by,item_order,play_all_items,shuffle_groups,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)''', (name.strip(), json.dumps(qs), group_by, item_order, 1 if play_all_items else 0, 1 if shuffle_groups else 0, 1, _now(), _now()))
                conn.commit(); mid = int(cur.lastrowid)
            G['_classic_invalidate'](); adv.BLOCK_DAY_CACHE.clear(); adv.SEQUENTIAL_DAY_CACHE.clear()
            return RedirectResponse(f'/scheduling/marathons/{mid}?msg=Marathon+created', 303)
        except sqlite3.IntegrityError:
            return RedirectResponse('/scheduling/marathons?msg='+quote('A Marathon with that name already exists.'), 303)

    @app.get('/scheduling/marathons/{mid}', response_class=HTMLResponse)
    def v127_marathon_edit(mid: int, msg: str = ''):
        return _marathon_edit_page(mid, msg)

    @app.post('/scheduling/marathons/{mid}/save')
    def v127_marathon_save(mid: int, name: str = Form(...), searches: str = Form(''), group_by: str = Form('show'), item_order: str = Form('chronological'), play_all_items: int = Form(0), shuffle_groups: int = Form(0), enabled: int = Form(0)):
        if group_by not in ('show','season','artist','album'): group_by = 'show'
        if item_order not in ('chronological','shuffle'): item_order = 'chronological'
        qs = [x.strip() for x in searches.splitlines() if x.strip()]
        if not qs:
            return RedirectResponse(f'/scheduling/marathons/{mid}?msg='+quote('Add at least one search source.'), 303)
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                conn.execute('''UPDATE marathons SET name=?,searches_json=?,group_by=?,item_order=?,play_all_items=?,shuffle_groups=?,enabled=?,updated_at=? WHERE id=?''', (name.strip(), json.dumps(qs), group_by, item_order, 1 if play_all_items else 0, 1 if shuffle_groups else 0, 1 if enabled else 0, _now(), mid)); conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/scheduling/marathons/{mid}?msg='+quote('That Marathon name is already in use.'), 303)
        G['_classic_invalidate'](); adv.BLOCK_DAY_CACHE.clear(); adv.SEQUENTIAL_DAY_CACHE.clear()
        return RedirectResponse(f'/scheduling/marathons/{mid}?msg=Marathon+saved', 303)

    @app.post('/scheduling/marathons/{mid}/delete')
    def v127_marathon_delete(mid: int):
        G['safe_backup_before_change']()
        with _db() as conn:
            conn.execute('DELETE FROM marathons WHERE id=?', (mid,)); conn.commit()
        G['_classic_invalidate'](); adv.BLOCK_DAY_CACHE.clear(); adv.SEQUENTIAL_DAY_CACHE.clear()
        return RedirectResponse('/scheduling/marathons?msg=Marathon+deleted', 303)

    @app.get('/scheduling/marathons/{mid}/preview', response_class=HTMLResponse)
    def v127_marathon_preview(mid: int):
        return _marathon_preview(mid)

    @app.post('/lists/filler/v127/add')
    def v127_filler_add(name: str = Form(...), filler_kind: str = Form('postroll'), source_choice: str = Form(...), playback_order: str = Form('shuffle'), fill_mode: str = Form('count'), count_items: int = Form(1), duration_seconds: int = Form(120), pad_minutes: int = Form(30), midroll_breaks: int = Form(1), midroll_strategy: str = Form('auto'), minimum_primary_seconds: int = Form(300), trim_to_fit: int = Form(0)):
        if filler_kind not in ('preroll','midroll','postroll','tail','fallback'): filler_kind='postroll'
        if fill_mode not in ('count','duration','pad'): fill_mode='count'
        if playback_order not in ('shuffle','chronological','random','season_episode'): playback_order='shuffle'
        if midroll_strategy not in ('auto','chapters','even'): midroll_strategy='auto'
        try: kind, ref = _parse_source_choice(source_choice)
        except ValueError as exc: return RedirectResponse('/lists/filler?msg='+quote(str(exc)),303)
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                collection_id = int(ref) if kind in ('collection','smart_collection','multi_collection') and ref.isdigit() else None
                library_id = int(ref) if kind=='local_library' and ref.isdigit() else None
                conn.execute('''INSERT INTO filler_presets(name,library_id,collection_id,interval_items,max_items,mode,enabled,filler_kind,fill_mode,count_items,duration_seconds,pad_minutes,trim_to_fit,midroll_breaks,source_kind,source_ref,playback_order,midroll_strategy,minimum_primary_seconds) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (name.strip(),library_id,collection_id,1,max(1,count_items),'advanced',1,filler_kind,fill_mode,max(1,count_items),max(1,duration_seconds),max(1,pad_minutes),1 if trim_to_fit else 0,max(1,min(8,midroll_breaks)),kind,ref,playback_order,midroll_strategy,max(60,min(14400,minimum_primary_seconds)))); conn.commit()
            return RedirectResponse('/lists/filler?msg=Filler+preset+created',303)
        except sqlite3.IntegrityError:
            return RedirectResponse('/lists/filler?msg='+quote('A filler preset with that name already exists.'),303)

    @app.post('/lists/filler/{fid}/v127-save')
    def v127_filler_save(fid: int, name: str = Form(...), filler_kind: str = Form('postroll'), source_choice: str = Form(...), playback_order: str = Form('shuffle'), fill_mode: str = Form('count'), count_items: int = Form(1), duration_seconds: int = Form(120), pad_minutes: int = Form(30), midroll_breaks: int = Form(1), midroll_strategy: str = Form('auto'), minimum_primary_seconds: int = Form(300), trim_to_fit: int = Form(0), enabled: int = Form(0)):
        if filler_kind not in ('preroll','midroll','postroll','tail','fallback'): filler_kind='postroll'
        if fill_mode not in ('count','duration','pad'): fill_mode='count'
        if playback_order not in ('shuffle','chronological','random','season_episode'): playback_order='shuffle'
        if midroll_strategy not in ('auto','chapters','even'): midroll_strategy='auto'
        try: kind, ref = _parse_source_choice(source_choice)
        except ValueError as exc: return RedirectResponse(f'/lists/filler/{fid}/edit?msg='+quote(str(exc)),303)
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                collection_id = int(ref) if kind in ('collection','smart_collection','multi_collection') and ref.isdigit() else None
                library_id = int(ref) if kind=='local_library' and ref.isdigit() else None
                conn.execute('''UPDATE filler_presets SET name=?,library_id=?,collection_id=?,enabled=?,filler_kind=?,fill_mode=?,count_items=?,duration_seconds=?,pad_minutes=?,trim_to_fit=?,midroll_breaks=?,max_items=?,source_kind=?,source_ref=?,playback_order=?,midroll_strategy=?,minimum_primary_seconds=? WHERE id=?''', (name.strip(),library_id,collection_id,1 if enabled else 0,filler_kind,fill_mode,max(1,count_items),max(1,duration_seconds),max(1,pad_minutes),1 if trim_to_fit else 0,max(1,min(8,midroll_breaks)),max(1,count_items),kind,ref,playback_order,midroll_strategy,max(60,min(14400,minimum_primary_seconds)),fid)); conn.commit()
        except sqlite3.IntegrityError:
            return RedirectResponse(f'/lists/filler/{fid}/edit?msg='+quote('A filler preset with that name already exists.'),303)
        adv.BLOCK_DAY_CACHE.clear(); adv.SEQUENTIAL_DAY_CACHE.clear(); G['_classic_invalidate']()
        return RedirectResponse(f'/lists/filler/{fid}/edit?msg=Filler+preset+saved',303)

    @app.post('/scheduling/blocks/{block_id}/clone')
    def v127_block_clone(block_id: int):
        G['safe_backup_before_change'](); now=_now()
        with _db() as conn:
            src=conn.execute('SELECT * FROM blocks WHERE id=?',(block_id,)).fetchone()
            if not src: raise HTTPException(404,'Block not found')
            base=f"{src['name']} Copy"; name=base; n=2
            while conn.execute('SELECT 1 FROM blocks WHERE name=? COLLATE NOCASE',(name,)).fetchone(): name=f'{base} {n}'; n+=1
            cur=conn.execute('INSERT INTO blocks(name,duration_minutes,created_at,updated_at) VALUES(?,?,?,?)',(name,src['duration_minutes'],now,now)); nid=int(cur.lastrowid)
            for bi in conn.execute('SELECT * FROM block_items WHERE block_id=? ORDER BY position,id',(block_id,)).fetchall():
                c=conn.execute('''INSERT INTO block_items(block_id,position,source_kind,source_ref,playback_order,show_in_epg,disable_watermarks,created_at) VALUES(?,?,?,?,?,?,?,?)''',(nid,bi['position'],bi['source_kind'],bi['source_ref'],bi['playback_order'],bi['show_in_epg'],bi['disable_watermarks'],now)); nb=int(c.lastrowid)
                for r in conn.execute('SELECT filler_id FROM block_item_fillers WHERE block_item_id=?',(bi['id'],)).fetchall(): conn.execute('INSERT INTO block_item_fillers(block_item_id,filler_id) VALUES(?,?)',(nb,r['filler_id']))
                for r in conn.execute('SELECT graphic_id FROM block_item_graphics WHERE block_item_id=?',(bi['id'],)).fetchall(): conn.execute('INSERT INTO block_item_graphics(block_item_id,graphic_id) VALUES(?,?)',(nb,r['graphic_id']))
            conn.commit()
        adv.BLOCK_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/blocks/{nid}?msg=Block+cloned',303)

    @app.post('/scheduling/block-templates/{template_id}/clone')
    def v127_template_clone(template_id: int):
        G['safe_backup_before_change'](); now=_now()
        with _db() as conn:
            src=conn.execute('SELECT * FROM block_templates WHERE id=?',(template_id,)).fetchone()
            if not src: raise HTTPException(404,'Template not found')
            base=f"{src['name']} Copy"; name=base; n=2
            while conn.execute('SELECT 1 FROM block_templates WHERE name=? COLLATE NOCASE',(name,)).fetchone(): name=f'{base} {n}'; n+=1
            cur=conn.execute('INSERT INTO block_templates(name,created_at,updated_at) VALUES(?,?,?)',(name,now,now)); nid=int(cur.lastrowid)
            for s in conn.execute('SELECT * FROM block_template_slots WHERE template_id=? ORDER BY start_minute,position,id',(template_id,)).fetchall():
                conn.execute('''INSERT INTO block_template_slots(template_id,day_mask,start_minute,block_id,deco_id,position) VALUES(?,?,?,?,?,?)''',(nid,s['day_mask'],s['start_minute'],s['block_id'],s['deco_id'],s['position']))
            conn.commit()
        adv.BLOCK_DAY_CACHE.clear(); return RedirectResponse(f'/scheduling/block-templates/{nid}?msg=Template+cloned',303)


# Assigned during install.
_BASE_CLIP_FILL = None
