# Add Reservation page — design spec

Reference: `Add Reservation.dc.html` in this project (canonical, high-fidelity). A design reference built in HTML — recreate in the target stack, don't port the HTML verbatim. Uses the same Organic design tokens as the booking calendar and Add Villa specs in this bundle (warm cream ground, terracotta/sage accents, Caprasimo headings over Figtree body, pill-shaped inputs/buttons — see `README.md` for the full token list).

## Page structure

Single scrolling form, one column, `max-width: 680px` centered, no step indicator (unlike Add Villa's two-step flow — this is one page, sectioned into three cards).

- **Top nav bar**: same nav component as the rest of the app — brand "Rumah" left, breadcrumb trail ("Reservations / New reservation") next to it as plain text with `/` separators (75% opacity, no link styling except the "Reservations" crumb which is a real link), EN/ID segmented control pushed right with `margin-left:auto`.
- **Page header**: h2 "New reservation" + muted subtitle "Enter what you have — the rest can wait." Leave clear air between the nav bar and this header (~20px+ beyond the section's own top padding) so the title doesn't crowd the sticky nav.
- **Optional outstanding-items banner**: only shown after a save where a tracked optional field (nationality) was left blank. Card styled as a warning banner — sage-tinted background (`--color-accent-2-100`) with `--color-accent-2-400` border, warning-triangle icon, bold title ("Still needs attention") + explanatory line, dismiss button (ghost, right-aligned) that clears it. This is feedback surfaced after the fact, not a validation blocker.
- **Three stacked cards**, each with a kicker label ("1. THE STAY" etc, `.card-kicker`) + h3 title, `--space-6` gap between cards:
  1. **The stay** — Villa (select, required) / Room type (select, required, disabled + placeholder "Choose a villa first" until a villa is picked) in a 2-col grid. Below: Check-in date / Check-out date / Number of guests in a 3-col grid, all required. Below that, a computed nights label ("4 nights") appears once both dates are valid. Below that, a room-availability check appears once villa + room + valid date range are all set: a clash warning (accent/terracotta tinted box, triangle icon, names the conflicting guest and their dates) or a free-to-book confirmation (sage-tinted box, checkmark icon).
  2. **The guest** — Guest full name (required, full-width). Phone / Email in a 2-col grid, both optional. Nationality (free-text input with a country datalist, optional) / Preferred language (select, optional — auto-fills from the selected villa's default language the first time, then respects manual edits) in a 2-col grid. If nationality is filled and isn't "Indonesian", a neutral-tinted info note appears: a police-report reminder for foreign guests.
  3. **Booking details** — Booked through (select, required) / Status (select, required, defaults to "Confirmed") in a 2-col grid. Nightly rate / Total amount / Amount paid (all optional, numeric-formatted IDR fields) in a 3-col grid — each shows a live formatted preview ("Rp 1.500.000") under the raw input as the user types. Below, a computed balance line appears once total + paid are both present: "Rp X still owed" (terracotta, bold) or "Paid in full" (sage, bold). Notes (optional, textarea, 2 rows, smaller `--radius-sm` corners rather than full pill).
- **Actions row**: "Save reservation" primary button + "Cancel" ghost button, left-aligned, side by side.
- **Toast**: on successful save, a pill-shaped dark toast ("Reservation saved") appears fixed bottom-center for ~2.4s, then the form resets to empty.

Required fields carry a plain accent-700 asterisk next to the label (matches Add Villa's convention). Optional fields show a small dimmed "(optional)" tag next to the label. No separate section splitting required vs. optional — they interleave within each card.

## Validation behavior

Not blocking per-field — validation happens only on submit ("Save reservation" click):
- A contact method (phone or email) is required at submit time even though both fields individually read as "(optional)" in the UI — this is a soft business rule, not a hard-required field, so no asterisk is shown.
- Villa, room type, check-in, check-out, guests, full name, booked-through, and status are all required at submit time (asterisked).
- If submit is attempted and requirements aren't met, nothing is shown in this design beyond the fields staying as-is (no error toast) — flag this gap to the team; a production build should add inline error states or a submit-blocked message.
- On a successful save where nationality was left blank, the outstanding-items banner appears (see above) as a post-save nudge, not a pre-save blocker.

## Computed/derived values (implement as pure functions of form state, not stored fields)

- **Nights**: `round((checkOut - checkIn) / 1 day)`, only shown when positive.
- **Room availability**: cross-references the selected room's existing bookings (mock data in this prototype — `VILLAS[].roomTypes[].bookings[]`) for date overlap against the entered check-in/check-out range.
- **Currency preview**: strips non-digits from the raw input, formats with `toLocaleString('id-ID')`, prefixed "Rp ".
- **Balance**: `total - paid`; positive → "still owed" (terracotta), zero/negative → "Paid in full" (sage).
- **Foreign-guest note**: shown whenever nationality is non-empty and not (case-insensitively) "Indonesian".
- **Language auto-fill**: when a villa is first selected, if the language field hasn't been manually touched yet, it's set to that villa's default language; a manual edit thereafter "sticks" and stops the auto-fill from overriding it on later villa changes.

## Data model note

Same underlying schema question as the Add Villa spec: this prototype's villa → room-type → bookings structure (with a `language` default per villa) is mock data for the prototype, not necessarily the repo's current schema. Reservations need a `Reservation` model (room FK, guest name, phone, email, nationality, language, booked_through, status, check_in, check_out, guests, nightly_rate, total_amount, amount_paid, notes) — confirm field names/types against whatever the repo's actual `Booking`/`Room` models end up being once the room layer lands (see Add Villa spec's note on Room/RoomCategory not yet existing in the schema).

## Copy (English + Indonesian)

Full bilingual copy for every label, placeholder, and message is in the `T.en` / `T.id` objects in `Add Reservation.dc.html`'s script block — copy these translation tables verbatim rather than re-writing strings; do not rewrite the English copy either.
