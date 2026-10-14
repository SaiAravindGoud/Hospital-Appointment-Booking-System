from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.jobs import scheduler as reminder_module


def test_upcoming_reminder_sends_email_and_marks_sent():
    now = datetime.now()
    appointment_time = now + timedelta(hours=2)

    appointment = SimpleNamespace(
        id=999,
        appointment_number="APT-REMINDER-TEST",
        appointment_date=appointment_time.date(),
        slot_time=appointment_time.time().replace(microsecond=0),
        token_number=1,
        status="Booked",
        reminder_sent=False,
        patient=SimpleNamespace(
            user=SimpleNamespace(email="test@example.com")
        ),
        doctor=SimpleNamespace(
            user=SimpleNamespace(name="Test Doctor")
        ),
    )

    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    query.all.return_value = [appointment]

    db = MagicMock()
    db.query.return_value = query

    with (
        patch.object(reminder_module, "SessionLocal", return_value=db),
        patch.object(reminder_module, "send_email", return_value=True) as send,
        patch.object(reminder_module, "datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = now
        mock_datetime.combine = datetime.combine

        reminder_module.send_upcoming_reminders()

    send.assert_called_once()
    assert appointment.reminder_sent is True
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_upcoming_reminder_does_not_mark_sent_when_email_fails():
    now = datetime.now()
    appointment_time = now + timedelta(hours=2)

    appointment = SimpleNamespace(
        id=998,
        appointment_number="APT-REMINDER-FAIL-TEST",
        appointment_date=appointment_time.date(),
        slot_time=appointment_time.time().replace(microsecond=0),
        token_number=1,
        status="Booked",
        reminder_sent=False,
        patient=SimpleNamespace(
            user=SimpleNamespace(email="test@example.com")
        ),
        doctor=SimpleNamespace(
            user=SimpleNamespace(name="Test Doctor")
        ),
    )

    query = MagicMock()
    query.options.return_value = query
    query.filter.return_value = query
    query.all.return_value = [appointment]

    db = MagicMock()
    db.query.return_value = query

    with (
        patch.object(reminder_module, "SessionLocal", return_value=db),
        patch.object(reminder_module, "send_email", return_value=False),
        patch.object(reminder_module, "datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = now
        mock_datetime.combine = datetime.combine

        reminder_module.send_upcoming_reminders()

    assert appointment.reminder_sent is False
    db.commit.assert_not_called()
    db.close.assert_called_once()
