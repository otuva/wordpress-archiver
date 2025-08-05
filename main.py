#!/usr/bin/env python3
"""
WordPress Archiver CLI Application

A command-line tool for archiving WordPress content locally using SQLite.
Handles duplicates and preserves content changes.
"""

import argparse
import sqlite3
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List
from api import WordPressAPI


class WordPressArchiver:
    def __init__(self, db_path: str = "wordpress_archive.db"):
        """
        Initialize the WordPress archiver with SQLite database.
        
        :param db_path: Path to the SQLite database file
        """
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize the SQLite database with required tables."""
        with sqlite3.connect(self.db_path) as conn:
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
            
            conn.commit()
    
    def calculate_content_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of content for change detection."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def archive_posts(self, api: WordPressAPI, limit: Optional[int] = None) -> Dict[str, int]:
        """Archive posts from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_posts(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for post in response.data:
                    try:
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = post.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if post exists
                            cursor.execute(
                                "SELECT id, content_hash, version FROM posts WHERE wp_id = ?",
                                (post['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # Post exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO posts 
                                        (wp_id, title, content, excerpt, author_id, date_created, 
                                         date_modified, status, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        post['id'],
                                        post.get('title', {}).get('rendered', ''),
                                        content,
                                        post.get('excerpt', {}).get('rendered', ''),
                                        post.get('author', 0),
                                        post.get('date', ''),
                                        post.get('modified', ''),
                                        post.get('status', ''),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated post: {post.get('title', {}).get('rendered', 'Unknown')}")
                            else:
                                # New post
                                cursor.execute('''
                                    INSERT INTO posts 
                                    (wp_id, title, content, excerpt, author_id, date_created, 
                                     date_modified, status, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    post['id'],
                                    post.get('title', {}).get('rendered', ''),
                                    content,
                                    post.get('excerpt', {}).get('rendered', ''),
                                    post.get('author', 0),
                                    post.get('date', ''),
                                    post.get('modified', ''),
                                    post.get('status', ''),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New post: {post.get('title', {}).get('rendered', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing post {post.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during post archiving: {e}")
            stats["errors"] += 1
        
        return stats
    
    def archive_comments(self, api: WordPressAPI, limit: Optional[int] = None) -> Dict[str, int]:
        """Archive comments from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_comments(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for comment in response.data:
                    try:
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = comment.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if comment exists
                            cursor.execute(
                                "SELECT id, content_hash, version FROM comments WHERE wp_id = ?",
                                (comment['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # Comment exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO comments 
                                        (wp_id, post_id, parent_id, author_name, author_email, author_url, content, 
                                         date_created, status, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        comment['id'],
                                        comment.get('post', 0),
                                        comment.get('parent', 0),
                                        comment.get('author_name', ''),
                                        comment.get('author_email', ''),
                                        comment.get('author_url', ''),
                                        content,
                                        comment.get('date', ''),
                                        comment.get('status', ''),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated comment: {comment.get('author_name', 'Unknown')}")
                            else:
                                # New comment
                                cursor.execute('''
                                    INSERT INTO comments 
                                    (wp_id, post_id, parent_id, author_name, author_email, author_url, content, 
                                     date_created, status, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    comment['id'],
                                    comment.get('post', 0),
                                    comment.get('parent', 0),
                                    comment.get('author_name', ''),
                                    comment.get('author_email', ''),
                                    comment.get('author_url', ''),
                                    content,
                                    comment.get('date', ''),
                                    comment.get('status', ''),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New comment: {comment.get('author_name', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing comment {comment.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during comment archiving: {e}")
            stats["errors"] += 1
        
        return stats
    
    def archive_pages(self, api: WordPressAPI, limit: Optional[int] = None) -> Dict[str, int]:
        """Archive pages from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_pages(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for page_data in response.data:
                    try:
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = page_data.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if page exists
                            cursor.execute(
                                "SELECT id, content_hash, version FROM pages WHERE wp_id = ?",
                                (page_data['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # Page exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO pages 
                                        (wp_id, title, content, excerpt, author_id, date_created, 
                                         date_modified, status, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        page_data['id'],
                                        page_data.get('title', {}).get('rendered', ''),
                                        content,
                                        page_data.get('excerpt', {}).get('rendered', ''),
                                        page_data.get('author', 0),
                                        page_data.get('date', ''),
                                        page_data.get('modified', ''),
                                        page_data.get('status', ''),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated page: {page_data.get('title', {}).get('rendered', 'Unknown')}")
                            else:
                                # New page
                                cursor.execute('''
                                    INSERT INTO pages 
                                    (wp_id, title, content, excerpt, author_id, date_created, 
                                     date_modified, status, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    page_data['id'],
                                    page_data.get('title', {}).get('rendered', ''),
                                    content,
                                    page_data.get('excerpt', {}).get('rendered', ''),
                                    page_data.get('author', 0),
                                    page_data.get('date', ''),
                                    page_data.get('modified', ''),
                                    page_data.get('status', ''),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New page: {page_data.get('title', {}).get('rendered', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing page {page_data.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during page archiving: {e}")
            stats["errors"] += 1
        
        return stats
    
    def save_session_stats(self, content_type: str, stats: Dict[str, int]):
        """Save archive session statistics."""
        with sqlite3.connect(self.db_path) as conn:
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
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall archive statistics."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Get counts
            cursor.execute("SELECT COUNT(*) FROM posts")
            total_posts = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM comments")
            total_comments = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM pages")
            total_pages = cursor.fetchone()[0]
            
            # Get latest session
            cursor.execute("""
                SELECT session_date, content_type, items_processed, items_new, items_updated, errors
                FROM archive_sessions 
                ORDER BY session_date DESC 
                LIMIT 1
            """)
            latest_session = cursor.fetchone()
            
            return {
                "total_posts": total_posts,
                "total_comments": total_comments,
                "total_pages": total_pages,
                "latest_session": latest_session
            }


def main():
    parser = argparse.ArgumentParser(
        description="WordPress Content Archiver - Archive WordPress content locally using SQLite"
    )
    parser.add_argument(
        "domain",
        help="WordPress site domain (e.g., https://example.com)"
    )
    parser.add_argument(
        "--content-type",
        choices=["posts", "comments", "pages", "all"],
        default="all",
        help="Type of content to archive (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of items to process (for testing)"
    )
    parser.add_argument(
        "--db",
        default="wordpress_archive.db",
        help="SQLite database file path (default: wordpress_archive.db)"
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show archive statistics and exit"
    )
    
    args = parser.parse_args()
    
    # Initialize archiver
    archiver = WordPressArchiver(args.db)
    
    if args.stats:
        stats = archiver.get_stats()
        print("\n=== Archive Statistics ===")
        print(f"Total Posts: {stats['total_posts']}")
        print(f"Total Comments: {stats['total_comments']}")
        print(f"Total Pages: {stats['total_pages']}")
        
        if stats['latest_session']:
            session_date, content_type, processed, new, updated, errors = stats['latest_session']
            print(f"\nLatest Session ({session_date}):")
            print(f"  Content Type: {content_type}")
            print(f"  Processed: {processed}")
            print(f"  New: {new}")
            print(f"  Updated: {updated}")
            print(f"  Errors: {errors}")
        return
    
    # Initialize API
    try:
        api = WordPressAPI(args.domain)
        print(f"Connecting to WordPress site: {args.domain}")
    except Exception as e:
        print(f"Error connecting to WordPress site: {e}")
        sys.exit(1)
    
    # Archive content based on type
    content_types = []
    if args.content_type == "all":
        content_types = ["posts", "comments", "pages"]
    else:
        content_types = [args.content_type]
    
    for content_type in content_types:
        print(f"\n=== Archiving {content_type.upper()} ===")
        
        try:
            if content_type == "posts":
                stats = archiver.archive_posts(api, args.limit)
            elif content_type == "comments":
                stats = archiver.archive_comments(api, args.limit)
            elif content_type == "pages":
                stats = archiver.archive_pages(api, args.limit)
            
            # Save session stats
            archiver.save_session_stats(content_type, stats)
            
            print(f"\n{content_type.title()} Archive Summary:")
            print(f"  Processed: {stats['processed']}")
            print(f"  New: {stats['new']}")
            print(f"  Updated: {stats['updated']}")
            print(f"  Errors: {stats['errors']}")
            
        except Exception as e:
            print(f"Error archiving {content_type}: {e}")
    
    print(f"\nArchive completed! Database: {args.db}")


if __name__ == "__main__":
    main()
