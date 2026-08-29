# Handoff: Villa Booking Dashboard (Rumah)

## Overview
A desktop booking-calendar dashboard for a villa property management system (PMS). One screen so far: a Gantt-style booking calendar showing every villa, grouped by area, with each villa's rooms and their bookings on a scrollable date timeline. Built as an HTML/React design prototype — not production code.

## About the design files
The bundled file (`Villa Dashboard.dc.html`) is a **design reference built in HTML**, not code to copy into the app. Recreate it in the target codebase's actual stack (this project is Django + server-rendered templates + vanilla JS per the `PMS` repo, so implement the interactive pieces — drag/resize, modals — as progressively-enhanced JS on top of the existing Django templates, or in whatever frontend layer the repo has since standardized on). Match layout, spacing, color and behavior as described below; don't port the HTML verbatim.

## Fidelity
**High-fidelity.** Colors, type, spacing and radii below are final design-system values. Copy, layout proportions and interaction behavior should be pixel/behavior-matched.

## Data model note
This design was built against `alireza-keivan/PMS`'s real schema: `Villa` (grouped by `area`) → `Booking` (status derived: confirmed / checked_in / checked_out / blocked / payment_incomplete — payment_incomplete always overrides stay-stage). **Rooms and room categories are NOT in the current repo schema** — the Room/RoomCategory layer in this design is a forward-looking mockup requested by a teammate, not yet backed by a migration. Flag this to whoever owns the schema before implementing; the room layer will need a `Room` model (villa FK, name, category) and bookings should move from `Villa` to `Room`.

## Design tokens

Colors:
- Background (page): `#f5ead8`
- Surface (cards, header bar, table): `#ebddc5`
- Text: `#201e1d`
- Accent (primary, terracotta): `#c67139` — hover `#a85f2e`-ish (one step down the ramp), active darker still
- Accent 2 (sage, secondary): `#7a8a5e`
- Divider: `#201e1d` at 16% opacity
- Each accent has a 100–900 tonal ramp generated in OKLCH; light steps (100–300) for tinted fills/hovers, 500 = base, 700–900 for text-on-tint and pressed states.

Typography:
- Headings: "Caprasimo" (display serif-ish, single weight 400)
- Body/UI: "Figtree"
- Base body size 15px, line-height 1.55
- Headings: line-height 1.12, letter-spacing -0.015em

Spacing scale (used as gap/padding throughout): 4.4 / 8.8 / 13.2 / 17.6 / 26.4 / 35.2 px

Radii: small controls 8px, cards/inputs 16px, large containers 28px (cards/dialogs round up further to ~32px). Buttons, inputs, tags, segmented controls are all fully pill-shaped (999px).

Shadows: sm `0 1px 2px rgba(46,43,37,.14)`, md `0 3px 10px rgba(46,43,37,.16)`, lg `0 12px 32px rgba(46,43,37,.22)`.

Overall style: warm cream/sand ground, rounded-pill controls, no sharp corners, no gradients, minimal icon use (Lucide-style line icons, stroke-width ~2.75).

## Screen: Booking calendar

