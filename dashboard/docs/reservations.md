# Vehicle reservations

How someone asks for a vehicle, how it gets approved, and how the emails work.

## The flow

```
 Requester                         Site                                Approver
 ─────────                         ────                                ────────
 Fills in "Request a vehicle"  ──► Saves it as Pending
                                   Email to requester: "We got it"
                                   Email to every approver: "New request" ──► Sees it in Reservations
                                                                             (number badge in the top bar)
                                                                         ──► Approve (picks a vehicle)
                                                                             Deny (must give a reason)
                                                                             Ask for information (must say what)
 Gets an email with the answer ◄── Status changes, history line added,
 and all the details they sent     Activity log line written
 
 If "Needs info": opens the link
 in the email, updates the form ──► Back to Pending, approvers emailed again
```

**Who can do what**

| | Who |
|---|---|
| Request a vehicle | Anyone signed in (all three tiers) |
| See their own requests | The person who sent them (Reservations → My requests) |
| See all requests, approve, deny, ask for info | Tier 1, and anyone a top admin gives the "Approve reservations" switch (Admin → People) |
| Update or cancel a request | Only the person who sent it, while it's Pending or Needs info. An approved request can still be cancelled until its return time; approvers get an email so they know the vehicle is free. |

**What the form asks:** name, email, UIN, phone, pick-up and return date and time, destination,
purpose, vehicle type (or any), passengers, other drivers (one per line: `name, email`), and notes.

**Double booking:** when approving, the approver picks the vehicle. The requested type is listed first. A vehicle
already approved for an overlapping time is greyed out, and the site refuses it if someone tries anyway. Retired
and Out of Service vehicles are not offered.

**Records kept:** every request keeps a history (who did what, when, and the message they wrote) and a copy of
every email. Decisions also go in Admin → Activity under "Reservations".

## Pages

| Page | Address |
|---|---|
| Request form | `/reserve` |
| My requests | `/reservations/mine` |
| Inbox (approvers) | `/reservations` (tabs: Pending, Needs info, Approved, Denied, Cancelled, All) |
| One request | `/reservations/<number>` |

Code: `dashboard/reservations.py`, `dashboard/mailer.py`, templates `reservations.html`, `reservation.html`.
Tables: `sql_postgres/13_reservations.sql`.

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
- **Requests without an account:** a public form for students who don't have a fleet account. This needs spam
  protection and FGCU sign-in first; today the form needs sign-in.
- **Calendar:** a week view of approved reservations per vehicle.
- **Reply by email:** let the requester answer a "Needs info" email directly (needs an inbox the site can read; the
  update link does the same job today).

## Questions for the sponsor

1. Who should get the "new request" email: both top admins, or one shared mailbox?
2. Should students without a fleet account be able to request (a public form), or only people with an account?
3. How far ahead must a request be sent (for example, at least 2 days before pick-up)?
4. Should approved requests need a valid driver's license on file for every driver before approval?
5. Which email address should the emails come from?
