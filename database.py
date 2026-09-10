"""Compatibility shim.

The data layer moved to ``app/repositories/`` and is split by domain there.
This re-export keeps ``from database import DatabaseManager`` working for the
standalone scripts in ``migrations/`` and ``scripts/``.
"""

from app.repositories import DatabaseManager

__all__ = ['DatabaseManager']
