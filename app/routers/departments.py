from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_roles
from app.database import get_db
from app.models import Department, User
from app.schemas.department import (
    DepartmentCreate,
    DepartmentResponse,
    DepartmentUpdate,
)

router = APIRouter(prefix="/departments", tags=["Departments"])


@router.post(
    "",
    response_model=DepartmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_department(
    data: DepartmentCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    name = data.name.strip()

    if not name:
        raise HTTPException(status_code=422, detail="Department name is required")

    existing = db.query(Department).filter(
        Department.name == name
    ).first()

    if existing:
        raise HTTPException(
            status_code=409,
            detail="Department already exists",
        )

    department = Department(
        name=name,
        description=data.description,
        is_active=True,
    )

    try:
        db.add(department)
        db.commit()
        db.refresh(department)
        return department
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Department already exists",
        )


@router.get("", response_model=list[DepartmentResponse])
def list_departments(db: Session = Depends(get_db)):
    return (
        db.query(Department)
        .filter(Department.is_active.is_(True))
        .order_by(Department.name)
        .all()
    )


@router.get("/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: int,
    db: Session = Depends(get_db),
):
    department = db.query(Department).filter(
        Department.id == department_id,
        Department.is_active.is_(True),
    ).first()

    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    return department


@router.patch("/{department_id}", response_model=DepartmentResponse)
def update_department(
    department_id: int,
    data: DepartmentUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_roles("Admin")),
):
    department = db.query(Department).filter(
        Department.id == department_id
    ).first()

    if department is None:
        raise HTTPException(status_code=404, detail="Department not found")

    changes = data.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(
            status_code=422,
            detail="Provide at least one field to update",
        )

    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()

        duplicate = db.query(Department).filter(
            Department.name == changes["name"],
            Department.id != department_id,
        ).first()

        if duplicate:
            raise HTTPException(
                status_code=409,
                detail="Department name already exists",
            )

    for field, value in changes.items():
        setattr(department, field, value)

    try:
        db.commit()
        db.refresh(department)
        return department
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Department update conflicts with existing data",
        )