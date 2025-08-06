#!/usr/bin/env python3
"""
WordPress Archive Viewer - Flask Application

A web interface to view and search archived WordPress content.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
import os

app = Flask(__name__)
app.config['DATABASE'] = 'wordpress_archive.db'
app.config['POSTS_PER_PAGE'] = 10
app.config['COMMENTS_PER_PAGE'] = 20


def render_html(text):
    """Render HTML content safely."""
    if not text:
        return ""
    # Decode HTML entities and mark as safe for rendering
    import html
    decoded = html.unescape(text)
    from markupsafe import Markup
    return Markup(decoded)


app.jinja_env.filters['render_html'] = render_html


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(app.config['DATABASE'])
    conn.row_factory = sqlite3.Row
    return conn


def get_archive_stats() -> Dict[str, Any]:
    """Get overall archive statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get counts
    cursor.execute("SELECT COUNT(*) FROM posts")
    total_posts = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM comments")
    total_comments = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM pages")
    total_pages = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM categories")
    total_categories = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tags")
    total_tags = cursor.fetchone()[0]
    
    # Get latest session
    cursor.execute("""
        SELECT id, session_date, content_type, items_processed, items_new, items_updated, errors
        FROM archive_sessions 
        ORDER BY session_date DESC 
        LIMIT 1
    """)
    latest_session = cursor.fetchone()
    
    conn.close()
    
    return {
        "total_posts": total_posts,
        "total_comments": total_comments,
        "total_pages": total_pages,
        "total_users": total_users,
        "total_categories": total_categories,
        "total_tags": total_tags,
        "latest_session": latest_session
    }


@app.route('/')
def index():
    """Home page with overview and statistics."""
    stats = get_archive_stats()
    return render_template('index.html', stats=stats)


@app.route('/posts')
def posts():
    """List all posts with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE title LIKE ? OR content LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM posts {where_clause}", params)
    total_posts = cursor.fetchone()[0]
    
    # Get posts for current page
    query = f"""
        SELECT wp_id, title, excerpt, author_id, date_created, date_modified, 
               status, version, created_at
        FROM posts 
        {where_clause}
        ORDER BY date_created DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    posts = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_posts + per_page - 1) // per_page
    
    return render_template('posts.html', 
                         posts=posts, 
                         page=page, 
                         total_pages=total_pages,
                         total_posts=total_posts,
                         search=search)


@app.route('/posts/<int:wp_id>')
def post_detail(wp_id):
    """Show detailed view of a specific post."""
    version = request.args.get('version', type=int)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get post details
    if version:
        cursor.execute("""
            SELECT wp_id, title, content, excerpt, author_id, date_created, 
                   date_modified, status, version, created_at
            FROM posts 
            WHERE wp_id = ? AND version = ?
        """, (wp_id, version))
        post_versions = cursor.fetchall()
    else:
        cursor.execute("""
            SELECT wp_id, title, content, excerpt, author_id, date_created, 
                   date_modified, status, version, created_at
            FROM posts 
            WHERE wp_id = ?
            ORDER BY version DESC
        """, (wp_id,))
        post_versions = cursor.fetchall()
    
    if not post_versions:
        conn.close()
        return "Post not found", 404
    
    # Get comments for this post
    cursor.execute("""
        SELECT wp_id, author_name, author_email, author_url, content, date_created, status, version, parent_id
        FROM comments 
        WHERE post_id = ?
        ORDER BY date_created ASC
    """, (wp_id,))
    comments = cursor.fetchall()
    
    conn.close()
    
    return render_template('post_detail.html', 
                         post_versions=post_versions,
                         comments=comments,
                         selected_version=version)


@app.route('/comments')
def comments():
    """List all comments with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['COMMENTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE author_name LIKE ? OR content LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM comments {where_clause}", params)
    total_comments = cursor.fetchone()[0]
    
    # Get comments for current page
    query = f"""
        SELECT c.wp_id, c.author_name, c.author_email, c.author_url, c.content, c.date_created, c.status, 
               c.version, c.parent_id, p.title as post_title, p.wp_id as post_id
        FROM comments c
        LEFT JOIN posts p ON c.post_id = p.wp_id
        {where_clause}
        ORDER BY c.date_created DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    comments = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_comments + per_page - 1) // per_page
    
    return render_template('comments.html', 
                         comments=comments, 
                         page=page, 
                         total_pages=total_pages,
                         total_comments=total_comments,
                         search=search)


