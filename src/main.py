from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from typing import Optional

from src.config import settings
from src.models import Base, engine, get_db
from src.models.models import User, Booking, Training
from src.business_logic import ScheduleService, AdminService
from src.business_logic.schemas import (
    TrainingCreate,
    TrainingUpdate,
    TrainingResponse,
    ScheduleEntryCreate,
    ScheduleEntryUpdate,
    BookingCreate,
)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Training Schedule Application")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")

    if settings.TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot initialized")
    if settings.VK_GROUP_TOKEN:
        logger.info("VK bot initialized")

    yield
    logger.info("Shutting down Training Schedule Application")


def get_schedule_service(db: Session = Depends(get_db)) -> ScheduleService:
    return ScheduleService(db)


def get_admin_service(db: Session = Depends(get_db)) -> AdminService:
    return AdminService(db)


app = FastAPI(
    title="Training Schedule API",
    description="API for managing training schedules and bookings",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/")
async def root():
    return {"message": "Training Schedule API", "version": "1.0.0", "docs": "/docs"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# --- Schedule ---

@app.get("/api/schedule/week")
async def get_week_schedule(
    week_start: Optional[str] = None,
    include_basic: bool = True,
    service: ScheduleService = Depends(get_schedule_service),
):
    if week_start:
        week_start_date = datetime.fromisoformat(week_start).date()
    else:
        today = date.today()
        week_start_date = today - timedelta(days=today.weekday())

    schedule = service.get_week_schedule(week_start_date, include_basic)
    return {"week_start": week_start_date.isoformat(), "schedule": schedule}


@app.post("/api/bookings")
async def create_booking(
    booking_data: BookingCreate,
    service: ScheduleService = Depends(get_schedule_service),
):
    try:
        booking = service.create_booking(booking_data)
        return {"booking_id": booking.id, "message": "Booking created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- Admin: Training templates ---

@app.get("/api/admin/trainings")
async def get_trainings(
    include_inactive: bool = False,
    admin_service: AdminService = Depends(get_admin_service),
):
    trainings = admin_service.get_all_trainings(include_inactive)
    return {"trainings": trainings}


@app.post("/api/admin/trainings", response_model=TrainingResponse)
async def create_training(
    training_data: TrainingCreate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    training = admin_service.create_training(training_data, admin_id)
    return training


@app.put("/api/admin/trainings/{training_id}")
async def update_training(
    training_id: int,
    update_data: TrainingUpdate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        training = admin_service.update_training(
            training_id, update_data.dict(exclude_none=True), admin_id
        )
        return {"training": training, "message": "Training updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.delete("/api/admin/trainings/{training_id}")
async def delete_training(
    training_id: int,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        admin_service.delete_training(training_id, admin_id)
        return {"message": "Training deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Admin: Schedule entries ---

@app.post("/api/admin/schedule-entries")
async def create_schedule_entry(
    entry_data: ScheduleEntryCreate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        entry = admin_service.create_schedule_entry(entry_data, admin_id)
        return {"entry_id": entry.id, "message": "Schedule entry created successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.put("/api/admin/schedule-entries/{entry_id}")
async def update_schedule_entry(
    entry_id: int,
    update_data: ScheduleEntryUpdate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        entry = admin_service.update_schedule_entry(
            entry_id, update_data.dict(exclude_none=True), admin_id
        )
        return {"entry_id": entry.id, "message": "Schedule entry updated successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/schedule-entries/{entry_id}/cancel")
async def cancel_schedule_entry(
    entry_id: int,
    reason: str,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        entry = admin_service.cancel_schedule_entry(entry_id, reason, admin_id)
        return {"entry_id": entry.id, "message": "Schedule entry cancelled"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Admin: Schedule generation ---

@app.post("/api/admin/schedule/generate")
async def generate_schedule(
    week_start: Optional[str] = None,
    include_basic: bool = True,
    admin_id: int = 1,
    service: ScheduleService = Depends(get_schedule_service),
):
    if week_start:
        week_start_date = datetime.fromisoformat(week_start).date()
    else:
        today = date.today()
        days_ahead = 7 - today.weekday()
        week_start_date = today + timedelta(days=days_ahead)

    entries = service.generate_weekly_schedule(week_start_date, include_basic)
    return {"message": f"Generated {len(entries)} entries", "week_start": week_start_date.isoformat()}


# --- Admin: Bookings ---

@app.get("/api/admin/bookings/pending")
async def get_pending_bookings(
    admin_service: AdminService = Depends(get_admin_service),
):
    bookings = admin_service.get_pending_bookings()
    return {"bookings": bookings}


@app.post("/api/admin/bookings/{booking_id}/confirm")
async def confirm_booking(
    booking_id: int,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        booking = admin_service.confirm_booking(booking_id, admin_id)
        return {"booking_id": booking.id, "message": "Booking confirmed"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/admin/bookings/{booking_id}/reject")
async def reject_booking(
    booking_id: int,
    reason: str,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        booking = admin_service.reject_booking(booking_id, reason, admin_id)
        return {"booking_id": booking.id, "message": "Booking rejected"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Admin: Users ---

@app.get("/api/admin/users")
async def get_users(
    admin_service: AdminService = Depends(get_admin_service),
):
    users = admin_service.get_all_users()
    return {"users": users}


@app.put("/api/admin/users/{user_id}/admin-status")
async def update_user_admin_status(
    user_id: int,
    is_admin: bool,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        user = admin_service.update_user_admin_status(user_id, is_admin, admin_id)
        return {"user_id": user.id, "message": "Admin status updated"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Admin: Audit & stats ---

@app.get("/api/admin/actions")
async def get_admin_actions(
    limit: int = 100,
    admin_service: AdminService = Depends(get_admin_service),
):
    actions = admin_service.get_admin_actions(limit)
    return {"actions": actions}


@app.get("/api/admin/stats")
async def admin_stats(
    admin_service: AdminService = Depends(get_admin_service),
):
    db = admin_service.db
    total_users = db.query(func.count(User.id)).scalar()
    total_bookings = db.query(func.count(Booking.id)).scalar()
    active_trainings = (
        db.query(func.count(Training.id)).filter(Training.is_active == True).scalar()
    )
    return {
        "total_users": total_users,
        "total_bookings": total_bookings,
        "active_trainings": active_trainings,
    }


# --- Admin: publish schedule ---

@app.post("/api/admin/schedule/publish")
async def publish_schedule(
    week_start: Optional[str] = None,
    admin_id: int = 1,
    service: ScheduleService = Depends(get_schedule_service),
):
    """Публикует расписание в Telegram-канал и VK."""
    if week_start:
        week_start_date = datetime.fromisoformat(week_start).date()
    else:
        today = date.today()
        week_start_date = today - timedelta(days=today.weekday())

    from src.utils.formatter import ScheduleGenerator, ScheduleFormatter
    from src.models.base import SessionLocal
    from src.celery_app import publish_schedule_to_channels

    db = service.db
    days = ScheduleGenerator.generate_from_db(db, week_start_date)
    content = ScheduleFormatter.format_week_schedule(days, week_start_date)

    # Сохраняем запись о публикации
    service.publish_schedule(week_start_date, content)

    # Запускаем публикацию через Celery
    publish_schedule_to_channels.delay(
        week_start_date.isoformat(),
        {"days": [
            {**d, "date": d["date"].isoformat() if hasattr(d["date"], "isoformat") else str(d["date"])}
            for d in days
        ]},
    )

    return {"message": "Публикация запущена", "preview": content[:300] + "..."}


# --- Admin: payment status ---

@app.put("/api/admin/bookings/{booking_id}/payment")
async def update_payment(
    booking_id: int,
    is_paid: bool,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    """Отметить оплату для бронирования."""
    try:
        payment = admin_service.update_payment_status(booking_id, is_paid, admin_id)
        return {"booking_id": booking_id, "is_paid": is_paid}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# --- Mini App ---

@app.get("/api/admin/verify")
async def verify_admin(
    telegram_id: int,
    admin_service: AdminService = Depends(get_admin_service),
):
    """Проверяет, является ли пользователь Telegram администратором."""
    user = admin_service.get_user_by_telegram_id(telegram_id)
    if not user:
        return {"is_admin": False, "user_id": None}
    return {"is_admin": user.is_admin, "user_id": user.id}


@app.get("/miniapp")
async def miniapp():
    """Отдаёт Mini App для Telegram Web App."""
    path = os.path.join(os.path.dirname(__file__), "static", "miniapp", "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Mini App not found")
    return FileResponse(path)


@app.get("/admin")
async def admin_panel():
    """Веб-панель администратора."""
    path = os.path.join(os.path.dirname(__file__), "static", "admin", "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Admin panel not found")
    return FileResponse(path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
