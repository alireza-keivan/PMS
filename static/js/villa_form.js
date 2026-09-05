/* A few small jobs on the villa form, all of which need real JavaScript.
 *
 *   1. Re-bind Alpine to markup HTMX has just swapped in - a room block, or a
 *      photo grid. Alpine only walks the page once, when it starts, so
 *      anything that arrives afterwards would never collapse or react to
 *      clicks. HTMX doesn't do this for us.
 *
 *   2. Show a live "Rp 1.500.000" reading under a price box as it's typed.
 *      The box itself stays exactly what was typed - digits, dots, whatever -
 *      so the cursor never jumps around mid-word; only the reading below is
 *      formatted. The server strips separators the same way regardless of
 *      what was typed (see IDRField in forms.py), so this is read-only sugar,
 *      never the source of truth.
 *
 *   3. Give a not-yet-uploaded photo a thumbnail. Most photo pickers on this
 *      page upload the moment a file is chosen and get a real thumbnail back
 *      from the server - but a villa's very first photos, picked before the
 *      villa itself has been saved even once, have nowhere to upload to yet.
 *      Those just get a local preview from the browser's own copy of the
 *      file, so the box doesn't look inert while it waits for the rest of the
 *      form to be submitted.
 *
 * Loaded through {% block pre_alpine_js %}, i.e. before alpine.min.js - see
 * the note in base.html for why that order matters.
 */
