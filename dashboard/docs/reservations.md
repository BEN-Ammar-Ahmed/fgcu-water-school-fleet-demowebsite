# Vehicle reservations

How someone asks for a vehicle, how it gets approved, and how the emails work.

There are **two websites** on the same database:

- **The vehicle request site** (`reserve_app.py`, http://localhost:5001): for anyone with the link. No account
  needed. Shows only vehicle names, types and locations.
- **The fleet site** (`app.py`, http://localhost:5000): the approvers' **Reservations** inbox, behind sign-in.

## The flow

```
 Requester (request site)              Database                       Approver (fleet site)
 ────────────────────────              ────────                       ─────────────────────
 1. Picks pick-up and return times
    and sees which vehicles are free
 2. Picks one ("Request this one")
    or "Any boat is fine"
 3. Fills in their details         ──► Saved as Pending
 4. Sees a thank-you page:             Email to requester: "Thank you,
    "pending review"                   pending review" + what they sent
                                       Email to every approver ──────► Sees it in Reservations
                                                                       (number badge in the top bar)
                                                                       The vehicle they picked is
                                                                       pre-selected; can give another
                                                                   ──► Approve / Deny (reason) /
                                                                       Ask for information (what) /
                                                                       Cancel
 Gets an email with the answer  ◄────  Status, history line,
 and everything they sent              Activity log line
 "Needs info": replies to the
 email with the answer         ─────────────────────────────────────► Approver uses "Edit details"
                                                                       with the answer, then approves
```

There is no link back to the request for the requester: after the thank-you page everything happens by email.
To change or cancel, they reply to the email; an approver makes the change on the fleet site.

**Who can do what**

| | Who |
|---|---|
| Request a vehicle | Anyone with the request site's link. It's a separate site, so the fleet site doesn't link to it except from the Reservations inbox ("Open the request site"). |
| Change or cancel a request | The requester asks by replying to an email; an approver makes the change |
| See all requests, approve, deny, ask for info, edit details, cancel | Tier 1, and anyone a top admin gives the "Approve reservations" switch (Admin -> People) |

**What the form asks:** name, email, UIN, phone, pick-up and return date and time, the vehicle (from the ones free
then, or any), vehicle type, destination, purpose, passengers, other drivers (one per line: `name, email`), and notes.

**Which vehicles are "free":** active, not Retired, Out of Service or In Maintenance, and not already approved for any
part of that time. Pending requests don't block a vehicle; the approver decides.

**Double booking:** the approver's list greys out vehicles already approved for an overlapping time, and the site
refuses them if someone tries anyway.

**Spam protection:** a hidden field robots fill in, at most 10 new requests an hour from one address, and at most
5 a day for one email address.

**Records kept:** every request keeps a history (who did what, when, and the message they wrote) and a copy of
every email. Decisions also go in Admin -> Activity under "Reservations".

## Pages

| Site | Page | Address |
|---|---|---|
| Request site | Choose times, see free vehicles | `/` |
| Request site | Your details | `/request` |
| Request site | Thank you (pending review) | `/thanks` |
| Fleet site | Inbox (approvers) | `/reservations` (tabs: Pending, Needs info, Approved, Denied, Cancelled, All) |
| Fleet site | One request (approve, deny, ask, cancel) | `/reservations/<number>` |
| Fleet site | Edit a request's details | `/reservations/<number>/edit` |

Code: `reserve_app.py` + `reserve_templates/`, `reservations.py`, `reservation_core.py` (shared), `mailer.py`.
Tables: `sql_postgres/13_reservations.sql`, `15_public_reservations.sql`.

**Putting it online:** the request site runs on its own address (for example `reserve.<your-domain>`). Set
`RESERVE_URL` and `FLEET_URL` in `.env` to the two real addresses so the links in emails point to the right place, and
give the request site its own `RESERVE_SECRET_KEY`. `FLEET_CONTACT_EMAIL` (optional) shows a "Questions?" address in the
request site's footer, and `MAIL_REPLY_TO` (optional) is where replies to the emails go, for example the fleet's shared
mailbox.

## Emails

### How it works now

The site never sends email in the middle of a page. Every email is first saved in the table
`wsb.email_outbox` (to, subject, body, which request, when). Then:

- **Without email set up** (today): emails wait in the outbox. Approvers can read every one at the bottom of the
  request page ("waiting to send"), and the requester can read the ones sent to them. Nothing is lost.
- **With email set up**: right after saving, the site sends what is waiting and marks each one `sent_at`. If
  sending fails (wrong password, server down), the email stays waiting with the error saved, and goes out on the
  next try.

| When | Who gets it | Subject |
|---|---|---|
| Request sent | Requester | We got your vehicle request (#N) |
| Request sent | Every approver | New vehicle request from NAME (#N) |
| Request updated after "Needs info" | Every approver | Vehicle request #N was updated |
| Approved | Requester | Your vehicle request is approved (#N), with vehicle and message |
| Denied | Requester | Your vehicle request was denied (#N), with the reason |
| Needs info | Requester | We need more information for your vehicle request (#N), with a link to update it |
| Approved request cancelled | Every approver | Vehicle request #N was cancelled |

Every email repeats everything the requester entered, so the requester can check it and the approver can decide from
the email alone.

### Switching real email on

Set these on the computer or server that runs the site (in `dashboard/.env`, never in git):

```
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=fleet-noreply@fgcu.edu
SMTP_PASSWORD=...
MAIL_FROM=fleet-noreply@fgcu.edu
```

Restart the site. Emails waiting in the outbox go out with the next request or decision.

### Options to choose from (decision for FGCU IT / the sponsor)

| Option | How | Good | Watch out |
|---|---|---|---|
| **1. FGCU Outlook mailbox (SMTP)** | IT creates a shared mailbox such as `fleet-noreply@fgcu.edu` and allows SMTP sign-in; put it in the settings above | Emails come from an FGCU address; no code changes | IT must allow SMTP for that mailbox (Microsoft often turns it off by default) |
| **2. Power Automate** | A flow reads new rows from `wsb.email_outbox` every few minutes, sends them from Outlook, and fills in `sent_at` | No passwords on the web server; FGCU staff can change the wording in Power Automate | Needs a Power Automate licence and a database connection (a PostgreSQL connector or an on-premises gateway) |
| **3. Email service (SendGrid, Resend, Amazon SES)** | Same settings as option 1, using the service's SMTP address and key | Quick to set up, reliable, shows what was delivered | Sender address must be verified; may need FGCU's OK to send "from" an fgcu.edu address |
| **4. Supabase** | A scheduled Supabase Edge Function sends what is waiting in the outbox | Runs next to the database | Another piece to maintain; still needs one of the senders above |

Our suggestion: **option 1** if IT allows it, otherwise **option 2**. Either way the site doesn't change: it keeps
writing to the outbox, and whatever sends the emails just needs to read `sent_at IS NULL` rows and fill in `sent_at`.

## Ideas for later

- **Reminders:** a daily job that emails the requester the day before pick-up, and the approver when a return is
  overdue.
- **Link to check-in/checkout:** when an approved reservation's vehicle is picked up, start the trip from the
  reservation (driver, destination and purpose already filled in), so Tier 2 only adds mileage and fuel.
- **Calendar:** a week view of approved reservations per vehicle.
- **Reply by email:** let the requester answer a "Needs info" email directly (needs an inbox the site can read; the
  update link does the same job today).

## Questions for the sponsor

Collected with the other open questions in [`questions-for-regina.md`](questions-for-regina.md).
