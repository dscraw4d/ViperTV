# ViperTV v1.2.8 — Scheduler Automation

This release implements the remaining scheduler automation layer requested after v1.2.7.

## Deco Templates
- Reusable timed presentation schedules built from existing Decos.
- Weekday masks on each timed Deco entry.
- Dynamic active-Deco lookup while Blocks advance through the day.
- Explicit Deco assigned directly to a Block Template slot continues to take precedence.

## Playout Templates
- Reusable rules that pair a Block Template with an optional Deco Template.
- Recurring weekday rules.
- Exact-date special-event/holiday rules.
- Numeric priority for resolving competing matches.
- Per-channel assignment.

## Scripted Scheduling
- First-class Scripted Schedule objects and channel assignments.
- Authenticated REST API under `/api/v1/scripted/*`.
- Endpoints are automatically exposed through FastAPI `/docs` and `/openapi.json`.
- External clients can search the catalog, create schedules, atomically replace schedule items, assign schedules, and reset playout.
- Items can use Smart Search queries, exact indexed-media UIDs, or standard ViperTV source kinds.
- Supports recurring weekday entries, exact dates, item counts, fill-to-next windows, EPG visibility and custom EPG titles.
- API token is generated locally and stored only in the persistent settings database.
- ViperTV does not execute uploaded external scripts inside the container; automation remains external and calls the authenticated API.

## Safety / migration
- Additive SQLite migration only; no database reset.
- Existing v1.2.7 data remains intact.
- Database triggers keep Classic, Block, Sequential, Playout Template and Scripted assignments mutually exclusive.
- Recovery-safe update contains no Compose YAML, `.env`, database, backups or media directories.
