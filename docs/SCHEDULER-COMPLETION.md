# ViperTV 1.2.7 — Scheduler Completion

ViperTV 1.2.7 completes the common programming layer shared by **Classic Schedules**, **Block Scheduling**, and **Sequential YAML**. The release adds reusable Marathons, one Advanced Filler model across every scheduler, chapter-aware mid-roll placement, exact fallback filling, and clone actions for Blocks/Templates.

## Reusable Marathons

Open **Scheduling → Marathons**. A Marathon is a reusable content source built from one or more Smart Search queries. Enter one query per line, then choose how the resulting programmes are grouped and rotated.

**Group by** supports Show, Season, Artist, and Album. **Item order** supports chronological or shuffled items. **Shuffle groups** randomizes group order. **Play all items** finishes a group before moving to the next; when disabled, ViperTV rotates one item at a time among groups.

Example Marathon queries:

```text
type:episode AND genre:comedy AND year:1980-1989
type:episode AND network:NBC AND year:1980-1989
```

After saving the Marathon, it becomes a normal source choice in Classic Schedule items and Block items.

## Advanced Filler

Open **Lists → Filler**. Presets can be used as **Pre-roll**, **Mid-roll**, **Post-roll**, **Tail**, or **Fallback** filler. They support **Count**, **Duration**, and **Pad** behavior.

A filler preset may source:

- Local Library
- Manual Collection
- Smart Collection
- Multi Collection
- Playlist
- Entire TV Show
- TV Season
- Individual Image
- Saved Marathon

This lets one Commercial Break, Station IDs, Promos, or Dead Air Rescue preset be reused across every scheduler.

### Mid-roll placement

ViperTV stores chapter offsets in `chapters_json` when the source exposes them. Mid-roll strategy **Auto** uses useful chapter boundaries first and falls back to evenly spaced breaks. **Chapters** and **Even** are available when you want explicit behavior. A minimum primary-programme length can be set so very short material is not interrupted.

### Fallback/dead-air behavior

When a fallback preset must fill an exact gap, ViperTV can loop a deterministic fallback item and trim the final pass to the remaining seconds. A fixed Block boundary therefore remains fixed instead of drifting later because filler was too long.

## Classic Scheduling

Classic remains the quickest reusable schedule builder. In addition to Collections, Playlists, shows, seasons and images, a Classic item can now select a saved **Marathon**. Use **Commercials / Filler & Graphics** on a Classic item to attach the same reusable filler presets used elsewhere.

## Block Scheduling

Blocks retain hard wall-clock boundaries. Blocks can use Marathons as item sources and reuse Advanced Filler/Decos for commercial breaks, unused time and dead-air fallback. Both **Blocks** and **Block Templates** can now be cloned.

## Sequential YAML

Sequential schedules can reference saved Marathons and Filler presets instead of duplicating their definitions. Example:

```yaml
content:
  - key: SHOWS
    marathon: "Sitcom Rotation"

  - key: ADS
    filler_preset: "Commercial Break"

sequences:
  PRIME:
    - count: 1
      content: SHOWS
    - count: 2
      content: ADS

playout:
  - sequence: PRIME
  - repeat: true
```

Existing Sequential content sources, sequences, count/duration/padding instructions, reset behavior, graphics instructions and playout instructions remain available.

## Upgrade and persistence

The v1.2.7 database migration is additive. Existing Channels, Classic Schedules, Blocks, Templates, Sequential schedules, Playlists, Collections, People metadata and source configuration are preserved. The recovery-safe drag-and-drop update intentionally contains no Compose files, `.env`, database, backups, or media directories.
