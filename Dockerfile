FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 STUDIO_MODE=server STUDIO_BIND=0.0.0.0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 studio && useradd --uid 1000 --gid studio --create-home studio
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py studio.py services.py security.py export_queue.py uploads.py teleprompter.py narration.py mixing.py lifecycle.py workspace.py manage.py ./
COPY static/ ./static/
RUN mkdir /data && chown studio:studio /data
USER studio
EXPOSE 8787
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import os,urllib.request; from urllib.parse import urlsplit; r=urllib.request.Request('http://127.0.0.1:8787/api/health',headers={'Host':urlsplit(os.environ['STUDIO_PUBLIC_URL']).netloc}); urllib.request.urlopen(r,timeout=4).read()"
CMD ["python", "app.py", "--data", "/data"]
