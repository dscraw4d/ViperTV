# ViperTV Collections — v1.1.39

ViperTV has three collection types.

## Manual Collection

A Manual Collection contains media you explicitly select.

1. Open **Media → Search**.
2. Enter a query, or enter `*` to browse all playable media.
3. Tick the movies, episodes, or shows you want.
4. At **Add Selection To Collection**, choose an existing Collection or type a new Collection name.
5. Click **Add To Collection**.

Use `type:show` when you want search results to be whole shows instead of individual episodes. A whole-show selection automatically expands to its playable episodes when a channel uses the collection.

## Smart Collection

A Smart Collection stores a search query instead of a fixed item list.

1. Open **Media → Search**.
2. Refine the query until the results are correct.
3. Enter a name under **Save As Smart Collection**.
4. Click **Save As Smart Collection**.

ViperTV evaluates the saved search whenever the collection is used. If a later Plex sync or local scan adds matching media, it automatically becomes part of the Smart Collection.

Examples:

```text
type:episode AND actor:"John Ritter" AND year:1980-1989
```

```text
type:show AND network:NBC AND genre:comedy
```

```text
type:movie AND year:199*
```

```text
genre:comedy AND NOT show_title:"Three's Company"
```

## Multi Collection

A Multi Collection combines existing Manual Collections and Smart Collections.

1. Open **Lists → Multi Collections**.
2. Click **Add Multi Collection**.
3. Open the new Multi Collection.
4. Tick the manual and Smart Collections you want it to contain.
5. Click **Save Members**.

A Multi Collection does not copy the source collections. Changes to its member collections are therefore reflected automatically.

## Search syntax

Operators:

- `AND`
- `OR`
- `NOT`
- parentheses: `( ... )`
- quoted phrases: `actor:"John Ritter"`
- wildcards: `year:198*`, `title:*Christmas*`

Supported fields in v1.1.39:

- `title`
- `show_title`
- `type` (`movie`, `episode`, `show`, `tv`)
- `actor`
- `director`
- `network`
- `genre` (when TVDB show metadata is available)
- `library_name`
- `source` (`local`, `plex`, and external server kind where available)
- `year`
- `release_date`
- `season_number`
- `episode_number`
- `plot`
- `status`

Year ranges are supported:

```text
year:1980-1989
```

Release-date wildcards and ranges are supported:

```text
release_date:197*
```

```text
release_date:[19800101 TO 19891231]
```

Searches use metadata already imported into ViperTV. Actor/director searches require People metadata. Network and genre searches use imported show metadata where available.