### Layout
- Full-height page, `background: var(--color-bg)`.
- **Top nav bar** (sticky, `top:0`, height ~64px): brand wordmark "Rumah" (heading font, 19px) left; a 2-option segmented control (Calendar / Today) next to it; user avatar (28px circle, accent-300 bg, initial letter) + user name (12.5px, 75% opacity) pushed to the right with `margin-left:auto`; an EN/ID language segmented control at the far right.
- **Page header**: "Booking calendar" (h2) + subtitle "All villas, one view." in muted text, padded from page edges.
- **Toolbar row** (wraps on narrow widths): a 3-option segmented control for date range (7 days / 14 days / 30 days); a date-nav cluster of 5 icon buttons — `<<` jump back by a full range, `<` back 1 day, a center pill button showing the current date range label (click = jump to today), `>` forward 1 day, `>>` jump forward a full range; a search input with a leading search icon; a primary "New booking" button pinned right.
- **Legend row**: small dot + label pairs for each booking status (Confirmed, Checked in, Checked out, Not available, Payment incomplete), each dot colored/bordered per status (see Status colors below).
- **Calendar card**: rounded 28px container, surface background, `shadow-sm`, margin from page edges.
  - **Date header row**: sticky at `top:64px` (right under the nav), same surface background, rounded top corners. Left gutter 220px wide (empty, aligns with villa/room name column). Right side: a grid of N equal columns (N = selected day range), each showing weekday abbreviation (10px, uppercase, 55% opacity) over day number (heading font, 15px). Today's column gets an accent-tinted background band.
  - **Body rows**, in a rounded-bottom, clipped container:
    - **Area group row**: sticky-adjacent divider row, tinted neutral background, uppercase small label (e.g. "CANGGU"), spans full width.
    - **Villa row**: 220px left gutter with: expand/collapse chevron button (▸/▾) toggling that villa's rooms, a 30px color-swatch circle (a per-villa accent color, cycled from a small palette), an inline-editable villa-name text input (click to rename — write straight to state, no separate "edit mode"), a trash/remove icon button (opens the confirm dialog). Right side of a villa row is empty (villas hold no bookings directly — only their rooms do).
    - **Room row** (only rendered when the parent villa is expanded): shown with a light neutral-tinted background, 44px-indented left gutter containing an inline-editable room-name input, a small pill tag showing the room's category (Deluxe / Suite / Standard — each tag gets a distinct tint from the accent/accent-2/neutral ramps), and a remove-room icon button. Right side is a 52px-tall day-grid timeline (weekend columns are NOT tinted — only "today" gets a tint) with booking bars drawn on top:
      - Each booking bar: absolutely positioned by day offset/span, 9px vertical inset, rounded (radius-sm), colored/bordered per status, flex-centered guest name label (falls back to "Booked" for nameless/blocked bars), min-width 44px so short bars stay legible.
      - Two 7px-wide invisible resize handles on the left/right edges of each bar (cursor `ew-resize`); dragging the bar body (cursor `grab`) moves it; drags are clamped so a booking can't overlap its neighbors in the same room, and can't be resized/moved past 0 or the visible range's end.
      - Dragging a bar vertically across room rows re-parents that booking to the room under the pointer.
      - Clicking a bar (without dragging) opens a **booking detail popover**: modal, centered, surface card, shows a colored status dot + status label, guest name (heading, large), "Villa · Room" line, date range line, an amount-owed tag if applicable, and Remove booking / Close actions.
      - Clicking empty timeline space opens a **New booking modal**: villa/room/date context line, a single "Guest name" field (leaving it blank creates a blocked/unavailable block instead of a real booking), Cancel / Add actions.
    - **"+ Add room" row**: appears under an expanded villa's rooms; ghost-style button.
  - **"+ Add villa" footer row**: full-width, secondary button, appends a new empty villa (with a default area/name) to the bottom of the list.
- **Remove confirmation dialog**: shared by both "remove villa" and "remove room" actions — centered modal, message line ("Remove Villa X? This can't be undone." / "Remove room X? This can't be undone."), Cancel (ghost) / Remove (primary, accent-filled) actions.

### Status colors (booking bars + legend dots)
- Confirmed: accent-2 (sage) tint fill, sage border
- Checked in: solid sage-ish stronger fill
- Checked out: neutral/muted fill
- Not available / blocked: hatched or flat neutral fill, no guest name (shows "Booked"/blank)
- Payment incomplete: accent (terracotta) tint fill — this status overrides all others regardless of stay stage

## Interactions & behavior
- Inline editing: villa and room names are plain text inputs styled to look like static text until hovered/focused (hover = subtle neutral fill, focus = accent-tinted fill + accent outline). Typing commits immediately to state — no explicit save button.
- All destructive actions (remove villa, remove room, remove booking) require the confirm dialog or are one click away from the detail popover — never a silent delete.
- Add villa / Add room are additive-only actions with sensible defaults (name auto-numbered, category defaults to "Standard").
- Date navigation: `<<`/`>>` jump by the full visible range; `<`/`>` step by 1 day; the center label button resets to today.
- Language toggle (EN/ID) swaps all UI copy via a simple translation-table lookup — every user-facing string in the app has an `en`/`id` pair.
- Modals/popovers close on backdrop click or their own Close/Cancel button; clicking inside the modal card does not close it (stopPropagation).
- The date header row stays pinned under the nav bar while scrolling the villa list, so date columns are always visible above whatever villa/room row is on screen.

## State needed
- List of villas: `{ name, area, swatch, rooms: [{ name, category, bookings: [{ guest, start, span, status, owing }] }] }`
- Currently selected date range (7/14/30 days) and a day offset for pagination
- Set of expanded villa indices
- Current language (en/id)
- Transient UI state: open booking popover, open confirm dialog, open "new booking" draft (villa/room/day + guest name field)

## Assets
No photography — this screen is data/UI only. Icons are inline SVG, Lucide-style line icons (stroke-width 2.75, rounded caps/joins).

## Screenshots
- `screenshots/calendar.png` — default calendar view, villas collapsed
- `screenshots/expanded-rooms.png` — a villa expanded showing its rooms and booking bars
- `screenshots/booking-detail.png` — the booking detail popover
- `screenshots/new-booking.png` — the new-booking modal
- `screenshots/remove-confirm.png` — the remove-villa confirmation dialog

## Files in this bundle
- `Villa Dashboard.dc.html` — the full design reference (HTML/React-in-template prototype). View source for exact markup/structure if needed, but recreate in the target stack rather than copying it.
