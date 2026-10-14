from datetime import date, datetime, timedelta
from uuid import uuid4
import logging
from datetime import date
from fastapi import Query

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.jobs.scheduler import send_upcoming_reminders
from app.models import (
    Appointment,
    AppointmentHistory,
    Doctor,
    DoctorLeave,
    DoctorSchedule,
    Patient,
    User,
)
from app.schemas.appointment import AppointmentCreate, AppointmentResponse
from app.services.email_service import send_email_safely

router = APIRouter(prefix="/appointments", tags=["Appointments"])

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = [
    "Booked",
    "Confirmed",
    "Checked-In",
    "In Consultation",
    "CheckedIn",
    "InProgress",
]


def get_patient_profile(db: Session, user: User):
    return db.query(Patient).filter(Patient.user_id == user.id).first()


def get_doctor_profile(db: Session, user: User):
    return db.query(Doctor).filter(Doctor.user_id == user.id).first()


def notify_appointment_patient(
    appointment: Appointment,
    subject: str,
    message: str,
) -> None:
    """Send an appointment notification without breaking the API."""
    try:
        patient_email = appointment.patient.user.email

        if patient_email:
            send_email_safely(patient_email, subject, message)

    except Exception:
        logger.exception(
            "Appointment notification failed for appointment ID %s",
            appointment.id,
        )


def appointments_visible_to_user(db: Session, user: User):
    query = db.query(Appointment)

    if user.role == "Admin":
        return query

    if user.role == "Patient":
        patient = get_patient_profile(db, user)

        if patient is None:
            raise HTTPException(
                status_code=404,
                detail="Patient profile not found",
            )

        return query.filter(Appointment.patient_id == patient.id)

    if user.role == "Doctor":
        doctor = get_doctor_profile(db, user)

        if doctor is None:
            raise HTTPException(
                status_code=404,
                detail="Doctor profile not found",
            )

        return query.filter(Appointment.doctor_id == doctor.id)

    raise HTTPException(
        status_code=403,
        detail="You do not have permission to view appointments",
    )


def _validate_reschedule_slot(
    db: Session,
    appointment: Appointment,
    data: AppointmentCreate,
):
    """Validate a new slot using the booking rules."""

    if data.appointment_date > date.today() + timedelta(days=30):
        raise HTTPException(
            status_code=400,
            detail="Appointments can only be booked up to 30 days in advance",
        )

    requested_start = datetime.combine(
        data.appointment_date,
        data.slot_time,
    )

    now = datetime.now(requested_start.tzinfo) if requested_start.tzinfo else datetime.now()
    if requested_start <= now:
        raise HTTPException(
            status_code=400,
            detail="Appointment slot must be in the future",
        )

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.id == data.doctor_id,
            Doctor.is_active.is_(True),
        )
        .with_for_update()
        .first()
    )

    if not doctor:
        raise HTTPException(
            status_code=404,
            detail="Active doctor not found",
        )

    duration = doctor.slot_duration_minutes
    requested_end = requested_start + timedelta(minutes=duration)
    day_name = data.appointment_date.strftime("%A")

    schedules = (
        db.query(DoctorSchedule)
        .filter(
            DoctorSchedule.doctor_id == doctor.id,
            DoctorSchedule.day_of_week == day_name,
        )
        .all()
    )

    valid_schedule = False

    for schedule in schedules:
        schedule_start = datetime.combine(
            data.appointment_date,
            schedule.start_time,
        )
        schedule_end = datetime.combine(
            data.appointment_date,
            schedule.end_time,
        )

        overlaps_break = (
            schedule.break_start is not None
            and schedule.break_end is not None
            and data.slot_time < schedule.break_end
            and requested_end.time() > schedule.break_start
        )

        aligned = (
            (requested_start - schedule_start).total_seconds()
            % (duration * 60)
            == 0
        )

        if (
            requested_start >= schedule_start
            and requested_end <= schedule_end
            and not overlaps_break
            and aligned
        ):
            valid_schedule = True
            break

    if not valid_schedule:
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested time is outside the doctor's schedule, "
                "overlaps a break, or is not a valid slot"
            ),
        )

    leave = (
        db.query(DoctorLeave)
        .filter(
            DoctorLeave.doctor_id == doctor.id,
            DoctorLeave.start_date <= data.appointment_date,
            DoctorLeave.end_date >= data.appointment_date,
        )
        .first()
    )

    if leave:
        raise HTTPException(
            status_code=400,
            detail="Doctor is on leave on the requested date",
        )

    existing = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == data.appointment_date,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.id != appointment.id,
        )
        .with_for_update()
        .all()
    )

    for other in existing:
        other_start = datetime.combine(
            other.appointment_date,
            other.slot_time,
        )
        other_end = other_start + timedelta(minutes=duration)

        if requested_start < other_end and requested_end > other_start:
            raise HTTPException(
                status_code=409,
                detail="This appointment slot is already booked",
            )

    patient_conflicts = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == appointment.patient_id,
            Appointment.appointment_date == data.appointment_date,
            Appointment.status.in_(ACTIVE_STATUSES),
            Appointment.id != appointment.id,
        )
        .with_for_update()
        .all()
    )

    for other in patient_conflicts:
        if other.slot_time == data.slot_time:
            raise HTTPException(
                status_code=409,
                detail="You already have an appointment at this time",
            )

        if other.doctor_id == doctor.id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "You already have an appointment with this doctor "
                    "on this date"
                ),
            )

    return doctor


