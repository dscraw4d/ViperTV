from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime
from typing import Any
from urllib.parse import quote

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import advanced_scheduling as adv

G: dict[str, Any] = {}
_BASE_BLOCK_ASSIGNMENT = None
_BASE_BLOCK_DAY_ITEMS = None
_BASE_CHANNEL_MEDIA = None
_BASE_SCHEDULED_CURSOR = None


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


def _tz():
    return adv._tz()


def _day_checks(selected: int = 127) -> str:
    names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    return ' '.join(
        f"<label class='check'><input type='checkbox' name='days' value='{i}' {'checked' if selected & (1<<i) else ''}> {name}</label>"
        for i, name in enumerate(names)
    )


def _daymask(days: list[str]) -> int:
    return adv._daymask(days)


def _min_to_hm(v: int) -> str:
    return adv._min_to_hm(v)


def _hm_to_min(v: str) -> int:
    return adv._hm_to_min(v)


def init_v128_db() -> None:
    """Additive v1.2.8 schema. Never drops/replaces existing user data."""
    with _db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS deco_templates(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deco_template_slots(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              template_id INTEGER NOT NULL REFERENCES deco_templates(id) ON DELETE CASCADE,
              day_mask INTEGER NOT NULL DEFAULT 127,
              start_minute INTEGER NOT NULL,
              deco_id INTEGER NOT NULL REFERENCES decos(id) ON DELETE CASCADE,
              position INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_deco_template_slots
              ON deco_template_slots(template_id,start_minute,position,id);

            CREATE TABLE IF NOT EXISTS playout_templates(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              notes TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS playout_template_entries(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              playout_template_id INTEGER NOT NULL REFERENCES playout_templates(id) ON DELETE CASCADE,
              day_mask INTEGER NOT NULL DEFAULT 127,
              match_date TEXT,
              priority INTEGER NOT NULL DEFAULT 0,
              block_template_id INTEGER NOT NULL REFERENCES block_templates(id) ON DELETE CASCADE,
              deco_template_id INTEGER REFERENCES deco_templates(id) ON DELETE SET NULL,
              position INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_playout_template_entries
              ON playout_template_entries(playout_template_id,match_date,day_mask,priority,position,id);
            CREATE TABLE IF NOT EXISTS playout_template_playouts(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              playout_template_id INTEGER NOT NULL REFERENCES playout_templates(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL DEFAULT 1,
              generation INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS scripted_schedules(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              description TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scripted_schedule_items(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              schedule_id INTEGER NOT NULL REFERENCES scripted_schedules(id) ON DELETE CASCADE,
              air_date TEXT,
              day_mask INTEGER NOT NULL DEFAULT 127,
              start_minute INTEGER NOT NULL,
              source_kind TEXT NOT NULL,
              source_ref TEXT NOT NULL,
              playback_order TEXT NOT NULL DEFAULT 'chronological',
              count_items INTEGER NOT NULL DEFAULT 1,
              fill_to_next INTEGER NOT NULL DEFAULT 0,
              duration_seconds REAL,
              show_in_epg INTEGER NOT NULL DEFAULT 1,
              title_override TEXT,
              position INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_scripted_schedule_items
              ON scripted_schedule_items(schedule_id,air_date,start_minute,position,id);
            CREATE TABLE IF NOT EXISTS scripted_playouts(
              channel_id INTEGER PRIMARY KEY REFERENCES channels(id) ON DELETE CASCADE,
              schedule_id INTEGER NOT NULL REFERENCES scripted_schedules(id) ON DELETE CASCADE,
              enabled INTEGER NOT NULL DEFAULT 1,
              generation INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        # Scheduler assignments are mutually exclusive. Triggers also cover old
        # v1.1/v1.2 forms, so switching back to Classic/Block/Sequential cannot
        # accidentally leave a Scripted/Playout Template assignment active.
        conn.executescript(
            """
            CREATE TRIGGER IF NOT EXISTS v128_classic_exclusive_insert AFTER INSERT ON classic_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_classic_exclusive_update AFTER UPDATE ON classic_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_block_exclusive_insert AFTER INSERT ON block_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_block_exclusive_update AFTER UPDATE ON block_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_seq_exclusive_insert AFTER INSERT ON sequential_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_seq_exclusive_update AFTER UPDATE ON sequential_playouts
            BEGIN DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_scripted_exclusive_insert AFTER INSERT ON scripted_playouts
            BEGIN DELETE FROM classic_playouts WHERE channel_id=NEW.channel_id; DELETE FROM block_playouts WHERE channel_id=NEW.channel_id; DELETE FROM sequential_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_scripted_exclusive_update AFTER UPDATE ON scripted_playouts
            BEGIN DELETE FROM classic_playouts WHERE channel_id=NEW.channel_id; DELETE FROM block_playouts WHERE channel_id=NEW.channel_id; DELETE FROM sequential_playouts WHERE channel_id=NEW.channel_id; DELETE FROM playout_template_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_pt_exclusive_insert AFTER INSERT ON playout_template_playouts
            BEGIN DELETE FROM classic_playouts WHERE channel_id=NEW.channel_id; DELETE FROM block_playouts WHERE channel_id=NEW.channel_id; DELETE FROM sequential_playouts WHERE channel_id=NEW.channel_id; DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; END;
            CREATE TRIGGER IF NOT EXISTS v128_pt_exclusive_update AFTER UPDATE ON playout_template_playouts
            BEGIN DELETE FROM classic_playouts WHERE channel_id=NEW.channel_id; DELETE FROM block_playouts WHERE channel_id=NEW.channel_id; DELETE FROM sequential_playouts WHERE channel_id=NEW.channel_id; DELETE FROM scripted_playouts WHERE channel_id=NEW.channel_id; END;
            """
        )
        row = conn.execute("SELECT value FROM settings WHERE key='scripted_api_token'").fetchone()
        if not row or not str(row['value'] or '').strip():
            conn.execute("INSERT INTO settings(key,value) VALUES('scripted_api_token',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (secrets.token_urlsafe(32),))
        conn.commit()


# -------------------------- Deco Templates -------------------------------

def _deco_for_minute(template_id: int | None, minute: int, weekday_bit: int):
    if not template_id:
        return None
    with _db() as conn:
        row = conn.execute(
            '''SELECT d.* FROM deco_template_slots s JOIN decos d ON d.id=s.deco_id
               WHERE s.template_id=? AND (s.day_mask & ?) != 0 AND s.start_minute<=?
               ORDER BY s.start_minute DESC,s.position DESC,s.id DESC LIMIT 1''',
            (int(template_id), int(weekday_bit), max(0, min(1439, int(minute))))
        ).fetchone()
    return row


def _deco_templates_page(msg: str = '') -> str:
    with _db() as conn:
        rows = conn.execute('''SELECT t.*,COUNT(s.id) slot_count FROM deco_templates t
                               LEFT JOIN deco_template_slots s ON s.template_id=t.id
                               GROUP BY t.id ORDER BY t.name COLLATE NOCASE''').fetchall()
    tr = ''.join(
        f"<tr><td><b>{_e(r['name'])}</b></td><td>{int(r['slot_count'] or 0)}</td>"
        f"<td><a class='button secondary' href='/scheduling/deco-templates/{r['id']}'>Edit</a></td></tr>" for r in rows
    ) or "<tr><td colspan='3' class='empty'>No Deco Templates yet.</td></tr>"
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Deco Templates', 'Schedule reusable Decos across a generic broadcast day. Playout Templates pair these presentation timelines with Block Templates.',
        "<a class='button secondary' href='/scheduling/decos'>Decos</a> <a class='button secondary' href='/scheduling/playout-templates'>Playout Templates</a>"
    ) + f"""
<div class='grid'><div class='card'><h2>Create Deco Template</h2><form method='post' action='/scheduling/deco-templates/add'><label>Name</label><input name='name' required placeholder='Weekday Branding'><button>Create Template</button></form></div>
<div class='card'><h2>How it works</h2><p>Add timed Deco changes such as <b>06:00 Morning</b>, <b>17:00 Evening</b>, and <b>20:00 Prime Time</b>. A Block slot with its own explicit Deco still wins; otherwise the active Deco Template entry is used.</p></div></div>
<div class='card'><h2>Templates</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Timed entries</th><th></th></tr></thead><tbody>{tr}</tbody></table></div></div>"""
    return _page('Deco Templates', body)


def _deco_template_editor(tid: int, msg: str = '') -> str:
    with _db() as conn:
        t = conn.execute('SELECT * FROM deco_templates WHERE id=?', (tid,)).fetchone()
        if not t: raise HTTPException(404, 'Deco Template not found')
        slots = conn.execute('''SELECT s.*,d.name deco_name FROM deco_template_slots s JOIN decos d ON d.id=s.deco_id
                                WHERE s.template_id=? ORDER BY s.start_minute,s.position,s.id''', (tid,)).fetchall()
        decos = conn.execute('SELECT id,name FROM decos ORDER BY name COLLATE NOCASE').fetchall()
    rows = ''.join(
        f"<tr><td>{_min_to_hm(int(s['start_minute']))}</td><td>{_e(s['deco_name'])}</td><td>{_e(_mask_text(int(s['day_mask'])))}</td>"
        f"<td><form method='post' action='/scheduling/deco-templates/{tid}/slots/{s['id']}/delete'><button class='danger'>Remove</button></form></td></tr>" for s in slots
    ) or "<tr><td colspan='4' class='empty'>No timed Deco entries yet.</td></tr>"
    opts = ''.join(f"<option value='{d['id']}'>{_e(d['name'])}</option>" for d in decos)
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Edit Deco Template', str(t['name']), "<a class='button secondary' href='/scheduling/deco-templates'>Back</a>"
    ) + f"""
<div class='card'><form method='post' action='/scheduling/deco-templates/{tid}/save'><label>Name</label><input name='name' value='{_e(t['name'])}' required><button>Save Name</button></form></div>
<div class='card'><h2>Timed Deco Changes</h2><div class='table-wrap'><table><thead><tr><th>Start</th><th>Deco</th><th>Days</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Add Timed Deco</h2><form method='post' action='/scheduling/deco-templates/{tid}/slots/add'><div class='grid'><div><label>Start</label><input type='time' name='start_time' value='00:00'></div><div><label>Deco</label><select name='deco_id' required>{opts}</select></div></div><p>{_day_checks()}</p><button>Add Entry</button></form></div>
<div class='card'><form method='post' action='/scheduling/deco-templates/{tid}/delete' onsubmit="return confirm('Delete this Deco Template?');"><button class='danger'>Delete Deco Template</button></form></div>"""
    return _page('Edit Deco Template', body)


def _mask_text(mask: int) -> str:
    names = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
    if mask == 127: return 'Every day'
    return ', '.join(names[i] for i in range(7) if mask & (1 << i)) or 'None'


# ------------------------- Playout Templates -----------------------------

def _playout_template_resolution(channel_id: int, today=None):
    today = today or datetime.now(_tz()).date()
    bit = 1 << today.weekday()
    day = today.isoformat()
    with _db() as conn:
        ass = conn.execute('''SELECT pp.*,pt.name playout_template_name FROM playout_template_playouts pp
                              JOIN playout_templates pt ON pt.id=pp.playout_template_id
                              WHERE pp.channel_id=? AND pp.enabled=1''', (channel_id,)).fetchone()
        if not ass: return None
        ent = conn.execute('''SELECT e.*,bt.name block_template_name,dt.name deco_template_name
                              FROM playout_template_entries e
                              JOIN block_templates bt ON bt.id=e.block_template_id
                              LEFT JOIN deco_templates dt ON dt.id=e.deco_template_id
                              WHERE e.playout_template_id=?
                                AND (e.match_date=? OR (e.match_date IS NULL AND (e.day_mask & ?) != 0))
                              ORDER BY CASE WHEN e.match_date=? THEN 1 ELSE 0 END DESC,
                                       e.priority DESC,e.position ASC,e.id ASC LIMIT 1''',
                           (int(ass['playout_template_id']), day, bit, day)).fetchone()
    if not ent: return None
    return ass, ent


def _block_assignment_v128(channel_id: int):
    resolved = _playout_template_resolution(channel_id)
    if not resolved:
        return _BASE_BLOCK_ASSIGNMENT(channel_id)
    ass, ent = resolved
    with _db() as conn:
        bt = conn.execute('SELECT updated_at FROM block_templates WHERE id=?', (int(ent['block_template_id']),)).fetchone()
    return {
        'channel_id': int(channel_id), 'template_id': int(ent['block_template_id']), 'default_deco_id': None,
        'generation': int(ass['generation'] or 0), 'playout_updated': str(ass['updated_at']),
        'template_name': str(ent['block_template_name']), 'updated_at': str(bt['updated_at'] if bt else ass['updated_at']),
        '_deco_template_id': int(ent['deco_template_id']) if ent['deco_template_id'] else None,
        '_playout_template_id': int(ass['playout_template_id']), '_playout_entry_id': int(ent['id'])
    }


def _block_day_items_v128(channel_id: int) -> list[dict[str, Any]]:
    resolved = _playout_template_resolution(channel_id)
    if not resolved:
        return _BASE_BLOCK_DAY_ITEMS(channel_id)
    ass_row, entry = resolved
    ass = _block_assignment_v128(channel_id)
    today = datetime.now(_tz()).date()
    weekday_bit = 1 << today.weekday()
    deco_template_id = int(entry['deco_template_id']) if entry['deco_template_id'] else None
    key = ('v128pt', channel_id, int(entry['id']), int(ass_row['generation']), str(ass_row['updated_at']), today.isoformat())
    if key in adv.BLOCK_DAY_CACHE:
        return [dict(x) for x in adv.BLOCK_DAY_CACHE[key]]
    with _db() as conn:
        slots = conn.execute(
            '''SELECT s.*,b.name block_name,b.duration_minutes FROM block_template_slots s
               JOIN blocks b ON b.id=s.block_id WHERE s.template_id=? AND (s.day_mask & ?) != 0
               ORDER BY s.start_minute,s.position,s.id''', (int(entry['block_template_id']), weekday_bit)
        ).fetchall()
    if not slots:
        return []
    out: list[dict[str, Any]] = []
    cursor = 0.0
    seed_base = f"pt|{channel_id}|{entry['id']}|{ass_row['generation']}|{today.isoformat()}"

    def dynamic_deco(minute: int, explicit_id=None):
        if explicit_id:
            return adv._deco(int(explicit_id))
        return _deco_for_minute(deco_template_id, minute, weekday_bit)

    for si, slot in enumerate(slots):
        start = float(int(slot['start_minute']) * 60)
        if start > cursor + 0.5:
            d = dynamic_deco(int(cursor // 60))
            gap = adv._fill_gap_with_deco(start - cursor, d, f'{seed_base}|pre|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
        if cursor > start + 0.5:
            start = cursor
        next_start = float(int(slots[si + 1]['start_minute']) * 60) if si + 1 < len(slots) else 86400.0
        block_end = min(86400.0, start + max(1, int(slot['duration_minutes'])) * 60.0, next_start)
        with _db() as conn:
            bis = conn.execute('SELECT * FROM block_items WHERE block_id=? ORDER BY position,id', (int(slot['block_id']),)).fetchall()
        fixed_deco = adv._deco(int(slot['deco_id'])) if slot['deco_id'] else None
        if not bis:
            d = fixed_deco or dynamic_deco(int(cursor // 60))
            gap = adv._fill_gap_with_deco(block_end - cursor, d, f'{seed_base}|empty|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
            continue
        pools: dict[int, list[dict[str, Any]]] = {}
        positions: dict[int, int] = {}
        for bi in bis:
            pool = adv._order_pool(adv._source_items(str(bi['source_kind']), str(bi['source_ref'])), str(bi['playback_order']), f'{seed_base}|slot{si}|item{bi["id"]}')
            pools[int(bi['id'])] = pool; positions[int(bi['id'])] = 0
        rounds = 0
        while cursor < block_end - 0.5 and rounds < 10000:
            made = False
            for bi in bis:
                pool = pools.get(int(bi['id'])) or []
                if not pool or cursor >= block_end - 0.5: continue
                deco_row = fixed_deco or dynamic_deco(int(cursor // 60))
                pos = positions[int(bi['id'])] % len(pool)
                src = pool[pos]; positions[int(bi['id'])] += 1
                remaining = block_end - cursor
                primary = adv._block_primary_item(src, bi, deco_row, remaining)
                presets = adv._filler_presets_for('block', int(bi['id']))
                decorated, new_cursor = adv._decorate_with_presets(primary, presets, f'{seed_base}|slot{si}|bi{bi["id"]}|{positions[int(bi["id"])]}', cursor)
                for p in (x for x in presets if str(x['filler_kind']) == 'tail'):
                    decorated.extend(adv._clip_fill(p, f'{seed_base}|slot{si}|bi{bi["id"]}|tail|{positions[int(bi["id"])]}', max(0.0, block_end - new_cursor)))
                decorated = [adv._decorate_block_filler_for_deco(x, deco_row) if x.get('_filler_kind') else x for x in decorated]
                for x in decorated:
                    dur = max(1.0, float(x.get('duration') or 0)); rem = block_end - cursor
                    if rem <= 0.5: break
                    if dur > rem + 0.5:
                        x = dict(x); x['_source_duration'] = float(x.get('_source_duration') or dur); x['_trim_limit'] = rem; x['duration'] = rem
                        out.append(x); cursor += rem; break
                    out.append(x); cursor += dur
                made = True
            rounds += 1
            if not made: break
        if cursor < block_end - 0.5:
            d = fixed_deco or dynamic_deco(int(cursor // 60))
            gap = adv._fill_gap_with_deco(block_end - cursor, d, f'{seed_base}|tail|{si}')
            out.extend(gap); cursor += sum(float(x.get('duration') or 0) for x in gap)
    if cursor < 86400 - 0.5:
        d = _deco_for_minute(deco_template_id, int(cursor // 60), weekday_bit)
        gap = adv._fill_gap_with_deco(86400 - cursor, d, f'{seed_base}|daytail')
        out.extend(gap)
    total = 0.0; clipped = []
    for x in out:
        dur = max(1.0, float(x.get('duration') or 0))
        if total >= 86400 - 0.5: break
        if total + dur > 86400:
            x = dict(x); x['_source_duration'] = float(x.get('_source_duration') or dur); x['_trim_limit'] = 86400-total; x['duration'] = 86400-total
        clipped.append(x); total += float(x.get('duration') or 0)
    adv._day_anchor(clipped)
    for k in list(adv.BLOCK_DAY_CACHE):
        if (k and k[0] == channel_id) or (len(k) > 1 and k[0] == 'v128pt' and k[1] == channel_id):
            adv.BLOCK_DAY_CACHE.pop(k, None)
    adv.BLOCK_DAY_CACHE[key] = [dict(x) for x in clipped]
    return [dict(x) for x in clipped]


def _playout_templates_page(msg: str = '') -> str:
    with _db() as conn:
        pts = conn.execute('''SELECT p.*,COUNT(e.id) entry_count FROM playout_templates p LEFT JOIN playout_template_entries e ON e.playout_template_id=p.id GROUP BY p.id ORDER BY p.name COLLATE NOCASE''').fetchall()
        channels = conn.execute('SELECT id,number,name FROM channels ORDER BY number,name').fetchall()
        assigns = {int(r['channel_id']): r for r in conn.execute('''SELECT pp.*,pt.name template_name FROM playout_template_playouts pp JOIN playout_templates pt ON pt.id=pp.playout_template_id''').fetchall()}
    rows = ''.join(f"<tr><td><b>{_e(p['name'])}</b></td><td>{int(p['entry_count'] or 0)}</td><td><a class='button secondary' href='/scheduling/playout-templates/{p['id']}'>Edit</a></td></tr>" for p in pts) or "<tr><td colspan='3' class='empty'>No Playout Templates yet.</td></tr>"
    popts = "<option value=''>— None —</option>" + ''.join(f"<option value='{p['id']}'>{_e(p['name'])}</option>" for p in pts)
    crows = []
    for c in channels:
        a = assigns.get(int(c['id']))
        opts = popts
        if a: opts = opts.replace(f"value='{a['playout_template_id']}'", f"value='{a['playout_template_id']}' selected", 1)
        crows.append(f"<tr><td>{_e(c['number'])}</td><td>{_e(c['name'])}</td><td><form method='post' action='/scheduling/playout-template-playouts/{c['id']}/assign'><select name='playout_template_id'>{opts}</select><button>Save</button></form></td><td>{_e(a['template_name']) if a else '—'}</td></tr>")
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading(
        'Playout Templates', 'Combine Block Templates and Deco Templates by weekday or exact date. When more than one rule matches, the highest priority wins.',
        "<a class='button secondary' href='/scheduling/deco-templates'>Deco Templates</a> <a class='button secondary' href='/scheduling/blocks'>Block Templates</a>"
    ) + f"""
<div class='grid'><div class='card'><h2>Create Playout Template</h2><form method='post' action='/scheduling/playout-templates/add'><label>Name</label><input name='name' required placeholder='Main Channel Calendar'><label>Notes</label><textarea name='notes' rows='3'></textarea><button>Create</button></form></div>
<div class='card'><h2>Priority examples</h2><p><b>10</b> Weekdays → Weekday Blocks + Weekday Decos<br><b>20</b> Saturday → Saturday Blocks + Weekend Decos<br><b>100</b> 2026-12-25 → Christmas Blocks + Holiday Decos</p><p>An exact-date rule is considered before recurring weekday rules; priority breaks ties.</p></div></div>
<div class='card'><h2>Saved Playout Templates</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Rules</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Channel Assignments</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Template</th><th>Active</th></tr></thead><tbody>{''.join(crows) or '<tr><td colspan=4>No channels.</td></tr>'}</tbody></table></div></div>"""
    return _page('Playout Templates', body)


def _playout_template_editor(pid: int, msg: str = '') -> str:
    with _db() as conn:
        p = conn.execute('SELECT * FROM playout_templates WHERE id=?', (pid,)).fetchone()
        if not p: raise HTTPException(404, 'Playout Template not found')
        entries = conn.execute('''SELECT e.*,bt.name block_name,dt.name deco_name FROM playout_template_entries e
                                  JOIN block_templates bt ON bt.id=e.block_template_id LEFT JOIN deco_templates dt ON dt.id=e.deco_template_id
                                  WHERE e.playout_template_id=? ORDER BY e.priority DESC,e.position,e.id''', (pid,)).fetchall()
        blocks = conn.execute('SELECT id,name FROM block_templates ORDER BY name COLLATE NOCASE').fetchall()
        decos = conn.execute('SELECT id,name FROM deco_templates ORDER BY name COLLATE NOCASE').fetchall()
    rows = ''.join(
        f"<tr><td>{int(r['priority'])}</td><td>{_e(r['match_date'] or _mask_text(int(r['day_mask'])))}</td><td>{_e(r['block_name'])}</td><td>{_e(r['deco_name'] or 'None')}</td>"
        f"<td><form method='post' action='/scheduling/playout-templates/{pid}/entries/{r['id']}/delete'><button class='danger'>Remove</button></form></td></tr>" for r in entries
    ) or "<tr><td colspan='5' class='empty'>No rules yet.</td></tr>"
    bopts = ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in blocks)
    dopts = "<option value=''>— No Deco Template —</option>" + ''.join(f"<option value='{x['id']}'>{_e(x['name'])}</option>" for x in decos)
    body = (f"<div class='msg'>{_e(msg)}</div>" if msg else '') + _heading('Edit Playout Template', str(p['name']), "<a class='button secondary' href='/scheduling/playout-templates'>Back</a>") + f"""
<div class='card'><form method='post' action='/scheduling/playout-templates/{pid}/save'><label>Name</label><input name='name' value='{_e(p['name'])}' required><label>Notes</label><textarea name='notes' rows='3'>{_e(p['notes'] or '')}</textarea><button>Save</button></form></div>
<div class='card'><h2>Rules</h2><div class='table-wrap'><table><thead><tr><th>Priority</th><th>When</th><th>Block Template</th><th>Deco Template</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Add Rule</h2><form method='post' action='/scheduling/playout-templates/{pid}/entries/add'><div class='grid3'><div><label>Priority</label><input type='number' name='priority' value='10'></div><div><label>Exact date (optional)</label><input type='date' name='match_date'><div class='muted small'>If supplied, weekday checkboxes are ignored.</div></div><div><label>Block Template</label><select name='block_template_id'>{bopts}</select><label>Deco Template</label><select name='deco_template_id'>{dopts}</select></div></div><p>{_day_checks()}</p><button>Add Rule</button></form></div>
<div class='card'><form method='post' action='/scheduling/playout-templates/{pid}/delete' onsubmit="return confirm('Delete this Playout Template?');"><button class='danger'>Delete Playout Template</button></form></div>"""
    return _page('Edit Playout Template', body)


# ------------------------- Scripted Scheduling ---------------------------

def _api_token() -> str:
    return str(G['get_setting']('scripted_api_token', '') or '')


def _api_authorized(request: Request) -> None:
    token = _api_token()
    auth = str(request.headers.get('authorization') or '')
    supplied = auth[7:].strip() if auth.lower().startswith('bearer ') else str(request.headers.get('x-vipertv-api-key') or '').strip()
    if not token or not secrets.compare_digest(token, supplied):
        raise HTTPException(401, 'Invalid ViperTV Scripted Scheduling API token')


def _scripted_assignment(channel_id: int):
    with _db() as conn:
        return conn.execute('''SELECT sp.*,ss.name schedule_name,ss.updated_at schedule_updated FROM scripted_playouts sp
                               JOIN scripted_schedules ss ON ss.id=sp.schedule_id WHERE sp.channel_id=? AND sp.enabled=1''', (channel_id,)).fetchone()


def _source_pool(kind: str, ref: str, order: str, seed: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        if kind == 'search':
            items = G['media_search_playable'](ref)
        elif kind == 'media_uid':
            with _db() as conn:
                row = conn.execute('SELECT payload_json FROM search_index_items WHERE uid=?', (ref,)).fetchone()
            if row:
                items = [json.loads(str(row['payload_json'] or '{}'))]
        else:
            class R(dict):
                __getattr__ = dict.get
            items = G['_classic_source_items'](R(source_kind=kind, source_ref=ref, id=0))
    except Exception:
        items = []
    items = [dict(x) for x in items if float(x.get('duration') or 0) > 0]
    return adv._order_pool(items, order, seed)


def _scripted_day_items(channel_id: int) -> list[dict[str, Any]]:
    ass = _scripted_assignment(channel_id)
    if not ass: return []
    today = datetime.now(_tz()).date(); day = today.isoformat(); bit = 1 << today.weekday()
    with _db() as conn:
        exact = conn.execute('''SELECT * FROM scripted_schedule_items WHERE schedule_id=? AND air_date=? ORDER BY start_minute,position,id''', (int(ass['schedule_id']), day)).fetchall()
        rows = exact or conn.execute('''SELECT * FROM scripted_schedule_items WHERE schedule_id=? AND air_date IS NULL AND (day_mask & ?) != 0 ORDER BY start_minute,position,id''', (int(ass['schedule_id']), bit)).fetchall()
    if not rows:
        out = [adv._gap(86400, 'Off Air')]; adv._day_anchor(out); return out
    out: list[dict[str, Any]] = []; cursor = 0.0
    seed = f"scripted|{channel_id}|{ass['schedule_id']}|{ass['generation']}|{day}"
    for i, row in enumerate(rows):
        start = float(int(row['start_minute']) * 60)
        end = float(int(rows[i+1]['start_minute']) * 60) if i + 1 < len(rows) else 86400.0
        if start > cursor + 0.5:
            out.append(adv._gap(start-cursor, 'Off Air')); cursor = start
        if end <= cursor + 0.5: continue
        pool = _source_pool(str(row['source_kind']), str(row['source_ref']), str(row['playback_order']), f'{seed}|{row["id"]}')
        if not pool:
            out.append(adv._gap(end-cursor, 'Off Air')); cursor = end; continue
        fill = bool(row['fill_to_next']); count = max(1, int(row['count_items'] or 1)); emitted = 0; pos = 0
        while cursor < end - 0.5 and (fill or emitted < count) and pos < 10000:
            src = dict(pool[pos % len(pool)]); pos += 1; emitted += 1
            dur = max(1.0, float(src.get('duration') or 0))
            if row['duration_seconds'] is not None and float(row['duration_seconds'] or 0) > 0:
                dur = min(dur, float(row['duration_seconds']))
            rem = end - cursor
            if dur > rem + 0.5:
                src['_source_duration'] = float(src.get('_source_duration') or src.get('duration') or dur)
                src['_trim_limit'] = rem; dur = rem
            src['duration'] = dur
            if not row['show_in_epg']: src['_guide_hidden'] = True
            if str(row['title_override'] or '').strip(): src['_guide_custom_title'] = str(row['title_override']).strip()
            src['_scripted_item_id'] = int(row['id'])
            out.append(src); cursor += dur
        if cursor < end - 0.5:
            out.append(adv._gap(end-cursor, 'Off Air')); cursor = end
    if cursor < 86400 - 0.5: out.append(adv._gap(86400-cursor, 'Off Air'))
    adv._day_anchor(out)
    return out


def _channel_media_v128(channel_id: int):
    ass = _scripted_assignment(channel_id)
    if ass:
        with _db() as conn:
            ch = conn.execute('SELECT * FROM channels WHERE id=?', (channel_id,)).fetchone()
        if not ch: raise HTTPException(404, 'Channel not found')
        items = _scripted_day_items(channel_id)
        tagged = []
        for raw in items:
            x = dict(raw); x['_v12_channel_id'] = int(channel_id); tagged.append(x)
        return ch, tagged
    return _BASE_CHANNEL_MEDIA(channel_id)


def _scheduled_cursor_v128(channel_id: int):
    ass = _scripted_assignment(channel_id)
    if ass:
        key = f"scripted:{ass['schedule_id']}:{ass['generation']}"
        with _db() as conn:
            r = conn.execute('SELECT cursor FROM playout_state WHERE channel_id=? AND source_key=?', (channel_id, key)).fetchone()
        return key, int(r['cursor']) if r else 0
    return _BASE_SCHEDULED_CURSOR(channel_id)


def _scripted_page(msg: str = '') -> str:
    with _db() as conn:
        schedules = conn.execute('''SELECT s.*,COUNT(i.id) item_count FROM scripted_schedules s LEFT JOIN scripted_schedule_items i ON i.schedule_id=s.id GROUP BY s.id ORDER BY s.name COLLATE NOCASE''').fetchall()
        channels = conn.execute('SELECT id,number,name FROM channels ORDER BY number,name').fetchall()
        assigns = {int(r['channel_id']): r for r in conn.execute('''SELECT sp.*,ss.name schedule_name FROM scripted_playouts sp JOIN scripted_schedules ss ON ss.id=sp.schedule_id''').fetchall()}
    rows = ''.join(f"<tr><td><b>{_e(s['name'])}</b><div class='muted small'>{_e(s['description'] or '')}</div></td><td>{int(s['item_count'] or 0)}</td><td><a class='button secondary' href='/scheduling/scripted/{s['id']}'>Edit / Inspect</a></td></tr>" for s in schedules) or "<tr><td colspan='3' class='empty'>No Scripted Schedules yet.</td></tr>"
    sopts = "<option value=''>— None —</option>" + ''.join(f"<option value='{s['id']}'>{_e(s['name'])}</option>" for s in schedules)
    crows=[]
    for c in channels:
        a=assigns.get(int(c['id'])); opts=sopts
        if a: opts=opts.replace(f"value='{a['schedule_id']}'",f"value='{a['schedule_id']}' selected",1)
        crows.append(f"<tr><td>{_e(c['number'])}</td><td>{_e(c['name'])}</td><td><form method='post' action='/scheduling/scripted-playouts/{c['id']}/assign'><select name='schedule_id'>{opts}</select><button>Save</button></form></td><td>{_e(a['schedule_name']) if a else '—'}</td></tr>")
    token = _api_token()
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Scripted Scheduling','Build schedules from Python, PowerShell, shell scripts or any HTTP client. These endpoints are included automatically in ViperTV /docs and /openapi.json.',"<a class='button secondary' href='/docs'>OpenAPI Docs</a>")+f"""
<div class='grid'><div class='card'><h2>Create Scripted Schedule</h2><form method='post' action='/scheduling/scripted/add'><label>Name</label><input name='name' required placeholder='External Automation'><label>Description</label><textarea name='description' rows='3'></textarea><button>Create</button></form></div>
<div class='card'><h2>API Authentication</h2><p>Send either <code>Authorization: Bearer TOKEN</code> or <code>X-ViperTV-API-Key: TOKEN</code>.</p><label>Current API token</label><input value='{_e(token)}' readonly><form method='post' action='/scheduling/scripted/token/rotate' onsubmit="return confirm('Rotate the API token? Existing scripts will stop working until updated.');"><button class='secondary'>Rotate Token</button></form><p class='muted small'>The token is stored in the persistent ViperTV settings database and is never added to update ZIPs.</p></div></div>
<div class='card'><h2>Schedules</h2><div class='table-wrap'><table><thead><tr><th>Name</th><th>Entries</th><th></th></tr></thead><tbody>{rows}</tbody></table></div></div>
<div class='card'><h2>Channel Assignments</h2><div class='table-wrap'><table><thead><tr><th>#</th><th>Channel</th><th>Scripted Schedule</th><th>Active</th></tr></thead><tbody>{''.join(crows) or '<tr><td colspan=4>No channels.</td></tr>'}</tbody></table></div></div>
<div class='card'><h2>API workflow</h2><pre>GET  /api/v1/scripted/catalog?query=John%20Ritter
GET  /api/v1/scripted/schedules
POST /api/v1/scripted/schedules
POST /api/v1/scripted/schedules/{{id}}/replace-items
POST /api/v1/scripted/channels/{{channel_id}}/assign</pre><p>The replace-items endpoint accepts recurring weekday entries or exact <code>YYYY-MM-DD</code> entries. Use <code>query</code> for Smart Search sources, or <code>source_kind</code> + <code>source_ref</code> for Collections, Playlists, Marathons, shows, seasons and other ViperTV sources.</p></div>"""
    return _page('Scripted Scheduling',body)


def _scripted_editor(sid:int,msg:str='')->str:
    with _db() as conn:
        s=conn.execute('SELECT * FROM scripted_schedules WHERE id=?',(sid,)).fetchone()
        if not s: raise HTTPException(404,'Scripted Schedule not found')
        rows=conn.execute('SELECT * FROM scripted_schedule_items WHERE schedule_id=? ORDER BY COALESCE(air_date,\'\'),start_minute,position,id',(sid,)).fetchall()
    trs=''.join(f"<tr><td>{_e(r['air_date'] or _mask_text(int(r['day_mask'])))}</td><td>{_min_to_hm(int(r['start_minute']))}</td><td>{_e(r['source_kind'])}: {_e(r['source_ref'])}</td><td>{'Fill window' if r['fill_to_next'] else int(r['count_items'])}</td><td>{'Yes' if r['show_in_epg'] else 'No'}</td></tr>" for r in rows) or "<tr><td colspan='5'>No entries. Push them through the API.</td></tr>"
    body=(f"<div class='msg'>{_e(msg)}</div>" if msg else '')+_heading('Scripted Schedule',str(s['name']),"<a class='button secondary' href='/scheduling/scripted'>Back</a>")+f"""
<div class='card'><form method='post' action='/scheduling/scripted/{sid}/save'><label>Name</label><input name='name' value='{_e(s['name'])}' required><label>Description</label><textarea name='description' rows='3'>{_e(s['description'] or '')}</textarea><button>Save</button></form></div>
<div class='card'><h2>Current programmed entries</h2><div class='table-wrap'><table><thead><tr><th>Date / Days</th><th>Start</th><th>Source</th><th>Count</th><th>EPG</th></tr></thead><tbody>{trs}</tbody></table></div><p class='muted small'>Scripted entries are normally replaced atomically by an external program. This avoids half-written on-air schedules.</p></div>
<div class='card'><form method='post' action='/scheduling/scripted/{sid}/clear'><button class='secondary'>Clear All Entries</button></form> <form class='inline' method='post' action='/scheduling/scripted/{sid}/delete' onsubmit="return confirm('Delete this Scripted Schedule?');"><button class='danger'>Delete Schedule</button></form></div>"""
    return _page('Scripted Schedule',body)


def _json_body(request: Request):
    return request.json()


def _normalize_days(value: Any) -> int:
    if value is None: return 127
    if isinstance(value,int): return max(1,min(127,value))
    names={'mon':0,'monday':0,'tue':1,'tuesday':1,'wed':2,'wednesday':2,'thu':3,'thursday':3,'fri':4,'friday':4,'sat':5,'saturday':5,'sun':6,'sunday':6}
    mask=0
    if isinstance(value,str): value=[x.strip() for x in value.split(',')]
    for x in value or []:
        if isinstance(x,int) and 0<=x<=6: mask|=1<<x
        else:
            k=str(x).strip().lower()
            if k in names: mask|=1<<names[k]
    return mask or 127


def _validate_api_item(raw: dict[str,Any], position:int) -> tuple:
    start=str(raw.get('start') or raw.get('start_time') or '').strip()
    if not start: raise ValueError(f'Item {position+1}: start is required')
    minute=_hm_to_min(start)
    air_date=str(raw.get('date') or raw.get('air_date') or '').strip() or None
    if air_date:
        try: datetime.strptime(air_date,'%Y-%m-%d')
        except ValueError: raise ValueError(f'Item {position+1}: date must be YYYY-MM-DD')
    if str(raw.get('query') or '').strip(): kind='search'; ref=str(raw['query']).strip()
    elif str(raw.get('uid') or '').strip(): kind='media_uid'; ref=str(raw['uid']).strip()
    else:
        kind=str(raw.get('source_kind') or '').strip(); ref=str(raw.get('source_ref') or '').strip()
    if not kind or not ref: raise ValueError(f'Item {position+1}: query, uid, or source_kind/source_ref is required')
    valid_kinds=set(G.get('CLASSIC_SOURCE_KINDS') or set()) | {'search','media_uid','marathon'}
    if kind not in valid_kinds: raise ValueError(f'Item {position+1}: unsupported source_kind {kind!r}')
    order=str(raw.get('order') or raw.get('playback_order') or 'chronological').strip()
    if order not in ('chronological','season_episode','shuffle','random'): order='chronological'
    count=max(1,min(10000,int(raw.get('count') or raw.get('count_items') or 1)))
    fill=1 if bool(raw.get('fill_to_next') or raw.get('fill')) else 0
    duration=raw.get('duration_seconds')
    duration=float(duration) if duration is not None and float(duration)>0 else None
    show=1 if raw.get('show_in_epg',True) is not False else 0
    title=str(raw.get('title') or raw.get('title_override') or '').strip() or None
    return air_date,_normalize_days(raw.get('days')),minute,kind,ref,order,count,fill,duration,show,title,position,_now()


def install_v128(app, main_globals: dict[str, Any]) -> None:
    global G,_BASE_BLOCK_ASSIGNMENT,_BASE_BLOCK_DAY_ITEMS,_BASE_CHANNEL_MEDIA,_BASE_SCHEDULED_CURSOR
    G=main_globals
    base_init=G['init_v12_db']
    def init_all():
        base_init(); init_v128_db()
    G['init_v12_db']=init_all

    _BASE_BLOCK_ASSIGNMENT=adv._block_assignment
    _BASE_BLOCK_DAY_ITEMS=adv.block_day_items
    adv._block_assignment=_block_assignment_v128
    adv.block_day_items=_block_day_items_v128

    _BASE_CHANNEL_MEDIA=G['channel_media']
    _BASE_SCHEDULED_CURSOR=G['_scheduled_cursor']
    G['channel_media']=_channel_media_v128
    G['_scheduled_cursor']=_scheduled_cursor_v128

    @app.get('/scheduling/deco-templates',response_class=HTMLResponse)
    def deco_templates(msg:str=''): return _deco_templates_page(msg)
    @app.post('/scheduling/deco-templates/add')
    def deco_templates_add(name:str=Form(...)):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO deco_templates(name,created_at,updated_at) VALUES(?,?,?)',(name.strip(),_now(),_now()));conn.commit();tid=int(cur.lastrowid)
            return RedirectResponse(f'/scheduling/deco-templates/{tid}',303)
        except sqlite3.IntegrityError:return RedirectResponse('/scheduling/deco-templates?msg='+quote('That Deco Template name already exists.'),303)
    @app.get('/scheduling/deco-templates/{tid}',response_class=HTMLResponse)
    def deco_template_edit(tid:int,msg:str=''): return _deco_template_editor(tid,msg)
    @app.post('/scheduling/deco-templates/{tid}/save')
    def deco_template_save(tid:int,name:str=Form(...)):
        G['safe_backup_before_change']()
        try:
            with _db() as conn: conn.execute('UPDATE deco_templates SET name=?,updated_at=? WHERE id=?',(name.strip(),_now(),tid));conn.commit()
        except sqlite3.IntegrityError:return RedirectResponse(f'/scheduling/deco-templates/{tid}?msg='+quote('That name is already in use.'),303)
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/deco-templates/{tid}?msg=Template+saved',303)
    @app.post('/scheduling/deco-templates/{tid}/slots/add')
    def deco_template_slot_add(tid:int,start_time:str=Form(...),deco_id:int=Form(...),days:list[str]=Form(default=[])):
        G['safe_backup_before_change']()
        with _db() as conn:
            pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM deco_template_slots WHERE template_id=?',(tid,)).fetchone()['p'])
            conn.execute('INSERT INTO deco_template_slots(template_id,day_mask,start_minute,deco_id,position) VALUES(?,?,?,?,?)',(tid,_daymask(days),_hm_to_min(start_time),deco_id,pos));conn.execute('UPDATE deco_templates SET updated_at=? WHERE id=?',(_now(),tid));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/deco-templates/{tid}?msg=Timed+Deco+added',303)
    @app.post('/scheduling/deco-templates/{tid}/slots/{slot_id}/delete')
    def deco_template_slot_delete(tid:int,slot_id:int):
        G['safe_backup_before_change']()
        with _db() as conn: conn.execute('DELETE FROM deco_template_slots WHERE id=? AND template_id=?',(slot_id,tid));conn.execute('UPDATE deco_templates SET updated_at=? WHERE id=?',(_now(),tid));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/deco-templates/{tid}?msg=Entry+removed',303)
    @app.post('/scheduling/deco-templates/{tid}/delete')
    def deco_template_delete(tid:int):
        G['safe_backup_before_change']()
        with _db() as conn: conn.execute('DELETE FROM deco_templates WHERE id=?',(tid,));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse('/scheduling/deco-templates?msg=Template+deleted',303)

    @app.get('/scheduling/playout-templates',response_class=HTMLResponse)
    def playout_templates(msg:str=''): return _playout_templates_page(msg)
    @app.post('/scheduling/playout-templates/add')
    def playout_template_add(name:str=Form(...),notes:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO playout_templates(name,notes,created_at,updated_at) VALUES(?,?,?,?)',(name.strip(),notes.strip() or None,_now(),_now()));conn.commit();pid=int(cur.lastrowid)
            return RedirectResponse(f'/scheduling/playout-templates/{pid}',303)
        except sqlite3.IntegrityError:return RedirectResponse('/scheduling/playout-templates?msg='+quote('That Playout Template name already exists.'),303)
    @app.get('/scheduling/playout-templates/{pid}',response_class=HTMLResponse)
    def playout_template_edit(pid:int,msg:str=''): return _playout_template_editor(pid,msg)
    @app.post('/scheduling/playout-templates/{pid}/save')
    def playout_template_save(pid:int,name:str=Form(...),notes:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn: conn.execute('UPDATE playout_templates SET name=?,notes=?,updated_at=? WHERE id=?',(name.strip(),notes.strip() or None,_now(),pid));conn.commit()
        except sqlite3.IntegrityError:return RedirectResponse(f'/scheduling/playout-templates/{pid}?msg='+quote('That name is already in use.'),303)
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/playout-templates/{pid}?msg=Template+saved',303)
    @app.post('/scheduling/playout-templates/{pid}/entries/add')
    def playout_template_entry_add(pid:int,priority:int=Form(10),match_date:str=Form(''),block_template_id:int=Form(...),deco_template_id:str=Form(''),days:list[str]=Form(default=[])):
        G['safe_backup_before_change']();match_date=match_date.strip() or None
        if match_date:
            try:datetime.strptime(match_date,'%Y-%m-%d')
            except ValueError:return RedirectResponse(f'/scheduling/playout-templates/{pid}?msg='+quote('Exact date must be YYYY-MM-DD.'),303)
        with _db() as conn:
            pos=int(conn.execute('SELECT COALESCE(MAX(position),-1)+1 p FROM playout_template_entries WHERE playout_template_id=?',(pid,)).fetchone()['p'])
            conn.execute('''INSERT INTO playout_template_entries(playout_template_id,day_mask,match_date,priority,block_template_id,deco_template_id,position) VALUES(?,?,?,?,?,?,?)''',(pid,_daymask(days),match_date,int(priority),block_template_id,int(deco_template_id) if deco_template_id.isdigit() else None,pos));conn.execute('UPDATE playout_templates SET updated_at=? WHERE id=?',(_now(),pid));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/playout-templates/{pid}?msg=Rule+added',303)
    @app.post('/scheduling/playout-templates/{pid}/entries/{eid}/delete')
    def playout_template_entry_delete(pid:int,eid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM playout_template_entries WHERE id=? AND playout_template_id=?',(eid,pid));conn.execute('UPDATE playout_templates SET updated_at=? WHERE id=?',(_now(),pid));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse(f'/scheduling/playout-templates/{pid}?msg=Rule+removed',303)
    @app.post('/scheduling/playout-templates/{pid}/delete')
    def playout_template_delete(pid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM playout_templates WHERE id=?',(pid,));conn.commit()
        adv.BLOCK_DAY_CACHE.clear();return RedirectResponse('/scheduling/playout-templates?msg=Template+deleted',303)
    @app.post('/scheduling/playout-template-playouts/{channel_id}/assign')
    def playout_template_assign(channel_id:int,playout_template_id:str=Form('')):
        G['safe_backup_before_change']();now=_now()
        with _db() as conn:
            if playout_template_id.isdigit():
                old=conn.execute('SELECT playout_template_id,generation FROM playout_template_playouts WHERE channel_id=?',(channel_id,)).fetchone();gen=(int(old['generation'])+1 if old and int(old['playout_template_id'])!=int(playout_template_id) else int(old['generation']) if old else 0)
                conn.execute('''INSERT INTO playout_template_playouts(channel_id,playout_template_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET playout_template_id=excluded.playout_template_id,enabled=1,generation=?,updated_at=excluded.updated_at''',(channel_id,int(playout_template_id),1,gen,now,now,gen))
            else:conn.execute('DELETE FROM playout_template_playouts WHERE channel_id=?',(channel_id,))
            conn.commit()
        adv.BLOCK_DAY_CACHE.clear();G['_classic_invalidate'](channel_id);return RedirectResponse('/scheduling/playout-templates?msg=Channel+assignment+saved',303)

    @app.get('/scheduling/scripted',response_class=HTMLResponse)
    def scripted(msg:str=''):return _scripted_page(msg)
    @app.post('/scheduling/scripted/add')
    def scripted_add(name:str=Form(...),description:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO scripted_schedules(name,description,created_at,updated_at) VALUES(?,?,?,?)',(name.strip(),description.strip() or None,_now(),_now()));conn.commit();sid=int(cur.lastrowid)
            return RedirectResponse(f'/scheduling/scripted/{sid}',303)
        except sqlite3.IntegrityError:return RedirectResponse('/scheduling/scripted?msg='+quote('That Scripted Schedule name already exists.'),303)
    @app.get('/scheduling/scripted/{sid}',response_class=HTMLResponse)
    def scripted_edit(sid:int,msg:str=''):return _scripted_editor(sid,msg)
    @app.post('/scheduling/scripted/{sid}/save')
    def scripted_save(sid:int,name:str=Form(...),description:str=Form('')):
        G['safe_backup_before_change']()
        try:
            with _db() as conn:conn.execute('UPDATE scripted_schedules SET name=?,description=?,updated_at=? WHERE id=?',(name.strip(),description.strip() or None,_now(),sid));conn.commit()
        except sqlite3.IntegrityError:return RedirectResponse(f'/scheduling/scripted/{sid}?msg='+quote('That name is already in use.'),303)
        return RedirectResponse(f'/scheduling/scripted/{sid}?msg=Schedule+saved',303)
    @app.post('/scheduling/scripted/{sid}/clear')
    def scripted_clear(sid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM scripted_schedule_items WHERE schedule_id=?',(sid,));conn.execute('UPDATE scripted_schedules SET updated_at=? WHERE id=?',(_now(),sid));conn.commit()
        return RedirectResponse(f'/scheduling/scripted/{sid}?msg=Entries+cleared',303)
    @app.post('/scheduling/scripted/{sid}/delete')
    def scripted_delete(sid:int):
        G['safe_backup_before_change']()
        with _db() as conn:conn.execute('DELETE FROM scripted_schedules WHERE id=?',(sid,));conn.commit()
        return RedirectResponse('/scheduling/scripted?msg=Schedule+deleted',303)
    @app.post('/scheduling/scripted-playouts/{channel_id}/assign')
    def scripted_assign(channel_id:int,schedule_id:str=Form('')):
        G['safe_backup_before_change']();now=_now()
        with _db() as conn:
            if schedule_id.isdigit():
                old=conn.execute('SELECT schedule_id,generation FROM scripted_playouts WHERE channel_id=?',(channel_id,)).fetchone();gen=(int(old['generation'])+1 if old and int(old['schedule_id'])!=int(schedule_id) else int(old['generation']) if old else 0)
                conn.execute('''INSERT INTO scripted_playouts(channel_id,schedule_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET schedule_id=excluded.schedule_id,enabled=1,generation=?,updated_at=excluded.updated_at''',(channel_id,int(schedule_id),1,gen,now,now,gen))
            else:conn.execute('DELETE FROM scripted_playouts WHERE channel_id=?',(channel_id,))
            conn.commit()
        G['_classic_invalidate'](channel_id);adv.BLOCK_DAY_CACHE.clear();adv.SEQUENTIAL_DAY_CACHE.clear();return RedirectResponse('/scheduling/scripted?msg=Channel+assignment+saved',303)
    @app.post('/scheduling/scripted/token/rotate')
    def scripted_token_rotate():
        G['safe_backup_before_change']();G['set_setting']('scripted_api_token',secrets.token_urlsafe(32));return RedirectResponse('/scheduling/scripted?msg=API+token+rotated',303)

    # Authenticated REST/OpenAPI endpoints for external schedulers.
    @app.get('/api/v1/scripted/status')
    async def api_scripted_status(request:Request):
        _api_authorized(request)
        with _db() as conn:
            return {'version':G['APP_VERSION'],'schedules':int(conn.execute('SELECT COUNT(*) c FROM scripted_schedules').fetchone()['c']),'assigned_channels':int(conn.execute('SELECT COUNT(*) c FROM scripted_playouts WHERE enabled=1').fetchone()['c'])}

    @app.get('/api/v1/scripted/catalog')
    async def api_scripted_catalog(request:Request,query:str='',limit:int=100):
        _api_authorized(request);items=G['media_search_playable'](query,max(1,min(500,limit))) if query.strip() else []
        return {'query':query,'items':[{'uid':x.get('uid'),'title':x.get('title'),'show_title':x.get('show_title'),'episode_title':x.get('episode_title'),'source_type':x.get('source_type'),'media_kind':x.get('media_kind') or x.get('media_type'),'duration':x.get('duration')} for x in items]}

    @app.get('/api/v1/scripted/schedules')
    async def api_scripted_schedules(request:Request):
        _api_authorized(request)
        with _db() as conn:rows=conn.execute('SELECT * FROM scripted_schedules ORDER BY name COLLATE NOCASE').fetchall()
        return {'schedules':[dict(r) for r in rows]}

    @app.get('/api/v1/scripted/channels')
    async def api_scripted_channels(request:Request):
        _api_authorized(request)
        with _db() as conn:
            rows=conn.execute('''SELECT c.id,c.number,c.name,c.enabled,sp.schedule_id,ss.name schedule_name FROM channels c LEFT JOIN scripted_playouts sp ON sp.channel_id=c.id AND sp.enabled=1 LEFT JOIN scripted_schedules ss ON ss.id=sp.schedule_id ORDER BY c.number,c.name''').fetchall()
        return {'channels':[dict(r) for r in rows]}

    @app.post('/api/v1/scripted/schedules')
    async def api_scripted_create(request:Request):
        _api_authorized(request);data=await request.json();name=str(data.get('name') or '').strip()
        if not name:raise HTTPException(400,'name is required')
        G['safe_backup_before_change']()
        try:
            with _db() as conn:
                cur=conn.execute('INSERT INTO scripted_schedules(name,description,created_at,updated_at) VALUES(?,?,?,?)',(name,str(data.get('description') or '').strip() or None,_now(),_now()));conn.commit();sid=int(cur.lastrowid)
            return {'id':sid,'name':name}
        except sqlite3.IntegrityError:raise HTTPException(409,'schedule name already exists')

    @app.get('/api/v1/scripted/schedules/{sid}/items')
    async def api_scripted_items(request:Request,sid:int):
        _api_authorized(request)
        with _db() as conn:rows=conn.execute('SELECT * FROM scripted_schedule_items WHERE schedule_id=? ORDER BY COALESCE(air_date,\'\'),start_minute,position,id',(sid,)).fetchall()
        return {'schedule_id':sid,'items':[dict(r) for r in rows]}

    @app.post('/api/v1/scripted/schedules/{sid}/replace-items')
    async def api_scripted_replace(request:Request,sid:int):
        _api_authorized(request);data=await request.json();raw_items=data.get('items')
        if not isinstance(raw_items,list):raise HTTPException(400,'items must be a JSON array')
        try:normalized=[_validate_api_item(dict(x),i) for i,x in enumerate(raw_items)]
        except (ValueError,TypeError) as exc:raise HTTPException(400,str(exc))
        G['safe_backup_before_change']()
        with _db() as conn:
            if not conn.execute('SELECT 1 FROM scripted_schedules WHERE id=?',(sid,)).fetchone():raise HTTPException(404,'Scripted Schedule not found')
            conn.execute('BEGIN IMMEDIATE');conn.execute('DELETE FROM scripted_schedule_items WHERE schedule_id=?',(sid,))
            conn.executemany('''INSERT INTO scripted_schedule_items(schedule_id,air_date,day_mask,start_minute,source_kind,source_ref,playback_order,count_items,fill_to_next,duration_seconds,show_in_epg,title_override,position,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',[(sid,*x) for x in normalized])
            conn.execute('UPDATE scripted_schedules SET updated_at=? WHERE id=?',(_now(),sid));conn.execute('UPDATE scripted_playouts SET generation=generation+1,updated_at=? WHERE schedule_id=?',(_now(),sid));conn.commit()
        return {'ok':True,'schedule_id':sid,'items':len(normalized)}

    @app.post('/api/v1/scripted/channels/{channel_id}/assign')
    async def api_scripted_assign(request:Request,channel_id:int):
        _api_authorized(request);data=await request.json();sid=int(data.get('schedule_id') or 0)
        G['safe_backup_before_change']()
        with _db() as conn:
            if not conn.execute('SELECT 1 FROM channels WHERE id=?',(channel_id,)).fetchone():raise HTTPException(404,'Channel not found')
            if not conn.execute('SELECT 1 FROM scripted_schedules WHERE id=?',(sid,)).fetchone():raise HTTPException(404,'Scripted Schedule not found')
            old=conn.execute('SELECT schedule_id,generation FROM scripted_playouts WHERE channel_id=?',(channel_id,)).fetchone();gen=(int(old['generation'])+1 if old and int(old['schedule_id'])!=sid else int(old['generation']) if old else 0);now=_now()
            conn.execute('''INSERT INTO scripted_playouts(channel_id,schedule_id,enabled,generation,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET schedule_id=excluded.schedule_id,enabled=1,generation=?,updated_at=excluded.updated_at''',(channel_id,sid,1,gen,now,now,gen));conn.commit()
        return {'ok':True,'channel_id':channel_id,'schedule_id':sid}

    @app.post('/api/v1/scripted/channels/{channel_id}/reset')
    async def api_scripted_reset(request:Request,channel_id:int):
        _api_authorized(request)
        with _db() as conn:conn.execute('UPDATE scripted_playouts SET generation=generation+1,updated_at=? WHERE channel_id=?',(_now(),channel_id));conn.execute("DELETE FROM playout_state WHERE channel_id=? AND source_key LIKE 'scripted:%'",(channel_id,));conn.commit()
        return {'ok':True,'channel_id':channel_id}
