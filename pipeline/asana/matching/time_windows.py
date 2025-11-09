"""
Менеджер временных окон для сопоставления задач
Использует временные метки для определения релевантного контекста
"""
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
import re


class TimeWindowMatcher:
    """Менеджер временных окон для сопоставления задач"""
    
    def __init__(
        self,
        primary_window_days: int = 7,
        extended_window_days: int = 30,
        distant_window_days: int = 90
    ):
        """
        Инициализация менеджера временных окон
        
        Args:
            primary_window_days: Размер основного окна в днях (±N дней)
            extended_window_days: Размер расширенного окна в днях (±N дней)
            distant_window_days: Размер дальнего окна в днях (±N дней)
        """
        self.primary_window_days = primary_window_days
        self.extended_window_days = extended_window_days
        self.distant_window_days = distant_window_days
    
    def extract_dates_from_context(self, context: str) -> List[str]:
        """
        Извлекает даты из контекста Telegram задачи
        
        Args:
            context: Текст контекста с датами в формате YYYY-MM-DD или [YYYY-MM-DD HH:MM]
            
        Returns:
            Список дат в формате YYYY-MM-DD
        """
        dates = []
        
        # Паттерны для поиска дат
        patterns = [
            r'\b(\d{4}-\d{2}-\d{2})\b',  # YYYY-MM-DD
            r'\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\]',  # [YYYY-MM-DD HH:MM]
            r'📅\s*(\d{4}-\d{2}-\d{2})',  # 📅 YYYY-MM-DD
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, context)
            dates.extend(matches)
        
        # Убираем дубликаты и сортируем
        dates = sorted(list(set(dates)))
        return dates
    
    def calculate_time_windows(self, first_date: Optional[str] = None, dates: Optional[List[str]] = None) -> Dict[str, Dict[str, str]]:
        """
        Вычисляет временные окна для задачи
        
        Args:
            first_date: Первая дата упоминания задачи (YYYY-MM-DD)
            dates: Список всех дат из контекста (если first_date не указана, берется первая)
            
        Returns:
            Словарь с окнами:
            {
                "primary": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
                "extended": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"},
                "distant": {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
            }
        """
        # Определяем базовую дату
        if first_date:
            base_date = datetime.strptime(first_date, "%Y-%m-%d")
        elif dates and len(dates) > 0:
            base_date = datetime.strptime(dates[0], "%Y-%m-%d")
        else:
            # Если дат нет, используем текущую дату
            base_date = datetime.now()
        
        windows = {
            "primary": {
                "from": (base_date - timedelta(days=self.primary_window_days)).strftime("%Y-%m-%d"),
                "to": (base_date + timedelta(days=self.primary_window_days)).strftime("%Y-%m-%d")
            },
            "extended": {
                "from": (base_date - timedelta(days=self.extended_window_days)).strftime("%Y-%m-%d"),
                "to": (base_date + timedelta(days=self.extended_window_days)).strftime("%Y-%m-%d")
            },
            "distant": {
                "from": (base_date - timedelta(days=self.distant_window_days)).strftime("%Y-%m-%d"),
                "to": (base_date + timedelta(days=self.distant_window_days)).strftime("%Y-%m-%d")
            }
        }
        
        return windows
    
    def parse_asana_date(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Парсит дату из Asana (может быть в разных форматах)
        
        Args:
            date_str: Дата в формате ISO 8601 или другом
            
        Returns:
            datetime объект или None
        """
        if not date_str:
            return None
        
        # Пробуем разные форматы
        formats = [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S%z",
            "%Y-%m-%d",
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str[:19], fmt)
            except ValueError:
                continue
        
        return None
    
    def task_in_window(
        self,
        asana_task: Dict[str, Any],
        window: Dict[str, str],
        use_created_at: bool = True,
        use_modified_at: bool = True
    ) -> bool:
        """
        Проверяет, попадает ли задача Asana в указанное временное окно
        
        Args:
            asana_task: Задача из Asana
            window: Окно {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
            use_created_at: Использовать дату создания
            use_modified_at: Использовать дату изменения
            
        Returns:
            True если задача попадает в окно
        """
        window_from = datetime.strptime(window["from"], "%Y-%m-%d")
        window_to = datetime.strptime(window["to"], "%Y-%m-%d")
        
        # Проверяем дату создания
        if use_created_at:
            created_at = self.parse_asana_date(asana_task.get("created_at"))
            if created_at:
                # Нормализуем до даты (без времени)
                created_date = created_at.replace(hour=0, minute=0, second=0, microsecond=0)
                if window_from <= created_date <= window_to:
                    return True
        
        # Проверяем дату изменения
        if use_modified_at:
            modified_at = self.parse_asana_date(asana_task.get("modified_at"))
            if modified_at:
                # Нормализуем до даты (без времени)
                modified_date = modified_at.replace(hour=0, minute=0, second=0, microsecond=0)
                if window_from <= modified_date <= window_to:
                    return True
        
        return False
    
    def filter_tasks_by_window(
        self,
        asana_tasks: List[Dict[str, Any]],
        window: Dict[str, str],
        window_name: str = "unknown"
    ) -> List[Dict[str, Any]]:
        """
        Фильтрует задачи Asana по временному окну
        
        Args:
            asana_tasks: Список задач из Asana
            window: Окно {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD"}
            window_name: Название окна для логирования
            
        Returns:
            Отфильтрованный список задач
        """
        filtered = []
        for task in asana_tasks:
            if self.task_in_window(task, window):
                # Добавляем метку окна для отладки
                task_copy = task.copy()
                task_copy["_time_window_match"] = window_name
                filtered.append(task_copy)
        
        return filtered
    
    def prioritize_tasks_by_windows(
        self,
        telegram_task: Dict[str, Any],
        asana_tasks: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Приоритизирует задачи Asana по временным окнам для Telegram задачи
        
        Args:
            telegram_task: Задача из Telegram
            asana_tasks: Все задачи из Asana
            
        Returns:
            Словарь с задачами по окнам:
            {
                "primary": [...],
                "extended": [...],
                "distant": [...]
            }
        """
        # Извлекаем даты из контекста
        context = telegram_task.get("context", "")
        dates = self.extract_dates_from_context(context)
        
        # Вычисляем временные окна
        first_date = dates[0] if dates else None
        windows = self.calculate_time_windows(first_date=first_date, dates=dates)
        
        # Фильтруем задачи по окнам
        result = {
            "primary": self.filter_tasks_by_window(asana_tasks, windows["primary"], "primary"),
            "extended": self.filter_tasks_by_window(asana_tasks, windows["extended"], "extended"),
            "distant": self.filter_tasks_by_window(asana_tasks, windows["distant"], "distant")
        }
        
        # Убираем дубликаты (задача может попасть в несколько окон)
        # Приоритет: primary > extended > distant
        seen_gids = set()
        for window_name in ["primary", "extended", "distant"]:
            filtered = []
            for task in result[window_name]:
                gid = task.get("gid")
                if gid and gid not in seen_gids:
                    seen_gids.add(gid)
                    filtered.append(task)
                elif not gid:
                    # Если нет GID, все равно добавляем (может быть тестовая задача)
                    filtered.append(task)
            result[window_name] = filtered
        
        return result

