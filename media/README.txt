Optional local media mount.

By default this folder is mounted read-only inside the ViperTV container as /media.
You can either place/symlink media here, or set VIPERTV_MEDIA_DIR in .env to an
existing media directory on the Docker host.

Examples inside ViperTV after mounting:
  /media/TV
  /media/Movies
  /media/Music Videos

For Windows Docker Desktop, use forward slashes in .env, for example:
  VIPERTV_MEDIA_DIR=D:/Media
