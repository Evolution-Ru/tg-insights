#!/usr/bin/env python3
"""
Анализ переписок с Фарма+ и извлечение задач
Главный скрипт - использует модульную структуру
"""
import sqlite3
import json
import sys
from pathlib import Path
from typing import Dict

# Импорты из модулей
# Добавляем корень проекта в путь для импортов
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.utils.db import get_db_connection, get_all_messages_from_chats
from scripts.analysis.utils.formatting import format_messages_as_thread
from scripts.analysis.compression import compress_thread_with_smart_model
from scripts.analysis.embeddings import save_embeddings_for_level
from scripts.analysis.extraction import (
    extract_tasks_from_compressed_thread,
    extract_projects_with_drilldown,
    group_and_deduplicate_tasks
)
from scripts.analysis.utils.gpt5_client import get_openai_client


# Конфигурация
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent  # tg-analyz/ (scripts/analysis/ -> scripts/ -> tg-analyz/)
DB_PATH = project_root / "accounts" / "ychukaev" / "messages.sqlite"

# ID чатов для анализа
CHAT_IDS = {
    "Евгений Батраев": "5684787189",
    "Никита Байкалов": "8109974557", 
    "IT farmaplus24.ru": "-1002823423591"
}

# Директории для результатов
RESULTS_DIR = project_root / "results" / "farma"
COMPRESSED_PARTS_DIR = RESULTS_DIR / "compressed_parts"
EMBEDDINGS_DIR = RESULTS_DIR / "embeddings"
EXTRACTED_DIR = RESULTS_DIR / "extracted"
THREADS_DIR = RESULTS_DIR / "threads"


