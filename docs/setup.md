# Setup and configuration

## Local development

1. Install Python 3.12 and PostgreSQL 14+ (or run `docker compose up -d db redis` for both).
2. Create the virtualenv and install dependencies:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements-dev.txt
   ```

3. Copy `.env.example` to `.env` and set `SECRET_KEY`. Every other default works locally.
4. Create the database. The default URL is `postgres://heza:heza@localhost:5432/heza`:

   ```bash
   sudo -u postgres psql -c "CREATE ROLE heza LOGIN PASSWORD 'heza' CREATEDB;"
   sudo -u postgres createdb -O heza heza
   ```

   `CREATEDB` is only needed so `manage.py test` can create its test database.

5. Migrate, seed and run:

   ```bash
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py seed_demo          # idempotent; --reset removes demo data first
   .venv/bin/python manage.py runserver 0.0.0.0:8742
   ```

6. In a second terminal, run maintenance every few minutes (or just once when needed). It expires unpaid
   holds, marks finished stays completed, and re-checks pending payments with the gateway:

   ```bash
   .venv/bin/python manage.py heza_maintenance
   ```

Emails are printed to the runserver console. That includes verification links, password resets and booking
confirmations. SMS messages are logged the same way. In DEBUG, the "check your inbox" page also shows the
verification link directly.

### SQLite fallback

Only use SQLite when PostgreSQL truly cannot run. Set `USE_SQLITE=True` in `.env`. SQLite ignores the
`select_for_update` row locks that prevent double booking under concurrent requests, so it is not safe for
production. The concurrency test is skipped on SQLite.

### Docker Compose

```bash
docker compose up --build        # Postgres, Redis, web on :8742, scheduler; seeds demo data
SEED_DEMO=0 docker compose up    # without demo data
docker compose exec web python manage.py createsuperuser
```

Compose v2.24 or newer is required.

## Configuration reference (`.env`)

| Variable | Purpose |
| --- | --- |
| `DEBUG` | `True` only for development. With `False`, `SECRET_KEY` must be set or the app refuses to start. |
| `SECRET_KEY` | Long random string. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"`. |
| `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `SITE_URL` | Host names, full origins, and the public base URL used in emails and payment redirects. |
| `DATABASE_URL` | PostgreSQL URL. |
| `CACHE_URL` | `locmemcache://` for one process. In production, use `redis://host:6379/1` so rate limits and settings caching are shared by all workers. |
| `EMAIL_URL` | `consolemail://` in dev, or `smtp+tls://user:pass@host:587`. |
| `PAYMENT_PROVIDERS_ENABLED` | Comma list from `sandbox,flutterwave`. The sandbox is enabled by default only when DEBUG is on. |
| `SANDBOX_WEBHOOK_SECRET` | HMAC secret the sandbox gateway uses to sign webhooks. |
| `SANDBOX_WEBHOOK_DELIVERY` | `inprocess` (default), or `http` to POST the webhook to `SITE_URL` over the network. |
| `FLUTTERWAVE_PUBLIC_KEY`, `FLUTTERWAVE_SECRET_KEY`, `FLUTTERWAVE_SECRET_HASH` | Flutterwave v3 keys. Test keys start with `FLWSECK_TEST-`. The secret hash must match the dashboard webhook setting. |
| `SMS_BACKEND` | `apps.notifications.backends.ConsoleSMSBackend` or `...AfricasTalkingSMSBackend`. |
| `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`, `AFRICASTALKING_SENDER_ID` | Africa's Talking credentials. Use `sandbox` as the username for their sandbox. |
| `WHATSAPP_BACKEND` | Console stub. A Cloud API backend skeleton exists but is not wired to a live account. |
| `USE_S3`, `S3_*` | S3-compatible media storage (AWS, MinIO, Spaces, Wasabi). KYC documents always stay on local private storage. |
| `MEDIA_ROOT`, `PRIVATE_MEDIA_ROOT` | Upload directories. Private media is never served by Nginx. |
| `SECURE_SSL` | `True` behind HTTPS. Enables the SSL redirect, secure cookies and HSTS. |
| `USE_X_FORWARDED_FOR` | `True` only behind the provided Nginx config, so rate limits and the audit log see real client IPs. |
| `RATELIMIT_ENABLED` | Defaults to `True`. Login, registration, password reset, contact and webhook endpoints are throttled. |
| `BOOKING_HOLD_MINUTES` | How long an unpaid booking holds inventory. Defaults to 30. |

## Payments in development

**Sandbox (default).**
1. On a pending booking, choose *Pay now*. You are redirected to `/payments/sandbox/checkout/<txn>/`, a page
   clearly marked TEST MODE.
2. Approve or decline there. The sandbox posts a webhook signed with `X-Heza-Sandbox-Signature: t=<ts>,v1=<hmac>`.
3. Heza checks the signature and the timestamp (5-minute tolerance), and stores the event only once.
4. Heza then calls the gateway's verify endpoint server-side, and confirms the booking only if the amount,
   currency and reference match.

The browser return page never confirms anything by itself.

**Flutterwave test mode.**
1. Put your test keys in `.env`.
2. Set the webhook URL in the Flutterwave dashboard to `https://<your-host>/payments/webhooks/flutterwave/`,
   and copy its secret hash into `FLUTTERWAVE_SECRET_HASH`.
3. For local testing, expose port 8742 with a tunnel such as `cloudflared` or `ngrok`, and set `SITE_URL` to
   the tunnel URL.

Card numbers and CVVs never touch Heza. Guests enter them on the gateway's hosted page.
