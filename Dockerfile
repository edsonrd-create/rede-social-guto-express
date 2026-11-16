FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd -u 10001 -m appuser && mkdir /data && chown appuser /data
COPY --chown=appuser:appuser . .
USER root
ENV DATABASE_PATH=/data/app/guto-social.sqlite3 ASSETS_ROOT=/data/app/reviewed-assets ARTIFACTS_ROOT=/data/app/generated-posts REMOTE_MODE=true LIVE_PUBLISH=false
CMD ["python", "bootstrap.py"]