def _record_appointment_status(
    db: Session,
    appointment: Appointment,
    old_status: str,
    new_status: str,
    user_id: int,
):
    appointment.status = new_status

    db.add(
        AppointmentHistory(
            appointment_id=appointment.id,
            old_status=old_status,
            new_status=new_status,
            changed_by=user_id,
        )
    )


def _recalculate_tokens(
    db: Session,
    doctor_id: int,
    appointment_date: date,
):
    rows = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == appointment_date,
        )
        .order_by(
            Appointment.slot_time,
            Appointment.id,
        )
        .all()
    )

    for token, row in enumerate(rows, start=1):
        row.token_number = token


@router.post(
    "",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def book_appointment(
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Only patients can book appointments",
        )

    patient = get_patient_profile(db, current_user)

    if patient is None:
        raise HTTPException(
            status_code=400,
            detail="Patient profile not found",
        )

    today = date.today()

    if data.appointment_date > today + timedelta(days=30):
        raise HTTPException(
            status_code=400,
            detail="Appointments can only be booked up to 30 days in advance",
        )

    requested_start = datetime.combine(
        data.appointment_date,
        data.slot_time,
    )

    now = datetime.now(requested_start.tzinfo) if requested_start.tzinfo else datetime.now()
    if requested_start <= now:
        raise HTTPException(
            status_code=400,
            detail="Appointment slot must be in the future",
        )

    try:
        doctor = (
            db.query(Doctor)
            .filter(
                Doctor.id == data.doctor_id,
                Doctor.is_active.is_(True),
            )
            .with_for_update()
            .first()
        )

        if doctor is None:
            raise HTTPException(
                status_code=404,
                detail="Active doctor not found",
            )

        duration = doctor.slot_duration_minutes
        requested_end = requested_start + timedelta(minutes=duration)
        day_name = data.appointment_date.strftime("%A")

        schedules = (
            db.query(DoctorSchedule)
            .filter(
                DoctorSchedule.doctor_id == doctor.id,
                DoctorSchedule.day_of_week == day_name,
            )
            .all()
        )

        valid_schedule = False

        for schedule in schedules:
            schedule_start = datetime.combine(
                data.appointment_date,
                schedule.start_time,
            )
            schedule_end = datetime.combine(
                data.appointment_date,
                schedule.end_time,
            )

            overlaps_break = (
                schedule.break_start is not None
                and schedule.break_end is not None
                and data.slot_time < schedule.break_end
                and requested_end.time() > schedule.break_start
            )

            aligned = (
                (requested_start - schedule_start).total_seconds()
                % (duration * 60)
                == 0
            )

            if (
                requested_start >= schedule_start
                and requested_end <= schedule_end
                and not overlaps_break
                and aligned
            ):
                valid_schedule = True
                break

        if not valid_schedule:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Requested time is outside the doctor's schedule, "
                    "overlaps a break, or is not a valid slot"
                ),
            )

        leave = (
            db.query(DoctorLeave)
            .filter(
                DoctorLeave.doctor_id == doctor.id,
                DoctorLeave.start_date <= data.appointment_date,
                DoctorLeave.end_date >= data.appointment_date,
            )
            .first()
        )

        if leave:
            raise HTTPException(
                status_code=400,
                detail="Doctor is on leave on the requested date",
            )

        existing = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .with_for_update()
            .all()
        )

        for other in existing:
            existing_start = datetime.combine(
                other.appointment_date,
                other.slot_time,
            )
            existing_end = existing_start + timedelta(minutes=duration)

            if (
                requested_start < existing_end
                and requested_end > existing_start
            ):
                raise HTTPException(
                    status_code=409,
                    detail="This appointment slot is already booked",
                )

        patient_conflicts = (
            db.query(Appointment)
            .filter(
                Appointment.patient_id == patient.id,
                Appointment.appointment_date == data.appointment_date,
                Appointment.status.in_(ACTIVE_STATUSES),
            )
            .with_for_update()
            .all()
        )

        for other in patient_conflicts:
            if other.slot_time == data.slot_time:
                raise HTTPException(
                    status_code=409,
                    detail="You already have an appointment at this time",
                )

            if other.doctor_id == doctor.id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "You already have an appointment with this doctor "
                        "on this date"
                    ),
                )

        appointment = Appointment(
            appointment_number=(
                f"APT-{data.appointment_date:%Y%m%d}-"
                f"{uuid4().hex[:8].upper()}"
            ),
            patient_id=patient.id,
            doctor_id=doctor.id,
            appointment_date=data.appointment_date,
            slot_time=data.slot_time,
            token_number=1,
            reason=data.reason,
            status="Booked",
            consultation_fee=doctor.consultation_fee,
            active_slot_key=(
                f"{doctor.id}:{data.appointment_date}:{data.slot_time}"
            ),
            active_patient_time_key=(
                f"{patient.id}:{data.appointment_date}:{data.slot_time}"
            ),
            active_patient_doctor_day_key=(
                f"{patient.id}:{doctor.id}:{data.appointment_date}"
            ),
        )

        db.add(appointment)
        db.flush()

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=None,
                new_status="Booked",
                changed_by=current_user.id,
            )
        )

        daily_appointments = (
            db.query(Appointment)
            .filter(
                Appointment.doctor_id == doctor.id,
                Appointment.appointment_date == data.appointment_date,
            )
            .order_by(
                Appointment.slot_time,
                Appointment.id,
            )
            .with_for_update()
            .all()
        )

        for token, daily_appointment in enumerate(
            daily_appointments,
            start=1,
        ):
            daily_appointment.token_number = token

        db.commit()
        db.refresh(appointment)

        # Send notification only after the booking has been committed.
        notify_appointment_patient(
            appointment,
            f"Appointment booked: {appointment.appointment_number}",
            (
                f"Hello {appointment.patient.user.name},\n\n"
                "Your appointment has been booked successfully.\n"
                f"Appointment number: {appointment.appointment_number}\n"
                f"Doctor: {appointment.doctor.user.name}\n"
                f"Date: {appointment.appointment_date}\n"
                f"Time: {appointment.slot_time}\n"
                f"Token number: {appointment.token_number}\n"
                f"Consultation fee: {appointment.consultation_fee}\n"
            ),
        )

        return appointment

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This booking conflicts with an existing appointment",
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        logger.exception("Appointment booking failed")
        raise


