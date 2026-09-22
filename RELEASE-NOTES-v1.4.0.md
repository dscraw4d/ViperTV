# ViperTV v1.4.0 — Media, Security & Automation Completion

ViperTV v1.4.0 closes the remaining major parity gaps identified after v1.3.0 while preserving the working streaming/scheduling core.

## New
- Folder-level image duration inheritance with nearest-child rule and per-image precedence.
- General Remote Stream definitions: FFmpeg-readable URL/file or trusted executable stdout, Live/VOD behavior and scheduled duration.
- Trakt Lists with manual refresh, automatic refresh interval, and automatic Playlist or Collection mirroring.
- Management authentication with local administrator login plus generic OIDC authorization-code login using provider discovery/userinfo.
- JWT-protected IPTV/stream endpoints and tokenized M3U access.
- Streaming-only external port gate for OMV/reverse-proxy deployments.
- Local Script Runner for Python/shell/executable scheduling programs with build ID/mode/arguments/API credentials.
- Dependency-free Python Scripted Scheduling client in `app/vipertv_script_client.py`.
- Scripted graphics on/off timeline API.
- Graphics Engine test bench that renders a short preview using real channel media and selected graphics.
- Relative-date search operators: `released_inthelast`, `released_onthisday`, `released_before`, `released_after`, `added_inthelast`, `added_onthisday`, `added_before`, `added_after`.

## Preserved from v1.3.0
- Jellyfin/Emby stream-from-disk path replacements.
- Reusable complete FFmpeg Profiles.
- Plex direct paths, Advanced Stream Selector, Graphics Engine 2.0, hardware acceleration, multiple streaming modes, indexed search, scheduler automation and recovery-safe migrations.

## Security notes
- Management auth is disabled after upgrade until explicitly enabled.
- IPTV JWT protection is disabled after upgrade until explicitly enabled.
- Executable Remote Streams are restricted to `/data/remote-scripts` by default.
- Scheduler programs are restricted to `/data/scheduler-scripts` by default.
- OIDC uses standard discovery, authorization-code exchange and the provider's UserInfo endpoint.
- A streaming-only port still requires a host/reverse-proxy mapping to container port 8409; ViperTV never rewrites the user's Compose file.
