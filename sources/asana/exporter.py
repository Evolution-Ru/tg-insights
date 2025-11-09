"""
Экспорт задач и проектов из Asana
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
from sources.asana.api_client import AsanaAPIClient
from sources.asana.models import AsanaTask, AsanaProject


def export_tasks_from_project(
    api_client: AsanaAPIClient,
    project_gid: str,
    include_stories: bool = True,
    limit: int = 100
) -> List[AsanaTask]:
    """
    Экспортировать задачи из проекта Asana
    
    Args:
        api_client: Клиент Asana API
        project_gid: GID проекта
        include_stories: Загружать ли комментарии для задач
        limit: Максимальное количество задач
        
    Returns:
        Список задач Asana
    """
    tasks_data = api_client.get_tasks_from_project(
        project_gid=project_gid,
        limit=limit
    )
    
    tasks = []
    for task_data in tasks_data:
        task = AsanaTask.from_dict(task_data)
        
        if include_stories:
            stories = api_client.get_stories_for_task(task.gid)
            task.stories = stories
        
        tasks.append(task)
    
    return tasks

