# Static Assets Documentation

This directory contains all static assets for the WordPress Archive Viewer web application.

## CSS Structure

The CSS is organized into modular files for better maintainability:

### `css/style.css`
Main CSS file that imports all other CSS modules. This is the only CSS file that should be linked in templates.

### `css/main.css`
Contains:
- CSS variables (colors, shadows, border-radius, etc.)
- Base styles (body, typography, main content)
- Loading states
- Custom scrollbar styles

### `css/navbar.css`
Contains:
- Navbar styling and layout
- Navigation links and hover effects
- Search box styling
- Responsive navbar behavior

### `css/cards.css`
Contains:
- Base card styles and hover effects
- Stats cards with gradient backgrounds
- Post cards and comment cards
- Content preview and HTML content styles
- Version cards and breadcrumb styling
- Comments container and pagination large styles

### `css/buttons.css`
Contains:
- Button styles (primary, outline, light variants)
- Form control styling
- Input group styling
- Button size variations

### `css/components.css`
Contains:
- Pagination styles
- Badge and version badge styles
- Alert styles
- Comment meta and URL styles
- Version history styling
- Footer styling
- Table styles
- Session row styles
- Responsive design rules

## JavaScript Structure

### `js/main.js`
Contains:
- Bootstrap tooltip initialization
- Session row click handlers
- Form loading states
- Smooth scrolling for anchor links

## Usage

All templates should only include the main CSS and JS files:

```html
<!-- In base.html -->
<link href="{{ url_for('static', filename='css/style.css') }}" rel="stylesheet">
<script src="{{ url_for('static', filename='js/main.js') }}"></script>
```

## Design System

The application uses a consistent design system with:

- **Primary Color**: `#6366f1` (Indigo)
- **Secondary Color**: `#64748b` (Slate)
- **Success Color**: `#10b981` (Emerald)
- **Warning Color**: `#f59e0b` (Amber)
- **Danger Color**: `#ef4444` (Red)
- **Info Color**: `#06b6d4` (Cyan)

All components use consistent:
- Border radius: `0.75rem` (large), `0.5rem` (small)
- Shadows: Small, medium, and large variants
- Transitions: `0.2s ease` for all interactive elements
- Typography: Inter font family

## Card Components

The application features several card types:

1. **Regular Cards**: Standard content containers
2. **Stats Cards**: Dashboard statistics with gradient backgrounds
3. **Post Cards**: Blog post previews with hover effects
4. **Comment Cards**: Comment displays with left border accent
5. **Version Cards**: Version history displays

All cards feature:
- Consistent hover animations
- Unified border radius and shadows
- Responsive design
- Proper spacing and typography 