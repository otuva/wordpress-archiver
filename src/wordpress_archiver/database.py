"""
Database Management Module

Handles SQLite database operations, schema creation, and connection management
for the WordPress archiver. Provides a clean interface for storing and retrieving
archived WordPress content with version tracking and change detection.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, Optional, List
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE SCHEMA DEFINITIONS
# =============================================================================

POSTS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        title TEXT,
        content TEXT,
        excerpt TEXT,
        author_id INTEGER,
        date_created TEXT,
        date_modified TEXT,
        status TEXT,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version)
    )
'''

COMMENTS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS comments (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        post_id INTEGER,
        parent_id INTEGER,
        author_name TEXT,
        author_email TEXT,
        author_url TEXT,
        content TEXT,
        date_created TEXT,
        status TEXT,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version),
        FOREIGN KEY (post_id) REFERENCES posts (wp_id),
        FOREIGN KEY (parent_id) REFERENCES comments (wp_id)
    )
'''

PAGES_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        title TEXT,
        content TEXT,
        excerpt TEXT,
        author_id INTEGER,
        date_created TEXT,
        date_modified TEXT,
        status TEXT,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version)
    )
'''

USERS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        name TEXT,
        url TEXT,
        description TEXT,
        link TEXT,
        slug TEXT,
        avatar_urls TEXT,
        mpp_avatar TEXT,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version)
    )
'''

CATEGORIES_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        name TEXT,
        description TEXT,
        link TEXT,
        slug TEXT,
        taxonomy TEXT,
        parent INTEGER,
        count INTEGER,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version)
    )
'''

TAGS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS tags (
        id INTEGER PRIMARY KEY,
        wp_id INTEGER,
        name TEXT,
        description TEXT,
        link TEXT,
        slug TEXT,
        taxonomy TEXT,
        count INTEGER,
        content_hash TEXT,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(wp_id, version)
    )
'''

SESSIONS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS archive_sessions (
        id INTEGER PRIMARY KEY,
        session_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        content_type TEXT,
        items_processed INTEGER,
        items_new INTEGER,
        items_updated INTEGER,
        errors TEXT
    )
'''

POST_CATEGORIES_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS post_categories (
        id INTEGER PRIMARY KEY,
        post_wp_id INTEGER,
        category_wp_id INTEGER,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_wp_id, category_wp_id, version),
        FOREIGN KEY (post_wp_id) REFERENCES posts (wp_id)
    )
'''

POST_TAGS_TABLE_SCHEMA = '''
    CREATE TABLE IF NOT EXISTS post_tags (
        id INTEGER PRIMARY KEY,
        post_wp_id INTEGER,
        tag_wp_id INTEGER,
        version INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(post_wp_id, tag_wp_id, version),
        FOREIGN KEY (post_wp_id) REFERENCES posts (wp_id)
    )
'''

# =============================================================================
# DATABASE INDEXES
# =============================================================================

DATABASE_INDEXES = [
    ("idx_posts_wp_id", "posts", "wp_id"),
    ("idx_posts_date_created", "posts", "date_created"),
    ("idx_comments_wp_id", "comments", "wp_id"),
    ("idx_comments_post_id", "comments", "post_id"),
    ("idx_comments_parent_id", "comments", "parent_id"),
    ("idx_comments_date_created", "comments", "date_created"),
    ("idx_pages_wp_id", "pages", "wp_id"),
    ("idx_pages_date_created", "pages", "date_created"),
    ("idx_users_wp_id", "users", "wp_id"),
    ("idx_categories_wp_id", "categories", "wp_id"),
    ("idx_tags_wp_id", "tags", "wp_id"),
    ("idx_sessions_date", "archive_sessions", "session_date"),
    ("idx_post_categories_post", "post_categories", "post_wp_id"),
    ("idx_post_categories_category", "post_categories", "category_wp_id"),
    ("idx_post_tags_post", "post_tags", "post_wp_id"),
    ("idx_post_tags_tag", "post_tags", "tag_wp_id"),
]

# =============================================================================
# DATABASE MANAGER CLASS
# =============================================================================

class DatabaseManager:
    """
    Manages SQLite database operations and schema for WordPress content archiving.
    
    Provides methods for:
    - Database initialization and schema creation
    - Content insertion and retrieval
    - Version tracking and change detection
    - Session management and statistics
    """
    
    def __init__(self, db_path: str):
        """
        Initialize database manager.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.
        
        Yields:
            SQLite connection with row factory configured
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize the SQLite database with required tables and indexes."""
        logger.info(f"Initializing database: {self.db_path}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Create tables
            self._create_tables(cursor)
            
            # Create indexes
            self._create_indexes(cursor)
            
            conn.commit()
            
        logger.info("Database schema initialized successfully")
    
    def _create_tables(self, cursor):
        """Create all database tables."""
        schemas = [
            POSTS_TABLE_SCHEMA,
            COMMENTS_TABLE_SCHEMA,
            PAGES_TABLE_SCHEMA,
            USERS_TABLE_SCHEMA,
            CATEGORIES_TABLE_SCHEMA,
            TAGS_TABLE_SCHEMA,
            SESSIONS_TABLE_SCHEMA,
            POST_CATEGORIES_TABLE_SCHEMA,
            POST_TAGS_TABLE_SCHEMA,
        ]
        
        for schema in schemas:
            cursor.execute(schema)
    
    def _create_indexes(self, cursor):
        """Create database indexes for better query performance."""
        for index_name, table, column in DATABASE_INDEXES:
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")
            except sqlite3.OperationalError:
                # Index might already exist
                pass
    
    # =============================================================================
    # CONTENT OPERATIONS
    # =============================================================================
    
    def content_exists(self, content_type: str, wp_id: int) -> bool:
        """
        Check if content exists in the database.
        
        Args:
            content_type: Type of content (posts, comments, pages, etc.)
            wp_id: WordPress ID of the content
            
        Returns:
            True if content exists, False otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT 1 FROM {content_type} WHERE wp_id = ? LIMIT 1", (wp_id,))
            return cursor.fetchone() is not None
    
    def get_content_hash(self, content_type: str, wp_id: int) -> Optional[str]:
        """
        Get the content hash of the latest version.
        
        Args:
            content_type: Type of content (posts, comments, pages, etc.)
            wp_id: WordPress ID of the content
            
        Returns:
            Content hash string or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT content_hash FROM {content_type} 
                WHERE wp_id = ? 
                ORDER BY version DESC 
                LIMIT 1
            """, (wp_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    
    def get_content_versions(self, content_type: str, wp_id: int) -> List[Dict[str, Any]]:
        """
        Get all versions of a specific content item.
        
        Args:
            content_type: Type of content (posts, comments, pages, etc.)
            wp_id: WordPress ID of the content
            
        Returns:
            List of content versions as dictionaries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM {content_type} 
                WHERE wp_id = ? 
                ORDER BY version DESC 
            """, (wp_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    def get_latest_version(self, content_type: str, wp_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the latest version of a specific content item.
        
        Args:
            content_type: Type of content (posts, comments, pages, etc.)
            wp_id: WordPress ID of the content
            
        Returns:
            Latest version as dictionary or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM {content_type} 
                WHERE wp_id = ? 
                ORDER BY version DESC 
                LIMIT 1
            """, (wp_id,))
            result = cursor.fetchone()
            return dict(result) if result else None
    
    def insert_content(self, content_type: str, data: Dict[str, Any], version: int = 1):
        """
        Insert new content into the database.
        
        Args:
            content_type: Type of content (posts, comments, pages, etc.)
            data: Content data dictionary
            version: Version number (default: 1)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if content_type == 'posts':
                cursor.execute('''
                    INSERT INTO posts 
                    (wp_id, title, content, excerpt, author_id, date_created, 
                     date_modified, status, content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['title'], data['content'], data['excerpt'],
                    data['author_id'], data['date_created'], data['date_modified'],
                    data['status'], data['content_hash'], version
                ))
                
                # Save post-category relationships
                category_ids = data.get('categories', [])
                if category_ids:
                    for category_id in category_ids:
                        try:
                            cursor.execute('''
                                INSERT OR IGNORE INTO post_categories 
                                (post_wp_id, category_wp_id, version)
                                VALUES (?, ?, ?)
                            ''', (data['wp_id'], category_id, version))
                        except sqlite3.IntegrityError:
                            # Relationship already exists for this version
                            pass
                
                # Save post-tag relationships
                tag_ids = data.get('tags', [])
                if tag_ids:
                    for tag_id in tag_ids:
                        try:
                            cursor.execute('''
                                INSERT OR IGNORE INTO post_tags 
                                (post_wp_id, tag_wp_id, version)
                                VALUES (?, ?, ?)
                            ''', (data['wp_id'], tag_id, version))
                        except sqlite3.IntegrityError:
                            # Relationship already exists for this version
                            pass
            elif content_type == 'comments':
                cursor.execute('''
                    INSERT INTO comments 
                    (wp_id, post_id, parent_id, author_name, author_email, author_url, 
                     content, date_created, status, content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['post_id'], data['parent_id'],
                    data['author_name'], data['author_email'], data['author_url'],
                    data['content'], data['date_created'], data['status'],
                    data['content_hash'], version
                ))
            elif content_type == 'pages':
                cursor.execute('''
                    INSERT INTO pages 
                    (wp_id, title, content, excerpt, author_id, date_created, 
                     date_modified, status, content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['title'], data['content'], data['excerpt'],
                    data['author_id'], data['date_created'], data['date_modified'],
                    data['status'], data['content_hash'], version
                ))
            elif content_type == 'users':
                cursor.execute('''
                    INSERT INTO users 
                    (wp_id, name, url, description, link, slug, avatar_urls, 
                     mpp_avatar, content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['name'], data['url'], data['description'],
                    data['link'], data['slug'], data['avatar_urls'],
                    data['mpp_avatar'], data['content_hash'], version
                ))
            elif content_type == 'categories':
                cursor.execute('''
                    INSERT INTO categories 
                    (wp_id, name, description, link, slug, taxonomy, parent, 
                     count, content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['name'], data['description'], data['link'],
                    data['slug'], data['taxonomy'], data['parent'], data['count'],
                    data['content_hash'], version
                ))
            elif content_type == 'tags':
                cursor.execute('''
                    INSERT INTO tags 
                    (wp_id, name, description, link, slug, taxonomy, count, 
                     content_hash, version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    data['wp_id'], data['name'], data['description'], data['link'],
                    data['slug'], data['taxonomy'], data['count'],
                    data['content_hash'], version
                ))
            
            conn.commit()
    
    # =============================================================================
    # POST RELATIONSHIPS (CATEGORIES AND TAGS)
    # =============================================================================
    
    def get_post_categories(self, post_wp_id: int, version: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get categories for a specific post.
        
        Args:
            post_wp_id: WordPress post ID
            version: Specific version (if None, gets latest version)
            
        Returns:
            List of category dictionaries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if version is None:
                # Get latest version of post
                latest_post = self.get_latest_version('posts', post_wp_id)
                if not latest_post:
                    return []
                version = latest_post['version']
            
            # Get category IDs for this post version
            cursor.execute('''
                SELECT category_wp_id 
                FROM post_categories 
                WHERE post_wp_id = ? AND version = ?
            ''', (post_wp_id, version))
            category_ids = [row[0] for row in cursor.fetchall()]
            
            if not category_ids:
                return []
            
            # Get category details
            placeholders = ','.join(['?'] * len(category_ids))
            cursor.execute(f'''
                SELECT wp_id, name, description, link, slug, taxonomy, parent, count
                FROM categories
                WHERE wp_id IN ({placeholders})
                ORDER BY name ASC
            ''', category_ids)
            
            categories = []
            for row in cursor.fetchall():
                categories.append({
                    'wp_id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'link': row[3],
                    'slug': row[4],
                    'taxonomy': row[5],
                    'parent': row[6],
                    'count': row[7]
                })
            
            return categories
    
    def get_post_tags(self, post_wp_id: int, version: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get tags for a specific post.
        
        Args:
            post_wp_id: WordPress post ID
            version: Specific version (if None, gets latest version)
            
        Returns:
            List of tag dictionaries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            if version is None:
                # Get latest version of post
                latest_post = self.get_latest_version('posts', post_wp_id)
                if not latest_post:
                    return []
                version = latest_post['version']
            
            # Get tag IDs for this post version
            cursor.execute('''
                SELECT tag_wp_id 
                FROM post_tags 
                WHERE post_wp_id = ? AND version = ?
            ''', (post_wp_id, version))
            tag_ids = [row[0] for row in cursor.fetchall()]
            
            if not tag_ids:
                return []
            
            # Get tag details
            placeholders = ','.join(['?'] * len(tag_ids))
            cursor.execute(f'''
                SELECT wp_id, name, description, link, slug, taxonomy, count
                FROM tags
                WHERE wp_id IN ({placeholders})
                ORDER BY name ASC
            ''', tag_ids)
            
            tags = []
            for row in cursor.fetchall():
                tags.append({
                    'wp_id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'link': row[3],
                    'slug': row[4],
                    'taxonomy': row[5],
                    'count': row[6]
                })
            
            return tags
    
    def get_posts_by_category(self, category_wp_id: int, page: int = 1, per_page: int = 10) -> tuple:
        """
        Get posts for a specific category with pagination.
        
        Args:
            category_wp_id: WordPress category ID
            page: Page number (1-based)
            per_page: Number of posts per page
            
        Returns:
            Tuple of (posts_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count of posts with this category
            cursor.execute('''
                SELECT COUNT(DISTINCT p.wp_id)
                FROM posts p
                INNER JOIN post_categories pc ON p.wp_id = pc.post_wp_id
                WHERE pc.category_wp_id = ?
                AND p.version = (
                    SELECT MAX(version) FROM posts WHERE wp_id = p.wp_id
                )
            ''', (category_wp_id,))
            total_posts = cursor.fetchone()[0]
            
            # Get posts for current page
            cursor.execute('''
                SELECT DISTINCT p.wp_id, p.title, p.excerpt, p.author_id, 
                       p.date_created, p.date_modified, p.status, p.version, p.created_at
                FROM posts p
                INNER JOIN post_categories pc ON p.wp_id = pc.post_wp_id
                WHERE pc.category_wp_id = ?
                AND p.version = (
                    SELECT MAX(version) FROM posts WHERE wp_id = p.wp_id
                )
                ORDER BY p.date_created DESC
                LIMIT ? OFFSET ?
            ''', (category_wp_id, per_page, offset))
            posts = cursor.fetchall()
        
        total_pages = (total_posts + per_page - 1) // per_page
        return posts, total_posts, total_pages
    
    def get_posts_by_tag(self, tag_wp_id: int, page: int = 1, per_page: int = 10) -> tuple:
        """
        Get posts for a specific tag with pagination.
        
        Args:
            tag_wp_id: WordPress tag ID
            page: Page number (1-based)
            per_page: Number of posts per page
            
        Returns:
            Tuple of (posts_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count of posts with this tag
            cursor.execute('''
                SELECT COUNT(DISTINCT p.wp_id)
                FROM posts p
                INNER JOIN post_tags pt ON p.wp_id = pt.post_wp_id
                WHERE pt.tag_wp_id = ?
                AND p.version = (
                    SELECT MAX(version) FROM posts WHERE wp_id = p.wp_id
                )
            ''', (tag_wp_id,))
            total_posts = cursor.fetchone()[0]
            
            # Get posts for current page
            cursor.execute('''
                SELECT DISTINCT p.wp_id, p.title, p.excerpt, p.author_id, 
                       p.date_created, p.date_modified, p.status, p.version, p.created_at
                FROM posts p
                INNER JOIN post_tags pt ON p.wp_id = pt.post_wp_id
                WHERE pt.tag_wp_id = ?
                AND p.version = (
                    SELECT MAX(version) FROM posts WHERE wp_id = p.wp_id
                )
                ORDER BY p.date_created DESC
                LIMIT ? OFFSET ?
            ''', (tag_wp_id, per_page, offset))
            posts = cursor.fetchall()
        
        total_pages = (total_posts + per_page - 1) // per_page
        return posts, total_posts, total_pages
    
    # =============================================================================
    # SESSION MANAGEMENT
    # =============================================================================
    
    def save_session_stats(self, content_type: str, stats: Dict[str, int]):
        """
        Save archive session statistics.
        
        Args:
            content_type: Type of content archived
            stats: Statistics dictionary with processed, new, updated, errors
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO archive_sessions 
                (content_type, items_processed, items_new, items_updated, errors)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                content_type,
                stats["processed"],
                stats["new"],
                stats["updated"],
                json.dumps([]) if stats["errors"] == 0 else json.dumps(["Errors occurred"])
            ))
            conn.commit()
    
    def save_comprehensive_session_stats(self, domain: str, content_types: list, 
                                       all_stats: Dict[str, Dict[str, int]], interrupted: bool = False):
        """
        Save comprehensive session statistics for a complete archive operation.
        
        Args:
            domain: WordPress domain being archived
            content_types: List of content types processed
            all_stats: Dictionary of statistics for each content type
            interrupted: Whether the operation was interrupted
        """
        total_processed = sum(stats["processed"] for stats in all_stats.values())
        total_new = sum(stats["new"] for stats in all_stats.values())
        total_updated = sum(stats["updated"] for stats in all_stats.values())
        total_errors = sum(stats["errors"] for stats in all_stats.values())
        
        # Create a summary of what was archived
        content_summary = []
        for content_type, stats in all_stats.items():
            if stats["processed"] > 0:
                content_summary.append(
                    f"{content_type}: {stats['processed']} processed, "
                    f"{stats['new']} new, {stats['updated']} updated"
                )
        
        if interrupted:
            session_description = f"INTERRUPTED - Archive of {domain} - {', '.join(content_types)}"
        else:
            session_description = f"Archive of {domain} - {', '.join(content_types)}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO archive_sessions 
                (content_type, items_processed, items_new, items_updated, errors)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                session_description,
                total_processed,
                total_new,
                total_updated,
                json.dumps(content_summary) if total_errors == 0 
                else json.dumps(content_summary + ["Errors occurred"])
            ))
            conn.commit()
    
    def save_failed_verification_session(self, domain: str, reason: str):
        """
        Save a session for failed WordPress verification.
        
        Args:
            domain: WordPress domain that failed verification
            reason: Reason for verification failure
        """
        session_description = f"FAILED VERIFICATION - {domain} - {reason}"
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO archive_sessions 
                (content_type, items_processed, items_new, items_updated, errors)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                session_description,
                0,  # No items processed
                0,  # No new items
                0,  # No updated items
                json.dumps([f"Verification failed: {reason}"])
            ))
            conn.commit()
    
    # =============================================================================
    # STATISTICS AND REPORTING
    # =============================================================================
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive archive statistics.
        
        Returns:
            Dictionary containing various statistics about the archive
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get counts for each content type
            tables = ['posts', 'comments', 'pages', 'users', 'categories', 'tags']
            stats = {}
            
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f'total_{table}'] = cursor.fetchone()[0]
            
            # Get session statistics
            cursor.execute("SELECT COUNT(*) FROM archive_sessions")
            stats['total_sessions'] = cursor.fetchone()[0]
            
            # Get recent sessions
            cursor.execute("""
                SELECT content_type, items_processed, session_date
                FROM archive_sessions 
                ORDER BY session_date DESC 
                LIMIT 10
            """)
            stats['recent_sessions'] = [dict(row) for row in cursor.fetchall()]
            
            # Get last updated timestamp
            cursor.execute("""
                SELECT MAX(created_at) as last_updated
                FROM (
                    SELECT created_at FROM posts
                    UNION ALL
                    SELECT created_at FROM comments
                    UNION ALL
                    SELECT created_at FROM pages
                    UNION ALL
                    SELECT created_at FROM users
                    UNION ALL
                    SELECT created_at FROM categories
                    UNION ALL
                    SELECT created_at FROM tags
                )
            """)
            result = cursor.fetchone()
            stats['last_updated'] = result[0] if result and result[0] else None
            
            return stats
    
    # =============================================================================
    # WEB APP DATABASE OPERATIONS
    # =============================================================================
    
    def get_paginated_posts(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated posts with optional search.
        
        Args:
            page: Page number (1-based)
            per_page: Number of posts per page
            search: Search term for title/content
            
        Returns:
            Tuple of (posts_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build search query
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
        return posts, total_posts, total_pages
    
    def get_paginated_comments(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated comments with optimized performance.
        
        Args:
            page: Page number (1-based)
            per_page: Number of comments per page
            search: Search term for author/content
            
        Returns:
            Tuple of (comments_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Apply SQLite optimizations
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = 10000")
            conn.execute("PRAGMA synchronous = NORMAL")
            
            # Build search query
            where_clause = ""
            params = []
            if search:
                where_clause = "WHERE c.author_name LIKE ? OR c.content LIKE ?"
                params = [f'%{search}%', f'%{search}%']
            
            # Get total count
            cursor.execute(f"SELECT COUNT(*) FROM comments c {where_clause}", params)
            total_comments = cursor.fetchone()[0]
            
            # Get comments with optimized query strategy
            query, query_params = self._build_comments_query(search, per_page, offset)
            
            # Execute query
            cursor.execute(query, query_params)
            paginated_comments = cursor.fetchall()
            
            # Process results
            processed_comments = self._process_comments(paginated_comments, search)
        
        total_pages = (total_comments + per_page - 1) // per_page
        return processed_comments, total_comments, total_pages
    
    def get_paginated_pages(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated pages with optional search.
        
        Args:
            page: Page number (1-based)
            per_page: Number of pages per page
            search: Search term for title/content
            
        Returns:
            Tuple of (pages_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build search query
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
        return pages, total_pages_count, total_pages
    
    def get_paginated_users(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated users with optional search.
        
        Args:
            page: Page number (1-based)
            per_page: Number of users per page
            search: Search term for name/description
            
        Returns:
            Tuple of (users_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build search query
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
                SELECT wp_id, name, url, description, link, slug, avatar_urls, 
                       mpp_avatar, version, created_at
                FROM users 
                {where_clause}
                ORDER BY name ASC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [per_page, offset])
            users = cursor.fetchall()
        
        total_pages = (total_users + per_page - 1) // per_page
        return users, total_users, total_pages
    
    def get_paginated_categories(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated categories with optional search.
        
        Args:
            page: Page number (1-based)
            per_page: Number of categories per page
            search: Search term for name/description
            
        Returns:
            Tuple of (categories_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build search query
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
                SELECT wp_id, name, description, link, slug, taxonomy, parent, 
                       count, version, created_at
                FROM categories 
                {where_clause}
                ORDER BY name ASC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [per_page, offset])
            categories = cursor.fetchall()
        
        total_pages = (total_categories + per_page - 1) // per_page
        return categories, total_categories, total_pages
    
    def get_paginated_tags(self, page: int, per_page: int, search: str = "") -> tuple:
        """
        Get paginated tags with optional search.
        
        Args:
            page: Page number (1-based)
            per_page: Number of tags per page
            search: Search term for name/description
            
        Returns:
            Tuple of (tags_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Build search query
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
                SELECT wp_id, name, description, link, slug, taxonomy, count, 
                       version, created_at
                FROM tags 
                {where_clause}
                ORDER BY name ASC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, params + [per_page, offset])
            tags = cursor.fetchall()
        
        total_pages = (total_tags + per_page - 1) // per_page
        return tags, total_tags, total_pages
    
    def get_paginated_sessions(self, page: int, per_page: int) -> tuple:
        """
        Get paginated archive sessions.
        
        Args:
            page: Page number (1-based)
            per_page: Number of sessions per page
            
        Returns:
            Tuple of (sessions_list, total_count, total_pages)
        """
        offset = (page - 1) * per_page
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute("SELECT COUNT(*) FROM archive_sessions")
            total_sessions = cursor.fetchone()[0]
            
            # Get sessions for current page
            query = """
                SELECT id, content_type, items_processed, items_new, items_updated, 
                       errors, session_date
                FROM archive_sessions 
                ORDER BY session_date DESC
                LIMIT ? OFFSET ?
            """
            cursor.execute(query, [per_page, offset])
            sessions = cursor.fetchall()
        
        total_pages = (total_sessions + per_page - 1) // per_page
        return sessions, total_sessions, total_pages
    
    def get_session_by_id(self, session_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific archive session by ID.
        
        Args:
            session_id: Archive session ID
            
        Returns:
            Session data as dictionary or None if not found
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, content_type, items_processed, items_new, items_updated, 
                       errors, session_date
                FROM archive_sessions 
                WHERE id = ?
            """, (session_id,))
            session = cursor.fetchone()
            
            return dict(session) if session else None
    
    def get_post_comments(self, wp_id: int) -> List[Dict[str, Any]]:
        """
        Get comments for a specific post with proper threading.
        
        Args:
            wp_id: WordPress post ID
            
        Returns:
            List of comments with proper threading levels
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wp_id, author_name, author_email, author_url, content, 
                       date_created, status, version, parent_id
                FROM comments 
                WHERE post_id = ?
                ORDER BY date_created ASC
            """, (wp_id,))
            all_comments = cursor.fetchall()
            
            # Convert to list of dicts
            comment_dicts = []
            for comment in all_comments:
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
            comment_tree = self._build_comment_tree(comment_dicts)
            
            # Flatten the tree for display
            return self._flatten_comment_tree(comment_tree)
    
    # =============================================================================
    # PRIVATE HELPER METHODS
    # =============================================================================
    
    def _build_comments_query(self, search: str, per_page: int, offset: int) -> tuple:
        """
        Build the appropriate comments query based on search requirements.
        
        Args:
            search: Search term
            per_page: Number of comments per page
            offset: Query offset
            
        Returns:
            Tuple of (query_string, query_parameters)
        """
        if search:
            # Use recursive CTE for search queries
            query = """
                WITH RECURSIVE comment_tree AS (
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
                ORDER BY sort_order DESC, level ASC
                LIMIT ? OFFSET ?
            """
            query_params = [f'%{search}%', f'%{search}%', f'%{search}%', f'%{search}%', per_page, offset]
        else:
            # Use simple query for better performance
            query = """
                SELECT 
                    c.wp_id, c.author_name, c.author_email, c.author_url, c.content, 
                    c.date_created, c.status, c.version, c.parent_id, 
                    p.title as post_title, p.wp_id as post_id
                FROM comments c
                LEFT JOIN posts p ON c.post_id = p.wp_id
                ORDER BY c.date_created DESC
                LIMIT ? OFFSET ?
            """
            query_params = [per_page * 3, offset]  # Get more comments to account for threading
        
        return query, query_params
    
    def _process_comments(self, paginated_comments: List[tuple], search: str) -> List[Dict[str, Any]]:
        """
        Process raw comment data into structured format.
        
        Args:
            paginated_comments: Raw comment data from database
            search: Search term (if any)
            
        Returns:
            Processed comments with proper structure
        """
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
                'post_id': comment[10]
            })
        
        # Calculate levels efficiently for non-search queries
        if not search:
            self._calculate_comment_levels(comments)
        else:
            # For search queries, use the level from recursive CTE
            for comment in comments:
                comment['level'] = comment[11] if len(comment) > 11 else 0
        
        return comments
    
    def _build_comment_tree(self, comments: List[Dict], parent_id: Optional[int] = None) -> List[Dict]:
        """
        Build a hierarchical comment tree.
        
        Args:
            comments: List of comment dictionaries
            parent_id: Parent comment ID to filter by
            
        Returns:
            Hierarchical comment tree
        """
        tree = []
        for comment in comments:
            if comment['parent_id'] == parent_id:
                comment['replies'] = self._build_comment_tree(comments, comment['wp_id'])
                tree.append(comment)
        return tree
    
    def _flatten_comment_tree(self, tree: List[Dict], level: int = 0) -> List[Dict]:
        """
        Flatten a comment tree for display (depth-first traversal).
        
        Args:
            tree: Comment tree to flatten
            level: Current nesting level
            
        Returns:
            Flattened list of comments with levels
        """
        flattened = []
        for comment in tree:
            comment['level'] = level
            flattened.append(comment)
            if comment['replies']:
                flattened.extend(self._flatten_comment_tree(comment['replies'], level + 1))
        return flattened
    
    def _calculate_comment_levels(self, comments: List[Dict[str, Any]]):
        """
        Calculate comment nesting levels efficiently.
        
        Args:
            comments: List of comment dictionaries to process
        """
        comment_dict = {c['wp_id']: c for c in comments}
        for comment in comments:
            level = 0
            current_parent = comment['parent_id']
            while current_parent and current_parent in comment_dict:
                level += 1
                current_parent = comment_dict[current_parent]['parent_id']
            comment['level'] = level 