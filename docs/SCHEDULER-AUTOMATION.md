# ViperTV v1.2.8 — Scheduler Automation

## Deco Templates

Open **Scheduling → Deco Templates**. A Deco Template is a generic presentation day made from timed entries. Each entry selects an existing reusable Deco and can apply to any combination of weekdays. A typical template might switch to a Morning Deco at 06:00, Evening Deco at 17:00, Prime Time Deco at 20:00, and Late Night Deco at 23:00.

When a Playout Template uses a Deco Template, ViperTV chooses the currently active Deco as Block programming advances through the day. If a Block Template slot has an explicit Deco, that explicit slot Deco takes precedence.

## Playout Templates

Open **Scheduling → Playout Templates**. A rule selects:

- a Block Template,
- an optional Deco Template,
- recurring weekdays or one exact `YYYY-MM-DD` date, and
- a numeric priority.

Exact-date rules are considered before normal weekday rules. When multiple matching rules remain, the highest priority wins. This allows a normal weekday schedule to be overridden by Saturday programming, holidays, special events, or temporary themed schedules without editing the underlying Block/Deco Templates.

Assign a Playout Template to a channel from the same page. ViperTV automatically makes scheduler assignments mutually exclusive, so assigning Classic, Block, Sequential, Scripted, or another Playout Template does not leave a hidden old scheduler active.

## Scripted Scheduling

Open **Scheduling → Scripted**. Create a named Scripted Schedule and assign it to a channel. ViperTV generates a persistent API token. External programs authenticate using either:

```text
Authorization: Bearer YOUR_TOKEN
```

or:

```text
X-ViperTV-API-Key: YOUR_TOKEN
```

All Scripted endpoints are present in ViperTV's interactive FastAPI documentation at `/docs` and machine-readable schema at `/openapi.json`.

### Typical workflow

1. `GET /api/v1/scripted/channels` to discover channel ids.
2. `GET /api/v1/scripted/catalog?query=John%20Ritter` to find content/UIDs.
3. `POST /api/v1/scripted/schedules` to create a schedule (or create one in the UI).
4. `POST /api/v1/scripted/schedules/{id}/replace-items` to atomically replace its programming.
5. `POST /api/v1/scripted/channels/{channel_id}/assign` to put it on air.
6. `POST /api/v1/scripted/channels/{channel_id}/reset` when an external controller intentionally wants to restart playout state.

### Replace-items example

```json
{
  "items": [
    {
      "start": "06:00",
      "query": "M*A*S*H",
      "count": 2,
      "days": ["mon", "tue", "wed", "thu", "fri"]
    },
    {
      "start": "18:00",
      "source_kind": "marathon",
      "source_ref": "3",
      "fill_to_next": true,
      "show_in_epg": true,
      "title": "Prime Time Marathon"
    },
    {
      "start": "20:00",
      "uid": "local:12:345",
      "date": "2026-12-25",
      "show_in_epg": true,
      "title": "Christmas Special"
    }
  ]
}
```

`query` uses ViperTV Smart Search. `uid` targets an exact item from the persistent search index. `source_kind` / `source_ref` can use the normal ViperTV scheduling sources, including Collections, Playlists, shows/seasons and saved Marathons.

A recurring item uses `days`; an exact one-off item uses `date`. If at least one exact-date entry exists for today, that exact-date set replaces the recurring entries for that day. `fill_to_next` cycles the selected source until the next scripted start time. Without it, `count` controls how many source items are emitted and any remaining window becomes Off Air.

### Python example

```python
import requests

BASE = "http://vipertv:8409"
TOKEN = "YOUR_TOKEN"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

payload = {
    "items": [
        {"start": "06:00", "query": "1980s comedy", "count": 4, "days": ["mon","tue","wed","thu","fri"]},
        {"start": "20:00", "source_kind": "marathon", "source_ref": "3", "fill_to_next": True},
    ]
}
requests.post(f"{BASE}/api/v1/scripted/schedules/1/replace-items", json=payload, headers=HEADERS).raise_for_status()
```

The API never executes uploaded Python or shell code inside ViperTV. External programs call the authenticated API, which keeps the ViperTV container isolated while still allowing fully programmable schedules.
