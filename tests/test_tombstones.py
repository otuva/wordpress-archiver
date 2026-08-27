"""
Tests for the tombstones spec (feat/tombstones branch):

A. All six typed tables (posts, comments, pages, users, categories, tags)
   gain nullable ``last_seen_at`` and ``gone_since`` columns -- on fresh DBs
   and via additive migration on legacy DBs.

B. DatabaseManager gains three methods:
   - ``touch_last_seen(content_type, wp_ids)`` sets last_seen_at=now,
     gone_since=NULL on each id's LATEST version row (works with thousands
     of ids).
   - ``mark_gone(content_type, wp_ids)`` sets gone_since=now ONLY where
     gone_since IS NULL -- the first-disappearance timestamp is preserved on
     repeat calls.
   - ``all_wp_ids(content_type)`` returns the distinct wp_id set.

C. ``WordPressArchiver.archive_content``:
   - stats gains ``gone=0``.
   - every successfully processed item's wp_id is touched (last_seen_at set,
     gone_since cleared) after the walk.
   - on a FULL clean walk only (no limit, no after_date, incomplete==0,
     errors==0): wp_ids present in the DB but absent from the walk get
     mark_gone, and stats["gone"] counts them.
   - a run with limit / after_date / any error must NOT mark anything gone.
   - tombstoning never touches any column besides the two new ones.

Stub WordPressAPI-alikes (only get_posts, the method archiver.py actually
calls for a 'posts' walk) stand in for the network -- no HTTP, no sleeps,
mirroring tests/test_reliability.py's stub-api pattern.
"""

from wordpress_archiver.archiver import _new_stats

from conftest import make_post, raw_connect
from wordpress_archiver.api import WordPressAPIError, WordPressResponse


TYPED_TABLES = ("posts", "comments", "pages", "users", "categories", "tags")


# =============================================================================
# Stubs (same shape as tests/test_reliability.py's _StubPostsAPI)
# =============================================================================

class _StubPostsAPI:
    """Minimal offline stand-in for WordPressAPI, exposing only get_posts.

    ``pages`` is a list of item-lists, one per page. ``raise_on_page`` makes
    get_posts raise a WordPressAPIError when asked for that page number,
    simulating a page-level fetch failure partway through a walk.
    """

    def __init__(self, pages, total_count, total_pages_count, raise_on_page=None):
        self.pages = pages
        self.total_count = total_count
        self.total_pages_count = total_pages_count
        self.raise_on_page = raise_on_page

    def get_posts(self, page: int = 1, per_page: int = 100, after=None) -> WordPressResponse:
        if self.raise_on_page is not None and page == self.raise_on_page:
            raise WordPressAPIError(f"simulated failure fetching page {page}")
        idx = page - 1
        data = self.pages[idx] if idx < len(self.pages) else []
        return WordPressResponse(
            data=data, total_count=self.total_count,
            total_pages_count=self.total_pages_count)


def _malformed_post(wp_id: int) -> dict:
    """An item shaped so ContentProcessor.extract_content_data('posts', ...)
    reliably raises: 'title' is a bare string where extract_content_data does
    wp_item.get('title', {}).get('rendered', '') -- a str has no .get, so
    this raises AttributeError before any DB write happens."""
    return {
        "id": wp_id,
        "title": "not a dict",
        "content": {"rendered": "x"},
        "excerpt": {"rendered": "x"},
        "status": "publish",
        "author": 1,
        "date": "2024-01-01T00:00:00",
        "modified": "2024-01-01T00:00:00",
        "categories": [],
        "tags": [],
        "link": f"https://example.com/?p={wp_id}",
        "slug": f"post-{wp_id}",
        "type": "post",
    }


def _latest_rows(db_path, table="posts"):
    """{wp_id: row-dict} for the latest version of every wp_id in ``table``."""
    conn = raw_connect(str(db_path))
    rows = {
        row["wp_id"]: dict(row)
        for row in conn.execute(
            f"SELECT * FROM {table} WHERE (wp_id, version) IN "
            f"(SELECT wp_id, MAX(version) FROM {table} GROUP BY wp_id)")
    }
    conn.close()
    return rows


