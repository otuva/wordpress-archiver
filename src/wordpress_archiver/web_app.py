"""
WordPress Archive Web Application

Flask-based web interface for viewing archived WordPress content.
Provides a clean, fast interface for browsing archived WordPress posts,
comments, pages, users, categories, and tags.
"""

import json
import os
import re
import time
import sqlite3
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, send_file, current_app
from markupsafe import Markup
import html

from .database import DatabaseManager
from .content_processor import (normalize_asset_url, url_hash, is_archivable_asset,
                                extract_video_embeds, _VIDEO_HOSTS,
                                normalize_permalink, resolve_internal_link)

# =============================================================================
# FLASK APP CONFIGURATION
# =============================================================================

app = Flask(__name__, template_folder=Path(__file__).parent / 'templates')

# App configuration
app.config['DATABASE'] = 'wordpress_archive.db'
app.config['POSTS_PER_PAGE'] = 6
app.config['COMMENTS_PER_PAGE'] = 20

# Enable SQLite optimizations
sqlite3.enable_callback_tracebacks(True)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

# =============================================================================
# DISPLAY-TIME ASSET REWRITING (module-level caches & precompiled regexes)
# =============================================================================

# Lazy caches — loaded once on first render_html call. Restarting the server
# picks up newly downloaded videos.
_site_url_cache = None
_video_hash_cache = None
_video_cache_loaded_at = 0.0
# Internal-link rewriting indexes — built once on first render (a server restart
# picks up a grown archive). permalink_map: {host+path -> (content_type, wp_id)};
# the id sets back the ?p= / ?page_id= query-permalink fallback.
_permalink_map_cache = None
_archived_post_ids_cache = None
_archived_page_ids_cache = None

