/* WordPress Archive Viewer - Main JavaScript */

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Bootstrap tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
    
    // Handle session row clicks
    document.querySelectorAll('.session-row').forEach(function(row) {
        row.addEventListener('click', function() {
            var url = this.getAttribute('data-session-url');
            if (url) {
                window.location.href = url;
            }
        });
        
        // Add hover effect
        row.addEventListener('mouseenter', function() {
            this.style.backgroundColor = 'var(--light-bg)';
        });
        
        row.addEventListener('mouseleave', function() {
            this.style.backgroundColor = '';
        });
    });
    
    // Add loading states to forms
    document.querySelectorAll('form').forEach(function(form) {
        form.addEventListener('submit', function() {
            var submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn) {
                submitBtn.classList.add('loading');
                submitBtn.disabled = true;
            }
        });
    });
    
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
        anchor.addEventListener('click', function (e) {
            e.preventDefault();
            var target = document.querySelector(this.getAttribute('href'));
            if (target) {
                target.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });

    // Make comment cards clickable (replaces inline onclick; clicks on inner
    // links pass through to their own href instead of navigating the card).
    document.querySelectorAll('.comment-card[data-href]').forEach(function(card) {
        card.addEventListener('click', function(e) {
            if (e.target.closest('a')) {
                return;
            }
            window.location.href = card.getAttribute('data-href');
        });
    });

    // Highlight a comment when the page opens with an anchor (e.g. #comment-123).
    if (window.location.hash) {
        try {
            var anchored = document.querySelector(window.location.hash);
            if (anchored) {
                anchored.classList.add('highlight');
                setTimeout(function() {
                    anchored.classList.remove('highlight');
                }, 2000);
            }
        } catch (err) {
            /* invalid selector in location.hash — ignore */
        }
    }
});

// =============================================================================
// Post-body image lightbox
// Click an image inside archived content to view its largest available version
// in a full-screen overlay. Everything is served from local /media/<hash>
// routes, so no network calls are made. Images wrapped in a link to another
// page keep their normal navigation.
// =============================================================================
document.addEventListener('DOMContentLoaded', function() {
    var IMG_EXT_RX = /\.(jpe?g|png|gif|webp|bmp|svg|avif)(\?|#|$)/i;

    function hrefIsImage(href) {
        return !!href && (/^\/media\//.test(href) || IMG_EXT_RX.test(href));
    }

    // Best "big version" URL for an image: a wrapping full-size image link wins,
    // then the largest srcset candidate, then the image's own source.
    function bigVersion(img) {
        var a = img.closest('a');
        if (a && hrefIsImage(a.getAttribute('href'))) {
            return a.getAttribute('href');
        }
        if (img.srcset) {
            var best = null, bestW = -1;
            img.srcset.split(',').forEach(function(part) {
                var tokens = part.trim().split(/\s+/);
                if (!tokens[0]) { return; }
                var descriptor = tokens[1] || '';
                var width = descriptor.endsWith('w') ? parseInt(descriptor, 10)
                          : descriptor.endsWith('x') ? parseFloat(descriptor) * 10000
                          : 0;
                if (width > bestW) { bestW = width; best = tokens[0]; }
            });
            if (best) { return best; }
        }
        return img.currentSrc || img.getAttribute('src');
    }

    // An image is lightbox-able unless it links to a non-image destination
    // (a real hyperlink to another page/post), which must navigate normally.
    function isLightboxable(img) {
        var a = img.closest('a');
        var href = a ? a.getAttribute('href') : null;
        if (href && !hrefIsImage(href)) { return false; }
        return !!bigVersion(img);
    }

    var overlay = null;
    function ensureOverlay() {
        if (overlay) { return overlay; }
        overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.innerHTML =
            '<span class="lightbox-close" aria-label="Close">&times;</span>' +
            '<img class="lightbox-img" alt="">';
        overlay.addEventListener('click', closeLightbox);
        document.body.appendChild(overlay);
        return overlay;
    }

    function openLightbox(src, alt) {
        var o = ensureOverlay();
        var img = o.querySelector('.lightbox-img');
        img.src = src;
        img.alt = alt || '';
        o.classList.add('open');
        document.body.classList.add('lightbox-lock');
    }

    function closeLightbox() {
        if (!overlay) { return; }
        overlay.classList.remove('open');
        overlay.querySelector('.lightbox-img').src = '';
        document.body.classList.remove('lightbox-lock');
    }

    document.querySelectorAll('.content-html').forEach(function(container) {
        container.querySelectorAll('img').forEach(function(img) {
            if (isLightboxable(img)) { img.classList.add('lightboxable'); }
        });
        container.addEventListener('click', function(e) {
            var img = e.target.closest('img.lightboxable');
            if (!img || !container.contains(img)) { return; }
            e.preventDefault();
            openLightbox(bigVersion(img), img.alt);
        });
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { closeLightbox(); }
    });
});
