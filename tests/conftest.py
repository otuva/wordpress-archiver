"""
Shared fixtures/helpers for the wordpress-archiver test suite.

Everything here builds tiny, realistic WordPress REST API item dicts and
tmp-path-backed databases so tests run fully offline and deterministically.
"""

import sqlite3
from pathlib import Path

import pytest

from wordpress_archiver.database import DatabaseManager
from wordpress_archiver.archiver import WordPressArchiver


@pytest.fixture
def db_path(tmp_path) -> str:
    """Path to a not-yet-created SQLite db file inside a tmp dir."""
    return str(tmp_path / "archive.db")


@pytest.fixture
def db(db_path) -> DatabaseManager:
    """A DatabaseManager whose constructor creates/migrates the schema."""
    return DatabaseManager(db_path)


@pytest.fixture
def archiver(db_path) -> WordPressArchiver:
    """A WordPressArchiver backed by the same tmp db (no network/API needed)."""
    return WordPressArchiver(db_path)


def raw_connect(db_path: str) -> sqlite3.Connection:
    """A plain sqlite3 connection for asserting against the tmp db directly,
    independent of anything DatabaseManager's own getters report."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def make_post(wp_id: int, title: str = "Hello World",
              content: str = "<p>Hello world.</p>",
              excerpt: str = "Hello world.",
              status: str = "publish",
              author: int = 1,
              date: str = "2024-01-01T00:00:00",
              modified: str = "2024-01-01T00:00:00",
              categories=None, tags=None, **extra) -> dict:
    """A minimal but realistic /wp/v2/posts item, as ContentProcessor.
    extract_content_data expects it (title/content/excerpt as {'rendered': ...},
    plus the flat fields it reads directly)."""
    item = {
        "id": wp_id,
        "title": {"rendered": title},
        "content": {"rendered": content},
        "excerpt": {"rendered": excerpt},
        "status": status,
        "author": author,
        "date": date,
        "modified": modified,
        "categories": list(categories) if categories is not None else [],
        "tags": list(tags) if tags is not None else [],
        "link": f"https://example.com/?p={wp_id}",
        "slug": f"post-{wp_id}",
        "type": "post",
    }
    item.update(extra)
    return item
