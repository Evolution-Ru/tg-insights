"""
Модуль извлечения задач и проектов
"""
from .tasks import extract_tasks_from_compressed_thread
from .projects import extract_projects_with_drilldown
from .grouping import find_similar_tasks, group_and_deduplicate_tasks

__all__ = [
    'extract_tasks_from_compressed_thread',
    'extract_projects_with_drilldown',
    'find_similar_tasks',
    'group_and_deduplicate_tasks',
]

