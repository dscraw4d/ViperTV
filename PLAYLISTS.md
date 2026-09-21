# ViperTV Playlists

ViperTV v1.1.40 adds ordered Playlists for building programming from whole TV
shows and existing Collections.

## Create a Playlist

Go to **Lists -> Playlists**, enter a name, and click **Create Playlist**.

You can also create a Playlist while viewing a TV show. Open **Media ->
Libraries**, browse a library, click a TV show, then use **Add Entire Show To
Playlist**. Enter a new Playlist name instead of selecting an existing Playlist.

## Add a TV Show

1. Open **Media -> Libraries**.
2. Click **Browse** beside a Local, Plex, Jellyfin or Emby library.
3. Click the TV-show title.
4. In **Add Entire Show To Playlist**, choose an existing Playlist or enter a
   new Playlist name.
5. Choose a playback order.
6. Click **Add Entire Show**.

Supported playback orders are:

- **Season / Episode** — season number, then episode number.
- **Chronological** — air date/year, then season and episode.
- **Shuffle** — stable shuffled order for that Playlist entry.
- **Random Daily Order** — a shuffled order that changes with the day.

## Add a Collection

Open **Lists -> Playlists -> Edit** for the Playlist. Under **Add Collection To
Playlist**, choose any Manual, Smart or Multi Collection and its playback order.

## Reorder a Playlist

The Playlist editor shows entries from top to bottom. Use the up/down arrows to
move an entry. Use **Remove** to delete an entry from the Playlist. This does not
delete the underlying TV show, Collection or media files.

## Use a Playlist on a Channel

1. Open **Scheduling -> Channels**.
2. Open **Schedule / Presentation** for a channel.
3. Add a time block.
4. In **Programming Source**, select `Playlist — <name>`.
5. For the Playlist's own entry order, use **sequential** schedule mode.

Shuffle/random schedule modes may reorder the fully expanded Playlist for that
schedule block.

## TV Show Metadata Pages

Clicking a TV show from **Media -> Libraries** or **Media -> TV Shows** opens a
show page containing all metadata currently available inside ViperTV, including:

- source and library
- network and original year
- TVDB genres and series status when imported
- actors and character names
- directors
- number of seasons and episodes
- total runtime
- episode numbers, titles, air dates/years, runtimes and episode plots when available

Metadata fields that were never supplied by the source are left out rather than
invented.


## Adding Movies

Open **Media → Movies**, or browse a library under **Media → Libraries**, and click a movie title. The movie metadata page has **Add Movie To Playlist**. You can choose an existing Playlist or create a new one in the same step. A movie is stored as one exact Playlist entry and can be moved up/down like any other entry.
