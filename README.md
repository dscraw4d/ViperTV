# ViperTV 1.1.46

ViperTV is a self-hosted virtual TV server for turning local media, Plex libraries, Jellyfin/Emby libraries, Pluto TV and direct HLS sources into scheduled IPTV channels with M3U/XMLTV output, browser playback and HDHomeRun-style discovery endpoints.

This public package is sanitized for installation on another user's machine: it contains **no ViperTV database, Plex token, API key, private NAS path, or private LAN address**.


## New in 1.1.46 — Classic Schedules and Playouts

ViperTV now has reusable ErsatzTV-style Classic Schedules and per-channel Playouts, including Dynamic/Fixed starts, Flood/One/Multiple/Duration modes, Collections/Smart Collections/Multi Collections/Playlists/TV shows/seasons as sources, multiple playback orders, fixed-time gap handling, custom EPG titles, filler tails, and playout reset controls. See `docs/SCHEDULING.md`.

Recent releases also added click-through TV/movie metadata pages, Playlists, detailed People pages, exact episode-level actor/director credits, and rich Plex episode metadata sync. See `CHANGELOG.md` for the complete history.

## New in 1.1.39 — search-first Collections

ViperTV collections now use an ErsatzTV-style workflow:

- **Manual Collection** — open **Media → Search**, search or browse (`*`), select individual movies/episodes or whole shows, then **Add To Collection**. You can choose an existing collection or create a new one in the same step.
- **Smart Collection** — refine a media search until it matches what you want, then **Save As Smart Collection**. The saved query is evaluated dynamically after future scans/syncs.
- **Multi Collection** — combine existing manual and Smart Collections into one reusable programming source.

The ViperTV search language supports `AND`, `OR`, `NOT`, parentheses and the fields `title`, `show_title`, `type`, `actor`, `director`, `network`, `genre`, `library_name`, `source`, `year`, `release_date`, `season_number`, `episode_number`, `plot`, and `status`. Example: `type:episode AND actor:"John Ritter" AND year:1980-1989`.

See `docs/COLLECTIONS.md` for the complete beginner workflow and query examples.

## Quick start

### Windows / Docker Desktop

1. Install Docker Desktop and make sure Linux containers are enabled.
2. Extract this ZIP to a permanent folder.
3. Double-click `Start-ViperTV.cmd`.
4. When the build finishes, open `http://localhost:8409`.
5. For other devices on the same LAN, use `http://<this-PC-LAN-IP>:8409`.

### Linux / OpenMediaVault / Docker Engine

```bash
chmod +x install.sh
./install.sh
```

Then open `http://<server-LAN-IP>:8409`.

The first Docker build needs Internet access to download the Python image/packages, FFmpeg dependencies and the browser HLS library.

## Where ViperTV stores things

The public Compose file deliberately uses portable relative folders:

- `./data` — live SQLite database/configuration and normal ViperTV backups.
- `./backups` — independent secondary database backups.
- `./media` — optional local media mount, read-only inside the container at `/media`.
- `.env` — deployment settings such as timezone, port, Pluto region and local media path.

Do **not** include `data/`, `backups/` or a populated `.env` when making a clean redistributable ZIP from an installed copy.

## Existing media on another disk/NAS

Edit `.env` before starting and change:

```text
VIPERTV_MEDIA_DIR=./media
```

Linux example:

```text
VIPERTV_MEDIA_DIR=/mnt/storage/media
```

Windows Docker Desktop example:

```text
VIPERTV_MEDIA_DIR=D:/Media
```

That host folder appears inside ViperTV as `/media` and is mounted read-only. You can also add extra read-only media mounts to `compose.yml`.

## Plex / actor and director metadata

Open **Media Sources → Plex**, add the server URL/token, and run **Sync All Libraries**. ViperTV imports the actor, character and director credits Plex exposes.

For local libraries, ViperTV can import `<actor>` and `<director>` data from `tvshow.nfo` and episode/movie sidecar NFO files. See `docs/PEOPLE-METADATA.md`.

The AI Channel Builder can then handle requests such as:

```text
Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s.
```

For a person + decade/year request, TV filtering uses the episode air date rather than only the series premiere year.

## Main features

- Local TV/movie libraries.
- Plex integration and metadata sync.
- Jellyfin / Emby sources.
- Actor, character and director people index.
- AI-style local natural-language Channel Builder (no cloud AI prompt service required).
- Manual channels, schedules, collections, smart collections, filler and cloning/templates.
- Pluto TV discovery/import and guide cache.
- Direct HLS / M3U8 live channels with recursive signed proxying.
- Retro TV historical schedule builder with TVTango/Jina/TVmaze fallback and Music Video filler.
- M3U and XMLTV endpoints for Kodi/IPTV clients.
- Browser Watch pages and guide.
- HDHomeRun-style discovery/lineup endpoints.
- Persistent SQLite data with primary and secondary backup locations.

## IPTV endpoints

After installation, replace `<host>` with the ViperTV server's LAN IP/name:

```text
http://<host>:8409/iptv/channels.m3u
http://<host>:8409/iptv/xmltv.xml
```

## Hardware acceleration

The normal public configuration defaults to software encoding so it starts on the widest range of systems.

Compatible Linux systems with Intel `/dev/dri` can use:

```bash
docker compose -f compose.yml -f compose.intel-vaapi.yml up -d --build
```

or `./start-intel-vaapi.sh`.

## TheTVDB

TheTVDB enrichment is optional. No API key is included. Configure your own key under **System → Metadata Providers** if you want canonical TVDB metadata.

Actor/director imports from Plex/NFO do not require TheTVDB.

## Security

ViperTV 1.1.46 does not include a built-in admin login. It is intended for a trusted LAN. Do not expose port 8409 directly to the public Internet. For remote access, use a VPN or an authenticated HTTPS reverse proxy. See `docs/SECURITY.md`.

## Updating

Read `docs/UPGRADE.md`. The important rule is to keep `data/`, `backups/` and `.env` when replacing application files.

## Included documentation

- `docs/PEOPLE-METADATA.md`
- `docs/OMV.md`
- `docs/SECURITY.md`
- `docs/UPGRADE.md`
- `PLUTO-SETUP.txt`
- `RETRO-TV-SETUP.txt`
- `LIVE-IPTV-SETUP.txt`
- `TVDB-SETUP.txt`
- `FEATURE-MATRIX.md`
- `CHANGELOG.md`
- `docs/RELEASE-HISTORY.md`

## Licensing note

This packaging pass does not choose a new software license on the project owner's behalf. Before publishing ViperTV as an open-source project or granting third parties redistribution rights, add the license terms you want. See `LICENSE-NOTICE.txt`.
