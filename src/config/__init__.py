import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import validator


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/training_schedule"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHANNEL_ID: str = ""
    TELEGRAM_ADMIN_IDS: List[int] = []
    
    @validator("TELEGRAM_ADMIN_IDS", pre=True)
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            if not v.strip():
                return []
            return [int(id.strip()) for id in v.split(",")]
        return v
    
    # VK
    VK_GROUP_TOKEN: str = ""
    VK_GROUP_ID: int = 0
    VK_CONFIRMATION_CODE: str = ""
    VK_SECRET_KEY: str = ""
    
    # Application
    DEBUG: bool = True
    SECRET_KEY: str = "your-secret-key-change-in-production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    
    # Reminder settings
    REMINDER_MINUTES_BEFORE: int = 60
    ADMIN_NOTIFICATION_ENABLED: bool = True
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
