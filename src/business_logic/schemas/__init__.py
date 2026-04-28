from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TrainingTypeEnum(str, Enum):
    personal = "personal"
    commercial = "commercial"
    basic = "basic"


class UserCreate(BaseModel):
    telegram_id: Optional[int] = None
    vk_id: Optional[int] = None
    username: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    is_admin: bool = False


class UserResponse(BaseModel):
    id: int
    telegram_id: Optional[int]
    vk_id: Optional[int]
    username: Optional[str]
    first_name: str
    last_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    is_admin: bool
    created_at: datetime

    class Config:
        from_attributes = True


class TrainingCreate(BaseModel):
    title: str = Field(..., max_length=200)
    description: Optional[str] = None
    training_type: TrainingTypeEnum
    day_of_week: int = Field(..., ge=0, le=6)
    start_time: str = Field(..., pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    duration_minutes: int = Field(default=60, gt=0)
    max_participants: Optional[int] = None
    is_active: bool = True


class TrainingUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    training_type: Optional[TrainingTypeEnum] = None
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    start_time: Optional[str] = Field(None, pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    duration_minutes: Optional[int] = Field(None, gt=0)
    max_participants: Optional[int] = None
    is_active: Optional[bool] = None


class TrainingResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    training_type: TrainingTypeEnum
    day_of_week: int
    start_time: str
    duration_minutes: int
    max_participants: Optional[int]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ScheduleEntryCreate(BaseModel):
    training_id: int
    date: datetime
    start_time: str = Field(..., pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    end_time: str = Field(..., pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    is_cancelled: bool = False
    cancellation_reason: Optional[str] = None


class ScheduleEntryUpdate(BaseModel):
    start_time: Optional[str] = Field(None, pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    end_time: Optional[str] = Field(None, pattern=r"^([0-1]?[0-9]|2[0-3]):[0-5][0-9]$")
    is_cancelled: Optional[bool] = None
    cancellation_reason: Optional[str] = None


class BookingCreate(BaseModel):
    user_id: int
    training_id: int
    schedule_entry_id: Optional[int] = None
    notes: Optional[str] = None


class BookingResponse(BaseModel):
    id: int
    user_id: int
    training_id: int
    schedule_entry_id: Optional[int]
    status: str
    notes: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    booking_id: int
    user_id: int
    amount: int
    payment_method: Optional[str] = None
    is_paid: bool = False
    transaction_id: Optional[str] = None


class WeekScheduleRequest(BaseModel):
    week_start_date: datetime
    include_basic: bool = True


class PublishedScheduleCreate(BaseModel):
    week_start_date: datetime
    week_end_date: datetime
    telegram_message_id: Optional[int] = None
    vk_post_id: Optional[int] = None
    content: str
