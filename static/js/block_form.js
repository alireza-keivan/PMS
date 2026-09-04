/* Alpine component for the Block Dates page: villa -> room dependent select,
 * nothing else. Deliberately smaller than static/js/reservation_form.js -
 * blocking dates has no guest, no money and no availability preview to keep
 * in sync, so this is the whole of the page's local state.
 *
 * Loaded through {% block pre_alpine_js %}, i.e. before alpine.min.js - see
 * the note in base.html for why that order matters.
 */
(function () {
  "use strict";

  window.blockForm = function (config) {
    config = config || {};
    return {
      villas: config.villas || [],
      villaId: config.villaId || "",
      roomId: config.roomId || "",
      roomNoVillaLabel: config.roomNoVillaLabel || "",
      roomReadyLabel: config.roomReadyLabel || "",

      get roomOptions() {
        var villa = this.villas.find(function (v) { return String(v.id) === String(this.villaId); }, this);
        return villa ? villa.rooms : [];
      },

      get roomPlaceholder() {
        return this.villaId ? this.roomReadyLabel : this.roomNoVillaLabel;
      },

      onVillaChange() {
        var stillValid = this.roomOptions.some(function (r) {
          return String(r.id) === String(this.roomId);
        }, this);
        if (!stillValid) this.roomId = "";
      },
    };
  };
})();
