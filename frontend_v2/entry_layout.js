(() => {
  'use strict';

  function moveFirst(container, selector) {
    if (!container) return;
    const item = container.querySelector(selector);
    if (item && container.firstElementChild !== item) container.insertBefore(item, container.firstElementChild);
  }

  function orderNavigation() {
    // Search is the entry point for a new project, so it must also be the first
    // visible item rather than merely the screen selected behind an "Overview"
    // tab. Keep desktop and mobile navigation in the same order.
    moveFirst(document.querySelector('.main-nav'), '[data-view="tepsearch"]');
    moveFirst(document.querySelector('.mobile-tabs'), '[data-view="tepsearch"]');
  }

  function ensureTepStep() {
    // The photo OCR review still writes through the stock v2 form controls.
    // Keep the TEP form block rendered in the hidden Inputs view while the user
    // stays on Search; this lets the existing change handlers update form.draft
    // without creating a second mapping of TEP fields.
    try {
      if (typeof form === 'undefined' || !form || !Array.isArray(form.blocks)) return;
      const index = form.blocks.findIndex((block) => block && (
        block.kind === 'tep' || /ТЭП/i.test(String(block.title || ''))
      ));
      if (index < 0 || form.step === index) return;
      form.step = index;
      if (typeof renderStep === 'function') renderStep();
    } catch (error) {
      // app.js can still be initializing during the first paint; the next user
      // action calls this again after the form exists.
    }
  }

  function movePhotoToSearch() {
    const searchPanel = document.querySelector('#view-tepsearch .tep-search-panel');
    const photoPanel = document.getElementById('v2PhotoPanel');
    if (!searchPanel || !photoPanel) return;

    if (photoPanel.previousElementSibling !== searchPanel) {
      searchPanel.insertAdjacentElement('afterend', photoPanel);
    }
    // The old hook hid the panel whenever the Inputs wizard was not on its TEP
    // block. The panel now belongs to Search, so visibility is controlled by the
    // Search view itself and must not depend on that hidden wizard step.
    photoPanel.hidden = false;

    if (photoPanel.dataset.searchVisibilityGuard === '1') return;
    photoPanel.dataset.searchVisibilityGuard = '1';
    const guard = new MutationObserver(() => {
      if (photoPanel.hidden) photoPanel.hidden = false;
      if (photoPanel.previousElementSibling !== searchPanel) {
        searchPanel.insertAdjacentElement('afterend', photoPanel);
      }
    });
    guard.observe(photoPanel, { attributes: true, attributeFilter: ['hidden'] });
  }

  // Switch the hidden form to the TEP block before the old photo handler reads
  // or applies values. Capture phase runs before the button's original handler.
  document.addEventListener('click', (event) => {
    if (event.target.closest('#v2CameraButton, #v2GalleryButton, #v2PhotoApply')) {
      ensureTepStep();
      movePhotoToSearch();
    }
  }, true);

  orderNavigation();
  movePhotoToSearch();

  // upgrade.js creates the photo panel and app.js builds form blocks
  // asynchronously. Watch only DOM structure; the panel gets its own tiny
  // attribute guard once it appears.
  const observer = new MutationObserver(() => {
    orderNavigation();
    movePhotoToSearch();
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();
