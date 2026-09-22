# ViperTV v1.4.0 Media, Security & Automation

## Image folder durations
Media → Images supports folder rules. Rules inherit to child folders; the nearest matching folder wins. A deliberately changed per-image duration has priority.

## Remote Streams
Sources → Remote Streams supports URL/file inputs readable by FFmpeg and trusted executable stdout. Executables must live under `/data/remote-scripts` unless the root setting is changed.

## Trakt
Sources → Trakt Lists stores a Trakt Client ID and mirrors user list items into an auto-managed Playlist or Collection. Enabled definitions are refreshed according to their interval.

## Management security
System → Security & Network can enable local login and/or OIDC. OIDC requires a discovery URL, client ID, and normally a client secret. Management auth is opt-in so upgrades cannot lock an existing administrator out.

## IPTV JWT
When enabled, IPTV/stream endpoints require a signed token unless the request already carries an authenticated management session. `/iptv/channels.m3u?token=<JWT>` is supported, and secure-prefix URLs propagate authorization through HLS child resources.

## Streaming-only port
Set the external port number under Security & Network, then map that host port to container port 8409 in OMV or a reverse proxy. Requests arriving through that port are limited to IPTV, streaming, HDHomeRun discovery, and health endpoints.

## Script Runner
Scheduling → Script Runner can upload and execute trusted Python/shell programs from `/data/scheduler-scripts`. Each process receives `VIPERTV_API_BASE`, `VIPERTV_API_TOKEN`, `VIPERTV_BUILD_ID`, `VIPERTV_MODE`, and `VIPERTV_ARGS_JSON`.

## Scripted graphics
Use `POST /api/v1/scripted/schedules/{id}/graphics-events` with an `events` array containing `start`, `graphic_id`, `action` (`on`/`off`), plus optional `days` or `date`.

## Graphics Test Bench
System → Graphics Test Bench renders a short MP4 using current channel media and any selected Graphics Engine elements without modifying the live schedule.

## Relative-date search
Examples:
- `released_inthelast:30d`
- `released_onthisday:true`
- `released_after:1990-01-01`
- `released_before:2000-01-01`
- `added_inthelast:7d`
- `added_after:2026-01-01`
