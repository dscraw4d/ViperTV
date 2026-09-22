# ViperTV Classic Scheduling — introduced in v1.1.46 (current release v1.2.0)

ViperTV v1.1.46 adds reusable **Classic Schedules** and **Playouts**. The workflow is deliberately similar to ErsatzTV's Classic Schedule model: a Schedule describes the programming rules, while a Playout assigns that Schedule to a channel.

## 1. Schedule vs. Playout

A **Schedule** is a reusable list of programming instructions. It does not belong to one particular channel.

A **Playout** connects one Schedule to one ViperTV channel. This means you can build a schedule named `Weekday Sitcoms` once and assign it to several channels. Each channel has its own playout generation/reset state.

Open:

- **Scheduling -> Schedules** to create/edit schedules.
- **Scheduling -> Playouts** to attach them to channels.
- **Guide** to preview the resulting programming.

Existing ViperTV time blocks from older releases are kept as **Legacy Time Blocks**. A Classic Playout takes precedence when one is assigned. Removing the Classic Playout makes the channel fall back to its legacy blocks/normal channel selections.

## 2. Schedule settings

Each Classic Schedule has four schedule-level options.

### Keep Multi-Part Episodes Together

When a selected episode looks like a multi-part story (`Part 1`, `Part 2`, etc.), ViperTV attempts to keep the following parts together in the correct order.

### Treat Collections As Shows

When multi-part grouping is enabled, this lets adjacent part-numbered items remain grouped even when the parts cross show boundaries. This is useful for crossover events stored in one Collection.

### Shuffle Schedule Items

The schedule-item rows themselves are shuffled for the broadcast day. Fixed starts are treated as dynamic and Flood behaves as One while this option is enabled, because a shuffled instruction list cannot reliably preserve hard clock starts.

### Random Start Point

Each playout begins its content pools at a deterministic random point instead of always beginning at the first episode/item.

## 3. Add a Schedule Item

Open a Schedule and choose **Add Schedule Item**.

### Programming source

A Schedule Item can use:

- **Collection** — a manually built ViperTV Collection.
- **Smart Collection** — a saved search that updates automatically.
- **Multi Collection** — a collection of Collections/Smart Collections.
- **Playlist** — an ordered ViperTV Playlist.
- **TV Show** — all indexed episodes of a show from Local, Plex, Jellyfin or Emby.
- **TV Season** — one indexed season of a show.

This is why Collections and Playlists are particularly useful: build the content pool first, then schedule the pool.

## 4. Start Type

### Dynamic

The item begins immediately after the preceding Schedule Item finishes.

### Fixed

The item targets a particular clock time such as `20:00`.

**Flexible** allows the item to begin immediately when a previous item has already carried the schedule past the requested time.

**Strict** will not force a late start for that day's fixed event. The daily builder leaves the fixed event for the next valid broadcast-day occurrence instead of pretending it started on time.

When ViperTV needs to wait for a fixed time, it creates a black/silent `Off Air` gap so the clock remains aligned.

## 5. Playback Order

### Chronological

Orders media by date and then by season/episode information when available.

### Season, Episode

Sorts TV episodes by show, season number and episode number.

### Shuffle

Produces a shuffled pool without repeating an item until the current pool has been exhausted.

### Random

Chooses from the source randomly and may repeat items.

### Shuffle In Order

Maintains chronological order within each show/group while mixing the groups together.

## 6. Playout Mode

### One

Play one media item, then advance to the next Schedule Item. With multi-part grouping enabled, a detected multi-part episode group can stay together.

### Multiple

Play multiple items before advancing.

Available Multiple modes:

- **Count** — play the configured number.
- **Collection Size** — play the complete source pool.
- **Multi-Episode Group Size** — play the current detected multi-part group.
- **Playlist Item Size** — use one logical Playlist entry per rotation (currently one expanded media item when the source has already been flattened).

### Duration

Fill a time budget, such as 30, 60 or 120 minutes, with complete media items that fit.

