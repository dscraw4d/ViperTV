# ViperTV security notes

ViperTV 1.2.0 does **not** provide a built-in administrator login for the web UI.
Treat the web interface as a trusted-LAN service.

- Do not port-forward TCP 8409 directly to the public Internet.
- If remote access is required, place ViperTV behind a reverse proxy/VPN with authentication and TLS.
- Plex tokens, Jellyfin/Emby API keys and optional TheTVDB credentials are stored in ViperTV's persistent database under `./data`.
- Keep `./data` and backups private and do not include them when redistributing a package.
- Local media is mounted read-only by the supplied Compose file.
