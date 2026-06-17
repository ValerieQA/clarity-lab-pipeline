"""
Email reporting for Clarity Lab Pipeline.

Sends operational alerts and strategy reports via Gmail SMTP.
All sends are best-effort: failures are logged but never block the publishing pipeline.

Required environment variables:
    GMAIL_SENDER         — sending address (e.g. kovalchuk25@gmail.com)
    GMAIL_APP_PASSWORD   — Gmail app-specific password
    REPORT_EMAIL_TO      — recipient address

Optional:
    SMTP_HOST            — defaults to smtp.gmail.com
    SMTP_PORT            — defaults to 587
"""

from __future__ import annotations

import logging
import os
import smtplib
import traceback
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

logger = logging.getLogger("email_reporter")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))

SUBJECT_DAILY   = "Clarity Lab Daily Report — {date}"
SUBJECT_WEEKLY  = "Clarity Lab Weekly Strategy Report — Week of {date}"
SUBJECT_ALERT   = "Clarity Lab Alert — Action Required"
SUBJECT_CYCLE   = "Clarity Lab Strategy Cycle Complete"
SUBJECT_NEW_STRATEGY = "Clarity Lab New Strategy Ready for Review"
SUBJECT_TOKEN   = "Clarity Lab Alert — Token / Permission Issue"


def _credentials() -> tuple[str, str, str]:
    """Return (sender, password, recipient). Raises if any are missing."""
    sender = os.environ.get("GMAIL_SENDER", "")
    password = os.environ.get("GMAIL_APP_PASSWORD", "")
    recipient = os.environ.get("REPORT_EMAIL_TO", "")
    missing = [k for k, v in [
        ("GMAIL_SENDER", sender),
        ("GMAIL_APP_PASSWORD", password),
        ("REPORT_EMAIL_TO", recipient),
    ] if not v]
    if missing:
        raise EnvironmentError(
            f"Email reporter: missing environment variables: {', '.join(missing)}"
        )
    return sender, password, recipient


def send_email(subject: str, body_text: str, body_html: Optional[str] = None) -> bool:
    """
    Send an email. Returns True on success, False on failure.
    Never raises — all errors are logged.
    """
    try:
        sender, password, recipient = _credentials()
    except EnvironmentError as exc:
        logger.error("Cannot send email: %s", exc)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient

    msg.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        msg.attach(MIMEText(body_html, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info("Email sent: %s → %s", subject, recipient)
        return True
    except Exception:
        logger.error("Failed to send email '%s':\n%s", subject, traceback.format_exc())
        return False


# ---------------------------------------------------------------------------
# Typed send helpers
# ---------------------------------------------------------------------------

def send_daily_report(body_text: str, body_html: Optional[str] = None, report_date: Optional[date] = None) -> bool:
    d = (report_date or date.today()).isoformat()
    return send_email(SUBJECT_DAILY.format(date=d), body_text, body_html)


def send_weekly_report(body_text: str, body_html: Optional[str] = None, week_of: Optional[date] = None) -> bool:
    d = (week_of or date.today()).isoformat()
    return send_email(SUBJECT_WEEKLY.format(date=d), body_text, body_html)


def send_critical_alert(body_text: str, body_html: Optional[str] = None) -> bool:
    return send_email(SUBJECT_ALERT, body_text, body_html)


def send_token_alert(body_text: str, body_html: Optional[str] = None) -> bool:
    return send_email(SUBJECT_TOKEN, body_text, body_html)


def send_cycle_complete(body_text: str, body_html: Optional[str] = None) -> bool:
    return send_email(SUBJECT_CYCLE, body_text, body_html)


def send_new_strategy(body_text: str, body_html: Optional[str] = None) -> bool:
    return send_email(SUBJECT_NEW_STRATEGY, body_text, body_html)
