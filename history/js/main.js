// Delivery Flow App Evolution Showcase JS
// Budget: < 15KB. Zero external requests. Reduced motion safe.

(function () {
  'use strict';

  let currentViewport = 'desktop';
  let currentRoute = 'home';

  function init() {
    setupViewportToggles();
    setupRouteToggles();
    updateView();
  }

  function setupViewportToggles() {
    const btns = document.querySelectorAll('[data-action="set-viewport"]');
    btns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const vp = btn.getAttribute('data-viewport');
        if (!vp || vp === currentViewport) return;
        currentViewport = vp;
        btns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', String(active));
        });
        updateView();
      });
    });
  }

  function setupRouteToggles() {
    const btns = document.querySelectorAll('[data-action="set-route"]');
    btns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const route = btn.getAttribute('data-route');
        if (!route || route === currentRoute) return;
        currentRoute = route;
        btns.forEach((b) => {
          const active = b === btn;
          b.classList.toggle('active', active);
          b.setAttribute('aria-pressed', String(active));
        });
        updateView();
      });
    });
  }

  function updateView() {
    const images = document.querySelectorAll('img[data-route]');
    images.forEach((img) => {
      const imgRoute = img.getAttribute('data-route');
      const imgViewport = img.getAttribute('data-viewport');
      const matches = (imgRoute === currentRoute && imgViewport === currentViewport);
      img.style.display = matches ? 'block' : 'none';
    });

    const routeLabels = document.querySelectorAll('.active-route-label');
    routeLabels.forEach((el) => {
      el.textContent = currentRoute;
    });

    const vpLabels = document.querySelectorAll('.active-viewport-label');
    vpLabels.forEach((el) => {
      el.textContent = currentViewport === 'desktop' ? 'Desktop (1280px)' : 'Mobile (390px)';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
