# ViperTV People

ViperTV's **Media -> People** area is the actor/director view of the media already indexed by ViperTV.

## Opening a person

Open **Media -> People**, search for a name, then click the person's name or **View Person**. Actor and director names shown on TV-show and movie metadata pages are clickable too.

## Person metadata

A person page shows the metadata ViperTV can prove from the imported Plex/local-NFO credit index:

- name
- actor/director role(s)
- imported character names
- source types and libraries
- years represented by matching media in your library
- movie count
- TV-show count
- matching TV-episode count
- number of imported credit records

The year range is the span of matching media in your own library. It is not a birth/death-date biography field.

## Movies

Every matching movie is listed with its year, actor/director credit, character (when known), library and a link to the movie metadata page.

## TV shows and episodes

TV credits are grouped by show. ViperTV then lists the individual matching episodes with season/episode number, episode title, air date/year, credit and character.

ViperTV also shows **Credit Scope**:

- **Episode credit** — the source supplied an actor/director credit for that exact episode.
- **Series cast** — the source supplied series-level cast metadata. ViperTV applies that series credit to the indexed episodes for collection/search/channel purposes.
- **Series director** — the source supplied series-level director metadata rather than an exact episode credit.

This distinction prevents ViperTV from presenting inherited series metadata as though it were an episode-specific source record.

## Create an actor or director Collection

On the person's page, use **Create Actor Smart Collection** or **Create Director Smart Collection**. You can change the proposed collection name before creating it.

These are dynamic Smart Collections. ViperTV stores an exact-name people query such as:

`actor_exact:"John Ritter"`

or:

`director_exact:"James Burrows"`

When later Plex syncs or local scans add matching media, the Smart Collection updates automatically.

## Refreshing People metadata

For Plex TV libraries, **Sync Metadata** now imports two layers: the fast catalog listing and a batched full-episode metadata pass. The full pass is where Plex exposes episode-level `Role` and `Director` records that are often omitted from a normal library listing.

The Plex page shows **Rich Episodes** as `checked / total`. Use **Refresh Rich Credits** to force all episodes to be read again after refreshing metadata in Plex. The first rich import can take longer on a large library, but later normal syncs only revisit new or changed episodes by comparing Plex `updatedAt`.

For local media, run the normal library scan so ViperTV can re-read `tvshow.nfo` and sidecar episode/movie NFO files.


## v1.1.44 exact episode behavior

People pages no longer expand a series-level cast/director credit into every episode.
If ViperTV has exact episode credits, only those episodes are listed and used by
person-created Smart Collections. A series-level-only credit is shown as an
association with the series, with a note that exact episode metadata is unavailable.

The person page is also optimized for large libraries: it reads the indexed credit
rows for that one person and fetches only referenced media instead of scanning every
movie and episode in the database.


## v1.1.45 richer Plex episode metadata

Plex's ordinary library listing can return partial episode objects without cast/director arrays even when Plex itself knows those credits. ViperTV v1.1.45 requests complete episode metadata in batches. This allows one-off guest stars and episode directors to be associated with the actual episodes instead of the whole series.

If a person still has only a series-level association after **Refresh Rich Credits**, refresh that show/episode's metadata in Plex and run the ViperTV refresh again. ViperTV does not fabricate episode appearances when Plex does not provide them.
