"""Offline GitHub PR review — Flask app factory.

Reuses the `gh` CLI you're already logged into. No token handling, no DB.
Reviews are saved as JSON in ./reviews/ so you can review offline and publish later.
"""
import os

from flask import Flask

from . import render, routes, storage

_BASE = os.path.dirname(os.path.dirname(__file__))


def create_app():
    app = Flask(__name__,
                template_folder=os.path.join(_BASE, "templates"),
                static_folder=os.path.join(_BASE, "static"))
    storage.REVIEWS.mkdir(exist_ok=True)
    app.jinja_env.filters["md"] = render.render_md
    app.jinja_env.filters["texton"] = render.text_on
    app.register_blueprint(routes.bp)
    return app
