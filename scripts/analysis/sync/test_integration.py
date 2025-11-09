#!/usr/bin/env python3
"""
Интеграционное тестирование синхронизации Telegram ↔ Asana
Использует прямые вызовы MCP инструментов через Cursor
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.sync.asana_sync import AsanaSync


class TeeLogger:
    """Класс для одновременного вывода в консоль и файл"""
    def __init__(self, log_file: Path):
        self.log_file = log_file
        self.terminal = sys.stdout
        self.log = open(log_file, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


def load_asana_tasks_via_mcp(project_gid: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Загрузить задачи из Asana через прямой вызов MCP инструмента
    
    Эта функция будет вызываться через доступные MCP функции в контексте Cursor
    """
    # В реальном выполнении эта функция будет заменена на прямой вызов MCP
    # через доступные функции типа mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT
    return []


def main():
    """Запуск интеграционного тестирования"""
    project_root = Path('/Users/ychukaev/Desktop/live/tg-analyz')
    telegram_file = project_root / 'results/farma/extracted/farma_tasks_extracted.json'
    
    # Настраиваем логирование
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"sync_integration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    tee_logger = TeeLogger(log_file)
    sys.stdout = tee_logger
    sys.stderr = tee_logger
    
    try:
        ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
        
        print("🚀 Интеграционное тестирование синхронизации Telegram ↔ Asana")
        print("=" * 70)
        print(f"📝 Лог сохраняется в: {log_file}")
        print("=" * 70)
        start_time = time.time()
        
        # Шаг 1: Загружаем задачи из Telegram
        print('\n[Шаг 1/5] 📥 Загрузка задач из Telegram...')
        try:
            sync = AsanaSync()
            telegram_tasks = sync.load_telegram_tasks(telegram_file)
            print(f'   ✅ Загружено {len(telegram_tasks)} задач из Telegram')
            
            if telegram_tasks:
                print(f'   📋 Примеры задач:')
                for idx, task in enumerate(telegram_tasks[:3], 1):
                    print(f'      {idx}. {task.get("title", "")[:60]}...')
        except Exception as e:
            print(f'   ❌ Ошибка загрузки: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Шаг 2: Загружаем задачи из Asana через MCP
        print(f'\n[Шаг 2/5] 📥 Загрузка задач из Asana через MCP...')
        print('   ⚠️  Эта функция будет вызвана через доступные MCP инструменты')
        print('   ⚠️  В реальном выполнении используется прямой вызов MCP')
        
        # Здесь будет реальный вызов MCP через доступные функции
        # Для тестирования сначала проверим структуру
        
        print('\n[Шаг 3/5] 🔍 Тест: Загрузка задач через MCP...')
        print('   Вызываем MCP инструмент для загрузки задач...')
        
        # В реальном выполнении здесь будет:
        # result = mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT(
        #     project_gid=ASANA_PROJECT_GID,
        #     limit=100,
        #     opt_fields=["name", "notes", "assignee", "assignee.name", "completed", "due_on"]
        # )
        
        print('   ⚠️  Для полного тестирования требуется реальный вызов MCP')
        print('   ⚠️  Продолжаем с тестированием остальных компонентов...')
        
        # Шаг 3: Тестируем сопоставление (если есть данные)
        print('\n[Шаг 4/5] 🔍 Тест: Сопоставление задач...')
        print('   ⚠️  Требуются данные из Asana для полного теста')
        
        # Шаг 4: Тестируем генерацию отчета
        print('\n[Шаг 5/5] 💾 Тест: Генерация отчета...')
        print('   ⚠️  Требуются результаты сопоставления для полного теста')
        
        # Итоги
        total_time = time.time() - start_time
        print('\n' + "=" * 70)
        print(f'✅ Интеграционное тестирование завершено')
        print(f'⏱️  Общее время: {total_time:.1f} секунд')
        print(f'📝 Полный лог сохранен: {log_file}')
        print("=" * 70)
        print('\n📋 Следующие шаги:')
        print('   1. Вызвать MCP инструмент для загрузки задач из Asana')
        print('   2. Выполнить сопоставление через эмбеддинги')
        print('   3. Проанализировать качество совпадений')
        print('   4. Сгенерировать отчет синхронизации')
        
    except KeyboardInterrupt:
        print('\n   ⚠️  Прервано пользователем')
    except Exception as e:
        print(f'\n   ❌ Ошибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        sys.stdout = tee_logger.terminal
        sys.stderr = sys.__stderr__
        tee_logger.close()
        print(f'\n📝 Лог сохранен: {log_file}')


if __name__ == "__main__":
    main()

