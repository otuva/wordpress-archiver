"""
Tests for the content-hash-scope spec:

A. ContentProcessor.normalize_content no longer strips ANY content -- it only
   html.unescape()s entities and collapses whitespace runs to a single space
   (plus strip()). So calculate_content_hash now changes when text inside a
   wp-block div, a <script> tag, a style= attribute, or a <time> element
   changes, and stays the same when only whitespace runs or entity
   representation differ.

B. Rehash-in-place: DatabaseManager.update_content_hash(content_type, wp_id,
   version, content_hash) restamps one row's hash in place. In
   WordPressArchiver._process_content_item, when the stored hash differs but
   the hash-source fields (posts: title/content/excerpt/status) are
   byte-identical to the latest stored version, no new version row is
   created -- the stored content_hash is restamped on the latest version,
   metadata refresh (raw_json + junction sync + stats["refreshed"]) still
   happens, and stats["updated"] stays 0.

Uses ContentProcessor directly for (A), and WordPressArchiver._process_content_item
plus DatabaseManager.update_content_hash directly for (B), against a real
tmp-path-backed DatabaseManager -- no network/API required.
"""

from wordpress_archiver.archiver import _new_stats
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


def _corrupt_hash(db_path, wp_id, version=1, stale_hash="stale-hash"):
    """Simulate a hashing-algorithm change: overwrite a stored content_hash
    with a value that won't match anything freshly computed."""
    conn = raw_connect(db_path)
    conn.execute(
        "UPDATE posts SET content_hash = ? WHERE wp_id = ? AND version = ?",
        (stale_hash, wp_id, version))
    conn.commit()
    conn.close()


# =============================================================================
# A. normalize_content / calculate_content_hash no longer strip anything
# =============================================================================

def test_wp_block_div_text_change_changes_hash():
    cp = ContentProcessor()
    content_a = '<div class="wp-block-paragraph">Alpha text.</div>'
    content_b = '<div class="wp-block-paragraph">Beta text.</div>'

    assert "Alpha text." in cp.normalize_content(content_a), \
        "wp-block div content must be preserved, not stripped"
    assert cp.calculate_content_hash(content_a) != cp.calculate_content_hash(content_b)


def test_script_tag_content_change_changes_hash():
    cp = ContentProcessor()
    content_a = '<script>var counter = 1;</script><p>Body</p>'
    content_b = '<script>var counter = 2;</script><p>Body</p>'

    assert "var counter = 1;" in cp.normalize_content(content_a), \
        "script tag content must be preserved, not stripped"
    assert cp.calculate_content_hash(content_a) != cp.calculate_content_hash(content_b)


def test_style_attribute_change_changes_hash():
    cp = ContentProcessor()
    content_a = '<p style="color:red;">Text</p>'
    content_b = '<p style="color:blue;">Text</p>'

    assert 'style="color:red' in cp.normalize_content(content_a), \
        "style= attribute must be preserved, not stripped"
    assert cp.calculate_content_hash(content_a) != cp.calculate_content_hash(content_b)


def test_time_element_change_changes_hash():
    cp = ContentProcessor()
    content_a = '<time datetime="2024-01-01T00:00:00">Jan 1</time>'
    content_b = '<time datetime="2024-01-02T00:00:00">Jan 2</time>'

    assert "Jan 1" in cp.normalize_content(content_a), \
        "time element content must be preserved, not stripped"
    assert cp.calculate_content_hash(content_a) != cp.calculate_content_hash(content_b)


def test_whitespace_and_entity_representation_do_not_change_hash():
    cp = ContentProcessor()

    whitespace_a = "<p>Hello    World.</p>"
    whitespace_b = "<p>Hello\n\n  World.</p>"
    assert cp.calculate_content_hash(whitespace_a) == cp.calculate_content_hash(whitespace_b)

    entity_a = "Fish &amp; Chips"
    entity_b = "Fish &#38; Chips"
    assert cp.calculate_content_hash(entity_a) == cp.calculate_content_hash(entity_b)


# =============================================================================
# B. DatabaseManager.update_content_hash targets exactly one row
# =============================================================================

