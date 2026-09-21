# OpenMediaVault / Compose installation

ViperTV can be used as a normal OMV Compose project.

1. Create a project directory and copy this package into it.
2. Edit `.env` to set `TZ`, `VIPERTV_PLEX_AUTO_SYNC_TIMEZONE`, Pluto region and (optionally) `VIPERTV_MEDIA_DIR`.
3. For NAS storage, replace the relative `./data` and `./backups` bind mounts in `compose.yml` with absolute OMV paths if desired.
4. Keep local media mounts read-only (`:ro`). You may add additional mounts such as `/mnt/tv:/media/tv:ro`.
5. Bring the project up with OMV Compose or `docker compose up -d --build`.
6. Open `http://<OMV-LAN-IP>:8409`.

If the host has compatible Intel graphics and `/dev/dri`, you can merge `compose.intel-vaapi.yml`; otherwise keep the default software profile.
