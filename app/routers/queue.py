from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query, WebSocket
from fastapi import HTTPException
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.security import decode_token, get_token_user_id
from app.database import get_db
from app.models import Appointment, AppointmentHistory, Doctor, Patient, User
from app.websockets.manager import manager


router = APIRouter(tags=["Live Queue"])


def authenticate_websocket_user(token: str | None, db: Session) -> User | None:
    if not token:
        return None

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            return None

        user_id = get_token_user_id(payload)
    except (JWTError, TypeError, ValueError):
        return None

    user = db.query(User).filter(User.id == user_id).first()

    if user is None or not user.is_active:
        return None

    return user


def build_queue_snapshot(db: Session, doctor_id: int) -> dict[str, Any]:
    appointments = (
        db.query(Appointment, Patient, User)
        .join(Patient, Appointment.patient_id == Patient.id)
        .join(User, Patient.user_id == User.id)
        .filter(
            Appointment.doctor_id == doctor_id,
            Appointment.appointment_date == date.today(),
            Appointment.status.in_(
                ["Booked", "Confirmed", "Checked-In", "In Consultation"]
            ),
        )
        .order_by(Appointment.token_number, Appointment.slot_time)
        .all()
    )

    queue = [
        {
            "appointment_id": appointment.id,
            "appointment_number": appointment.appointment_number,
            "token_number": appointment.token_number,
            "patient_name": patient_user.name,
            "slot_time": appointment.slot_time.isoformat(),
            "status": appointment.status,
        }
        for appointment, patient, patient_user in appointments
    ]

    return {
        "type": "queue_snapshot",
        "doctor_id": doctor_id,
        "date": date.today().isoformat(),
        "queue": queue,
    }


async def broadcast_queue_update(db: Session, doctor_id: int) -> None:
    await manager.broadcast_queue(
        doctor_id,
        build_queue_snapshot(db, doctor_id),
    )


@router.websocket("/ws/queue/{doctor_id}")
async def doctor_queue_websocket(
    websocket: WebSocket,
    doctor_id: int,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = authenticate_websocket_user(token, db)

    if user is None:
        await websocket.close(code=4401, reason="Authentication required")
        return

    if user.role == "Doctor":
        doctor = (
            db.query(Doctor)
            .filter(Doctor.user_id == user.id, Doctor.is_active.is_(True))
            .first()
        )

        if doctor is None or doctor.id != doctor_id:
            await websocket.close(code=4403, reason="Access denied")
            return

    elif user.role != "Admin":
        await websocket.close(code=4403, reason="Access denied")
        return

    await manager.connect_queue(doctor_id, websocket)

    try:
        await websocket.send_json(build_queue_snapshot(db, doctor_id))

        while True:
            await websocket.receive_text()

    except Exception:
        pass

    finally:
        manager.disconnect_queue(doctor_id, websocket)


@router.websocket("/ws/notifications")
async def notifications_websocket(
    websocket: WebSocket,
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    user = authenticate_websocket_user(token, db)

    if user is None:
        await websocket.close(code=4401, reason="Authentication required")
        return

    await manager.connect_notifications(user.id, websocket)

    try:
        await websocket.send_json(
            {
                "type": "connection_established",
                "user_id": user.id,
                "message": "Connected to real-time notifications",
            }
        )

        while True:
            await websocket.receive_text()

    except Exception:
        pass

    finally:
        manager.disconnect_notifications(user.id, websocket)


@router.put("/doctors/me/call-next")
async def call_next_patient(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Only doctors can call the next patient",
        )

    doctor = (
        db.query(Doctor)
        .filter(
            Doctor.user_id == current_user.id,
            Doctor.is_active.is_(True),
        )
        .first()
    )

    if doctor is None:
        raise HTTPException(status_code=404, detail="Active doctor profile not found")

    appointment = (
        db.query(Appointment)
        .filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == date.today(),
            Appointment.status == "Checked-In",
        )
        .order_by(Appointment.token_number, Appointment.slot_time)
        .with_for_update()
        .first()
    )

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="No checked-in patients are waiting in today's queue",
        )

    old_status = appointment.status

    try:
        appointment.status = "In Consultation"

        db.add(
            AppointmentHistory(
                appointment_id=appointment.id,
                old_status=old_status,
                new_status="In Consultation",
                changed_by=current_user.id,
            )
        )

        db.commit()
        db.refresh(appointment)

    except Exception:
        db.rollback()
        raise

    patient = (
        db.query(Patient)
        .filter(Patient.id == appointment.patient_id)
        .first()
    )

    result = {
        "message": "Next patient called successfully",
        "appointment_id": appointment.id,
        "appointment_number": appointment.appointment_number,
        "token_number": appointment.token_number,
        "status": appointment.status,
    }

    await broadcast_queue_update(db, doctor.id)

    if patient is not None:
        await manager.notify_user(
            patient.user_id,
            {
                "type": "patient_called",
                **result,
                "doctor_id": doctor.id,
            },
        )

    return result
