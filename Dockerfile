FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system heza && useradd --system --gid heza --home /app heza

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN SECRET_KEY=build-only DEBUG=False USE_SQLITE=True python manage.py collectstatic --noinput \
    && mkdir -p /app/media /app/private_media /app/staticfiles-shared \
    && chown -R heza:heza /app/media /app/private_media /app/staticfiles /app/staticfiles-shared \
    && chmod +x /app/docker/entrypoint.sh

USER heza
EXPOSE 8742
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "heza.wsgi:application", "-c", "deploy/gunicorn.conf.py"]
