"""Serve and model dreamcatcher's local web interface."""

from dreamcatcher.web.app import serve_web, serve_web_in_background
from dreamcatcher.web.server import WEB_MAX_PORT

__all__ = ["WEB_MAX_PORT", "serve_web", "serve_web_in_background"]
