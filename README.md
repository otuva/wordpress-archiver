# WordPress Archiver

A Python CLI application for archiving WordPress content locally using SQLite. The application handles duplicates intelligently and preserves content changes by creating new versions when content is modified.

## Features

- **Local SQLite Storage**: All content is stored locally in a SQLite database
- **Duplicate Prevention**: Prevents storing duplicate content using content hashing
- **Version Control**: When content changes, new versions are saved while preserving the original
- **Multiple Content Types**: Archive posts, comments, and pages
- **Session Tracking**: Tracks archive sessions with statistics
- **Error Handling**: Robust error handling with detailed logging
- **Web Interface**: Modern Flask web application to browse and search archived content
- **Search Functionality**: Search across all content types
- **Version History**: View all versions of content with change tracking

## Installation

1. Clone or download the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

### Command Line Archiver

Archive all content from a WordPress site:
```bash
python main.py https://example.com
```

### Web Viewer

Start the Flask web application to browse archived content:
```bash
python app.py
```

Then open your browser to `http://localhost:5000`

### Command Line Options

- `domain`: WordPress site domain (required)
- `--content-type`: Type of content to archive (`posts`, `comments`, `pages`, `all`)
- `--limit`: Limit number of items to process (for testing)
- `--db`: SQLite database file path (default: `wordpress_archive.db`)
- `--stats`: Show archive statistics and exit

### Examples

Archive only posts:
```bash
python main.py https://example.com --content-type posts
```

Archive comments with a limit for testing:
```bash
python main.py https://example.com --content-type comments --limit 50
```

Use a custom database file:
```bash
python main.py https://example.com --db my_archive.db
```

View archive statistics:
```bash
python main.py https://example.com --stats
```

## Database Schema

The application creates the following tables:

### Posts Table
- `id`: Primary key
- `wp_id`: WordPress post ID (unique)
- `title`: Post title
- `content`: Post content
- `excerpt`: Post excerpt
- `author_id`: Author ID
- `date_created`: Creation date
- `date_modified`: Modification date
- `status`: Post status
- `content_hash`: SHA-256 hash of content
- `version`: Version number
- `created_at`: Local timestamp

### Comments Table
- `id`: Primary key
- `wp_id`: WordPress comment ID (unique)
- `post_id`: Associated post ID
- `author_name`: Comment author name
- `author_email`: Comment author email
- `content`: Comment content
- `date_created`: Creation date
- `status`: Comment status
- `content_hash`: SHA-256 hash of content
- `version`: Version number
- `created_at`: Local timestamp

### Pages Table
- Similar structure to posts table

### Archive Sessions Table
- `id`: Primary key
- `session_date`: Session timestamp
- `content_type`: Type of content archived
- `items_processed`: Number of items processed
- `items_new`: Number of new items
- `items_updated`: Number of updated items
- `errors`: Error information

## How It Works

1. **Content Hashing**: Each piece of content is hashed using SHA-256 to detect changes
2. **Duplicate Detection**: The application checks if content with the same WordPress ID already exists
3. **Version Control**: When content changes, a new version is created with an incremented version number
4. **Session Tracking**: Each archive session is logged with statistics

## Database Migration

If you have an existing database from a previous version, you may need to migrate it to support multiple versions of the same content:

```bash
python migrate_db.py wordpress_archive.db
```

This migration changes the unique constraint from `wp_id` to `(wp_id, version)` to allow storing multiple versions of the same content.

## Error Handling

The application includes comprehensive error handling:
- Network errors are caught and logged
- Individual item processing errors don't stop the entire archive process
- Database errors are handled gracefully
- Detailed error messages are provided

## Requirements

- Python 3.6+
- `requests` library
- `flask` library
- SQLite3 (included with Python)

## License

This project is open source and available under the MIT License. 