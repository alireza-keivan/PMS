/* Booking calendar glue: builds the vis-timeline widget once, then bridges
 * HTMX swaps (fresh data) and Alpine (the side panel) into its imperative
 * DataSet API - neither HTMX nor Alpine know how to talk to it directly.
 * Read-only: editable is off, nothing here writes booking data.
 */
(function () {
  "use strict";

  // "load", not "DOMContentLoaded": vis-timeline measures the container's
  // actual laid-out width when it's constructed, and stylesheets (Tailwind,
  // vis-timeline's own CSS) aren't guaranteed to have been applied yet at
  // DOMContentLoaded - a too-early measurement can leave the widget stuck
  // showing a far wider date range than the one actually requested.
  window.addEventListener("load", function () {
    var container = document.getElementById("calendar-timeline");
    if (!container) return; // no_organization state - nothing to build

    var groupsDataSet = new vis.DataSet();
    var itemsDataSet = new vis.DataSet();

    var options = {
      editable: false,
      zoomable: false,
      moveable: false,
      selectable: true,
      stack: true,
      orientation: "top",
      format: {
        // vis-timeline calls this with a *moment* object, not a plain Date -
        // and only accepts the whole minorLabels table as a function, never
        // a function nested under a single scale key (that fails vis-
        // timeline's own options validation with a type error).
        minorLabels: function (momentDate, scale) {
          if (scale === "day" || scale === "weekday") {
            return formatDayHeader(momentDate.toDate());
          }
          return String(momentDate.date());
        },
      },
    };

    var timeline = new vis.Timeline(container, itemsDataSet, groupsDataSet, options);

    loadCalendarData();
    restoreCollapsedGroups();

    document.body.addEventListener("htmx:afterSwap", function (evt) {
      if (evt.detail.target && evt.detail.target.id === "calendar-panel") {
        loadCalendarData();
        restoreCollapsedGroups();
      }
    });

    timeline.on("click", function (props) {
      // vis-timeline's own click event already tells us which group's label
      // was clicked (props.what === "group-label") - reading a custom
      // data-* attribute off the clicked DOM node isn't reliable, since
      // vis-timeline runs custom group/item HTML through an XSS sanitizer
      // that doesn't allowlist data-* attributes.
      if (props.what === "group-label" && props.group != null && String(props.group).indexOf("area-") === 0) {
        toggleGroup(props.group);
        return;
      }
      if (props.item != null) {
        var item = itemsDataSet.get(props.item);
        if (item) {
          item.dateRangeLabel = formatDateRange(item.start, item.end);
          window.dispatchEvent(new CustomEvent("booking-selected", { detail: item }));
        }
      }
    });

    function loadCalendarData() {
      var node = document.getElementById("calendar-data");
      if (!node) return;
      var data = JSON.parse(node.textContent);
      groupsDataSet.clear();
      groupsDataSet.add(data.groups);
      itemsDataSet.clear();
      itemsDataSet.add(data.items);
      timeline.setWindow(node.dataset.start, node.dataset.rangeEnd, { animation: false });
      // Defensive: force a re-measure of the container/axis. Without this,
      // a redraw that happens to land before the container's final layout
      // (e.g. right after an HTMX swap collapses/expands other page
      // content) can leave the day columns sized for the wrong width.
      timeline.redraw();
    }

    function toggleGroup(groupId) {
      var collapsedKey = "cal-collapsed:" + groupId;
      var isCollapsed = localStorage.getItem(collapsedKey) === "1";
      groupsDataSet.updateOnly([{ id: groupId, showNested: isCollapsed }]);
      localStorage.setItem(collapsedKey, isCollapsed ? "0" : "1");
    }

    function restoreCollapsedGroups() {
      groupsDataSet.forEach(function (group) {
        if (String(group.id).indexOf("area-") !== 0) return;
        if (localStorage.getItem("cal-collapsed:" + group.id) === "1") {
          groupsDataSet.updateOnly([{ id: group.id, showNested: false }]);
        }
      });
    }

    function formatDayHeader(date) {
      // vis-timeline's own label boxes are single-line (overflow: hidden,
      // white-space: nowrap, sized before any custom content is measured) -
      // a two-line stacked label silently gets clipped inside that box, so
      // weekday and day number render on one line instead.
      var lang = document.documentElement.lang || "en";
      var weekday = new Intl.DateTimeFormat(lang, { weekday: "short" }).format(date);
      return (
        '<span class="cal-weekday">' + weekday + "</span> " +
        '<span class="cal-daynum">' + date.getDate() + "</span>"
      );
    }

    function formatDateRange(startIso, endIso) {
      var lang = document.documentElement.lang || "en";
      var opts = { day: "numeric", month: "short" };
      var start = new Date(startIso + "T00:00:00");
      var end = new Date(endIso + "T00:00:00");
      return (
        new Intl.DateTimeFormat(lang, opts).format(start) +
        " – " +
        new Intl.DateTimeFormat(lang, { day: "numeric", month: "short", year: "numeric" }).format(end)
      );
    }
  });
})();
