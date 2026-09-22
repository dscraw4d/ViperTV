# Third-party components in the Windows standalone distribution

ViperTV's own licensing status is described by `LICENSE-NOTICE.txt`; this file does not assign a license to ViperTV.

The Windows standalone builder downloads and redistributes separate runtime components used to run ViperTV:

- **CPython 3.12** — Python Software Foundation License. Source and license information: https://www.python.org/
- **FFmpeg Windows essentials build** — FFmpeg and the selected build's enabled libraries are distributed under their applicable licenses. The builder uses the Gyan.dev essentials package. FFmpeg source/license information: https://ffmpeg.org/ and https://www.gyan.dev/ffmpeg/builds/
- **FastAPI, Starlette, Pydantic, Uvicorn, python-multipart, Beautiful Soup, PyYAML and their Python dependencies** — installed from PyPI at the exact versions listed in `requirements-windows.txt`; each retains its own upstream license.
- **hls.js** — vendored for local browser HLS playback; upstream license/source: https://github.com/video-dev/hls.js

These components remain separate third-party works. Their copyright notices and license terms continue to apply.

The Windows build script also preserves license/readme files shipped by the upstream FFmpeg package and downloads the hls.js license beside the bundled runtime. Python package `.dist-info` metadata remains in the private runtime.