def _gone_count(db_path, table="posts"):
    conn = raw_connect(str(db_path))
    count = conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE gone_since IS NOT NULL").fetchone()[0]
    conn.close()
    return count


# =============================================================================
# 1. Fresh DB schema
# =============================================================================

def test_fresh_db_has_tombstone_columns_on_all_typed_tables(db, db_path):
    conn = raw_connect(db_path)
    for table in TYPED_TABLES:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert "last_seen_at" in cols, f"{table} missing last_seen_at"
        assert "gone_since" in cols, f"{table} missing gone_since"
    conn.close()


# =============================================================================
# 2. touch_last_seen: sets last_seen_at, clears gone_since, latest-version-only
# =============================================================================

def test_touch_last_seen_sets_and_clears_and_only_touches_latest_version(archiver):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>V1</p>"), stats)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>V2</p>"), stats)

    db_path = str(archiver.db.db_path)
    conn = raw_connect(db_path)
    conn.execute(
        "UPDATE posts SET gone_since = ? WHERE wp_id = 1 AND version = 2",
        ("2024-06-01T00:00:00",))
    conn.commit()
    conn.close()

    archiver.db.touch_last_seen("posts", [1])

    conn = raw_connect(db_path)
    v1 = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 1 AND version = 1").fetchone())
    v2 = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 1 AND version = 2").fetchone())
    conn.close()

    assert v2["last_seen_at"] is not None
    assert v2["gone_since"] is None
    assert v1["last_seen_at"] is None, "only the latest version row is touched"


# =============================================================================
# 3. mark_gone: stamps latest version, preserves first-disappearance timestamp
# =============================================================================

def test_mark_gone_preserves_original_timestamp_on_repeat_call(archiver):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item("posts", make_post(10), stats)

    db_path = str(archiver.db.db_path)
    conn = raw_connect(db_path)
    conn.execute(
        "UPDATE posts SET gone_since = ? WHERE wp_id = 10 AND version = 1",
        ("2020-01-01T00:00:00",))
    conn.commit()
    conn.close()

    archiver.db.mark_gone("posts", [10])

    conn = raw_connect(db_path)
    row = conn.execute(
        "SELECT gone_since FROM posts WHERE wp_id = 10 AND version = 1").fetchone()
    conn.close()

    assert row["gone_since"] == "2020-01-01T00:00:00", \
        "mark_gone must not overwrite an already-set gone_since"


# =============================================================================
# 4. gone -> reappear -> touch clears gone_since
# =============================================================================

def test_reappearance_after_mark_gone_clears_gone_since(archiver):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item("posts", make_post(11), stats)

    archiver.db.mark_gone("posts", [11])
    row = _latest_rows(archiver.db.db_path)[11]
    assert row["gone_since"] is not None

    archiver.db.touch_last_seen("posts", [11])
    row = _latest_rows(archiver.db.db_path)[11]
    assert row["gone_since"] is None
    assert row["last_seen_at"] is not None


# =============================================================================
# 5. all_wp_ids: distinct across versions
# =============================================================================

def test_all_wp_ids_returns_distinct_ids_across_versions(archiver):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>V1</p>"), stats)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>V2</p>"), stats)
    archiver._process_content_item("posts", make_post(2), stats)

    assert set(archiver.db.all_wp_ids("posts")) == {1, 2}


# =============================================================================
# 6. archive_content: full clean walk marks missing items gone
# =============================================================================

def test_full_clean_walk_marks_missing_items_gone(archiver):
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    walk_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2)]],
        total_count=2, total_pages_count=1)
    stats = archiver.archive_content(walk_stub, "posts")

    rows = _latest_rows(archiver.db.db_path)
    assert rows[1]["last_seen_at"] is not None
    assert rows[1]["gone_since"] is None
    assert rows[2]["last_seen_at"] is not None
    assert rows[2]["gone_since"] is None
    assert rows[3]["gone_since"] is not None

    assert stats["gone"] == 1


