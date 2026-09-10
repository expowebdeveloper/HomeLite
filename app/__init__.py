"""Application factory.

Replaces the former single-module app.py. Route handlers now live in
``app/routes`` as blueprints, business logic in ``app/services`` and data access
in ``app/repositories``; this module only wires them together.
"""

import logging

from datetime import timedelta
from flask import Flask, jsonify, redirect, request, session, url_for
from flask_login import current_user, logout_user

from app.config import Config, warn_on_insecure_defaults

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    app.config['JWT_SECRET_KEY'] = Config.JWT_SECRET_KEY
    app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(seconds=Config.JWT_ACCESS_EXPIRY)

    # Strict session cookie configuration
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)

    warn_on_insecure_defaults()

    _register_extensions(app)
    _register_blueprints(app)
    _register_request_hooks(app)
    _register_error_handlers(app)
    return app


def _register_extensions(app):
    from app.extensions import login_manager
    from app.models import user as _user_model  # noqa: F401 — registers the user_loader

    login_manager.init_app(app)
    login_manager.login_view = 'auth.auth_portal'

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized', 'authenticated': False}), 401
        return redirect(url_for('auth.auth_portal', next=request.path))


def _register_blueprints(app):
    from app.routes import auth, exports, market_intelligence, pages, properties, scrapers

    for module in (pages, auth, properties, market_intelligence, scrapers, exports):
        app.register_blueprint(module.bp)


def _register_request_hooks(app):
    from app.extensions import db_manager

    @app.after_request
    def add_security_headers(response):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: "
            "https://fonts.googleapis.com https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
            "img-src 'self' data: https://*.s3.amazonaws.com;"
        )
        return response

    @app.before_request
    def check_flask_session():
        # Only protect non-API routes that use Flask-Login
        if request.path.startswith('/api/'):
            return

        if current_user.is_authenticated:
            token = session.get('refresh_token')
            if not token or not db_manager.validate_session_token(token):
                logout_user()
                session.clear()
                return redirect(url_for('auth.auth_portal'))


def _register_error_handlers(app):
    """Return JSON for API paths and let pages fall through to Flask's default."""

    def _wants_json():
        return request.path.startswith('/api/')

    @app.errorhandler(404)
    def not_found(error):
        if _wants_json():
            return jsonify({'error': 'Not found'}), 404
        return error, 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.exception('Unhandled error on %s', request.path)
        if _wants_json():
            return jsonify({'error': 'Internal server error'}), 500
        return error, 500


__all__ = ['create_app']
