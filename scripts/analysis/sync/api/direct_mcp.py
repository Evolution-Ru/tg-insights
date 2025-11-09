#!/usr/bin/env python3
"""
Простая интеграция с Composio MCP через прямые вызовы инструментов Cursor
В контексте Cursor MCP инструменты доступны напрямую через функции
"""
from typing import Dict, List, Any, Optional, Callable


class DirectMCPClient:
    """
    Простой клиент для прямых вызовов MCP инструментов через Cursor
    
    В Cursor MCP инструменты доступны напрямую через функции типа:
    mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT()
    
    Этот клиент просто оборачивает вызовы для единообразного интерфейса
    """
    
    def __init__(self, mcp_tool_call: Optional[Callable] = None):
        """
        Args:
            mcp_tool_call: Функция для вызова MCP инструментов
                          Если None, будет использоваться прямое обращение через globals()
        """
        self.mcp_tool_call = mcp_tool_call
        self.server_name = "mcp-config-el8wcq"
    
    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Вызвать MCP инструмент
        
        Args:
            tool_name: Полное имя инструмента (например, "mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT")
            arguments: Аргументы для инструмента
            
        Returns:
            Результат вызова в формате {'successful': bool, 'data': ...}
        """
        # Убираем префикс "mcp_mcp-config-el8wcq_" если есть
        if tool_name.startswith(f'mcp_{self.server_name}_'):
            tool_name_short = tool_name.replace(f'mcp_{self.server_name}_', '')
        else:
            tool_name_short = tool_name
        
        # Если передана функция для вызова, используем её
        if self.mcp_tool_call:
            try:
                result = self.mcp_tool_call(tool_name, arguments)
                return self._normalize_response(result)
            except Exception as e:
                return {'successful': False, 'error': str(e)}
        
        # Иначе пытаемся найти функцию в globals()
        # В контексте Cursor MCP функции доступны глобально
        try:
            import sys
            # Пробуем найти функцию в текущем модуле или глобальных переменных
            # В Cursor эти функции доступны через специальный механизм
            # Пока возвращаем инструкцию
            return {
                'successful': False,
                'error': f'Используйте прямые вызовы MCP инструментов через Cursor. Пример: mcp_{self.server_name}_{tool_name_short}(**arguments)'
            }
        except Exception as e:
            return {'successful': False, 'error': str(e)}
    
    def _normalize_response(self, response: Any) -> Dict[str, Any]:
        """
        Нормализовать ответ от MCP инструмента
        
        Args:
            response: Ответ от MCP инструмента
            
        Returns:
            Нормализованный ответ в формате {'successful': bool, 'data': ...}
        """
        if isinstance(response, dict):
            # Проверяем разные форматы ответа Composio
            if 'successfull' in response:  # Опечатка в API Composio
                successful = response.get('successfull', False)
                data = response.get('data', {})
                error = response.get('error')
                
                return {
                    'successful': successful,
                    'data': data,
                    'error': error
                }
            elif 'successful' in response:
                return response
            elif 'data' in response:
                return {'successful': True, 'data': response['data']}
            else:
                return {'successful': True, 'data': response}
        
        return {'successful': True, 'data': response}


def create_direct_mcp_client(mcp_tool_call: Optional[Callable] = None):
    """
    Создать клиент для прямых вызовов MCP инструментов
    
    Args:
        mcp_tool_call: Функция для вызова MCP инструментов (опционально)
        
    Returns:
        DirectMCPClient клиент
        
    Пример использования в Cursor:
        # Прямой вызов MCP инструмента
        result = mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT(
            project_gid="1210655252186716",
            limit=100
        )
        
        # Или через клиент (если нужен единообразный интерфейс)
        client = create_direct_mcp_client()
        result = client.call_tool(
            "mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT",
            {"project_gid": "1210655252186716", "limit": 100}
        )
    """
    return DirectMCPClient(mcp_tool_call)


# Функция-хелпер для загрузки задач из Asana через прямые вызовы
def load_asana_tasks_direct_call(
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
    
    Использование:
        # В Cursor вызовите напрямую:
        result = mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT(
            project_gid="1210655252186716",
            limit=100,
            opt_fields=["name", "notes", "completed"]
        )
        
        if result.get('successfull') or result.get('successful'):
            tasks = result.get('data', {}).get('data', [])
    """
    # Эта функция служит только как документация и пример
    # В реальном использовании вызывайте MCP инструмент напрямую через Cursor
    return []


# Пример использования в Cursor:
"""
# Прямой вызов MCP инструмента (рекомендуется)
result = mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT(
    project_gid="1210655252186716",
    limit=100,
    opt_fields=["name", "notes", "completed", "assignee", "due_on"]
)

# Обработка результата
if result.get('successfull') or result.get('successful'):
    tasks = result.get('data', {}).get('data', [])
    print(f"Загружено задач: {len(tasks)}")
else:
    error = result.get('error', 'Unknown error')
    print(f"Ошибка: {error}")
"""

