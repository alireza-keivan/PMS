# Bali Villa Management Dashboard

## What this is
A lightweight property management dashboard built specifically for Bali villa operators — not a hotel PMS, not a generic global tool. Real-time booking sync, WhatsApp-native workflow, and honest legal compliance tracking, priced for the size of business that's actually here.

## Backend stack
**Python, Django.** The core of this product is a data model with role-based permissions — villas, bookings, guests, staff, compliance documents — viewed differently by owners, staff, and guests. Django's ORM, migrations, auth, file storage, and built-in admin cover all of that on day one, which matters more here than raw async ergonomics.

Specifics:
- **Django Ninja** for webhook endpoints and external-facing API routes (Beds24, WhatsApp, Stripe callbacks) — Pydantic-style validation and easy async views inside the Django project. Don't split this into a separate FastAPI service; keep one codebase.
- **`httpx`** for outbound async calls to external APIs. Django async views (4.1+) handle this fine — do not assume Django is sync-only.
- **Celery** for background and scheduled jobs (compliance reminders, periodic sync reconciliation, delayed guest messages). Use n8n only where a visually inspectable workflow is genuinely worth the extra hosting cost — see Automation tooling below.
- **Django admin** doubles as the internal ops panel for inspecting client data and manual overrides. Don't build custom internal-only screens that the admin already handles.

## Who it's for
Operators managing roughly 3-15 separate villas. Not single-villa owners (not enough operational pain to justify paying monthly), and not large portfolio operators with 20+ villas (already courted by Guesty/Hostaway enterprise sales). The target is someone juggling multiple independent bookings and calendars at once, where manual tracking genuinely breaks down.

## Tech decision: sync through Beds24, not direct to Airbnb/Booking.com
Airbnb and Booking.com do not offer API access to individual developers — only to approved Connectivity Partners, and that program isn't realistically open to a small project like this. Instead, this project syncs booking, calendar, and rate data through **Beds24's API**, which already has that partner access.

Beds24 also has built-in support worth using instead of building from scratch:
- **Google for Vacation Rentals (Free Booking Links)** — free, no commission, just needs a setting turned on and a verified Google Business Profile
- **Stripe integration** for direct-booking payments — funds go straight to the owner's own account

Do not attempt to integrate directly with the Airbnb or Booking.com APIs — that path is gated behind a partner program not available to us.

### Hybrid sync strategy
Not every client will use or be able to afford Beds24. Support two tiers:
- **Premium tier (Beds24):** near-real-time sync, full guest details, pricing, and messaging — for clients already using or willing to pay for Beds24.
- **Basic tier (iCal calendar feeds):** free, no partner approval needed — but one-way and higher-latency (OTAs typically refresh iCal feeds every few hours, not instantly), availability/date-blocking only, no guest names, no pricing, no messages.

Be explicit with clients and in the UI about which tier they're on. Never present the basic tier's data as real-time or complete when it isn't — several features (AI screenshot-to-booking, real-time alerts, detailed owner reporting) will be meaningfully more limited on the basic tier, and that difference should be visible, not hidden.

## Core philosophy — follow these rules on every feature
1. **WhatsApp automation, built the right way.** When a guest takes an action in the dashboard that needs staff attention (requesting cleaning, reporting a repair, anything similar), the backend should automatically trigger an outbound WhatsApp message to the relevant staff member — not just log it and hope someone checks the dashboard. Use the official **WhatsApp Business Platform (Cloud API)**, through a Business Solution Provider like Twilio or 360dialog. Never use unofficial or reverse-engineered WhatsApp automation libraries (e.g. anything simulating a WhatsApp Web session) — that violates WhatsApp's terms and risks the number getting banned. Note: business-initiated messages sent outside a 24-hour window since the last message from that person require a pre-approved message template — factor that into how any automated outbound flow is designed.
2. **Be honest about automation — never overstate it.** Don't label something "automatic" or "verified" if a human step is still required. Example: the guest police-reporting feature (STM) is a *reminder*, not automatic filing — the report itself is still a manual paper process with police. The compliance status view shows "items needing attention," not "verified compliant."
3. **Never build incentivized reviews.** Do not build any feature that offers a discount or reward conditioned on a guest leaving a review, or specifically a positive one — this directly violates Airbnb's review policy and risks a client's listing being penalized.
4. **Simple over clever.** This is a solo/two-person team. Prefer straightforward, boring, maintainable solutions over elaborate ones.
5. **Never write to real booking/availability data without confirmation first.** Read operations are fine to run freely; anything that writes to live inventory needs explicit confirmation.

## Frontend stack
**Django templates + HTMX + Alpine.js + Tailwind CSS.** One codebase, one deploy, server-rendered. Do not build a separate React/Next SPA for this project.

