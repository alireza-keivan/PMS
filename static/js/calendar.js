/* Booking calendar glue.
 *
 * The grid itself is plain server-rendered HTML (see
 * templates/bookings/_calendar_panel.html) - there is no timeline widget to
 * drive. All this file does is:
 *   1. define the Alpine component holding expand/collapse + the open booking
 *      card, with collapse state remembered per browser, and
 *   2. re-bind Alpine to markup HTMX swaps in, which Alpine doesn't do itself.
 *
 * Read-only: nothing here writes booking data.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "cal-collapsed-villas";

  function readCollapsed() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch (err) {
      return {}; // private browsing, cleared storage, corrupt value - just start open
    }
  }

  window.calendarGrid = function () {
    return {
      collapsed: readCollapsed(),
      detail: null,
      // { message, url } for the shared remove-villa/remove-room confirm
      // dialog - see _calendar_panel.html. null when no dialog is open.
      confirmTarget: null,

      // Villas start expanded; only an explicit collapse is remembered.
      isOpen: function (villaId) {
        return !this.collapsed[villaId];
      },

      toggle: function (villaId) {
        if (this.collapsed[villaId]) {
          delete this.collapsed[villaId];
        } else {
          this.collapsed[villaId] = true;
        }
        try {
          localStorage.setItem(STORAGE_KEY, JSON.stringify(this.collapsed));
        } catch (err) {
          /* storage unavailable - collapse still works for this page view */
        }
      },
    };
  };

  // HTMX replaces the panel's DOM wholesale; Alpine only walks the tree on
  // first load, so freshly swapped rows would otherwise ignore x-show/@click.
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (window.Alpine && evt.detail && evt.detail.target) {
      window.Alpine.initTree(evt.detail.target);
    }
  });
})();
