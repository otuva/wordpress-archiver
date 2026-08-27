"""
Tests for the raw_json_history table and DatabaseManager.update_latest_raw_json /
get_raw_json_history, per the raw-json-history spec:

- raw_json_history(id, content_type, wp_id, version, raw_json NOT NULL,
  replaced_at) is created automatically on DatabaseManager init, including
  when opening a pre-existing db file from an older schema.
- update_latest_raw_json(content_type, wp_id, raw_json, categories=None,
  tags=None) targets only the MAX(version) row, is a lossless no-op when the
  stored raw_json is identical, skips writing history when the stored
  raw_json is NULL (nothing to preserve), otherwise appends the superseded
  raw_json to history before overwriting, and (for posts) syncs
  post_categories/post_tags for the latest version regardless of whether
  raw_json itself changed.
- get_raw_json_history returns rows newest-first.

These exercise DatabaseManager directly, with no archiver/API involved.
"""

import sqlite3

from wordpress_archiver.database import DatabaseManager
from wordpress_archiver.content_processor import ContentProcessor

from conftest import make_post, raw_connect


def _insert_post(db, wp_id, version=1, **kwargs):
    """Insert a post version through the real extractor (so content_hash and
    raw_json are exactly what production code would produce), returning the
    extracted content_data dict."""
    cp = ContentProcessor()
    data = cp.extract_content_data(make_post(wp_id, **kwargs), "posts")
    db.insert_content("posts", data, version=version)
    return data


def test_raw_json_history_table_created_on_fresh_db(db, db_path):
    conn = raw_connect(db_path)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(raw_json_history)")}
    conn.close()
    assert cols == {"id", "content_type", "wp_id", "version", "raw_json", "replaced_at"}


