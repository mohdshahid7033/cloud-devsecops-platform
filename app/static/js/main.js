/**
 * ABC Free Consultants - Client Application Script
 * Vanilla JavaScript for UI interactions, accessibility, and form validation
 * Communicates with backend endpoints (/api/status, /api/contact)
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Mobile Menu Toggle
  const navToggle = document.getElementById('nav-toggle');
  const navMenu = document.getElementById('nav-menu');
  const navLinks = document.querySelectorAll('.nav-link');

  if (navToggle && navMenu) {
    navToggle.addEventListener('click', () => {
      const isOpen = navMenu.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    // Close mobile menu when a nav link is clicked
    navLinks.forEach((link) => {
      link.addEventListener('click', () => {
        if (navMenu.classList.contains('open')) {
          navMenu.classList.remove('open');
          navToggle.setAttribute('aria-expanded', 'false');
        }
      });
    });
  }

  // 2. Sticky Navbar Shadow on Scroll
  const navbar = document.getElementById('navbar');
  const handleScroll = () => {
    if (window.scrollY > 10) {
      navbar?.classList.add('scrolled');
    } else {
      navbar?.classList.remove('scrolled');
    }
  };
  window.addEventListener('scroll', handleScroll, { passive: true });
  handleScroll();

  // 3. Active Link Highlighting via IntersectionObserver
  const sections = document.querySelectorAll('section[id]');
  if ('IntersectionObserver' in window && sections.length > 0) {
    const observerOptions = {
      root: null,
      rootMargin: '-20% 0px -60% 0px',
      threshold: 0
    };

    const sectionObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const currentId = entry.target.getAttribute('id');
          navLinks.forEach((link) => {
            const href = link.getAttribute('href');
            if (href === `#${currentId}`) {
              link.classList.add('active');
            } else {
              link.classList.remove('active');
            }
          });
        }
      });
    }, observerOptions);

    sections.forEach((sec) => sectionObserver.observe(sec));
  }

  // 4. Platform Live Telemetry Fetcher
  const fetchTelemetry = async () => {
    const refreshBtn = document.getElementById('refresh-telemetry-btn');
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.textContent = 'Updating Telemetry...';
    }

    try {
      const res = await fetch('/api/status', { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      // Update Service & Version
      const serviceEl = document.getElementById('telem-service');
      const versionEl = document.getElementById('telem-version');
      if (serviceEl) serviceEl.textContent = data.service || 'devsecops-platform';
      if (versionEl) versionEl.textContent = `Release: ${data.version || 'v1.0.1-production'}`;

      // Update Database Status
      const dbStatusEl = document.getElementById('telem-db-status');
      const dbDetailsEl = document.getElementById('telem-db-details');
      const heroDbEl = document.getElementById('hero-db-status');

      if (data.database) {
        const isConnected = data.database.status === 'connected';
        if (dbStatusEl) {
          dbStatusEl.textContent = isConnected ? 'MySQL Connected' : 'Resilient Fallback Mode';
          dbStatusEl.className = isConnected ? 'widget-value text-success' : 'widget-value text-warning';
        }
        if (dbDetailsEl) {
          const latencyStr = data.database.latency_ms ? ` (${data.database.latency_ms}ms)` : '';
          dbDetailsEl.textContent = `Host: ${data.database.host || 'mysql'}:${data.database.port || 3306}${latencyStr}`;
        }
        if (heroDbEl) {
          heroDbEl.textContent = isConnected ? 'MySQL Live' : 'Fallback Store';
          heroDbEl.className = isConnected ? 'metric-val text-success' : 'metric-val text-warning';
        }
        const consultationsCountEl = document.getElementById('telem-consultations-count');
        if (consultationsCountEl) {
          consultationsCountEl.textContent = `${data.database.total_records || 0} Records`;
        }
      }

      // Update Uptime
      const uptimeEl = document.getElementById('telem-uptime');
      if (uptimeEl && typeof data.uptime_seconds === 'number') {
        const secs = data.uptime_seconds;
        const mins = Math.floor(secs / 60);
        const hours = Math.floor(mins / 60);
        if (hours > 0) {
          uptimeEl.textContent = `${hours}h ${mins % 60}m active`;
        } else if (mins > 0) {
          uptimeEl.textContent = `${mins}m ${secs % 60}s active`;
        } else {
          uptimeEl.textContent = `${secs}s active`;
        }
      }

      const statusText = document.getElementById('telemetry-status-text');
      if (statusText) {
        statusText.textContent = 'ONLINE & HEALTHY';
        statusText.className = 'text-success';
      }
    } catch (err) {
      console.warn('Telemetry fetch error:', err);
      const statusText = document.getElementById('telemetry-status-text');
      if (statusText) {
        statusText.textContent = 'TELEMETRY DEGRADED';
        statusText.className = 'text-warning';
      }
    } finally {
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.textContent = '↻ Refresh Live Telemetry';
      }
    }
  };

  // Attach refresh button event and load initially
  const refreshBtn = document.getElementById('refresh-telemetry-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', fetchTelemetry);
  }
  fetchTelemetry();

  // 5. Contact Form Validation & Real API Submission
  const contactForm = document.getElementById('consultation-form');
  const formFeedback = document.getElementById('form-feedback');
  const submitBtn = document.getElementById('submit-btn');

  if (contactForm && formFeedback) {
    contactForm.addEventListener('submit', async (event) => {
      event.preventDefault();

      // Retrieve form inputs
      const nameInput = document.getElementById('contact-name');
      const emailInput = document.getElementById('contact-email');
      const companyInput = document.getElementById('contact-company');
      const serviceInput = document.getElementById('contact-service');
      const messageInput = document.getElementById('contact-message');

      const name = nameInput ? nameInput.value.trim() : '';
      const email = emailInput ? emailInput.value.trim() : '';
      const company = companyInput ? companyInput.value.trim() : '';
      const service = serviceInput ? serviceInput.value : '';
      const message = messageInput ? messageInput.value.trim() : '';

      // Reset invalid states
      [nameInput, emailInput, companyInput, serviceInput, messageInput].forEach((input) => {
        if (input) input.classList.remove('invalid');
      });

      // Simple Email Format Validator
      const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

      // Validation Checks
      let hasError = false;
      let errorMessage = '';

      if (!name || name.length < 2) {
        nameInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please provide your full name (at least 2 characters).';
      } else if (!email || !emailRegex.test(email)) {
        emailInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please provide a valid corporate email address.';
      } else if (!company) {
        companyInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please provide your organization or company name.';
      } else if (!service) {
        serviceInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please select a practice area of interest.';
      } else if (!message || message.length < 10) {
        messageInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please provide a brief project overview (at least 10 characters).';
      }

      if (hasError) {
        formFeedback.className = 'form-feedback error';
        formFeedback.textContent = errorMessage;
        formFeedback.style.display = 'block';
        return;
      }

      // Enter Loading State
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting to DevSecOps Database...';
      }

      try {
        const response = await fetch('/api/contact', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
          },
          body: JSON.stringify({
            name,
            email,
            company,
            service,
            message
          })
        });

        const result = await response.json();

        if (response.ok && result.status === 'success') {
          formFeedback.className = 'form-feedback success';
          formFeedback.innerHTML = `
            <strong>✓ Consultation Request Confirmed!</strong><br>
            Thank you, <strong>${escapeHtml(name)}</strong>. Your request for <strong>${escapeHtml(company)}</strong> has been persisted to the platform database.<br>
            <span class="ref-badge">Tracking Reference: <code>${escapeHtml(result.reference_id)}</code></span> &bull; 
            <span class="ref-storage">Storage: <code>${escapeHtml(result.storage)}</code></span><br>
            A senior advisor will contact you at <strong>${escapeHtml(email)}</strong> within 24 business hours.
          `;
          formFeedback.style.display = 'block';
          contactForm.reset();

          // Refresh live telemetry count
          fetchTelemetry();
        } else {
          formFeedback.className = 'form-feedback error';
          formFeedback.textContent = result.error || 'Failed to submit request. Please try again.';
          formFeedback.style.display = 'block';
        }
      } catch (err) {
        console.error('Submission error:', err);
        formFeedback.className = 'form-feedback error';
        formFeedback.textContent = 'Network communication error. Please check your connectivity and try again.';
        formFeedback.style.display = 'block';
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Submit Free Advisory Request';
        }
      }
    });
  }

  // Safe HTML Escaping for rendered responses
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
});
