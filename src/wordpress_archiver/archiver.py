"""
WordPress Archiver Module

Main archiving functionality with improved structure and error handling.
"""

import logging
import json
import hashlib
import shutil
import subprocess
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

from .api import WordPressAPI, WordPressAPIError
from .database import DatabaseManager
from .content_processor import (
    ContentProcessor,
    normalize_asset_url,
    url_hash,
    is_archivable_asset,
    extract_urls_from_html,
    extract_video_embeds,
)

logger = logging.getLogger(__name__)

# REST bases that already have dedicated typed tables — the generic discovery
# walker skips these to avoid duplicating them into api_objects.
TYPED_REST_BASES = {'posts', 'pages', 'comments', 'users', 'categories', 'tags', 'media'}

# Empty stats skeleton; every archive_* returns these keys so session summing works.
def _new_stats(**extra) -> Dict[str, int]:
    base = {"processed": 0, "new": 0, "updated": 0, "errors": 0}
    base.update(extra)
    return base


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
                        self._process_content_item(content_type, item, stats, api)
                        
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
    
    def _process_content_item(self, content_type: str, item: Dict[str, Any], stats: Dict[str, int], api: Optional[WordPressAPI] = None):
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
        else:
            # Visible content unchanged: keep the newest metadata current on the
            # latest version in place (no new version, history stays append-only).
            if content_data.get('raw_json') is not None:
                self.db.update_latest_raw_json(
                    content_type, content_data['wp_id'], content_data['raw_json'])

        # If processing a post, fetch and save category/tag details
        if content_type == 'posts' and api:
            self._process_post_taxonomies(content_data, api)
    
    def _process_post_taxonomies(self, post_data: Dict[str, Any], api: WordPressAPI):
        """
        Fetch and save category and tag details for a post.
        
        Args:
            post_data: Post data dictionary containing category/tag IDs
            api: WordPress API instance
        """
        # Process categories
        category_ids = post_data.get('categories', [])
        for category_id in category_ids:
            if not self.db.content_exists('categories', category_id):
                try:
                    response = api.get_category(category_id)
                    if response.data:
                        category_data = self.content_processor.extract_content_data(response.data, 'categories')
                        self.db.insert_content('categories', category_data, version=1)
                        logger.debug(f"Saved category: {category_data.get('name', category_id)}")
                except Exception as e:
                    logger.warning(f"Failed to fetch category {category_id}: {e}")
        
        # Process tags
        tag_ids = post_data.get('tags', [])
        for tag_id in tag_ids:
            if not self.db.content_exists('tags', tag_id):
                try:
                    response = api.get_tag(tag_id)
                    if response.data:
                        tag_data = self.content_processor.extract_content_data(response.data, 'tags')
                        self.db.insert_content('tags', tag_data, version=1)
                        logger.debug(f"Saved tag: {tag_data.get('name', tag_id)}")
                except Exception as e:
                    logger.warning(f"Failed to fetch tag {tag_id}: {e}")
    
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

    # =========================================================================
    # MEDIA (binary assets -> BLOBs in the DB)
    # =========================================================================

    def _scan_content_for_urls(self, api: Optional[WordPressAPI] = None) -> set:
        """Collect every archivable asset URL referenced anywhere in the archive.

        Scans ALL versions of every content row (old versions reference assets
        too), user avatars, and — when an API client is given — the authoritative
        /wp/v2/media attachment list.
        """
        site_url = self.db.get_meta('site_url') or (api.domain if api else None)
        urls: set = set()

        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            scan_targets = [
                ('posts', ('content', 'excerpt')),
                ('pages', ('content', 'excerpt')),
                ('comments', ('content',)),
                ('categories', ('description',)),
                ('tags', ('description',)),
                ('users', ('description',)),
            ]
            for table, cols in scan_targets:
                cursor.execute(f"SELECT {', '.join(cols)} FROM {table}")
                for row in cursor.fetchall():
                    for value in row:
                        if value:
                            urls |= extract_urls_from_html(value, site_url)

            # Avatars are JSON dicts of size -> url (gravatar etc.)
            cursor.execute("SELECT avatar_urls, mpp_avatar FROM users")
            for avatar_urls, mpp_avatar in cursor.fetchall():
                for blob in (avatar_urls, mpp_avatar):
                    if not blob:
                        continue
                    try:
                        parsed = json.loads(blob)
                    except (ValueError, TypeError):
                        continue
                    if isinstance(parsed, dict):
                        candidates = parsed.values()
                    elif isinstance(parsed, str):
                        candidates = [parsed]
                    else:
                        candidates = []
                    for candidate in candidates:
                        if isinstance(candidate, str):
                            norm = normalize_asset_url(candidate, site_url)
                            if norm and is_archivable_asset(norm):
                                urls.add(norm)

        if api:
            urls |= self._scan_media_endpoint(api, site_url)

        return urls

    def _scan_media_endpoint(self, api: WordPressAPI, site_url: Optional[str]) -> set:
        """Enumerate the /wp/v2/media attachment list (originals + thumbnail sizes)."""
        urls: set = set()
        page = 1
        try:
            while True:
                response = api.get_media(page=page, per_page=100)
                if not response.data:
                    break
                for item in response.data:
                    source = item.get('source_url')
                    if source:
                        norm = normalize_asset_url(source, site_url)
                        if norm and is_archivable_asset(norm):
                            urls.add(norm)
                    sizes = (item.get('media_details') or {}).get('sizes') or {}
                    for size in sizes.values():
                        size_url = size.get('source_url')
                        if size_url:
                            norm = normalize_asset_url(size_url, site_url)
                            if norm and is_archivable_asset(norm):
                                urls.add(norm)
                if page >= response.total_pages_count:
                    break
                page += 1
        except WordPressAPIError as e:
            logger.warning(f"Could not enumerate /media endpoint: {e}")
        return urls

    def archive_media(self, api: WordPressAPI, max_size_bytes: int = 50 * 1024 * 1024) -> Dict[str, int]:
        """Download every referenced binary asset into the media BLOB store.

        Incremental: URLs already present are skipped. Failures and oversized
        files are recorded (not raised) so a single bad asset never aborts a run.
        """
        stats = _new_stats(discovered=0, downloaded=0, skipped=0, oversized=0)
        all_urls = self._scan_content_for_urls(api)
        stats["discovered"] = len(all_urls)
        known = self.db.media_url_hashes()

        for url in sorted(all_urls):
            h = url_hash(url)
            if h in known:
                stats["skipped"] += 1
                continue
            try:
                content, content_type, http_status = api.download_binary(url, max_size_bytes)
                if content is None:
                    self.db.insert_media(h, url, None, None, content_type, 'oversized', http_status)
                    stats["oversized"] += 1
                    logger.warning(f"Oversized media skipped: {url}")
                    continue
                content_hash = hashlib.sha256(content).hexdigest()
                mime = (content_type or 'application/octet-stream').split(';')[0].strip()
                self.db.insert_media(h, url, content, content_hash, mime, 'ok', http_status)
                known.add(h)
                stats["downloaded"] += 1
                stats["new"] += 1
            except WordPressAPIError as e:
                self.db.insert_media(h, url, None, None, None, 'failed', None)
                stats["failed"] = stats.get("failed", 0) + 1
                stats["errors"] += 1
                logger.warning(f"Failed to download {url}: {e}")
            except Exception as e:
                self.db.insert_media(h, url, None, None, None, 'failed', None)
                stats["failed"] = stats.get("failed", 0) + 1
                stats["errors"] += 1
                logger.warning(f"Error downloading {url}: {e}")

        stats["processed"] = stats["discovered"]
        logger.info(
            f"Media: {stats['downloaded']} downloaded, {stats['skipped']} already known, "
            f"{stats.get('failed', 0)} failed, {stats['oversized']} oversized"
        )
        return stats

    # =========================================================================
    # VIDEOS (yt-dlp -> folder on disk, opt-in)
    # =========================================================================

    def archive_videos(self, api: Optional[WordPressAPI], db_path: str,
                       timeout: int = 600) -> Dict[str, int]:
        """Download video embeds with yt-dlp into <db>_media/videos/.

        Opt-in. Skips gracefully if yt-dlp is absent; per-video failures are
        recorded, never fatal. Already-downloaded embeds are skipped.
        """
        stats = _new_stats(discovered=0, downloaded=0, skipped=0)
        if not shutil.which('yt-dlp'):
            logger.warning("yt-dlp not found; skipping video download. "
                           "Install with: pip install yt-dlp (and ffmpeg for merging).")
            return stats

        site_url = self.db.get_meta('site_url') or (api.domain if api else None)

        embeds: List[str] = []
        seen = set()
        with self.db.get_connection() as conn:
            cursor = conn.cursor()
            for table in ('posts', 'pages', 'comments'):
                cursor.execute(f"SELECT content FROM {table}")
                for (content,) in cursor.fetchall():
                    if content:
                        for embed in extract_video_embeds(content):
                            if embed not in seen:
                                seen.add(embed)
                                embeds.append(embed)
        stats["discovered"] = len(embeds)

        videos_dir = Path(db_path).parent / f"{Path(db_path).stem}_media" / "videos"
        videos_dir.mkdir(parents=True, exist_ok=True)
        done = self.db.downloaded_video_hashes()

        for embed in embeds:
            h = url_hash(normalize_asset_url(embed, site_url))
            if h in done:
                stats["skipped"] += 1
                continue
            output_template = str(videos_dir / f"{h}.%(ext)s")
            try:
                result = subprocess.run(
                    ['yt-dlp',
                     '-f', 'bestvideo[height<=1080]+bestaudio/best[ext=mp4]/best',
                     '--merge-output-format', 'mp4',
                     '--no-playlist', '--no-warnings',
                     '-o', output_template,
                     '--print', 'after_move:filepath',
                     embed],
                    capture_output=True, text=True, timeout=timeout
                )
                if result.returncode != 0:
                    msg = (result.stderr or '').strip()[:500]
                    self.db.insert_video(h, embed, None, None, None, 0, 'failed', msg)
                    stats["failed"] = stats.get("failed", 0) + 1
                    stats["errors"] += 1
                    logger.warning(f"yt-dlp failed for {embed}: {msg.splitlines()[-1] if msg else ''}")
                    continue

                filepath = ''
                if result.stdout and result.stdout.strip():
                    filepath = result.stdout.strip().splitlines()[-1].strip()
                if not filepath or not Path(filepath).exists():
                    matches = list(videos_dir.glob(f"{h}.*"))
                    filepath = str(matches[0]) if matches else ''
                if not filepath or not Path(filepath).exists():
                    self.db.insert_video(h, embed, None, None, None, 0, 'failed', 'output file not found')
                    stats["failed"] = stats.get("failed", 0) + 1
                    stats["errors"] += 1
                    continue

                path = Path(filepath)
                self.db.insert_video(h, embed, path.name, None, path.suffix.lstrip('.'),
                                     path.stat().st_size, 'downloaded', None)
                done.add(h)
                stats["downloaded"] += 1
                stats["new"] += 1
            except subprocess.TimeoutExpired:
                self.db.insert_video(h, embed, None, None, None, 0, 'failed', f'timeout ({timeout}s)')
                stats["failed"] = stats.get("failed", 0) + 1
                stats["errors"] += 1
            except Exception as e:
                self.db.insert_video(h, embed, None, None, None, 0, 'failed', str(e)[:500])
                stats["failed"] = stats.get("failed", 0) + 1
                stats["errors"] += 1

        stats["processed"] = stats["discovered"]
        logger.info(
            f"Videos: {stats['downloaded']} downloaded, {stats['skipped']} already known, "
            f"{stats.get('failed', 0)} failed"
        )
        return stats

    # =========================================================================
    # ENDPOINTS (REST discovery completeness net -> api_objects)
    # =========================================================================

    def archive_all_endpoints(self, api: WordPressAPI) -> Dict[str, int]:
        """Walk the REST discovery index and archive every collection it lists
        that isn't already a typed table (CPTs, custom taxonomies, menus,
        templates, plugin routes...) as raw JSON, so nothing is silently missed.
        """
        stats = _new_stats(discovered=0, skipped=0, routes=0)
        try:
            root = api.get_root()
        except WordPressAPIError as e:
            logger.error(f"Could not fetch REST discovery index: {e}")
            stats["errors"] += 1
            return stats

        self.db.set_meta('discovery_index', json.dumps(root.data, ensure_ascii=False))

        # Capture the type/taxonomy catalogs wholesale for reference.
        for special in ('/wp/v2/types', '/wp/v2/taxonomies'):
            try:
                resp = api.get_json(special)
                self.db.set_meta(special.strip('/').replace('/', '_'),
                                 json.dumps(resp.data, ensure_ascii=False))
            except WordPressAPIError as e:
                logger.warning(f"Could not fetch {special}: {e}")

        routes = {}
        if isinstance(root.data, dict):
            routes = root.data.get('routes', {}) or {}
        collection_routes = self._discover_collection_routes(routes)
        stats["routes"] = len(collection_routes)
        logger.info(f"Discovered {len(collection_routes)} extra collection routes to archive")

        for route in collection_routes:
            try:
                self._archive_endpoint(api, route, stats)
            except Exception as e:
                logger.warning(f"Error archiving endpoint {route}: {e}")
                stats["errors"] += 1

        stats["processed"] = stats["discovered"]
        return stats

    def _discover_collection_routes(self, routes: Dict[str, Any]) -> List[str]:
        """Pick GET-able, non-parameterized collection routes not already typed."""
        out = []
        for path, info in routes.items():
            if not path.startswith('/'):
                continue
            # Skip namespace roots and any parameterized (detail/nested) route.
            if path.count('/') < 2 or '(?' in path:
                continue
            methods = []
            if isinstance(info, dict):
                methods = info.get('methods') or []
                if not methods:
                    for ep in info.get('endpoints', []) or []:
                        methods += ep.get('methods', []) or []
            elif isinstance(info, list):
                for ep in info:
                    methods += ep.get('methods', []) or []
            if 'GET' not in methods:
                continue
            last = path.rstrip('/').split('/')[-1]
            if path.startswith('/wp/v2/') and last in TYPED_REST_BASES:
                continue
            out.append(path)
        return out

    def _archive_endpoint(self, api: WordPressAPI, route: str, stats: Dict[str, int]):
        """Paginate one collection route and store each object in api_objects."""
        page = 1
        while True:
            try:
                response = api.get_json(route, params={'page': page, 'per_page': 100})
            except WordPressAPIError:
                if page == 1:
                    # Route may not support pagination/params; try once bare.
                    response = api.get_json(route)
                else:
                    break

            data = response.data
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                items = [data]
            else:
                break
            if not items:
                break

            for item in items:
                stats["discovered"] += 1
                raw = json.dumps(item, ensure_ascii=False)
                wp_id = self._api_object_id(item, raw)
                content_hash = self.content_processor.calculate_content_hash(raw)
                existing = self.db.get_api_object_latest(route, wp_id)
                if existing is None:
                    self.db.insert_api_object(route, wp_id, raw, content_hash, version=1)
                    stats["new"] += 1
                elif existing.get('content_hash') != content_hash:
                    self.db.insert_api_object(route, wp_id, raw, content_hash,
                                              version=existing['version'] + 1)
                    stats["updated"] += 1
                else:
                    stats["skipped"] += 1

            if not isinstance(data, list) or page >= response.total_pages_count:
                break
            page += 1

    @staticmethod
    def _api_object_id(item: Any, raw: str) -> int:
        """Derive a stable integer key for an arbitrary REST object."""
        if isinstance(item, dict):
            key = item.get('id', item.get('slug'))
            if isinstance(key, int):
                return key
            if key is not None:
                return int(hashlib.sha1(str(key).encode('utf-8')).hexdigest()[:12], 16)
        # Keyless object: key on its content so re-runs dedup, changes append.
        return int(hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12], 16)

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