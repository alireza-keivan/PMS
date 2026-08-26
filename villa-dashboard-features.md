# Bali Villa Dashboard — Feature Overview

**The pitch, in one line:**
"A lightweight property management system built specifically for Bali villas — real-time booking sync, WhatsApp-native workflow, and honest legal compliance tracking, priced for the size of business that's actually here."

---

## Core Operations

1. **Real-time booking sync**
 The moment a guest books through Airbnb or Booking.com, it shows up on the dashboard instantly — not 15 minutes later like most budget tools.

2. **One calendar, every channel**
 Every villa and every booking platform in a single view. No more checking Airbnb, then Booking.com, then a spreadsheet separately.

3. **WhatsApp-native workflow**
 Staff and guests communicate through WhatsApp — the app everyone in Bali already uses, instead of a separate app nobody opens.

4. **Balinese-calendar-aware scheduling**
 The system automatically factors in local holidays like Nyepi, Galungan, and Kuningan when planning staff shifts.

5. **Owner reporting dashboard**
 A simple view of bookings, revenue, and occupancy an owner can check anytime — no need to ask anyone for a report. Includes a daily staff view too — who's arriving, who's leaving, and who still owes payment, all in one screen.

6. **AI screenshot-to-booking**
 Staff screenshot a WhatsApp booking conversation, and AI drafts the reservation form automatically. Staff just confirms with one tap.

---

## Guest Experience

7. **Guest request portal**
 Guests can request cleaning, repairs, or extras — like a private chef, grocery stocking, or airport transfer — directly from their phone.

8. **Curated local experience page**
 A page for each villa showcasing nearby tours, cooking classes, and activities — and a real source of referral income for the owner, since local operators typically pay commission.

9. **Private guest feedback triage**
 Around day 3 of the stay, guests get a quiet, private "how's everything going" prompt — not a public review request. Happy guests get gently invited to leave a public review; guests with a problem get routed straight to the owner instead, so it can be fixed before it turns into a bad public review. Any loyalty discount is offered separately, for booking direct again next time — never tied to what someone reviews, since Airbnb explicitly bans trading discounts for reviews and it risks the listing itself.

---

## Marketing & Distribution

10. **Google metasearch presence (free direct bookings)**
 The villa's own rate shows up right next to Airbnb and Booking.com when a guest searches on Google — pulling bookings toward a direct channel instead of paying OTA commission. This runs through the same booking system already powering the sync, at no extra cost — no ad spend required to turn it on.

11. **Direct payment collection**
 Guests booking directly can pay by credit card or digital wallet (Apple Pay, Google Pay) right on the villa's own booking page — the payment goes straight into the owner's own account. Pairs naturally with #10: driving direct traffic only pays off if there's a way to collect payment once they arrive. One caveat to flag honestly: this needs the owner to have their own payment account, which in Indonesia generally requires a registered business — so it isn't available on day one for an owner who isn't yet properly licensed.

12. **Rate parity check**
 Compares the villa's own rate across Airbnb, Booking.com, and the direct booking page, so an OTA quietly undercutting the direct rate gets caught immediately. This protects the value of #10 and #11 — driving guests to book direct only pays off if the direct rate isn't accidentally the most expensive option.

13. **Mini villa website**
 A simple, templated one-page site for each villa — photos, amenities, description — built once and reused for every client. Gives owners somewhere clean to send Instagram followers instead of a chaotic WhatsApp DM, with booking handled by the same engine powering #10 and #11.

---

## Legal & Compliance — ready to present

14. **Compliance document vault**
 Every license (NIB, PBG, SLF) stored in one place, with automatic alerts before anything expires — so nothing quietly lapses. Fully within the app, no government interaction needed.

15. **Guest police-reporting reminder (STM)**
 The system tracks which foreign guests still need their 24-hour police report filed and flags anyone approaching the deadline. This is a reminder, not automatic filing — the report itself is still a manual paper process with police, and that's not changing.

16. **Action-needed status view**
 A simple counter showing how many compliance items need attention this week — expiring documents, upcoming police-report deadlines. Deliberately framed as "what needs doing," not "verified compliant," since some of the underlying steps are still manual.

---

## Backlog — not ready to build or present yet

- **Automatic PHR tax calculation** — parked for now. Feedback from the ground is that under-reporting revenue to reduce hotel tax is common practice among smaller villa owners, so a tool built around "accurate, automatic tax numbers" may not be something that segment actually wants. Revisit this specifically for larger, professionally-run management companies, who have real audit exposure and want clean, defensible numbers — not as a general pitch to independent owners.

- **Yield rules (automated inventory/channel control)** — parked for now. Useful for portfolio operators managing many villas who want to strategically control how much inventory each channel sees, but not relevant to a single-villa owner with only one unit to sell. Also the highest-risk feature to build, since it writes live changes to channel availability instead of just reading data — a bug here risks blocking real bookings or causing the exact double-booking problem this product exists to prevent. Revisit only once a client has a large enough portfolio for it to matter.

- **Pace report (year-over-year booking comparison)** — parked for now, not a difficulty problem but a data problem: it needs a full year or more of historical bookings to be meaningful, which no new client will have on day one. Revisit once clients have been on the platform long enough to accumulate that history.

- **Booking performance insights (source market map, channel mix, ADR trends)** — parked for phase two. Genuinely useful for a client's marketing decisions, but requires real engineering (geo-mapping guest nationality, trend calculations over time) that isn't essential for launch. Good feature to add once the core product is validated.

- **Competitor rate shopping** — do not build. Unlike everything else on this list, this needs data you don't own and can't get for free: either a paid third-party rate-intelligence subscription (real ongoing cost) or scraping OTA listings, which is fragile and against most OTAs' terms of service. Genuinely a different category of feature from the rest of this product.

---

**Why this matters, in one line:**
"Big international software handles bookings. Nothing handles the Indonesian legal side honestly. That's the gap this fills."
