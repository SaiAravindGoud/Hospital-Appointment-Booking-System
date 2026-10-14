import os

from app.services.email_service import send_email


def test_reminder_email_delivery():
    recipient = os.getenv("REMINDER_TEST_EMAIL")

    assert recipient, (
        "Set REMINDER_TEST_EMAIL in your environment "
        "to the email address you can access."
    )

    sent = send_email(
        recipient,
        "Hospital Appointment System - Reminder Email Test",
        (
            "This is a test of the appointment reminder email service.\n"
            "No appointment or database records were changed."
        ),
    )

    assert sent, "Reminder test email failed. Check the Uvicorn/pytest logs."
