# Publishing ViperTV on GitHub

This folder is prepared as a clean source tree for GitHub.

- `.env` is intentionally not included. Users create it from `.env.example`.
- `data/`, `backups/`, and user media are ignored by Git.
- Do not commit Plex tokens, Jellyfin/Emby API keys, TheTVDB keys, databases, backups, or personal media.
- Choose and add an open-source license before advertising the project as open source.
- Current source version: **1.4.0**.

Suggested repository description:

> Self-hosted virtual TV server for local media, Plex, Jellyfin/Emby, Pluto TV and scheduled IPTV channels with M3U/XMLTV output. Created by Darren “The Viper” Crawford.

Suggested topics:

`virtual-tv`, `iptv`, `self-hosted`, `docker`, `python`, `plex`, `jellyfin`, `emby`, `m3u`, `xmltv`, `media-server`

## v1.2.8 release highlights

Deco Templates, prioritized Playout Templates, and authenticated Scripted Scheduling REST/OpenAPI endpoints complete the scheduler automation layer.


## v1.4.0 release highlights
Media/security/automation completion: folder image inheritance, general Remote Streams, Trakt Lists, optional local/OIDC management auth, JWT IPTV protection, streaming-only port rules, executable scheduler scripts, scripted graphics controls, graphics test bench and relative-date search.
