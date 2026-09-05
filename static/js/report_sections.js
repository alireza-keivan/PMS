/* Collapse/expand for the blocks on the reporting screen.
 *
 * Which blocks are open is remembered in this browser, because changing the
 * date range or the villa reloads the whole page - without remembering, every
 * block a user had tidied away would spring back open on each filter change.
 *
 * Storage can throw outright (private windows, browsers set to block site
 * data), so every read and write is wrapped and simply falls back to the
 * default the template asked for.
 */
window.reportSection = function (key, defaultOpen) {
  const storageKey = "reports.section." + key;
  let open = defaultOpen;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved !== null) open = saved === "1";
  } catch (e) {
    /* no stored preference available - keep the default */
  }
  return {
    open: open,
    toggle() {
      this.open = !this.open;
      try {
        localStorage.setItem(storageKey, this.open ? "1" : "0");
      } catch (e) {
        /* can't remember it; the toggle still works for this page view */
      }
    },
  };
};
