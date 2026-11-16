"""Interface web do MiniFS (servidor Flask + front-end estático)."""

from .app import create_app

__all__ = ["create_app"]
