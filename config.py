"""Compatibility shim.

Configuration moved to ``app/config.py``. This re-export keeps the standalone
scripts in ``migrations/`` and ``scripts/`` working unchanged.
"""

from app.config import Config, INSECURE_DEFAULTS, warn_on_insecure_defaults

__all__ = ['Config', 'INSECURE_DEFAULTS', 'warn_on_insecure_defaults']
