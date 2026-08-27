"""
Tests for the reliability spec (fix/reliability branch):

A. database: a new ``archive_failures`` table (content_type, wp_id NULLABLE,
   stage, detail, error, occurred_at) is auto-created on init.
   ``DatabaseManager.insert_failure(content_type, stage, error, wp_id=None,
   detail=None)`` inserts a row; ``get_recent_failures(limit=100)`` returns
   them newest-first.

B. ``WordPressArchiver.archive_content`` stats gain ``missing`` and
   ``incomplete`` counters (both 0 by default):
   - A per-item processing exception persists an archive_failures row with
     stage 'item' (wp_id taken from the raw item) and still lets the rest of
     the page process normally.
   - A page-level fetch exception persists stage 'page', sets
     stats['incomplete'] = 1, and items already pulled from earlier pages
     stay archived.
   - After a full UNBOUNDED walk (no --limit, no --after-date), if the first
     page's X-WP-Total (``response.total_count``) exceeds the number of items
     actually processed, stats['missing'] = expected - processed and a
     stage='completeness' failure row is written. A falsy total_count (0 or
     None) skips the check entirely, and so does a limited/incomplete walk.

C. ``api.WordPressAPI`` sessions have a urllib3 Retry policy mounted on
   'https://' with total==3, 429/503 in status_forcelist, and
   respect_retry_after_header True.

D. (light) main.py's SIGINT handling during 'archive' should save an
   interrupted comprehensive session (content_type contains 'INTERRUPTED')
   and exit 130. Exercising that for real means running archive_command
   end-to-end (effectively a subprocess-level test), so this file only probes
   for an injectable hook and skips with a clear reason if main.py doesn't
   expose one yet.

Stub WordPressAPI-alikes (only the methods archiver.py actually calls) stand
in for the network -- no HTTP, no sleeps; the retry test only inspects the
mounted adapter's configuration, it never triggers an actual retry.
"""

import pytest

from wordpress_archiver.archiver import WordPressArchiver
from wordpress_archiver.api import WordPressAPI, WordPressAPIError, WordPressResponse

from conftest import make_post, raw_connect


# =============================================================================
# Stubs
# =============================================================================

