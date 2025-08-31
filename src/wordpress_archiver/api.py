"""
WordPress REST API Client

Provides a clean interface to interact with WordPress REST API endpoints.
"""

import requests
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class WordPressResponse:
    """Custom response object to include data and pagination details."""
    data: Any
    total_count: int
    total_pages_count: int


class WordPressAPIError(Exception):
    """Custom exception for WordPress API errors."""
    pass


class WordPressAPI:
    """WordPress REST API wrapper with comprehensive error handling."""
    
    def __init__(self, domain: str, timeout: int = 30):
        """
        Initialize the WordPress API wrapper.
        
        Args:
            domain: The domain name of the WordPress site (e.g., https://example.com)
            timeout: Request timeout in seconds
        """
        self.base_url = f"{domain.rstrip('/')}/wp-json/wp/v2"
        self.domain = domain.rstrip('/')
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "WordPressAPI/1.0 (Python)"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _make_request(self, method: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> WordPressResponse:
        """
        Internal method to make an API request with comprehensive error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., 'posts', 'comments')
            params: Query parameters
            
        Returns:
            WordPressResponse object
            
        Raises:
            WordPressAPIError: If the request fails
        """
        url = f"{self.base_url}/{endpoint}"
        
        try:
            response = self.session.request(
                method, url, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            total_count = int(response.headers.get("X-WP-Total", 0))
            total_pages_count = int(response.headers.get("X-WP-TotalPages", 1))
            
            return WordPressResponse(data, total_count, total_pages_count)
            
        except requests.exceptions.Timeout:
            raise WordPressAPIError(f"Request timeout for {url}")
        except requests.exceptions.ConnectionError:
            raise WordPressAPIError(f"Connection error for {url}")
        except requests.exceptions.HTTPError as e:
            raise WordPressAPIError(f"HTTP error {e.response.status_code}: {e.response.text}")
        except requests.exceptions.RequestException as e:
            raise WordPressAPIError(f"Request failed: {e}")
        except ValueError as e:
            raise WordPressAPIError(f"Invalid JSON response: {e}")

    def get_posts(self, page: int = 1, per_page: int = 10, after: Optional[str] = None) -> WordPressResponse:
        """
        Retrieve a paginated list of posts ordered by date ascending.
        
        Args:
            page: Page number to fetch
            per_page: Number of posts per page (default: 10)
            after: ISO 8601 formatted date-time string to fetch posts after this date
            
        Returns:
            WordPressResponse object
        """
        params = {
            "page": page, 
            "per_page": per_page,
            "orderby": "date", 
            "order": "asc"
        }
        if after:
            params["after"] = after
            
        return self._make_request("GET", "posts", params=params)

    def get_post(self, post_id: int) -> WordPressResponse:
        """
        Retrieve a single post by its ID.
        
        Args:
            post_id: ID of the post to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"posts/{post_id}")

    def get_comments(self, post_id: Optional[int] = None, page: int = 1, 
                    per_page: int = 10, after: Optional[str] = None) -> WordPressResponse:
        """
        Retrieve a list of comments, optionally filtered by post ID.
        
        Args:
            post_id: Filter comments by post ID (optional)
            page: Page number to fetch
            per_page: Number of comments per page (default: 10)
            after: ISO 8601 formatted date-time string to fetch comments after this date
            
        Returns:
            WordPressResponse object
        """
        params = {
            "page": page, 
            "per_page": per_page,
            "orderby": "date", 
            "order": "asc"
        }
        if post_id:
            params["post"] = post_id
        if after:
            params["after"] = after
            
        return self._make_request("GET", "comments", params=params)

    def get_comment(self, comment_id: int) -> WordPressResponse:
        """
        Retrieve a single comment by its ID.
        
        Args:
            comment_id: ID of the comment to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"comments/{comment_id}")

    def get_pages(self, page: int = 1, per_page: int = 10, after: Optional[str] = None) -> WordPressResponse:
        """
        Retrieve a paginated list of pages ordered by date ascending.
        
        Args:
            page: Page number to fetch
            per_page: Number of pages per page (default: 10)
            after: ISO 8601 formatted date-time string to fetch pages after this date
            
        Returns:
            WordPressResponse object
        """
        params = {
            "page": page, 
            "per_page": per_page,
            "orderby": "date", 
            "order": "asc"
        }
        if after:
            params["after"] = after
            
        return self._make_request("GET", "pages", params=params)

    def get_page(self, page_id: int) -> WordPressResponse:
        """
        Retrieve a single page by its ID.
        
        Args:
            page_id: ID of the page to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"pages/{page_id}")

    def get_users(self, page: int = 1, per_page: int = 10, after: Optional[str] = None) -> WordPressResponse:
        """
        Retrieve a paginated list of users.
        
        Args:
            page: Page number to fetch
            per_page: Number of users per page (default: 10)
            after: ISO 8601 formatted date-time string to fetch users after this date
            
        Returns:
            WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        if after:
            params["after"] = after
            
        return self._make_request("GET", "users", params=params)

    def get_user(self, user_id: int) -> WordPressResponse:
        """
        Retrieve a single user by their ID.
        
        Args:
            user_id: ID of the user to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"users/{user_id}")

    def get_categories(self, page: int = 1, per_page: int = 10) -> WordPressResponse:
        """
        Retrieve a paginated list of categories.
        
        Args:
            page: Page number to fetch
            per_page: Number of categories per page (default: 10)
            
        Returns:
            WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        return self._make_request("GET", "categories", params=params)

    def get_category(self, category_id: int) -> WordPressResponse:
        """
        Retrieve a single category by its ID.
        
        Args:
            category_id: ID of the category to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"categories/{category_id}")

    def get_tags(self, page: int = 1, per_page: int = 10) -> WordPressResponse:
        """
        Retrieve a paginated list of tags.
        
        Args:
            page: Page number to fetch
            per_page: Number of tags per page (default: 10)
            
        Returns:
            WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        return self._make_request("GET", "tags", params=params)

    def get_tag(self, tag_id: int) -> WordPressResponse:
        """
        Retrieve a single tag by its ID.
        
        Args:
            tag_id: ID of the tag to fetch
            
        Returns:
            WordPressResponse object
        """
        return self._make_request("GET", f"tags/{tag_id}")

    def verify_wordpress_site(self) -> bool:
        """
        Verify that the given site is actually a WordPress site.
        
        Returns:
            bool: True if it's a WordPress site, False otherwise
        """
        logger.info(f"Verifying WordPress site: {self.domain}")
        
        try:
            # Check WordPress REST API
            logger.debug("Checking WordPress REST API...")
            response = self.session.get(f"{self.domain}/wp-json/", timeout=self.timeout)
            
            if response.status_code == 200:
                try:
                    api_info = response.json()
                    if 'namespaces' in api_info and 'wp/v2' in api_info.get('namespaces', []):
                        logger.info("✅ WordPress REST API found")
                        return True
                except (ValueError, KeyError):
                    pass
            
            # Alternative check: look for WordPress-specific indicators
            logger.debug("Checking HTML content for WordPress indicators...")
            response = self.session.get(self.domain, timeout=self.timeout)
            
            if response.status_code == 200:
                content = response.text.lower()
                wordpress_indicators = [
                    'wp-content', 'wp-includes', 'wordpress', 'wp-json', 'wp-admin'
                ]
                
                found_indicators = [
                    indicator for indicator in wordpress_indicators 
                    if indicator in content
                ]
                
                if found_indicators:
                    logger.info(f"✅ WordPress indicators found: {', '.join(found_indicators)}")
                    return True
            
            # Check common WordPress endpoints
            logger.debug("Checking common WordPress endpoints...")
            endpoints_to_check = [
                '/wp-admin/', '/wp-content/', '/wp-includes/', 
                '/wp-config.php', '/xmlrpc.php'
            ]
            
            for endpoint in endpoints_to_check:
                try:
                    response = self.session.head(f"{self.domain}{endpoint}", timeout=5)
                    if response.status_code in [200, 403, 401]:
                        logger.info(f"✅ Found WordPress endpoint: {endpoint}")
                        return True
                except:
                    continue
            
            logger.error(f"❌ {self.domain} does not appear to be a WordPress site")
            return False
            
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Cannot connect to {self.domain}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error while verifying site: {e}")
            return False

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close session."""
        self.session.close() 