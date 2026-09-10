"""Production entry point.

Serve with a real WSGI server, e.g.::

    gunicorn --bind 0.0.0.0:5002 wsgi:app

Debug mode is never enabled here.
"""

from app import create_app

app = create_app()