Reasoning:
- The dashboard is tables, lists, forms, and status views with partial updates — HTMX territory, not client-state-heavy React territory.
- The mini villa websites (#13) are public, SEO-sensitive, and image-heavy. Server-rendered Django templates handle this natively; a SPA would require adding SSR as a third framework.
- Bilingual EN/ID is handled by Django's built-in i18n across templates — one translation system, not two kept in sync.
- Django session auth throughout. No token/CORS layer, no Node build step in production.

Specifics:
- **HTMX** for partial page updates (refreshing a booking list, submitting a guest request, updating a compliance status) — prefer this over writing custom JS fetch calls.
- **Alpine.js** only for small local UI state (dropdowns, modals, toggles). If a component starts needing complex state management, that's a signal the UI is too complicated — simplify it rather than reaching for a heavier tool.
- **Tailwind CSS** for styling. Define design tokens (spacing, type scale, color palette) up front and reuse them; don't scatter arbitrary values.
- **Tailwind is compiled to a static file — rebuild it after any styling change.** `static/css/tailwind.css` is generated from the classes found in the templates. A class that isn't in that compiled file simply does nothing in the browser, silently, with no error. So any time you add or change a class in a template, run the build or the change will not appear:
  - `npm run css` — watch mode, rebuilds as you edit. Use this while working on templates.
  - `npm run css:build` — one-off minified build.

  Then hard-refresh the browser (Ctrl+Shift+R) to get past the cached stylesheet. If a styling edit appears to do nothing, suspect the stale build first — check whether the class is actually present in `static/css/tailwind.css` before editing the markup again. This applies to variants too: `bg-black` being compiled does not mean `bg-black/50` is.
- **vis-timeline** (free, open-source) for the multi-villa calendar view — rooms/villas as rows, dates across the top, bookings as colored bars. Do not use FullCalendar's Resource Timeline view for this — that specific layout is part of FullCalendar's paid add-on (roughly $480 one-time), not the free core. Revisit that paid upgrade only once there are paying clients to justify it.
- Mobile-first for all guest-facing screens — guests are on phones, and so are most staff.

## Plain language, no jargon
Every piece of text a user sees — tooltips, labels, buttons, error messages, onboarding text — must be in plain, simple language. No technical terms, no industry jargon. If a word needs explaining, replace it instead of defining it. Model: "Keeping track of bookings from different sites can feel impossible. See everything in one place." — plain problem, plain benefit, no jargon.

If a genuinely stateful feature emerges later (live drag-and-drop across villas, real-time collaborative ops board), React can be added to that single page in isolation. Don't preemptively adopt it for the whole project.

## Design principles
- **Apple-simple, not admin-panel-complex.** Most villa managers are not technical and get overwhelmed by too many raw options on one screen. Every screen should have one clear default action and minimal visible choices — hide advanced/rare options behind a secondary step (progressive disclosure) rather than exposing everything at once.
- **Bilingual from day one: English and Bahasa Indonesia.** Every UI string, notification, and label needs both languages. Set up proper i18n/localization structure before writing any UI text directly into components — don't retrofit this later.

## Images
Serve guest-facing and villa photos as WebP wherever possible — smaller file size, faster load, supported by all modern browsers. If the image library or service in use doesn't support WebP output, don't silently fall back to a different format — stop and propose alternatives (a different processing library, or a CDN/image service with WebP support) before proceeding.

## Automation tooling: consider n8n
For automation and workflow logic (WhatsApp triggers, AI processing pipelines, compliance reminders, etc.), consider n8n as an option alongside custom backend code — its visual workflow builder is easier for a non-technical team to inspect and modify later. Trade-off to weigh: self-hosting n8n adds its own server/maintenance cost, and n8n Cloud has its own subscription — check this against the "keep costs low" principle above before defaulting to it for every automation.

## Feature reference
See @villa-dashboard-features.md for the full feature list, grouped by category, plus the backlog of features that are intentionally excluded or delayed — and why.

## Logging
Along the way, build a logging system to see how each section works. It should be very detailed and functional.

## communication
Whenever chatting with me, be simple and don't use jargons. you can use tech words, but not English jargons.

## Gitignore file
Whenever you create files/folders, make sure you update the .gitignore file.

## Build order
1. Beds24 sync + owner reporting dashboard (the foundational data pipeline everything else depends on)
2. Compliance document vault + action-needed status view (cheap, low-risk, high demo value — mostly reading and displaying data)
3. WhatsApp-native workflow + AI screenshot-to-booking
4. Marketing & distribution features (Google listing, direct payments, mini website, rate parity)
5. Guest experience features (request portal, experience page, feedback triage)

Do not build anything from the Backlog section of the feature doc without checking in first — several items are parked for real reasons (legal risk, missing data, or a segment mismatch), not just low priority.

## Git rules
**Never run `git push`, or push to any remote repository (GitHub or otherwise), under any circumstances** — even if it seems like a routine or expected next step. Local commits are fine. Pushing to a remote is always done manually, by me, never automatically.