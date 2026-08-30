/* Alpine component for the Add Reservation page: villa -> room type dependent
 * select, the foreign-guest note, and the live balance line. All three are
 * small, page-local UI state with no server round trip needed - see
 * CLAUDE.md's guidance on when Alpine is the right tool.
 *
 * The nights/availability box is deliberately NOT handled here - that one
 * depends on real booking data, so it stays a live HTMX call to
 * apps.bookings.views.ReservationAvailabilityView (see add.html) rather than
 * being reimplemented in JS. Loaded through {% block pre_alpine_js %}, i.e.
 * before alpine.min.js - see the note in base.html for why that order
 * matters, and static/js/villa_form.js for the IDR-preview handler this page
 * also reuses unchanged.
 */
(function () {
  "use strict";

  window.reservationForm = function (config) {
    config = config || {};
    return {
      villas: config.villas || [],
      villaId: config.villaId || "",
      roomTypeId: config.roomTypeId || "",
      nationality: config.nationality || "",
      totalRaw: config.totalRaw || "",
      paidRaw: config.paidRaw || "",
      roomTypeNoVillaLabel: config.roomTypeNoVillaLabel || "",
      roomTypeReadyLabel: config.roomTypeReadyLabel || "",

      get roomTypeOptions() {
        var villa = this.villas.find(function (v) { return String(v.id) === String(this.villaId); }, this);
        return villa ? villa.room_types : [];
      },

      get roomTypePlaceholder() {
        return this.villaId ? this.roomTypeReadyLabel : this.roomTypeNoVillaLabel;
      },

      onVillaChange() {
        var stillValid = this.roomTypeOptions.some(function (r) {
          return String(r.id) === String(this.roomTypeId);
        }, this);
        if (!stillValid) this.roomTypeId = "";
      },

      // Indonesian guests need no police-report reminder - see PoliceReport
      // in apps.compliance.models, which only exists for foreign guests.
      get isForeign() {
        return !!this.nationality && this.nationality !== "ID";
      },

      get balance() {
        var total = parseInt(String(this.totalRaw).replace(/\D/g, ""), 10);
        if (!total) return null;
        var paid = parseInt(String(this.paidRaw).replace(/\D/g, ""), 10) || 0;
        return total - paid;
      },
    };
  };
})();
