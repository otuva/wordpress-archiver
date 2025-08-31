"""
WordPress Archiver Module

Main archiving functionality with improved structure and error handling.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from .api import WordPressAPI, WordPressAPIError
from .database import DatabaseManager
from .content_processor import ContentProcessor

logger = logging.getLogger(__name__)


class WordPressArchiver:
    """Main archiver class with improved structure and error handling."""
    
    def __init__(self, db_path: str = "wordpress_archive.db"):
        """
        Initialize the WordPress archiver.
        
        Args:
            db_path: Path to the SQLite database file
        """
        self.db = DatabaseManager(db_path)
        self.content_processor = ContentProcessor()
    
    def archive_content(self, api: WordPressAPI, content_type: str, 
                       limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, int]:
        """
        Archive content of a specific type from WordPress API.
        
        Args:
            api: WordPress API instance
            content_type: Type of content to archive
            limit: Maximum number of items to process
            after_date: Only archive content after this date
            
        Returns:
            Dictionary with archive statistics
        """
        logger.info(f"Starting archive of {content_type}")
        
        stats = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
        page = 1
        consecutive_empty_pages = 0
        per_page = min(100, limit) if limit else 100
        
        # Format date for API
        after_iso = self.content_processor.format_date_for_api(after_date)
        
        try:
            while True:
                # Get content from API
                response = self._get_content_page(api, content_type, page, per_page, after_iso)
                
                if not response.data:
                    break
                
                page_has_matching_content = False
                
                for item in response.data:
                    try:
                        page_has_matching_content = True
                        stats["processed"] += 1
                        
                        # Process the item
                        self._process_content_item(content_type, item, stats)
                        
                        # Check limit
                        if limit and stats["processed"] >= limit:
                            break
                            
                    except Exception as e:
                        stats["errors"] += 1
                        logger.error(f"Error processing {content_type} {item.get('id', 'Unknown')}: {e}")
                
                # Check limit again after processing the page
                if limit and stats["processed"] >= limit:
                    break
                
                # Handle consecutive empty pages
                if not page_has_matching_content:
                    consecutive_empty_pages += 1
                    if consecutive_empty_pages >= 10:
                        logger.warning(f"Stopping after {consecutive_empty_pages} consecutive pages with no content")
                        break
                else:
                    consecutive_empty_pages = 0
                
                if page >= response.total_pages_count:
                    break
                
                page += 1
        
        except Exception as e:
            logger.error(f"Error during {content_type} archiving: {e}")
            stats["errors"] += 1
        
        logger.info(f"Completed archive of {content_type}: {stats}")
        return stats
    
    def _get_content_page(self, api: WordPressAPI, content_type: str, page: int, 
                         per_page: int, after_iso: Optional[str] = None):
        """Get a page of content from the WordPress API."""
        if content_type == "posts":
            return api.get_posts(page=page, per_page=per_page, after=after_iso)
        elif content_type == "comments":
            return api.get_comments(page=page, per_page=per_page, after=after_iso)
        elif content_type == "pages":
            return api.get_pages(page=page, per_page=per_page, after=after_iso)
        elif content_type == "users":
            return api.get_users(page=page, per_page=per_page, after=after_iso)
        elif content_type == "categories":
            return api.get_categories(page=page, per_page=per_page)
        elif content_type == "tags":
            return api.get_tags(page=page, per_page=per_page)
        else:
            raise ValueError(f"Unsupported content type: {content_type}")
    
    def _process_content_item(self, content_type: str, item: Dict[str, Any], stats: Dict[str, int]):
        """Process a single content item."""
        # Extract and normalize content data
        content_data = self.content_processor.extract_content_data(item, content_type)
        
        # Check if content exists and get current hash
        existing_hash = self.db.get_content_hash(content_type, content_data['wp_id'])
        
        if existing_hash is None:
            # New content
            self.db.insert_content(content_type, content_data, version=1)
            stats["new"] += 1
            logger.info(f"New {content_type}: {self._get_item_title(content_data, content_type)}")
        elif existing_hash != content_data['content_hash']:
            # Content changed, create new version
            latest_version = self.db.get_latest_version(content_type, content_data['wp_id'])
            new_version = latest_version['version'] + 1 if latest_version else 2
            
            self.db.insert_content(content_type, content_data, version=new_version)
            stats["updated"] += 1
            logger.info(f"Updated {content_type}: {self._get_item_title(content_data, content_type)}")
    
    def _get_item_title(self, content_data: Dict[str, Any], content_type: str) -> str:
        """Get a human-readable title for the content item."""
        if content_type in ['posts', 'pages']:
            return content_data.get('title', 'Unknown')
        elif content_type == 'comments':
            return content_data.get('author_name', 'Unknown')
        elif content_type in ['users', 'categories', 'tags']:
            return content_data.get('name', 'Unknown')
        else:
            return 'Unknown'
    
    def archive_all_content(self, api: WordPressAPI, content_types: List[str], 
                           limit: Optional[int] = None, after_date: Optional[datetime] = None) -> Dict[str, Dict[str, int]]:
        """
        Archive multiple content types.
        
        Args:
            api: WordPress API instance
            content_types: List of content types to archive
            limit: Maximum number of items per type
            after_date: Only archive content after this date
            
        Returns:
            Dictionary with statistics for each content type
        """
        all_stats = {}
        
        for content_type in content_types:
            logger.info(f"Archiving {content_type}...")
            stats = self.archive_content(api, content_type, limit, after_date)
            all_stats[content_type] = stats
            
            # Save individual session for single content type operations
            if len(content_types) == 1:
                self.db.save_session_stats(content_type, stats)
        
        return all_stats
    
    def get_archive_stats(self) -> Dict[str, Any]:
        """Get overall archive statistics."""
        return self.db.get_stats()
    
    def save_comprehensive_session(self, domain: str, content_types: List[str], 
                                 all_stats: Dict[str, Dict[str, int]], interrupted: bool = False):
        """Save comprehensive session statistics."""
        self.db.save_comprehensive_session_stats(domain, content_types, all_stats, interrupted)
    
    def save_failed_verification(self, domain: str, reason: str):
        """Save a session for failed WordPress verification."""
        self.db.save_failed_verification_session(domain, reason) 