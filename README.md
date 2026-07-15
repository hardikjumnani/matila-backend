# Anonymous Delayed Chat — Backend

Production backend for the Anonymous Delayed Chat application: verified college
students are anonymously matched and chat for up to 72 hours, with an optional
mutual, paid identity reveal.

- **Framework:** Django + Django REST Framework + Django Channels
- **Datastore:** PostgreSQL (persistent state), Redis (cache, channel layer, Celery broker)
- **Async:** Celery + Celery Beat
- **Integrations:** Firebase Authentication, AWS S3, Firebase Cloud Messaging, Razorpay
- **Architecture:** Layered Modular Monolith (thin views/consumers, fat domain services)

## Architecture

```
Flutter client
      │
HTTP (DRF) / WebSocket (Channels)
      │
Views / Consumers        ← thin: auth, validation, delegate, respond
      │
Domain Services          ← all business rules, state transitions, transactions
      │
Django ORM → PostgreSQL
```

## Repository layout

```
Backend/
├── apps/                 # domain apps (one bounded context each)
│   ├── common/           # shared: UUID base models, ServiceResult, exceptions
│   ├── users/            # profile & onboarding
│   ├── verification/     # college ID + gesture selfie verification
│   ├── matchmaking/      # match queue & pairing
│   ├── chats/            # chat lifecycle
│   ├── messaging/        # messages (labelled "messaging" to avoid the
│   │                     #   django.contrib.messages label collision)
│   ├── reveal/           # reveal intent & completion
│   ├── payments/         # Razorpay orders, verification, webhooks
│   ├── reports/          # reporting & moderation records
│   ├── ratings/          # post-chat ratings
│   ├── notifications/    # in-app notifications & FCM delivery
│   ├── configuration/    # feature flags & runtime config
│   ├── audit/            # audit log
│   └── admin_panel/      # admin review & moderation APIs
│       └── each app: services/  tasks/  tests/  migrations/
├── config/               # project: settings/, asgi, wsgi, urls, celery, routing
├── requirements/         # base.txt, development.txt, production.txt
└── manage.py
```

## Local setup

```bash
# 1. Create and activate a virtual environment
py -m venv .venv
.venv/Scripts/activate           # Windows
# source .venv/bin/activate      # macOS/Linux

# 2. Install development dependencies
python -m pip install -r requirements/development.txt

# 3. Configure environment
cp .env.example .env             # then edit values
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 4. Run checks
python manage.py check
```

## Settings modules

| Module | Use |
|--------|-----|
| `config.settings.development` | Local development (default). |
| `config.settings.production`  | Production. Fails fast without PostgreSQL + Redis. |

Select with `DJANGO_SETTINGS_MODULE`.

## Testing

Tests run under `pytest` with `pytest-django`, using the self-contained
`config.settings.test` settings (SQLite, in-memory cache/channel layer, eager
Celery) — no `.env` or external services required. External integrations
(Firebase, Razorpay, S3) are mocked.

```bash
pytest                       # run the suite
pytest --cov --cov-report=term-missing   # with coverage
```

Shared factory-boy factories live in `tests/factories.py`. CI
(`.github/workflows/ci.yml`) runs ruff, black --check, a migration-drift check,
and pytest with an 85% coverage gate on Python 3.10 and 3.11.

## Runtime entrypoints

| Process | Command (production) | Serves |
|---------|----------------------|--------|
| REST API | `gunicorn config.wsgi:application` | HTTP |
| WebSockets | `daphne config.asgi:application` | WebSocket |
| Worker | `celery -A config worker` | Async tasks |
| Scheduler | `celery -A config beat` | Scheduled tasks |
