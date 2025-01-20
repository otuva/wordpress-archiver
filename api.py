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