def test_update_content_hash_restamps_targeted_row_only(db, db_path):
    data_v1 = _insert_post(db, 1, version=1, content="<p>one</p>")
    data_v2 = _insert_post(db, 1, version=2, content="<p>two</p>")

    db.update_content_hash("posts", 1, 1, "restamped-hash")

    conn = raw_connect(db_path)
    hash_v1 = conn.execute(
        "SELECT content_hash FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    hash_v2 = conn.execute(
        "SELECT content_hash FROM posts WHERE wp_id = 1 AND version = 2").fetchone()[0]
    conn.close()

    assert hash_v1 == "restamped-hash"
    assert hash_v2 == data_v2["content_hash"], "the non-targeted version must be untouched"
    assert hash_v2 != "restamped-hash"


# =============================================================================
# B. Rehash-in-place via WordPressArchiver._process_content_item
# =============================================================================

def test_rehash_in_place_after_hash_algorithm_change(archiver, db_path):
    stats = _new_stats(refreshed=0)
    item = make_post(1, title="Hello", content="<p>Same content.</p>")
    archiver._process_content_item("posts", item, stats)

    _corrupt_hash(db_path, wp_id=1, version=1)

    archiver._process_content_item("posts", item, stats)

    assert stats["new"] == 1, "only the first call inserts a brand-new item"
    assert stats["updated"] == 0, "identical content must not mint a new version"

    conn = raw_connect(db_path)
    rows = conn.execute(
        "SELECT version, content_hash FROM posts WHERE wp_id = 1").fetchall()
    conn.close()

    assert len(rows) == 1, "still exactly one version row"
    expected_hash = ContentProcessor().extract_content_data(item, "posts")["content_hash"]
    assert rows[0]["content_hash"] == expected_hash
    assert rows[0]["content_hash"] != "stale-hash"


def test_rehash_in_place_still_refreshes_metadata(archiver, db_path):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts",
        make_post(1, title="Hello", content="<p>Same content.</p>", categories=[10]),
        stats)

    _corrupt_hash(db_path, wp_id=1, version=1)

    conn = raw_connect(db_path)
    old_raw_json = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    conn.close()

    # categories is hash-excluded, so content_hash-wise this is still "the
    # same content" -- only the stale stored hash + the raw_json/categories
    # metadata differ.
    archiver._process_content_item(
        "posts",
        make_post(1, title="Hello", content="<p>Same content.</p>", categories=[10, 20]),
        stats)

    assert stats["updated"] == 0
    assert stats["refreshed"] == 1

    conn = raw_connect(db_path)
    rows = conn.execute("SELECT version FROM posts WHERE wp_id = 1").fetchall()
    new_raw_json = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    hist = conn.execute(
        "SELECT content_type, wp_id, version, raw_json FROM raw_json_history").fetchall()
    conn.close()

    assert len(rows) == 1, "rehash-in-place must not create a new version"
    assert new_raw_json != old_raw_json
    assert len(hist) == 1
    assert hist[0]["content_type"] == "posts"
    assert hist[0]["wp_id"] == 1
    assert hist[0]["raw_json"] == old_raw_json


def test_genuine_content_change_with_stale_hash_creates_new_version(archiver, db_path):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>Original content.</p>"), stats)

    _corrupt_hash(db_path, wp_id=1, version=1)

    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>Changed content!</p>"), stats)

    assert stats["updated"] == 1, "a real content edit must still create a new version"

    conn = raw_connect(db_path)
    versions = sorted(r["version"] for r in conn.execute(
        "SELECT version FROM posts WHERE wp_id = 1"))
    v1_content = conn.execute(
        "SELECT content FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    conn.close()

    assert versions == [1, 2]
    assert v1_content == "<p>Original content.</p>", "v1 must stay immutable"


def test_rehash_none_vs_empty_string_excerpt_equivalence(archiver, db_path):
    stats = _new_stats(refreshed=0)
    item = make_post(1, title="Hello", content="<p>X</p>", excerpt="")
    archiver._process_content_item("posts", item, stats)

    # Simulate a legacy row where the stored excerpt column is NULL (rather
    # than '') while the freshly extracted excerpt is '' -- these must be
    # treated as equal by the hash-source comparison.
    conn = raw_connect(db_path)
    conn.execute("UPDATE posts SET excerpt = NULL WHERE wp_id = 1 AND version = 1")
    conn.commit()
    conn.close()
    _corrupt_hash(db_path, wp_id=1, version=1)

    archiver._process_content_item("posts", item, stats)

    assert stats["updated"] == 0, \
        "NULL-vs-'' excerpt must not be treated as a genuine content change"

    conn = raw_connect(db_path)
    rows = conn.execute("SELECT version FROM posts WHERE wp_id = 1").fetchall()
    conn.close()
    assert len(rows) == 1
