# Reporting page — what else could go on it

Working list for the owner reporting screen (`/reporting`, feature #5).
Everything here can be built from data already in the database — no new
outside connection needed.

## Already on the page

Five headline numbers, money received each month (bar chart), how full the
villas were over time (line chart), where bookings come from, guest
nationality, villa-by-villa table, money still owed, and how fresh the
booking data is.

---

## Strongest additions (useful and cheap)

### 1. What's already booked ahead — **built**
Nights and money confirmed for the next 30 / 60 / 90 days. The rest of the
page looks backwards; an owner's first question is usually "how does next
month look?"

Built in `_booked_ahead()` in [apps/reporting/views.py](../apps/reporting/views.py),
windows defined as `AHEAD_WINDOWS` in [apps/reporting/reports.py](../apps/reporting/reports.py).
It always counts forward from today and ignores the date picker, which the
card says in words. Money shown is the value of stays arriving in the window,
not money received.

### 2. Direct vs booking-site money
`BookingPayment.kind` already records paid by the site / paid directly /
deposit / refund. Showing the split is the number an owner cares about most —
money that didn't pay commission. It also builds the case for the direct
booking work (features #10 and #11).

### 3. How complete the data is
How many bookings are full detail vs calendar-only — `Booking.source_detail`
is exactly this. Fits the honesty rule head on: it tells the owner *why* some
numbers are blank instead of leaving the screen looking broken. Pairs with the
premium/basic tier split.

### 4. Cancellations
How many, and the money that walked away. Straight from
`Booking.Status.CANCELLED`.

### 5. Average length of stay
Plus a small breakdown: 1–2 nights, 3–6, a week or more. One line of data,
says a lot about who is coming.

---

## Good, slightly more work

### 6. How far ahead people book
`created_at` (on every record, from `TimeStampedModel`) against `check_in`
gives the gap for free. Useful for deciding when to move prices.

### 7. Empty gaps worth filling
One- and two-night holes between two bookings. Genuinely actionable — staff
can go chase them.

### 8. Busiest days of the week
For arrivals and departures. Helps plan cleaning and driver shifts.

### 9. Repeat guests
How many guests have stayed before.

### 10. A compliance line
A small "X things need attention" strip pulling from the compliance app, so
the owner sees it without opening another screen. The reporting view already
imports `_documents_needing_attention` and `_upcoming_police_reports`.

---

## Two cautions

- **Year-on-year comparison** and **deeper booking insights** (source market
  map, price trends over time) are parked in the feature doc. The first needs
  a full year of history no new client has; the second is phase two. Worth
  noting that where bookings come from and guest nationality are *already*
  built on this page — so part of that parked item quietly happened. Decide
  whether the rest gets unparked before building more of it.

- **Comparing your price to other villas** is marked do-not-build in the
  feature doc. That data isn't ours to get — it needs a paid subscription or
  scraping, which is fragile and against most booking sites' terms.
