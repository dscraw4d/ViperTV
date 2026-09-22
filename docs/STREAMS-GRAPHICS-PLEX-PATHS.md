# ViperTV v1.2.9 — Stream Selection, Graphics Engine 2.0 and Plex Direct Paths

## Stream selector
Open **System → Audio / Subtitles**. Create a profile, add rules from highest to lowest priority, then select it globally or assign it to individual channels.

Audio and subtitle rules are evaluated independently. A rule can constrain language, title text, codec, channel count, forced/default, SDH, external status, ViperTV channel and time window. Overnight windows are supported (for example 22:00–06:00).

When no advanced selector is active, ViperTV retains the channel's legacy subtitle setting. Subtitle `Copy` is used only for codecs that can be safely carried by the MPEG-TS station output; incompatible text subtitles are burned instead so playback remains usable.

## Graphics Engine 2.0
Open **System → Graphics & Branding**. Reusable graphics may now be Image, Dynamic Text, Subtitle Graphic, or Motion / Video Overlay. Z-index and start/end timing apply to the reusable stack.

Subtitle Graphics render the subtitle selected by the active Stream Selector and accept an optional FFmpeg/libass ASS style string. Motion overlays accept a container-visible media path and may loop.

Dynamic text supports: `{{channel_name}}`, `{{channel_number}}`, `{{title}}`, `{{show_title}}`, `{{episode_title}}`, `{{episode_code}}`, `{{season}}`, `{{episode}}`, `{{year}}`, `{{air_date}}`, `{{rating}}`, `{{network}}`, `{{artist}}`, `{{album}}`, `{{library}}`, `{{time}}`, `{{date}}`, and `{{weekday}}`.

## Plex stream from disk
Open **Plex → Direct Media Paths**. Add one or more mappings from the path Plex reports to the path visible inside the ViperTV container.

Example:

- Plex path: `D:\Media\TV`
- ViperTV container path: `/mnt/share2`

If Plex reports `D:\Media\TV\MASH\S02E13.mkv`, ViperTV tests `/mnt/share2/MASH/S02E13.mkv`. If it exists, the station reads it directly. If it does not, the normal Plex Media Part URL is used automatically.

Path replacements do not create Docker mounts. The destination must already be visible inside the ViperTV container through your OMV Compose configuration.
