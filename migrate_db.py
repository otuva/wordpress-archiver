#!/usr/bin/env python3
"""
Database Migration Script

Migrates existing WordPress archive database to support multiple versions
of the same content by changing the unique constraint from wp_id to (wp_id, version).
"""

import sqlite3
import os
import sys


def migrate_database(db_path: str):
    """Migrate the database to support multiple versions."""
    if not os.path.exists(db_path):
        print(f"Database {db_path} not found!")
        return False
    
    print(f"Migrating database: {db_path}")
    
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            
            # Check if migration is needed
            cursor.execute("PRAGMA table_info(posts)")
            posts_columns = cursor.fetchall()
            
            # Look for unique constraint on wp_id
            has_unique_wp_id = False
            for column in posts_columns:
                if column[1] == 'wp_id' and column[5] == 1:  # column[5] is pk/unique flag
                    has_unique_wp_id = True
                    break
            
            if not has_unique_wp_id:
                print("Database already migrated or has correct schema.")
                return True
            
            print("Starting migration...")
            
            # Create temporary tables with new schema
            print("Creating temporary tables...")
            
            # Posts table
            cursor.execute('''
                CREATE TABLE posts_new (
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
                CREATE TABLE comments_new (
                    id INTEGER PRIMARY KEY,
                    wp_id INTEGER,
                    post_id INTEGER,
                    author_name TEXT,
                    author_email TEXT,
                    content TEXT,
                    date_created TEXT,
                    status TEXT,
                    content_hash TEXT,
                    version INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(wp_id, version),
                    FOREIGN KEY (post_id) REFERENCES posts_new (wp_id)
                )
            ''')
            
            # Pages table
            cursor.execute('''
                CREATE TABLE pages_new (
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
            
            # Copy data from old tables to new tables
            print("Copying data...")
            
            # Copy posts
            cursor.execute("SELECT COUNT(*) FROM posts")
            posts_count = cursor.fetchone()[0]
            print(f"Copying {posts_count} posts...")
            
            cursor.execute('''
                INSERT INTO posts_new 
                (id, wp_id, title, content, excerpt, author_id, date_created, 
                 date_modified, status, content_hash, version, created_at)
                SELECT id, wp_id, title, content, excerpt, author_id, date_created,
                       date_modified, status, content_hash, version, created_at
                FROM posts
            ''')
            
            # Copy comments
            cursor.execute("SELECT COUNT(*) FROM comments")
            comments_count = cursor.fetchone()[0]
            print(f"Copying {comments_count} comments...")
            
            cursor.execute('''
                INSERT INTO comments_new 
                (id, wp_id, post_id, author_name, author_email, content, date_created,
                 status, content_hash, version, created_at)
                SELECT id, wp_id, post_id, author_name, author_email, content, date_created,
                       status, content_hash, version, created_at
                FROM comments
            ''')
            
            # Copy pages
            cursor.execute("SELECT COUNT(*) FROM pages")
            pages_count = cursor.fetchone()[0]
            print(f"Copying {pages_count} pages...")
            
            cursor.execute('''
                INSERT INTO pages_new 
                (id, wp_id, title, content, excerpt, author_id, date_created,
                 date_modified, status, content_hash, version, created_at)
                SELECT id, wp_id, title, content, excerpt, author_id, date_created,
                       date_modified, status, content_hash, version, created_at
                FROM pages
            ''')
            
            # Drop old tables
            print("Dropping old tables...")
            cursor.execute("DROP TABLE posts")
            cursor.execute("DROP TABLE comments")
            cursor.execute("DROP TABLE pages")
            
            # Rename new tables
            print("Renaming tables...")
            cursor.execute("ALTER TABLE posts_new RENAME TO posts")
            cursor.execute("ALTER TABLE comments_new RENAME TO comments")
            cursor.execute("ALTER TABLE pages_new RENAME TO pages")
            
            # Commit changes
            conn.commit()
            
            print("Migration completed successfully!")
            return True
            
    except Exception as e:
        print(f"Migration failed: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python migrate_db.py <database_path>")
        print("Example: python migrate_db.py wordpress_archive.db")
        sys.exit(1)
    
    db_path = sys.argv[1]
    
    if migrate_database(db_path):
        print("\nMigration successful! You can now run the archiver again.")
    else:
        print("\nMigration failed! Please check the error messages above.")
        sys.exit(1)


if __name__ == "__main__":
    main() 