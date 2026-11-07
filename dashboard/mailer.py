"""Email outbox. The site never sends mail in the middle of a page: it adds a row to wsb.email_outbox,
then send_waiting() delivers what is waiting, if SMTP is set up.

Set these to switch real sending on (see docs/reservations.md):
    SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, MAIL_FROM
Without SMTP_HOST every email just waits in the outbox, where approvers can read it on the reservation page.
"""
import os
import smtplib
from email.message import EmailMessage


def queue(run, to_email, subject, body, reservation_id=None):
    """Add one email to the outbox. `run` is app.run (commits)."""
    if not to_email:
        return
    run("""INSERT INTO wsb.email_outbox (to_email, subject, body, reservation_id)
           VALUES (%s, %s, %s, %s)""", (to_email[:150], subject[:200], body, reservation_id))


def configured():
    return bool(os.environ.get('SMTP_HOST'))


def send_waiting(q, run, limit=20):
    """Send emails that are waiting. Returns how many were sent. Does nothing without SMTP_HOST."""
    if not configured():
        return 0
    rows = q("""SELECT email_id, to_email, subject, body FROM wsb.email_outbox
                WHERE sent_at IS NULL ORDER BY email_id LIMIT %s""", (limit,))
    if not rows:
        return 0
    sent = 0
    port = int(os.environ.get('SMTP_PORT', 587))
    with smtplib.SMTP(os.environ['SMTP_HOST'], port, timeout=15) as s:
        if port != 25:
            s.starttls()
        if os.environ.get('SMTP_USER'):
            s.login(os.environ['SMTP_USER'], os.environ.get('SMTP_PASSWORD', ''))
        for r in rows:
            msg = EmailMessage()
            msg['From'] = os.environ.get('MAIL_FROM') or os.environ.get('SMTP_USER', '')
            msg['To'] = r['to_email']
            msg['Subject'] = r['subject']
            msg.set_content(r['body'])
            try:
                s.send_message(msg)
            except smtplib.SMTPException as e:
                run('UPDATE wsb.email_outbox SET error = %s WHERE email_id = %s', (str(e)[:500], r['email_id']))
                continue
            run('UPDATE wsb.email_outbox SET sent_at = now(), error = NULL WHERE email_id = %s', (r['email_id'],))
            sent += 1
    return sent
