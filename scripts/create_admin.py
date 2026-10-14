import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import getpass

from sqlalchemy.exc import IntegrityError

from app.auth.security import hash_password
from app.database import SessionLocal
from app.models import User


def main():
    print("\n=== Create First Admin Account ===")

    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    phone = input("Admin phone (10 digits): ").strip()

    password = getpass.getpass("Admin password (minimum 8 characters): ")
    confirm_password = getpass.getpass("Confirm password: ")

    if len(name) < 2:
        print("ERROR: Name must contain at least 2 characters.")
        return

    if "@" not in email:
        print("ERROR: Enter a valid email address.")
        return

    if not phone.isdigit() or len(phone) != 10:
        print("ERROR: Phone must contain exactly 10 digits.")
        return

    if len(password) < 8:
        print("ERROR: Password must contain at least 8 characters.")
        return

    if password != confirm_password:
        print("ERROR: Passwords do not match.")
        return

    db = SessionLocal()

    try:
        existing = db.query(User).filter(User.email == email).first()

        if existing:
            print("ERROR: This email is already registered.")
            return

        admin = User(
            name=name,
            email=email,
            phone=phone,
            hashed_password=hash_password(password),
            role="Admin",
            is_active=True,
        )

        db.add(admin)
        db.commit()

        print("\nSUCCESS: Admin account created.")
        print("Email:", email)
        print("Role: Admin")
        print("Now log in through Swagger.")

    except IntegrityError:
        db.rollback()
        print("ERROR: Account conflicts with an existing database record.")

    finally:
        db.close()


if __name__ == "__main__":
    main()