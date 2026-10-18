FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-ai.txt requirements.txt ./
RUN pip install --no-cache-dir -r requirements-ai.txt
COPY editor.py server.py ./
COPY web/ ./web/
RUN useradd -m -u 10001 appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
ENV EDITOR_DATA_DIR=/data WHISPER_MODEL=base WHISPER_DEVICE=cpu
EXPOSE 8000
CMD ["uvicorn","server:app","--host","0.0.0.0","--port","8000","--workers","1"]
