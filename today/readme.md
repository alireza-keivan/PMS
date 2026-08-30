# Handoff: Rumah — Today Page (Desktop)

## Overview
This is the "Today" screen for Rumah, a villa property management dashboard for small Bali villa operators. It's the daily working screen: what's happening today across all the operator's villas, at a glance. This handoff covers the **desktop layout only** (≥1024px). A companion screenshot shows the rendered result.

## About the Design Files
The bundled file (`reference.dc.html`) is a **design reference built in HTML**, not production code — do not copy its markup or inline styles directly into the app. Treat it as a precise visual and structural spec. Recreate it in the target codebase's existing framework (React, Vue, etc.) using that codebase's existing component patterns, state management, and data layer. If no frontend framework exists yet in this codebase, pick the most appropriate one for the stack and implement there.

## Fidelity
**High-fidelity.** Colors, type, spacing, radii and the card system are final — pull exact values from the Design Tokens section below rather than eyeballing the screenshot. Copy strings (titles, labels) are final and should be used verbatim.

## Screen: Today

### Purpose
A single scannable view answering four questions for the operator: which rooms are occupied right now, who's arriving today, who's leaving today, and who still owes money. It should be understandable in five seconds with no explanation needed.

### Overall structure (top to bottom)
```
Page (padded container, background = --color-bg)
├── Page header: "Today" (h2) + date subline (muted, small)
├── Stat strip (row, 2 items)
│   ├── Revenue-this-month tile
│   └── Needs-doing tile
└── Lists section (2×2 grid, 2 columns × 2 rows)
    ├── Occupied today      (top-left)
    ├── Arriving today      (top-right)
    ├── Leaving today       (bottom-left)
    └── Still owe money     (bottom-right)
```
These two groups (stat strip, then the 2×2 list grid) are the entire content of the page — there is nothing else on this screen besides the shared top app nav bar (not part of this handoff).

### Relationships between elements — READ THIS CAREFULLY
- The stat strip and the list grid are **stacked vertically, independent groups** — not part of the same grid. The stat strip is a plain horizontal flex row; the list grid below it is a separate 2-column CSS grid.
- **All four list cards are visual siblings of equal weight and identical structure.** They must share one component: same header pattern, same card chrome, same row template, same scroll behavior. Do not build "Occupied today" as a special/bigger component and the other three as lesser ones — this was an earlier version's bug that this redesign explicitly corrects. If you're tempted to give one card different padding, header size, or card style than the others, stop — that's wrong.
- Every list card's row content is **guest-and-stay data**, just filtered and annotated differently:
  - Occupied today = bookings where today falls inside [check-in date, check-out date) — i.e. currently in-house tonight.
  - Arriving today = bookings where check-in date = today.
  - Leaving today = bookings where check-out date = today.
  - Still owe money = bookings (regardless of date) with a nonzero outstanding balance.
  - A single guest/booking can appear in more than one list simultaneously (e.g. arriving today AND still owes money) — these are independent filters over the same underlying booking dataset, not four separate lists to maintain by hand.
- The count badge in each card header is a **live count of that card's rows**, not a static label — wire it to `list.length`, matching whatever's currently rendered (including empty state = 0, not hidden).
- Each list card scrolls internally (`max-height` + `overflow-y:auto`) instead of growing the page — this is what keeps the 2×2 grid's row heights aligned even when one list has many more entries than another. All four cards in a row/column pair should be visually equal height; the scroll is what guarantees that regardless of data volume.
- The 2×2 grid must **reflow to a single column on narrow viewports** (the mobile version, covered separately, stacks all four cards vertically and shows the stat strip as one compact row above them). On desktop keep it locked at 2 columns.

## Layout — measurements
- Page horizontal/vertical padding: `--space-6` (26.4px) sides, with `--space-8` (35.2px) bottom.
- Header block: h2 "Today", 2px margin-bottom, then a muted `<p>` for the date, `--space-6` margin-bottom below it before the stat strip.
- Stat strip: `display:flex`, `gap:12px`, `margin-bottom:18px`. Two tiles, each `flex:1`.
- List grid: `display:grid`, `grid-template-columns:repeat(2, 1fr)` (use `minmax(280px,1fr)` with `auto-fit` if you want it to self-collapse to 1 column at narrow desktop widths too), `gap:16px`.

### Stat tile component (used twice: Revenue, Needs doing)
- Container: flex row, `align-items:center`, `gap:10px`, background `--color-surface`, `border-radius:--radius-lg` (28px), shadow `--shadow-sm`, padding `14px 16px`.
- Leading icon: 34×34px circle (`border-radius:50%`), icon centered, 17×17px SVG stroke icon, stroke-width 2.75.
  - Revenue tile: icon bg `--color-accent-200`, icon color `--color-accent-800`, trending-up/chart icon.
  - Needs-doing tile: icon bg `--color-accent-2-200`, icon color `--color-accent-2-800`, clipboard/checklist icon.
- Text block: label line then number line.
  - Label: 10.5px, uppercase, letter-spacing 0.05em, 60% opacity.
  - Number: `--font-heading` (Caprasimo), 20px.
