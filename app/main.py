
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine
from app.jobs.scheduler import start_scheduler, stop_scheduler
from app.routers.auth import router as auth_router
from app.routers.departments import router as departments_router
from app.routers.doctors import router as doctors_router
from app.routers.schedules import router as schedules_router
from app.routers.availability import router as availability_router
from app.routers.appointments import router as appointments_router
from app.routers.consultations import router as consultations_router
from app.routers.queue import router as queue_router
from app.routers.reports import router as reports_router

APP_NAME = "Hospital Appointment Booking System"

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        engine.dispose()


app = FastAPI(
    title=APP_NAME,
    description="Hospital appointment booking and live queue management API",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(departments_router)
app.include_router(doctors_router)
app.include_router(schedules_router)
app.include_router(availability_router)
app.include_router(appointments_router)
app.include_router(consultations_router)
app.include_router(queue_router)
app.include_router(reports_router)

@app.get("/", tags=["Health"])
def root():
    return {"message": "Hospital Appointment Booking System is running"}


@app.get("/health", tags=["Health"])
def health_check():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}
