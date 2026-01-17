# WordPress Archiver

A comprehensive tool for archiving WordPress content locally using SQLite. This tool provides both command-line and web interface functionality to archive and view WordPress content with version control and change detection.

## Features

- **Complete Content Archiving**: Archive posts, comments, pages, users, categories, and tags
- **Post Relationships**: Automatic tracking of post-category and post-tag relationships
- **Version Control**: Track content changes with automatic versioning
- **Change Detection**: Intelligent content hashing to detect and archive only changed content
- **Web Interface**: Beautiful web interface to browse and search archived content
- **Author Information**: Display author names instead of IDs
- **Avatar Rendering**: Visual avatar display with multiple size options
- **Content Navigation**: Browse posts by category or tag, and view categories/tags for each post
- **Date Filtering**: Archive content from specific dates onwards
- **Duplicate Prevention**: Smart handling of duplicate content
- **Session Tracking**: Track archive sessions with detailed statistics and error reporting
- **SQLite Database**: Lightweight, portable database storage

## Installation

### Prerequisites

- Python 3.8 or higher
- pip

### Install from Source

```bash
# Clone the repository
git clone <repository-url>
cd wordpress-archiver

# Install the package
pip install -e .
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Command Line Interface

The tool provides a unified command-line interface with three main commands:

#### Archive Content

```bash
# Archive all content from a WordPress site
python main.py archive https://example.com

# Archive only posts with a limit
python main.py archive https://example.com --content-type posts --limit 50

# Archive content after a specific date
python main.py archive https://example.com --after-date 2024-01-01

# Archive with custom database path
python main.py archive https://example.com --db my_archive.db

# Enable verbose logging
python main.py archive https://example.com --verbose
```

#### View Statistics

```bash
# Show archive statistics
python main.py stats

# Show statistics for specific database
python main.py stats --db my_archive.db
```

#### Start Web Interface

```bash
# Start web interface
python main.py web

# Start on custom port
python main.py web --port 8080

# Start with debug mode
python main.py web --debug
```

### Web Interface

The web interface provides:

- **Dashboard**: Overview of archived content statistics
- **Content Browsing**: Browse posts, comments, pages, users, categories, and tags
- **Post Relationships**: View and navigate posts by categories and tags
- **Author Names**: See author names instead of IDs
- **Avatar Display**: Visual avatar rendering with clickable size options
- **Search**: Search across all content types
- **Version History**: View different versions of content
- **Session History**: Track archive sessions with accurate content type and error status

Access the web interface at `http://localhost:5000` after starting it.

## Configuration

### Database

The tool uses SQLite for data storage. The database file is created automatically and includes:

- **Posts Table**: WordPress posts with version control
- **Comments Table**: Comments with post relationships
- **Pages Table**: WordPress pages with version control
- **Users Table**: User information, metadata, and avatar URLs (stored as JSON)
- **Categories Table**: Category information
- **Tags Table**: Tag information
- **Post Categories Table**: Junction table linking posts to categories
- **Post Tags Table**: Junction table linking posts to tags
- **Archive Sessions Table**: Session tracking and statistics with error reporting

### Content Processing

The tool includes intelligent content processing:

- **Content Normalization**: Removes dynamic elements that change between requests
- **Hash-based Change Detection**: Uses SHA-256 hashing for efficient change detection
- **Version Control**: Automatically creates new versions when content changes
- **Duplicate Prevention**: Prevents storing identical content multiple times

## Post Relationships

The archiver automatically tracks relationships between posts and their categories/tags:

- **Categories**: Each post can belong to multiple categories
- **Tags**: Each post can have multiple tags
- **Navigation**: Browse posts by clicking on categories or tags
- **Automatic Fetching**: Category and tag details are automatically fetched when encountered in posts
- **Versioning**: Relationships are versioned along with posts to track changes over time

In the web interface:
- Click on a category or tag to see all associated posts
- View categories and tags for each post on the post detail page
- Navigate seamlessly between posts, categories, and tags

## Architecture

The project is organized into modular components:

```
src/wordpress_archiver/
├── __init__.py          # Package initialization
├── api.py              # WordPress REST API client
├── archiver.py         # Main archiving logic
├── content_processor.py # Content processing and normalization
├── database.py         # Database management and operations
├── web_app.py          # Flask web application
└── templates/          # HTML templates for web interface
```

### Key Components

- **WordPressAPI**: Handles communication with WordPress REST API
- **WordPressArchiver**: Main archiving orchestration
- **ContentProcessor**: Content normalization and change detection
- **DatabaseManager**: Database operations and schema management
- **WebApp**: Flask-based web interface

## API Reference

### WordPressAPI

```python
from wordpress_archiver.api import WordPressAPI

# Initialize API client
api = WordPressAPI("https://example.com")

# Get posts
response = api.get_posts(page=1, per_page=10)

# Get comments
response = api.get_comments(post_id=123)

# Verify WordPress site
is_wordpress = api.verify_wordpress_site()
```

### WordPressArchiver

```python
from wordpress_archiver.archiver import WordPressArchiver

# Initialize archiver
archiver = WordPressArchiver("archive.db")

# Archive content
stats = archiver.archive_content(api, "posts", limit=100)

# Get statistics
stats = archiver.get_archive_stats()
```

## Error Handling

The tool includes comprehensive error handling:

- **API Errors**: Graceful handling of WordPress API errors
- **Network Issues**: Retry logic and timeout handling
- **Database Errors**: Transaction rollback and error logging
- **Content Processing**: Fallback mechanisms for malformed content

## Logging

The tool uses Python's logging module with configurable levels:

```bash
# Enable verbose logging
python main.py archive https://example.com --verbose
```

Log levels:
- **INFO**: General operation information
- **DEBUG**: Detailed debugging information
- **WARNING**: Non-critical issues
- **ERROR**: Critical errors

## Performance

The tool is optimized for performance:

- **Batch Processing**: Processes content in configurable batches
- **Database Indexing**: Automatic index creation for fast queries
- **Connection Pooling**: Efficient database connection management
- **Memory Management**: Streaming processing for large datasets

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For issues and questions:

1. Check the documentation
2. Search existing issues
3. Create a new issue with detailed information

## Changelog

### Version 1.1.0
- Added post-category and post-tag relationship tracking
- Display author names instead of IDs
- Avatar URL rendering with visual display and clickable size links
- Improved archive session tracking with accurate content type and error status
- Enhanced content navigation (browse posts by category/tag)
- Removed unnecessary status badges for cleaner UI
- Improved error detection and reporting in sessions

### Version 1.0.0
- Initial release
- Complete WordPress content archiving
- Web interface
- Version control
- Change detection
- Session tracking 