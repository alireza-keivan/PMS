/* Booking calendar glue.
 *
 * The grid itself is plain server-rendered HTML (see
 * templates/bookings/_calendar_panel.html) - there is no timeline widget to
 * drive. This file:
 *   1. defines the Alpine component holding expand/collapse + the open
 *      booking card + the one shared confirm dialog, with collapse state
 *      remembered per browser,
 *   2. re-binds Alpine to markup HTMX swaps in, which Alpine doesn't do
 *      itself, and
 *   3. drives drag-to-move / drag-to-resize on a booking bar - see the
 *      bottom of this file. A drag only ever *proposes* a change: nothing
 *      is written until the shared confirm dialog is accepted, and the
 *      panel is reloaded from the server afterwards rather than trusting
 *      the client's own math - see CLAUDE.md rule 5.
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
      // { message, mode, url, onConfirm, onCancel } for the one shared
      // confirm dialog in _calendar_panel.html. mode is one of:
      //   "form"     - a real POST via the dialog's own <form>, e.g. remove
      //                villa/room/booking
      //   "navigate" - confirm, then a plain GET navigation, e.g. add
      //                villa/room/booking
      //   "callback" - confirm runs onConfirm() directly, e.g. reschedule
      // onCancel (optional) fires on ANY dismissal that isn't a confirm -
      // used by the drag flow to snap a bar back to where it started.
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

      cancelConfirm: function () {
        if (this.confirmTarget && this.confirmTarget.onCancel) this.confirmTarget.onCancel();
        this.confirmTarget = null;
      },
      confirmNavigate: function () {
        if (this.confirmTarget && this.confirmTarget.mode === "navigate") {
          window.location.href = this.confirmTarget.url;
        }
      },
      confirmCallback: function () {
        var target = this.confirmTarget;
        this.confirmTarget = null;
        if (target && target.mode === "callback" && target.onConfirm) target.onConfirm();
      },
    };
  };

  // HTMX replaces the panel's DOM wholesale; Alpine only walks the tree on
  // first load, so freshly swapped rows would otherwise ignore x-show/@click.
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (window.Alpine && evt.detail && evt.detail.target) {
      window.Alpine.initTree(evt.detail.target);
    }
    updateStickyOffsets();
    observeStickyHeaders();
  });

  // ---- keep the stacked sticky headers (date / area / villa) in sync ----
  //
  // The area and villa header rows stick just below whatever sticky rows sit
  // above them (see _calendar_panel.html), using top offsets that read from
  // --cal-date-h / --cal-area-h custom properties on #calendar-grid rather
  // than hardcoded pixel guesses - those would drift under browser zoom,
  // different fonts, or the longer Bahasa Indonesia strings, silently
  // reopening the same "header slides under the wrong row" bug.

  var stickyObserver = window.ResizeObserver ? new ResizeObserver(updateStickyOffsets) : null;

  function updateStickyOffsets() {
    var grid = document.getElementById("calendar-grid");
    if (!grid) return;
    var dateHeader = document.getElementById("cal-date-header");
    var areaHeader = grid.querySelector(".cal-area-header");
    if (dateHeader) grid.style.setProperty("--cal-date-h", dateHeader.offsetHeight + "px");
    grid.style.setProperty("--cal-area-h", (areaHeader ? areaHeader.offsetHeight : 0) + "px");
  }

  function observeStickyHeaders() {
    if (!stickyObserver) return;
    stickyObserver.disconnect();
    var grid = document.getElementById("calendar-grid");
    if (!grid) return;
    var dateHeader = document.getElementById("cal-date-header");
    var areaHeader = grid.querySelector(".cal-area-header");
    if (dateHeader) stickyObserver.observe(dateHeader);
    if (areaHeader) stickyObserver.observe(areaHeader);
  }

  updateStickyOffsets();
  observeStickyHeaders();
  window.addEventListener("resize", updateStickyOffsets);

  // ---- drag to move / resize a booking bar -------------------------------
  //
  // #calendar-panel itself is never replaced by HTMX (only its contents are,
  // via hx-swap="innerHTML"), so one delegated pointerdown listener here
  // covers every swap without needing to re-attach anything on
  // htmx:afterSwap the way the Alpine re-init above has to.

  var panel = document.getElementById("calendar-panel");
  if (!panel || !window.PointerEvent) return; // no calendar on this page, or too old a browser

  function csrfHeaders() {
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}");
    } catch (err) {
      return {};
    }
  }

  function shortDate(iso) {
    var d = new Date(iso + "T00:00:00");
    var lang = document.documentElement.lang || "en";
    try {
      return new Intl.DateTimeFormat(lang, { day: "numeric", month: "short" }).format(d);
    } catch (err) {
      return iso; // unsupported locale tag - fall back to something rather than throw
    }
  }

  function addDays(iso, days) {
    var d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + days);
    return d.toISOString().slice(0, 10);
  }

  function fillTemplate(str, values) {
    Object.keys(values).forEach(function (key) {
      str = str.split("%(" + key + ")s").join(values[key]);
    });
    return str;
  }

  function alpineData() {
    var root = panel.closest("[x-data]");
    return root && window.Alpine ? window.Alpine.$data(root) : null;
  }

  panel.addEventListener("pointerdown", function (downEvent) {
    var bar = downEvent.target.closest("[data-booking-id]");
    if (!bar) return;

    var homeRow = bar.closest("[data-room-row-id]");
    var grid = document.getElementById("calendar-grid");
    if (!homeRow || !grid) return;

    var edge = downEvent.target.closest("[data-edge]");
    var mode = edge ? edge.dataset.edge : "move"; // "start" | "end" | "move"

    var days = parseInt(grid.dataset.days, 10) || 14;
    var rowRect = homeRow.getBoundingClientRect();
    var barRect = bar.getBoundingClientRect();
    var dayWidth = rowRect.width / days;
    var origLeftPx = barRect.left - rowRect.left;
    var origWidthPx = barRect.width;
    var origStyle = bar.getAttribute("style");

    var startX = downEvent.clientX;
    var moved = false;
    var targetRow = homeRow;
    var finalDays = 0; // day-delta actually applied, after clamping - what gets sent to the server

    downEvent.preventDefault();
    bar.setPointerCapture(downEvent.pointerId);

    function highlight(row) {
      if (targetRow !== homeRow) targetRow.style.backgroundColor = "";
      targetRow = row;
      if (targetRow !== homeRow) {
        targetRow.style.backgroundColor = "rgba(198, 113, 57, .12)"; // --color-accent, low opacity
      }
    }

    function revert() {
      bar.setAttribute("style", origStyle);
      highlight(homeRow);
    }

    function onMove(moveEvent) {
      var dx = moveEvent.clientX - startX;
      if (Math.abs(dx) > 4) moved = true;
      var dayDelta = Math.round(dx / dayWidth);

      if (mode === "move") {
        var offset = Math.max(-origLeftPx, Math.min(rowRect.width - origWidthPx - origLeftPx, dayDelta * dayWidth));
        finalDays = Math.round(offset / dayWidth);
        bar.style.transform = "translateX(" + finalDays * dayWidth + "px)";

        var hovered = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
        var hoveredRow = hovered && hovered.closest("[data-room-row-id]");
        if (hoveredRow && hoveredRow.dataset.villaId === homeRow.dataset.villaId && hoveredRow !== targetRow) {
          highlight(hoveredRow);
        }
      } else if (mode === "start") {
        var maxLeft = origLeftPx + origWidthPx - dayWidth;
        var newLeft = Math.max(0, Math.min(maxLeft, origLeftPx + dayDelta * dayWidth));
        finalDays = Math.round((newLeft - origLeftPx) / dayWidth);
        bar.style.left = newLeft + "px";
        bar.style.width = origLeftPx + origWidthPx - newLeft + "px";
      } else if (mode === "end") {
        var maxWidth = rowRect.width - origLeftPx;
        var newWidth = Math.max(dayWidth, Math.min(maxWidth, origWidthPx + dayDelta * dayWidth));
        finalDays = Math.round((newWidth - origWidthPx) / dayWidth);
        bar.style.width = newWidth + "px";
      }
    }

    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);

      if (moved) {
        // A real drag happened - the click Alpine's own @click would still
        // receive right after this shouldn't also open the detail popover.
        bar.addEventListener("click", function (e) { e.stopImmediatePropagation(); }, { capture: true, once: true });
      }

      var roomChanged = targetRow !== homeRow;
      if (finalDays === 0 && !roomChanged) {
        revert(); // no real change - snap back silently, no dialog
        return;
      }

      var newCheckIn = mode === "start" ? addDays(bar.dataset.checkIn, finalDays) : bar.dataset.checkIn;
      var newCheckOut = mode === "end" ? addDays(bar.dataset.checkOut, finalDays) : bar.dataset.checkOut;
      if (mode === "move") {
        newCheckIn = addDays(bar.dataset.checkIn, finalDays);
        newCheckOut = addDays(bar.dataset.checkOut, finalDays);
      }
      var newRoomId = roomChanged ? targetRow.dataset.roomRowId : bar.dataset.roomId;

      var dates = shortDate(newCheckIn) + " – " + shortDate(newCheckOut);
      var template = mode === "move"
        ? (roomChanged ? grid.dataset.msgMoveNewRoom : grid.dataset.msgMoveSameRoom)
        : grid.dataset.msgResize;
      var message = fillTemplate(template, { guest: bar.dataset.guest, room: targetRow.dataset.roomName, dates: dates });
      if (!bar.dataset.detail) {
        message += " " + fillTemplate(grid.dataset.msgSyncWarning, { channel: bar.dataset.channel });
      }

      var data = alpineData();
      if (!data) { revert(); return; }

      data.confirmTarget = {
        message: message,
        mode: "callback",
        onCancel: revert,
        onConfirm: function () {
          fetch(bar.dataset.rescheduleUrl, {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/x-www-form-urlencoded" }, csrfHeaders()),
            body: new URLSearchParams({ check_in: newCheckIn, check_out: newCheckOut, room_id: newRoomId || "" }),
          })
            .then(function (r) { return r.json().then(function (body) { return { ok: r.ok && body.ok, body: body }; }); })
            .then(function (result) {
              if (result.ok) {
                window.htmx.ajax("GET", window.location.pathname + window.location.search, {
                  target: "#calendar-panel", swap: "innerHTML",
                });
              } else {
                revert();
                window.alert(result.body.error || grid.dataset.msgRescheduleFailed);
              }
            })
            .catch(function () {
              revert();
              window.alert(grid.dataset.msgRescheduleFailed);
            });
        },
      };
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
})();
