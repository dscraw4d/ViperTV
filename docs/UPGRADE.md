# Upgrading ViperTV

The supplied public package keeps persistent state in `./data` and rolling secondary backups in `./backups`.

1. Stop ViperTV: `docker compose down`.
2. Make an extra copy of `data/` and `.env`.
3. Replace the application/package files with the newer release **without deleting `data/`, `backups/`, or `.env`**.
4. Run `docker compose up -d --build`.
5. Check `docker compose logs --tail=200 vipertv`.

For v1.1.38 specifically, run **Plex → Sync All Libraries** once after upgrading so actor/director credits are indexed. Local libraries should be scanned again if you want NFO people metadata imported.


## v1.1.39 collection upgrade

No database reset or conversion is required. Existing manual, Smart and Multi Collections remain in the database. New Smart Collections should be created from **Media → Search → Save As Smart Collection**. Legacy v1.1.38 field/value Smart Collection rules are still recognized for compatibility.
