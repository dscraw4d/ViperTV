# ViperTV v1.2.7 — Scheduler Completion

Created by Darren “The Viper” Crawford.

## Highlights

ViperTV 1.2.7 completes the shared scheduling layer introduced in the 1.2 series. **Classic Schedules, Block Scheduling and Sequential YAML** can now reuse the same Marathon and Advanced Filler sources rather than maintaining separate approximations.

### First-class Marathons

- Saved/reusable Marathon objects under **Scheduling → Marathons**.
- Combine one or more Smart Search queries.
- Group by Show, Season, Artist or Album.
- Chronological or shuffled item order.
- Optional shuffled group order.
- Play every item in a group or rotate one item per group.
- Use the same Marathon from Classic, Block or Sequential scheduling.

### Advanced Filler completion

- Reusable Pre-roll, Mid-roll, Post-roll, Tail and Fallback presets.
- Count, Duration and Pad modes.
- Sources can be a Local Library, Manual/Smart/Multi Collection, Playlist, whole Show, Season, Image or saved Marathon.
- Chapter-aware Mid-roll placement when source chapter metadata is available.
- Automatic even-spacing fallback when chapters are unavailable.
- Exact loop-and-trim Fallback behavior for fixed schedule gaps/dead air.

### Sequential and Block improvements

- Sequential YAML accepts `marathon: "Name"` and `filler_preset: "Name"`.
- Blocks and Block Templates can be cloned.
- Existing Decos, watermark policies, Graphics & Branding and hard Block boundaries remain supported.

## Upgrade safety

The migration is additive and preserves the existing ViperTV database. The recovery-safe update contains no Compose YAML, `.env`, databases, backups or media. Leave the working OMV Compose configuration untouched.