# Precompiled regexes for URL rewriting (no BeautifulSoup dependency).
_REWRITE_IMG_SRC_RX = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)
_REWRITE_SOURCE_SRC_RX = re.compile(
    r'(<source\b[^>]*?\bsrc\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)
_REWRITE_SRCSET_RX = re.compile(
    r'(srcset\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)
_REWRITE_UPLOAD_HREF_RX = re.compile(
    r'(<a\b[^>]*?\bhref\s*=\s*["\'])([^"\']*wp-content/uploads[^"\']*)(["\'])', re.IGNORECASE)
# Matches url(x), url('x') and url( "x" ) alike. Group 2 is the bare URL
# (no quotes/whitespace/paren) so it normalizes to the same hash the archiver's
# _CSS_URL_RE produced at download time; groups 1 and 3 preserve any quotes.
_REWRITE_CSS_URL_RX = re.compile(
    r'(url\(\s*["\']?)([^"\'\)\s]+)(["\']?\s*\))', re.IGNORECASE)
_REWRITE_IFRAME_VIDEO_RX = re.compile(
    r'<iframe\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\'][^>]*>(?:.*?</iframe>)?',
    re.IGNORECASE | re.DOTALL)
_REWRITE_META_IMG_RX = re.compile(
    r'(<meta\b[^>]*?(?:property|name)\s*=\s*["\'](?:og:image(?::url)?|twitter:image)["\']'
    r'[^>]*?\bcontent\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)
_REWRITE_ANY_UPLOAD_RX = re.compile(
    r'https?://[^\s"\'<>()]+/wp-content/uploads/[^\s"\'<>()]+', re.IGNORECASE)
# Any anchor href — the resolver decides whether it maps to an archived post/page.
_REWRITE_ANCHOR_HREF_RX = re.compile(
    r'(<a\b[^>]*?\bhref\s*=\s*["\'])([^"\']+)(["\'])', re.IGNORECASE)


# 1x1 transparent GIF placeholder for missing media assets (43 bytes).
_TRANSPARENT_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x00\x00\x00\x00\x00'
    b'\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x44\x01\x00\x3b'
)


def render_html(text: str) -> str:
    """
    Render HTML content safely for display in templates.
    Rewrites asset URLs to local /media/<hash> routes and converts downloaded
    video iframes to <video> elements. Stored content is never mutated.

    Args:
        text: Raw HTML text to render

    Returns:
        Safely rendered HTML markup
    """
    if not text:
        return ""
    decoded = html.unescape(text)

    # Lazy-load caches on first use (app context must be active).
    global _site_url_cache, _video_hash_cache, _video_cache_loaded_at
    if _site_url_cache is None:
        _site_url_cache = get_db_manager().get_meta('site_url') or ''
    if _video_hash_cache is None or time.time() - _video_cache_loaded_at > 60:
        _video_hash_cache = get_db_manager().downloaded_video_hashes()
        _video_cache_loaded_at = time.time()

    site_url = _site_url_cache
    downloaded_videos = _video_hash_cache

    # Build the internal-link index once (read-only; cached for the process).
    global _permalink_map_cache, _archived_post_ids_cache, _archived_page_ids_cache
    if _permalink_map_cache is None:
        pmap, post_ids, page_ids = {}, set(), set()
        for link, ctype, wp_id in get_db_manager().permalink_index():
            key = normalize_permalink(link, site_url)
            if key:
                pmap[key] = (ctype, wp_id)
            (post_ids if ctype == 'posts' else page_ids).add(wp_id)
        _permalink_map_cache = pmap
        _archived_post_ids_cache = post_ids
        _archived_page_ids_cache = page_ids

    # --- Replace video iframes that have been downloaded with <video> ---
    def _replace_video_iframe(m):
        src = m.group(1).strip()
        # Handle protocol-relative URLs identically to extract_video_embeds
        check_src = src
        if src.lower().startswith('//'):
            check_src = 'https:' + src
        # Only touch known video hosts; leave other embeds intact
        if not any(h in check_src.lower() for h in _VIDEO_HOSTS):
            return m.group(0)
        # Hashing must use the same logic as the archiver
        norm = normalize_asset_url(check_src, site_url)
        h = url_hash(norm)
        if h in downloaded_videos:
            return ('<video controls preload="metadata" style="max-width:100%">'
                    f'<source src="/video/{h}" type="video/mp4">'
                    'Your browser does not support the video tag.</video>')
        # Not downloaded — keep the iframe as-is (works online via frame-src *)
        return m.group(0)

    decoded = _REWRITE_IFRAME_VIDEO_RX.sub(_replace_video_iframe, decoded)

    # --- Generic asset URL rewriting (img, source, upload href, css url) ---
    def _rewrite_asset_url(m):
        before = m.group(1)
        url = m.group(2)
        after = m.group(3)
        norm = normalize_asset_url(url, site_url)
        if norm and is_archivable_asset(norm):
            return before + '/media/' + url_hash(norm) + after
        return m.group(0)

    decoded = _REWRITE_IMG_SRC_RX.sub(_rewrite_asset_url, decoded)
    decoded = _REWRITE_SOURCE_SRC_RX.sub(_rewrite_asset_url, decoded)
    decoded = _REWRITE_UPLOAD_HREF_RX.sub(_rewrite_asset_url, decoded)

    # --- Internal hyperlinks: archived post/page permalinks -> local routes ---
    def _rewrite_internal_link(m):
        local = resolve_internal_link(m.group(2), site_url, _permalink_map_cache,
                                      _archived_post_ids_cache, _archived_page_ids_cache)
        return m.group(1) + local + m.group(3) if local else m.group(0)

    decoded = _REWRITE_ANCHOR_HREF_RX.sub(_rewrite_internal_link, decoded)

    decoded = _REWRITE_CSS_URL_RX.sub(_rewrite_asset_url, decoded)

    # --- srcset rewriting (each attribute holds multiple URL+descriptor pairs) ---
    def _rewrite_srcset(m):
        before = m.group(1)
        value = m.group(2)
        after = m.group(3)
        parts = []
        for candidate in value.split(','):
            candidate = candidate.strip()
            if not candidate:
                continue
            tokens = candidate.split()
            if not tokens:
                continue
            url = tokens[0]
            norm = normalize_asset_url(url, site_url)
            if norm and is_archivable_asset(norm):
                tokens[0] = '/media/' + url_hash(norm)
            parts.append(' '.join(tokens))
        return before + ', '.join(parts) + after

    decoded = _REWRITE_SRCSET_RX.sub(_rewrite_srcset, decoded)

    # --- Meta og:image / twitter:image rewrite ---
    decoded = _REWRITE_META_IMG_RX.sub(_rewrite_asset_url, decoded)

    # --- Generic uploads URL rewrite (catches data-src, style, etc.) ---
    def _rewrite_any_upload(m):
        url = m.group(0)
        norm = normalize_asset_url(url, site_url)
        if norm and is_archivable_asset(norm):
            return '/media/' + url_hash(norm)
        return url

    decoded = _REWRITE_ANY_UPLOAD_RX.sub(_rewrite_any_upload, decoded)

    return Markup(decoded)


def calculate_indentation(level: int) -> int:
    """
    Calculate indentation for comment levels, capped at 200px.
    
    Args:
        level: Comment nesting level
        
    Returns:
        Indentation in pixels (capped at 200px)
    """
    return min(level * 20, 200)


_db_manager = None

def get_db_manager() -> DatabaseManager:
    """Get database manager instance."""
    global _db_manager
    db_path = app.config['DATABASE']
    if _db_manager is None or str(_db_manager.db_path) != db_path:
        _db_manager = DatabaseManager(db_path)
    return _db_manager


def get_archive_stats() -> Dict[str, Any]:
    """Get overall archive statistics."""
    db = get_db_manager()
    return db.get_stats()





# =============================================================================
# JINJA2 FILTERS
# =============================================================================

app.jinja_env.filters['render_html'] = render_html
app.jinja_env.filters['calculate_indentation'] = calculate_indentation


def rewrite_url(url):
    """Jinja filter: rewrite a single asset URL to local /media/<hash>.

    Used for standalone URLs such as avatars that are not embedded in HTML.
    """
    if not url:
        return url
    global _site_url_cache
    if _site_url_cache is None:
        _site_url_cache = get_db_manager().get_meta('site_url') or ''
    norm = normalize_asset_url(url, _site_url_cache)
    if norm and is_archivable_asset(norm):
        return '/media/' + url_hash(norm)
    return url


app.jinja_env.filters['rewrite_url'] = rewrite_url

# =============================================================================
# CONTEXT PROCESSORS
# =============================================================================

@app.context_processor
def inject_current_year():
    """Inject current year into all templates."""
    return {'current_year': datetime.now().year}

# =============================================================================
# SECURITY HEADERS
# =============================================================================

# Content Security Policy: archived HTML is stored and served verbatim, but the
# browser must never EXECUTE script it contains. script-src is locked to 'self'
# (only our own vendored JS), so inline <script>, javascript: URLs and on*=
# handlers coming from arbitrary archived sites are inert. Inline styles, images,
# fonts and iframe embeds stay allowed so archived content renders faithfully.
CSP_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://fonts.googleapis.com",
    "img-src * data:",
    "media-src 'self'",
    "font-src 'self' https://cdnjs.cloudflare.com https://fonts.gstatic.com data:",
    "frame-src *",
    "object-src 'none'",
    "base-uri 'self'",
])


