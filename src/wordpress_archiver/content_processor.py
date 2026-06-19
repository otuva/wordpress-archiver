"""
Content Processing Module

Handles content normalization, hashing, and change detection for WordPress content.
"""

import hashlib
import json
import re
import html
import logging
from typing import Dict, Any, Optional, List, Set
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse, urljoin, urlunparse

logger = logging.getLogger(__name__)

# =============================================================================
# ASSET URL NORMALIZATION + HASHING (shared by archiver and web viewer)
#
# Download-time (archiver) and display-time (web_app) MUST produce an identical
# url_hash for the same asset, or the viewer serves a placeholder for a file we
# actually archived. These functions are the single source of truth for that
# contract — import them in both places; never reimplement.
# =============================================================================

IMAGE_EXTS = {
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico',
    '.avif', '.tiff', '.tif',
}
DOC_EXTS = {
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.odt',
    '.zip', '.mp3', '.m4a', '.wav', '.ogg', '.csv', '.txt',
}
# Hosts that serve avatar images without a file extension (gravatar etc.).
AVATAR_HOSTS = {
    'secure.gravatar.com', 'gravatar.com',
    '0.gravatar.com', '1.gravatar.com', '2.gravatar.com',
}


def normalize_asset_url(url: str, site_url: Optional[str] = None) -> str:
    """
    Canonicalize an asset URL so the same asset always hashes identically.

    Lowercases scheme+host only (paths can be case-sensitive), resolves
    protocol-relative (``//host/x``) and root-relative (``/x``) URLs, and keeps
    the query string (WP cache-busters like ``?x76751`` are part of identity).
    """
    if not url:
        return ''
    url = html.unescape(url.strip())
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/') and site_url:
        url = urljoin(site_url, url)
    parsed = urlparse(url)
    parsed = parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower())
    return urlunparse(parsed)


def url_hash(normalized_url: str) -> str:
    """SHA-256 of a normalized URL — the key used by the ``media`` table and the
    viewer's ``/media/<hash>`` route."""
    return hashlib.sha256(normalized_url.encode('utf-8')).hexdigest()


def is_archivable_asset(normalized_url: str) -> bool:
    """True if a URL points at a downloadable binary we should store as a BLOB."""
    parsed = urlparse(normalized_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    ext = PurePosixPath(path).suffix
    if ext in IMAGE_EXTS or ext in DOC_EXTS:
        return True
    if 'wp-content/uploads' in path:
        return True
    if host in AVATAR_HOSTS or host.endswith('.gravatar.com') or host.endswith('.wp.com'):
        return True
    return False


# Precompiled extraction patterns (compiled once at import).
_IMG_SRC_RE = re.compile(r'<img\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_SOURCE_SRC_RE = re.compile(r'<source\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_SRCSET_RE = re.compile(r'\bsrcset\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_UPLOAD_HREF_RE = re.compile(
    r'<a\b[^>]*?\bhref\s*=\s*["\']([^"\']*wp-content/uploads[^"\']*)["\']', re.IGNORECASE)
_META_IMG_RE = re.compile(
    r'<meta\b[^>]*?(?:property|name)\s*=\s*["\'](?:og:image(?::url)?|twitter:image)["\']'
    r'[^>]*?\bcontent\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
# Safety net: any on-site upload URL in any attribute (data-src, style url(), etc.).
_ANY_UPLOAD_RE = re.compile(
    r'https?://[^\s"\'<>()]+/wp-content/uploads/[^\s"\'<>()]+', re.IGNORECASE)
# CSS background-image: url(...).
_CSS_URL_RE = re.compile(r'url\(\s*["\']?([^"\')]+)["\']?\s*\)', re.IGNORECASE)

# Video-embed iframe hosts handled by yt-dlp (not stored as BLOBs).
_VIDEO_HOSTS = (
    'youtube.com', 'youtu.be', 'youtube-nocookie.com',
    'vimeo.com', 'player.vimeo.com', 'odysee.com', 'dailymotion.com',
)
_IFRAME_SRC_RE = re.compile(r'<iframe\b[^>]*?\bsrc\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)


def _srcset_urls(value: str) -> List[str]:
    """Pull the URL out of each ``url 300w`` / ``url 2x`` candidate in a srcset."""
    urls = []
    for candidate in value.split(','):
        candidate = candidate.strip()
        if candidate:
            urls.append(candidate.split()[0])
    return urls


def extract_urls_from_html(html_text: str, site_url: Optional[str] = None) -> Set[str]:
    """Return the set of normalized, archivable asset URLs referenced in HTML."""
    if not html_text:
        return set()
    raw: List[str] = []
    for rx in (_IMG_SRC_RE, _SOURCE_SRC_RE, _UPLOAD_HREF_RE, _META_IMG_RE,
               _ANY_UPLOAD_RE, _CSS_URL_RE):
        for m in rx.finditer(html_text):
            raw.append(m.group(1) if m.groups() else m.group(0))
    for m in _SRCSET_RE.finditer(html_text):
        raw.extend(_srcset_urls(m.group(1)))
    out: Set[str] = set()
    for u in raw:
        norm = normalize_asset_url(u, site_url)
        if norm and is_archivable_asset(norm):
            out.add(norm)
    return out


def extract_video_embeds(html_text: str) -> List[str]:
    """Return iframe embed URLs for video hosts (deduped, order-preserving)."""
    if not html_text:
        return []
    seen = set()
    out = []
    for m in _IFRAME_SRC_RE.finditer(html_text):
        src = m.group(1).strip()
        low = src.lower()
        if low.startswith('//'):
            src = 'https:' + src
            low = src.lower()
        if any(h in low for h in _VIDEO_HOSTS) and src not in seen:
            seen.add(src)
            out.append(src)
    return out


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
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', '')),
                'categories': wp_item.get('categories', []),
                'tags': wp_item.get('tags', []),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', '')),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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
                'content_hash': self.calculate_content_hash(wp_item.get('content', {}).get('rendered', '')),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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
                'content_hash': self.calculate_content_hash(user_content),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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
                'content_hash': self.calculate_content_hash(category_content),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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
                'content_hash': self.calculate_content_hash(tag_content),
                'raw_json': json.dumps(wp_item, ensure_ascii=False)
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