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
_project_root = _script_dir.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.sync.asana_sync import AsanaSync


# Конфигурация
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
ASANA_WORKSPACE_GID = "624391999090674"


def load_asana_tasks_via_mcp(mcp_client) -> List[Dict[str, Any]]:
    """
    Загрузить задачи из проекта Asana через MCP
    
    Args:
        mcp_client: MCP клиент для работы с Asana
        
    Returns:
        Список задач из Asana
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
                    "created_at", "modified_at"
                ]
            }
        )
        
        if result and result.get('successful'):
            return result.get('data', {}).get('data', [])
        else:
            print(f"⚠️  Ошибка загрузки задач из Asana: {result.get('error', 'Unknown error')}")
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
        return result and result.get('successful', False)
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
        
        if result and result.get('successful'):
            task = result.get('data', {}).get('data', {})
            return task.get('gid')
        else:
            print(f"⚠️  Ошибка создания задачи: {result.get('error', 'Unknown error')}")
            return None
    except Exception as e:
        print(f"❌ Ошибка создания задачи: {e}")
        return None


def sync_telegram_to_asana(
    telegram_tasks_file: Path,
    mcp_client=None,
    dry_run: bool = True
) -> Dict[str, Any]:
    """
    Выполнить синхронизацию задач Telegram → Asana
    
    Args:
        telegram_tasks_file: Путь к файлу с задачами из Telegram
        mcp_client: MCP клиент для работы с Asana (опционально)
        dry_run: Если True, только анализирует, не создает/не обновляет
        
    Returns:
        Отчет о синхронизации
    """
    sync = AsanaSync()
    
    print("📥 Загрузка задач из Telegram...")
    telegram_tasks = sync.load_telegram_tasks(telegram_tasks_file)
    print(f"   ✓ Загружено {len(telegram_tasks)} задач")
    
    asana_tasks = []
    if mcp_client:
        print("\n📥 Загрузка задач из Asana...")
        asana_tasks = load_asana_tasks_via_mcp(mcp_client)
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
    
    # Сопоставление задач
    print("\n🔍 Сопоставление задач...")
    matching = sync.find_matching_tasks(telegram_tasks, asana_tasks)
    
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
    
    # Проверяем наличие MCP клиента
    # В реальном использовании MCP клиент должен быть передан извне
    mcp_client = None  # TODO: получить MCP клиент
    
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

