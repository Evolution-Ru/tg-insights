#!/usr/bin/env python3
"""
Скрипт для синхронизации задач Telegram ↔ Asana
Использует MCP сервер для работы с Asana API
"""
import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent.parent  # scripts -> sync -> analysis -> scripts -> tg-analyz
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.sync.core.asana_sync import AsanaSync

# Импортируем простой клиент для прямых вызовов MCP
try:
    from scripts.analysis.sync.api.direct_mcp import create_direct_mcp_client
except ImportError:
    create_direct_mcp_client = None


# Конфигурация
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
ASANA_WORKSPACE_GID = "624391999090674"


def load_stories_for_task(mcp_client, task_gid: str) -> List[str]:
    """
    Загрузить комментарии (stories) для задачи Asana
    
    Args:
        mcp_client: MCP клиент для работы с Asana
        task_gid: GID задачи
        
    Returns:
        Список текстов комментариев
    """
    try:
        result = mcp_client.call_tool(
            "mcp_mcp-config-el8wcq_ASANA_GET_STORIES_FOR_TASK",
            {
                "task_gid": task_gid,
                "opt_fields": ["text", "created_at", "created_by.name"]
            }
        )
        
        successful = result.get('successful') or result.get('successfull', False)
        if result and successful:
            stories = result.get('data', {}).get('data', [])
            # Извлекаем только текстовые комментарии (не системные события)
            comments = []
            for story in stories:
                text = story.get('text', '').strip()
                if text:  # Только текстовые комментарии
                    created_by = story.get('created_by', {}).get('name', 'Неизвестно')
                    created_at = story.get('created_at', '')
                    # Форматируем комментарий с автором и датой
                    comment = f"[{created_by}, {created_at}] {text}"
                    comments.append(comment)
            return comments
        return []
    except Exception as e:
        # Если не удалось загрузить stories, возвращаем пустой список
        # Не прерываем выполнение из-за ошибки загрузки комментариев
        return []


def load_asana_tasks_via_mcp(mcp_client, include_stories: bool = True) -> List[Dict[str, Any]]:
    """
    Загрузить задачи из проекта Asana через MCP
    
    Args:
        mcp_client: MCP клиент для работы с Asana
        include_stories: Загружать ли комментарии (stories) для задач
        
    Returns:
        Список задач из Asana с добавленными комментариями в поле 'stories'
    """
    try:
        # Используем MCP инструмент для получения задач проекта
        result = mcp_client.call_tool(
            "mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT",
            {
                "project_gid": ASANA_PROJECT_GID,
                "limit": 100,
                "opt_fields": [
                    "name", "notes", "assignee", "assignee.name",
                    "completed", "due_on", "custom_fields",
                    "created_at", "modified_at", "gid"
                ]
            }
        )
        
        # Обрабатываем ответ Composio (может быть "successfull" или "successful")
        successful = result.get('successful') or result.get('successfull', False)
        
        if result and successful:
            tasks = result.get('data', {}).get('data', [])
            
            # Загружаем комментарии для каждой задачи (если включено)
            if include_stories:
                print(f"   📝 Загрузка комментариев для {len(tasks)} задач...")
                for i, task in enumerate(tasks):
                    task_gid = task.get('gid')
                    if task_gid:
                        stories = load_stories_for_task(mcp_client, task_gid)
                        if stories:
                            # Добавляем комментарии в задачу
                            task['stories'] = stories
                            # Объединяем комментарии с notes для удобства использования
                            notes = task.get('notes', '') or ''
                            if notes:
                                notes += '\n\n--- Комментарии ---\n'
                            else:
                                notes = '--- Комментарии ---\n'
                            notes += '\n'.join(stories)
                            task['notes'] = notes
                        
                        # Показываем прогресс каждые 10 задач
                        if (i + 1) % 10 == 0:
                            print(f"      Загружено комментариев для {i + 1}/{len(tasks)} задач...", end='\r')
                
                print(f"      ✅ Загружены комментарии для всех задач")
            
            return tasks
        else:
            error = result.get('error', 'Unknown error') if result else 'No response'
            print(f"⚠️  Ошибка загрузки задач из Asana: {error}")
            return []
    except Exception as e:
        print(f"❌ Исключение при загрузке задач из Asana: {e}")
        return []


