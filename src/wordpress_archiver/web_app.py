"""
WordPress Archive Web Application

Flask-based web interface for viewing archived WordPress content.
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for
import json
import os
from typing import Dict, Any, List, Optional
from pathlib import Path

from .database import DatabaseManager

app = Flask(__name__, template_folder=Path(__file__).parent / 'templates')
app.config['DATABASE'] = 'wordpress_archive.db'
app.config['POSTS_PER_PAGE'] = 10
app.config['COMMENTS_PER_PAGE'] = 20


def render_html(text: str) -> str:
    """Render HTML content safely."""
    if not text:
        return ""
    import html
    decoded = html.unescape(text)
    from markupsafe import Markup
    return Markup(decoded)


def calculate_indentation(level: int) -> int:
    """Calculate indentation for comment levels, capped at 200px."""
    return min(level * 20, 200)


app.jinja_env.filters['render_html'] = render_html
app.jinja_env.filters['calculate_indentation'] = calculate_indentation


def get_db_manager() -> DatabaseManager:
    """Get database manager instance."""
    return DatabaseManager(app.config['DATABASE'])


def get_archive_stats() -> Dict[str, Any]:
    """Get overall archive statistics."""
    db = get_db_manager()
    return db.get_stats()


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
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
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
    
    db = get_db_manager()
    
    if version:
        post_versions = db.get_content_versions('posts', wp_id)
        post_versions = [p for p in post_versions if p['version'] == version]
    else:
        post_versions = db.get_content_versions('posts', wp_id)
    
    if not post_versions:
        return "Post not found", 404
    
    # Get comments for this post
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT wp_id, author_name, author_email, author_url, content, date_created, status, version, parent_id
            FROM comments 
            WHERE post_id = ?
            ORDER BY date_created ASC
        """, (wp_id,))
        all_comments = cursor.fetchall()
        
        # Convert to list of dicts for easier manipulation
        comment_dicts = []
        for comment in all_comments:
            # Convert parent_id 0 to None for easier handling
            parent_id = comment[8] if comment[8] != 0 else None
            comment_dicts.append({
                'wp_id': comment[0],
                'author_name': comment[1],
                'author_email': comment[2],
                'author_url': comment[3],
                'content': comment[4],
                'date_created': comment[5],
                'status': comment[6],
                'version': comment[7],
                'parent_id': parent_id,
                'replies': []
            })
        
        # Build comment hierarchy
        def build_comment_tree(comments, parent_id=None):
            tree = []
            for comment in comments:
                if comment['parent_id'] == parent_id:
                    comment['replies'] = build_comment_tree(comments, comment['wp_id'])
                    tree.append(comment)
            return tree
        
        # Build the comment tree
        comment_tree = build_comment_tree(comment_dicts)
        
        # Flatten the tree for display (depth-first traversal)
        def flatten_tree(tree, level=0):
            flattened = []
            for comment in tree:
                comment['level'] = level
                flattened.append(comment)
                if comment['replies']:
                    flattened.extend(flatten_tree(comment['replies'], level + 1))
            return flattened
        
        comments = flatten_tree(comment_tree)
    
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
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Build query with search
        where_clause = ""
        params = []
        if search:
            where_clause = "WHERE c.author_name LIKE ? OR c.content LIKE ?"
            params = [f'%{search}%', f'%{search}%']
        
        # Get total count
        cursor.execute(f"SELECT COUNT(*) FROM comments c {where_clause}", params)
        total_comments = cursor.fetchone()[0]
        
        # Use recursive CTE to calculate comment levels and get paginated results
        if search:
            # For search, we need to include all matching comments and their ancestors
            query = f"""
                WITH RECURSIVE comment_tree AS (
                    -- Base case: top-level comments (parent_id = 0 or NULL)
                    SELECT 
                        c.wp_id, c.author_name, c.author_email, c.author_url, c.content, 
                        c.date_created, c.status, c.version, c.parent_id, 
                        p.title as post_title, p.wp_id as post_id,
                        0 as level,
                        c.date_created as sort_order
                    FROM comments c
                    LEFT JOIN posts p ON c.post_id = p.wp_id
                    WHERE (c.parent_id = 0 OR c.parent_id IS NULL)
                    AND (c.author_name LIKE ? OR c.content LIKE ?)
                    
                    UNION ALL
                    
                    -- Recursive case: child comments
                    SELECT 
                        c.wp_id, c.author_name, c.author_email, c.author_url, c.content, 
                        c.date_created, c.status, c.version, c.parent_id, 
                        p.title as post_title, p.wp_id as post_id,
                        ct.level + 1,
                        c.date_created as sort_order
                    FROM comments c
                    LEFT JOIN posts p ON c.post_id = p.wp_id
                    JOIN comment_tree ct ON c.parent_id = ct.wp_id
                    WHERE (c.author_name LIKE ? OR c.content LIKE ?)
                )
                SELECT * FROM comment_tree
                ORDER BY sort_order ASC, level ASC
                LIMIT ? OFFSET ?
            """
            query_params = [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%', per_page, offset]
        else:
            # No search - use simple recursive CTE
            query = """
                WITH RECURSIVE comment_tree AS (
                    -- Base case: top-level comments (parent_id = 0 or NULL)
                    SELECT 
                        c.wp_id, c.author_name, c.author_email, c.author_url, c.content, 
                        c.date_created, c.status, c.version, c.parent_id, 
                        p.title as post_title, p.wp_id as post_id,
                        0 as level,
                        c.date_created as sort_order
                    FROM comments c
                    LEFT JOIN posts p ON c.post_id = p.wp_id
                    WHERE (c.parent_id = 0 OR c.parent_id IS NULL)
                    
                    UNION ALL
                    
                    -- Recursive case: child comments
                    SELECT 
                        c.wp_id, c.author_name, c.author_email, c.author_url, c.content, 
                        c.date_created, c.status, c.version, c.parent_id, 
                        p.title as post_title, p.wp_id as post_id,
                        ct.level + 1,
                        c.date_created as sort_order
                    FROM comments c
                    LEFT JOIN posts p ON c.post_id = p.wp_id
                    JOIN comment_tree ct ON c.parent_id = ct.wp_id
                )
                SELECT * FROM comment_tree
                ORDER BY sort_order ASC, level ASC
                LIMIT ? OFFSET ?
            """
            query_params = [per_page, offset]
        
        # Execute query with pagination parameters
        cursor.execute(query, query_params)
        paginated_comments = cursor.fetchall()
        
        # Convert to list of dicts
        comments = []
        for comment in paginated_comments:
            parent_id = comment[8] if comment[8] != 0 else None
            comments.append({
                'wp_id': comment[0],
                'author_name': comment[1],
                'author_email': comment[2],
                'author_url': comment[3],
                'content': comment[4],
                'date_created': comment[5],
                'status': comment[6],
                'version': comment[7],
                'parent_id': parent_id,
                'post_title': comment[9],
                'post_id': comment[10],
                'level': comment[11]
            })
    
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
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
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
    db = get_db_manager()
    page_versions = db.get_content_versions('pages', wp_id)
    
    if not page_versions:
        return "Page not found", 404
    
    return render_template('page_detail.html', page_versions=page_versions)


@app.route('/users')
def users():
    """List all users with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
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
    db = get_db_manager()
    user_versions = db.get_content_versions('users', wp_id)
    
    if not user_versions:
        return "User not found", 404
    
    return render_template('user_detail.html', user_versions=user_versions)


@app.route('/categories')
def categories():
    """List all categories with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
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
    db = get_db_manager()
    category_versions = db.get_content_versions('categories', wp_id)
    
    if not category_versions:
        return "Category not found", 404
    
    return render_template('category_detail.html', category_versions=category_versions)


@app.route('/tags')
def tags():
    """List all tags with pagination."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    per_page = app.config['POSTS_PER_PAGE']
    offset = (page - 1) * per_page
    
    db = get_db_manager()
    
    with db.get_connection() as conn:
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
    db = get_db_manager()
    tag_versions = db.get_content_versions('tags', wp_id)
    
    if not tag_versions:
        return "Tag not found", 404
    
    return render_template('tag_detail.html', tag_versions=tag_versions)


@app.route('/sessions')
def sessions():
    """Show archive sessions."""
    db = get_db_manager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_date, content_type, items_processed, items_new, 
                   items_updated, errors
            FROM archive_sessions 
            ORDER BY session_date DESC
            LIMIT 50
        """)
        sessions = cursor.fetchall()
    
    return render_template('sessions.html', sessions=sessions)


@app.route('/sessions/<int:session_id>')
def session_detail(session_id):
    """Show detailed view of a specific session."""
    db = get_db_manager()
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, session_date, content_type, items_processed, items_new, 
                   items_updated, errors
            FROM archive_sessions 
            WHERE id = ?
        """, (session_id,))
        session = cursor.fetchone()
    
    if not session:
        return "Session not found", 404
    
    # Parse errors if they exist
    errors_data = []
    if session['errors'] and session['errors'] != '[]':
        try:
            errors_data = json.loads(session['errors'])
        except:
            errors_data = [session['errors']]
    
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
    
    db = get_db_manager()
    results = []
    
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
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
    
    return jsonify({'results': [dict(row) for row in results]})


def create_app(db_path: str = "wordpress_archive.db"):
    """Create and configure the Flask application."""
    app.config['DATABASE'] = db_path
    
    # Check if database exists
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database {db_path} not found! Please run the archiver first.")
    
    return app


def run_app(host: str = '0.0.0.0', port: int = 5000, debug: bool = True):
    """Run the Flask application."""
    app = create_app()
    app.run(debug=debug, host=host, port=port) 