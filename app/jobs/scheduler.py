
import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.models import (
    Appointment,
    Consultation,
    Doctor,
    Patient,
)
from app.services.email_service import send_email

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _patient_email(appointment):
    patient = appointment.patient
    return patient.user.email if patient and patient.user else None


def _appointment_details(appointment):
    doctor_name = (
        appointment.doctor.user.name
        if appointment.doctor and appointment.doctor.user
        else "Your doctor"
    )
    return (
        f"Appointment number: {appointment.appointment_number}\n"
        f"Doctor: {doctor_name}\n"
        f"Date: {appointment.appointment_date}\n"
        f"Time: {appointment.slot_time}\n"
        f"Token number: {appointment.token_number}\n"
        f"Status: {appointment.status}\n"
    )


def send_upcoming_reminders():
    """Email patients with appointments in the next 24 hours once."""
    db = SessionLocal()
    try:
        now = datetime.now()
        end = now + timedelta(hours=24)

        appointments = (
            db.query(Appointment)
            .options(
                joinedload(Appointment.patient).joinedload(Patient.user),
                joinedload(Appointment.doctor).joinedload(Doctor.user),
            )
            .filter(
                Appointment.appointment_date >= now.date(),
                Appointment.appointment_date <= end.date(),
                Appointment.status.in_(["Booked", "Confirmed"]),
                Appointment.reminder_sent.is_(False),
            )
            .all()
        )

        for appointment in appointments:
            slot = datetime.combine(
                appointment.appointment_date,
                appointment.slot_time,
            )

            if not (now < slot <= end):
                continue

            email = _patient_email(appointment)
            if not email:
                logger.warning(
                    "Reminder skipped: no email for appointment %s",
                    appointment.id,
                )
                continue

            sent = send_email(
                email,
                f"Appointment reminder: {appointment.appointment_number}",
                "This is a reminder for your upcoming appointment.\n\n"
                + _appointment_details(appointment),
            )

            if sent:
                appointment.reminder_sent = True
                db.commit()

    except Exception:
        db.rollback()
        logger.exception("Upcoming appointment reminder job failed")
    finally:
        db.close()


def mark_no_shows():
    """Mark Booked appointments as No-Show 30 minutes after their slot."""
    db = SessionLocal()
    try:
        now = datetime.now()

        appointments = (
            db.query(Appointment)
            .filter(
                Appointment.status == "Booked",
                Appointment.appointment_date <= now.date(),
            )
            .all()
        )

        for appointment in appointments:
            slot = datetime.combine(
                appointment.appointment_date,
                appointment.slot_time,
            )

            if now >= slot + timedelta(minutes=30):
                appointment.status = "No-Show"
                appointment.active_slot_key = None
                appointment.active_patient_time_key = None
                appointment.active_patient_doctor_day_key = None

                logger.info(
                    "Appointment %s marked No-Show",
                    appointment.appointment_number,
                )

        db.commit()

    except Exception:
        db.rollback()
        logger.exception("No-show job failed")
    finally:
        db.close()


def send_follow_up_reminders():
    """Email patients whose consultation follow-up date is tomorrow."""
    db = SessionLocal()
    try:
        tomorrow = date.today() + timedelta(days=1)

        consultations = (
            db.query(Consultation)
            .options(
                joinedload(Consultation.appointment)
                .joinedload(Appointment.patient)
                .joinedload(Patient.user),
                joinedload(Consultation.appointment)
                .joinedload(Appointment.doctor)
                .joinedload(Doctor.user),
            )
            .filter(Consultation.follow_up_date == tomorrow)
            .all()
        )

        for consultation in consultations:
            appointment = consultation.appointment
            if not appointment:
                continue

            email = _patient_email(appointment)
            if not email:
                logger.warning(
                    "Follow-up reminder skipped: no email for appointment %s",
                    appointment.id,
                )
                continue

            doctor_name = (
                appointment.doctor.user.name
                if appointment.doctor and appointment.doctor.user
                else "your doctor"
            )

            sent = send_email(
                email,
                "Upcoming follow-up appointment",
                f"This is a reminder that your follow-up date is tomorrow, "
                f"{tomorrow}.\n"
                f"Doctor: {doctor_name}\n"
                f"Original appointment: {appointment.appointment_number}",
            )

            if sent:
                logger.info(
                    "Follow-up reminder sent for appointment %s",
                    appointment.appointment_number,
                )

    except Exception:
        logger.exception("Follow-up reminder job failed")
    finally:
        db.close()


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(
        send_upcoming_reminders,
        "interval",
        hours=1,
        id="appointment_reminders",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        mark_no_shows,
        "interval",
        minutes=15,
        id="appointment_no_shows",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.add_job(
        send_follow_up_reminders,
        "cron",
        hour=9,
        minute=0,
        id="follow_up_reminders",
        replace_existing=True,
        max_instances=1,
    )

    scheduler.start()
    logger.info("Appointment scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Appointment scheduler stopped")
