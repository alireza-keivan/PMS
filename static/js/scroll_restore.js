/* Keeps the scroll position when a plain (non-htmx) form submit reloads the
 * page - e.g. saving villa details or the room list. Those forms POST and
 * get redirected back to the same page, which is a brand new navigation as
 * far as the browser is concerned, so it resets scroll to the top by
 * default. This remembers where the user was, keyed by path, and puts it
 * back after the redirect lands.
 */
(function () {
  "use strict";

  function key() {
    return "scrollpos:" + window.location.pathname;
  }

  document.body.addEventListener("submit", function (evt) {
    var form = evt.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.hasAttribute("hx-post") || form.hasAttribute("hx-get")) return;
    try {
      sessionStorage.setItem(key(), String(window.scrollY));
    } catch (e) {}
  });

  document.addEventListener("DOMContentLoaded", function () {
    var stored;
    try {
      stored = sessionStorage.getItem(key());
    } catch (e) {
      return;
    }
    if (stored === null) return;
    try {
      sessionStorage.removeItem(key());
    } catch (e) {}
    window.scrollTo(0, parseInt(stored, 10) || 0);
  });
})();