@app.route('/pages')
def pages():
    """List all pages with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE title LIKE ? OR content LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM pages {where_clause}", params)
    total_pages_count = cursor.fetchone()[0]
    
    # Get pages for current page
    query = f"""
        SELECT wp_id, title, excerpt, author_id, date_created, date_modified, 
               status, version, created_at
        FROM pages 
        {where_clause}
        ORDER BY date_created DESC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    pages = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_pages_count + per_page - 1) // per_page
    
    return render_template('pages.html', 
                         pages=pages, 
                         page=page, 
                         total_pages=total_pages,
                         total_pages_count=total_pages_count,
                         search=search)


@app.route('/pages/<int:wp_id>')
def page_detail(wp_id):
    """Show detailed view of a specific page."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get page details
    cursor.execute("""
        SELECT wp_id, title, content, excerpt, author_id, date_created, 
               date_modified, status, version, created_at
        FROM pages 
        WHERE wp_id = ?
        ORDER BY version DESC
    """, (wp_id,))
    page_versions = cursor.fetchall()
    
    if not page_versions:
        conn.close()
        return "Page not found", 404
    
    conn.close()
    
    return render_template('page_detail.html', page_versions=page_versions)


@app.route('/users')
def users():
    """List all users with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE name LIKE ? OR description LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM users {where_clause}", params)
    total_users = cursor.fetchone()[0]
    
    # Get users for current page
    query = f"""
        SELECT wp_id, name, url, description, link, slug, version, created_at
        FROM users 
        {where_clause}
        ORDER BY name ASC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    users = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_users + per_page - 1) // per_page
    
    return render_template('users.html', 
                         users=users, 
                         page=page, 
                         total_pages=total_pages,
                         total_users=total_users,
                         search=search)


@app.route('/users/<int:wp_id>')
def user_detail(wp_id):
    """Show detailed view of a specific user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get user details
    cursor.execute("""
        SELECT wp_id, name, url, description, link, slug, avatar_urls, mpp_avatar, version, created_at
        FROM users 
        WHERE wp_id = ?
        ORDER BY version DESC
    """, (wp_id,))
    user_versions = cursor.fetchall()
    
    if not user_versions:
        conn.close()
        return "User not found", 404
    
    conn.close()
    
    return render_template('user_detail.html', user_versions=user_versions)


@app.route('/categories')
def categories():
    """List all categories with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE name LIKE ? OR description LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM categories {where_clause}", params)
    total_categories = cursor.fetchone()[0]
    
    # Get categories for current page
    query = f"""
        SELECT wp_id, name, description, link, slug, taxonomy, parent, count, version, created_at
        FROM categories 
        {where_clause}
        ORDER BY name ASC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    categories = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_categories + per_page - 1) // per_page
    
    return render_template('categories.html', 
                         categories=categories, 
                         page=page, 
                         total_pages=total_pages,
                         total_categories=total_categories,
                         search=search)


@app.route('/categories/<int:wp_id>')
def category_detail(wp_id):
    """Show detailed view of a specific category."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get category details
    cursor.execute("""
        SELECT wp_id, name, description, link, slug, taxonomy, parent, count, version, created_at
        FROM categories 
        WHERE wp_id = ?
        ORDER BY version DESC
    """, (wp_id,))
    category_versions = cursor.fetchall()
    
    if not category_versions:
        conn.close()
        return "Category not found", 404
    
    conn.close()
    
    return render_template('category_detail.html', category_versions=category_versions)


@app.route('/tags')
def tags():
    """List all tags with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Build query with search
    where_clause = ""
    params = []
    if search:
        where_clause = "WHERE name LIKE ? OR description LIKE ?"
        params = [f'%{search}%', f'%{search}%']
    
    # Get total count
    cursor.execute(f"SELECT COUNT(*) FROM tags {where_clause}", params)
    total_tags = cursor.fetchone()[0]
    
    # Get tags for current page
    query = f"""
        SELECT wp_id, name, description, link, slug, taxonomy, count, version, created_at
        FROM tags 
        {where_clause}
        ORDER BY name ASC
        LIMIT ? OFFSET ?
    """
    cursor.execute(query, params + [per_page, offset])
    tags = cursor.fetchall()
    
    conn.close()
    
    total_pages = (total_tags + per_page - 1) // per_page
    
    return render_template('tags.html', 
                         tags=tags, 
                         page=page, 
                         total_pages=total_pages,
                         total_tags=total_tags,
                         search=search)


