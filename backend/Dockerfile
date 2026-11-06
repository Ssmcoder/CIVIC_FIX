# CrowdResolve backend — FastAPI + SQLAlchemy
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY seed ../seed 2>/dev/null || true

# media + sqlite live on a mounted volume in production
ENV MEDIA_DIR=/data/media DATABASE_URL=sqlite+aiosqlite:////data/civicfix.db
RUN mkdir -p /data/media
VOLUME /data

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