def test_undercounting_walk_does_not_mark_gone(archiver):
    """A walk that returns fewer items than its own X-WP-Total (missing > 0)
    is not trustworthy evidence of deletion — the API itself says items exist
    that the walk didn't deliver, so nothing may be tombstoned."""
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    # API claims 5 items but delivers only 2: posts 1-2 seen, 3 unseen —
    # but missing=3 must veto the tombstone pass entirely.
    walk_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2)]],
        total_count=5, total_pages_count=1)
    stats = archiver.archive_content(walk_stub, "posts")

    assert stats["missing"] == 3
    assert stats["gone"] == 0
    rows = _latest_rows(archiver.db.db_path)
    assert rows[3]["gone_since"] is None


# =============================================================================
# 7. archive_content: limited walk marks nothing gone
# =============================================================================

def test_limited_walk_does_not_mark_gone(archiver):
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    walk_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2)]],
        total_count=3, total_pages_count=1)
    stats = archiver.archive_content(walk_stub, "posts", limit=2)

    assert _gone_count(archiver.db.db_path) == 0
    assert stats.get("gone", 0) == 0


# =============================================================================
# 8. archive_content: incomplete (page-level failure) walk marks nothing gone
# =============================================================================

def test_incomplete_walk_does_not_mark_gone(archiver):
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    walk_stub = _StubPostsAPI(
        pages=[[make_post(1)], []],
        total_count=3, total_pages_count=2, raise_on_page=2)
    stats = archiver.archive_content(walk_stub, "posts")

    assert stats["incomplete"] == 1
    assert _gone_count(archiver.db.db_path) == 0
    assert stats.get("gone", 0) == 0


# =============================================================================
# 9. archive_content: a per-item error marks nothing gone
# =============================================================================

def test_walk_with_item_error_does_not_mark_gone(archiver):
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    walk_stub = _StubPostsAPI(
        pages=[[make_post(1), _malformed_post(99)]],
        total_count=2, total_pages_count=1)
    stats = archiver.archive_content(walk_stub, "posts")

    assert stats["errors"] > 0
    assert _gone_count(archiver.db.db_path) == 0
    assert stats.get("gone", 0) == 0


# =============================================================================
# 10. Tombstoning changes nothing but the two new columns
# =============================================================================

def test_tombstoning_does_not_mutate_other_columns(archiver):
    seed_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2), make_post(3)]],
        total_count=3, total_pages_count=1)
    archiver.archive_content(seed_stub, "posts")

    conn = raw_connect(str(archiver.db.db_path))
    before = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 3 AND version = 1").fetchone())
    conn.close()
    assert before["gone_since"] is None

    walk_stub = _StubPostsAPI(
        pages=[[make_post(1), make_post(2)]],
        total_count=2, total_pages_count=1)
    archiver.archive_content(walk_stub, "posts")

    conn = raw_connect(str(archiver.db.db_path))
    after = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 3 AND version = 1").fetchone())
    conn.close()

    assert after["gone_since"] is not None

    for col in before:
        if col in ("last_seen_at", "gone_since"):
            continue
        assert after[col] == before[col], f"column {col!r} changed by tombstoning"


# =============================================================================
# 11. Chunking sanity: touch_last_seen with thousands of ids
# =============================================================================

def test_touch_last_seen_chunking_sanity_with_1200_ids(db, db_path):
    wp_ids = list(range(1, 1201))

    conn = raw_connect(db_path)
    conn.executemany(
        "INSERT INTO posts (wp_id, version, content_hash) VALUES (?, 1, ?)",
        [(wp_id, f"hash{wp_id}") for wp_id in wp_ids])
    conn.commit()
    conn.close()

    db.touch_last_seen("posts", wp_ids)

    conn = raw_connect(db_path)
    touched = conn.execute(
        "SELECT COUNT(*) FROM posts WHERE last_seen_at IS NOT NULL").fetchone()[0]
    conn.close()

    assert touched == 1200
