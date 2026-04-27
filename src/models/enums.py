from enum import Enum


class TrainingType(str, Enum):
    """Типы тренировок."""
    PERSONAL = "personal"
    COMMERCIAL = "commercial"
    BASIC = "basic"


class BookingStatus(str, Enum):
    """Статусы бронирования тренировок."""
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    ATTENDED = "attended"


class AdminActionType(str, Enum):
    """Типы административных действий."""
    CREATE_TRAINING = "create_training"
    UPDATE_TRAINING = "update_training"
    DELETE_TRAINING = "delete_training"
    CREATE_SCHEDULE_ENTRY = "create_schedule_entry"
    UPDATE_SCHEDULE_ENTRY = "update_schedule_entry"
    CANCEL_SCHEDULE_ENTRY = "cancel_schedule_entry"
    CONFIRM_BOOKING = "confirm_booking"
    REJECT_BOOKING = "reject_booking"
    UPDATE_USER_ADMIN_STATUS = "update_user_admin_status"
    SCHEDULE_GENERATED = "schedule_generated"
    SCHEDULE_PUBLISHED = "schedule_published"


class MessengerType(str, Enum):
    """Типы мессенджеров."""
    TELEGRAM = "telegram"
    VK = "vk"


class ReminderStatus(str, Enum):
    """Статусы напоминаний."""
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"