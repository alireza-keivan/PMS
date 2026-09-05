/* Time picker - the "Time Picker" card from the design handoff.
 *
 * Drives templates/partials/_time_picker.html. Read that file first: the real
 * time input is the source of truth, this only fills it in.
 *
 * Deliberately plain: no framework, no build step, no dependency. It attaches
 * to every [data-time-picker] on the page, so a page can hold more than one
 * (check-in and check-out sit side by side). If the script never loads, the
 * partial's native time box is still there and the form still works.
 *
 * Three wheels: hour, minute, am/pm. The middle row of each is the chosen one.
 * Minutes step by whatever data-step says (30 by default), so with 30 there
 * are only two rows to choose between: 00 and 30.
 *
 * Each wheel is a short scrolling strip that snaps a row to the middle, so a
 * flick carries on and eases to a stop the way a phone's alarm wheel does,
 * using the browser's own scrolling rather than an animation of our own. The
 * row heights here (ROW) and in .tp-row/.tp-pad in src.css must match.
 *
 * The am/pm words come from the browser's own Intl, in the page's language
 * (<html lang>), so there is nothing to translate here.
 */
(function () {
  "use strict";

  function pad2(n) {
    return n < 10 ? "0" + n : "" + n;
  }

  function lang() {
    return document.documentElement.lang || undefined;
  }

  // "2:00 PM" in the page's language. Always 12-hour, to match the wheels.
  function label(hour24, minute) {
    var d = new Date(2000, 0, 1, hour24, minute);
    return d.toLocaleTimeString(lang(), {
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    });
  }

  // The two day-period words ("AM"/"PM", whatever this language calls them),
  // pulled out of a formatted time rather than hard-coded.
  function periodWords() {
    function word(hour24) {
      var d = new Date(2000, 0, 1, hour24, 0);
      try {
        var parts = new Intl.DateTimeFormat(lang(), {
          hour: "numeric",
          hour12: true,
        }).formatToParts(d);
        for (var i = 0; i < parts.length; i++) {
          if (parts[i].type === "dayPeriod") return parts[i].value;
        }
      } catch (e) {
        /* falls through to the plain words below */
      }
      return hour24 < 12 ? "AM" : "PM";
    }
    return [word(9), word(15)];
  }

  function setup(root) {
    var input = root.querySelector('input[type="time"], input[type="text"]');
    if (!input) return;

    var native = root.querySelector(".tp-native");
    var trigger = root.querySelector("[data-tp-trigger]");
    var triggerValue = root.querySelector("[data-tp-trigger-value]");
    var panel = root.querySelector(".tp-panel");
    var cols = {
      hour: root.querySelector('[data-tp-col="hour"]'),
      minute: root.querySelector('[data-tp-col="minute"]'),
      period: root.querySelector('[data-tp-col="period"]'),
    };
    if (!trigger || !panel || !cols.hour) return;

    var step = parseInt(root.dataset.step, 10) || 30;
    var periods = periodWords();

    var hourList = [12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11];
    var minuteList = [];
    for (var m = 0; m < 60; m += step) minuteList.push(m);

    // What the wheels currently show. Read out of the input on the way in and
    // written back to it on every change.
    var state = { hour: 12, minute: 0, period: 0, filled: false, open: false };

    function readInput() {
      var parts = (input.value || "").split(":");
      if (parts.length < 2) {
        state.filled = false;
        return;
      }
      var h = parseInt(parts[0], 10);
      var mm = parseInt(parts[1], 10);
      if (isNaN(h) || isNaN(mm)) {
        state.filled = false;
        return;
      }
      state.period = h < 12 ? 0 : 1;
      state.hour = h % 12 === 0 ? 12 : h % 12;
      // A time that doesn't land on a step (say an old 14:15 with 30-minute
      // steps) is shown at the nearest step below rather than dropped.
      state.minute = minuteList.reduce(function (best, v) {
        return v <= mm ? v : best;
      }, minuteList[0]);
      state.filled = true;
    }

    function hour24() {
      var h = state.hour % 12;
      return state.period === 1 ? h + 12 : h;
    }

    function paintTrigger() {
      if (state.filled) {
        triggerValue.textContent = label(hour24(), state.minute);
        triggerValue.classList.remove("text-ink-600");
      } else {
        triggerValue.textContent = triggerValue.dataset.emptyText;
        triggerValue.classList.add("text-ink-600");
      }
    }

    // ---- The wheels ------------------------------------------------------
    // Each wheel is a real scrolling strip, not a list redrawn step by step.
    // That is what makes it glide the way the alarm wheel on a phone does: a
    // finger flick gets the browser's own momentum, the rows snap to the
    // middle on their own (CSS scroll-snap), and the fade and shrink of the
    // rows either side is recalculated from the scroll position as it moves,
    // so it eases rather than jumping between two looks.
    //
    // Every row is the same height. That matters: the chosen row is simply
    // whichever one the scroll position lands on, round(scrollTop / ROW).
    var ROW = 24; // must match .tp-row in src.css
    var PAD = 2;  // blank rows above and below, so row one can reach the middle

    var wheels = [
      {
        el: cols.hour,
        list: hourList,
        wrap: true, // hours turn round for ever, 11 -> 12 -> 1
        index: function () { return hourList.indexOf(state.hour); },
        pick: function (i) { state.hour = hourList[i]; },
        format: function (v) { return "" + v; },
      },
      {
        el: cols.minute,
        list: minuteList,
        // Only two rows at half-hour steps, and two rows spinning round and
        // round reads as a glitch. It wraps only if there are enough of them.
        wrap: minuteList.length > 5,
        index: function () { return Math.max(0, minuteList.indexOf(state.minute)); },
        pick: function (i) { state.minute = minuteList[i]; },
        format: pad2,
      },
      {
        el: cols.period,
        list: periods,
        wrap: false,
        index: function () { return state.period; },
        pick: function (i) { state.period = i; },
        format: function (v) { return v; },
      },
    ];

    // While we are the ones writing to the input, ignore the `change` we
    // caused - otherwise it would reposition the wheel mid-spin.
    var writing = false;

    function writeBack() {
      writing = true;
      input.value = pad2(hour24()) + ":" + pad2(state.minute);
      input.dispatchEvent(new Event("change", { bubbles: true }));
      writing = false;
    }

    // A wrapping wheel holds three copies of its list end to end. Spinning
    // never actually reaches an edge, because once it settles in the first or
    // last copy we move it silently back to the middle one - same rows on
    // screen, plenty of room left to keep turning.
    function build(wheel) {
      var el = wheel.el;
      var copies = wheel.wrap ? 3 : 1;
      wheel.display = [];
      for (var c = 0; c < copies; c++) {
        for (var i = 0; i < wheel.list.length; i++) wheel.display.push(i);
      }
      el.innerHTML = "";
      el.appendChild(spacer());
      wheel.rows = wheel.display.map(function (listIndex, pos) {
        var btn = document.createElement("button");
        btn.type = "button";
        btn.tabIndex = -1;
        btn.className = "tp-row";
        btn.textContent = wheel.format(wheel.list[listIndex]);
        btn.addEventListener("click", function () {
          // A flick that happened to end on a row is a spin, not a tap.
          if (wheel.dragged) return;
          goTo(wheel, pos, true);
        });
        el.appendChild(btn);
        return btn;
      });
      el.appendChild(spacer());
    }

    function spacer() {
      var d = document.createElement("div");
      d.className = "tp-pad";
      d.setAttribute("aria-hidden", "true");
      return d;
    }

    function goTo(wheel, pos, smooth) {
      wheel.el.scrollTo({ top: pos * ROW, behavior: smooth ? "smooth" : "auto" });
    }

    // Where the wheel is right now, as a fractional row - 3.5 means halfway
    // between the fourth and fifth. Everything visual is drawn from this, so
    // it stays smooth all the way through a spin.
    function position(wheel) {
      return wheel.el.scrollTop / ROW;
    }

    // The row in the middle shrinks and fades the further it is from centre.
    // Size is a transform, never a font size - changing the font would change
    // the row's height and the whole strip would shuffle as it moved.
    function paintRows(wheel) {
      var pos = position(wheel);
      wheel.rows.forEach(function (btn, i) {
        var d = Math.min(Math.abs(i - pos), 2.4);
        btn.style.transform = "scale(" + (1 - 0.26 * d).toFixed(3) + ")";
        btn.style.opacity = (1 - 0.38 * d).toFixed(3);
        btn.style.fontWeight = d < 0.5 ? "700" : "400";
      });
    }

    // Called once the wheel has stopped: take whatever row it landed on as
    // the choice, and move a wrapping wheel back to its middle copy.
    function settle(wheel) {
      var len = wheel.list.length;
      var pos = Math.round(position(wheel));
      pos = Math.max(0, Math.min(wheel.display.length - 1, pos));
      // Opening the panel scrolls the wheels into place, which lands here too.
      // Landing back on the row that was already chosen is not a choice, so an
      // empty field stays empty until something is actually turned.
      if (!state.filled && wheel.display[pos] === wheel.index()) return;
      wheel.pick(wheel.display[pos]);
      state.filled = true;
      writeBack();
      paintTrigger();
      if (wheel.wrap && (pos < len || pos >= 2 * len)) {
        wheel.el.scrollTop = (len + (pos % len)) * ROW;
        paintRows(wheel);
      }
    }

    // Put every wheel where the current time says it should be, with no
    // animation. Used on open, and when something else fills the input in.
    function reposition() {
      wheels.forEach(function (wheel) {
        var pos = wheel.index() + (wheel.wrap ? wheel.list.length : 0);
        wheel.el.scrollTop = pos * ROW;
        paintRows(wheel);
      });
    }

    function render() {
      paintTrigger();
      reposition();
    }

    wheels.forEach(function (wheel) {
      var el = wheel.el;
      build(wheel);

      // Scrolling fires a lot; painting is tied to the screen's own refresh so
      // it stays cheap. "Stopped" is just a short quiet spell with no scroll
      // events - there is no reliable end-of-momentum event across browsers.
      var frame = null;
      var idle = null;
      el.addEventListener("scroll", function () {
        if (frame === null) {
          frame = requestAnimationFrame(function () {
            frame = null;
            paintRows(wheel);
          });
        }
        clearTimeout(idle);
        idle = setTimeout(function () { settle(wheel); }, 90);
      });

      // The wheel takes the focus, not the rows - so the arrow keys turn it
      // and the focus ring sits round the whole strip.
      el.tabIndex = 0;
      el.setAttribute("role", "listbox");
      el.addEventListener("keydown", function (e) {
        var by = 0;
        if (e.key === "ArrowUp" || e.key === "ArrowLeft") by = -1;
        else if (e.key === "ArrowDown" || e.key === "ArrowRight") by = 1;
        else if (e.key === "PageUp") by = -3;
        else if (e.key === "PageDown") by = 3;
        else return;
        e.preventDefault();
        goTo(wheel, Math.round(position(wheel)) + by, true);
      });

      // A finger already scrolls the strip natively, with the momentum that
      // comes with it, so dragging only has to be wired up for a mouse.
      var startY = 0, startTop = 0, dragging = false;

      el.addEventListener("pointerdown", function (e) {
        if (e.pointerType !== "mouse") return;
        dragging = true;
        wheel.dragged = false;
        startY = e.clientY;
        startTop = el.scrollTop;
        el.setPointerCapture(e.pointerId);
        e.preventDefault();
      });

      el.addEventListener("pointermove", function (e) {
        if (!dragging) return;
        var dy = e.clientY - startY;
        if (Math.abs(dy) > 3) wheel.dragged = true;
        el.scrollTop = startTop - dy;
      });

      function endDrag(e) {
        if (!dragging) return;
        dragging = false;
        if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
        // Land on a whole row rather than stopping between two. Scroll-snap
        // does this by itself for a finger, but not for a drag we drove.
        goTo(wheel, Math.round(position(wheel)), true);
        // Cleared after the click that follows this release has been and gone.
        setTimeout(function () { wheel.dragged = false; }, 0);
      }
      el.addEventListener("pointerup", endDrag);
      el.addEventListener("pointercancel", endDrag);
    });


    // Opening/closing animates (fade + slight scale, see .tp-panel in
    // src.css). Same two-step as the date picker: drop `hidden` first so the
    // panel is in the layout, then add the open class on the next frame so
    // there is a starting style to transition from. Closing reverses it, and
    // only sets `hidden` once the fade has finished.
    var closeTimer = null;

    function open() {
      clearTimeout(closeTimer);
      state.open = true;
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      render();
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          panel.classList.add("tp-panel-open");
        });
      });
    }

    function close() {
      state.open = false;
      panel.classList.remove("tp-panel-open");
      trigger.setAttribute("aria-expanded", "false");
      clearTimeout(closeTimer);
      closeTimer = setTimeout(function () {
        panel.hidden = true;
      }, 160);
    }

    trigger.addEventListener("click", function () {
      if (state.open) close();
      else open();
    });
    root.querySelector("[data-tp-done]").addEventListener("click", close);

    // Something else on the page may set the box (a reset, a form redraw), so
    // follow it rather than assuming these wheels are the only writer.
    input.addEventListener("change", function () {
      if (writing) return; // our own write, the wheels are already where they should be
      readInput();
      render();
    });

    // Tap anywhere else and the wheels fold away again. composedPath() is
    // fixed at dispatch time, so it still lists root even though picking a row
    // rebuilds the very button that was clicked.
    document.addEventListener("click", function (e) {
      if (state.open && e.composedPath().indexOf(root) === -1) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state.open) close();
    });

    readInput();
    if (native) native.hidden = true;
    trigger.hidden = false;
    render();
  }

  function init() {
    document.querySelectorAll("[data-time-picker]").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
