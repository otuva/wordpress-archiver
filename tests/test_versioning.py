"""
Tests for the archiver's versioning contract, per the raw-json-history spec:

- A brand-new item creates version 1.
- A re-processed item whose change is confined to a hash-excluded field (e.g.
  'categories') must NOT create a new version row: instead the latest
  version's raw_json is refreshed in place, the old raw_json is preserved in
  raw_json_history, post_categories/post_tags are re-synced, and the
  "refreshed" stats counter increments by exactly the number of actual
  raw_json replacements (never on a true no-op re-run).
- A change to hashed/rendered content (e.g. content.rendered) DOES create a
  new version row, and existing versions are never mutated (append-only):
  the old version's stored content/raw_json bytes are unchanged afterwards.

Uses WordPressArchiver._process_content_item directly against a real
DatabaseManager on a tmp db -- no network/API required.
"""

from wordpress_archiver.archiver import _new_stats

from conftest import make_post, raw_connect


def test_new_item_creates_version_1(archiver, db_path):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item("posts", make_post(1, title="Hello"), stats)

    assert stats["new"] == 1
    assert stats["updated"] == 0
    assert stats["refreshed"] == 0

    conn = raw_connect(db_path)
    rows = conn.execute(
        "SELECT wp_id, version FROM posts WHERE wp_id = 1").fetchall()
    conn.close()
    assert len(rows) == 1
    assert rows[0]["version"] == 1


def test_hash_excluded_field_change_refreshes_without_new_version(archiver, db_path):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", categories=[10]), stats)

    conn = raw_connect(db_path)
    old_raw_json = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    conn.close()

    # Only 'categories' changes -- content_hash is computed from
    # title+content+excerpt+status only, so this must NOT bump the version.
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", categories=[10, 20]), stats)

    assert stats["new"] == 1        # unchanged: still just the first insert
    assert stats["updated"] == 0    # no new version was created
    assert stats["refreshed"] == 1  # raw_json WAS replaced in place

    conn = raw_connect(db_path)
    versions = [r["version"] for r in conn.execute(
        "SELECT version FROM posts WHERE wp_id = 1")]
    new_raw_json = conn.execute(
        "SELECT raw_json FROM posts WHERE wp_id = 1 AND version = 1").fetchone()[0]
    hist = conn.execute(
        "SELECT content_type, wp_id, version, raw_json FROM raw_json_history"
    ).fetchall()
    cats = {r[0] for r in conn.execute(
        "SELECT category_wp_id FROM post_categories WHERE post_wp_id = 1 AND version = 1")}
    conn.close()

    assert versions == [1], "content-identical re-run must stay a single version"
    assert new_raw_json != old_raw_json
    assert len(hist) == 1
    assert hist[0]["content_type"] == "posts"
    assert hist[0]["wp_id"] == 1
    assert hist[0]["raw_json"] == old_raw_json
    assert cats == {10, 20}, "post_categories junction must be re-synced"


def test_content_change_creates_new_version_and_v1_is_immutable(archiver, db_path):
    stats = _new_stats(refreshed=0)
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>Original content.</p>"), stats)

    conn = raw_connect(db_path)
    v1_before = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 1 AND version = 1").fetchone())
    conn.close()

    archiver._process_content_item(
        "posts", make_post(1, title="Hello", content="<p>Changed content!</p>"), stats)

    assert stats["new"] == 1
    assert stats["updated"] == 1

    conn = raw_connect(db_path)
    versions = sorted(r["version"] for r in conn.execute(
        "SELECT version FROM posts WHERE wp_id = 1"))
    v1_after = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 1 AND version = 1").fetchone())
    v2 = dict(conn.execute(
        "SELECT * FROM posts WHERE wp_id = 1 AND version = 2").fetchone())
    conn.close()

    assert versions == [1, 2], "append-only: a new version row is added"

    # Append-only guarantee: the v1 row's bytes are untouched by the v2 write.
    assert v1_after["content"] == v1_before["content"]
    assert v1_after["raw_json"] == v1_before["raw_json"]
    assert v1_after["content_hash"] == v1_before["content_hash"]

    assert v2["content"] == "<p>Changed content!</p>"
    assert v2["content"] != v1_after["content"]


def test_refreshed_counter_only_increments_on_actual_replacement(archiver):
    stats = _new_stats(refreshed=0)

    # First sighting: counted as "new", not "refreshed".
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", categories=[10]), stats)
    assert stats["refreshed"] == 0

    # Exact re-run: hash AND raw_json both identical -> true no-op.
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", categories=[10]), stats)
    assert stats["refreshed"] == 0
    assert stats["updated"] == 0

    # Hash-excluded field actually differs now -> a genuine replacement.
    archiver._process_content_item(
        "posts", make_post(1, title="Hello", categories=[10, 20]), stats)
    assert stats["refreshed"] == 1
    assert stats["updated"] == 0
