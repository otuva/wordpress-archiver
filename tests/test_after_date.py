"""--after-date param mapping: posts/pages filter by modified_after (catches
edits to old items; a new item's modified date equals its publish date), while
comments keep the plain `after` written-date filter — WordPress core stores no
comment modification/approval timestamp, so nothing better exists."""

from wordpress_archiver.api import WordPressAPI


def _capture_params(api):
    captured = {}

    def fake_make_request(method, endpoint, params=None):
        captured['endpoint'] = endpoint
        captured['params'] = dict(params or {})
        raise RuntimeError("stop after capture")

    api._make_request = fake_make_request
    return captured


def _api():
    return WordPressAPI("https://example.com")


def test_get_posts_maps_after_to_modified_after():
    api = _api()
    captured = _capture_params(api)
    try:
        api.get_posts(after="2026-08-25T00:00:00")
    except RuntimeError:
        pass
    assert captured['params'].get('modified_after') == "2026-08-25T00:00:00"
    assert 'after' not in captured['params']


def test_get_pages_maps_after_to_modified_after():
    api = _api()
    captured = _capture_params(api)
    try:
        api.get_pages(after="2026-08-25T00:00:00")
    except RuntimeError:
        pass
    assert captured['params'].get('modified_after') == "2026-08-25T00:00:00"
    assert 'after' not in captured['params']


def test_get_comments_keeps_plain_after():
    api = _api()
    captured = _capture_params(api)
    try:
        api.get_comments(after="2026-08-25T00:00:00")
    except RuntimeError:
        pass
    assert captured['params'].get('after') == "2026-08-25T00:00:00"
    assert 'modified_after' not in captured['params']


def test_no_date_filter_sends_neither():
    api = _api()
    captured = _capture_params(api)
    try:
        api.get_posts()
    except RuntimeError:
        pass
    assert 'after' not in captured['params']
    assert 'modified_after' not in captured['params']


def test_get_posts_published_date_field_sends_plain_after():
    api = _api()
    captured = _capture_params(api)
    try:
        api.get_posts(after="2026-08-25T00:00:00", date_field='published')
    except RuntimeError:
        pass
    assert captured['params'].get('after') == "2026-08-25T00:00:00"
    assert 'modified_after' not in captured['params']


def test_incremental_posts_walk_runs_modified_then_published_pass(archiver):
    """A scheduled post auto-published by wp-cron keeps its pre-cutoff
    post_modified, so only the publish-date pass sees it — the incremental
    walk must run both passes and not double-archive first-pass items."""
    from datetime import datetime
    from conftest import make_post

    class _DualPassStub:
        def __init__(self):
            self.date_fields = []

        def get_posts(self, page=1, per_page=10, after=None, date_field='modified'):
            if page == 1:
                self.date_fields.append(date_field)
            data = {
                # edited since cutoff → modified pass
                'modified': [make_post(1)],
                # scheduled post (stale post_modified) + the same post 1 again
                'published': [make_post(1), make_post(2)],
            }[date_field]

            class R:
                pass
            r = R()
            r.data = data if page == 1 else []
            r.total_count = len(r.data)
            r.total_pages_count = 1
            return r

    stub = _DualPassStub()
    stats = archiver.archive_content(stub, "posts",
                                     after_date=datetime(2026, 8, 25))

    assert stub.date_fields == ['modified', 'published']
    # Post 1 archived once (skipped in pass 2), post 2 caught by pass 2.
    import sqlite3
    conn = sqlite3.connect(archiver.db.db_path)
    counts = dict(conn.execute(
        "SELECT wp_id, COUNT(*) FROM posts GROUP BY wp_id").fetchall())
    conn.close()
    assert counts == {1: 1, 2: 1}
    assert stats["processed"] == 2
