# SARDO360 — Property Insight

Flask application for aggregating, de-duplicating and analysing luxury property
listings scraped from multiple Algarve agencies.

## Running it

```bash
python -m venv venv
venv/Scripts/activate            # Windows;  source venv/bin/activate on Unix
pip install -r requirements.txt

cp env.example .env              # then fill in the values
python run.py                    # http://localhost:5002
```

Production uses a real WSGI server and never enables debug:

```bash
gunicorn --bind 0.0.0.0:5002 wsgi:app
```

## Tests

```bash
python tests/test_smoke.py       # no test framework required
pytest tests/                    # pip install -r requirements-dev.txt
```

The smoke suite asserts that every route is registered, the data layer exposes
its full method surface, pages render, every split stylesheet is served, and the
main APIs answer with the expected shape. It talks to the real database, so it
needs a working `.env`.

## Layout

```
run.py / wsgi.py          entry points (dev / production)
config.py, database.py    thin re-export shims kept so scripts/ and migrations/
                          keep working; the real code lives in app/

app/
  __init__.py             create_app() — blueprints, hooks, error handlers
  config.py               every setting, read from the environment
  extensions.py           shared singletons (db, S3, mailer, PDF, login manager)

  routes/                 one blueprint per area of the URL space
    pages.py              /, /reports, /scraper-logs
    auth.py               login, OTP, TOTP/MFA, sessions
    properties.py         search, detail, tags, manual records, documents
    market_intelligence.py  the analytics dashboard API
    scrapers.py           scraper activity and log streaming
    exports.py            PDF and Excel export

  repositories/           data access, one module per domain, recomposed into a
                          single DatabaseManager in __init__.py
  services/               business logic: auth, email, exports, PDF, S3, grouping
  utils/                  formatting, request helpers, security primitives
  models/                 the Flask-Login user model

  templates/
    pages/                one file per rendered page
    components/           shared partials (document head, stylesheet links)
    legacy/               kept but not rendered by any route
  static/
    css/                  base, layout, utilities, responsive, components/, pages/
    js/                   main.js, pages/, vendor/
    assets/  images/  pdfs/

migrations/               numbered schema migrations, run directly
scripts/                  one-off maintenance scripts, run directly
tests/                    smoke tests
fonts/                    TTFs registered by the PDF generator
```

### Notes on the structure

- **Repositories are mixins.** `DatabaseManager` is composed from one mixin per
  domain, so every existing `db_manager.<method>()` call site works unchanged
  while each domain lives in its own file.
- **Stylesheets are split but order-dependent.** The files in `static/css`
  concatenate, in the order listed in `templates/components/stylesheets.html`,
  to exactly the CSS that used to live in one `style.css`. Re-ordering those
  links changes the cascade.
- **Endpoints are blueprint-qualified.** `url_for` needs the prefix:
  `url_for('pages.index')`, `url_for('auth.logout')`.

## Configuration

Every setting is read from the environment in `app/config.py`; `env.example`
documents all of them. Several security keys fall back to a value hard-coded in
that file — the app logs a warning at startup for each one still on its default.
Set `FLASK_SECRET_KEY`, `SECRET_KEY`, `JWT_SECRET_KEY` and `MFA_ENCRYPTION_KEY`
in `.env` before deploying.
