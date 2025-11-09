"""
Извлечение проектов из сжатых диалогов с drill-down
"""
import json
import sqlite3
from typing import Dict, Any, List
from pathlib import Path
from ..utils.gpt5_client import get_openai_client
from ..utils.response_parser import parse_gpt5_response, parse_json_response
from ..embeddings.drilldown import drill_down_to_raw_messages


def extract_projects_with_drilldown(
    final_summary: str,
    conn: sqlite3.Connection,
    output_dir: Path,
    chat_ids: Dict[str, str],
    use_drilldown: bool = True,
    client=None
) -> Dict[str, Any]:
    """
    Извлекает проекты из финальной выжимки с возможностью drill-down к исходным сообщениям.
    Использует эмбеддинги для поиска релевантных исходных сообщений.
    
    Args:
        final_summary: Финальная выжимка диалога
        conn: Подключение к базе данных
        output_dir: Директория с файлами эмбеддингов
        chat_ids: Словарь с ID чатов
        use_drilldown: Использовать ли drill-down для уточнения
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь с ключом 'projects' содержащим список проектов
    """
    if client is None:
        client = get_openai_client()
    
    print(f"\n📊 Извлечение проектов из финальной выжимки...")
    
    system_prompt = """Ты анализируешь финальную выжимку переписки по проекту Фарма+ и извлекаешь проекты и задачи.

Для каждого проекта определи:
1. Название проекта
2. Описание проекта
3. Основные задачи в проекте
4. Участники проекта
5. Статус проекта
6. Важные даты и дедлайны

Верни результат в формате JSON с полями для drill-down (нужно ли получать исходные сообщения для уточнения)."""
    
    user_prompt = f"""Проанализируй финальную выжимку и извлеки проекты:

{final_summary}

Для каждого проекта, если нужны уточнения, укажи:
- "needs_drilldown": true/false
- "drilldown_query": текст запроса для поиска исходных сообщений

Верни результат в формате JSON:
{{
  "projects": [
    {{
      "name": "Название проекта",
      "description": "Описание",
      "tasks": ["Задача 1", "Задача 2"],
      "participants": ["Участник 1", "Участник 2"],
      "status": "в работе/завершен/планируется",
      "important_dates": ["Дата 1", "Дата 2"],
      "needs_drilldown": true,
      "drilldown_query": "Текст для поиска исходных сообщений"
    }}
  ]
}}"""
    
    try:
        response = client.responses.create(
            model="gpt-5",
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            reasoning={"effort": "medium"}
        )
        
        # Парсим ответ
        response_text = parse_gpt5_response(response)
        
        if not response_text:
            raise Exception("Пустой ответ от модели")
        
        # Парсим JSON
        result = parse_json_response(response_text)
        
        if result is None:
            raise Exception("Не удалось распарсить JSON из ответа")
        
        projects = result.get("projects", [])
        
        print(f"✓ Извлечено {len(projects)} проектов")
        
        # Выполняем drill-down для проектов, которые требуют уточнения
        if use_drilldown:
            for project in projects:
                if project.get("needs_drilldown") and project.get("drilldown_query"):
                    print(f"\n   🔍 Drill-down для проекта '{project.get('name', 'Неизвестно')}'...")
                    drilldown_query = project.get("drilldown_query")
                    raw_messages = drill_down_to_raw_messages(
                        drilldown_query,
                        conn,
                        output_dir,
                        chat_ids,
                        top_k=10,
                        client=client
                    )
                    
                    if raw_messages:
                        project["raw_messages"] = raw_messages
                        project["drilldown_count"] = len(raw_messages)
                        print(f"      ✓ Найдено {len(raw_messages)} релевантных сообщений")
                    else:
                        print(f"      ⚠ Исходные сообщения не найдены")
        
        return result
        
    except Exception as e:
        print(f"❌ Ошибка при извлечении проектов: {e}")
        import traceback
        print(f"   Детали: {traceback.format_exc()[:300]}")
        return {"projects": []}

