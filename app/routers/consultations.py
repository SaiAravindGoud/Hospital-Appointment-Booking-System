
import os
from datetime import date
from pathlib import Path
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.database import get_db
from app.models import (
    Appointment,
    AppointmentHistory,
    Consultation,
    Doctor,
    Patient,
    UploadedFile,
    User,
)

router = APIRouter(tags=["Consultations, Files & Patient History"])

BASE_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = BASE_DIR / "uploads" / "appointment_files"
MAX_FILE_SIZE = 5 * 1024 * 1024

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
FILE_TYPES = {"Lab Report", "Prescription", "Scan"}


def get_patient_profile(db: Session, user: User):
    return db.query(Patient).filter(Patient.user_id == user.id).first()


def get_doctor_profile(db: Session, user: User):
    return db.query(Doctor).filter(Doctor.user_id == user.id).first()


def get_appointment_or_404(db: Session, appointment_id: int):
    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == appointment_id)
        .first()
    )

    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found",
        )

    return appointment


def can_access_appointment(
    db: Session,
    user: User,
    appointment: Appointment,
):
    if user.role == "Admin":
        return True

    if user.role == "Patient":
        patient = get_patient_profile(db, user)
        return (
            patient is not None
            and appointment.patient_id == patient.id
        )

    if user.role == "Doctor":
        doctor = get_doctor_profile(db, user)
        return (
            doctor is not None
            and appointment.doctor_id == doctor.id
        )

    return False


def require_appointment_access(
    db: Session,
    user: User,
    appointment: Appointment,
):
    if not can_access_appointment(db, user, appointment):
        raise HTTPException(
            status_code=403,
            detail="You cannot access this appointment",
        )


def consultation_dict(consultation: Consultation):
    return {
        "id": consultation.id,
        "appointment_id": consultation.appointment_id,
        "symptoms": consultation.symptoms,
        "diagnosis": consultation.diagnosis,
        "prescription": consultation.prescription,
        "advice": consultation.advice,
        "follow_up_date": consultation.follow_up_date,
        "created_at": consultation.created_at,
    }


def file_dict(uploaded: UploadedFile):
    return {
        "id": uploaded.id,
        "appointment_id": uploaded.appointment_id,
        "uploaded_by": uploaded.uploaded_by,
        "file_type": uploaded.file_type,
        "original_name": uploaded.original_name,
        "stored_name": uploaded.stored_name,
        "size_kb": uploaded.size_kb,
        "created_at": uploaded.created_at,
    }


# --------------------------------------------------
# CREATE CONSULTATION
# POST /appointments/{appointment_id}/consultation
# --------------------------------------------------

@router.post(
    "/appointments/{appointment_id}/consultation",
    status_code=status.HTTP_201_CREATED,
)
def create_consultation(
    appointment_id: int,
    symptoms: str = Form(..., min_length=1),
    diagnosis: str = Form(..., min_length=1),
    prescription: str | None = Form(default=None),
    advice: str | None = Form(default=None),
    follow_up_date: date | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Doctor":
        raise HTTPException(
            status_code=403,
            detail="Only the appointment doctor can write a consultation",
        )

    appointment = get_appointment_or_404(db, appointment_id)
    doctor = get_doctor_profile(db, current_user)

    if doctor is None or appointment.doctor_id != doctor.id:
        raise HTTPException(
            status_code=403,
            detail="You are not the doctor assigned to this appointment",
        )

    print(
        f"DEBUG consultation: appointment_id={appointment.id}, "
        f"status={appointment.status!r}, "
        f"doctor_id={appointment.doctor_id}, "
        f"current_doctor_id={doctor.id}"
    )

    if appointment.status != "In Consultation":
        raise HTTPException(
            status_code=400,
            detail="Consultations can only be saved when status is In Consultation",
        )

    existing = (
        db.query(Consultation)
        .filter(Consultation.appointment_id == appointment.id)
        .first()
    )

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="A consultation already exists for this appointment",
        )

    prescription_data = None

    if prescription:
        import json

        try:
            prescription_data = json.loads(prescription)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422,
                detail=(
                    'Prescription must be valid JSON, e.g. '
                    '[{"medicine":"Medicine A","dosage":"1 tablet","days":5}]'
                ),
            )

        if not isinstance(prescription_data, (dict, list)):
            raise HTTPException(
                status_code=422,
                detail="Prescription must be a JSON object or array",
            )

    consultation = Consultation(
        appointment_id=appointment.id,
        symptoms=symptoms.strip(),
        diagnosis=diagnosis.strip(),
        prescription=prescription_data,
        advice=advice.strip() if advice else None,
        follow_up_date=follow_up_date,
    )

    old_status = appointment.status
    appointment.status = "Completed"

    db.add(consultation)
    db.add(
        AppointmentHistory(
            appointment_id=appointment.id,
            old_status=old_status,
            new_status="Completed",
            changed_by=current_user.id,
        )
    )

    try:
        db.commit()
        db.refresh(consultation)
    except Exception:
        db.rollback()
        raise

    return consultation_dict(consultation)


# --------------------------------------------------
# GET CONSULTATION
# GET /appointments/{appointment_id}/consultation
# --------------------------------------------------

