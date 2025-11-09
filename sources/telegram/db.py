"""
Работа с базой данных Telegram
"""
from pathlib import Path
from shared.utils.db import get_db_connection

# Re-export для удобства
__all__ = ['get_db_connection']

