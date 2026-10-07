import os
from typing import List
from pydantic_settings import BaseSettings
from pydantic import field_validator, ConfigDict, JsonValue


class Settings(BaseSettings):
    model_config = ConfigDict(
        env_file=".env", 
        case_sensitive=False,
        json_schema_extra={
            "properties": {
                "TELEGRAM_ADMIN_IDS": {"type": "string"}
            }
        }
    )
    
    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/training_schedule"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHANNEL_ID: str = ""
    TELEGRAM_ADMIN_IDS: str = ""  # Keep as string first
    
    @field_validator("TELEGRAM_ADMIN_IDS", mode="after")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                return [int(id.strip()) for id in v.split(",")]
            except ValueError:
                return []
        if isinstance(v, list):
            return v
        return []
    
    # VK
    VK_GROUP_TOKEN: str = ""
    VK_GROUP_ID: int = 0
    VK_USER_TOKEN: str = ""
    VK_ADMIN_IDS: str = ""  # Keep as string first

    @field_validator("VK_ADMIN_IDS", mode="after")
    @classmethod
    def parse_vk_admin_ids(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            try:
                return [int(id.strip()) for id in v.split(",")]
            except ValueError:
                return []
        if isinstance(v, list):
            return v
        return []

    VK_CONFIRMATION_CODE: str = ""
    VK_SECRET_KEY: str = ""
    VK_INVITE_DAILY_LIMIT: int = 40
    VK_INVITE_DELAY_SECONDS: int = 3
    
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

    # Mini App — публичный URL приложения (HTTPS в проде, ngrok для локальных тестов)
    MINIAPP_URL: str = "http://localhost:8000"

class VkSettings(BaseSettings):
    model_config = ConfigDict(env_file="./.env", extra="ignore")
    VK_GROUP_TOKEN: str = ""

settings = Settings()
vk_settings = VkSettings()
