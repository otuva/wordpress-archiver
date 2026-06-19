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
    """Custom exception for WordPress API errors.

    ``status_code`` carries the HTTP status when the failure was an HTTP error
    response (None for timeouts, connection errors, and invalid JSON), so callers
    can branch on it instead of parsing the message string.
    """

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class WordPressAPI:
    """WordPress REST API wrapper with comprehensive error handling."""
    
    def __init__(self, domain: str, timeout: int = 30,
                 auth: Optional[tuple] = None):
        """
        Initialize the WordPress API wrapper.

        Args:
            domain: The domain name of the WordPress site (e.g., https://example.com)
            timeout: Request timeout in seconds
            auth: Optional (username, application_password) tuple. When supplied,
                requests are authenticated (HTTP Basic over HTTPS) and list
                endpoints request context=edit / status=any so private, draft and
                protected content (plus raw fields and user emails) are captured.
        """
        self.base_url = f"{domain.rstrip('/')}/wp-json/wp/v2"
        self.root_url = f"{domain.rstrip('/')}/wp-json"
        self.domain = domain.rstrip('/')
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "WordPressAPI/1.0 (Python)"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.authenticated = bool(auth)
        if auth:
            self.session.auth = auth

    def _maybe_auth_params(self, params: Dict[str, Any], status_filter: bool = True) -> Dict[str, Any]:
        """Add context=edit (and status=any) to list requests when authenticated."""
        if self.authenticated:
            params["context"] = "edit"
            if status_filter:
                params["status"] = "any"
        return params

    @staticmethod
    def _api_error(context: str, exc: Exception) -> 'WordPressAPIError':
        """Convert a requests exception to a WordPressAPIError without changing message text."""
        if isinstance(exc, requests.exceptions.Timeout):
            return WordPressAPIError(f"Request timeout for {context}")
        if isinstance(exc, requests.exceptions.ConnectionError):
            return WordPressAPIError(f"Connection error for {context}")
        if isinstance(exc, requests.exceptions.HTTPError):
            return WordPressAPIError(
                f"HTTP error {exc.response.status_code}: {exc.response.text}",
                status_code=exc.response.status_code)
        if isinstance(exc, requests.exceptions.RequestException):
            return WordPressAPIError(f"Request failed: {exc}")
        if isinstance(exc, ValueError):
            return WordPressAPIError(f"Invalid JSON response: {exc}")
        return WordPressAPIError(str(exc))

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
            
        except (requests.exceptions.RequestException, ValueError) as e:
            # Timeout/ConnectionError/HTTPError are RequestException subclasses;
            # _api_error dispatches on the concrete type (and attaches status_code).
            raise self._api_error(url, e)

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

        return self._make_request("GET", "posts", params=self._maybe_auth_params(params))

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

        return self._make_request("GET", "comments", params=self._maybe_auth_params(params))

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

        return self._make_request("GET", "pages", params=self._maybe_auth_params(params))

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

        return self._make_request("GET", "users", params=self._maybe_auth_params(params, status_filter=False))

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

    def get_media(self, page: int = 1, per_page: int = 100) -> WordPressResponse:
        """Retrieve a paginated list of media attachments (/wp/v2/media)."""
        params = {"page": page, "per_page": per_page}
        return self._make_request("GET", "media", params=self._maybe_auth_params(params, status_filter=False))

    def _request_full(self, url: str, params: Optional[Dict[str, Any]] = None) -> WordPressResponse:
        """Make a GET request to an absolute wp-json URL (used for discovery/generic routes)."""
        try:
            response = self.session.request("GET", url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            total_count = int(response.headers.get("X-WP-Total", 0))
            total_pages_count = int(response.headers.get("X-WP-TotalPages", 1))
            return WordPressResponse(data, total_count, total_pages_count)
        except (requests.exceptions.RequestException, ValueError) as e:
            # Timeout/ConnectionError/HTTPError are RequestException subclasses;
            # _api_error dispatches on the concrete type (and attaches status_code).
            raise self._api_error(url, e)

    def get_root(self) -> WordPressResponse:
        """Fetch the REST API discovery index at /wp-json/ (lists every route)."""
        return self._request_full(self.root_url)

    def get_json(self, route: str, params: Optional[Dict[str, Any]] = None) -> WordPressResponse:
        """
        GET an arbitrary discovered route.

        Args:
            route: Full route path beginning with '/', e.g. '/wp/v2/menu-items'.
        """
        url = f"{self.domain}/wp-json{route}"
        return self._request_full(url, params=params)

    def get_route_page(self, route: str, page: int = 1,
                       per_page: int = 100) -> WordPressResponse:
        """GET one page of a discovered collection route, with graceful fallback.

        Reuses ``_maybe_auth_params`` for the ``context=edit`` scope so the magic
        param lives in one place. Fallbacks, in order:

        - Authenticated and the edit-scoped request fails: retry without the edit
          params, so a route we can read in *view* scope but not *edit* still gets
          archived (no content dropped).
        - On page 1, if it still fails with anything other than a permission error,
          make one bare attempt with no params — a route may reject ``?page`` /
          ``per_page`` (400) or even crash on them (5xx) yet return fine when asked
          plainly, and we must not lose that content.

        The one failure we never retry is ``401/403``: auth is decided before query
        params, so an identical request can't change the outcome. Definitive failures
        are raised with ``status_code`` set for the caller to classify (permission-
        walled vs param vs real error).
        """
        params = self._maybe_auth_params({'page': page, 'per_page': per_page},
                                         status_filter=False)
        try:
            return self.get_json(route, params=params)
        except WordPressAPIError as e:
            if self.authenticated:
                try:
                    return self.get_json(route,
                                         params={'page': page, 'per_page': per_page})
                except WordPressAPIError as e2:
                    e = e2
            if page == 1 and e.status_code not in (401, 403):
                return self.get_json(route)
            raise e

    def download_binary(self, url: str, max_size_bytes: int = 50 * 1024 * 1024) -> tuple:
        """
        Download a binary asset.

        Returns:
            (content_bytes, content_type, http_status). content_bytes is None when
            the asset exceeds max_size_bytes (caller records it as 'oversized').

        Raises:
            WordPressAPIError: on network/HTTP failure (caller records 'failed').
        """
        try:
            with self.session.get(url, timeout=self.timeout, stream=True) as response:
                status = response.status_code
                response.raise_for_status()

                content_type = response.headers.get("Content-Type", "application/octet-stream")
                declared = response.headers.get("Content-Length")
                if declared and int(declared) > max_size_bytes:
                    response.close()
                    return None, content_type, status

                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_size_bytes:
                        response.close()
                        return None, content_type, status
                    chunks.append(chunk)
                return b"".join(chunks), content_type, status

        except requests.exceptions.RequestException as e:
            # Timeout/ConnectionError/HTTPError are all RequestException subclasses;
            # _api_error is the single conversion point and attaches status_code.
            raise self._api_error(url, e)

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
                except requests.exceptions.RequestException:
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