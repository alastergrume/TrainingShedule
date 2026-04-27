from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any


class MessengerInterface(ABC):
    """Abstract interface for all messengers."""

    @abstractmethod
    async def send_message(self, chat_id: str, text: str, **kwargs) -> Any:
        """Send a text message."""
        pass

    @abstractmethod
    async def edit_message(self, chat_id: str, message_id: int, text: str, **kwargs) -> Any:
        """Edit an existing message."""
        pass

    @abstractmethod
    async def delete_message(self, chat_id: str, message_id: int) -> bool:
        """Delete a message."""
        pass

    @abstractmethod
    async def send_schedule(self, schedule_data: Dict, **kwargs) -> Dict:
        """Send schedule in appropriate format."""
        pass

    @abstractmethod
    async def update_schedule(self, schedule_data: Dict, message_id: int, **kwargs) -> Dict:
        """Update existing schedule message."""
        pass

    @abstractmethod
    async def send_reminder(self, user_id: str, reminder_data: Dict) -> bool:
        """Send reminder to user."""
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> Dict:
        """Get user information."""
        pass


class MessengerFactory:
    """Factory to create messenger instances."""
    
    _messengers = {}
    
    @classmethod
    def register(cls, name: str, messenger_class):
        cls._messengers[name] = messenger_class
    
    @classmethod
    def create(cls, name: str, **kwargs) -> MessengerInterface:
        messenger_class = cls._messengers.get(name)
        if not messenger_class:
            raise ValueError(f"Messenger '{name}' not registered")
        return messenger_class(**kwargs)
    
    @classmethod
    def get_available(cls) -> List[str]:
        return list(cls._messengers.keys())