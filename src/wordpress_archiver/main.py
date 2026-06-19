#!/usr/bin/env python3
"""
WordPress Archiver - Main Entry Point

A comprehensive tool for archiving WordPress content locally using SQLite.
Provides both CLI and web interface functionality for viewing archived content.

Features:
- Archive WordPress posts, comments, pages, users, categories, and tags
- Web interface for browsing archived content
- Search and pagination support
- Version tracking for content changes
- Session management and statistics
"""

import argparse
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path

from .api import WordPressAPI, WordPressAPIError
from .archiver import WordPressArchiver

# =============================================================================
# LOGGING AND UTILITY FUNCTIONS
# =============================================================================

def setup_logging(verbose: bool = False):
    """
    Setup logging configuration for the application.
    
    Args:
        verbose: Enable debug logging if True
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def signal_handler(sig, frame):
    """
    Handle interrupt signals gracefully.
    
    Provides user-friendly feedback when the archive operation is interrupted.
    """
    print("\n\n⚠️  Archive operation interrupted by user (Ctrl+C)")
    print("💾 Progress has been saved. You can resume later.")
    print("📊 Check the web interface to see what was archived.")
    sys.exit(0)


def parse_date(date_string: str) -> datetime:
    """
    Parse date string in various formats.
    
    Args:
        date_string: Date string in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format
        
    Returns:
        Parsed datetime object
        
    Raises:
        ValueError: If date format is invalid
    """
    try:
        # Try parsing as date first
        if len(date_string) == 10:  # YYYY-MM-DD
            return datetime.strptime(date_string, '%Y-%m-%d')
        else:  # YYYY-MM-DD HH:MM:SS
            return datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValueError(
            f"Invalid date format: {date_string}. "
            "Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format"
        )

# =============================================================================
# COMMAND HANDLERS
# =============================================================================

def archive_command(args):
    """
    Handle the archive command.
    
    Archives WordPress content based on the provided arguments.
    
    Args:
        args: Parsed command line arguments
    """
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    # Set up signal handler for graceful interrupt
    signal.signal(signal.SIGINT, signal_handler)
    
    # Parse after_date if provided
    after_date = None
    if args.after_date:
        try:
            after_date = parse_date(args.after_date)
            logger.info(f"📅 Filtering content after: {after_date}")
        except ValueError as e:
            logger.error(f"❌ {e}")
            sys.exit(1)
    
    # Parse optional authentication (Application Password)
    auth = None
    if getattr(args, 'auth', None):
        if ':' not in args.auth:
            logger.error("❌ --auth must be in the form USER:APP_PASSWORD")
            sys.exit(1)
        user, password = args.auth.split(':', 1)
        auth = (user, password)
        logger.info(f"🔐 Authenticating as '{user}' (private/draft/raw content enabled)")

    # Initialize archiver
    archiver = WordPressArchiver(args.db)

    # Initialize API and verify WordPress site
    try:
        with WordPressAPI(args.domain, auth=auth) as api:
            logger.info(f"Connecting to WordPress site: {args.domain}")
            
            # Verify that it's actually a WordPress site
            logger.info("🔍 Verifying WordPress site...")
            if not api.verify_wordpress_site():
                logger.error(f"❌ Cannot proceed: {args.domain} is not a valid WordPress site")
                logger.error("   Please provide a valid WordPress site URL")
                logger.error("   Example: https://wordpress.org")
                
                # Save a session for the failed verification
                archiver.save_failed_verification(args.domain, "Not a WordPress site")
                sys.exit(1)
            
            # Record the site URL so display-time URL rewriting can resolve
            # relative asset references to the same hash used at download time.
            archiver.db.set_meta('site_url', api.domain)

            # Determine content types to archive
            content_types = _get_content_types(args.content_type)
            if args.no_media and 'media' in content_types:
                content_types = [c for c in content_types if c != 'media']
            if args.no_endpoints and 'endpoints' in content_types:
                content_types = [c for c in content_types if c != 'endpoints']

            logger.info(f"🚀 Starting archive operation for: {args.domain}")
            logger.info(f"📋 Content types to archive: {', '.join(content_types)}")
            if args.limit:
                logger.info(f"🔢 Processing limit: {args.limit} items per type")

            logger.info("=" * 60)

            # Archive each content type
            all_stats = {}
            for content_type in content_types:
                try:
                    logger.info(f"Archiving {content_type}...")
                    if content_type == 'media':
                        stats = archiver.archive_media(api, limit=args.limit)
                    elif content_type == 'endpoints':
                        stats = archiver.archive_all_endpoints(
                            api, limit=args.limit,
                            recheck_permissions=args.recheck_permissions)
                    else:
                        stats = archiver.archive_content(
                            api,
                            content_type,
                            limit=args.limit,
                            after_date=after_date
                        )
                    all_stats[content_type] = stats

                    # Log results
                    if stats.get('new', 0) > 0:
                        logger.info(f"✅ New {content_type}: {stats['new']}")
                    if stats.get('updated', 0) > 0:
                        logger.info(f"🔄 Updated {content_type}: {stats['updated']}")
                    if stats.get('auth_walled', 0) > 0:
                        logger.info(f"🔒 {stats['auth_walled']} {content_type} require auth — skipped")
                    if stats.get('errors', 0) > 0:
                        logger.warning(f"⚠️  Errors in {content_type}: {stats['errors']}")

                except Exception as e:
                    logger.error(f"❌ Error archiving {content_type}: {e}")
                    all_stats[content_type] = {
                        'processed': 0, 'new': 0, 'updated': 0, 'errors': 1
                    }

            # Download videos with yt-dlp (opt-in)
            if args.download_videos:
                try:
                    logger.info("🎬 Downloading video embeds with yt-dlp...")
                    all_stats['videos'] = archiver.archive_videos(api, args.db, limit=args.limit)
                except Exception as e:
                    logger.error(f"❌ Error downloading videos: {e}")
                    all_stats['videos'] = {'processed': 0, 'new': 0, 'updated': 0, 'errors': 1}

            # Save comprehensive session stats
            archiver.save_comprehensive_session(
                args.domain, list(all_stats.keys()), all_stats
            )
            
            logger.info("\n🎉 Archive completed! Database: " + args.db)
            logger.info("🌐 Run 'python main.py web' to view the archived content in your browser.")
            
    except WordPressAPIError as e:
        logger.error(f"❌ API Error: {e}")
        archiver.save_failed_verification(args.domain, str(e))
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        archiver.save_failed_verification(args.domain, str(e))
        sys.exit(1)


def stats_command(args):
    """
    Handle the stats command.
    
    Display archive statistics.
    
    Args:
        args: Parsed command line arguments
    """
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        archiver = WordPressArchiver(args.db)
        stats = archiver.get_archive_stats()
        
        print("\n📊 WordPress Archive Statistics")
        print("=" * 40)
        print(f"📁 Database: {args.db}")
        print(f"📅 Last Updated: {stats.get('last_updated', 'Unknown')}")
        print()
        
        # Content type statistics
        for content_type in ['posts', 'comments', 'pages', 'users', 'categories', 'tags']:
            count = stats.get(f'total_{content_type}', 0)
            print(f"📝 {content_type.title()}: {count:,}")

        print()

        # Lossless-archive stores
        print(f"🖼️  Media assets stored: {stats.get('total_media', 0):,}")
        print(f"🎬 Videos downloaded: {stats.get('total_videos', 0):,}")
        print(f"🧩 Other API objects: {stats.get('total_api_objects', 0):,}")

        print()
        
        # Session statistics
        total_sessions = stats.get('total_sessions', 0)
        print(f"🔄 Archive Sessions: {total_sessions}")
        
        if total_sessions > 0:
            print("\n📈 Recent Sessions:")
            recent_sessions = stats.get('recent_sessions', [])
            for session in recent_sessions[:5]:  # Show last 5 sessions
                print(f"   • {session['content_type']} - {session['items_processed']} items")
        
    except Exception as e:
        logger.error(f"❌ Error getting statistics: {e}")
        sys.exit(1)


def web_command(args):
    """
    Handle the web command.
    
    Start the web interface for browsing archived content.
    
    Args:
        args: Parsed command line arguments
    """
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        # Check if database exists
        if not Path(args.db).exists():
            logger.error(f"❌ Database {args.db} not found!")
            logger.error("   Please run the archiver first to create the database.")
            logger.error("   Example: python main.py archive https://example.com")
            sys.exit(1)
        
        logger.info(f"🌐 Starting web interface on {args.host}:{args.port}")
        logger.info(f"📁 Using database: {args.db}")
        logger.info("🔗 Open your browser and navigate to the URL above")
        
        # Import and run the web app
        from .web_app import app
        app.config['DATABASE'] = args.db
        app.run(
            debug=args.debug,
            host=args.host,
            port=args.port
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to start web interface: {e}")
        sys.exit(1)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def _get_content_types(content_type: str) -> list:
    """
    Get list of content types to archive based on input.
    
    Args:
        content_type: Content type string from command line
        
    Returns:
        List of content types to process
    """
    if content_type == "all":
        # 'media' runs after the text types (it scans their content for URLs);
        # 'endpoints' captures everything else the REST index exposes.
        return ["posts", "comments", "pages", "users", "categories", "tags",
                "media", "endpoints"]
    else:
        return [content_type]

# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """
    Main entry point for the WordPress Archiver application.
    
    Sets up command line argument parsing and routes to appropriate handlers.
    """
    parser = argparse.ArgumentParser(
        description="WordPress Content Archiver - Archive WordPress content locally using SQLite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Archive all content from a WordPress site
  python main.py archive https://example.com

  # Archive only posts with a limit
  python main.py archive https://example.com --content-type posts --limit 50

  # Archive content after a specific date
  python main.py archive https://example.com --after-date 2024-01-01

  # Show archive statistics
  python main.py stats

  # Start web interface
  python main.py web

  # Start web interface on custom port
  python main.py web --port 8080
        """
    )
    
    # Create subparsers for different commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Archive command
    archive_parser = subparsers.add_parser('archive', help='Archive WordPress content')
    archive_parser.add_argument(
        'domain',
        help="WordPress site URL (e.g., https://example.com)"
    )
    archive_parser.add_argument(
        '--content-type', '-t',
        choices=["posts", "comments", "pages", "users", "categories", "tags",
                 "media", "endpoints", "all"],
        default="all",
        help="Content type to archive (default: all)"
    )
    archive_parser.add_argument(
        '--limit', '-l',
        type=int,
        help="Limit items per phase (content type, media downloads, videos, and "
             "objects per REST route) — for quick preview runs. Omit for a full "
             "archive."
    )
    archive_parser.add_argument(
        '--no-media',
        action='store_true',
        help="Skip downloading binary media assets (images/PDFs/avatars)"
    )
    archive_parser.add_argument(
        '--no-endpoints',
        action='store_true',
        help="Skip the REST discovery walk (custom post types, taxonomies, menus, ...)"
    )
    archive_parser.add_argument(
        '--recheck-permissions',
        action='store_true',
        help="Re-probe REST endpoints that returned permission errors (401/403) on a "
             "previous run with the same credentials (they're skipped by default)"
    )
    archive_parser.add_argument(
        '--download-videos',
        action='store_true',
        help="Download video embeds with yt-dlp to <db>_media/videos/ (needs yt-dlp + ffmpeg)"
    )
    archive_parser.add_argument(
        '--auth',
        metavar='USER:APP_PASSWORD',
        help="WordPress Application Password (user:password) to also capture "
             "private/draft/protected content, raw fields, user emails and settings"
    )
    archive_parser.add_argument(
        '--after-date', '-a',
        help="Only archive content after this date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
    )
    archive_parser.add_argument(
        '--db',
        default="wordpress_archive.db",
        help="SQLite database file path (default: wordpress_archive.db)"
    )
    archive_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose logging"
    )
    
    # Stats command
    stats_parser = subparsers.add_parser('stats', help='Show archive statistics')
    stats_parser.add_argument(
        '--db',
        default="wordpress_archive.db",
        help="SQLite database file path (default: wordpress_archive.db)"
    )
    stats_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose logging"
    )
    
    # Web command
    web_parser = subparsers.add_parser('web', help='Start web interface')
    web_parser.add_argument(
        '--host',
        default='127.0.0.1',
        help="Host to bind to (default: 127.0.0.1, local-only). Use 0.0.0.0 to "
             "expose on your LAN — note the viewer serves ALL archived content, "
             "including private/draft data and user emails captured via --auth."
    )
    web_parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help="Port to bind to (default: 5000)"
    )
    web_parser.add_argument(
        '--debug',
        action='store_true',
        help="Enable debug mode"
    )
    web_parser.add_argument(
        '--db',
        default="wordpress_archive.db",
        help="SQLite database file path (default: wordpress_archive.db)"
    )
    web_parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Enable verbose logging"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Route to appropriate command handler
    if args.command == 'archive':
        archive_command(args)
    elif args.command == 'stats':
        stats_command(args)
    elif args.command == 'web':
        web_command(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main() 