@router.get("/appointments/{appointment_id}/consultation")
def get_consultation(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = get_appointment_or_404(db, appointment_id)
    require_appointment_access(db, current_user, appointment)

    consultation = (
        db.query(Consultation)
        .filter(Consultation.appointment_id == appointment.id)
        .first()
    )

    if consultation is None:
        raise HTTPException(
            status_code=404,
            detail="Consultation not found",
        )

    return consultation_dict(consultation)


# --------------------------------------------------
# UPLOAD APPOINTMENT FILE
# POST /appointments/{appointment_id}/files
# --------------------------------------------------

@router.post(
    "/appointments/{appointment_id}/files",
    status_code=status.HTTP_201_CREATED,
)
async def upload_appointment_file(
    appointment_id: int,
    file: UploadFile = File(...),
    file_type: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = get_appointment_or_404(db, appointment_id)

    if current_user.role == "Patient":
        patient = get_patient_profile(db, current_user)

        if patient is None or appointment.patient_id != patient.id:
            raise HTTPException(
                status_code=403,
                detail="You can only upload files for your own appointments",
            )

        if file_type != "Lab Report":
            raise HTTPException(
                status_code=403,
                detail="Patients may upload Lab Report files only",
            )

    elif current_user.role == "Doctor":
        doctor = get_doctor_profile(db, current_user)

        if doctor is None or appointment.doctor_id != doctor.id:
            raise HTTPException(
                status_code=403,
                detail="You can only upload files for your own patients",
            )

        if file_type not in {"Prescription", "Scan"}:
            raise HTTPException(
                status_code=403,
                detail="Doctors may upload Prescription or Scan files only",
            )

    else:
        raise HTTPException(
            status_code=403,
            detail="Only the patient or assigned doctor can upload files",
        )

    if file_type not in FILE_TYPES:
        raise HTTPException(
            status_code=422,
            detail="file_type must be Lab Report, Prescription, or Scan",
        )

    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()

    if not original_name or extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, JPG, JPEG, and PNG files are allowed",
        )

    content = await file.read(MAX_FILE_SIZE + 1)

    if not content:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty",
        )

    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="File size cannot exceed 5 MB",
        )

    stored_name = f"{uuid4().hex}{extension}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / stored_name

    try:
        destination.write_bytes(content)

        record = UploadedFile(
            appointment_id=appointment.id,
            uploaded_by=current_user.id,
            file_type=file_type,
            original_name=original_name[:255],
            stored_name=stored_name,
            size_kb=max(1, (len(content) + 1023) // 1024),
        )

        db.add(record)
        db.commit()
        db.refresh(record)

    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise

    finally:
        await file.close()

    return file_dict(record)


# --------------------------------------------------
# LIST APPOINTMENT FILES
# GET /appointments/{appointment_id}/files
# --------------------------------------------------

@router.get("/appointments/{appointment_id}/files")
def list_appointment_files(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    appointment = get_appointment_or_404(db, appointment_id)
    require_appointment_access(db, current_user, appointment)

    records = (
        db.query(UploadedFile)
        .filter(UploadedFile.appointment_id == appointment.id)
        .order_by(UploadedFile.created_at.desc())
        .all()
    )

    return [file_dict(record) for record in records]


# --------------------------------------------------
# DOWNLOAD APPOINTMENT FILE
# GET /files/{file_id}/download
# --------------------------------------------------

@router.get("/files/{file_id}/download")
def download_appointment_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(UploadedFile)
        .filter(UploadedFile.id == file_id)
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail="File not found",
        )

    appointment = get_appointment_or_404(db, record.appointment_id)
    require_appointment_access(db, current_user, appointment)

    path = UPLOAD_DIR / record.stored_name

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Stored file is missing",
        )

    media_types = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }

    return FileResponse(
        path=path,
        media_type=media_types.get(
            path.suffix.lower(),
            "application/octet-stream",
        ),
        filename=record.original_name,
    )


# --------------------------------------------------
# PATIENT APPOINTMENT HISTORY
# GET /patients/me/history
# --------------------------------------------------

@router.get("/patients/me/history")
def patient_appointment_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role != "Patient":
        raise HTTPException(
            status_code=403,
            detail="Only patients can view their own appointment history",
        )

    patient = get_patient_profile(db, current_user)

    if patient is None:
        raise HTTPException(
            status_code=404,
            detail="Patient profile not found",
        )

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient.id,
            Appointment.appointment_date <= date.today(),
        )
        .order_by(
            Appointment.appointment_date.desc(),
            Appointment.slot_time.desc(),
        )
        .all()
    )

    results = []

    for appointment in appointments:
        consultation = (
            db.query(Consultation)
            .filter(
                Consultation.appointment_id == appointment.id
            )
            .first()
        )

        files = (
            db.query(UploadedFile)
            .filter(
                UploadedFile.appointment_id == appointment.id
            )
            .order_by(UploadedFile.created_at.desc())
            .all()
        )

        results.append(
            {
                "appointment_id": appointment.id,
                "appointment_number": appointment.appointment_number,
                "appointment_date": appointment.appointment_date,
                "slot_time": appointment.slot_time,
                "status": appointment.status,
                "doctor_id": appointment.doctor_id,
                "diagnosis": (
                    consultation.diagnosis if consultation else None
                ),
                "consultation": (
                    consultation_dict(consultation)
                    if consultation
                    else None
                ),
                "files": [file_dict(item) for item in files],
            }
        )

    return results
