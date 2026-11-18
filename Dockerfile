FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /data /media \
    && chown -R appuser:appuser /data /media

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY main.py ./
RUN pip install --no-cache-dir .

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

USER appuser
ENV DATABASE_PATH=/data/news_reels.db \
    OUTPUT_DIR=/media \
    PYTHONUNBUFFERED=1

VOLUME ["/data", "/media"]
ENTRYPOINT ["/entrypoint.sh"]
CMD ["status"]
