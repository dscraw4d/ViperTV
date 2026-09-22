# ViperTV Advanced Scheduling — v1.2.0

ViperTV v1.2.0 adds four major programming systems on top of the existing Classic Schedule/Playout engine: **Block Scheduling**, **advanced Commercial/Filler presets**, **Graphics & Branding**, and **Sequential YAML Scheduling**.

The database migration is additive. Existing channels, Classic Schedules, Playlists, Collections, media indexes, Pluto/Retro configuration and streaming settings are preserved.

## Block Scheduling

Open **Scheduling → Blocks / Templates**.

A **Block** has a fixed duration (for example 30, 60 or 120 minutes). Add one or more programming sources to the Block. Sources may be Collections, Smart/Multi Collections, Playlists, TV shows or TV seasons, using the same indexed sources available to Classic Scheduling.

Each Block item controls playback order, whether the primary item appears in the EPG, whether station watermarks are disabled, attached Filler presets, and attached Graphics.

A **Block Template** places Blocks at fixed wall-clock start times on selected days of the week. Block output is hard-clipped to the next Block boundary, so commercials or filler cannot push the following Block late.

A **Deco** is reusable Block presentation policy. It can control watermark inheritance/disable/override, whether a watermark appears during filler, default filler for unused Block time, dead-air fallback filler, exact-boundary trimming, and additional graphics.

Assign a Template to a channel under **Block Playouts**. A channel can have one active advanced scheduling mode at a time: assigning Block disables Classic and Sequential for that channel.

## Commercial / Filler presets

Open **Lists → Filler**.

A preset can use a Collection (recommended) or a local library and has one of five roles:

- **Pre-roll** — before primary programming.
- **Mid-roll** — breaks a sufficiently long programme into commercial segments.
- **Post-roll** — after primary programming.
- **Tail** — when a Classic schedule-item run or Block item finishes.
- **Fallback** — replaces otherwise unscheduled gaps.

Modes are:

- **Count** — play a configured number of clips.
- **Duration** — fill a target number of seconds.
- **Pad** — fill to the next wall-clock multiple such as 15 or 30 minutes.

**Trim final filler clip** allows ViperTV to stop the last filler item exactly at a hard schedule boundary. Mid-roll supports 1–8 breaks. ViperTV 1.2.7 can place mid-roll breaks on imported chapter boundaries. **Auto** uses chapters when available and falls back to even spacing; **Chapters** prefers chapter boundaries; **Even** deliberately spaces breaks uniformly. Local files use ffprobe chapter metadata, Plex imports Chapter offsets when available, and Jellyfin/Emby imports chapter positions when exposed by the server.

For Classic Scheduling, edit a Schedule Item and click **Commercials / Filler & Graphics**. For Block Scheduling, attach presets directly to the Block item. Sequential schedules can mark any content instruction with `filler_kind`.

## Graphics & Branding

Open **System → Graphics & Branding**.

Graphics are reusable overlay definitions. Two v1.2.0 types are included:

- **Image** — station bugs, logos, ratings graphics, promotional images, etc.
- **Dynamic Text** — lower thirds, Now/Next text and other generated labels.

Position options include corners and center, with margins, image width, opacity, text size/color, optional text box, start/end time and z-index.

Dynamic text variables include `{{channel_name}}`, `{{channel_number}}`, `{{title}}`, `{{show_title}}`, `{{episode_title}}`, `{{season}}`, `{{episode}}`, `{{year}}`, and `{{now}}`.

Graphics may be assigned globally to a channel with **All**, **Primary only** or **Filler only** scope. They may also be attached to Classic items, Block items/Decos, or toggled by Sequential instructions.

When overlays are active ViperTV deliberately uses the reliable software H.264 filter path for that item; otherwise the channel's normal Direct/QSV/VAAPI profile remains available.

## Sequential Scheduling

Open **Scheduling → Sequential**.

Sequential schedules are YAML documents. They have four major sections:

- `content` — reusable named content sources.
- `sequences` — reusable instruction groups.
- `reset` — instructions run once at the beginning of the broadcast day.
- `playout` — looping instructions that construct the day.

Supported content sources include search queries, Collections, Smart/Multi Collections, Playlists, shows, direct Images, saved Marathons and reusable Filler presets. A saved Marathon or Filler preset can therefore be shared by Classic, Block and Sequential schedules instead of being duplicated in YAML.

Supported scheduling instructions include `all`, `count`, `duration`, `pad_to_next`, `pad_until`, and `sequence`.

Control instructions include `graphics_on`, `graphics_off`, `watermark`, `repeat`, `shuffle_sequence`, `skip_items`, `skip_to_item`, `wait_until`, and `epg_group`.

Example:

```yaml
content:
  - collection: "My Shows"
    key: SHOWS
    order: chronological
  - collection: "Commercials"
    key: ADS
    order: shuffle

sequences:
  PRIME:
    - count: 1
      content: SHOWS
    - count: 2
      content: ADS
      filler_kind: midroll

reset:
  - wait_until: "06:00"

playout:
  - sequence: PRIME
    repeat: 8
  - pad_to_next: 30
    content: ADS
    trim: true
    filler_kind: postroll
  - repeat: true
```

Saving a Sequential schedule validates YAML before replacing the active definition. Assigning Sequential to a channel disables Block and Classic on that channel. **Reset** increments the playout generation and clears its persisted cursor.

## Compatibility / precedence

ViperTV keeps the original Classic scheduler and Legacy Time Blocks. Per channel, the intended order is exactly one selected reusable playout mode: **Classic**, **Block**, or **Sequential**. The assignment screens automatically remove the other two modes to avoid ambiguous scheduling.

The shared live-channel producer, Plex direct-Part source path, slow-viewer disconnect model, Pluto recursive HLS proxy and Retro TV engine are not replaced by these scheduling features.


## v1.2.7 scheduler-completion extensions

### Saved Marathons

Open **Scheduling → Marathons** to create reusable Marathon sources. A Marathon accepts one or more Smart Search queries (one per line), then groups matches by **Show**, **Season**, **Artist**, or **Album**. Group order can be kept or shuffled, item order can be chronological or shuffled, and **Play all items** controls whether ViperTV exhausts a group before moving on or rotates one item at a time among groups.

Saved Marathons appear directly as source choices in Classic Schedule items and Block items. Sequential YAML can reference one with:

```yaml
content:
  - key: SHOWS
    marathon: "Sitcom Rotation"
```

### Reusable Advanced Filler sources

Filler presets are no longer limited to a library/collection pool. A preset can source a Local Library, Manual/Smart/Multi Collection, Playlist, entire TV Show, Season, individual Image, or saved Marathon. The same preset is usable by Classic, Block and Sequential schedules.

Sequential YAML can reference a preset directly:

```yaml
content:
  - key: ADS
    filler_preset: "Commercial Break"
```

### Chapter-aware mid-roll

Media rows now carry additive `chapters_json` metadata. Mid-roll strategy **Auto** chooses chapter boundaries when usable metadata exists and otherwise falls back to even spacing. This is intended to place breaks at more natural programme boundaries without requiring manual timestamps.

### Exact fallback filling

Fallback filler can repeatedly use one deterministic item and trim the final repetition to the exact remaining time. This is particularly useful at hard Block boundaries where the next scheduled Block must start on time.

### Clone actions

Blocks and Block Templates now have **Clone** actions so a working daypart or programming pattern can be duplicated and edited without rebuilding it from scratch.

For a focused walkthrough, see `SCHEDULER-COMPLETION.md`.
