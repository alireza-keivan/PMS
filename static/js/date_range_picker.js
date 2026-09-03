/* Date range picker - the "Date Range Picker" card from the design handoff.
 *
 * Drives templates/partials/_date_range_picker.html. Read that file first: the
 * two real date inputs are the source of truth, this only fills them in.
 *
 * Deliberately plain: no framework, no build step, no dependency. It attaches
 * to every [data-date-range-picker] on the page, so a page can hold more than
 * one. If the script never loads, the partial's native date boxes are still
 * there and the form still works.
 *
 * Month and weekday names come from the browser's own Intl, in the page's
 * language (<html lang>), so EN and ID both read right with no strings to
 * translate here.
 */
(function () {
  "use strict";

  var DAY = 86400000;

  function parse(value) {
    // "YYYY-MM-DD" -> a local Date. new Date(string) would read it as UTC and
    // land on the day before for anyone east of Greenwich - which is everyone
    // this product is for.
    if (!value) return null;
    var p = value.split("-");
    if (p.length !== 3) return null;
    var d = new Date(+p[0], +p[1] - 1, +p[2]);
    return isNaN(d) ? null : d;
  }

  function iso(d) {
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + m + "-" + day;
  }

  function startOfToday() {
    var n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }

  function sameDay(a, b) {
    return !!a && !!b && a.getTime() === b.getTime();
  }

  function setup(root) {
    var inputs = root.querySelectorAll('input[type="date"]');
    if (inputs.length < 2) return;
    var checkIn = inputs[0];
    var checkOut = inputs[1];

    var native = root.querySelector(".drp-native");
    var trigger = root.querySelector("[data-drp-trigger]");
    var triggerLabel = root.querySelector("[data-drp-label]");
    var triggerValue = root.querySelector("[data-drp-trigger-value]");
    var panel = root.querySelector(".drp-panel");
    var monthLabel = root.querySelector("[data-drp-month]");
    var weekdayRow = root.querySelector("[data-drp-weekdays]");
    var dayGrid = root.querySelector("[data-drp-days]");
    var summaryText = root.querySelector("[data-drp-summary-text]");
    if (!trigger || !panel || !dayGrid) return;

    var lang = document.documentElement.lang || "en";
    var minNights = parseInt(root.dataset.minNights, 10) || 1;
    var today = startOfToday();

    var state = {
      inDate: parse(checkIn.value),
      outDate: parse(checkOut.value),
      mode: "in",
      open: false,
    };
    var view = new Date(
      (state.inDate || today).getFullYear(),
      (state.inDate || today).getMonth(),
      1
    );

    // JavaScript is here, so swap the two plain boxes for the one field.
    native.hidden = true;
    trigger.hidden = false;
    if (triggerLabel) triggerLabel.hidden = false;

    var monthFmt = new Intl.DateTimeFormat(lang, { month: "long", year: "numeric" });
    var shortFmt = new Intl.DateTimeFormat(lang, { month: "short", day: "numeric" });
    var weekdayFmt = new Intl.DateTimeFormat(lang, { weekday: "short" });
    var pickText = root.querySelector('[data-drp-summary="in"]').textContent;
    var nightWord = summaryText.dataset.nightWord || "night";
    var nightsWord = summaryText.dataset.nightsWord || "nights";

    // Monday-first, like the design and like every calendar in Indonesia.
    (function buildWeekdays() {
      var monday = new Date(2024, 0, 1); // a Monday
      for (var i = 0; i < 7; i++) {
        var cell = document.createElement("div");
        cell.className = "drp-weekday";
        cell.textContent = weekdayFmt
          .format(new Date(monday.getTime() + i * DAY))
          .slice(0, 2);
        weekdayRow.appendChild(cell);
      }
    })();

    function summarize(d) {
      return d ? shortFmt.format(d) : pickText;
    }

    function nights() {
      if (!state.inDate || !state.outDate) return 0;
      return Math.round((state.outDate - state.inDate) / DAY);
    }

    function writeBack() {
      var pairs = [[checkIn, state.inDate], [checkOut, state.outDate]];
      pairs.forEach(function (pair) {
        var next = pair[1] ? iso(pair[1]) : "";
        if (pair[0].value === next) return;
        pair[0].value = next;
        // The price line on the villa page listens for this - see
        // templates/public/_booking_panel.html.
        pair[0].dispatchEvent(new Event("change", { bubbles: true }));
      });
    }

    function disabled(d) {
      if (d < today) return true;
      // Leaving has to be at least the shortest stay after arriving.
      if (state.mode === "out" && state.inDate) {
        return d.getTime() < state.inDate.getTime() + minNights * DAY;
      }
      return false;
    }

    function pick(d) {
      if (state.mode === "in") {
        state.inDate = d;
        if (state.outDate && state.outDate.getTime() < d.getTime() + minNights * DAY) {
          state.outDate = null;
        }
        state.mode = "out";
      } else {
        state.outDate = d;
        state.mode = "in";
      }
      writeBack();
      render();
    }

    function render() {
      root.querySelectorAll("[data-drp-tab]").forEach(function (tab) {
        tab.classList.toggle("drp-tab-active", tab.dataset.drpTab === state.mode);
      });
      root.querySelector('[data-drp-summary="in"]').textContent = summarize(state.inDate);
      root.querySelector('[data-drp-summary="out"]').textContent = summarize(state.outDate);

      monthLabel.textContent = monthFmt.format(view);

      var n = nights();
      var nightsPhrase = n ? n + " " + (n === 1 ? nightWord : nightsWord) : "";
      summaryText.textContent = nightsPhrase || summaryText.dataset.emptyText || "";

      // The one field, closed: the whole stay on a single line.
      if (state.inDate && state.outDate) {
        triggerValue.textContent =
          shortFmt.format(state.inDate) + " - " + shortFmt.format(state.outDate) +
          (nightsPhrase ? ", " + nightsPhrase : "");
      } else if (state.inDate) {
        triggerValue.textContent = shortFmt.format(state.inDate) + " - " + pickText;
      } else {
        triggerValue.textContent = triggerValue.dataset.emptyText || "";
      }

      dayGrid.textContent = "";
      var first = new Date(view.getFullYear(), view.getMonth(), 1);
      var offset = (first.getDay() + 6) % 7; // Monday-first
      var daysInMonth = new Date(view.getFullYear(), view.getMonth() + 1, 0).getDate();

      for (var i = 0; i < 42; i++) {
        var num = i - offset + 1;
        var cell = document.createElement("div");
        cell.className = "drp-day";
        if (num < 1 || num > daysInMonth) {
          dayGrid.appendChild(cell);
          continue;
        }
        var d = new Date(view.getFullYear(), view.getMonth(), num);
        var isEnd = sameDay(d, state.inDate) || sameDay(d, state.outDate);
        var inRange =
          state.inDate && state.outDate && d > state.inDate && d < state.outDate;
        var off = disabled(d);

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "drp-day-inner";
        btn.textContent = num;
        if (isEnd) btn.classList.add("drp-day-selected");
        if (inRange) cell.classList.add("drp-day-in-range");
        if (off) {
          btn.disabled = true;
          btn.classList.add("drp-day-off");
        } else {
          btn.addEventListener("click", pick.bind(null, d));
        }
        cell.appendChild(btn);
        dayGrid.appendChild(cell);
      }
    }

    // Opening/closing animates (fade + slight scale, see .drp-panel in
    // src.css) instead of the panel just appearing. That needs the `hidden`
    // attribute and the `.drp-panel-open` class handled a frame apart: remove
    // `hidden` first so the panel is actually in the layout, then add the
    // open class on the next frame so the browser has a starting style
    // (opacity 0, scaled down) to transition from - adding both in the same
    // tick would skip straight to the end state with no animation. Closing
    // reverses this: drop the class to play the transition out, then only
    // set `hidden` once it's finished so the panel isn't clickable mid-fade.
    var closeTimer = null;

    function open(mode) {
      clearTimeout(closeTimer);
      state.mode = mode;
      state.open = true;
      panel.hidden = false;
      trigger.setAttribute("aria-expanded", "true");
      view = new Date(
        ((mode === "out" && state.outDate) || state.inDate || today).getFullYear(),
        ((mode === "out" && state.outDate) || state.inDate || today).getMonth(),
        1
      );
      render();
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          panel.classList.add("drp-panel-open");
        });
      });
    }

    function close() {
      state.open = false;
      panel.classList.remove("drp-panel-open");
      trigger.setAttribute("aria-expanded", "false");
      clearTimeout(closeTimer);
      closeTimer = setTimeout(function () {
        panel.hidden = true;
      }, 160);
    }

    // One field opens the calendar. It picks up where the stay left off: no
    // dates yet, or a complete stay, and the next tap sets the arriving date
    // again; half a stay, and it carries on with the leaving date.
    trigger.addEventListener("click", function () {
      if (state.open) close();
      else open(state.inDate && !state.outDate ? "out" : "in");
    });

    // The tabs inside only move between the two ends - they never close it.
    root.querySelectorAll("[data-drp-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        state.mode = tab.dataset.drpTab;
        render();
      });
    });

    root.querySelector("[data-drp-prev]").addEventListener("click", function () {
      view = new Date(view.getFullYear(), view.getMonth() - 1, 1);
      render();
    });
    root.querySelector("[data-drp-next]").addEventListener("click", function () {
      view = new Date(view.getFullYear(), view.getMonth() + 1, 1);
      render();
    });
    root.querySelector("[data-drp-done]").addEventListener("click", close);

    // Tap anywhere else on the page and the month folds away again. Picking a
    // day rebuilds the grid (render() clears and redraws every cell), which
    // detaches the very button that was just clicked before this listener
    // runs - so root.contains(e.target) would wrongly read "outside" and
    // close the panel right after the first date is chosen. composedPath()
    // is fixed at dispatch time, before that rebuild, so it still lists root
    // as an ancestor.
    document.addEventListener("click", function (e) {
      if (state.open && e.composedPath().indexOf(root) === -1) close();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && state.open) close();
    });

    render();
  }

  function init() {
    document.querySelectorAll("[data-date-range-picker]").forEach(setup);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
