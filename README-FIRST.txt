VIPERTV v1.1.46 — DRAG & DROP UPDATE (NO SSH)
Created by Darren "The Viper" Crawford

This package contains ONLY program/documentation files. It does not contain or replace your database, media, backups, Plex token, .env, or storage paths.

WHAT v1.1.46 ADDS
- Reusable Classic Schedules modeled after the workflow of ErsatzTV Classic Schedules.
- A Schedule is now separate from a Channel. Build it once, then assign it to one or more channels from Scheduling -> Playouts.
- Per-channel Playout assignments with independent reset/generation state.
- Schedule-level options:
  * Keep multi-part episodes together
  * Treat Collections as Shows
  * Shuffle Schedule Items
  * Random Start Point
- Schedule Item source types:
  * Manual Collection
  * Smart Collection
  * Multi Collection
  * Playlist
  * Entire TV Show
  * Individual TV Season
- Start types: Dynamic or Fixed clock time.
- Fixed start behavior: Flexible or Strict.
- Playback orders: Chronological, Season/Episode, Shuffle, Random and Shuffle In Order.
- Playout modes: One, Multiple, Duration and Flood.
- Multiple modes: Count, Collection Size, Multi-Episode Group Size and Playlist Item Size.
- Fill With Group: None, Ordered Groups or Shuffled Groups.
- Duration tail behavior: advance immediately, Offline/black, or use a filler Collection.
- Discard-to-fill attempts for Duration items.
- Custom EPG title and Guide Mode (Normal/Filler).
- Schedule item editing, moving up/down and deletion.
- Schedule cloning and deletion.
- Guide/XMLTV integration for Classic Schedule output.
- Automatic black/silent schedule gaps for fixed starts and offline tails.
- Existing pre-v1.1.46 time-block schedules are NOT deleted. They remain under Channel Studio as Legacy Time Blocks and are used whenever no Classic Playout is assigned.

HOW TO INSTALL
1. Stop ViperTV in your OpenMediaVault / Docker web interface.
2. Open this ZIP and drag its CONTENTS over your existing ViperTV program folder. Allow matching files to be replaced.
3. Build/Rebuild the ViperTV project in your Docker/Compose web interface. A restart alone is not enough because app/main.py is copied into the image at build time.
4. Start ViperTV. The sidebar and /healthz should say v1.1.46.
5. Open Scheduling -> Schedules and create your first Classic Schedule.
6. Add Schedule Items, then open Scheduling -> Playouts and assign the Schedule to a channel.
7. Open Guide to preview the result.

NO DATABASE RESET IS REQUIRED.
Your channels, Collections, Smart Collections, Multi Collections, Playlists, people metadata, Plex settings, old schedules and media stay intact.

See docs/SCHEDULING.md for a beginner-friendly scheduling walkthrough.
