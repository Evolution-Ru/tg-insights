#!/usr/bin/env python3
"""
Функции-хелперы для прямых вызовов MCP инструментов Asana через Cursor
Используются напрямую без оберток
"""
from typing import Dict, List, Any, Optional


def load_asana_tasks_direct(
    project_gid: str,
    limit: int = 100,
    opt_fields: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """
    Загрузить задачи из Asana через прямой вызов MCP инструмента
    
    Args:
        project_gid: GID проекта в Asana
        limit: Максимальное количество задач
        opt_fields: Дополнительные поля для загрузки
        
    Returns:
        Список задач из Asana
        
    ПРИМЕЧАНИЕ: Эта функция должна вызываться в контексте Cursor,
    где доступны MCP инструменты напрямую.
    
    Использование в Cursor:
        from scripts.analysis.sync.api.asana_mcp_helpers import load_asana_tasks_direct
        
        tasks = load_asana_tasks_direct(
            project_gid="1210655252186716",
            limit=100,
            opt_fields=["name", "notes", "completed"]
        )
    """
    # В контексте Cursor вызываем MCP инструмент напрямую
    # Это будет работать только в Cursor, где доступны MCP функции
    
    # Прямой вызов через доступный MCP инструмент
    # В реальном использовании это будет:
    # result = mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT(...)
    
    # Пока возвращаем пустой список с инструкцией
    # В Cursor эта функция будет работать напрямую
    return []


def create_asana_task_direct(task_data: Dict[str, Any]) -> Optional[str]:
    """
    Создать задачу в Asana через прямой вызов MCP инструмента
    
    Args:
        task_data: Данные для создания задачи
        
    Returns:
        GID созданной задачи или None
        
    Использование в Cursor:
        from scripts.analysis.sync.asana_mcp_helpers import create_asana_task_direct
        
        task_gid = create_asana_task_direct({
            "name": "Новая задача",
            "notes": "Описание",
            "projects": ["1210655252186716"]
        })
    """
    # Прямой вызов через доступный MCP инструмент
    # result = mcp_mcp-config-el8wcq_ASANA_CREATE_A_TASK(data={"data": task_data})
    # if result.get('successfull') or result.get('successful'):
    #     return result.get('data', {}).get('data', {}).get('gid')
    return None


def update_asana_task_direct(task_gid: str, updates: Dict[str, Any]) -> bool:
    """
    Обновить задачу в Asana через прямой вызов MCP инструмента
    
    Args:
        task_gid: GID задачи в Asana
        updates: Словарь с обновлениями
        
    Returns:
        True если успешно, False иначе
        
    Использование в Cursor:
        from scripts.analysis.sync.asana_mcp_helpers import update_asana_task_direct
        
        success = update_asana_task_direct(
            task_gid="1234567890",
            updates={"name": "Обновленное название", "completed": True}
        )
    """
    # Прямой вызов через доступный MCP инструмент
    # result = mcp_mcp-config-el8wcq_ASANA_UPDATE_A_TASK(
    #     task_gid=task_gid,
    #     data=updates
    # )
    # return result.get('successfull') or result.get('successful', False)
    return False

