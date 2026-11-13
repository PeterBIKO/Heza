# Deployment

Heza runs as a standard Django app: Gunicorn behind Nginx, with HTTPS, PostgreSQL and Redis. A background
job runs `manage.py heza_maintenance` every 5 minutes. There are two supported ways to deploy:

* **A. Docker Compose** on one VPS. This is the quickest.
* **B. A native install** with systemd units.

A 2 vCPU / 4 GB VPS on Ubuntu 24.04 is enough to start.

## Before you go live

* A domain (for example `heza.rw`) pointing at the server.
* Flutterwave **live** keys, with the webhook URL `https://heza.rw/payments/webhooks/flutterwave/` and a
  secret hash set in the Flutterwave dashboard.
* SMTP credentials for email, and Africa's Talking credentials for SMS (optional).
* A strong `SECRET_KEY` and database password. Keep them in the env file only, never in git.
* Disable the sandbox gateway: `PAYMENT_PROVIDERS_ENABLED=flutterwave`. This is already the default when
  `DEBUG=False`.

## A. Docker Compose

```bash
sudo apt install -y docker.io docker-compose-v2 git
sudo git clone <your repo> /srv/heza/app && cd /srv/heza/app
sudo cp .env.example .env.production && sudo nano .env.production
```

Set at least these in `.env.production`:

```ini
DOMAIN=heza.rw
SECRET_KEY=<64 random chars>
POSTGRES_PASSWORD=<random>
ALLOWED_HOSTS=heza.rw,www.heza.rw
CSRF_TRUSTED_ORIGINS=https://heza.rw,https://www.heza.rw
SITE_URL=https://heza.rw
EMAIL_URL=smtp+tls://user:password@smtp.example.com:587
DEFAULT_FROM_EMAIL=Heza <no-reply@heza.rw>
PAYMENT_PROVIDERS_ENABLED=flutterwave
FLUTTERWAVE_PUBLIC_KEY=FLWPUBK-...
FLUTTERWAVE_SECRET_KEY=FLWSECK-...
FLUTTERWAVE_SECRET_HASH=<the hash you set in Flutterwave>
SMS_BACKEND=apps.notifications.backends.AfricasTalkingSMSBackend
AFRICASTALKING_USERNAME=<username>
AFRICASTALKING_API_KEY=<key>
```

Get a certificate. The first time, before Nginx is up, run certbot in standalone mode:

```bash
sudo apt install -y certbot
sudo certbot certonly --standalone -d heza.rw -d www.heza.rw
sudo mkdir -p deploy/certs deploy/acme
sudo cp -L /etc/letsencrypt/live/heza.rw/{fullchain,privkey}.pem deploy/certs/
```

Start the stack:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d --build
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production \
  exec web python manage.py createsuperuser
```

The `web` container runs migrations on start. Nginx serves `/static/` and `/media/`. KYC documents are never
exposed. The `scheduler` container runs maintenance every 5 minutes.

**Renewing certificates.** Use the webroot mode, which Nginx already serves at `/.well-known/acme-challenge/`,
in a monthly cron entry:

```bash
certbot renew --webroot -w /srv/heza/app/deploy/acme --deploy-hook \
  "cp -L /etc/letsencrypt/live/heza.rw/*.pem /srv/heza/app/deploy/certs/ && docker compose -f /srv/heza/app/docker-compose.yml -f /srv/heza/app/docker-compose.prod.yml exec nginx nginx -s reload"
```

**Updating:**

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml --env-file .env.production up -d --build
```

## B. Native install (systemd + Nginx)

```bash
sudo apt install -y python3.12-venv postgresql redis-server nginx certbot python3-certbot-nginx git
sudo useradd --system --home /srv/heza --shell /usr/sbin/nologin heza
sudo mkdir -p /srv/heza/{media,private_media,backups} && sudo chown -R heza:heza /srv/heza
sudo -u heza git clone <your repo> /srv/heza/app
cd /srv/heza/app
sudo -u heza python3.12 -m venv .venv
sudo -u heza .venv/bin/pip install -r requirements.txt

sudo -u postgres psql -c "CREATE ROLE heza LOGIN PASSWORD '<db password>';"
sudo -u postgres createdb -O heza heza
```

Create `/srv/heza/app/.env`, owned by `heza` with mode `600`:

```ini
DEBUG=False
SECRET_KEY=<64 random chars>
ALLOWED_HOSTS=heza.rw,www.heza.rw
CSRF_TRUSTED_ORIGINS=https://heza.rw,https://www.heza.rw
SITE_URL=https://heza.rw
DATABASE_URL=postgres://heza:<db password>@localhost:5432/heza
CACHE_URL=redis://127.0.0.1:6379/1
MEDIA_ROOT=/srv/heza/media
PRIVATE_MEDIA_ROOT=/srv/heza/private_media
SECURE_SSL=True
USE_X_FORWARDED_FOR=True
EMAIL_URL=smtp+tls://user:password@smtp.example.com:587
PAYMENT_PROVIDERS_ENABLED=flutterwave
FLUTTERWAVE_PUBLIC_KEY=...
FLUTTERWAVE_SECRET_KEY=...
FLUTTERWAVE_SECRET_HASH=...
```

Migrate, collect static files, and create an admin:

```bash
sudo -u heza .venv/bin/python manage.py migrate
sudo -u heza .venv/bin/python manage.py collectstatic --noinput
sudo -u heza .venv/bin/python manage.py createsuperuser
sudo -u heza .venv/bin/python manage.py check --deploy
```

Install the services and timers:

```bash
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now heza.service heza-maintenance.timer heza-backup.timer
```

Install the Nginx site and get HTTPS:

```bash
sudo sed 's/heza.example.com/heza.rw/g' deploy/nginx/heza.conf | sudo tee /etc/nginx/sites-available/heza
sudo ln -s /etc/nginx/sites-available/heza /etc/nginx/sites-enabled/heza
sudo mkdir -p /var/www/certbot
sudo certbot certonly --webroot -w /var/www/certbot -d heza.rw -d www.heza.rw   # after a first HTTP-only start, or use --nginx
sudo nginx -t && sudo systemctl reload nginx
```

The certbot package installs its own renewal timer. Nginx must be able to read `/srv/heza/app/staticfiles`
and `/srv/heza/media`:

```bash
sudo chmod o+x /srv/heza /srv/heza/app
```

**Updating:**

```bash
cd /srv/heza/app && sudo -u heza git pull
sudo -u heza .venv/bin/pip install -r requirements.txt
sudo -u heza .venv/bin/python manage.py migrate
sudo -u heza .venv/bin/python manage.py collectstatic --noinput
sudo systemctl reload heza
```

## Operations checklist

* **Firewall**: only ports 22, 80 and 443 open (`ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable`).
  PostgreSQL and Redis listen on localhost or inside the Docker network only.
* **Logs**:
  * `journalctl -u heza -f` (native) or `docker compose logs -f web`;
  * Nginx logs in `/var/log/nginx/`.
* **Webhooks**: the admin panel's *Webhooks* page shows every event, with its signature check result. A burst
  of `invalid signature` entries means a misconfigured secret hash, or someone probing the endpoint.
* **Stuck payments**: maintenance re-verifies pending payments between 2 minutes and 2 days old. Admins can
  also press *Re-verify* on a payment.
* **Backups**: see [backup.md](backup.md). Test a restore at least once a quarter.
* **Scaling**: raise `WEB_CONCURRENCY` (Gunicorn workers). Redis keeps rate limits consistent across
  workers. Media can move to S3-compatible storage with `USE_S3=True` and the `S3_*` settings.