@app.route('/tags/<int:wp_id>')
def tag_detail(wp_id):
    """Show detailed view of a specific tag."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get tag details
    cursor.execute("""
        SELECT wp_id, name, description, link, slug, taxonomy, count, version, created_at
        FROM tags 
        WHERE wp_id = ?
        ORDER BY version DESC
    """, (wp_id,))
    tag_versions = cursor.fetchall()
    
    if not tag_versions:
        conn.close()
        return "Tag not found", 404
    
    conn.close()
    
    return render_template('tag_detail.html', tag_versions=tag_versions)


@app.route('/sessions')
def sessions():
    """Show archive sessions."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, session_date, content_type, items_processed, items_new, 
               items_updated, errors
        FROM archive_sessions 
        ORDER BY session_date DESC
        LIMIT 50
    """)
    sessions = cursor.fetchall()
    
    conn.close()
    
    return render_template('sessions.html', sessions=sessions)


@app.route('/sessions/<int:session_id>')
def session_detail(session_id):
    """Show detailed view of a specific session."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get session details
    cursor.execute("""
        SELECT id, session_date, content_type, items_processed, items_new, 
               items_updated, errors
        FROM archive_sessions 
        WHERE id = ?
    """, (session_id,))
    session = cursor.fetchone()
    
    if not session:
        conn.close()
        return "Session not found", 404
    
    # Parse errors if they exist
    errors_data = []
    if session['errors'] and session['errors'] != '[]':
        try:
            errors_data = json.loads(session['errors'])
        except:
            errors_data = [session['errors']]
    
    conn.close()
    
    return render_template('session_detail.html', session=session, errors_data=errors_data)


@app.route('/api/stats')
def api_stats():
    """API endpoint for archive statistics."""
    stats = get_archive_stats()
    return jsonify(stats)


@app.route('/api/search')
def api_search():
    """API endpoint for searching content."""
    query = request.args.get('q', '')
    content_type = request.args.get('type', 'all')
    
    if not query:
        return jsonify({'results': []})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    results = []
    
    if content_type in ['all', 'posts']:
        cursor.execute("""
            SELECT 'post' as type, wp_id, title, excerpt, date_created
            FROM posts 
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY date_created DESC
            LIMIT 10
        """, [f'%{query}%', f'%{query}%'])
        results.extend(cursor.fetchall())
    
    if content_type in ['all', 'comments']:
        cursor.execute("""
            SELECT 'comment' as type, wp_id, author_name as title, content as excerpt, date_created
            FROM comments 
            WHERE author_name LIKE ? OR content LIKE ?
            ORDER BY date_created DESC
            LIMIT 10
        """, [f'%{query}%', f'%{query}%'])
        results.extend(cursor.fetchall())
    
    if content_type in ['all', 'pages']:
        cursor.execute("""
            SELECT 'page' as type, wp_id, title, excerpt, date_created
            FROM pages 
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY date_created DESC
            LIMIT 10
        """, [f'%{query}%', f'%{query}%'])
        results.extend(cursor.fetchall())
    
    conn.close()
    
    return jsonify({'results': [dict(row) for row in results]})


if __name__ == '__main__':
    # Check if database exists
    if not os.path.exists(app.config['DATABASE']):
        print(f"Database {app.config['DATABASE']} not found!")
        print("Please run the archiver first to create the database.")
        exit(1)
    
    app.run(debug=True, host='0.0.0.0', port=5000) 