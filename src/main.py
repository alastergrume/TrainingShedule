from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import logging
from contextlib import asynccontextmanager
from datetime import datetime, date, timedelta
from typing import Optional

from src.config import settings
from src.models import Base, engine, get_db
from src.business_logic import ScheduleService, AdminService
from src.business_logic.schemas import (
    TrainingCreate,
    TrainingResponse,
    ScheduleEntryCreate,
    BookingCreate,
)
from src.messengers.telegram.bot import TelegramBot
from src.messengers.vk.bot import VKBot

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan events for FastAPI app."""
    # Startup
    logger.info("Starting Training Schedule Application")
    
    # Create database tables
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")
    
    # Start bots in background (in real app would be proper async tasks)
    # For now just initialize
    if settings.TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot initialized")
    
    if settings.VK_GROUP_TOKEN:
        logger.info("VK bot initialized")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Training Schedule Application")


# Dependency functions
def get_schedule_service():
    """Dependency for ScheduleService."""
    db = next(get_db())
    return ScheduleService(db)


def get_admin_service():
    """Dependency for AdminService."""
    db = next(get_db())
    return AdminService(db)


# Create FastAPI app
app = FastAPI(
    title="Training Schedule API",
    description="API for managing training schedules and bookings",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Training Schedule API",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


@app.get("/api/schedule/week")
async def get_week_schedule(
    week_start: Optional[str] = None,
    include_basic: bool = True,
    service: ScheduleService = Depends(get_schedule_service)
):
    """Get schedule for a week."""
    if week_start:
        week_start_date = datetime.fromisoformat(week_start).date()
    else:
        # Default to current week's Monday
        today = date.today()
        week_start_date = today - timedelta(days=today.weekday())
    
    schedule = service.get_week_schedule(week_start_date, include_basic)
    return {
        "week_start": week_start_date.isoformat(),
        "schedule": schedule
    }


@app.post("/api/bookings")
async def create_booking(
    booking_data: dict,
    service: ScheduleService = Depends(get_schedule_service)
):
    """Create a new booking."""
    booking_create = BookingCreate(**booking_data)
    booking = service.create_booking(booking_create)
    return {"booking": booking, "message": "Booking created successfully"}


# Admin endpoints
@app.get("/api/admin/trainings")
async def get_trainings(
    include_inactive: bool = False,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get all training templates."""
    trainings = admin_service.get_all_trainings(include_inactive)
    return {"trainings": trainings}


@app.post("/api/admin/trainings")
async def create_training(
    training_data: TrainingCreate,
    admin_id: int = 1,  # In real app, get from authentication
    admin_service: AdminService = Depends(get_admin_service)
):
    """Create a new training template."""
    training = admin_service.create_training(training_data, admin_id)
    return {"training": training, "message": "Training created successfully"}


@app.put("/api/admin/trainings/{training_id}")
async def update_training(
    training_id: int,
    update_data: dict,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Update a training template."""
    training = admin_service.update_training(training_id, update_data, admin_id)
    return {"training": training, "message": "Training updated successfully"}


@app.delete("/api/admin/trainings/{training_id}")
async def delete_training(
    training_id: int,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Delete a training template (soft delete)."""
    admin_service.delete_training(training_id, admin_id)
    return {"message": "Training deleted successfully"}


@app.post("/api/admin/schedule-entries")
async def create_schedule_entry(
    entry_data: ScheduleEntryCreate,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Create a specific schedule entry."""
    entry = admin_service.create_schedule_entry(entry_data, admin_id)
    return {"entry": entry, "message": "Schedule entry created successfully"}


@app.put("/api/admin/schedule-entries/{entry_id}")
async def update_schedule_entry(
    entry_id: int,
    update_data: dict,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Update a schedule entry."""
    entry = admin_service.update_schedule_entry(entry_id, update_data, admin_id)
    return {"entry": entry, "message": "Schedule entry updated successfully"}


@app.post("/api/admin/schedule-entries/{entry_id}/cancel")
async def cancel_schedule_entry(
    entry_id: int,
    reason: str,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Cancel a schedule entry."""
    entry = admin_service.cancel_schedule_entry(entry_id, reason, admin_id)
    return {"entry": entry, "message": "Schedule entry cancelled successfully"}


@app.get("/api/admin/bookings/pending")
async def get_pending_bookings(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get pending bookings requiring approval."""
    bookings = admin_service.get_pending_bookings()
    return {"bookings": bookings}


@app.post("/api/admin/bookings/{booking_id}/confirm")
async def confirm_booking(
    booking_id: int,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Confirm a booking."""
    booking = admin_service.confirm_booking(booking_id, admin_id)
    return {"booking": booking, "message": "Booking confirmed successfully"}


@app.post("/api/admin/bookings/{booking_id}/reject")
async def reject_booking(
    booking_id: int,
    reason: str,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Reject a booking."""
    booking = admin_service.reject_booking(booking_id, reason, admin_id)
    return {"booking": booking, "message": "Booking rejected successfully"}


@app.get("/api/admin/users")
async def get_users(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get all users."""
    users = admin_service.get_all_users()
    return {"users": users}


@app.put("/api/admin/users/{user_id}/admin-status")
async def update_user_admin_status(
    user_id: int,
    is_admin: bool,
    admin_id: int = 1,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Update user's admin status."""
    user = admin_service.update_user_admin_status(user_id, is_admin, admin_id)
    return {"user": user, "message": "User admin status updated successfully"}


@app.get("/api/admin/actions")
async def get_admin_actions(
    limit: int = 100,
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get recent admin actions."""
    actions = admin_service.get_admin_actions(limit)
    return {"actions": actions}


@app.get("/api/admin/stats")
async def admin_stats(
    admin_service: AdminService = Depends(get_admin_service)
):
    """Get admin statistics."""
    db = next(get_db())
    from sqlalchemy import func
    from src.models import User, Booking, Training
    
    total_users = db.query(func.count(User.id)).scalar()
    total_bookings = db.query(func.count(Booking.id)).scalar()
    active_trainings = db.query(func.count(Training.id)).filter(Training.is_active == True).scalar()
    
    return {
        "total_users": total_users,
        "total_bookings": total_bookings,
        "active_trainings": active_trainings,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )