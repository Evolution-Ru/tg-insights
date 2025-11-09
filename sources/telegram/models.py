"""
Модели данных для Telegram
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class TelegramMessage:
    """Модель сообщения Telegram"""
    chat_id: str
    message_id: int
    date: str
    from_id: Optional[int]
    content: str
    sender_name: str
    chat_name: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Преобразует в словарь"""
        return {
            "chat_id": self.chat_id,
            "message_id": self.message_id,
            "date": self.date,
            "from_id": self.from_id,
            "content": self.content,
            "sender_name": self.sender_name,
            "chat_name": self.chat_name
        }


@dataclass
class TelegramUser:
    """Модель пользователя Telegram"""
    id: int
    type: Optional[str] = None
    name: Optional[str] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    about: Optional[str] = None
    is_bot: Optional[int] = None
    verified: Optional[int] = None

