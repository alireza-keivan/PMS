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

  /* Search box in the calendar toolbar.
   *
   * The suggestion list is server-rendered and swapped in by HTMX on every
   * keystroke, so there is no client-side copy of the results to track an
   * index against. Instead we read the links straight out of the DOM each
   * time a key is pressed, and mark the highlighted one with a class - that
   * survives nothing, which is exactly right: a new list means a new
   * highlight, starting from nothing again.
   */
  var SEARCH_ACTIVE_CLASSES = ["bg-teal-50", "ring-1", "ring-inset", "ring-teal-500"];

  window.calendarSearch = function () {
    return {
      searchOpen: false,
      index: -1,

      // $root, not $el: these run from the input's own keydown handlers, where
      // $el is the input rather than the wrapper holding the results.
      items: function () {
        var box = this.$root.querySelector("#calendar-search-suggestions");
        return box ? Array.prototype.slice.call(box.querySelectorAll("a")) : [];
      },

      paint: function () {
        var self = this;
        this.items().forEach(function (link, i) {
          SEARCH_ACTIVE_CLASSES.forEach(function (cls) {
            link.classList.toggle(cls, i === self.index);
          });
        });
      },

      // A fresh list arrived - drop the old highlight.
      reset: function () {
        this.index = -1;
        this.paint();
      },

      move: function (step) {
        var items = this.items();
        if (!items.length) return;
        this.searchOpen = true;
        // Wraps around at both ends so holding a key never dead-ends.
        if (this.index < 0) this.index = step > 0 ? 0 : items.length - 1;
        else this.index = (this.index + step + items.length) % items.length;
        this.paint();
        items[this.index].scrollIntoView({ block: "nearest" });
      },

      choose: function (event) {
        var items = this.items();
        if (this.index < 0 || !items[this.index]) return; // let the form do its normal thing
        event.preventDefault();
        items[this.index].click();
        this.close();
      },

      close: function () {
        this.searchOpen = false;
        this.reset();
      },
    };
  };

  window.calendarGrid = function () {
    return {
      collapsed: readCollapsed(),
      detail: null,
      // Armed by the "Block dates" button (after its confirm dialog). While
      // it's on, the cursor over the grid turns into a hand and the next drag
      // across empty days picks the range to hold - see the block-drag
      // section at the bottom of this file. It switches itself off again once
      // that drag is done with, so it's never a mode you get stuck in.
      blockMode: false,

      startBlockMode: function () {
        this.blockMode = true;
        document.body.classList.add("cal-block-mode");
      },

      endBlockMode: function () {
        this.blockMode = false;
        document.body.classList.remove("cal-block-mode");
      },

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
    // Only the calendar panel's own swaps can need a jump. The search
    // dropdown swaps into #calendar-search-suggestions on every keystroke,
    // and jumping on those is what yanked the view back to the last guest
    // the moment you clicked the box to type a new name.
    var swapped = evt.detail && evt.detail.target;
    if (swapped && swapped.id !== "calendar-search-suggestions") {
      focusSearchedBooking();
      var trigger = evt.detail.requestConfig && evt.detail.requestConfig.elt;
      if (trigger && trigger.hasAttribute && trigger.hasAttribute("data-cal-today")) {
        revealToday();
      }
    }
  });

  // ---- the Today button's landing ---------------------------------------
  //
  // Today reloads the grid at a range starting on today, so the whole panel
  // is replaced at once and the change reads as a blink with nothing saying
  // where today ended up. This eases that: the date strip glides sideways to
  // today's column (on phones, where the grid really does scroll - on
  // desktop the whole range is already on screen and there is nothing to
  // slide) and the column glows for a moment as it settles.
  //
  // Only runs on swaps started by the Today button itself, never on a plain
  // page load or the arrow buttons - a flash on every navigation would stop
  // meaning anything.

  function revealToday() {
    var col = document.querySelector("[data-today-col]");
    if (!col) return; // today is outside the rendered range - nothing to show

    var scroller = col.closest(".cal-scroll");
    if (scroller) {
      // Line the column up just right of the pinned villa-name column rather
      // than under it. getBoundingClientRect over offsetLeft because the
      // sticky name column and the grid's own offset parents make offsetLeft
      // unreliable here.
      var nameCol = scroller.querySelector(".cal-namecol");
      var nameWidth = nameCol ? nameCol.getBoundingClientRect().width : 0;
      var left =
        scroller.scrollLeft +
        col.getBoundingClientRect().left -
        scroller.getBoundingClientRect().left -
        nameWidth;
      try {
        scroller.scrollTo({ left: left, behavior: "smooth" });
      } catch (err) {
        scroller.scrollLeft = left; // older browsers: jump, no glide
      }
    }

    col.classList.remove("cal-today-flash");
    // Restart the animation on a repeat press: the class has to actually
    // leave the element for a frame or the browser keeps the finished run.
    window.requestAnimationFrame(function () {
      col.classList.add("cal-today-flash");
      window.setTimeout(function () {
        col.classList.remove("cal-today-flash");
      }, 950);
    });
  }

  // ---- jump to a guest picked from the search dropdown -------------------
  //
  // The search box (see _calendar_panel.html + BookingSearchSuggestionsView)
  // navigates the calendar to a range starting on that booking's check-in
  // date with ?focus=<id>; the grid renders data-focus-booking-id so this
  // runs after every swap (and on first load) to scroll the bar into view
  // and flash it, rather than making staff hunt for it in the new range.

  function focusSearchedBooking() {
    var grid = document.getElementById("calendar-grid");
    var id = grid && grid.dataset.focusBookingId;
    if (!id) return;
    var bar = grid.querySelector('[data-booking-id="' + id + '"]');
    if (!bar) return;
    // Jump once per grid. Without this, anything that re-runs this (a
    // re-render, a later swap) would drag the view back to a guest the
    // person has already moved on from.
    delete grid.dataset.focusBookingId;

    // hx-push-url put ?focus=<id> in the address bar so this jump survives
    // a fresh navigation. Once the jump has happened, drop it from the URL -
    // otherwise refreshing the page (or copying the link) replays the same
    // jump-to-guest every time instead of just showing the calendar.
    if (window.history && window.history.replaceState) {
      var url = new URL(window.location.href);
      if (url.searchParams.has("focus")) {
        url.searchParams.delete("focus");
        window.history.replaceState(window.history.state, "", url);
      }
    }

    // The bar is always in the DOM, but its villa may be collapsed (that
    // choice is remembered per browser in localStorage), which leaves it
    // display:none - scrolling to it then does nothing at all. That is why
    // the jump looked like it worked for some guests and not others: it
    // depended entirely on whether that guest's villa happened to be open.
    // So open the villa first, and only then scroll.
    var host = bar.closest("[data-villa-id]");
    var villaId = host && host.dataset.villaId;
    var root = document.querySelector('[x-data="calendarGrid()"]');
    var state = null;
    try {
      state = window.Alpine && root ? window.Alpine.$data(root) : null;
    } catch (err) {
      state = null; // Alpine not ready yet - fall through to the plain scroll
    }
    if (state && villaId && !state.isOpen(villaId)) state.toggle(villaId);

    var reveal = function () {
      // Wait a frame so Alpine's x-show/x-cloak collapse toggling (the
      // expand above, plus the initTree run just before this in the same
      // htmx:afterSwap handler) has actually applied to layout - scrolling
      // against stale positions is what left this only moving the view
      // horizontally, since the date columns don't shift when rows above the
      // bar collapse/expand but its vertical offset does.
      window.requestAnimationFrame(function () {
        window.requestAnimationFrame(function () {
          bar.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
          bar.classList.add("cal-search-focus");
          window.setTimeout(function () {
            bar.classList.remove("cal-search-focus");
          }, 750);
        });
      });
    };

    if (window.Alpine && window.Alpine.nextTick) {
      window.Alpine.nextTick(reveal);
    } else {
      reveal();
    }
  }

  // On a full page load (opening a ?focus=... URL directly, or a refresh)
  // this file runs before alpine.min.js does, so the rows are still hidden
  // behind x-cloak and there is no Alpine to expand a collapsed villa with -
  // wait for Alpine to finish starting instead of scrolling into nothing.
  if (window.Alpine && window.Alpine.version) {
    focusSearchedBooking();
  } else {
    document.addEventListener("alpine:initialized", focusSearchedBooking, { once: true });
  }

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
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function daysBetween(fromIso, toIso) {
    var a = new Date(fromIso + "T00:00:00");
    var b = new Date(toIso + "T00:00:00");
    if (isNaN(a) || isNaN(b)) return null;
    return Math.round((b - a) / 86400000);
  }

  function fillTemplate(str, values) {
    Object.keys(values).forEach(function (key) {
      str = str.split("%(" + key + ")s").join(values[key]);
    });
    return str;
  }

  // Re-fetching the whole panel replaces content above the fold too, which
  // otherwise leaves the browser's own scroll-anchor logic free to reset the
  // page to the top - restore the scroll position the user was looking at.
  function reloadPanel() {
    var scrollX = window.scrollX;
    var scrollY = window.scrollY;
    return window.htmx.ajax("GET", window.location.pathname + window.location.search, {
      target: "#calendar-panel", swap: "innerHTML",
    }).then(function () {
      window.scrollTo(scrollX, scrollY);
    });
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
    var dayWidth = rowRect.width / days;
    var origStyle = bar.getAttribute("style");

    // A stay that runs past either edge of the visible window is drawn
    // clipped to that edge (see _build_bar server-side). Dragging that clipped
    // shape would show a two-day box for a week-long stay, so for the duration
    // of the drag the bar is re-laid-out at its true length - it can now stick
    // out past the window edges, which is exactly the point.
    var windowStart = grid.dataset.start;
    var trueStart = windowStart ? daysBetween(windowStart, bar.dataset.checkIn) : null;
    var trueEnd = windowStart ? daysBetween(windowStart, bar.dataset.checkOut) : null;
    var origLeftPx, origWidthPx;
    if (trueStart === null || trueEnd === null) {
      var barRect = bar.getBoundingClientRect();
      origLeftPx = barRect.left - rowRect.left;
      origWidthPx = barRect.width;
    } else {
      origLeftPx = trueStart * dayWidth + 3;
      origWidthPx = Math.max(1, trueEnd - trueStart) * dayWidth - 6;
      bar.style.left = origLeftPx + "px";
      bar.style.width = origWidthPx + "px";
      bar.style.zIndex = "5"; // sits above neighbouring bars while it overhangs
    }

    var startX = downEvent.clientX;
    var moved = false;
    var targetRow = homeRow;
    var finalDays = 0; // day-delta actually applied, after clamping - what gets sent to the server

    downEvent.preventDefault();
    bar.setPointerCapture(downEvent.pointerId);
    // elementFromPoint below needs to see the row *under* the cursor, but the
    // bar itself is what's sitting at the cursor (it's the thing following the
    // pointer) - without this it flip-flops between the bar's own home row and
    // the real hovered row, which reads as the box jittering between rows.
    if (mode === "move") bar.style.pointerEvents = "none";

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
        finalDays = dayDelta;

        var hovered = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
        var hoveredRow = hovered && hovered.closest("[data-room-row-id]");
        if (hoveredRow && hoveredRow.dataset.villaId === homeRow.dataset.villaId && hoveredRow !== targetRow) {
          highlight(hoveredRow);
        }

        // Vertical offset follows whichever row is currently highlighted,
        // so the bar visually snaps into the hovered room row instead of
        // only ever sliding sideways within its original row.
        var offsetY = targetRow.getBoundingClientRect().top - rowRect.top;
        bar.style.transform = "translate(" + finalDays * dayWidth + "px, " + offsetY + "px)";
      } else if (mode === "start") {
        var maxLeft = origLeftPx + origWidthPx - dayWidth;
        var newLeft = Math.min(maxLeft, origLeftPx + dayDelta * dayWidth);
        finalDays = Math.round((newLeft - origLeftPx) / dayWidth);
        bar.style.left = newLeft + "px";
        bar.style.width = origLeftPx + origWidthPx - newLeft + "px";
      } else if (mode === "end") {
        var newWidth = Math.max(dayWidth, origWidthPx + dayDelta * dayWidth);
        finalDays = Math.round((newWidth - origWidthPx) / dayWidth);
        bar.style.width = newWidth + "px";
      }
    }

    function onUp() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      bar.style.pointerEvents = "";

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
                reloadPanel();
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

  /* Drag across empty days to block a room.
   *
   * "Block dates" used to be a separate page with its own villa/room/date
   * form. It isn't any more: you press on an empty day in a room's row, drag
   * to the last day you want held, and confirm - which is where you were
   * already looking, and needs no re-typing of what the grid already knows.
   *
   * Same rule as the reschedule drag above: this only ever *proposes* a
   * range. Nothing is written until the shared confirm dialog is accepted,
   * the server re-checks the room, the dates and the overlap
   * (apps/bookings/views.py BlockDatesView), and the panel is then reloaded
   * from the server rather than drawn from the client's own math.
   */
  // Escape is the way out of block mode without having to find the button
  // again (the hint strip's Cancel is the other).
  document.addEventListener("keydown", function (evt) {
    if (evt.key !== "Escape") return;
    var data = alpineData();
    if (data && data.blockMode) data.endBlockMode();
  });

  panel.addEventListener("pointerdown", function (downEvent) {
    if (downEvent.button !== 0) return;             // right/middle click isn't a drag
    if (downEvent.target.closest("[data-booking-id]")) return; // the reschedule drag owns bars

    // Only after the "Block dates" button has been pressed and confirmed -
    // otherwise a stray drag across the grid would start proposing blocks.
    var armed = alpineData();
    if (!armed || !armed.blockMode) return;

    var row = downEvent.target.closest("[data-room-row-id]");
    var grid = document.getElementById("calendar-grid");
    if (!row || !grid) return;

    var days = parseInt(grid.dataset.days, 10) || 14;
    var windowStart = grid.dataset.start;
    if (!windowStart) return;

    var rowRect = row.getBoundingClientRect();
    var dayWidth = rowRect.width / days;

    function dayAt(clientX) {
      var idx = Math.floor((clientX - rowRect.left) / dayWidth);
      return Math.max(0, Math.min(days - 1, idx));
    }

    var anchorDay = dayAt(downEvent.clientX);
    var lastDay = anchorDay;
    var moved = false;

    // The proposed range, drawn straight into the row so it reads like any
    // other bar. Removed again whichever way the drag ends.
    var ghost = document.createElement("div");
    ghost.className = "cal-block-ghost";
    row.appendChild(ghost);

    function paint() {
      var from = Math.min(anchorDay, lastDay);
      var to = Math.max(anchorDay, lastDay);
      ghost.style.left = from * dayWidth + 3 + "px";
      ghost.style.width = (to - from + 1) * dayWidth - 6 + "px";
    }
    paint();

    document.body.classList.add("cal-dragging");
    downEvent.preventDefault();

    function cleanup() {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      document.body.classList.remove("cal-dragging");
      if (ghost.parentNode) ghost.parentNode.removeChild(ghost);
    }

    function onMove(moveEvent) {
      if (Math.abs(moveEvent.clientX - downEvent.clientX) > 4) moved = true;
      lastDay = dayAt(moveEvent.clientX);
      paint();
    }

    function onUp() {
      var from = Math.min(anchorDay, lastDay);
      var to = Math.max(anchorDay, lastDay);
      cleanup();

      var data = alpineData();
      if (!data) return;

      // A plain click on an empty day is not a range - nothing to propose, so
      // stay armed and let them try the drag again.
      if (!moved) return;

      var checkIn = addDays(windowStart, from);
      var checkOut = addDays(windowStart, to + 1); // free again the morning after
      data.endBlockMode(); // one block per press of the button

      data.confirmTarget = {
        message: fillTemplate(grid.dataset.msgBlock, {
          room: row.dataset.roomName,
          dates: shortDate(checkIn) + " – " + shortDate(checkOut),
        }),
        mode: "callback",
        onConfirm: function () {
          fetch(grid.dataset.blockUrl, {
            method: "POST",
            headers: Object.assign({ "Content-Type": "application/x-www-form-urlencoded" }, csrfHeaders()),
            body: new URLSearchParams({
              room: row.dataset.roomRowId, check_in: checkIn, check_out: checkOut,
            }),
          })
            .then(function (r) { return r.json().then(function (body) { return { ok: r.ok && body.ok, body: body }; }); })
            .then(function (result) {
              if (result.ok) reloadPanel();
              else window.alert(result.body.error || grid.dataset.msgBlockFailed);
            })
            .catch(function () { window.alert(grid.dataset.msgBlockFailed); });
        },
      };
    }

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  });
})();
