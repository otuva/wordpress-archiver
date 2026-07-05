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

    // A wrapping <a> counts as an image link if its href ends in an image
    // extension or points at a local /media/ blob. A /media/ hash URL carries no
    // extension, so a non-image attachment (e.g. a linked PDF) can slip through
    // here — openLightbox's onerror chain then falls back to the <img>'s own src.
    function hrefIsImage(href) {
        return !!href && (/^\/media\//.test(href) || IMG_EXT_RX.test(href));
    }

    // Ordered, de-duplicated URLs to try for the enlarged view, best first: a
    // wrapping full-size image link, then the largest srcset candidate, then the
    // image's own source. openLightbox walks this list on each load failure, so a
    // dead link or a non-image /media/ target degrades to the thumbnail instead
    // of a broken overlay.
    function bigVersionCandidates(img) {
        var urls = [];
        function add(u) { if (u && urls.indexOf(u) === -1) { urls.push(u); } }

        var a = img.closest('a');
        var href = a && a.getAttribute('href');
        if (hrefIsImage(href)) { add(href); }

        if (img.srcset) {
            var best = null, bestW = -1;
            img.srcset.split(',').forEach(function(part) {
                var tokens = part.trim().split(/\s+/);
                if (!tokens[0]) { return; }
                var d = tokens[1] || '';
                // w-descriptors are pixel widths (hundreds/thousands); x-descriptors
                // are small density factors (1x/2x/3x). parseFloat keeps both on a
                // sane scale so a real width outranks a 2x thumbnail if a malformed
                // srcset mixes them.
                var last = d.slice(-1);
                var weight = (last === 'w' || last === 'x') ? parseFloat(d) : 0;
                if (weight > bestW) { bestW = weight; best = tokens[0]; }
            });
            add(best);
        }
        add(img.currentSrc || img.getAttribute('src'));
        return urls;
    }

    // An image is lightbox-able unless it links to a non-image destination
    // (a real hyperlink to another page/post), which must navigate normally.
    function isLightboxable(img) {
        var a = img.closest('a');
        var href = a && a.getAttribute('href');
        if (href && !hrefIsImage(href)) { return false; }
        return bigVersionCandidates(img).length > 0;
    }

    var overlay = null, lightImg = null;
    function ensureOverlay() {
        if (overlay) { return overlay; }
        overlay = document.createElement('div');
        overlay.className = 'lightbox-overlay';
        overlay.setAttribute('role', 'dialog');
        overlay.setAttribute('aria-modal', 'true');
        overlay.setAttribute('aria-label', 'Image viewer');
        overlay.innerHTML =
            '<button type="button" class="lightbox-close" aria-label="Close">&times;</button>' +
            '<img class="lightbox-img" alt="">' +
            '<p class="lightbox-msg">Image unavailable</p>';
        lightImg = overlay.querySelector('.lightbox-img');
        // Close on a backdrop or close-button click, but keep the overlay open
        // when the enlarged image itself is clicked so it can be inspected.
        overlay.addEventListener('click', function(e) {
            if (e.target !== lightImg) { closeLightbox(); }
        });
        document.body.appendChild(overlay);
        return overlay;
    }

    function openLightbox(img) {
        ensureOverlay();
        var candidates = bigVersionCandidates(img);
        var i = 0;
        overlay.classList.remove('error');
        lightImg.alt = img.alt || '';
        lightImg.onerror = function() {
            i += 1;
            if (i < candidates.length) {
                lightImg.src = candidates[i];
            } else {
                // Nothing loaded (e.g. the link pointed at a PDF) — show a notice
                // rather than a broken-image icon.
                lightImg.onerror = null;
                lightImg.removeAttribute('src');
                overlay.classList.add('error');
            }
        };
        lightImg.src = candidates[0];
        overlay.classList.add('open');
        // Lock scrolling on <html>: the page's own html{overflow-y:scroll} means
        // overflow:hidden on <body> would be ignored for the viewport.
        document.documentElement.classList.add('lightbox-lock');
    }

    function closeLightbox() {
        if (!overlay || !overlay.classList.contains('open')) { return; }
        overlay.classList.remove('open');
        // removeAttribute, not src='' — an empty src resolves to the current page
        // URL and fires a spurious request for the document itself.
        lightImg.onerror = null;
        lightImg.removeAttribute('src');
        document.documentElement.classList.remove('lightbox-lock');
    }

    document.querySelectorAll('.content-html').forEach(function(container) {
        container.querySelectorAll('img').forEach(function(img) {
            if (isLightboxable(img)) { img.classList.add('lightboxable'); }
        });
        container.addEventListener('click', function(e) {
            // Leave modified/non-primary clicks alone so Ctrl/Cmd/Shift+click can
            // still open a wrapped image link in a new tab.
            if (e.defaultPrevented || e.button !== 0 ||
                e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
            var img = e.target.closest('img.lightboxable');
            if (!img || !container.contains(img)) { return; }
            e.preventDefault();
            openLightbox(img);
        });
    });

    document.addEventListener('keydown', function(e) {
        // !e.repeat: ignore OS key-repeat so a held Escape doesn't re-run close.
        if (e.key === 'Escape' && !e.repeat) { closeLightbox(); }
    });
});
