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
