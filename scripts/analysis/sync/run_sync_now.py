#!/usr/bin/env python3
"""
Скрипт запуска синхронизации Telegram ↔ Asana в режиме dry_run
С подробным логированием по шагам
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
    """Запуск синхронизации"""
    project_root = Path('/Users/ychukaev/Desktop/live/tg-analyz')
    telegram_file = project_root / 'results/farma/extracted/farma_tasks_extracted.json'
    asana_file = Path('/Users/ychukaev/.cursor/projects/Users-ychukaev-Desktop-live/agent-tools/17692119-6d7d-46c8-8e20-07f32b8b33d6.txt')
    
    # Настраиваем логирование в файл
    logs_dir = project_root / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"sync_asana_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    
    # Перенаправляем вывод в файл и консоль
    tee_logger = TeeLogger(log_file)
    sys.stdout = tee_logger
    sys.stderr = tee_logger
    
    try:
        # Параметры для теста (можно ограничить количество задач)
        MAX_ASANA_TASKS = None  # None = все задачи, или укажите число для теста (например, 10)
        
        print("🚀 Синхронизация Telegram ↔ Asana (dry_run)")
        print("=" * 70)
        print(f"📝 Лог сохраняется в: {log_file}")
        print("=" * 70)
        start_time = time.time()
        
        # Шаг 1: Загружаем задачи из Telegram
        print('\n[Шаг 1/4] 📥 Загрузка задач из Telegram...')
        try:
            sync = AsanaSync()
            telegram_tasks = sync.load_telegram_tasks(telegram_file)
            print(f'   ✅ Загружено {len(telegram_tasks)} задач из Telegram')
            
            # Показываем примеры задач
            if telegram_tasks:
                print(f'   📋 Примеры задач:')
                for idx, task in enumerate(telegram_tasks[:3], 1):
                    print(f'      {idx}. {task.get("title", "")[:60]}...')
        except Exception as e:
            print(f'   ❌ Ошибка загрузки: {e}')
            return
        
        # Шаг 2: Загружаем задачи из Asana
        print(f'\n[Шаг 2/4] 📥 Загрузка задач из Asana из файла...')
        try:
            with open(asana_file, 'r', encoding='utf-8') as f:
                asana_data = json.load(f)
            
            asana_tasks = asana_data.get('data', {}).get('data', [])
            original_count = len(asana_tasks)
            
            if MAX_ASANA_TASKS:
                asana_tasks = asana_tasks[:MAX_ASANA_TASKS]
                print(f'   ✅ Загружено {len(asana_tasks)} задач из Asana (из {original_count} всего)')
                print(f'   ⚠️  Режим теста: ограничено до {MAX_ASANA_TASKS} задач')
            else:
                print(f'   ✅ Загружено {len(asana_tasks)} задач из Asana')
            
            # Показываем примеры задач
            if asana_tasks:
                print(f'   📋 Примеры задач:')
                for idx, task in enumerate(asana_tasks[:3], 1):
                    print(f'      {idx}. {task.get("name", "")[:60]}...')
        except Exception as e:
            print(f'   ❌ Ошибка загрузки: {e}')
            return
        
        # Шаг 3: Сопоставление задач
        print('\n[Шаг 3/4] 🔍 Сопоставление задач через эмбеддинги...')
        print('   ⚡ Быстрый и дешевый поиск через эмбеддинги (без GPT-5)')
        matching_start = time.time()
        
        try:
            matching = sync.find_matching_tasks(
                telegram_tasks, 
                asana_tasks, 
                similarity_threshold=0.75,  # Порог для эмбеддингов (немного выше)
                verbose=True,
                max_asana_tasks=MAX_ASANA_TASKS,
                use_embeddings=True,  # Используем эмбеддинги (дешево и быстро)
                use_gpt5_verification=False  # Без GPT-5 проверки (экономия средств)
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
                    print(f'\n      {idx}. Схожесть: {score:.2f}')
                    print(f'         📱 Telegram: {tg_task.get("title", "")[:70]}')
                    print(f'         ✅ Asana: {asana_task.get("name", "")[:70]}')
            
            # Показываем задачи только в Telegram
            if matching['telegram_only']:
                print(f'\n   📱 Задачи только в Telegram ({len(matching["telegram_only"])}):')
                for idx, tg_task in enumerate(matching['telegram_only'][:5], 1):
                    print(f'      {idx}. {tg_task.get("title", "")[:70]}')
                if len(matching['telegram_only']) > 5:
                    print(f'      ... и еще {len(matching["telegram_only"]) - 5} задач')
        except KeyboardInterrupt:
            print('\n   ⚠️  Прервано пользователем')
            return
        except Exception as e:
            print(f'\n   ❌ Ошибка сопоставления: {e}')
            import traceback
            traceback.print_exc()
            return
        
        # Шаг 4: Генерация отчета
        print('\n[Шаг 4/4] 💾 Генерация отчета...')
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
        except Exception as e:
            print(f'   ❌ Ошибка генерации отчета: {e}')
            return
        
        # Итоги
        total_time = time.time() - start_time
        print('\n' + "=" * 70)
        print(f'✅ Синхронизация завершена (dry_run режим)')
        print(f'⏱️  Общее время: {total_time:.1f} секунд ({total_time/60:.1f} минут)')
        print(f'📝 Полный лог сохранен: {log_file}')
        print("=" * 70)
    finally:
        # Восстанавливаем stdout и закрываем файл
        sys.stdout = tee_logger.terminal
        sys.stderr = sys.__stderr__
        tee_logger.close()
        print(f'\n📝 Лог сохранен: {log_file}')


if __name__ == "__main__":
    main()

