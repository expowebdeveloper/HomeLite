"""Server-rendered pages."""

from flask import Blueprint, render_template
from flask_login import login_required
from app.services.auth_service import scraper_access_required, report_access_required

bp = Blueprint('pages', __name__)


@bp.route('/')
@login_required
def index():
    return render_template('pages/index.html')


@bp.route('/reports')
@login_required
def reports():
    """Property status / market movement report page (spec section 6). Super Admin only."""
    from flask import redirect, url_for
    from flask_login import current_user
    if getattr(current_user, 'role', '') != 'super_admin':
        return redirect(url_for('pages.index'))
    return render_template('pages/reports.html')


@bp.route('/scraper-logs')
@login_required
@scraper_access_required
def scraper_logs():
    """Live scraper activity + log console."""
    return render_template('pages/scraper_logs.html')