@app.after_request
def set_security_headers(response):
    """Attach a CSP that neutralizes any script embedded in archived content."""
    response.headers['Content-Security-Policy'] = CSP_POLICY
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

# =============================================================================
# ROUTE HANDLERS - MAIN PAGES
# =============================================================================

@app.route('/')
def index():
    """Home page with overview and statistics."""
    stats = get_archive_stats()
    return render_template('index.html', stats=stats)


@app.route('/posts')
def posts():
    """
    List all posts with pagination and search functionality.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for title/content
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    posts, total_posts, total_pages = db.get_paginated_posts(page, per_page, search)
    
    return render_template('posts.html', 
                         posts=posts, 
                         page=page, 
                         total_pages=total_pages,
                         total_posts=total_posts,
                         search=search)


@app.route('/posts/<int:wp_id>')
def post_detail(wp_id):
    """
    Show detailed view of a specific post with comments.
    
    Args:
        wp_id: WordPress post ID
        
    Query Parameters:
        version: Specific version to display
    """
    version = request.args.get('version', type=int)

    db = get_db_manager()

    # Always load the full version history so the version switcher stays
    # available. When a specific version is requested, surface it as the
    # displayed one (post_versions[0]) without dropping the other versions
    # the switcher needs to navigate between them.
    post_versions = db.get_content_versions('posts', wp_id)
    if not post_versions:
        return "Post not found", 404
    if version:
        selected = [p for p in post_versions if p['version'] == version]
        if selected:
            others = [p for p in post_versions if p['version'] != version]
            post_versions = selected + others
    if version and not selected:
        return ("Post version not found", 404)

    # Get comments for this post
    comments = db.get_post_comments(wp_id)

    # Get categories and tags for the displayed (front) version.
    post_version = post_versions[0]['version']
    categories = db.get_post_categories(wp_id, post_version)
    tags = db.get_post_tags(wp_id, post_version)
    
    # Get author names for all post versions
    for post_version_item in post_versions:
        author_id = post_version_item.get('author_id')
        if author_id:
            author_versions = db.get_content_versions('users', author_id)
            if author_versions:
                post_version_item['author_name'] = author_versions[0].get('name', 'Unknown')
            else:
                post_version_item['author_name'] = 'Unknown'
        else:
            post_version_item['author_name'] = 'Unknown'
    
    return render_template('post_detail.html', 
                         post_versions=post_versions,
                         comments=comments,
                         categories=categories,
                         tags=tags,
                         selected_version=version)


@app.route('/comments')
def comments():
    """
    List all comments with pagination and optimized performance.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for author/content
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['COMMENTS_PER_PAGE']
    
    db = get_db_manager()
    comments, total_comments, total_pages = db.get_paginated_comments(page, per_page, search)
    
    return render_template('comments.html', 
                         comments=comments, 
                         page=page, 
                         total_pages=total_pages,
                         total_comments=total_comments,
                         search=search)


