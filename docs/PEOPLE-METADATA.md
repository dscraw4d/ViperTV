# Actor and director metadata (v1.1.38)

ViperTV can index people credits without requiring TheTVDB metadata enrichment.

## Plex

Add the Plex server under **Media Sources → Plex**, then run **Sync All Libraries**. ViperTV imports actor, character and director credits exposed by Plex.

## Local media

ViperTV can import people data from `tvshow.nfo` and episode/movie sidecar NFO files, including `<actor>` and `<director>` entries. Run a normal local library scan after adding or changing NFO files.

## AI Channel Builder examples

- `Make channel 84 called John Ritter 80s with TV starring John Ritter from the 1980s.`
- `Create a channel starring John Ritter.`
- `Make an 80s TV channel directed by Dave Powers.`

For people + decade/year requests, ViperTV filters TV by each episode's air date rather than only by the series premiere year.
