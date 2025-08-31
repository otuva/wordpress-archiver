#!/usr/bin/env python3
"""
WordPress Archiver - Main Entry Point

A comprehensive tool for archiving WordPress content locally using SQLite.
Provides both CLI and web interface functionality.
"""

import argparse
import signal
import sys
import logging
from datetime import datetime
from pathlib import Path

from src.wordpress_archiver.api import WordPressAPI, WordPressAPIError
from src.wordpress_archiver.archiver import WordPressArchiver
from src.wordpress_archiver.web_app import run_app


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )


def signal_handler(sig, frame):
    """Handle interrupt signals gracefully."""
    print("\n\n⚠️  Archive operation interrupted by user (Ctrl+C)")
    print("💾 Progress has been saved. You can resume later.")
    print("📊 Check the web interface to see what was archived.")
    sys.exit(0)


def parse_date(date_string: str) -> datetime:
    """Parse date string in various formats."""
    try:
        # Try parsing as date first
        if len(date_string) == 10:  # YYYY-MM-DD
            return datetime.strptime(date_string, '%Y-%m-%d')
        else:  # YYYY-MM-DD HH:MM:SS
            return datetime.strptime(date_string, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValueError(f"Invalid date format: {date_string}. Use YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format")


def archive_command(args):
    """Handle the archive command."""
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
    
    # Initialize archiver
    archiver = WordPressArchiver(args.db)
    
    # Initialize API
    try:
        with WordPressAPI(args.domain) as api:
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
            
            # Archive content based on type
            content_types = []
            if args.content_type == "all":
                content_types = ["posts", "comments", "pages", "users", "categories", "tags"]
            else:
                content_types = [args.content_type]
            
            logger.info(f"🚀 Starting archive operation for: {args.domain}")
            logger.info(f"📋 Content types to archive: {', '.join(content_types)}")
            if args.limit:
                logger.info(f"🔢 Processing limit: {args.limit} items per type")
            if after_date:
                logger.info(f"📅 Only archiving content after: {after_date}")
            logger.info("=" * 60)
            
            # Archive content
            all_stats = archiver.archive_all_content(
                api, content_types, args.limit, after_date
            )
            
            # Save comprehensive session stats for multiple content types
            if len(content_types) > 1:
                archiver.save_comprehensive_session(args.domain, content_types, all_stats)
            
            # Print summary
            logger.info(f"\n🎉 Archive completed! Database: {args.db}")
            logger.info("🌐 Run 'python main.py web' to view the archived content in your browser.")
            
    except WordPressAPIError as e:
        logger.error(f"❌ WordPress API error: {e}")
        archiver.save_failed_verification(args.domain, f"API error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        archiver.save_failed_verification(args.domain, f"Unexpected error: {e}")
        sys.exit(1)


def stats_command(args):
    """Handle the stats command."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    archiver = WordPressArchiver(args.db)
    stats = archiver.get_archive_stats()
    
    print("\n=== Archive Statistics ===")
    print(f"Total Posts: {stats['total_posts']}")
    print(f"Total Comments: {stats['total_comments']}")
    print(f"Total Pages: {stats['total_pages']}")
    print(f"Total Users: {stats['total_users']}")
    print(f"Total Categories: {stats['total_categories']}")
    print(f"Total Tags: {stats['total_tags']}")
    
    if stats['latest_session']:
        session = stats['latest_session']
        print(f"\nLatest Session ({session['session_date']}):")
        print(f"  Content Type: {session['content_type']}")
        print(f"  Processed: {session['items_processed']}")
        print(f"  New: {session['items_new']}")
        print(f"  Updated: {session['items_updated']}")
        print(f"  Errors: {session['errors']}")


def web_command(args):
    """Handle the web command."""
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"🌐 Starting web interface on http://{args.host}:{args.port}")
        logger.info("📊 Access the web interface to view archived content")
        run_app(host=args.host, port=args.port, debug=args.debug)
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        logger.error("💡 Run 'python main.py archive <domain>' first to create the database")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to start web interface: {e}")
        sys.exit(1)


def main():
    """Main entry point."""
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
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Archive command
    archive_parser = subparsers.add_parser('archive', help='Archive WordPress content')
    archive_parser.add_argument('domain', help='WordPress site domain (e.g., https://example.com)')
    archive_parser.add_argument(
        '--content-type',
        choices=["posts", "comments", "pages", "users", "categories", "tags", "all"],
        default="all",
        help="Type of content to archive (default: all)"
    )
    archive_parser.add_argument(
        '--limit',
        type=int,
        help="Limit number of items to process (for testing)"
    )
    archive_parser.add_argument(
        '--after-date',
        help="Only archive content created/modified after this date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
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
        default='0.0.0.0',
        help="Host to bind to (default: 0.0.0.0)"
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
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute the appropriate command
    if args.command == 'archive':
        archive_command(args)
    elif args.command == 'stats':
        stats_command(args)
    elif args.command == 'web':
        web_command(args)


if __name__ == "__main__":
    main() 