@router.get("/my", response_model=list[AppointmentResponse])
def list_my_appointments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Only patients can access this endpoint",
        )

    query = appointments_visible_to_user(db, current_user)

    return (
        query.order_by(
            Appointment.appointment_date,
            Appointment.slot_time,
        )
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("", response_model=list[AppointmentResponse])
def list_appointments(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    doctor_id: int | None = Query(default=None, gt=0),
    start_date: date | None = None,
    end_date: date | None = None,
    appointment_number: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = appointments_visible_to_user(db, current_user)

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="start_date cannot be later than end_date",
        )

    if status_filter:
        query = query.filter(Appointment.status == status_filter)

    if doctor_id is not None:
        query = query.filter(Appointment.doctor_id == doctor_id)

    if start_date is not None:
        query = query.filter(Appointment.appointment_date >= start_date)

    if end_date is not None:
        query = query.filter(Appointment.appointment_date <= end_date)

    if appointment_number:
        query = query.filter(
            Appointment.appointment_number.ilike(
                f"%{appointment_number.strip()}%"
            )
        )

    return (
        query.order_by(
            Appointment.appointment_date,
            Appointment.slot_time,
        )
        .offset(skip)
        .limit(limit)
        .all()
    )

@router.get("/{appointment_id}", response_model=AppointmentResponse)
def get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = appointments_visible_to_user(db, current_user)

    appointment = query.filter(
        Appointment.id == appointment_id
    ).first()

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    return appointment


@router.patch("/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    new_status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    allowed_statuses = {
        "Checked-In",
        "In Consultation",
        "Completed",
        "Cancelled",
        "No-Show",
    }

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Allowed values: {sorted(allowed_statuses)}",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    old_status = appointment.status

    transitions = {
        "Booked": {"Checked-In", "Cancelled", "No-Show"},
        "Confirmed": {"Checked-In", "Cancelled", "No-Show"},
        "Checked-In": {"In Consultation", "Cancelled"},
        "In Consultation": {"Completed"},
    }

    if new_status not in transitions.get(old_status, set()):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot change appointment status from "
                f"{old_status} to {new_status}"
            ),
        )

    if current_user.role == "Patient":
        patient = get_patient_profile(db, current_user)

        if (
            new_status != "Cancelled"
            or old_status not in {"Booked", "Confirmed"}
            or not patient
            or appointment.patient_id != patient.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Patients may only cancel their own booked appointments",
            )

    elif current_user.role == "Doctor":
        doctor = get_doctor_profile(db, current_user)

        if not doctor or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=403,
                detail="You can only update appointments assigned to you",
            )

    elif current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="You are not allowed to update appointment status",
        )

    try:
        appointment.status = new_status

        if new_status == "Cancelled":
            appointment.active_slot_key = None
            appointment.active_patient_time_key = None
            appointment.active_patient_doctor_day_key = None

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status,
                new_status=new_status,
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(appointment)

        return appointment

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{appointment_id}/reschedule",
    response_model=AppointmentResponse,
)
def reschedule_appointment(
    appointment_id: int,
    data: AppointmentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Only patients can reschedule appointments",
        )

    patient = get_patient_profile(db, current_user)

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not found",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if appointment.patient_id != patient.id:
        raise HTTPException(
            status_code=403,
            detail="You can only reschedule your own appointments",
        )

    if appointment.status != "Booked":
        raise HTTPException(
            status_code=400,
            detail="Only Booked appointments can be rescheduled",
        )

    if appointment.reschedule_count >= 2:
        raise HTTPException(
            status_code=400,
            detail="Maximum of 2 reschedules reached; cancel and book again",
        )

    old_start = datetime.combine(
        appointment.appointment_date,
        appointment.slot_time,
    )

    if datetime.now() > old_start - timedelta(hours=2):
        raise HTTPException(
            status_code=400,
            detail="Appointments must be rescheduled at least 2 hours before the slot",
        )

    old_doctor_id = appointment.doctor_id
    old_date = appointment.appointment_date

    try:
        doctor = _validate_reschedule_slot(db, appointment, data)

        appointment.active_slot_key = None
        appointment.active_patient_time_key = None
        appointment.active_patient_doctor_day_key = None

        db.flush()

        appointment.doctor_id = doctor.id
        appointment.appointment_date = data.appointment_date
        appointment.slot_time = data.slot_time
        appointment.reason = data.reason
        appointment.consultation_fee = doctor.consultation_fee
        appointment.reschedule_count += 1
        appointment.reminder_sent = False

        appointment.active_slot_key = (
            f"{doctor.id}:{data.appointment_date}:{data.slot_time}"
        )
        appointment.active_patient_time_key = (
            f"{patient.id}:{data.appointment_date}:{data.slot_time}"
        )
        appointment.active_patient_doctor_day_key = (
            f"{patient.id}:{doctor.id}:{data.appointment_date}"
        )

        _recalculate_tokens(db, old_doctor_id, old_date)
        _recalculate_tokens(db, doctor.id, data.appointment_date)

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status="Booked",
                new_status="Booked",
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(appointment)

        return appointment

    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The requested slot conflicts with another booking",
        )

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{appointment_id}/cancel",
    response_model=AppointmentResponse,
)
def cancel_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Only patients can cancel appointments",
        )

    patient = get_patient_profile(db, current_user)

    if not patient:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not found",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if appointment.patient_id != patient.id:
        raise HTTPException(
            status_code=403,
            detail="You can only cancel your own appointments",
        )

    if appointment.status != "Booked":
        raise HTTPException(
            status_code=400,
            detail="Only Booked appointments can be cancelled",
        )

    slot_start = datetime.combine(
        appointment.appointment_date,
        appointment.slot_time,
    )

    if datetime.now() > slot_start - timedelta(hours=2):
        raise HTTPException(
            status_code=400,
            detail="Appointments must be cancelled at least 2 hours before the slot",
        )

    try:
        old_status = appointment.status
        old_doctor_id = appointment.doctor_id
        old_date = appointment.appointment_date

        _record_appointment_status(
            db,
            appointment,
            old_status,
            "Cancelled",
            current_user.id,
        )

        appointment.active_slot_key = None
        appointment.active_patient_time_key = None
        appointment.active_patient_doctor_day_key = None

        db.flush()

        _recalculate_tokens(db, old_doctor_id, old_date)

        db.commit()
        db.refresh(appointment)

        return appointment

    except Exception:
        db.rollback()
        raise