def update_asana_task_via_mcp(mcp_client, task_gid: str, updates: Dict[str, Any]) -> bool:
    """
    Обновить задачу в Asana через MCP
    
    Args:
        mcp_client: MCP клиент
        task_gid: GID задачи в Asana
        updates: Словарь с обновлениями
        
    Returns:
        True если успешно, False иначе
    """
    try:
        result = mcp_client.call_tool(
            "mcp_mcp-config-el8wcq_ASANA_UPDATE_A_TASK",
            {
                "task_gid": task_gid,
                "data": updates
            }
        )
        # Обрабатываем ответ Composio (может быть "successfull" или "successful")
        if not result:
            return False
        return result.get('successful') or result.get('successfull', False)
    except Exception as e:
        print(f"❌ Ошибка обновления задачи {task_gid}: {e}")
        return False


def create_asana_task_via_mcp(mcp_client, task_data: Dict[str, Any]) -> Optional[str]:
    """
    Создать задачу в Asana через MCP
    
    Args:
        mcp_client: MCP клиент
        task_data: Данные для создания задачи
        
    Returns:
        GID созданной задачи или None
    """
    try:
        result = mcp_client.call_tool(
            "mcp_mcp-config-el8wcq_ASANA_CREATE_A_TASK",
            {
                "data": task_data
            }
        )
        
        # Обрабатываем ответ Composio (может быть "successfull" или "successful")
        successful = result and (result.get('successful') or result.get('successfull', False))
        
        if successful:
            task = result.get('data', {}).get('data', {})
            return task.get('gid')
        else:
            error = result.get('error', 'Unknown error') if result else 'No response'
            print(f"⚠️  Ошибка создания задачи: {error}")
            return None
    except Exception as e:
        print(f"❌ Ошибка создания задачи: {e}")
        return None


