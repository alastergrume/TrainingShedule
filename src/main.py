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
    QuickUserCreate,
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
    path = os.path.join(os.path.dirname(__file__), "static", "admin", "index.html")
    if not os.path.exists(path):
        return {"message": "Training Schedule API", "version": "1.0.0", "docs": "/docs"}
    return FileResponse(path)


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
    result = []
    for t in trainings:
        participants = admin_service.get_training_participants(t.id)
        result.append({
            "id": t.id,
            "title": t.title,
            "description": t.description,
            "training_type": t.training_type.value if hasattr(t.training_type, "value") else t.training_type,
            "day_of_week": t.day_of_week,
            "start_time": t.start_time,
            "duration_minutes": t.duration_minutes,
            "max_participants": t.max_participants,
            "is_active": t.is_active,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "participants": participants,
        })
    return {"trainings": result}


@app.post("/api/admin/trainings", response_model=TrainingResponse)
async def create_training(
    training_data: TrainingCreate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service),
):
    try:
        training = admin_service.create_training(training_data, admin_id)
        return training
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# --- Admin: Users search & quick create ---

@app.get("/api/admin/users/search")
async def search_users(
    q: str = "",
    admin_service: AdminService = Depends(get_admin_service),
):
    if not q.strip():
        users = admin_service.get_all_users()
    else:
        users = admin_service.search_users(q)
    return {
        "users": [
            {
                "id": u.id,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "username": u.username,
            }
            for u in users
        ]
    }


@app.post("/api/admin/users")
async def create_quick_user(
    user_data: QuickUserCreate,
    admin_service: AdminService = Depends(get_admin_service),
):
    user = admin_service.create_quick_user(user_data.first_name, user_data.last_name)
    return {"id": user.id, "first_name": user.first_name, "last_name": user.last_name}


@app.get("/api/admin/trainings/{training_id}/participants")
async def get_training_participants(
    training_id: int,
    admin_service: AdminService = Depends(get_admin_service),
):
    participants = admin_service.get_training_participants(training_id)
    return {"participants": participants}


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

@app.get("/api/admin/schedule/publish-status")
async def get_publish_status(
    week_starts: str = "",
    service: ScheduleService = Depends(get_schedule_service),
):
    """Check publication status for given weeks (comma-separated ISO dates)."""
    from src.models.models import PublishedSchedule as PS
    result = {}
    to_verify = []

    for ws in week_starts.split(","):
        ws = ws.strip()
        if not ws:
            continue
        try:
            ws_date = datetime.fromisoformat(ws).date()
        except ValueError:
            continue
        published = (
            service.db.query(PS)
            .filter(PS.week_start_date == ws_date)
            .order_by(PS.published_at.desc())
            .first()
        )
        has_message = bool(
            published and (published.telegram_message_id or published.vk_post_id)
        )
        result[ws] = {
            "published": has_message,
            "published_at": published.published_at.isoformat() if published else None,
            "telegram_message_id": published.telegram_message_id if published else None,
            "telegram_channel_id": settings.TELEGRAM_CHANNEL_ID or None,
        }
        if published and (published.telegram_message_id or published.vk_post_id):
            to_verify.append((ws, published))

    if to_verify:
        from src.messengers.interfaces.messenger import MessengerFactory
        tg = None
        vk = None
        if settings.TELEGRAM_BOT_TOKEN:
            try:
                tg = MessengerFactory.create('telegram')
            except Exception as e:
                logger.warning(f"Failed to create telegram messenger: {e}")
        if settings.VK_GROUP_TOKEN:
            try:
                vk = MessengerFactory.create('vk')
            except Exception as e:
                logger.warning(f"Failed to create vk messenger: {e}")

        for ws, pub in to_verify:
            changed = False
            if pub.telegram_message_id and tg:
                try:
                    if not await tg.check_message_exists(tg.channel_id, pub.telegram_message_id):
                        pub.telegram_message_id = None
                        changed = True
                except Exception as e:
                    logger.warning(f"TG check error for {ws}: {e}")
            if pub.vk_post_id and vk:
                try:
                    if not await vk.check_post_exists(pub.vk_post_id):
                        pub.vk_post_id = None
                        changed = True
                except Exception as e:
                    logger.warning(f"VK check error for {ws}: {e}")
            if changed:
                service.db.commit()
                has_msg = bool(pub.telegram_message_id or pub.vk_post_id)
                result[ws]["published"] = has_msg
                result[ws]["telegram_message_id"] = pub.telegram_message_id
                if not has_msg:
                    result[ws]["message_deleted"] = True

    return result


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

    # Проверяем, есть ли уже публикация с message_id
    from src.models.models import PublishedSchedule as PS
    existing = (
        db.query(PS)
        .filter(PS.week_start_date == week_start_date)
        .first()
    )
    existing_tg_id = existing.telegram_message_id if existing else None
    existing_vk_id = existing.vk_post_id if existing else None

    # Сохраняем/обновляем запись о публикации
    service.publish_schedule(week_start_date, content)

    # Запускаем публикацию через Celery (с message_id для редактирования)
    publish_schedule_to_channels.delay(
        week_start_date.isoformat(),
        {"days": [
            {**d, "date": d["date"].isoformat() if hasattr(d["date"], "isoformat") else str(d["date"])}
            for d in days
        ]},
        telegram_message_id=existing_tg_id,
        vk_post_id=existing_vk_id,
    )

    is_update = existing_tg_id or existing_vk_id
    return {
        "message": "Расписание обновлено" if is_update else "Публикация запущена",
        "preview": content[:300] + "...",
    }


# --- Admin: check message existence ---

@app.get("/api/admin/schedule/check-message")
async def check_message_exists(
    week_start: str,
    service: ScheduleService = Depends(get_schedule_service),
):
    """Check if published messages still exist in Telegram/VK."""
    from src.models.models import PublishedSchedule as PS

    ws_date = datetime.fromisoformat(week_start).date()
    published = (
        service.db.query(PS)
        .filter(PS.week_start_date == ws_date)
        .first()
    )
    if not published:
        return {"exists": False, "reason": "not_published"}

    result = {"telegram": None, "vk": None}

    from src.messengers.interfaces.messenger import MessengerFactory

    if published.telegram_message_id and settings.TELEGRAM_BOT_TOKEN:
        try:
            tg = MessengerFactory.create('telegram')
            exists = await tg.check_message_exists(
                tg.channel_id, published.telegram_message_id
            )
            result["telegram"] = exists
            if not exists:
                published.telegram_message_id = None
        except Exception:
            result["telegram"] = None

    if published.vk_post_id and settings.VK_GROUP_TOKEN:
        try:
            vk = MessengerFactory.create('vk')
            exists = await vk.check_post_exists(published.vk_post_id)
            result["vk"] = exists
            if not exists:
                published.vk_post_id = None
        except Exception:
            result["vk"] = None

    changed = (published.telegram_message_id is None and result.get("telegram") is False) or \
              (published.vk_post_id is None and result.get("vk") is False)
    if changed:
        service.db.commit()

    any_exists = any(v is True for v in result.values())
    return {"exists": any_exists, "channels": result}


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
