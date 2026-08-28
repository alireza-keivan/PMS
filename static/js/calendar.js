/* Booking calendar glue: builds the vis-timeline widget once, then bridges
 * HTMX swaps (fresh data) and Alpine (the side panel) into its imperative
 * DataSet API - neither HTMX nor Alpine know how to talk to it directly.
 * Read-only: editable is off, nothing here writes booking data.
 */
(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
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
      var toggle = props.event && props.event.target.closest(".cal-area-toggle");
      if (toggle) {
        toggleGroup(toggle.dataset.groupId);
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
      timeline.setWindow(node.dataset.start, node.dataset.rangeEnd);
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
      var lang = document.documentElement.lang || "en";
      var weekday = new Intl.DateTimeFormat(lang, { weekday: "short" }).format(date);
      return (
        '<div class="cal-weekday">' + weekday + "</div>" +
        '<div class="cal-daynum">' + date.getDate() + "</div>"
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
