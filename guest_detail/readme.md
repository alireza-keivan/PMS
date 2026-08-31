# Handoff: Guest Detail Page

## Overview
Guest profile page for Rumah, a villa property management tool. Shows one guest's bookings, requests, contact info, private staff feedback, activity log, and police report reminders.

## About the Design Files
The bundled HTML file is a **design reference built in HTML** — a prototype showing intended look and behavior, not production code to copy directly. Recreate this design in the target codebase's existing environment (React, Vue, etc.) using its established patterns and libraries. If no environment exists yet, choose the most appropriate framework and implement there.

## Fidelity
**High-fidelity.** Colors, typography, spacing, and layout are final. Recreate pixel-perfectly using the codebase's existing component library where one exists, or build to these exact values.

## Design System
Built on the "Organic" design system: warm cream/sand background, terracotta primary accent, sage secondary accent, Caprasimo display headings over Figtree body text, generous rounded corners. Reference `_ds/organic-.../styles.css` (bundled) for the full token set — colors ramps (100–900), spacing scale, radii, shadows.

## Layout
- Sticky top nav bar: logo "Rumah", nav links (Villas / Guests / Compliance / Messages / Marketing), user avatar + email, right-aligned.
- Page container max-width 1100px, centered, horizontal padding via `--space-6`.
- "← Back to guests" link, then guest name (h2) + stay-count tag, right-aligned tag row.
- Two rows of 3 cards each in a `repeat(3, 1fr)` grid, `--space-5` gap, collapsing to 1 column under 760px:
  - Row 1: Bookings, Requests, Guest info
  - Row 2: Private feedback, Recent activity, Police report reminders

## Components
**Card** (all six use this pattern):
- `.card.elev-sm`, border-radius 20px, fixed height 304px, internal padding 10px (all sides — set directly on the card, overriding the base `.card` padding)
- Header: `<h4>` title, no bottom border
- Body: scrollable list area (`overflow-y:auto`, thin custom-colored scrollbar using accent-600/neutral-200), each row separated by a 1px divider, `--space-3` vertical padding per row
- Rows show **4 at a time** — the 5th+ item scrolls into view; a bottom fade gradient (36px, transparent → surface color) appears when content overflows past 4 rows
- Empty states ("No requests yet.", "No feedback yet.") shown in muted text when a list is empty

**Row content per card:**
- *Bookings*: villa name + date range (bold), source + status (muted, smaller)
- *Requests*: title (bold), detail (muted)
- *Guest info*: uppercase label (muted, 11px), value (bold) — fields: Full name, Phone, Email, Nationality, Preferred language, Total expenditure, Amount due (currency formatted as Rp with locale grouping)
- *Private feedback*: note (bold), author + date (muted)
- *Recent activity*: action (bold), timestamp (muted)
- *Police report reminders*: villa name (bold), status tag (`tag-accent` for "Overdue", `tag-neutral` for "Marked as done by staff"), deadline (muted)

## Interactions & Behavior
- Card lists scroll independently; overflow fade only shows when list length > 4.
- No other interactivity in this prototype (nav links, back link, and tags are static — wire up navigation/routing as appropriate for the target app).

## Design Tokens
Pull all values from the Organic design system stylesheet — do not hardcode:
- Colors: `--color-bg`, `--color-text`, `--color-surface`, `--color-divider`, `--color-accent-*` (100–900), `--color-accent-2-*`, `--color-neutral-*`
- Type: `--font-heading` (Caprasimo), `--font-body` (Figtree)
- Spacing: `--space-3` through `--space-8`
- Radius: `--radius-lg` (cards use a locally-overridden 20px per direct edit)
- Shadow: `.elev-sm`

Text sizes used directly (not tokenized in this prototype): 19px (logo), 13.5px (body/rows/nav), 12px (meta/muted), 11px (uppercase labels), 10.5px (badges).

## Data / State
Static mock data in the file — replace with real API data of the same shape:
- `guest`: name, email, phone, stays, country, nationality, language, totalSpent, amountDue
- `bookings[]`: villa, dates, source, status
- `requests[]`: title, detail (currently empty — empty state)
- `feedback[]`: note, author, date (currently empty — empty state)
- `activity[]`: action, timestamp
- `policeReminders[]`: villa, badgeClass, badgeLabel, deadline

Each list's "overflow" flag is `list.length > 4` — drives whether the fade gradient renders.

## Files
- `Guest Detail.dc.html` — full design reference for this page.
