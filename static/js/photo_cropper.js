/* Choosing which part of a photo shows - the framing window on the villa form.
 *
 * Why this exists: every picture on a villa's public page is shown at 16:9
 * (DISPLAY_RATIO in apps/villas/images.py). Until now the server just kept the
 * middle of whatever was uploaded, so a tall photo of a pool lost its sky and
 * a photo with the villa name along the bottom lost the name. The operator
 * only found out by opening the public page.
 *
 * So: when a picture is picked, this opens a window showing that exact 16:9
 * frame with the picture inside it. Drag to move, pinch or the slider to zoom.
 * What is inside the frame is what guests see. The same window reopens from
 * the "Adjust" button on a picture that is already there.
 *
 * What gets sent: not a cut-down image - just four numbers per picture, the
 * left, top, width and height of the frame as fractions of the original. The
 * uploaded file stays whole, so the frame can be moved again later without the
 * picture ever losing quality, and the server cuts each display copy from the
 * original. See _parse_crops in apps/villas/views.py.
 *
 * Deliberately hand-written rather than a cropper library: it is one frame,
 * one shape, drag and zoom, and pulling in a dependency for that would cost
 * more to keep working than the ~200 lines here. See "Simple over clever" in
 * CLAUDE.md.
 */
(function () {
  "use strict";

  // Must match DISPLAY_RATIO in apps/villas/images.py. If that changes, this
  // changes with it - the whole point of the window is that the frame shown
  // here is the frame the villa page uses.
  var RATIO = 16 / 9;

  // How far in the operator may zoom is not a fixed number - it is whatever
  // still leaves enough real pixels behind. The villa page's hero is served
  // 1600px wide (the top of RESPONSIVE_WIDTHS in apps/villas/images.py), and
  // nothing is ever enlarged, so a crop narrower than that arrives smaller
  // than the box it has to fill and the browser stretches it. That is exactly
  // how a sharp photo turns soft on the public page. So the slider simply
  // stops there, per picture, instead of letting a crop be made that cannot
  // be shown well.
  var HERO_WIDTH = 1600;

  // Uploads are shrunk to this width before they are stored - to_webp() in
  // apps/villas/images.py. The window opens on the file still on the phone,
  // which can be far bigger, so the zoom limit has to be measured against
  // what will survive the upload rather than what was picked. Otherwise a
  // crop is allowed here that the server can never deliver at hero size, and
  // reopening the same picture later - by then a 2000px file - would find the
  // saved zoom out of range and quietly reframe it.
  var STORED_MAX_WIDTH = 2000;

  // The ceiling on top of that, for a picture big enough that the pixel limit
  // never bites. Zooming further than this is almost always a mis-drag.
  var ZOOM_CEILING = 4;

  function t(key, fallback) {
    var strings = window.PHOTO_CROPPER_STRINGS || {};
    return strings[key] || fallback;
  }

  // ---- the window ------------------------------------------------------

  function buildModal() {
    // Styled inline, not with Tailwind classes. The stylesheet is built from
    // the templates, and a class that only ever appears in this file is not in
    // it - the window came out completely unstyled. Inline styles need no
    // build step and cannot be purged.
    var el = document.createElement("div");
    el.setAttribute(
      "style",
      "position:fixed; inset:0; z-index:60; display:flex; align-items:center;" +
        "justify-content:center; background:rgba(32,30,29,.72); padding:16px;"
    );
    el.innerHTML = [
      '<div role="dialog" aria-modal="true" style="width:100%; max-width:520px;' +
        'background:#fff; border-radius:16px; padding:16px;' +
        'box-shadow:0 12px 32px rgba(46,43,37,.35); font-family:inherit;">',
      '  <div style="display:flex; justify-content:space-between; align-items:baseline; gap:8px; margin-bottom:4px;">',
      '    <h2 style="margin:0; font-size:16px; font-weight:600; color:#201e1d;" data-title></h2>',
      '    <span style="font-size:12px; color:#82796a;" data-counter></span>',
      "  </div>",
      '  <p style="margin:0 0 12px; font-size:13px; color:#645c50;">' +
        t("help", "Drag the picture to move it. Everything inside the box is what guests see.") +
        "</p>",
      '  <div data-frame style="position:relative; width:100%; overflow:hidden;' +
        'border-radius:8px; background:#201e1d; touch-action:none; cursor:grab;' +
        'user-select:none;">',
      '    <img data-photo alt="" draggable="false" style="position:absolute; top:0; left:0; transform-origin:0 0; max-width:none;">',
      '    <div style="position:absolute; inset:0; pointer-events:none; box-shadow:inset 0 0 0 1px rgba(255,255,255,.7);"></div>',
      '    <div style="position:absolute; inset:0; pointer-events:none;' +
        'background:linear-gradient(to right, transparent 33.33%, rgba(255,255,255,.28) 33.33%, rgba(255,255,255,.28) calc(33.33% + 1px), transparent calc(33.33% + 1px), transparent 66.66%, rgba(255,255,255,.28) 66.66%, rgba(255,255,255,.28) calc(66.66% + 1px), transparent calc(66.66% + 1px)),' +
        'linear-gradient(to bottom, transparent 33.33%, rgba(255,255,255,.28) 33.33%, rgba(255,255,255,.28) calc(33.33% + 1px), transparent calc(33.33% + 1px), transparent 66.66%, rgba(255,255,255,.28) 66.66%, rgba(255,255,255,.28) calc(66.66% + 1px), transparent calc(66.66% + 1px));"></div>',
      "  </div>",
      '  <div style="display:flex; align-items:center; gap:12px; margin-top:12px;">',
      '    <span style="font-size:12px; color:#82796a;">' + t("zoom", "Zoom") + "</span>",
      '    <input type="range" data-zoom min="1" max="4" step="0.01" value="1" style="flex:1; accent-color:#b2622d; cursor:pointer;">',
      "  </div>",
      '  <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:16px;">',
      '    <button type="button" data-reset style="background:none; border:0; padding:0; font-size:13px; color:#645c50; text-decoration:underline; cursor:pointer;">' +
        t("reset", "Center it again") + "</button>",
      '    <div style="display:flex; gap:8px;">',
      '      <button type="button" data-cancel style="border:1px solid #dcd3c4; background:#fff; color:#474238; border-radius:8px; padding:7px 14px; font-size:13px; cursor:pointer;">' +
        t("cancel", "Cancel") + "</button>",
      '      <button type="button" data-confirm style="border:0; background:#b2622d; color:#fff; border-radius:8px; padding:7px 18px; font-size:13px; font-weight:600; cursor:pointer;"></button>',
      "    </div>",
      "  </div>",
      "</div>",
    ].join("");
    return el;
  }

  /* Open the window on one picture.
   *
   * `source` is anything an <img> can load - a blob: URL for a file that is
   * still on the operator's phone, or the stored file's own URL for a picture
   * that is already uploaded. `startCrop` is a previously chosen box, or null.
   * `onDone` is called with the chosen box, or with null if they backed out.
   */
  function openCropper(options) {
    var modal = buildModal();
    var frame = modal.querySelector("[data-frame]");
    var img = modal.querySelector("[data-photo]");
    var zoom = modal.querySelector("[data-zoom]");
    var titleEl = modal.querySelector("[data-title]");
    var counterEl = modal.querySelector("[data-counter]");

    titleEl.textContent = options.title || t("title", "Choose what shows");
    counterEl.textContent = options.counter || "";
    modal.querySelector("[data-confirm]").textContent =
      options.confirmLabel || t("done", "Use this");

    // The frame's shape comes from RATIO, so there is one place to change it.
    frame.style.aspectRatio = String(RATIO);
    document.body.appendChild(modal);

    // Everything below is in "displayed pixels inside the frame": `cover` is
    // the scale at which the picture exactly fills the frame with nothing
    // spare, so a zoom of 1 can never leave a gap at an edge.
    var state = { cover: 1, zoom: 1, x: 0, y: 0, w: 0, h: 0, maxZoom: ZOOM_CEILING };

    function frameSize() {
      return { w: frame.clientWidth, h: frame.clientHeight };
    }

    function clamp() {
      var f = frameSize();
      var shown = { w: state.w * state.cover * state.zoom, h: state.h * state.cover * state.zoom };
      // Never past an edge: the left of the picture can be at most 0, and its
      // right must be at least the frame's right.
      state.x = Math.min(0, Math.max(f.w - shown.w, state.x));
      state.y = Math.min(0, Math.max(f.h - shown.h, state.y));
    }

    function draw() {
      clamp();
      var scale = state.cover * state.zoom;
      img.style.width = state.w + "px";
      img.style.height = state.h + "px";
      img.style.transform =
        "translate(" + state.x + "px," + state.y + "px) scale(" + scale + ")";
      zoom.value = state.zoom;
    }

    function fitCover() {
      var f = frameSize();
      state.cover = Math.max(f.w / state.w, f.h / state.h);

      // The crop is f.w / (cover * zoom) real pixels wide, so the zoom that
      // leaves exactly HERO_WIDTH of them is f.w / (HERO_WIDTH * cover).
      // Never below 1: a picture only just big enough simply cannot zoom.
      var usable = Math.min(state.w, STORED_MAX_WIDTH);
      var sharpLimit = usable / HERO_WIDTH;
      state.maxZoom = Math.max(1, Math.min(ZOOM_CEILING, sharpLimit));
      zoom.max = state.maxZoom;
      zoom.disabled = state.maxZoom <= 1;
    }

    function centre() {
      var f = frameSize();
      var scale = state.cover * state.zoom;
      state.x = (f.w - state.w * scale) / 2;
      state.y = (f.h - state.h * scale) / 2;
    }

    // The box, as fractions of the original picture. Read straight off what is
    // on screen, so what the operator sees is exactly what the server cuts.
    function currentCrop() {
      var f = frameSize();
      var scale = state.cover * state.zoom;
      var x = -state.x / scale / state.w;
      var y = -state.y / scale / state.h;
      var w = f.w / scale / state.w;
      var h = f.h / scale / state.h;
      return {
        x: Math.max(0, Math.min(1, x)),
        y: Math.max(0, Math.min(1, y)),
        width: Math.max(0.01, Math.min(1, w)),
        height: Math.max(0.01, Math.min(1, h)),
      };
    }

    // The other direction: put the picture back where a saved box says it was.
    function applyCrop(crop) {
      var f = frameSize();
      var scale = f.w / (crop.width * state.w);
      state.zoom = Math.max(1, Math.min(state.maxZoom, scale / state.cover));
      var real = state.cover * state.zoom;
      // Centre on the middle of the saved box, not its top-left corner. If the
      // zoom above had to be clamped (an older crop, saved before the limit
      // matched the stored file) anchoring the corner would slide the picture
      // sideways as well as widening it. Centring keeps the same subject.
      var midX = (crop.x + crop.width / 2) * state.w * real;
      var midY = (crop.y + crop.height / 2) * state.h * real;
      state.x = f.w / 2 - midX;
      state.y = f.h / 2 - midY;
    }

    function close(result) {
      document.removeEventListener("keydown", onKey);
      modal.remove();
      options.onDone(result);
    }

    function onKey(evt) {
      if (evt.key === "Escape") close(null);
    }
    document.addEventListener("keydown", onKey);

    img.onload = function () {
      state.w = img.naturalWidth;
      state.h = img.naturalHeight;
      fitCover();
      if (options.startCrop) {
        applyCrop(options.startCrop);
      } else {
        centre();
      }
      draw();
    };
    img.src = options.source;

    // ---- dragging ------------------------------------------------------
    var dragging = null;
    frame.addEventListener("pointerdown", function (evt) {
      dragging = { px: evt.clientX, py: evt.clientY };
      frame.setPointerCapture(evt.pointerId);
      frame.style.cursor = "grabbing";
    });
    frame.addEventListener("pointermove", function (evt) {
      if (!dragging) return;
      state.x += evt.clientX - dragging.px;
      state.y += evt.clientY - dragging.py;
      dragging.px = evt.clientX;
      dragging.py = evt.clientY;
      draw();
    });
    function endDrag() {
      dragging = null;
      frame.style.cursor = "grab";
    }
    frame.addEventListener("pointerup", endDrag);
    frame.addEventListener("pointercancel", endDrag);

    // ---- zooming -------------------------------------------------------
    // Zooming keeps the middle of the frame where it is, rather than growing
    // out of the top-left corner, which is what feels right when dragging.
    function setZoom(next) {
      var f = frameSize();
      var before = state.cover * state.zoom;
      state.zoom = Math.max(1, Math.min(state.maxZoom, next));
      var after = state.cover * state.zoom;
      state.x = f.w / 2 - (f.w / 2 - state.x) * (after / before);
      state.y = f.h / 2 - (f.h / 2 - state.y) * (after / before);
      draw();
    }
    zoom.addEventListener("input", function () {
      setZoom(parseFloat(zoom.value));
    });
    frame.addEventListener("wheel", function (evt) {
      evt.preventDefault();
      setZoom(state.zoom * (evt.deltaY < 0 ? 1.08 : 1 / 1.08));
    }, { passive: false });

    modal.querySelector("[data-reset]").addEventListener("click", function () {
      state.zoom = 1;
      centre();
      draw();
    });
    modal.querySelector("[data-cancel]").addEventListener("click", function () {
      close(null);
    });
    modal.querySelector("[data-confirm]").addEventListener("click", function () {
      close(currentCrop());
    });
    modal.addEventListener("pointerdown", function (evt) {
      if (evt.target === modal) close(null);
    });

    // A frame that changes size (phone rotated) must not leave the picture
    // with a gap down one side.
    window.addEventListener("resize", function () {
      if (!state.w) return;
      fitCover();
      draw();
    });
  }

  // ---- picking files: frame each one, then upload ----------------------

  document.body.addEventListener("change", function (evt) {
    var input = evt.target;
    if (!input.matches || !input.matches("input[type=file][data-cropper]")) return;
    if (!input.files || !input.files.length) return;
    if (input.dataset.framing === "done") {
      // The window has already run for these files - this is the change event
      // we fired ourselves. Let it through untouched.
      delete input.dataset.framing;
      return;
    }

    // Stop HTMX and the form from seeing these files until the operator has
    // framed them. The upload itself waits on the "framed" event this fires.
    evt.stopPropagation();

    var files = Array.prototype.slice.call(input.files);
    var crops = [];
    var holder = document.querySelector(input.dataset.crops);

    function next(index) {
      if (index >= files.length) {
        if (holder) holder.value = JSON.stringify(crops);
        input.dataset.framing = "done";
        // Two audiences: HTMX pickers listen for "framed" and upload now, and
        // the very first step-1 picker has no upload URL at all and just needs
        // its local preview redrawn (villa_form.js listens for "change").
        input.dispatchEvent(new CustomEvent("framed", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return;
      }
      var url = URL.createObjectURL(files[index]);
      openCropper({
        source: url,
        startCrop: null,
        counter: files.length > 1 ? index + 1 + " / " + files.length : "",
        onDone: function (crop) {
          URL.revokeObjectURL(url);
          if (!crop) {
            // Backing out of one picture backs out of the whole batch. A
            // browser will not let us drop a single file from what was picked,
            // and uploading a picture they just cancelled would be worse than
            // asking them to pick again.
            input.value = "";
            if (holder) holder.value = "";
            return;
          }
          crops.push(crop);
          next(index + 1);
        },
      });
    }

    // Backing out of the first picture's window means backing out of the whole
    // upload: nothing has been sent yet, so clearing the input is enough.
    next(0);
  }, true);

  // ---- re-framing a picture that is already uploaded -------------------

  document.body.addEventListener("click", function (evt) {
    var button = evt.target.closest ? evt.target.closest("[data-adjust-photo]") : null;
    if (!button) return;

    var saved = null;
    if (button.dataset.crop) {
      var parts = button.dataset.crop.split(",").map(parseFloat);
      saved = { x: parts[0], y: parts[1], width: parts[2], height: parts[3] };
    }

    openCropper({
      source: button.dataset.image,
      startCrop: saved,
      confirmLabel: t("save", "Save this view"),
      onDone: function (crop) {
        if (!crop) return;
        window.htmx.ajax("POST", button.dataset.url, {
          source: button,
          target: button.dataset.target,
          swap: "innerHTML",
          values: { crops: JSON.stringify([crop]) },
        });
      },
    });
  });
})();