@app.route('/pages')
def pages():
    """
    List all pages with pagination and search functionality.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for title/content
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    pages, total_pages_count, total_pages = db.get_paginated_pages(page, per_page, search)
    
    return render_template('pages.html', 
                         pages=pages, 
                         page=page, 
                         total_pages=total_pages,
                         total_pages_count=total_pages_count,
                         search=search)


@app.route('/pages/<int:wp_id>')
def page_detail(wp_id):
    """
    Show detailed view of a specific page.
    
    Args:
        wp_id: WordPress page ID
    """
    db = get_db_manager()
    page_versions = db.get_content_versions('pages', wp_id)
    
    if not page_versions:
        return "Page not found", 404
    
    return render_template('page_detail.html', page_versions=page_versions)


@app.route('/users')
def users():
    """
    List all users with pagination and search functionality.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for name/description
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    users, total_users, total_pages = db.get_paginated_users(page, per_page, search)
    
    return render_template('users.html', 
                         users=users, 
                         page=page, 
                         total_pages=total_pages,
                         total_users=total_users,
                         search=search)


@app.route('/users/<int:wp_id>')
def user_detail(wp_id):
    """
    Show detailed view of a specific user with their posts.
    
    Args:
        wp_id: WordPress user ID
    """
    page = request.args.get('page', 1, type=int)
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    user_versions = db.get_content_versions('users', wp_id)
    
    if not user_versions:
        return "User not found", 404
    
    # Parse avatar_urls JSON for each version
    for user_version in user_versions:
        avatar_urls = user_version.get('avatar_urls', '')
        if avatar_urls:
            try:
                if isinstance(avatar_urls, str):
                    user_version['avatar_urls'] = json.loads(avatar_urls)
                elif isinstance(avatar_urls, dict):
                    # Already a dict, no parsing needed
                    pass
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, keep as is
                pass
    
    # Get posts by this author
    posts, total_posts, total_pages = db.get_posts_by_author(wp_id, page, per_page)
    
    return render_template('user_detail.html', 
                         user_versions=user_versions,
                         posts=posts,
                         page=page,
                         total_pages=total_pages,
                         total_posts=total_posts)


