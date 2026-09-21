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

For Plex libraries, use the normal Plex metadata sync. For local media, run the normal library scan so ViperTV can re-read `tvshow.nfo` and sidecar episode/movie NFO files.
