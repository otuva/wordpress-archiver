"""
Tests for the media-metadata spec:

- media table gains nullable `etag` and `last_modified` columns (present on a
  fresh DB; added by additive migration when opening a legacy DB whose media
  table lacks them). DatabaseManager.insert_media(..., etag=None,
  last_modified=None) stores them.
- WordPressArchiver._scan_media_endpoint(api, site_url, limit=None, stats=None)
  now, in addition to returning the set of archivable URLs, stores each
  /wp/v2/media attachment's full JSON into the versioned api_objects table
  under route '/wp/v2/media', using the same dedup as the generic endpoint
  walker (via the shared _store_api_object helper): first sight -> version 1
  (stats['meta_new'] += 1 when stats is given and the key is present); JSON
  changed -> version+1 (stats['meta_updated']); unchanged -> no new row
  (stats['meta_unchanged'] when present).
- _store_api_object(route, item, index=None) implements that dedup and returns
  'new'/'updated'/'skipped'; counting is the caller's job. `index` is an
  optional prefetched {wp_id: (version, content_hash)} map (see
  get_api_object_hash_index) that replaces the per-item DB read.
- api.download_binary returns a 5-tuple: (content, content_type, http_status,
  etag, last_modified).

Uses WordPressArchiver/DatabaseManager directly against tmp sqlite dbs -- no
network required (a stub stands in for WordPressAPI.get_media, and
download_binary's HTTP call is monkeypatched).
"""

import sqlite3

import pytest

from wordpress_archiver.database import DatabaseManager
from wordpress_archiver.api import WordPressAPI, WordPressResponse

from conftest import raw_connect


# =============================================================================
# Helpers
# =============================================================================

