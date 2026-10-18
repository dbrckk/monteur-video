FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-ai.txt requirements.txt ./
# Full image uses Whisper CPU; CI/light installs remain FFmpeg-functional.
ARG INSTALL_WHISPER=0
RUN if [ "$INSTALL_WHISPER" = "1" ]; then \
      pip install --no-cache-dir -r requirements-ai.txt; \
    else \
      pip install --no-cache-dir -r requirements.txt; \
    fi
COPY editor.py montage.py visual_quality.py soundtrack.py server.py ./
COPY web/ ./web/
RUN useradd -m -u 10001 appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV EDITOR_DATA_DIR=/data HF_HOME=/data/huggingface WHISPER_MODEL=base WHISPER_DEVICE=cpu
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/health',timeout=4).read()" || exit 1
EXPOSE 8000
CMD ["sh","-c","exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