@router.put(
    "/{appointment_id}/check-in",
    response_model=AppointmentResponse,
)
def check_in_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Only Admin can check in appointments",
        )

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .with_for_update()
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    if appointment.status != "Booked":
        raise HTTPException(
            status_code=400,
            detail="Only Booked appointments can be checked in",
        )

    now = datetime.now()
    slot_start = datetime.combine(
        appointment.appointment_date,
        appointment.slot_time,
    )

    if now.date() != appointment.appointment_date:
        raise HTTPException(
            status_code=400,
            detail="Check-in is only allowed on the appointment date",
        )

    if now < slot_start - timedelta(minutes=30):
        raise HTTPException(
            status_code=400,
            detail="Check-in opens 30 minutes before the appointment slot",
        )

    if now > slot_start + timedelta(minutes=30):
        raise HTTPException(
            status_code=400,
            detail="The check-in window has passed; the appointment may be marked No-Show",
        )

    try:
        _record_appointment_status(
            db,
            appointment,
            appointment.status,
            "Checked-In",
            current_user.id,
        )

        db.commit()
        db.refresh(appointment)

        return appointment

    except Exception:
        db.rollback()
        raise


@router.post("/test-reminder-email")
def test_reminder_email(
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Admin":
        raise HTTPException(
            status_code=403,
            detail="Only Admin can test reminder jobs",
        )

    send_upcoming_reminders()

    return {
        "message": (
            "Appointment reminder job executed. "
            "Check server logs and reminder_sent values."
        )
    }
