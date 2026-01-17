"""
WordPress Archive Web Application

Flask-based web interface for viewing archived WordPress content.
Provides a clean, fast interface for browsing archived WordPress posts,
comments, pages, users, categories, and tags.
"""

import json
import os
import sqlite3
from typing import Dict, Any, List, Optional
from pathlib import Path

from flask import Flask, render_template, request, jsonify, redirect, url_for
from markupsafe import Markup
import html

from .database import DatabaseManager

# =============================================================================
# FLASK APP CONFIGURATION
# =============================================================================

app = Flask(__name__, template_folder=Path(__file__).parent / 'templates')

# App configuration
app.config['DATABASE'] = 'wordpress_archive.db'
app.config['POSTS_PER_PAGE'] = 10
app.config['COMMENTS_PER_PAGE'] = 20

# Enable SQLite optimizations
sqlite3.enable_callback_tracebacks(True)

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def render_html(text: str) -> str:
    """
    Render HTML content safely for display in templates.
    
    Args:
        text: Raw HTML text to render
        
    Returns:
        Safely rendered HTML markup
    """
    if not text:
        return ""
    decoded = html.unescape(text)
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


def get_db_manager() -> DatabaseManager:
    """Get database manager instance."""
    return DatabaseManager(app.config['DATABASE'])


def get_archive_stats() -> Dict[str, Any]:
    """Get overall archive statistics."""
    db = get_db_manager()
    return db.get_stats()





# =============================================================================
# JINJA2 FILTERS
# =============================================================================

app.jinja_env.filters['render_html'] = render_html
app.jinja_env.filters['calculate_indentation'] = calculate_indentation

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
    
    # Get post versions
    if version:
        post_versions = db.get_content_versions('posts', wp_id)
        post_versions = [p for p in post_versions if p['version'] == version]
    else:
        post_versions = db.get_content_versions('posts', wp_id)
    
    if not post_versions:
        return "Post not found", 404
    
    # Get comments for this post
    comments = db.get_post_comments(wp_id)
    
    # Get categories and tags for the post (use selected version or latest)
    post_version = version if version else (post_versions[0]['version'] if post_versions else None)
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
    Show detailed view of a specific user.
    
    Args:
        wp_id: WordPress user ID
    """
    db = get_db_manager()
    user_versions = db.get_content_versions('users', wp_id)
    
    if not user_versions:
        return "User not found", 404
    
    return render_template('user_detail.html', user_versions=user_versions)


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
        
        # Parse errors
        has_errors = False
        if session_dict.get('errors'):
            try:
                errors_json = session_dict['errors']
                if isinstance(errors_json, str):
                    errors_list = json.loads(errors_json)
                    has_errors = len(errors_list) > 0 and errors_list != []
                elif isinstance(errors_json, list):
                    has_errors = len(errors_json) > 0
            except (json.JSONDecodeError, TypeError):
                has_errors = session_dict['errors'] and str(session_dict['errors']) != '[]'
        
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
    
    # Parse errors JSON
    errors_data = []
    if session.get('errors'):
        try:
            errors_json = session['errors']
            if isinstance(errors_json, str):
                errors_data = json.loads(errors_json)
            elif isinstance(errors_json, list):
                errors_data = errors_json
        except (json.JSONDecodeError, TypeError):
            # If parsing fails, treat as string
            if session['errors'] and session['errors'] != '[]':
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

 