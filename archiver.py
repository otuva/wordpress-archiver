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
import signal
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
            
            conn.commit()
    
    def calculate_content_hash(self, content: str) -> str:
        """Calculate SHA-256 hash of normalized content for change detection."""
        normalized_content = self.normalize_content(content)
        return hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    def normalize_content(self, content: str) -> str:
        """
        Normalize content by removing dynamic elements that change between requests.
        
        :param content: Raw HTML content from WordPress
        :return: Normalized content for consistent hashing
        """
        if not content:
            return ""
        
        # Remove ShareThis widgets and similar dynamic social sharing elements
        import re
        import html
        
        # Remove ShareThis inline share buttons
        content = re.sub(
            r'<div[^>]*class="[^"]*sharethis[^"]*"[^>]*>.*?</div>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # Remove other common dynamic social sharing widgets
        content = re.sub(
            r'<div[^>]*class="[^"]*(?:social-share|share-buttons|social-media)[^"]*"[^>]*>.*?</div>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # Remove dynamic ad elements
        content = re.sub(
            r'<div[^>]*class="[^"]*(?:adsbygoogle|advertisement|ad-container)[^"]*"[^>]*>.*?</div>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # Remove script tags that might contain dynamic content
        content = re.sub(
            r'<script[^>]*>.*?</script>',
            '',
            content,
            flags=re.DOTALL | re.IGNORECASE
        )
        
        # Remove inline styles that might be dynamically generated
        content = re.sub(
            r'style="[^"]*"',
            '',
            content
        )
        
        # Remove data attributes that might be dynamic
        content = re.sub(
            r'data-[^=]*="[^"]*"',
            '',
            content
        )
        
        # Remove empty divs and spans that might be left after cleaning
        content = re.sub(
            r'<div[^>]*>\s*</div>',
            '',
            content
        )
        content = re.sub(
            r'<span[^>]*>\s*</span>',
            '',
            content
        )
        
        # Normalize HTML entities (convert all to decimal format)
        # First, decode all HTML entities to their actual characters
        content = html.unescape(content)
        
        # Then re-encode them consistently (this will use decimal format)
        # We need to handle this manually since html.escape() doesn't give us control
        # over the format, so we'll just leave them decoded for now
        
        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content)
        content = content.strip()
        
        return content
    
    def is_date_after_filter(self, item_date: str, after_date: Optional[datetime]) -> bool:
        """
        Check if an item's date is after the filter date.
        
        :param item_date: ISO format date string from WordPress
        :param after_date: Filter date to compare against
        :return: True if item should be included, False otherwise
        """
        if not after_date:
            return True
        
        try:
            # Parse the WordPress date (ISO format)
            item_datetime = datetime.fromisoformat(item_date.replace('Z', '+00:00'))
            return item_datetime >= after_date
        except (ValueError, AttributeError):
            # If date parsing fails, include the item to be safe
            return True
    
    def archive_posts(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
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
                        # Check if post date is after the filter date
                        post_date = post.get('date', '')
                        if not self.is_date_after_filter(post_date, after_date):
                            continue
                        
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = post.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if post exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM posts WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
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
    
    def archive_comments(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
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
                        # Check if comment date is after the filter date
                        comment_date = comment.get('date', '')
                        if not self.is_date_after_filter(comment_date, after_date):
                            continue
                        
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = comment.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if comment exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM comments WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
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
    
    def archive_pages(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
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
                        # Check if page date is after the filter date
                        page_date = page_data.get('date', '')
                        if not self.is_date_after_filter(page_date, after_date):
                            continue
                        
                        stats["processed"] += 1
                        
                        # Calculate content hash
                        content = page_data.get('content', {}).get('rendered', '')
                        content_hash = self.calculate_content_hash(content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if page exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM pages WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
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
    
    def archive_users(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
        """Archive users from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_users(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for user in response.data:
                    try:
                        # For users, we don't have a reliable date field, so we'll include all users
                        # when after_date is specified (users are typically created once)
                        stats["processed"] += 1
                        
                        # Calculate content hash from user data
                        user_content = f"{user.get('name', '')}{user.get('description', '')}{user.get('url', '')}"
                        content_hash = self.calculate_content_hash(user_content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if user exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM users WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
                                (user['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # User exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO users 
                                        (wp_id, name, url, description, link, slug, avatar_urls, mpp_avatar, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        user['id'],
                                        user.get('name', ''),
                                        user.get('url', ''),
                                        user.get('description', ''),
                                        user.get('link', ''),
                                        user.get('slug', ''),
                                        json.dumps(user.get('avatar_urls', {})),
                                        json.dumps(user.get('mpp_avatar', {})),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated user: {user.get('name', 'Unknown')}")
                            else:
                                # New user
                                cursor.execute('''
                                    INSERT INTO users 
                                    (wp_id, name, url, description, link, slug, avatar_urls, mpp_avatar, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    user['id'],
                                    user.get('name', ''),
                                    user.get('url', ''),
                                    user.get('description', ''),
                                    user.get('link', ''),
                                    user.get('slug', ''),
                                    json.dumps(user.get('avatar_urls', {})),
                                    json.dumps(user.get('mpp_avatar', {})),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New user: {user.get('name', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing user {user.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during user archiving: {e}")
            stats["errors"] += 1
        
        return stats
    
    def archive_categories(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
        """Archive categories from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_categories(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for category in response.data:
                    try:
                        # For categories, we don't have a reliable date field, so we'll include all categories
                        # when after_date is specified (categories are typically created once)
                        stats["processed"] += 1
                        
                        # Calculate content hash from category data
                        category_content = f"{category.get('name', '')}{category.get('description', '')}{category.get('slug', '')}"
                        content_hash = self.calculate_content_hash(category_content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if category exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM categories WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
                                (category['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # Category exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO categories 
                                        (wp_id, name, description, link, slug, taxonomy, parent, count, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        category['id'],
                                        category.get('name', ''),
                                        category.get('description', ''),
                                        category.get('link', ''),
                                        category.get('slug', ''),
                                        category.get('taxonomy', ''),
                                        category.get('parent', 0),
                                        category.get('count', 0),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated category: {category.get('name', 'Unknown')}")
                            else:
                                # New category
                                cursor.execute('''
                                    INSERT INTO categories 
                                    (wp_id, name, description, link, slug, taxonomy, parent, count, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    category['id'],
                                    category.get('name', ''),
                                    category.get('description', ''),
                                    category.get('link', ''),
                                    category.get('slug', ''),
                                    category.get('taxonomy', ''),
                                    category.get('parent', 0),
                                    category.get('count', 0),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New category: {category.get('name', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing category {category.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during category archiving: {e}")
            stats["errors"] += 1
        
        return stats
    
    def archive_tags(self, api: WordPressAPI, limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
        """Archive tags from WordPress API."""
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        
        try:
            while True:
                response = api.get_tags(page=page, per_page=100)
                
                if not response.data:
                    break
                
                for tag in response.data:
                    try:
                        # For tags, we don't have a reliable date field, so we'll include all tags
                        # when after_date is specified (tags are typically created once)
                        stats["processed"] += 1
                        
                        # Calculate content hash from tag data
                        tag_content = f"{tag.get('name', '')}{tag.get('description', '')}{tag.get('slug', '')}"
                        content_hash = self.calculate_content_hash(tag_content)
                        
                        with sqlite3.connect(self.db_path) as conn:
                            cursor = conn.cursor()
                            
                            # Check if tag exists and get the latest version
                            cursor.execute(
                                "SELECT id, content_hash, version FROM tags WHERE wp_id = ? ORDER BY version DESC LIMIT 1",
                                (tag['id'],)
                            )
                            existing = cursor.fetchone()
                            
                            if existing:
                                # Tag exists, check if content changed
                                if existing[1] != content_hash:
                                    # Content changed, create new version
                                    cursor.execute('''
                                        INSERT INTO tags 
                                        (wp_id, name, description, link, slug, taxonomy, count, content_hash, version)
                                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    ''', (
                                        tag['id'],
                                        tag.get('name', ''),
                                        tag.get('description', ''),
                                        tag.get('link', ''),
                                        tag.get('slug', ''),
                                        tag.get('taxonomy', ''),
                                        tag.get('count', 0),
                                        content_hash,
                                        existing[2] + 1
                                    ))
                                    stats["updated"] += 1
                                    print(f"Updated tag: {tag.get('name', 'Unknown')}")
                            else:
                                # New tag
                                cursor.execute('''
                                    INSERT INTO tags 
                                    (wp_id, name, description, link, slug, taxonomy, count, content_hash, version)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    tag['id'],
                                    tag.get('name', ''),
                                    tag.get('description', ''),
                                    tag.get('link', ''),
                                    tag.get('slug', ''),
                                    tag.get('taxonomy', ''),
                                    tag.get('count', 0),
                                    content_hash,
                                    1
                                ))
                                stats["new"] += 1
                                print(f"New tag: {tag.get('name', 'Unknown')}")
                            
                            conn.commit()
                    
                    except Exception as e:
                        stats["errors"] += 1
                        print(f"Error processing tag {tag.get('id', 'Unknown')}: {e}")
                
                if limit and stats["processed"] >= limit:
                    break
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            print(f"Error during tag archiving: {e}")
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
    
    def save_comprehensive_session_stats(self, domain: str, content_types: List[str], all_stats: Dict[str, Dict[str, int]], interrupted: bool = False):
        """Save comprehensive session statistics for a complete archive operation."""
        total_processed = sum(stats["processed"] for stats in all_stats.values())
        total_new = sum(stats["new"] for stats in all_stats.values())
        total_updated = sum(stats["updated"] for stats in all_stats.values())
        total_errors = sum(stats["errors"] for stats in all_stats.values())
        
        # Create a summary of what was archived
        content_summary = []
        for content_type, stats in all_stats.items():
            if stats["processed"] > 0:
                content_summary.append(f"{content_type}: {stats['processed']} processed, {stats['new']} new, {stats['updated']} updated")
        
        if interrupted:
            session_description = f"INTERRUPTED - Archive of {domain} - {', '.join(content_types)}"
        else:
            session_description = f"Archive of {domain} - {', '.join(content_types)}"
        
        with sqlite3.connect(self.db_path) as conn:
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
                json.dumps(content_summary) if total_errors == 0 else json.dumps(content_summary + ["Errors occurred"])
            ))
            conn.commit()
    
    def save_failed_verification_session(self, domain: str, reason: str):
        """Save a session for failed WordPress verification."""
        session_description = f"FAILED VERIFICATION - {domain} - {reason}"
        
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
            
            return {
                "total_posts": total_posts,
                "total_comments": total_comments,
                "total_pages": total_pages,
                "total_users": total_users,
                "total_categories": total_categories,
                "total_tags": total_tags,
                "latest_session": latest_session
            }


def main():
    # Set up signal handler for graceful interrupt
    def signal_handler(sig, frame):
        print("\n\n⚠️  Archive operation interrupted by user (Ctrl+C)")
        print("💾 Progress has been saved. You can resume later.")
        print("📊 Check the web interface to see what was archived.")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    parser = argparse.ArgumentParser(
        description="WordPress Content Archiver - Archive WordPress content locally using SQLite"
    )
    parser.add_argument(
        "domain",
        help="WordPress site domain (e.g., https://example.com)"
    )
    parser.add_argument(
        "--content-type",
        choices=["posts", "comments", "pages", "users", "categories", "tags", "all"],
        default="all",
        help="Type of content to archive (default: all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of items to process (for testing)"
    )
    parser.add_argument(
        "--after-date",
        help="Only archive content created/modified after this date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
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
    
    # Parse after_date if provided
    after_date = None
    if args.after_date:
        try:
            # Try parsing as date first
            if len(args.after_date) == 10:  # YYYY-MM-DD
                after_date = datetime.strptime(args.after_date, '%Y-%m-%d')
            else:  # YYYY-MM-DD HH:MM:SS
                after_date = datetime.strptime(args.after_date, '%Y-%m-%d %H:%M:%S')
            print(f"📅 Filtering content after: {after_date}")
        except ValueError:
            print(f"❌ Invalid date format: {args.after_date}")
            print("   Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format")
            sys.exit(1)
    
    # Initialize archiver
    archiver = WordPressArchiver(args.db)
    
    if args.stats:
        stats = archiver.get_stats()
        print("\n=== Archive Statistics ===")
        print(f"Total Posts: {stats['total_posts']}")
        print(f"Total Comments: {stats['total_comments']}")
        print(f"Total Pages: {stats['total_pages']}")
        print(f"Total Users: {stats['total_users']}")
        print(f"Total Categories: {stats['total_categories']}")
        print(f"Total Tags: {stats['total_tags']}")
        
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
        
        # Save a session for the connection failure
        archiver = WordPressArchiver(args.db)
        archiver.save_failed_verification_session(args.domain, f"Connection failed: {e}")
        
        sys.exit(1)
    
    # Verify that it's actually a WordPress site
    print(f"\n🔍 Verifying WordPress site...")
    if not api.verify_wordpress_site():
        print(f"\n❌ Cannot proceed: {args.domain} is not a valid WordPress site")
        print("   Please provide a valid WordPress site URL")
        print("   Example: https://wordpress.org")
        
        # Save a session for the failed verification
        archiver.save_failed_verification_session(args.domain, "Not a WordPress site")
        
        sys.exit(1)
    
    # Archive content based on type
    content_types = []
    if args.content_type == "all":
        content_types = ["posts", "comments", "pages", "users", "categories", "tags"]
    else:
        content_types = [args.content_type]
    
    print(f"\n🚀 Starting archive operation for: {args.domain}")
    print(f"📋 Content types to archive: {', '.join(content_types)}")
    if args.limit:
        print(f"🔢 Processing limit: {args.limit} items per type")
    if after_date:
        print(f"📅 Only archiving content after: {after_date}")
    print("=" * 60)
    
    all_stats = {}
    for content_type in content_types:
        print(f"\n=== Archiving {content_type.upper()} ===")
        
        try:
            if content_type == "posts":
                stats = archiver.archive_posts(api, args.limit, after_date)
            elif content_type == "comments":
                stats = archiver.archive_comments(api, args.limit, after_date)
            elif content_type == "pages":
                stats = archiver.archive_pages(api, args.limit, after_date)
            elif content_type == "users":
                stats = archiver.archive_users(api, args.limit, after_date)
            elif content_type == "categories":
                stats = archiver.archive_categories(api, args.limit, after_date)
            elif content_type == "tags":
                stats = archiver.archive_tags(api, args.limit, after_date)
            
            # Store stats for comprehensive session
            all_stats[content_type] = stats
            
            # Only save individual session for single content type operations
            if len(content_types) == 1:
                archiver.save_session_stats(content_type, stats)
            
            print(f"\n✅ {content_type.title()} Archive Summary:")
            print(f"  📊 Processed: {stats['processed']}")
            print(f"  ➕ New: {stats['new']}")
            print(f"  🔄 Updated: {stats['updated']}")
            print(f"  ❌ Errors: {stats['errors']}")
            
        except KeyboardInterrupt:
            print(f"\n⚠️  Archive operation interrupted during {content_type} processing")
            # Save session for interrupted operation
            all_stats[content_type] = {"processed": 0, "new": 0, "updated": 0, "errors": 1}
            if len(content_types) > 1:
                archiver.save_comprehensive_session_stats(args.domain, content_types, all_stats, interrupted=True)
            else:
                archiver.save_session_stats(content_type, {"processed": 0, "new": 0, "updated": 0, "errors": 1})
            print("💾 Progress has been saved. You can resume later.")
            sys.exit(0)
        except Exception as e:
            print(f"❌ Error archiving {content_type}: {e}")
            all_stats[content_type] = {"processed": 0, "new": 0, "updated": 0, "errors": 1}
    
    # Save comprehensive session stats for multiple content types
    if len(content_types) > 1:
        archiver.save_comprehensive_session_stats(args.domain, content_types, all_stats)
    
    print(f"\n🎉 Archive completed! Database: {args.db}")
    print("🌐 Run 'python3 app.py' to view the archived content in your browser.")


if __name__ == "__main__":
    main()