def main():
    print("🚀 Начало работы скрипта...")
    print(f"📁 База данных: {DB_PATH}")
    print(f"   Существует: {DB_PATH.exists()}")
    
    if not DB_PATH.exists():
        print(f"❌ База данных не найдена!")
        return
    
    # Создаем директории для результатов
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    COMPRESSED_PARTS_DIR.mkdir(parents=True, exist_ok=True)
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    THREADS_DIR.mkdir(parents=True, exist_ok=True)
    
    print("🔌 Подключение к БД...")
    conn = get_db_connection(DB_PATH)
    conn.row_factory = sqlite3.Row
    print("✓ Подключено к БД")
    
    # Получаем клиент OpenAI
    client = get_openai_client()
    
    # ЭТАП 1: Сбор всех сообщений из чатов
    print(f"\n{'='*60}")
    print(f"📥 ЭТАП 1: Сбор всех сообщений из чатов")
    print(f"{'='*60}")
    
    all_messages = get_all_messages_from_chats(conn, CHAT_IDS, limit_messages_per_chat=500)
    
    if not all_messages:
        print("❌ Сообщения не найдены!")
        conn.close()
        return
    
    # ЭТАП 2: Форматирование единого потока
    print(f"\n{'='*60}")
    print(f"📝 ЭТАП 2: Форматирование единого потока")
    print(f"{'='*60}")
    
    thread_text = format_messages_as_thread(all_messages)
    
    # Сохраняем исходный поток
    raw_thread_file = THREADS_DIR / "farma_thread_raw.txt"
    with open(raw_thread_file, "w", encoding="utf-8") as f:
        f.write(thread_text)
    print(f"💾 Исходный поток сохранен: {raw_thread_file} ({len(thread_text)} символов)")
    
    # ЭТАП 3: Сжатие диалога до ключевых моментов
    print(f"\n{'='*60}")
    print(f"🧠 ЭТАП 3: Сжатие диалога до ключевых моментов")
    print(f"{'='*60}")
    
    compressed_text = compress_thread_with_smart_model(
        thread_text,
        max_chunk_size=10000,
        output_dir=COMPRESSED_PARTS_DIR,
        client=client
    )
    
    # Сохраняем сжатый вариант
    compressed_file = THREADS_DIR / "farma_thread_compressed.txt"
    with open(compressed_file, "w", encoding="utf-8") as f:
        f.write(compressed_text)
    print(f"💾 Сжатый поток сохранен: {compressed_file} ({len(compressed_text)} символов)")
    
    # ЭТАП 3.5: Сохранение эмбеддингов для drill-down
    print(f"\n{'='*60}")
    print(f"📊 ЭТАП 3.5: Сохранение эмбеддингов для drill-down")
    print(f"{'='*60}")
    
    print(f"\n   📊 Сохранение эмбеддингов для исходных сообщений...")
    raw_messages_for_embeddings = [
        {
            'id': msg.get('message_id', i),
            'text': f"{msg.get('sender_name', '')}: {msg.get('content', '')}",
            'metadata': {
                'message_id': msg.get('message_id'),
                'date': msg.get('date'),
                'chat_id': msg.get('chat_id'),
                'chat_name': msg.get('chat_name')
            }
        }
        for i, msg in enumerate(all_messages)
    ]
    save_embeddings_for_level('raw_messages', raw_messages_for_embeddings, COMPRESSED_PARTS_DIR, client)
    
    # Сохраняем эмбеддинги для финальной выжимки
    print(f"\n   📊 Сохранение эмбеддингов для финальной выжимки...")
    save_embeddings_for_level('summaries', [{
        'id': 'final_summary',
        'text': compressed_text,
        'metadata': {'type': 'sliding_window_summary'}
    }], COMPRESSED_PARTS_DIR, client)
    
    # ЭТАП 4: Извлечение задач с ветками обсуждений
    print(f"\n{'='*60}")
    print(f"📋 ЭТАП 4: Извлечение задач с ветками обсуждений")
    print(f"{'='*60}")
    
    tasks_result = extract_tasks_from_compressed_thread(compressed_text, client)
    all_tasks = tasks_result.get("tasks", [])
    
    # Сохраняем сырые результаты
    raw_output_file = EXTRACTED_DIR / "farma_tasks_extracted_raw.json"
    with open(raw_output_file, "w", encoding="utf-8") as f:
        json.dump(all_tasks, f, ensure_ascii=False, indent=2)
    
    print(f"\n{'='*60}")
    print(f"✅ Извлечение завершено!")
    print(f"   Всего извлечено задач: {len(all_tasks)}")
    print(f"💾 Сырые результаты сохранены в: {raw_output_file}")
    
    # Группируем и дедуплицируем задачи
    if all_tasks:
        print(f"\n{'='*60}")
        print(f"🔗 Группировка и дедупликация задач")
        print(f"{'='*60}")
        
        grouped_result = group_and_deduplicate_tasks(all_tasks, client=client)
        
        # Сохраняем группированные результаты
        grouped_output_file = EXTRACTED_DIR / "farma_tasks_extracted.json"
        with open(grouped_output_file, "w", encoding="utf-8") as f:
            json.dump(grouped_result, f, ensure_ascii=False, indent=2)
        print(f"💾 Группированные результаты сохранены: {grouped_output_file}")
        
        # Выводим статистику
        print(f"\n📊 Статистика:")
        print(f"   Всего задач: {grouped_result['total_tasks']}")
        print(f"   Уникальных задач: {len(grouped_result['unique_tasks'])}")
        print(f"   Групп дубликатов: {len(grouped_result['duplicate_groups'])}")
        
        # Сохраняем эмбеддинги для задач
        print(f"\n   📊 Сохранение эмбеддингов для задач...")
        tasks_for_embeddings = [
            {
                'id': i,
                'text': f"{task.get('title', '')} {task.get('description', '')}",
                'metadata': task
            }
            for i, task in enumerate(all_tasks)
        ]
        save_embeddings_for_level('tasks', tasks_for_embeddings, COMPRESSED_PARTS_DIR, client)
    
    # ЭТАП 5: Извлечение проектов с drill-down
    print(f"\n{'='*60}")
    print(f"📊 ЭТАП 5: Извлечение проектов с drill-down")
    print(f"{'='*60}")
    
    projects_result = extract_projects_with_drilldown(
        compressed_text,
        conn,
        COMPRESSED_PARTS_DIR,
        CHAT_IDS,
        use_drilldown=True,
        client=client
    )
    
    # Сохраняем проекты
    projects_file = EXTRACTED_DIR / "farma_projects_extracted.json"
    with open(projects_file, "w", encoding="utf-8") as f:
        json.dump(projects_result, f, ensure_ascii=False, indent=2)
    print(f"💾 Проекты сохранены: {projects_file}")
    
    # Сохраняем эмбеддинги для проектов
    projects = projects_result.get("projects", [])
    if projects:
        print(f"\n   📊 Сохранение эмбеддингов для проектов...")
        projects_for_embeddings = [
            {
                'id': i,
                'text': f"{project.get('name', '')} {project.get('description', '')}",
                'metadata': project
            }
            for i, project in enumerate(projects)
        ]
        save_embeddings_for_level('projects', projects_for_embeddings, COMPRESSED_PARTS_DIR, client)
    
    conn.close()
    print(f"\n✅ Работа завершена!")


if __name__ == "__main__":
    main()

