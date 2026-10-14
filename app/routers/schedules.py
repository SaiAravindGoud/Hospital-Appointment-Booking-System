
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user, require_roles
from app.database import get_db
from app.models import Doctor, DoctorLeave, DoctorSchedule, User
from app.schemas.schedule import (
    DoctorLeaveCreate,
    DoctorLeaveResponse,
    ScheduleCreate,
    ScheduleResponse,
)

router = APIRouter(tags=["Doctor Schedules and Leave"])


def get_doctor_or_404(db: Session, doctor_id: int) -> Doctor:
    doctor = db.query(Doctor).filter(
        Doctor.id == doctor_id,
        Doctor.is_active.is_(True),
    ).first()

    if doctor is None:
        raise HTTPException(status_code=404, detail="Active doctor not found")

    return doctor


@router.post(
    "/doctors/{doctor_id}/schedules",
    response_model=ScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_schedule(
    doctor_id: int,
    data: ScheduleCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    get_doctor_or_404(db, doctor_id)

    schedule = DoctorSchedule(
        doctor_id=doctor_id,
        **data.model_dump(),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@router.get(
    "/doctors/{doctor_id}/schedules",
    response_model=list[ScheduleResponse],
)
def list_schedules(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    get_doctor_or_404(db, doctor_id)

    return (
        db.query(DoctorSchedule)
        .filter(DoctorSchedule.doctor_id == doctor_id)
        .order_by(DoctorSchedule.day_of_week, DoctorSchedule.start_time)
        .all()
    )


@router.delete("/schedules/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    schedule = db.query(DoctorSchedule).filter(
        DoctorSchedule.id == schedule_id
    ).first()

    if schedule is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    db.delete(schedule)
    db.commit()
    return {"message": "Schedule deleted successfully"}


@router.post(
    "/doctors/{doctor_id}/leaves",
    response_model=DoctorLeaveResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_doctor_leave(
    doctor_id: int,
    data: DoctorLeaveCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    get_doctor_or_404(db, doctor_id)

    leave = DoctorLeave(
        doctor_id=doctor_id,
        **data.model_dump(),
    )
    db.add(leave)
    db.commit()
    db.refresh(leave)
    return leave


@router.get(
    "/doctors/{doctor_id}/leaves",
    response_model=list[DoctorLeaveResponse],
)
def list_doctor_leaves(
    doctor_id: int,
    db: Session = Depends(get_db),
):
    get_doctor_or_404(db, doctor_id)

    return (
        db.query(DoctorLeave)
        .filter(DoctorLeave.doctor_id == doctor_id)
        .order_by(DoctorLeave.start_date)
        .all()
    )


@router.delete("/leaves/{leave_id}")
def delete_doctor_leave(
    leave_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    leave = db.query(DoctorLeave).filter(
        DoctorLeave.id == leave_id
    ).first()

    if leave is None:
        raise HTTPException(status_code=404, detail="Doctor leave not found")

    db.delete(leave)
    db.commit()
    return {"message": "Doctor leave deleted successfully"}
