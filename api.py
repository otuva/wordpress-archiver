import requests


class WordPressResponse:
    def __init__(self, data, total_count, total_pages_count):
        """
        Custom response object to include data and pagination details.

        :param data: The JSON response data
        :param total_count: Total number of items
        :param total_pages_count: Total number of pages
        """
        self.data = data
        self.total_count = total_count
        self.total_pages_count = total_pages_count


class WordPressAPI:
    def __init__(self, domain):
        """
        Initialize the WordPress API wrapper.

        :param domain: The domain name of the WordPress site (e.g., https://example.com)
        """
        self.base_url = f"{domain.rstrip('/')}/wp-json/wp/v2"
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "WordPressAPI/1.0 (Python)"
        }

    def _make_request(self, method, endpoint, params=None):
        """
        Internal method to make an API request.

        :param method: HTTP method (GET, POST, etc.)
        :param endpoint: API endpoint (e.g., 'posts', 'comments')
        :param params: Query parameters
        :return: WordPressResponse object
        """
        url = f"{self.base_url}/{endpoint}"
        try:
            response = requests.request(
                method, url, headers=self.headers, params=params
            )
            response.raise_for_status()
            data = response.json()
            total_count = int(response.headers.get("X-WP-Total", 0))
            total_pages_count = int(response.headers.get("X-WP-TotalPages", 1))
            return WordPressResponse(data, total_count, total_pages_count)
        except requests.exceptions.RequestException as e:
            print(f"Error: {e}")
            raise

    def get_posts(self, page=1, per_page=10, after=None):
        """
        Retrieve a paginated list of posts ordered by date ascending.

        :param page: Page number to fetch
        :param per_page: Number of posts per page (default: 10)
        :param after: ISO 8601 formatted date-time string to fetch posts after this date
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page,
                  "orderby": "date", "order": "asc"}
        if after:
            params["after"] = after
        return self._make_request("GET", "posts", params=params)

    def get_post(self, post_id):
        """
        Retrieve a single post by its ID.

        :param post_id: ID of the post to fetch
        :return: Post details
        """
        return self._make_request("GET", f"posts/{post_id}")

    def get_comments(self, post_id=None, page=1, per_page=10, after=None):
        """
        Retrieve a list of comments, optionally filtered by post ID and ordered by date ascending.

        :param post_id: Filter comments by post ID (optional)
        :param page: Page number to fetch
        :param per_page: Number of comments per page (default: 10)
        :param after: ISO 8601 formatted date-time string to fetch comments after this date
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page,
                  "orderby": "date", "order": "asc"}
        if post_id:
            params["post"] = post_id
        if after:
            params["after"] = after
        return self._make_request("GET", "comments", params=params)

    def get_comment(self, comment_id):
        """
        Retrieve a single comment by its ID.

        :param comment_id: ID of the comment to fetch
        :return: Comment details
        """
        return self._make_request("GET", f"comments/{comment_id}")

    def get_pages(self, page=1, per_page=10, after=None):
        """
        Retrieve a paginated list of pages ordered by date ascending.

        :param page: Page number to fetch
        :param per_page: Number of pages per page (default: 10)
        :param after: ISO 8601 formatted date-time string to fetch pages after this date
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page,
                  "orderby": "date", "order": "asc"}
        if after:
            params["after"] = after
        return self._make_request("GET", "pages", params=params)

    def get_page(self, page_id):
        """
        Retrieve a single page by its ID.

        :param page_id: ID of the page to fetch
        :return: Page details
        """
        return self._make_request("GET", f"pages/{page_id}")

    def get_users(self, page=1, per_page=10, after=None):
        """
        Retrieve a paginated list of users.

        :param page: Page number to fetch
        :param per_page: Number of users per page (default: 10)
        :param after: ISO 8601 formatted date-time string to fetch users after this date
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        if after:
            params["after"] = after
        return self._make_request("GET", "users", params=params)

    def get_user(self, user_id):
        """
        Retrieve a single user by their ID.

        :param user_id: ID of the user to fetch
        :return: User details
        """
        return self._make_request("GET", f"users/{user_id}")

    def get_categories(self, page=1, per_page=10):
        """
        Retrieve a paginated list of categories.

        :param page: Page number to fetch
        :param per_page: Number of categories per page (default: 10)
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        return self._make_request("GET", "categories", params=params)

    def get_category(self, category_id):
        """
        Retrieve a single category by its ID.

        :param category_id: ID of the category to fetch
        :return: Category details
        """
        return self._make_request("GET", f"categories/{category_id}")

    def get_tags(self, page=1, per_page=10):
        """
        Retrieve a paginated list of tags.

        :param page: Page number to fetch
        :param per_page: Number of tags per page (default: 10)
        :return: WordPressResponse object
        """
        params = {"page": page, "per_page": per_page}
        return self._make_request("GET", "tags", params=params)

    def get_tag(self, tag_id):
        """
        Retrieve a single tag by its ID.

        :param tag_id: ID of the tag to fetch
        :return: Tag details
        """
        return self._make_request("GET", f"tags/{tag_id}")

    def verify_wordpress_site(self) -> bool:
        """
        Verify that the given site is actually a WordPress site.
        
        Returns:
            bool: True if it's a WordPress site, False otherwise
        """
        # Get the base domain without the API path
        base_domain = self.base_url.replace('/wp-json/wp/v2', '')
        
        try:
            print(f"   Checking WordPress REST API...")
            # Check if the site has WordPress REST API
            headers = {
                "Accept": "application/json",
                "User-Agent": "WordPressAPI/1.0 (Python)"
            }
            response = requests.get(f"{base_domain}/wp-json/", headers=headers, timeout=10)
            
            if response.status_code == 200:
                # Check if it returns WordPress API info
                try:
                    api_info = response.json()
                    if 'namespaces' in api_info and 'wp/v2' in api_info.get('namespaces', []):
                        print(f"   ✅ WordPress REST API found")
                        return True
                except (ValueError, KeyError):
                    pass
            
            print(f"   ⚠️  WordPress REST API not found, checking HTML content...")
            # Alternative check: look for WordPress-specific headers or meta tags
            response = requests.get(base_domain, timeout=10)
            if response.status_code == 200:
                content = response.text.lower()
                wordpress_indicators = [
                    'wp-content',
                    'wp-includes', 
                    'wordpress',
                    'wp-json',
                    'wp-admin'
                ]
                
                found_indicators = []
                for indicator in wordpress_indicators:
                    if indicator in content:
                        found_indicators.append(indicator)
                
                if found_indicators:
                    print(f"   ✅ WordPress indicators found: {', '.join(found_indicators)}")
                    return True
            
            # Check for common WordPress endpoints
            print(f"   ⚠️  Checking common WordPress endpoints...")
            endpoints_to_check = [
                '/wp-admin/',
                '/wp-content/',
                '/wp-includes/',
                '/wp-config.php',
                '/xmlrpc.php'
            ]
            
            for endpoint in endpoints_to_check:
                try:
                    response = requests.head(f"{base_domain}{endpoint}", timeout=5)
                    if response.status_code in [200, 403, 401]:  # 403/401 means it exists but access denied
                        print(f"   ✅ Found WordPress endpoint: {endpoint}")
                        return True
                except:
                    continue
            
            print(f"❌ Error: {base_domain} does not appear to be a WordPress site")
            print("   - No WordPress REST API found")
            print("   - No WordPress indicators found in HTML")
            print("   - No common WordPress endpoints found")
            return False
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error: Cannot connect to {base_domain}")
            print(f"   - Network error: {e}")
            return False
        except Exception as e:
            print(f"❌ Error: Unexpected error while verifying site: {e}")
            return False
