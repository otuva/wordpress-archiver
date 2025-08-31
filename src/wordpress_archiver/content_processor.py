"""
Content Processing Module

Handles content normalization, hashing, and change detection for WordPress content.
"""

import hashlib
import re
import html
import logging
from typing import Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class ContentProcessor:
    """Handles content processing, normalization, and change detection."""
    
    def __init__(self):
        """Initialize the content processor."""
        self.dynamic_patterns = [
            # ShareThis and social sharing widgets
            (r'<div[^>]*class="[^"]*sharethis[^"]*"[^>]*>.*?</div>', ''),
            (r'<div[^>]*class="[^"]*(?:social-share|share-buttons|social-media)[^"]*"[^>]*>.*?</div>', ''),
            
            # Dynamic ad elements
            (r'<div[^>]*class="[^"]*(?:adsbygoogle|advertisement|ad-container)[^"]*"[^>]*>.*?</div>', ''),
            
            # Script tags with dynamic content
            (r'<script[^>]*>.*?</script>', ''),
            
            # Inline styles that might be dynamically generated
            (r'style="[^"]*"', ''),
            
            # Data attributes that might be dynamic
            (r'data-[^=]*="[^"]*"', ''),
            
            # Empty divs and spans left after cleaning
            (r'<div[^>]*>\s*</div>', ''),
            (r'<span[^>]*>\s*</span>', ''),
            
            # WordPress-specific dynamic elements
            (r'<div[^>]*class="[^"]*wp-block[^"]*"[^>]*>.*?</div>', ''),
            (r'<div[^>]*id="[^"]*wp-block[^"]*"[^>]*>.*?</div>', ''),
            
            # Analytics and tracking scripts
            (r'<div[^>]*class="[^"]*(?:analytics|tracking|gtag)[^"]*"[^>]*>.*?</div>', ''),
            
            # Dynamic timestamps and dates
            (r'<time[^>]*datetime="[^"]*"[^>]*>.*?</time>', ''),
            
            # Dynamic IDs and classes that change between requests
            (r'id="[^"]*[0-9]{10,}[^"]*"', ''),
            (r'class="[^"]*[0-9]{10,}[^"]*"', ''),
        ]
    
    def normalize_content(self, content: str) -> str:
        """
        Normalize content by removing dynamic elements that change between requests.
        
        Args:
            content: Raw HTML content from WordPress
            
        Returns:
            Normalized content for consistent hashing
        """
        if not content:
            return ""
        
        normalized = content
        
        # Apply all dynamic pattern removals
        for pattern, replacement in self.dynamic_patterns:
            normalized = re.sub(pattern, replacement, normalized, flags=re.DOTALL | re.IGNORECASE)
        
        # Decode HTML entities to their actual characters
        normalized = html.unescape(normalized)
        
        # Normalize whitespace
        normalized = re.sub(r'\s+', ' ', normalized)
        normalized = normalized.strip()
        
        return normalized
    
    def calculate_content_hash(self, content: str) -> str:
        """
        Calculate SHA-256 hash of normalized content for change detection.
        
        Args:
            content: Raw content to hash
            
        Returns:
            SHA-256 hash of normalized content
        """
        normalized_content = self.normalize_content(content)
        return hashlib.sha256(normalized_content.encode('utf-8')).hexdigest()
    
    def is_date_after_filter(self, item_date: str, after_date: Optional[datetime]) -> bool:
        """
        Check if an item's date is after the filter date.
        
        Args:
            item_date: ISO format date string from WordPress
            after_date: Filter date to compare against
            
        Returns:
            True if item should be included, False otherwise
        """
        if not after_date:
            return True
        
        try:
            # Parse the WordPress date (ISO format)
            item_datetime = datetime.fromisoformat(item_date.replace('Z', '+00:00'))
            return item_datetime >= after_date
        except (ValueError, AttributeError) as e:
            logger.warning(f"Failed to parse date '{item_date}': {e}")
            # If date parsing fails, include the item to be safe
            return True
    
    def format_date_for_api(self, after_date: Optional[datetime]) -> Optional[str]:
        """
        Format date for WordPress API consumption.
        
        Args:
            after_date: Date to format
            
        Returns:
            ISO 8601 formatted date string or None
        """
        if not after_date:
            return None
        
        # WordPress API expects ISO 8601 format with time
        # If it's just a date, add time to make it start of day
        if after_date.hour == 0 and after_date.minute == 0 and after_date.second == 0:
            return after_date.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            return after_date.isoformat()
    
    def extract_content_data(self, wp_item: Dict[str, Any], content_type: str) -> Dict[str, Any]:
        """
        Extract and normalize content data from WordPress API response.
        
        Args:
            wp_item: Raw WordPress API response item
            content_type: Type of content (posts, comments, pages, etc.)
            
        Returns:
            Normalized content data dictionary
        """
        if content_type == 'posts':
            return {
                'wp_id': wp_item['id'],
                'title': wp_item.get('title', {}).get('rendered', ''),
                'content': wp_item.get('content', {}).get('rendered', ''),
                'excerpt': wp_item.get('excerpt', {}).get('rendered', ''),
                'author_id': wp_item.get('author', 0),
                'date_created': wp_item.get('date', ''),
                'date_modified': wp_item.get('modified', ''),
                'status': wp_item.get('status', ''),
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', ''))
            }
        elif content_type == 'comments':
            return {
                'wp_id': wp_item['id'],
                'post_id': wp_item.get('post', 0),
                'parent_id': wp_item.get('parent', 0),
                'author_name': wp_item.get('author_name', ''),
                'author_email': wp_item.get('author_email', ''),
                'author_url': wp_item.get('author_url', ''),
                'content': wp_item.get('content', {}).get('rendered', ''),
                'date_created': wp_item.get('date', ''),
                'status': wp_item.get('status', ''),
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', ''))
            }
        elif content_type == 'pages':
            return {
                'wp_id': wp_item['id'],
                'title': wp_item.get('title', {}).get('rendered', ''),
                'content': wp_item.get('content', {}).get('rendered', ''),
                'excerpt': wp_item.get('excerpt', {}).get('rendered', ''),
                'author_id': wp_item.get('author', 0),
                'date_created': wp_item.get('date', ''),
                'date_modified': wp_item.get('modified', ''),
                'status': wp_item.get('status', ''),
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', ''))
            }
        elif content_type == 'users':
            user_content = f"{wp_item.get('name', '')}{wp_item.get('description', '')}{wp_item.get('url', '')}"
            return {
                'wp_id': wp_item['id'],
                'name': wp_item.get('name', ''),
                'url': wp_item.get('url', ''),
                'description': wp_item.get('description', ''),
                'link': wp_item.get('link', ''),
                'slug': wp_item.get('slug', ''),
                'avatar_urls': wp_item.get('avatar_urls', {}),
                'mpp_avatar': wp_item.get('mpp_avatar', {}),
                'content_hash': self.calculate_content_hash(user_content)
            }
        elif content_type == 'categories':
            category_content = f"{wp_item.get('name', '')}{wp_item.get('description', '')}{wp_item.get('slug', '')}"
            return {
                'wp_id': wp_item['id'],
                'name': wp_item.get('name', ''),
                'description': wp_item.get('description', ''),
                'link': wp_item.get('link', ''),
                'slug': wp_item.get('slug', ''),
                'taxonomy': wp_item.get('taxonomy', ''),
                'parent': wp_item.get('parent', 0),
                'count': wp_item.get('count', 0),
                'content_hash': self.calculate_content_hash(category_content)
            }
        elif content_type == 'tags':
            tag_content = f"{wp_item.get('name', '')}{wp_item.get('description', '')}{wp_item.get('slug', '')}"
            return {
                'wp_id': wp_item['id'],
                'name': wp_item.get('name', ''),
                'description': wp_item.get('description', ''),
                'link': wp_item.get('link', ''),
                'slug': wp_item.get('slug', ''),
                'taxonomy': wp_item.get('taxonomy', ''),
                'count': wp_item.get('count', 0),
                'content_hash': self.calculate_content_hash(tag_content)
            }
        else:
            raise ValueError(f"Unsupported content type: {content_type}")
    
    def has_content_changed(self, old_hash: str, new_content: str) -> bool:
        """
        Check if content has changed by comparing hashes.
        
        Args:
            old_hash: Previous content hash
            new_content: New content to check
            
        Returns:
            True if content has changed, False otherwise
        """
        new_hash = self.calculate_content_hash(new_content)
        return old_hash != new_hash
    
    def get_content_summary(self, content: str, max_length: int = 200) -> str:
        """
        Generate a summary of content for display purposes.
        
        Args:
            content: Full content to summarize
            max_length: Maximum length of summary
            
        Returns:
            Content summary
        """
        if not content:
            return ""
        
        # Remove HTML tags for summary
        text_content = re.sub(r'<[^>]+>', '', content)
        text_content = html.unescape(text_content)
        text_content = re.sub(r'\s+', ' ', text_content).strip()
        
        if len(text_content) <= max_length:
            return text_content
        
        # Truncate and add ellipsis
        return text_content[:max_length].rsplit(' ', 1)[0] + '...' 