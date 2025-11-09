#!/usr/bin/env python3
"""
Тест новой архитектуры синхронизации V2
Проверяет работу временных окон, кеша эмбеддингов и батчинга

Использование:
    python test_v2.py [--limit-telegram N] [--limit-asana M] [--asana-file PATH]
    
    --limit-telegram N  - Ограничить количество Telegram задач (по умолчанию: 10)
    --limit-asana M     - Ограничить количество Asana задач (по умолчанию: 20)
    --asana-file PATH   - Путь к файлу с задачами Asana (опционально)
"""
import json
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent.parent  # tests -> sync -> analysis -> scripts -> tg-analyz
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.analysis.sync.core.asana_sync import AsanaSync

# Импортируем функции для работы с MCP
try:
    from scripts.analysis.sync.scripts.sync_farma import load_asana_tasks_via_mcp
    from scripts.analysis.sync.api.direct_mcp import create_direct_mcp_client
    HAS_MCP = True
except ImportError:
    HAS_MCP = False
    load_asana_tasks_via_mcp = None
    create_direct_mcp_client = None

# Конфигурация Asana
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+


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


def main():
    """Запуск теста V2 архитектуры"""
    # Парсинг аргументов командной строки
    parser = argparse.ArgumentParser(
        description='Тест архитектуры синхронизации V2',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python test_v2.py --limit-telegram 5 --limit-asana 10
  python test_v2.py --limit-telegram 3 --asana-file /path/to/asana_tasks.json
        """
    )
    parser.add_argument(
        '--limit-telegram',
        type=int,
        default=10,
        help='Ограничить количество Telegram задач для тестирования (по умолчанию: 10)'
    )
    parser.add_argument(
        '--limit-asana',
        type=int,
        default=20,
        help='Ограничить количество Asana задач для тестирования (по умолчанию: 20)'
    )
    parser.add_argument(
        '--asana-file',
        type=str,
        default=None,
        help='Путь к файлу с задачами Asana (JSON формат). Если не указан, будет попытка загрузки через MCP'
    )
    parser.add_argument(
        '--use-mcp',
        action='store_true',
        help='Использовать MCP для загрузки задач Asana (по умолчанию: автоматически, если доступно)'
    )
    
    args = parser.parse_args()
    
    # Вычисляем корень проекта (tg-analyz/)
    # test_v2.py находится в tg-analyz/scripts/analysis/sync/
    # Нужно подняться на 4 уровня вверх: sync -> analysis -> scripts -> tg-analyz
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    
    # Пути к файлам
    telegram_file = project_root / 'results/farma/extracted/farma_tasks_extracted.json'
    asana_file = Path(args.asana_file) if args.asana_file else None
    
    # Настраиваем логирование
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"test_v2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    tee_logger = TeeLogger(log_file)
    sys.stdout = tee_logger
    sys.stderr = tee_logger
    
    try:
        print("🚀 Тест архитектуры синхронизации V2")
        print("=" * 70)
        print(f"📝 Лог сохраняется в: {log_file}")
        print(f"⚙️  Параметры теста:")
        print(f"   - Telegram задач: {args.limit_telegram}")
        print(f"   - Asana задач: {args.limit_asana}")
        if asana_file:
            print(f"   - Файл Asana: {asana_file}")
        print("=" * 70)
        start_time = time.time()
        
        # Шаг 1: Инициализация с V2 параметрами
        print('\n[Шаг 1/5] 🔧 Инициализация синхронизатора V2...')
        sync = AsanaSync(
            use_time_windows=True,      # Временные окна
            use_embedding_cache=True    # Кеш эмбеддингов
        )
        print('   ✅ Синхронизатор инициализирован с V2 параметрами')
        
        # Проверяем статистику кеша
        if sync.embedding_cache:
            cache_stats = sync.embedding_cache.get_cache_stats()
            print(f'   💾 Кеш эмбеддингов: {cache_stats["local_cache_size"]} записей')
        
        # Шаг 2: Загрузка задач из Telegram
        print('\n[Шаг 2/5] 📥 Загрузка задач из Telegram...')
        if not telegram_file.exists():
            print(f'   ❌ Файл не найден: {telegram_file}')
            return
        
        all_telegram_tasks = sync.load_telegram_tasks(telegram_file)
        print(f'   📦 Всего задач в файле: {len(all_telegram_tasks)}')
        
        # Ограничиваем количество для тестирования
        telegram_tasks = all_telegram_tasks[:args.limit_telegram]
        print(f'   ✅ Загружено {len(telegram_tasks)} задач для тестирования (лимит: {args.limit_telegram})')
        
        if telegram_tasks:
            print(f'   📋 Примеры задач:')
            for idx, task in enumerate(telegram_tasks[:3], 1):
                print(f'      {idx}. {task.get("title", "")[:60]}...')
        
        # Шаг 3: Загрузка задач из Asana
        print('\n[Шаг 3/5] 📥 Загрузка задач из Asana...')
        asana_tasks = []
        all_asana_tasks = []
        
        # Приоритет 1: Загрузка через MCP (если доступно и не указан файл)
        # В Cursor MCP инструменты доступны напрямую через функции типа:
        # mcp_mcp-config-el8wcq_ASANA_GET_TASKS_FROM_A_PROJECT()
        if (args.use_mcp or not asana_file) and HAS_MCP:
            try:
                print('   🔄 Попытка загрузки через MCP...')
                
                # Пробуем использовать функцию load_asana_tasks_via_mcp из sync_farma
                # Она использует MCP клиент, который в Cursor может работать
                if load_asana_tasks_via_mcp:
                    # Создаем простой клиент-обертку для прямых вызовов MCP
                    # В Cursor MCP функции доступны глобально
                    class SimpleMCPWrapper:
                        """Простая обертка для прямых вызовов MCP в Cursor"""
                        def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
                            # В Cursor можно вызывать MCP функции напрямую
                            # Но в обычном Python это не работает
                            # Поэтому возвращаем ошибку, чтобы fallback на файл сработал
                            return {
                                'successful': False,
                                'error': 'MCP доступен только в контексте Cursor. Используйте --asana-file для тестирования вне Cursor.'
                            }
                    
                    mcp_client = SimpleMCPWrapper()
                    all_asana_tasks = load_asana_tasks_via_mcp(mcp_client)
                    
                    if all_asana_tasks:
                        print(f'   ✅ Загружено {len(all_asana_tasks)} задач через MCP')
                    else:
                        print('   ⚠️  MCP вернул пустой список или недоступен')
                        print('   💡 В обычном терминале используйте --asana-file для тестирования')
                else:
                    print('   ⚠️  MCP функции недоступны')
            except Exception as e:
                print(f'   ⚠️  Ошибка загрузки через MCP: {e}')
                print('   💡 Продолжаем с файлом, если указан')
        
        # Приоритет 2: Загрузка из файла (если MCP не сработал или указан файл)
        if not all_asana_tasks and asana_file and asana_file.exists():
            print(f'   📂 Загрузка из файла: {asana_file}')
            with open(asana_file, 'r', encoding='utf-8') as f:
                asana_data = json.load(f)
            all_asana_tasks = asana_data.get('data', {}).get('data', [])
            if all_asana_tasks:
                print(f'   📦 Всего задач в файле: {len(all_asana_tasks)}')
        
        # Ограничиваем количество для тестирования
        if all_asana_tasks:
            asana_tasks = all_asana_tasks[:args.limit_asana]
            print(f'   ✅ Используется {len(asana_tasks)} задач для тестирования (лимит: {args.limit_asana})')
        else:
            print('   ⚠️  Не удалось загрузить задачи Asana')
            print('   💡 Варианты:')
            print('      - Используйте --asana-file для загрузки из файла')
            print('      - Используйте --use-mcp для загрузки через MCP (если доступно)')
            print('      - Запустите тест без Asana задач для проверки кеша и временных окон')
        
        if not asana_tasks:
            print('   ⚠️  Нет задач Asana для сопоставления, пропускаем тест сопоставления')
            print('   💡 Тест можно запустить только с проверкой кеша и временных окон')
            return
        
        # Шаг 4: Тест сопоставления через V2
        print('\n[Шаг 4/5] 🔍 Тест сопоставления через V2 архитектуру...')
        print('   ⚡ Используются: временные окна + кеш эмбеддингов + батчинг')
        
        matching_start = time.time()
        
        try:
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
            
            matching_time = time.time() - matching_start
            print(f'\n   ✅ Сопоставление завершено за {matching_time:.1f} секунд')
            print(f'\n   📊 Результаты:')
            print(f'      ✓ Найдено совпадений: {len(matching["matches"])}')
            print(f'      ✓ Только в Telegram: {len(matching["telegram_only"])}')
            print(f'      ✓ Только в Asana: {len(matching["asana_only"])}')
            
            # Показываем примеры совпадений
            if matching['matches']:
                print(f'\n   📋 Примеры совпадений (топ-5):')
                for idx, (tg_task, asana_task, score) in enumerate(matching['matches'][:5], 1):
                    print(f'\n      {idx}. Схожесть: {score:.3f}')
                    print(f'         📱 Telegram: {tg_task.get("title", "")[:70]}')
                    print(f'         ✅ Asana: {asana_task.get("name", "")[:70]}')
            
            # Показываем статистику покрытия
            if 'coverage' in matching:
                coverage = matching['coverage']
                print(f'\n   📊 Анализ покрытия:')
                if 'coverage_percentage' in coverage:
                    print(f'      Покрытие: {coverage["coverage_percentage"]:.1f}%')
                if 'by_status' in coverage:
                    print(f'      По статусам: {coverage["by_status"]}')
        
        except KeyboardInterrupt:
            print('\n   ⚠️  Прервано пользователем')
            return
        except Exception as e:
            print(f'\n   ❌ Ошибка сопоставления: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Шаг 5: Статистика кеша
        print('\n[Шаг 5/5] 💾 Статистика использования кеша...')
        if sync.embedding_cache:
            sync.embedding_cache.print_cache_stats()
        
        # Итоги
        total_time = time.time() - start_time
        print('\n' + "=" * 70)
        print(f'✅ Тест V2 архитектуры завершен')
        print(f'⏱️  Общее время: {total_time:.1f} секунд ({total_time/60:.1f} минут)')
        print(f'📝 Полный лог сохранен: {log_file}')
        print("=" * 70)
        
    except KeyboardInterrupt:
        print('\n   ⚠️  Прервано пользователем')
    except Exception as e:
        print(f'\n   ❌ Критическая ошибка: {e}')
        import traceback
        traceback.print_exc()
    finally:
        sys.stdout = tee_logger.terminal
        sys.stderr = sys.__stderr__
        tee_logger.close()
        print(f'\n📝 Лог сохранен: {log_file}')


if __name__ == "__main__":
    main()