def sync_telegram_to_asana(
    telegram_tasks_file: Path,
    mcp_client=None,
    dry_run: bool = True,
    include_stories: bool = True
) -> Dict[str, Any]:
    """
    Выполнить синхронизацию задач Telegram → Asana
    
    Args:
        telegram_tasks_file: Путь к файлу с задачами из Telegram
        mcp_client: MCP клиент для работы с Asana (опционально)
        dry_run: Если True, только анализирует, не создает/не обновляет
        include_stories: Загружать ли комментарии (stories) для задач Asana
        
    Returns:
        Отчет о синхронизации
    """
    # Инициализируем синхронизатор с новой архитектурой V2
    sync = AsanaSync(
        use_time_windows=True,      # Использовать временные окна для фильтрации
        use_embedding_cache=True    # Использовать кеш эмбеддингов
    )
    
    print("📥 Загрузка задач из Telegram...")
    telegram_tasks = sync.load_telegram_tasks(telegram_tasks_file)
    print(f"   ✓ Загружено {len(telegram_tasks)} задач")
    
    asana_tasks = []
    if mcp_client:
        print("\n📥 Загрузка задач из Asana...")
        asana_tasks = load_asana_tasks_via_mcp(mcp_client, include_stories=include_stories)
        print(f"   ✓ Загружено {len(asana_tasks)} задач")
    else:
        print("\n⚠️  MCP клиент не предоставлен, пропускаем загрузку из Asana")
        print("   Для полной синхронизации используйте MCP клиент")
    
    if not asana_tasks:
        print("\n📊 Анализ структуры задач из Telegram...")
        # Генерируем структурированный отчет только по Telegram
        structure = {
            'total_tasks': len(telegram_tasks),
            'by_status': {},
            'by_assignee': {},
            'open_tasks': [],
            'completed_tasks': []
        }
        
        for task in telegram_tasks:
            status = task.get('status', 'неизвестно')
            assignee = task.get('assignee', 'не назначен')
            
            structure['by_status'][status] = structure['by_status'].get(status, 0) + 1
            structure['by_assignee'][assignee] = structure['by_assignee'].get(assignee, 0) + 1
            
            if status == 'не выполнено':
                structure['open_tasks'].append({
                    'title': task.get('title'),
                    'assignee': assignee,
                    'description': task.get('description', '')[:200]
                })
            elif status == 'выполнено':
                structure['completed_tasks'].append({
                    'title': task.get('title'),
                    'assignee': assignee
                })
        
        return {
            'mode': 'telegram_only',
            'structure': structure,
            'telegram_tasks': telegram_tasks
        }
    
    # Сопоставление задач через новую архитектуру V2
    print("\n🔍 Сопоставление задач (V2: временные окна + кеш эмбеддингов)...")
    matching = sync.find_matching_tasks_v2(
        telegram_tasks, 
        asana_tasks,
        similarity_threshold=0.75,
        verbose=True,
        use_embeddings=True,
        use_gpt5_verification=False,  # GPT-5 только для потенциальных совпадений
        low_threshold=0.65,
        use_two_stage_matching=True
    )
    
    print(f"   ✓ Найдено совпадений: {len(matching['matches'])}")
    print(f"   ✓ Только в Telegram: {len(matching['telegram_only'])}")
    print(f"   ✓ Только в Asana: {len(matching['asana_only'])}")
    
    # Генерация отчета
    sync_dir = telegram_tasks_file.parent.parent / "sync"
    sync_dir.mkdir(parents=True, exist_ok=True)
    
    report_file = sync_dir / "sync_report.json"
    report = sync.generate_sync_report(matching, report_file)
    
    print(f"\n💾 Отчет сохранен: {report_file}")
    
    # Выполнение синхронизации (если не dry_run)
    if not dry_run and mcp_client:
        print("\n🔄 Выполнение синхронизации...")
        
        # Обновление существующих задач
        updated_count = 0
        for tg_task, asana_task, score in matching['matches']:
            updates = sync.enrich_asana_task_with_telegram(asana_task, tg_task)
            if updates:
                if update_asana_task_via_mcp(mcp_client, asana_task['gid'], updates):
                    updated_count += 1
                    print(f"   ✓ Обновлена задача: {asana_task.get('name', '')[:50]}")
        
        print(f"   ✓ Обновлено задач: {updated_count}")
        
        # Создание новых задач
        created_count = 0
        for tg_task in matching['telegram_only']:
            task_data = sync.create_asana_task_from_telegram(tg_task)
            task_gid = create_asana_task_via_mcp(mcp_client, task_data)
            if task_gid:
                created_count += 1
                print(f"   ✓ Создана задача: {tg_task.get('title', '')[:50]}")
        
        print(f"   ✓ Создано задач: {created_count}")
    elif dry_run:
        print("\n⚠️  Режим dry_run: изменения не применены")
        print("   Для применения изменений запустите с dry_run=False")
    
    return report


def main():
    """Основная функция"""
    project_root = Path(__file__).resolve().parent.parent.parent
    results_dir = project_root / "results" / "farma" / "extracted"
    telegram_tasks_file = results_dir / "farma_tasks_extracted.json"
    
    if not telegram_tasks_file.exists():
        print(f"❌ Файл не найден: {telegram_tasks_file}")
        return
    
    # Создаем MCP клиент для прямых вызовов через Cursor
    # В контексте Cursor MCP инструменты доступны напрямую через функции типа:
    # mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT()
    mcp_client = None
    
    # Пробуем создать простой клиент
    if create_direct_mcp_client:
        # В контексте Cursor можно использовать прямые вызовы MCP инструментов
        # Клиент нужен только для единообразного интерфейса
        mcp_client = create_direct_mcp_client()
    
    print("🚀 Синхронизация Telegram ↔ Asana")
    print("=" * 60)
    
    report = sync_telegram_to_asana(
        telegram_tasks_file,
        mcp_client=mcp_client,
        dry_run=True  # По умолчанию только анализ
    )
    
    print("\n" + "=" * 60)
    print("✅ Синхронизация завершена")
    
    if 'summary' in report:
        print(f"\n📊 Итоги:")
        print(f"   Совпадений: {report['summary']['matched_tasks']}")
        print(f"   Только в Telegram: {report['summary']['telegram_only']}")
        print(f"   Только в Asana: {report['summary']['asana_only']}")


if __name__ == "__main__":
    main()

