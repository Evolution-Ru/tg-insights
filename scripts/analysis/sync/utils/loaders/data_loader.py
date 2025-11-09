#!/usr/bin/env python3
"""
Модуль для загрузки данных из файлов
"""
import json
from pathlib import Path
from typing import Dict, List, Any


def load_telegram_tasks(tasks_file: Path) -> List[Dict[str, Any]]:
    """
    Загрузить задачи из Telegram анализа
    
    Args:
        tasks_file: Путь к файлу с задачами
        
    Returns:
        Список задач из Telegram
    """
    with open(tasks_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Если данные - список, возвращаем его напрямую
    if isinstance(data, list):
        return data
    
    # Если данные - словарь, ищем ключ 'unique_tasks'
    if isinstance(data, dict):
        return data.get('unique_tasks', [])
    
    # Если формат неизвестен, возвращаем пустой список
    return []


def load_telegram_projects(projects_file: Path) -> List[Dict[str, Any]]:
    """
    Загрузить проекты из Telegram анализа
    
    Args:
        projects_file: Путь к файлу с проектами
        
    Returns:
        Список проектов из Telegram
    """
    with open(projects_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('projects', [])

