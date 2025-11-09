#!/usr/bin/env python3
"""
Модуль для преобразования задач между форматами Telegram и Asana
"""
import re
from typing import Dict, Any, Optional

# Конфигурация Asana
ASANA_WORKSPACE_GID = "624391999090674"
ASANA_USER_GID = "1169547205416171"
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+


def parse_deadline(deadline_str: str) -> Optional[str]:
    """
    Парсинг дедлайна из строки в формат YYYY-MM-DD
    
    Args:
        deadline_str: Строка с дедлайном
        
    Returns:
        Дата в формате YYYY-MM-DD или None
    """
    if not deadline_str:
        return None
    
    # Если уже в формате YYYY-MM-DD
    if re.match(r'\d{4}-\d{2}-\d{2}', deadline_str):
        return deadline_str
    
    # Пытаемся распарсить другие форматы
    # Если формат не распознан, возвращаем None
    return None


def enrich_asana_task_with_telegram(
    asana_task: Dict[str, Any], 
    telegram_task: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Дополнить задачу из Asana данными из Telegram
    
    Args:
        asana_task: Задача из Asana
        telegram_task: Задача из Telegram
        
    Returns:
        Словарь с рекомендациями по обновлению задачи в Asana
    """
    updates = {}
    
    asana_notes = asana_task.get('notes', '') or ''
    tg_desc = telegram_task.get('description', '')
    tg_context = telegram_task.get('context', '')
    
    # Если в Asana нет описания или оно короче, добавляем из Telegram
    if not asana_notes or len(asana_notes) < len(tg_desc):
        updates['notes'] = f"{asana_notes}\n\n--- Контекст из Telegram ---\n{tg_desc}\n\n{tg_context}".strip()
    
    # Проверяем статус
    tg_status = telegram_task.get('status', '')
    asana_completed = asana_task.get('completed', False)
    
    if tg_status == 'выполнено' and not asana_completed:
        updates['completed'] = True
    elif tg_status == 'не выполнено' and asana_completed:
        updates['completed'] = False
    
    # Проверяем дедлайн
    tg_deadline = telegram_task.get('deadline')
    asana_due_on = asana_task.get('due_on')
    
    if tg_deadline and not asana_due_on:
        # Парсим дедлайн из Telegram (может быть в разных форматах)
        updates['due_on'] = parse_deadline(tg_deadline)
    
    # Добавляем информацию о чатах и обсуждениях
    tg_chats = telegram_task.get('chats', [])
    tg_thread = telegram_task.get('discussion_thread', '')
    
    if tg_chats or tg_thread:
        context_note = "\n\n--- Источники обсуждения ---\n"
        if tg_chats:
            context_note += f"Чаты: {', '.join(tg_chats)}\n"
        if tg_thread:
            context_note += f"Тема обсуждения: {tg_thread}\n"
        
        if 'notes' not in updates:
            updates['notes'] = asana_notes
        updates['notes'] += context_note
    
    return updates


def create_asana_task_from_telegram(
    telegram_task: Dict[str, Any],
    workspace_gid: str = ASANA_WORKSPACE_GID,
    project_gid: str = ASANA_PROJECT_GID,
    assignee_gid: str = ASANA_USER_GID
) -> Dict[str, Any]:
    """
    Подготовить данные для создания задачи в Asana из Telegram задачи
    
    Args:
        telegram_task: Задача из Telegram
        workspace_gid: GID workspace в Asana
        project_gid: GID проекта в Asana
        assignee_gid: GID исполнителя в Asana
        
    Returns:
        Словарь с данными для ASANA_CREATE_A_TASK
    """
    title = telegram_task.get('title', 'Без названия')
    description = telegram_task.get('description', '')
    context = telegram_task.get('context', '')
    
    # Формируем описание
    notes = f"{description}\n\n--- Контекст ---\n{context}"
    
    # Добавляем информацию о чатах
    chats = telegram_task.get('chats', [])
    thread = telegram_task.get('discussion_thread', '')
    
    if chats or thread:
        notes += "\n\n--- Источники ---\n"
        if chats:
            notes += f"Чаты: {', '.join(chats)}\n"
        if thread:
            notes += f"Тема: {thread}\n"
    
    task_data = {
        'name': title,
        'notes': notes,
        'assignee': assignee_gid,
        'projects': [project_gid],
        'workspace': workspace_gid
    }
    
    # Добавляем дедлайн если есть
    deadline = telegram_task.get('deadline')
    if deadline:
        parsed_deadline = parse_deadline(deadline)
        if parsed_deadline:
            task_data['due_on'] = parsed_deadline
    
    # Статус выполнения
    status = telegram_task.get('status', '')
    if status == 'выполнено':
        task_data['completed'] = True
    
    return task_data

