#!/usr/bin/env python3
"""
Полное интеграционное тестирование синхронизации Telegram ↔ Asana
Использует реальные данные из MCP
"""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

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


def main():
    """Запуск полного интеграционного тестирования"""
    project_root = Path('/Users/ychukaev/Desktop/live/tg-analyz')
    telegram_file = project_root / 'results/farma/extracted/farma_tasks_extracted.json'
    asana_file = Path('/Users/ychukaev/.cursor/projects/Users-ychukaev-Desktop-live/agent-tools/cecef6cc-1bcb-4abf-b803-080f0f46035e.txt')
    
    # Настраиваем логирование
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"sync_full_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    tee_logger = TeeLogger(log_file)
    sys.stdout = tee_logger
    sys.stderr = tee_logger
    
    try:
        print("🚀 Полное интеграционное тестирование синхронизации Telegram ↔ Asana")
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
        
        # Шаг 2: Загружаем задачи из Asana
        print(f'\n[Шаг 2/5] 📥 Загрузка задач из Asana...')
        try:
            with open(asana_file, 'r', encoding='utf-8') as f:
                asana_data = json.load(f)
            
            asana_tasks = asana_data.get('data', {}).get('data', [])
            print(f'   ✅ Загружено {len(asana_tasks)} задач из Asana')
            
            if asana_tasks:
                print(f'   📋 Примеры задач:')
                for idx, task in enumerate(asana_tasks[:3], 1):
                    print(f'      {idx}. {task.get("name", "")[:60]}...')
        except Exception as e:
            print(f'   ❌ Ошибка загрузки: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Шаг 3: Сопоставление задач с двухэтапным алгоритмом
        print('\n[Шаг 3/5] 🔍 Сопоставление задач через эмбеддинги + GPT-5 проверка...')
        print('   ⚡ Двухэтапное совпадение: низкий порог (0.65) + GPT-5 проверка')
        matching_start = time.time()
        
        try:
            matching = sync.find_matching_tasks(
                telegram_tasks, 
                asana_tasks, 
                similarity_threshold=0.75,  # Порог для высокого совпадения
                verbose=True,
                use_embeddings=True,
                use_gpt5_verification=False,  # GPT-5 только для потенциальных совпадений
                low_threshold=0.65,  # Низкий порог для потенциальных совпадений
                use_two_stage_matching=True  # Включить двухэтапное совпадение
            )
            
            matching_time = time.time() - matching_start
            print(f'\n   ✅ Сопоставление завершено за {matching_time:.1f} секунд')
            print(f'\n   📊 Результаты:')
            print(f'      ✓ Найдено совпадений: {len(matching["matches"])}')
            print(f'      ✓ Только в Telegram: {len(matching["telegram_only"])}')
            print(f'      ✓ Только в Asana: {len(matching["asana_only"])}')
            
            # Показываем примеры совпадений с оценками
            if matching['matches']:
                print(f'\n   📋 Примеры совпадений (топ-10):')
                for idx, (tg_task, asana_task, score) in enumerate(matching['matches'][:10], 1):
                    print(f'\n      {idx}. Схожесть: {score:.3f}')
                    print(f'         📱 Telegram: {tg_task.get("title", "")[:70]}')
                    print(f'         ✅ Asana: {asana_task.get("name", "")[:70]}')
            
            # Показываем задачи только в Telegram
            if matching['telegram_only']:
                print(f'\n   📱 Задачи только в Telegram ({len(matching["telegram_only"])}):')
                for idx, tg_task in enumerate(matching['telegram_only'][:10], 1):
                    print(f'      {idx}. {tg_task.get("title", "")[:70]}')
                if len(matching['telegram_only']) > 10:
                    print(f'      ... и еще {len(matching["telegram_only"]) - 10} задач')
        except KeyboardInterrupt:
            print('\n   ⚠️  Прервано пользователем')
            return
        except Exception as e:
            print(f'\n   ❌ Ошибка сопоставления: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Шаг 4: Анализ покрытия и контекста
        print('\n[Шаг 4/5] 📊 Анализ покрытия и контекста...')
        try:
            # Извлекаем контекст из совпадений
            coverage_analysis = []
            for tg_task, asana_task, score in matching['matches']:
                context = sync.extract_asana_task_context(asana_task)
                coverage_analysis.append({
                    'telegram_task': tg_task.get('title', ''),
                    'asana_task': asana_task.get('name', ''),
                    'score': score,
                    'asana_context': context
                })
            
            print(f'   ✅ Проанализировано {len(coverage_analysis)} совпадений')
            
            # Показываем примеры контекста
            if coverage_analysis:
                print(f'\n   📋 Примеры контекста из Asana (топ-3):')
                for idx, item in enumerate(coverage_analysis[:3], 1):
                    print(f'\n      {idx}. Telegram: {item["telegram_task"][:50]}')
                    print(f'         Asana: {item["asana_task"][:50]}')
                    print(f'         Score: {item["score"]:.3f}')
                    context = item['asana_context']
                    if context.get('summary'):
                        print(f'         Контекст: {context["summary"][:100]}...')
        except Exception as e:
            print(f'   ⚠️  Ошибка анализа покрытия: {e}')
            import traceback
            traceback.print_exc()
        
        # Шаг 5: Генерация отчета
        print('\n[Шаг 5/5] 💾 Генерация отчета...')
        try:
            sync_dir = telegram_file.parent.parent / 'sync'
            sync_dir.mkdir(parents=True, exist_ok=True)
            report_file = sync_dir / 'sync_report.json'
            report = sync.generate_sync_report(matching, report_file)
            
            print(f'   ✅ Отчет сохранен: {report_file}')
            
            if 'summary' in report:
                print(f'\n   📊 Итоги отчета:')
                print(f'      Совпадений: {report["summary"]["matched_tasks"]}')
                print(f'      Только в Telegram: {report["summary"]["telegram_only"]}')
                print(f'      Только в Asana: {report["summary"]["asana_only"]}')
                if 'coverage_percentage' in report['summary']:
                    print(f'      Покрытие: {report["summary"]["coverage_percentage"]:.1f}%')
        except Exception as e:
            print(f'   ❌ Ошибка генерации отчета: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Итоги
        total_time = time.time() - start_time
        print('\n' + "=" * 70)
        print(f'✅ Полное интеграционное тестирование завершено')
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