- Copy: "Revenue this month" / "Rp 48,200,000" (format as local currency, live figure). "Needs doing" / "4 tasks" (live count of open guest-request/maintenance tasks — see Guest Requests screen in the wider brief; not built out yet, just referenced here as a number).

### List card component (used 4×: Occupied, Arriving, Leaving, Owing)
**Header** (above the card, not inside it): flex row, `gap:8px`, `margin-bottom:10px`.
  - 16×16px SVG icon, stroke `--color-accent-700`, stroke-width 2.75. Distinct icon per card (home = Occupied, arrow-into-box = Arriving, arrow-out-of-box = Leaving, wallet = Owing).
  - `<h4>` title, no margin: "Occupied today" / "Arriving today" / "Leaving today" / "Still owe money".
  - Count badge, pushed right with `margin-left:auto`: `tag tag-neutral` for Occupied/Arriving/Leaving, `tag tag-accent` for Owing (it's the one that needs attention).

**Card body**: background `--color-surface`, `border-radius:--radius-lg`, shadow `--shadow-sm`, `overflow:hidden`. Inner scroll wrapper `max-height:220px; overflow-y:auto`.

**Row** (repeats per item): flex row, `gap:10px`, `padding:10px 14px`, `border-bottom:1px solid --color-divider` (omit on last row).
  - Avatar: 30×30px circle, guest's first-initial, `--font-heading` 12px. Background/color pulled from the accent/accent-2/neutral ramp, rotated per row so adjacent guests are visually distinguishable (not meaningful data, just a rotation for scannability).
  - Name + sub-line block (`flex:1`, allow truncation): name bold 13px; sub-line 11.5px at 65% opacity — villa name (+ room, for Occupied) for the three occupancy lists, or omitted for Owing where the meta column carries the info instead.
  - Right-aligned meta (`flex:none`, right-text, 65% opacity, 11–12.5px):
    - Occupied: "Night X of Y".
    - Arriving: "Check-in [time]".
    - Leaving: "Check-out [time]".
    - Owing: the outstanding amount, bold, colored `--color-accent-700` (this is the one list where the meta column is the primary data, not a secondary annotation).

**Empty state**: if a list has zero rows, show a single muted 13px line inside the card body instead of the scroll list (e.g. "No one arriving today" / "Everyone is paid up") rather than an empty white box.

## Design Tokens
- `--color-bg`: `#f5ead8` (page background)
- `--color-surface`: `#ebddc5` (card background)
- `--color-text`: `#201e1d`
- `--color-divider`: `color-mix(in srgb, #201e1d 16%, transparent)` (row separators)
- `--color-accent` (terracotta): `#c67139` — ramp 100→900, key steps used: `-200` `#ffe1d0`, `-700` `#8c491a`, `-800` `#643312`
- `--color-accent-2` (sage): `#7a8a5e` — key steps used: `-200` `#e1eecc`, `-800` `#3d472b`
- `--color-neutral`: key steps used: `-100` `#f9f4ed`, `-200` `#eee7db`, `-700` `#645c50`, `-800` `#474238`
- Heading font: `"Caprasimo"`, weight 400 (display headings and stat numbers only)
- Body font: `"Figtree"`
- Radii: `--radius-sm` 8px (small chips), `--radius-md` 16px, `--radius-lg` 28px (all cards/tiles)
- Shadows: `--shadow-sm` `0 1px 2px color-mix(in srgb, #2e2b25 14%, transparent)` (cards/tiles), `--shadow-md` for stronger elevation if needed
- Spacing scale used on this screen: `--space-2` 8.8px, `--space-3` 13.2px, `--space-4` 17.6px, `--space-6` 26.4px, `--space-8` 35.2px
- Icons: Lucide icon set, stroke-width 2.75 throughout

## Interactions & Behavior
- No modals or navigation live on this screen in the current design — it's read-first. Rows are static in this mock; if the target app wants rows clickable (e.g. to open a booking or guest profile), that's an extension, not specified here — confirm with design before adding.
- Each list card's inner list scrolls independently on overflow; the page itself does not need to scroll unless the viewport is short.
- No loading/error states were designed — treat data as available synchronously from whatever the app's existing booking data source is; add a skeleton/spinner per the codebase's existing conventions if async loading is required.

## State Management
- Four derived lists (occupied, arriving, departing, owing), computed from one source of truth: the bookings dataset for the operator's villas. See "Relationships between elements" above for the exact filter logic each list applies — implement these as derived/computed values (selectors), not four independently-fetched or independently-maintained arrays.
- Revenue and Needs-doing are separate aggregate figures, not derived from the same booking array in this mock — they'll likely come from whatever revenue/task-tracking data source exists elsewhere in the app.

## Assets
No images or icons beyond inline SVG (Lucide-style, stroke-width 2.75) drawn directly in the markup. No external image assets are used on this screen.

## Files
- `reference.dc.html` — the HTML design reference (desktop and mobile frames both present; this handoff is scoped to the **desktop** frame only — ignore the "MOBILE" labeled frame in that file for this handoff).
- A screenshot of the desktop layout will be provided separately by the user alongside this package.
