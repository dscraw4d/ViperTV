FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata fonts-dejavu-core i965-va-driver vainfo libva2 libva-drm2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Vendor hls.js into the image so browser preview does not depend on Internet access at runtime.
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/hls.js@1.7.3/dist/hls.min.js','/app/app/hls.min.js')"

EXPOSE 8409
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8409/healthz', timeout=3).read()" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8409", "--workers", "1"]
