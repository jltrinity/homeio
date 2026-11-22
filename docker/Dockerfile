FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 homeio \
    && useradd --uid 10001 --gid homeio --no-create-home homeio \
    && mkdir /data && chown homeio:homeio /data
COPY --chown=homeio:homeio homeio ./homeio
COPY --chown=homeio:homeio docker/entrypoint.sh ./entrypoint.sh
USER homeio
ENV HOMEIO_DATABASE=/data/homeio.sqlite3
EXPOSE 8000
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "30", "--worker-tmp-dir", "/tmp", "homeio.web.app:create_app()"]
