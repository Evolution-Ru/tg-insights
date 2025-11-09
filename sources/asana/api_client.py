"""
API клиент для работы с Asana через MCP
"""
from typing import Dict, List, Any, Optional, Callable


class AsanaAPIClient:
    """
    Клиент для работы с Asana API через MCP инструменты.
    
    Используется в контексте Cursor, где доступны MCP инструменты напрямую.
    """
    
    def __init__(self, mcp_tool_call: Optional[Callable] = None):
        """
        Инициализация клиента
        
        Args:
            mcp_tool_call: Функция для вызова MCP инструментов (опционально, для тестирования)
        """
        self.mcp_tool_call = mcp_tool_call
    
    def _call_mcp_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Вызов MCP инструмента
        
        Args:
            tool_name: Имя MCP инструмента
            params: Параметры для вызова
            
        Returns:
            Результат вызова
        """
        if self.mcp_tool_call:
            return self.mcp_tool_call(tool_name, params)
        
        # В контексте Cursor вызываем напрямую через глобальные функции
        # Это будет работать только в Cursor
        raise NotImplementedError(
            "MCP инструменты доступны только в контексте Cursor. "
            "Используйте mcp_tool_call для тестирования."
        )
    
    def get_tasks_from_project(
        self,
        project_gid: str,
        limit: int = 100,
        opt_fields: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Загрузить задачи из проекта Asana
        
        Args:
            project_gid: GID проекта в Asana
            limit: Максимальное количество задач
            opt_fields: Дополнительные поля для загрузки
            
        Returns:
            Список задач из Asana
        """
        if opt_fields is None:
            opt_fields = [
                "name", "notes", "assignee", "assignee.name",
                "completed", "due_on", "custom_fields",
                "created_at", "modified_at", "gid"
            ]
        
        result = self._call_mcp_tool(
            "mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT",
            {
                "project_gid": project_gid,
                "limit": limit,
                "opt_fields": opt_fields
            }
        )
        
        successful = result.get('successful') or result.get('successfull', False)
        
        if result and successful:
            data = result.get('data', {})
            if isinstance(data, dict):
                tasks = data.get('data', [])
            else:
                tasks = data if isinstance(data, list) else []
            return tasks
        
        return []
    
    def get_stories_for_task(self, task_gid: str) -> List[str]:
        """
        Загрузить комментарии (stories) для задачи
        
        Args:
            task_gid: GID задачи в Asana
            
        Returns:
            Список текстов комментариев
        """
        result = self._call_mcp_tool(
            "mcp_mcp-config-el8wcq_ASANA_GET_STORIES_FOR_TASK",
            {
                "task_gid": task_gid,
                "opt_fields": ["text", "created_at", "created_by"]
            }
        )
        
        successful = result.get('successful') or result.get('successfull', False)
        
        if result and successful:
            data = result.get('data', {})
            if isinstance(data, dict):
                stories = data.get('data', [])
            else:
                stories = data if isinstance(data, list) else []
            
            # Извлекаем тексты комментариев
            texts = []
            for story in stories:
                if isinstance(story, dict):
                    text = story.get('text', '')
                    if text:
                        texts.append(text)
                elif hasattr(story, 'text'):
                    texts.append(story.text)
            
            return texts
        
        return []
    
    def create_task(self, task_data: Dict[str, Any]) -> Optional[str]:
        """
        Создать задачу в Asana
        
        Args:
            task_data: Данные для создания задачи
            
        Returns:
            GID созданной задачи или None
        """
        result = self._call_mcp_tool(
            "mcp_mcp-config-el8wcq_ASANA_CREATE_A_TASK",
            {"data": task_data}
        )
        
        successful = result.get('successful') or result.get('successfull', False)
        
        if result and successful:
            data = result.get('data', {})
            if isinstance(data, dict):
                task = data.get('data', {})
                if isinstance(task, dict):
                    return task.get('gid')
        
        return None
    
    def update_task(self, task_gid: str, updates: Dict[str, Any]) -> bool:
        """
        Обновить задачу в Asana
        
        Args:
            task_gid: GID задачи в Asana
            updates: Словарь с обновлениями
            
        Returns:
            True если успешно, False иначе
        """
        result = self._call_mcp_tool(
            "mcp_mcp-config-el8wcq_ASANA_UPDATE_A_TASK",
            {
                "task_gid": task_gid,
                "data": updates
            }
        )
        
        return result.get('successful') or result.get('successfull', False)

