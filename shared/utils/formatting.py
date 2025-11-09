"""
Утилиты для форматирования сообщений и потоков
"""
from typing import List, Dict, Any


def get_short_name(full_name: str) -> str:
    """Извлекает только имя без фамилии"""
    if not full_name:
        return "Неизвестно"
    parts = full_name.strip().split()
    return parts[0] if parts else full_name


def format_messages_as_thread(messages: List[Dict[str, Any]]) -> str:
    """
    Форматирует сообщения в единый поток с пометками чатов и участников.
    Оптимизировано: группирует по дням, убирает повторяющиеся даты и фамилии.
    """
    lines = []
    current_chat = None
    current_date = None
    
    for msg in messages:
        chat_name = msg["chat_name"]
        date = msg["date"]
        sender = get_short_name(msg["sender_name"])
        content = msg["content"].strip()
        
        if not content:
            continue
        
        # Извлекаем дату (YYYY-MM-DD)
        date_str = date[:10] if len(date) > 10 else date
        
        # Добавляем пометку чата при смене
        if chat_name != current_chat:
            if lines:
                lines.append("")
            lines.append(f"{'='*60}")
            lines.append(f"💬 ЧАТ: {chat_name}")
            lines.append(f"{'='*60}")
            current_chat = chat_name
            current_date = None
        
        # Добавляем дату только если она изменилась
        if date_str != current_date:
            lines.append(f"\n📅 {date_str}")
            current_date = date_str
        
        # Сообщение без даты (она уже указана выше)
        lines.append(f"{sender}: {content}")
    
    return "\n".join(lines)

