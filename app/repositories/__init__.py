"""Data access layer.

The original ``database.DatabaseManager`` was a single 2,800 line class covering
six unrelated domains. It is now split into one mixin per domain and recomposed
here, so every existing ``db_manager.<method>()`` call site keeps working
unchanged while each domain lives in its own file.
"""

from app.repositories.base import BaseRepository
from app.repositories.documents import DocumentsMixin
from app.repositories.market_intelligence import MarketIntelligenceMixin
from app.repositories.properties import PropertiesMixin
from app.repositories.scrapers import ScrapersMixin
from app.repositories.sessions import SessionsMixin
from app.repositories.tags import TagsMixin
from app.repositories.users import UsersMixin


class DatabaseManager(
    UsersMixin,
    SessionsMixin,
    PropertiesMixin,
    TagsMixin,
    ScrapersMixin,
    DocumentsMixin,
    MarketIntelligenceMixin,
    BaseRepository,
):
    """Single entry point to the database, assembled from the domain mixins."""


__all__ = ['DatabaseManager']
