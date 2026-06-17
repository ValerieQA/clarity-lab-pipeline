"""Tests for notifications/email_reporter.py"""

import os
from unittest import mock

import pytest

from notifications.email_reporter import send_email, send_daily_report, send_critical_alert, send_token_alert


VALID_ENV = {
    "GMAIL_SENDER": "sender@gmail.com",
    "GMAIL_APP_PASSWORD": "app_password",
    "REPORT_EMAIL_TO": "recipient@gmail.com",
}


class TestSendEmail:
    def test_missing_env_returns_false(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            result = send_email("Test subject", "Test body")
        assert result is False

    def test_smtp_success(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            with mock.patch("smtplib.SMTP") as mock_smtp:
                instance = mock_smtp.return_value.__enter__.return_value
                result = send_email("Test", "Body")
        assert result is True
        instance.sendmail.assert_called_once()

    def test_smtp_failure_returns_false(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            with mock.patch("smtplib.SMTP") as mock_smtp:
                mock_smtp.return_value.__enter__.side_effect = ConnectionRefusedError("refused")
                result = send_email("Test", "Body")
        assert result is False

    def test_send_daily_report_subject_contains_date(self):
        from datetime import date
        with mock.patch.dict(os.environ, VALID_ENV):
            with mock.patch("smtplib.SMTP") as mock_smtp:
                instance = mock_smtp.return_value.__enter__.return_value
                send_daily_report("body text", report_date=date(2026, 6, 16))
        args = instance.sendmail.call_args
        assert args is not None
        message_str = args[0][2]
        assert "2026-06-16" in message_str

    def test_send_critical_alert_uses_correct_subject(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            with mock.patch("smtplib.SMTP") as mock_smtp:
                instance = mock_smtp.return_value.__enter__.return_value
                send_critical_alert("Something broke")
        args = instance.sendmail.call_args
        # Subject may be encoded as quoted-printable; check raw string contains key phrase
        message_str = args[0][2]
        assert "Action_Required" in message_str or "Action Required" in message_str

    def test_send_token_alert_uses_correct_subject(self):
        with mock.patch.dict(os.environ, VALID_ENV):
            with mock.patch("smtplib.SMTP") as mock_smtp:
                instance = mock_smtp.return_value.__enter__.return_value
                send_token_alert("Token expired")
        args = instance.sendmail.call_args
        assert "Token" in args[0][2]
