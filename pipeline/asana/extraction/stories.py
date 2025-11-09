"""
Извлечение комментариев (stories) из задач Asana
"""
from typing import List
from sources.asana.api_client import AsanaAPIClient


def extract_stories_for_task(
    api_client: AsanaAPIClient,
    task_gid: str
) -> List[str]:
    """
    Извлекает комментарии (stories) для задачи Asana
    
    Args:
        api_client: Клиент Asana API
        task_gid: GID задачи
        
    Returns:
        Список текстов комментариев
    """
    return api_client.get_stories_for_task(task_gid)