class _StubPostsAPI:
    """Minimal offline stand-in for WordPressAPI, exposing only get_posts.

    ``pages`` is a list of item-lists, one per page (page 1 = pages[0], ...).
    ``total_count``/``total_pages_count`` are reported on every response, the
    way WordPress reports X-WP-Total/X-WP-TotalPages for the whole collection
    on every page. ``raise_on_page`` makes get_posts raise a
    WordPressAPIError when asked for that page number, simulating a
    page-level fetch failure partway through a walk.
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


# =============================================================================
# A. archive_failures table + insert_failure/get_recent_failures
# =============================================================================

def test_fresh_db_has_archive_failures_table(db, db_path):
    conn = raw_connect(db_path)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(archive_failures)")}
    conn.close()
    for expected in ("id", "content_type", "wp_id", "stage", "detail", "error",
                      "occurred_at"):
        assert expected in cols


def test_insert_failure_and_get_recent_failures_round_trip(db):
    db.insert_failure("posts", "item", "boom 1", wp_id=1, detail="first")
    db.insert_failure("posts", "page", "boom 2")  # wp_id/detail omitted -> NULL
    db.insert_failure("media", "completeness", "boom 3", wp_id=None, detail=None)

    rows = db.get_recent_failures()

    assert len(rows) == 3
    # Newest first: insertion order 1, 2, 3 -> ids ascend, so reversed here.
    assert [r["error"] for r in rows] == ["boom 3", "boom 2", "boom 1"]

    by_error = {r["error"]: r for r in rows}
    assert by_error["boom 1"]["content_type"] == "posts"
    assert by_error["boom 1"]["stage"] == "item"
    assert by_error["boom 1"]["wp_id"] == 1
    assert by_error["boom 1"]["detail"] == "first"

    assert by_error["boom 2"]["wp_id"] is None
    assert by_error["boom 2"]["detail"] is None

    assert by_error["boom 3"]["content_type"] == "media"
    assert by_error["boom 3"]["stage"] == "completeness"


def test_get_recent_failures_respects_limit(db):
    for i in range(5):
        db.insert_failure("posts", "item", f"err{i}", wp_id=i)

    rows = db.get_recent_failures(limit=2)

    assert len(rows) == 2
    # Newest first -> the two highest ids / most recent inserts.
    assert [r["error"] for r in rows] == ["err4", "err3"]


# =============================================================================
# B. archive_content: per-item failure persistence
# =============================================================================

def test_per_item_failure_is_persisted_and_good_item_still_archived(archiver):
    good = make_post(1, title="Good post")
    bad = _malformed_post(2)
    stub = _StubPostsAPI(pages=[[good, bad]], total_count=2, total_pages_count=1)

    stats = archiver.archive_content(stub, "posts")

    assert archiver.db.content_exists("posts", 1)
    assert not archiver.db.content_exists("posts", 2)
    assert stats["errors"] == 1

    failures = archiver.db.get_recent_failures()
    item_failures = [f for f in failures if f["stage"] == "item"]
    assert len(item_failures) == 1
    assert item_failures[0]["content_type"] == "posts"
    assert item_failures[0]["wp_id"] == 2

    # total_count(2) == processed(2): nothing missing, no completeness issue.
    assert stats.get("missing", 0) == 0
    assert stats.get("incomplete", 0) == 0


# =============================================================================
# B. archive_content: page-level failure persistence
# =============================================================================

def test_page_level_failure_marks_incomplete_and_keeps_earlier_pages(archiver):
    page1 = [make_post(i) for i in range(1, 101)]
    stub = _StubPostsAPI(pages=[page1], total_count=250, total_pages_count=3,
                         raise_on_page=2)

    stats = archiver.archive_content(stub, "posts")

    assert stats["incomplete"] == 1

    failures = archiver.db.get_recent_failures()
    page_failures = [f for f in failures if f["stage"] == "page"]
    assert len(page_failures) == 1
    assert page_failures[0]["content_type"] == "posts"

    conn = raw_connect(str(archiver.db.db_path))
    count = conn.execute("SELECT COUNT(DISTINCT wp_id) FROM posts").fetchone()[0]
    conn.close()
    assert count == 100, "page-1 items must stay archived despite the page-2 failure"


# =============================================================================
# B. archive_content: completeness check
# =============================================================================

def test_completeness_check_reports_missing_on_unbounded_walk(tmp_path):
    archiver = WordPressArchiver(str(tmp_path / "completeness.db"))
    items = [make_post(1), make_post(2)]
    stub = _StubPostsAPI(pages=[items], total_count=5, total_pages_count=1)

    stats = archiver.archive_content(stub, "posts")

    assert stats["missing"] == 3
    assert stats["incomplete"] == 0

    failures = archiver.db.get_recent_failures()
    completeness_failures = [f for f in failures if f["stage"] == "completeness"]
    assert len(completeness_failures) == 1
    assert completeness_failures[0]["content_type"] == "posts"


def test_completeness_check_skipped_when_limit_given(tmp_path):
    archiver = WordPressArchiver(str(tmp_path / "completeness_limited.db"))
    items = [make_post(1), make_post(2)]
    stub = _StubPostsAPI(pages=[items], total_count=5, total_pages_count=1)

    stats = archiver.archive_content(stub, "posts", limit=2)

    assert stats.get("missing", 0) == 0
    failures = archiver.db.get_recent_failures()
    assert not [f for f in failures if f["stage"] == "completeness"]


@pytest.mark.parametrize("falsy_total", [0, None])
def test_completeness_check_skipped_when_total_count_falsy(tmp_path, falsy_total):
    archiver = WordPressArchiver(str(tmp_path / f"falsy_{falsy_total}.db"))
    items = [make_post(1), make_post(2)]
    stub = _StubPostsAPI(pages=[items], total_count=falsy_total, total_pages_count=1)

    stats = archiver.archive_content(stub, "posts")

    assert stats.get("missing", 0) == 0
    failures = archiver.db.get_recent_failures()
    assert not [f for f in failures if f["stage"] == "completeness"]


# =============================================================================
# C. api.WordPressAPI retry policy
# =============================================================================

def test_retry_policy_mounted_on_https_session():
    # WordPressAPI's constructor (domain, timeout=30, auth=None) does no
    # network I/O -- safe to instantiate directly against a fake domain.
    api = WordPressAPI("https://example.com")

    adapter = api.session.get_adapter("https://x")
    retry = adapter.max_retries

    assert retry.total == 3
    assert 429 in retry.status_forcelist
    assert 503 in retry.status_forcelist
    assert retry.respect_retry_after_header is True

    # The anonymous (off-origin media) session must carry the same policy.
    anon_adapter = api._anon_session.get_adapter("https://x")
    assert anon_adapter.max_retries.total == 3


# =============================================================================
# D. (light) SIGINT handling saves an INTERRUPTED session and exits 130
# =============================================================================

def test_sigint_during_archive_saves_interrupted_session_and_exits_130():
    """Spec D: Ctrl+C during 'archive' should save a comprehensive session
    whose content_type contains 'INTERRUPTED' and exit(130).

    Exercising that for real means running archive_command end-to-end (it
    installs its SIGINT handler, talks to a live-ish API, and calls
    sys.exit) -- effectively a subprocess-level test, out of scope here. This
    only looks for an injectable hook (a factory/closure main.py could expose
    so the handler is unit-testable) and calls it directly if present;
    otherwise it skips with a clear reason rather than asserting against
    main.py's internals by guesswork.
    """
    import wordpress_archiver.main as main_module

    hook = None
    for name in ("build_sigint_handler", "_build_sigint_handler",
                 "make_sigint_handler", "_make_sigint_handler"):
        hook = getattr(main_module, name, None)
        if hook is not None:
            break

    if hook is None:
        pytest.skip(
            "main.py exposes no injectable SIGINT-handler factory yet (spec "
            "D) -- signal_handler is a fixed module-level function with no "
            "way to unit-test the 'save INTERRUPTED session + exit 130' "
            "behavior without actually running archive_command as a "
            "subprocess. Omitted per the spec's 'keep D light' guidance; "
            "revisit once main.py exposes such a hook.")

    calls = {}

    class _SpyArchiver:
        def save_comprehensive_session(self, domain, content_types, all_stats,
                                       interrupted=False):
            calls["domain"] = domain
            calls["content_types"] = content_types
            calls["all_stats"] = all_stats
            calls["interrupted"] = interrupted

    import logging
    # Factory signature: (archiver, domain, all_stats, logger). The handler
    # derives the completed content types from all_stats at fire time.
    handler = hook(_SpyArchiver(), "https://example.com",
                   {"posts": {"processed": 3}}, logging.getLogger("test"))

    with pytest.raises(SystemExit) as exc_info:
        handler(2, None)  # SIGINT, frame (frame unused)

    assert exc_info.value.code == 130
    assert calls.get("interrupted") is True
    assert calls.get("content_types") == ["posts"]