(function () {
  "use strict";

  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (window.Alpine && evt.detail && evt.detail.target) {
      window.Alpine.initTree(evt.detail.target);
    }
  });

  // ---- 2. live "Rp" reading ------------------------------------------

  // Group by whatever language the page is in, not always Indonesian, so the
  // preview matches what the server prints back on the next page (see
  // apps/bookings/services.py _money). <html lang> is set from Django's
  // active locale in base.html.
  function formatRp(raw) {
    var digits = String(raw || "").replace(/\D/g, "");
    if (!digits) return "";
    var lang = document.documentElement.lang || "en";
    return "Rp " + Number(digits).toLocaleString(lang);
  }

  function updateIdrPreview(input) {
    var preview = input.nextElementSibling;
    if (!preview || !preview.matches("[data-idr-preview]")) return;
    preview.textContent = formatRp(input.value);
  }

  document.body.addEventListener("input", function (evt) {
    if (evt.target.matches && evt.target.matches("[data-idr-input]")) {
      updateIdrPreview(evt.target);
    }
  });

  // Covers a value that's already there when the page loads or HTMX swaps a
  // block in - e.g. going back to a room type that already has a rate saved.
  function initIdrPreviews(root) {
    root.querySelectorAll("[data-idr-input]").forEach(updateIdrPreview);
  }
  document.addEventListener("DOMContentLoaded", function () {
    initIdrPreviews(document);
  });
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.detail && evt.detail.target) initIdrPreviews(evt.detail.target);
  });

  // ---- 2b. coupon discount: lock until a rate exists, preview the result --

  // A coupon only means something once there's a rate to take it off of - see
  // the matching check in RoomCategoryForm.clean() in forms.py, which is what
  // actually enforces it. This just keeps the box from inviting a number that
  // would be dropped on save.
  function updateCoupon(block) {
    var percentInput = block.querySelector("[data-coupon-input]");
    var checkbox = block.querySelector("[data-coupon-enable]");
    var preview = block.querySelector("[data-coupon-preview]");
    if (!percentInput || !checkbox || !preview) return;

    var card = block.closest(".card") || document;
    var rateInputs = card.querySelectorAll("[data-idr-input]");
    var rates = [];
    rateInputs.forEach(function (input) {
      var digits = String(input.value || "").replace(/\D/g, "");
      if (digits) rates.push(Number(digits));
    });

    var hasRate = rates.length > 0;
    percentInput.disabled = !hasRate;
    checkbox.disabled = !hasRate;
    if (!hasRate) {
      checkbox.checked = false;
      preview.textContent = "";
      return;
    }

    var percent = Number(percentInput.value);
    if (!checkbox.checked || !percent) {
      preview.textContent = "";
      return;
    }

    var lang = document.documentElement.lang || "en";
    var readings = rates.map(function (rate) {
      var final = Math.round(rate * (100 - percent) / 100);
      return "Rp " + final.toLocaleString(lang);
    });
    preview.textContent = readings.join(" / ");
  }

  function initCoupons(root) {
    root.querySelectorAll("[data-coupon-block]").forEach(updateCoupon);
  }

  document.body.addEventListener("input", function (evt) {
    var block = evt.target.closest && evt.target.closest("[data-coupon-block]");
    if (block) { updateCoupon(block); return; }
    // A rate box living outside the coupon block itself still has to refresh
    // the coupon preview sitting below it in the same card.
    if (evt.target.matches && evt.target.matches("[data-idr-input]")) {
      var card = evt.target.closest(".card");
      var couponBlock = card && card.querySelector("[data-coupon-block]");
      if (couponBlock) updateCoupon(couponBlock);
    }
  });
  document.body.addEventListener("change", function (evt) {
    if (evt.target.matches && evt.target.matches("[data-coupon-enable]")) {
      updateCoupon(evt.target.closest("[data-coupon-block]"));
    }
  });
  document.addEventListener("DOMContentLoaded", function () {
    initCoupons(document);
  });
  document.body.addEventListener("htmx:afterSwap", function (evt) {
    if (evt.detail && evt.detail.target) initCoupons(evt.detail.target);
  });

  // ---- 3. local preview for a not-yet-uploaded villa photo ------------

  document.body.addEventListener("change", function (evt) {
    var input = evt.target;
    if (!input.matches || !input.matches("input[type=file][data-blob-preview]")) return;

    var tile = input.closest("label");
    var row = tile && tile.parentElement;
    if (!row) return;

    var file = input.files && input.files[0];
    if (!file) return;

    // A tile that already wraps an existing photo (see
    // villas/_experience_fields.html) just gets its own image swapped, so
    // picking a new file replaces the preview in place instead of adding a
    // second box next to it.
    var existingImg = tile.querySelector("img");
    if (existingImg) {
      existingImg.src = URL.createObjectURL(file);
      return;
    }

    // A single-photo tile (no "multiple" on its input, e.g.
    // villas/_experience_fields.html) has nowhere else for a second photo to
    // go, so picking a file turns the dashed placeholder itself into the
    // preview instead of adding a new box next to it.
    if (!input.multiple) {
      tile.querySelector("svg").remove();
      var singleImg = document.createElement("img");
      singleImg.src = URL.createObjectURL(file);
      singleImg.alt = "";
      singleImg.className = "h-full w-full object-cover";
      tile.appendChild(singleImg);
      return;
    }

    row.querySelectorAll("[data-pending-preview]").forEach(function (el) { el.remove(); });

    var box = document.createElement("div");
    box.dataset.pendingPreview = "true";
    box.className = "h-[74px] w-[74px] flex-none overflow-hidden rounded-sm border border-sand-300";
    var img = document.createElement("img");
    img.src = URL.createObjectURL(file);
    img.alt = "";
    img.className = "h-full w-full object-cover";
    box.appendChild(img);
    row.insertBefore(box, tile);
  });

  // ---- 4. "Save" stays off until something actually changes ------------
  //
  // On a villa that already exists, pressing save with nothing changed just
  // reloads the same page for no reason. So the button starts switched off
  // and only wakes up once the form's values differ from what they were when
  // the page loaded. A draft villa is not marked up with this, because its
  // first save has to go through even if nothing was typed.
  //
  // The comparison is on the whole form's values at once, so it also catches
  // a block HTMX swapped in or out - and it goes back off by itself if the
  // values are put back the way they were.
  //
  // Pictures are the one thing this comparison cannot see: they are uploaded
  // to the server and held aside there rather than sitting in a form field
  // (see PhotoQuerySet in apps/villas/models.py), so the row comes back with
  // no change to any value here. The server says so instead, by sending
  // "photos-changed" back with the new row, and that latches the button on -
  // the change is on the server now, and only Save settles it either way.

  function snapshot(form) {
    var pairs = [];
    new FormData(form).forEach(function (value, name) {
      if (name === "csrfmiddlewaretoken") return;
      // A file box holds a File here, which is never equal to itself across
      // two readings - the name alone is enough to notice a picked file.
      pairs.push(name + "=" + (value instanceof File ? value.name : value));
    });
    return pairs.join("&");
  }

  function watchDirty(form) {
    // The button usually sits inside the form, but it can also live outside
    // and point back with form="<id>" (the activities page does this).
    var button = form.querySelector("[data-dirty-submit]");
    if (!button && form.id) {
      button = document.querySelector('[data-dirty-submit][form="' + form.id + '"]');
    }
    if (!button) return;
    var clean = snapshot(form);
    var photosChanged = false;

    function isDirty() {
      return photosChanged || snapshot(form) !== clean;
    }

    function refresh() {
      button.disabled = !isDirty();
    }
    refresh();

    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    document.body.addEventListener("htmx:afterSwap", function (evt) {
      if (evt.detail && evt.detail.target && form.contains(evt.detail.target)) refresh();
    });
    document.body.addEventListener("photos-changed", function () {
      photosChanged = true;
      refresh();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("form[data-dirty-guard]").forEach(watchDirty);
  });
})();
