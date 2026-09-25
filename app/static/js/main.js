/**
 * ABC Free Consultants - Client Application Script
 * Vanilla JavaScript for UI interactions, accessibility, and form validation
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

  // 4. Contact Form Validation & Submission Handling
  const contactForm = document.getElementById('consultation-form');
  const formFeedback = document.getElementById('form-feedback');
  const submitBtn = document.getElementById('submit-btn');

  if (contactForm && formFeedback) {
    contactForm.addEventListener('submit', (event) => {
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

      if (!name) {
        nameInput?.classList.add('invalid');
        hasError = true;
        errorMessage = 'Please provide your full name.';
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

      // Simulate submission UX (Accessible textContent, no innerHTML vulnerability)
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Submitting Request...';
      }

      setTimeout(() => {
        formFeedback.className = 'form-feedback success';
        formFeedback.textContent = `Thank you, ${name}! Your complimentary consultation request for ${company} has been received. A senior advisor will contact you at ${email} within 24 hours.`;
        formFeedback.style.display = 'block';

        contactForm.reset();

        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Submit Free Advisory Request';
        }
      }, 600);
    });
  }
});