def test_raw_json_history_created_via_migration_on_legacy_db(tmp_path):
    db_path = str(tmp_path / "legacy.db")

    # Simulate a pre-existing archive from before this feature: a posts table
    # (already with a raw_json column, as an earlier migration would have
    # added) but no raw_json_history table at all.
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            wp_id INTEGER,
            title TEXT,
            content TEXT,
            excerpt TEXT,
            author_id INTEGER,
            date_created TEXT,
            date_modified TEXT,
            status TEXT,
            content_hash TEXT,
            raw_json TEXT,
            version INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(wp_id, version)
        )
    """)
    conn.execute(
        "INSERT INTO posts (wp_id, title, content, excerpt, author_id, "
        "date_created, date_modified, status, content_hash, raw_json, version) "
        "VALUES (1, 'Legacy Title', 'Legacy content', 'Legacy excerpt', 1, "
        "'2024-01-01', '2024-01-01', 'publish', 'legacyhash', 'legacyraw', 1)"
    )
    conn.commit()
    conn.close()

    # Opening this pre-existing file must add raw_json_history without
    # touching (let alone dropping) the existing data.
    DatabaseManager(db_path)

    conn = raw_connect(db_path)
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "raw_json_history" in tables

    row = conn.execute(
        "SELECT title, raw_json FROM posts WHERE wp_id = 1").fetchone()
    conn.close()
    assert row["title"] == "Legacy Title"
    assert row["raw_json"] == "legacyraw"


def test_update_latest_raw_json_missing_wp_id_returns_false(db, db_path):
    result = db.update_latest_raw_json("posts", 999, '{"a": 1}')
    assert result is False

    conn = raw_connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM raw_json_history").fetchone()[0]
    conn.close()
    assert count == 0


def test_update_latest_raw_json_identical_is_noop(db, db_path):
    data = _insert_post(db, 1)

    result = db.update_latest_raw_json("posts", 1, data["raw_json"])
    assert result is False

    conn = raw_connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM raw_json_history").fetchone()[0]
    stored = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1").fetchone()[0]
    conn.close()
    assert count == 0
    assert stored == data["raw_json"]


def test_update_latest_raw_json_null_stored_writes_no_history(db, db_path):
    _insert_post(db, 1)

    conn = raw_connect(db_path)
    conn.execute("UPDATE posts SET raw_json = NULL WHERE wp_id = 1")
    conn.commit()
    conn.close()

    result = db.update_latest_raw_json("posts", 1, '{"new": true}')
    assert result is True

    conn = raw_connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM raw_json_history").fetchone()[0]
    stored = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1").fetchone()[0]
    conn.close()
    assert count == 0, "no prior raw_json to preserve, so no history row"
    assert stored == '{"new": true}'


def test_update_latest_raw_json_differing_appends_history(db, db_path):
    data = _insert_post(db, 1)
    old_raw_json = data["raw_json"]
    new_raw_json = '{"different": true}'

    result = db.update_latest_raw_json("posts", 1, new_raw_json)
    assert result is True

    conn = raw_connect(db_path)
    hist = conn.execute(
        "SELECT content_type, wp_id, version, raw_json FROM raw_json_history"
    ).fetchall()
    stored = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1").fetchone()[0]
    conn.close()

    assert len(hist) == 1
    assert hist[0]["content_type"] == "posts"
    assert hist[0]["wp_id"] == 1
    assert hist[0]["version"] == 1
    assert hist[0]["raw_json"] == old_raw_json
    assert stored == new_raw_json


def test_update_latest_raw_json_targets_latest_version_only(db, db_path):
    data_v1 = _insert_post(db, 1, version=1, content="<p>one</p>")
    data_v2 = _insert_post(db, 1, version=2, content="<p>two</p>")

    result = db.update_latest_raw_json("posts", 1, '{"z": true}')
    assert result is True

    conn = raw_connect(db_path)
    raw_v1 = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    raw_v2 = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 2").fetchone()[0]
    hist = conn.execute(
        "SELECT version, raw_json FROM raw_json_history").fetchall()
    conn.close()

    assert raw_v1 == data_v1["raw_json"], "v1 (not the latest) must be untouched"
    assert raw_v2 == '{"z": true}'
    assert len(hist) == 1
    assert hist[0]["version"] == 2
    assert hist[0]["raw_json"] == data_v2["raw_json"]


def test_update_latest_raw_json_syncs_post_categories_and_tags(db, db_path):
    data = _insert_post(db, 1, categories=[10, 20], tags=[30])

    conn = raw_connect(db_path)
    cats = {r[0] for r in conn.execute(
        "SELECT category_wp_id FROM post_categories WHERE post_wp_id = 1 AND version = 1")}
    conn.close()
    assert cats == {10, 20}

    # raw_json passed back identical -> no history/replace, but membership
    # sync still happens because it's driven by categories=/tags=, not by
    # whether raw_json changed.
    result = db.update_latest_raw_json(
        "posts", 1, data["raw_json"], categories=[10, 99], tags=[30])
    assert result is False

    conn = raw_connect(db_path)
    cats = {r[0] for r in conn.execute(
        "SELECT category_wp_id FROM post_categories WHERE post_wp_id = 1 AND version = 1")}
    tags = {r[0] for r in conn.execute(
        "SELECT tag_wp_id FROM post_tags WHERE post_wp_id = 1 AND version = 1")}
    row_id_before = conn.execute(
        "SELECT id FROM post_categories "
        "WHERE post_wp_id = 1 AND version = 1 AND category_wp_id = 10"
    ).fetchone()[0]
    conn.close()
    assert cats == {10, 99}
    assert tags == {30}

    # Same membership passed again -> delete+reinsert must NOT fire, so the
    # surviving row's id stays exactly the same.
    db.update_latest_raw_json(
        "posts", 1, data["raw_json"], categories=[10, 99], tags=[30])

    conn = raw_connect(db_path)
    row_id_after = conn.execute(
        "SELECT id FROM post_categories "
        "WHERE post_wp_id = 1 AND version = 1 AND category_wp_id = 10"
    ).fetchone()[0]
    conn.close()
    assert row_id_after == row_id_before


def test_get_raw_json_history_newest_first(db):
    data = _insert_post(db, 1)
    original_raw_json = data["raw_json"]

    db.update_latest_raw_json("posts", 1, '{"v": 2}')
    db.update_latest_raw_json("posts", 1, '{"v": 3}')

    hist = db.get_raw_json_history("posts", 1)
    assert len(hist) == 2
    # Newest-first: the value displaced most recently ('{"v": 2}', pushed out
    # by the second call) comes before the original raw_json.
    assert hist[0]["raw_json"] == '{"v": 2}'
    assert hist[1]["raw_json"] == original_raw_json