@app.route('/categories')
def categories():
    """
    List all categories with pagination and search functionality.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for name/description
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    categories, total_categories, total_pages = db.get_paginated_categories(page, per_page, search)
    
    return render_template('categories.html', 
                         categories=categories, 
                         page=page, 
                         total_pages=total_pages,
                         total_categories=total_categories,
                         search=search)


@app.route('/categories/<int:wp_id>')
def category_detail(wp_id):
    """
    Show detailed view of a specific category with posts.
    
    Args:
        wp_id: WordPress category ID
    """
    page = request.args.get('page', 1, type=int)
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    category_versions = db.get_content_versions('categories', wp_id)
    
    if not category_versions:
        return "Category not found", 404
    
    # Get posts for this category
    posts, total_posts, total_pages = db.get_posts_by_category(wp_id, page, per_page)
    
    return render_template('category_detail.html', 
                         category_versions=category_versions,
                         posts=posts,
                         page=page,
                         total_pages=total_pages,
                         total_posts=total_posts)


@app.route('/tags')
def tags():
    """
    List all tags with pagination and search functionality.
    
    Query Parameters:
        page: Page number (default: 1)
        search: Search term for name/description
    """
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    tags, total_tags, total_pages = db.get_paginated_tags(page, per_page, search)
    
    return render_template('tags.html', 
                         tags=tags, 
                         page=page, 
                         total_pages=total_pages,
                         total_tags=total_tags,
                         search=search)


@app.route('/tags/<int:wp_id>')
def tag_detail(wp_id):
    """
    Show detailed view of a specific tag with posts.
    
    Args:
        wp_id: WordPress tag ID
    """
    page = request.args.get('page', 1, type=int)
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    tag_versions = db.get_content_versions('tags', wp_id)
    
    if not tag_versions:
        return "Tag not found", 404
    
    # Get posts for this tag
    posts, total_posts, total_pages = db.get_posts_by_tag(wp_id, page, per_page)
    
    return render_template('tag_detail.html', 
                         tag_versions=tag_versions,
                         posts=posts,
                         page=page,
                         total_pages=total_pages,
                         total_posts=total_posts)


@app.route('/sessions')
def sessions():
    """
    List all archive sessions with pagination.
    
    Query Parameters:
        page: Page number (default: 1)
    """
    page = request.args.get('page', 1, type=int)
    per_page = app.config['POSTS_PER_PAGE']
    
    db = get_db_manager()
    sessions, total_sessions, total_pages = db.get_paginated_sessions(page, per_page)
    
    # Parse errors and content types for each session
    parsed_sessions = []
    for session in sessions:
        # Convert sqlite3.Row to dict first
        session_dict = dict(session)
        
        # Parse errors - check if errors field contains actual error messages
        has_errors = False
        if session_dict.get('errors'):
            try:
                errors_json = session_dict['errors']
                if isinstance(errors_json, str):
                    errors_list = json.loads(errors_json)
                elif isinstance(errors_json, list):
                    errors_list = errors_json
                else:
                    errors_list = []
                
                # Check if any item in the list is an actual error message
                # Content summaries don't count as errors
                if isinstance(errors_list, list):
                    error_indicators = ['error', 'failed', 'exception', 'errors occurred']
                    has_errors = any(
                        any(indicator in str(item).lower() for indicator in error_indicators)
                        for item in errors_list
                    )
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, check if the string contains error indicators
                errors_str = str(session_dict.get('errors', '')).lower()
                has_errors = 'error' in errors_str or 'failed' in errors_str
        
        # Parse content type
        parsed_ct = _parse_content_type(session_dict.get('content_type', ''))
        
        # Add parsed info to session dict
        session_dict['has_errors'] = has_errors
        session_dict['parsed_content_type'] = parsed_ct
        parsed_sessions.append(session_dict)
    
    return render_template('sessions.html', 
                         sessions=parsed_sessions, 
                         page=page, 
                         total_pages=total_pages,
                         total_sessions=total_sessions)


@app.route('/sessions/<int:session_id>')
def session_detail(session_id):
    """
    Show detailed view of a specific archive session.
    
    Args:
        session_id: Archive session ID
    """
    db = get_db_manager()
    session = db.get_session_by_id(session_id)
    
    if not session:
        return "Session not found", 404
    
    # Parse errors JSON - filter to only actual error messages
    errors_data = []
    if session.get('errors'):
        try:
            errors_json = session['errors']
            if isinstance(errors_json, str):
                errors_list = json.loads(errors_json)
            elif isinstance(errors_json, list):
                errors_list = errors_json
            else:
                errors_list = []
            
            # Filter to only actual error messages (not content summaries)
            error_indicators = ['error', 'failed', 'exception', 'errors occurred']
            errors_data = [
                item for item in errors_list
                if isinstance(item, str) and any(
                    indicator in item.lower() for indicator in error_indicators
                )
            ]
        except (json.JSONDecodeError, TypeError):
            # If parsing fails, check if string contains error indicators
            errors_str = str(session.get('errors', '')).lower()
            if any(indicator in errors_str for indicator in ['error', 'failed', 'exception']):
                errors_data = [str(session['errors'])]
    
    # Parse content type to extract info
    content_type = session.get('content_type', '')
    parsed_content_type = _parse_content_type(content_type)
    
    return render_template('session_detail.html', 
                         session=session,
                         errors_data=errors_data,
                         parsed_content_type=parsed_content_type)


def _parse_content_type(content_type_str: str) -> Dict[str, Any]:
    """
    Parse content type string to extract meaningful information.
    
    Args:
        content_type_str: Content type string from database
        
    Returns:
        Dictionary with parsed content type information
    """
    if not content_type_str:
        return {'type': 'unknown', 'display': 'Unknown', 'types': []}
    
    # Check for comprehensive archive sessions
    if 'Archive of' in content_type_str:
        parts = content_type_str.split(' - ', 1)
        if len(parts) == 2:
            domain = parts[0].replace('Archive of ', '').strip()
            types_str = parts[1]
            types_list = [t.strip() for t in types_str.split(',')]
            
            # If only one type, treat it as a single type, not comprehensive
            if len(types_list) == 1:
                type_name = types_list[0].lower()
                return {
                    'type': 'single',
                    'display': types_list[0].title(),
                    'types': [type_name]
                }
            
            # Multiple types or empty - this is a complete archive
            return {
                'type': 'comprehensive',
                'display': 'Complete Archive',
                'domain': domain,
                'types': types_list
            }
    
    # Check for interrupted sessions
    if 'INTERRUPTED' in content_type_str:
        parts = content_type_str.split(' - ', 1)
        if len(parts) >= 2:
            rest = parts[1]
            if 'Archive of' in rest:
                archive_parts = rest.split(' - ', 1)
                if len(archive_parts) == 2:
                    domain = archive_parts[0].replace('Archive of ', '').strip()
                    types_str = archive_parts[1]
                    types_list = [t.strip() for t in types_str.split(',')]
                    return {
                        'type': 'interrupted',
                        'display': 'Interrupted Archive',
                        'domain': domain,
                        'types': types_list
                    }
        return {
            'type': 'interrupted',
            'display': 'Interrupted',
            'domain': None,
            'types': []
        }
    
    # Check for failed verification
    if 'FAILED VERIFICATION' in content_type_str:
        parts = content_type_str.split(' - ', 2)
        domain = parts[1] if len(parts) > 1 else None
        reason = parts[2] if len(parts) > 2 else None
        return {
            'type': 'failed_verification',
            'display': 'Failed Verification',
            'domain': domain,
            'reason': reason
        }
    
    # Single content type (normal case)
    valid_types = ['posts', 'comments', 'pages', 'users', 'categories', 'tags']
    if content_type_str.lower() in valid_types:
        return {
            'type': 'single',
            'display': content_type_str.title(),
            'types': [content_type_str.lower()]
        }
    
    # Unknown format
    return {
        'type': 'unknown',
        'display': content_type_str,
        'types': []
    }


# =============================================================================
# ROUTE HANDLERS - MEDIA & RAW API
# =============================================================================


@app.route('/media/<url_hash>')
def serve_media(url_hash):
    """Serve archived media files by URL hash (images, documents, etc.)."""
    db = get_db_manager()
    media = db.get_media_by_url_hash(url_hash)
    if media and media.get('status') == 'ok' and media.get('content') is not None:
        resp = Response(
            media['content'],
            mimetype=media.get('mime_type', 'application/octet-stream')
        )
        resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        return resp
    # Return 1x1 transparent GIF for misses / failed / oversized
    return Response(
        _TRANSPARENT_GIF,
        mimetype='image/gif',
        headers={'Cache-Control': 'no-cache'}
    )


@app.route('/video/<url_hash>')
def serve_video(url_hash):
    """Serve downloaded video files by URL hash."""
    db = get_db_manager()
    video = db.get_video_by_url_hash(url_hash)
    if video and video.get('status') == 'downloaded':
        local_path = video.get('local_path')
        if local_path:
            db_path = Path(current_app.config['DATABASE'])
            video_dir = db_path.parent / (db_path.stem + '_media') / 'videos'
            video_file = video_dir / local_path
            if video_file.exists():
                return send_file(str(video_file), mimetype='video/mp4')
    return ("Video not available", 404)


@app.route('/raw')
def raw_endpoints():
    """List all available API endpoints with object counts."""
    db = get_db_manager()
    endpoints = db.get_api_endpoints()
    return render_template('raw_endpoints.html', endpoints=endpoints)


@app.route('/raw/<path:endpoint_name>')
def raw_objects(endpoint_name):
    """Browse raw API objects for a given endpoint with pagination."""
    # Clamp user-supplied paging: per_page=0 would divide-by-zero, page<1 would
    # produce a negative OFFSET. Cap per_page to keep one page bounded.
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(200, max(1, request.args.get('per_page', 20, type=int)))
    db = get_db_manager()
    lookup = '/' + endpoint_name.lstrip('/')
    rows, total, total_pages = db.get_paginated_api_objects(lookup, page, per_page)
    objects_data = []
    for row in rows:
        obj = dict(row)
        if obj.get('raw_json'):
            try:
                obj['pretty_json'] = json.dumps(
                    json.loads(obj['raw_json']),
                    indent=2,
                    ensure_ascii=False
                )
            except (json.JSONDecodeError, TypeError):
                obj['pretty_json'] = obj['raw_json']
        objects_data.append(obj)
    return render_template(
        'raw_objects.html',
        endpoint=endpoint_name,
        objects=objects_data,
        page=page,
        total_pages=total_pages,
        total=total,
        per_page=per_page
    )
