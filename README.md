# Social Engine Pro

## Run locally

Python 3.9 or newer is required. Install the dependencies and start the Flask
application from the project root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

The app listens on `http://127.0.0.1:5002` by default. For local development,
it creates `social_engine_local.db` automatically. Set `LOCAL_DATABASE_PATH` to
change that location. To use PostgreSQL instead, set `DATABASE_URL`; the
PostgreSQL database is initialized at startup.

Set `GOOGLE_API_KEY` to enable content generation. SMTP is optional; configure
`SMTP_USER` and `SMTP_PASSWORD`, or use `GMAIL_ADDRESS` and
`GMAIL_APP_PASSWORD`, to send verification and reset emails.
