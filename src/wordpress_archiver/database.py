"""
Database Management Module

Handles SQLite database operations, schema creation, and connection management.
"""

import sqlite3
import json
import logging
from typing import Dict, Any, Optional
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database operations and schema."""
    
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
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize the SQLite database with required tables."""
        logger.info(f"Initializing database: {self.db_path}")
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Posts table
            cursor.execute('''
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
            ''')
            
            # Comments table
            cursor.execute('''
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
            ''')
            
            # Pages table
            cursor.execute('''
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
            ''')
            
            # Archive sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS archive_sessions (
                    id INTEGER PRIMARY KEY,
                    session_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    content_type TEXT,
                    items_processed INTEGER,
                    items_new INTEGER,
                    items_updated INTEGER,
                    errors TEXT
                )
            ''')
            
            # Users table
            cursor.execute('''
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
            ''')
            
            # Categories table
            cursor.execute('''
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
            ''')
            
            # Tags table
            cursor.execute('''
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
            ''')
            
            # Create indexes for better performance
            self._create_indexes(cursor)
            
            conn.commit()
            logger.info("Database schema initialized successfully")
    
    def _create_indexes(self, cursor):
        """Create database indexes for better query performance."""
        indexes = [
            ("idx_posts_wp_id", "posts", "wp_id"),
            ("idx_posts_date_created", "posts", "date_created"),
            ("idx_comments_wp_id", "comments", "wp_id"),
            ("idx_comments_post_id", "comments", "post_id"),
            ("idx_comments_date_created", "comments", "date_created"),
            ("idx_pages_wp_id", "pages", "wp_id"),
            ("idx_pages_date_created", "pages", "date_created"),
            ("idx_users_wp_id", "users", "wp_id"),
            ("idx_categories_wp_id", "categories", "wp_id"),
            ("idx_tags_wp_id", "tags", "wp_id"),
            ("idx_sessions_date", "archive_sessions", "session_date"),
        ]
        
        for index_name, table, column in indexes:
            try:
                cursor.execute(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} ({column})")
            except sqlite3.OperationalError:
                # Index might already exist
                pass
    
    def save_session_stats(self, content_type: str, stats: Dict[str, int]):
        """Save archive session statistics."""
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
        """Save comprehensive session statistics for a complete archive operation."""
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
        """Save a session for failed WordPress verification."""
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
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall archive statistics."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get counts for each content type
            tables = ['posts', 'comments', 'pages', 'users', 'categories', 'tags']
            stats = {}
            
            for table in tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[f"total_{table}"] = cursor.fetchone()[0]
            
            # Get latest session
            cursor.execute("""
                SELECT id, session_date, content_type, items_processed, 
                       items_new, items_updated, errors
                FROM archive_sessions 
                ORDER BY session_date DESC 
                LIMIT 1
            """)
            latest_session = cursor.fetchone()
            stats['latest_session'] = latest_session
            
            return stats
    
    def get_content_versions(self, content_type: str, wp_id: int) -> list:
        """Get all versions of a specific content item."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM {content_type} 
                WHERE wp_id = ? 
                ORDER BY version DESC
            """, (wp_id,))
            return cursor.fetchall()
    
    def get_latest_version(self, content_type: str, wp_id: int) -> Optional[sqlite3.Row]:
        """Get the latest version of a specific content item."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT * FROM {content_type} 
                WHERE wp_id = ? 
                ORDER BY version DESC 
                LIMIT 1
            """, (wp_id,))
            return cursor.fetchone()
    
    def content_exists(self, content_type: str, wp_id: int) -> bool:
        """Check if content exists in the database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT 1 FROM {content_type} WHERE wp_id = ? LIMIT 1", (wp_id,))
            return cursor.fetchone() is not None
    
    def get_content_hash(self, content_type: str, wp_id: int) -> Optional[str]:
        """Get the content hash of the latest version."""
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
    
    def insert_content(self, content_type: str, data: Dict[str, Any], version: int = 1):
        """Insert new content into the database."""
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