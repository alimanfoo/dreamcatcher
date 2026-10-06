"""Serve and model dreamcatcher's local web interface."""

from dreamcatcher.web.app import serve_web
from dreamcatcher.web.server import WEB_MAX_PORT

__all__ = ["WEB_MAX_PORT", "serve_web"]