For Shuffle/Random sources, **Discard To Fill Attempts** tells ViperTV how many alternate items it may try when the next item is too long for the remaining time.

### Flood

Keep playing the source until the next unused Fixed Schedule Item. If no later Fixed item exists in that broadcast day, Flood continues to the end of the day.

A common pattern is:

1. Dynamic + Flood — daytime TV collection
2. Fixed 20:00 + One — movie collection
3. Dynamic + Flood — late-night collection

## 7. Fill With Group

For Collections/Smart Collections containing multiple shows, Duration or Multiple blocks can be constrained to one group at a time.

- **None** — use the full pool.
- **Ordered Groups** — rotate groups in name order.
- **Shuffled Groups** — rotate groups in a stable shuffled order.

Example: a Smart Collection containing `Cheers`, `Night Court` and `Family Ties` can fill a two-hour block from one show before rotating to the next group.

## 8. Duration Tail

When a Duration block cannot fit another complete program:

- **None** — advance immediately to the next Schedule Item.
- **Offline / black** — fill the unused tail with black video and silent audio.
- **Filler Collection** — try clips from the chosen Collection; any final unusable remainder becomes a hidden filler gap.

## 9. EPG controls

### Custom EPG Title

Overrides the displayed program title for media produced by that Schedule Item. For example, individual cartoons can appear in the guide under `Saturday Morning Cartoons`.

### Guide Mode

- **Normal** — include the item in ViperTV/XMLTV guide output.
- **Filler** — treat it as secondary content and omit it from XMLTV guide entries.

## 10. Reordering and editing

On a Schedule page:

- **Edit** changes a Schedule Item.
- **Up / Down** changes item order.
- **Delete** removes only the instruction, not its Collection/media.
- **Clone Schedule** makes an independent copy.

## 11. Assigning a Playout

Open **Scheduling -> Playouts**.

For a channel, select the desired Classic Schedule and click **Assign**.

Choose **No Classic Schedule** to detach it. The channel then uses its old channel selections and/or Legacy Time Blocks again.

### Reset Playout

**Reset Playout** increments that channel's playout generation and clears its Classic playout cursor. This gives shuffle/random schedules a fresh independent starting generation without deleting the Schedule.

## 12. Examples

### 24/7 one-show channel

- Source: TV Show — `M*A*S*H`
- Start: Dynamic
- Playback Order: Season, Episode
- Playout Mode: One

The Schedule loops continuously through episodes.

### Balanced sitcom rotation

Add one Dynamic / One item for each show:

1. Cheers
2. Night Court
3. Family Ties
4. Three's Company

Each trip through the Schedule advances each show's episode pool.

### Prime-time movie at 8 PM

1. Daytime Smart Collection — Dynamic / Flood
2. Movies Collection — Fixed `20:00` / One
3. Late Night Collection — Dynamic / Flood

The daytime flood stops at the 8 PM hard boundary; if a complete item cannot fit, ViperTV holds the remaining time with `Off Air` rather than starting something that would run across the movie start.

### 30-minute padded cartoon slot

- Source: Cartoon Smart Collection
- Playout Mode: Duration
- Duration: 30 minutes
- Tail: Filler Collection
- Tail Filler: Bumpers / Commercials

ViperTV fills the slot with complete content and uses filler for the remainder.

## 13. Compatibility

The Classic Scheduling migration is additive, and the current v1.2.0 advanced-scheduling migration is also additive. It does not remove or reset:

- channels
- media libraries
- Plex/Jellyfin/Emby setup
- Collections / Smart Collections / Multi Collections
- Playlists
- People metadata
- older ViperTV Schedule blocks

Classic Playouts simply take precedence while assigned.

## 14. Scope in v1.2.0

Classic Schedule / Playout remains fully supported. ViperTV v1.2.0 additionally implements its own **Block Scheduling**, advanced **Commercial/Filler**, **Graphics & Branding**, and **Sequential YAML Scheduling** layers. See `ADVANCED-SCHEDULING.md` for those systems. Legacy Time Blocks remain available for older configurations.
