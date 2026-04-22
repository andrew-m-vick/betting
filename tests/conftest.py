"""Pytest fixtures.

Tests run against SQLite in-memory unless TEST_DATABASE_URL points at
a real Postgres. In-memory is fast and isolates CI from Neon quota.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("FLASK_ENV", "testing")
os.environ.setdefault("TEST_DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ODDS_API_KEY", "test-key")

from app import create_app  # noqa: E402
from app.extensions import db as _db  # noqa: E402
from config import TestingConfig  # noqa: E402


@pytest.fixture(scope="session")
def _app_singleton():
    """Build the Flask app once and create the schema in a scratch context."""
    app = create_app(TestingConfig)
    with app.app_context():
        _db.create_all()
    return app


@pytest.fixture
def app(_app_singleton):
    """Per-test app context so Flask-Login's `g._login_user` cache and
    SQLAlchemy's identity map don't leak across tests."""
    with _app_singleton.app_context():
        yield _app_singleton
        # Clean tables + close scoped session so the next test starts clean.
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        _db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """Alias for the SQLAlchemy instance inside the per-test app context."""
    return _db
