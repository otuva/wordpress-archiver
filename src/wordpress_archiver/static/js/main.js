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