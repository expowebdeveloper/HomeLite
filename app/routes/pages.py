"""Server-rendered pages."""

from flask import Blueprint
from flask import render_template
from flask_login import login_required

bp = Blueprint('pages', __name__)



@bp.route('/')
@login_required
def index():
    return render_template('pages/index.html')

@bp.route('/reports')
@login_required
def reports():
    """Property status / market movement report page (spec section 6)."""
    return render_template('pages/reports.html')


@bp.route('/scraper-logs')
@login_required
def scraper_logs():
    """Live scraper activity + log console."""
    return render_template('pages/scraper_logs.html')