# The pre-migration media schema (MEDIA_TABLE_SCHEMA in database.py, minus
# the two new columns), hand-copied here so the migration test is independent
# of whatever the current in-repo schema looks like.
LEGACY_MEDIA_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS media (
        id INTEGER PRIMARY KEY,
        url_hash TEXT NOT NULL UNIQUE,
        url TEXT NOT NULL,
        content BLOB,
        content_hash TEXT,
        mime_type TEXT DEFAULT 'application/octet-stream',
        byte_size INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ok',
        http_status INTEGER,
        fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
'''


def make_media_item(wp_id: int, filename: str = "photo.jpg",
                     alt_text: str = "A photo",
                     domain: str = "https://example.com") -> dict:
    """A minimal but realistic /wp/v2/media attachment item, as returned by
    WordPress's REST API."""
    base = f"{domain}/wp-content/uploads/2024/01"
    name, ext = filename.rsplit(".", 1)
    return {
        "id": wp_id,
        "date": "2024-01-01T00:00:00",
        "slug": f"{name}-{wp_id}",
        "type": "attachment",
        "link": f"{domain}/?attachment_id={wp_id}",
        "title": {"rendered": filename},
        "author": 1,
        "caption": {"rendered": f"Caption for {filename}"},
        "alt_text": alt_text,
        "media_type": "image",
        "mime_type": "image/jpeg",
        "source_url": f"{base}/{filename}",
        "media_details": {
            "width": 1024,
            "height": 768,
            "sizes": {
                "thumbnail": {
                    "source_url": f"{base}/{name}-150x150.{ext}",
                    "width": 150,
                    "height": 150,
                },
            },
        },
    }


class _StubMediaAPI:
    """Minimal offline stand-in for WordPressAPI.get_media."""

    def __init__(self, items):
        self.items = items

    def get_media(self, page: int = 1, per_page: int = 100) -> WordPressResponse:
        if page > 1:
            return WordPressResponse(data=[], total_count=0, total_pages_count=1)
        return WordPressResponse(
            data=self.items, total_count=len(self.items), total_pages_count=1)


def _api_object_rows(db_path, endpoint="/wp/v2/media"):
    conn = raw_connect(db_path)
    rows = conn.execute(
        "SELECT wp_id, version, raw_json FROM api_objects WHERE endpoint = ? "
        "ORDER BY wp_id ASC, version ASC", (endpoint,)).fetchall()
    conn.close()
    return rows


# =============================================================================
# A/C. media table schema + migration
# =============================================================================

def test_fresh_db_media_table_has_etag_and_last_modified_columns(db, db_path):
    conn = raw_connect(db_path)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(media)")}
    conn.close()
    assert "etag" in cols
    assert "last_modified" in cols


def test_legacy_db_media_migration_adds_columns_and_keeps_existing_row(tmp_path):
    legacy_db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(legacy_db_path))
    conn.execute(LEGACY_MEDIA_TABLE_SCHEMA)
    conn.execute(
        "INSERT INTO media (url_hash, url, content, content_hash, mime_type, "
        "byte_size, status, http_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("legacyhash", "https://example.com/old.jpg", b"legacy-bytes",
         "legacychash", "image/jpeg", 12, "ok", 200),
    )
    conn.commit()
    conn.close()

    # Opening via DatabaseManager must additively migrate the existing table.
    DatabaseManager(str(legacy_db_path))

    conn = raw_connect(str(legacy_db_path))
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(media)")}
    row = conn.execute(
        "SELECT * FROM media WHERE url_hash = 'legacyhash'").fetchone()
    conn.close()

    assert "etag" in cols
    assert "last_modified" in cols
    assert row is not None
    # Pre-existing row is untouched apart from the new (NULL) columns.
    assert row["url"] == "https://example.com/old.jpg"
    assert row["content"] == b"legacy-bytes"
    assert row["content_hash"] == "legacychash"
    assert row["mime_type"] == "image/jpeg"
    assert row["byte_size"] == 12
    assert row["status"] == "ok"
    assert row["http_status"] == 200
    assert row["etag"] is None
    assert row["last_modified"] is None


# =============================================================================
# C. DatabaseManager.insert_media(..., etag=..., last_modified=...)
# =============================================================================

def test_insert_media_stores_etag_and_last_modified(db, db_path):
    db.insert_media(
        "h1", "https://example.com/a.jpg", b"data", "ch1", "image/jpeg",
        "ok", 200, etag='"abc123"',
        last_modified="Wed, 21 Oct 2015 07:28:00 GMT")

    conn = raw_connect(db_path)
    row = conn.execute(
        "SELECT etag, last_modified FROM media WHERE url_hash = 'h1'").fetchone()
    conn.close()

    assert row["etag"] == '"abc123"'
    assert row["last_modified"] == "Wed, 21 Oct 2015 07:28:00 GMT"


def test_insert_media_omitted_etag_and_last_modified_are_null(db, db_path):
    db.insert_media(
        "h2", "https://example.com/b.jpg", b"data", "ch2", "image/jpeg",
        "ok", 200)

    conn = raw_connect(db_path)
    row = conn.execute(
        "SELECT etag, last_modified FROM media WHERE url_hash = 'h2'").fetchone()
    conn.close()

    assert row["etag"] is None
    assert row["last_modified"] is None


# =============================================================================
# A/B. _scan_media_endpoint stores attachment JSON into api_objects
# =============================================================================

def test_scan_media_endpoint_stores_attachment_json(archiver, db_path):
    item1 = make_media_item(501, filename="photo.jpg", alt_text="First photo")
    item2 = make_media_item(502, filename="banner.png", alt_text="Second photo")
    stub = _StubMediaAPI([item1, item2])
    stats = dict(meta_new=0, meta_updated=0)

    urls = archiver._scan_media_endpoint(stub, "https://example.com", stats=stats)

    assert item1["source_url"] in urls
    assert item1["media_details"]["sizes"]["thumbnail"]["source_url"] in urls
    assert item2["source_url"] in urls
    assert item2["media_details"]["sizes"]["thumbnail"]["source_url"] in urls

    rows = _api_object_rows(db_path)
    assert len(rows) == 2
    assert {r["wp_id"] for r in rows} == {501, 502}
    assert all(r["version"] == 1 for r in rows)

    assert stats["meta_new"] == 2
    assert stats["meta_updated"] == 0


def test_scan_media_endpoint_rescan_identical_items_is_a_noop(archiver, db_path):
    item1 = make_media_item(501, filename="photo.jpg", alt_text="First photo")
    item2 = make_media_item(502, filename="banner.png", alt_text="Second photo")
    archiver._scan_media_endpoint(
        _StubMediaAPI([item1, item2]), "https://example.com",
        stats=dict(meta_new=0, meta_updated=0))

    stats2 = dict(meta_new=0, meta_updated=0)
    archiver._scan_media_endpoint(
        _StubMediaAPI([item1, item2]), "https://example.com", stats=stats2)

    rows = _api_object_rows(db_path)
    assert len(rows) == 2
    assert all(r["version"] == 1 for r in rows)
    assert stats2["meta_new"] == 0
    assert stats2["meta_updated"] == 0


def test_scan_media_endpoint_rescan_changed_item_bumps_version(archiver, db_path):
    item1 = make_media_item(501, filename="photo.jpg", alt_text="First photo")
    item2 = make_media_item(502, filename="banner.png", alt_text="Second photo")
    archiver._scan_media_endpoint(
        _StubMediaAPI([item1, item2]), "https://example.com",
        stats=dict(meta_new=0, meta_updated=0))

    item1_changed = make_media_item(501, filename="photo.jpg",
                                     alt_text="Updated alt text")
    stats2 = dict(meta_new=0, meta_updated=0)
    archiver._scan_media_endpoint(
        _StubMediaAPI([item1_changed, item2]), "https://example.com",
        stats=stats2)

    assert stats2["meta_new"] == 0
    assert stats2["meta_updated"] == 1

    rows = _api_object_rows(db_path)
    versions_501 = sorted(r["version"] for r in rows if r["wp_id"] == 501)
    versions_502 = sorted(r["version"] for r in rows if r["wp_id"] == 502)
    assert versions_501 == [1, 2]
    assert versions_502 == [1]

    latest_501_raw = [r["raw_json"] for r in rows
                      if r["wp_id"] == 501 and r["version"] == 2][0]
    assert "Updated alt text" in latest_501_raw


# =============================================================================
# A. _store_api_object dedup helper
# =============================================================================

def test_store_api_object_new_skipped_updated(archiver):
    item = make_media_item(900, filename="doc.jpg", alt_text="Original")

    assert archiver._store_api_object("/wp/v2/media", item) == "new"
    assert archiver._store_api_object("/wp/v2/media", item) == "skipped"

    changed = make_media_item(900, filename="doc.jpg", alt_text="Different")
    assert archiver._store_api_object("/wp/v2/media", changed) == "updated"


def test_store_api_object_prefetched_index_stays_current(archiver):
    # With a prefetched hash index the helper must dedup against (and keep
    # updating) the index instead of hitting the DB per item.
    item = make_media_item(901, filename="doc2.jpg", alt_text="Original")
    index = archiver.db.get_api_object_hash_index("/wp/v2/media")
    assert index == {}

    assert archiver._store_api_object("/wp/v2/media", item, index=index) == "new"
    assert 901 in index and index[901][0] == 1
    assert archiver._store_api_object("/wp/v2/media", item, index=index) == "skipped"

    changed = make_media_item(901, filename="doc2.jpg", alt_text="Different")
    assert archiver._store_api_object("/wp/v2/media", changed, index=index) == "updated"
    assert index[901][0] == 2

    # A freshly prefetched index reflects what actually landed in the DB.
    assert archiver.db.get_api_object_hash_index("/wp/v2/media")[901] == index[901]


# =============================================================================
# D. api.download_binary returns a 5-tuple including etag/last_modified
# =============================================================================

class _FakeStreamResponse:
    """Minimal stand-in for a requests.Response used as a context manager,
    matching exactly what WordPressAPI.download_binary calls on it."""

    def __init__(self, status_code=200, headers=None, chunks=(b"binary-bytes",)):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = list(chunks)

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        yield from self._chunks

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_download_binary_returns_5_tuple_with_etag_and_last_modified(monkeypatch):
    api = WordPressAPI("https://example.com")
    fake_response = _FakeStreamResponse(
        status_code=200,
        headers={
            "Content-Type": "image/jpeg",
            "ETag": '"abc123"',
            "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT",
        },
        chunks=(b"binary-bytes",),
    )

    def fake_get(url, timeout=None, stream=None):
        return fake_response

    monkeypatch.setattr(api.session, "get", fake_get)

    result = api.download_binary("https://example.com/wp-content/uploads/a.jpg")

    assert len(result) == 5
    content, content_type, http_status, etag, last_modified = result
    assert content == b"binary-bytes"
    assert content_type == "image/jpeg"
    assert http_status == 200
    assert etag == '"abc123"'
    assert last_modified == "Wed, 21 Oct 2015 07:28:00 GMT"
