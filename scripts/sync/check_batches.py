#!/usr/bin/env python3
"""
Проверка статусов батчей OpenAI и обработка завершенных батчей для суммаризации Asana задач
"""
import sys
import json
import time
import hashlib
from pathlib import Path

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent  # scripts -> ai-pmtool
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.ai.gpt5_client import get_openai_client
from pipeline.asana.summarization.summarizer import AsanaTaskSummarizer


def check_and_process_batches(verbose: bool = True):
    """Проверяет статусы батчей и обрабатывает завершенные"""
    client = get_openai_client()
    
    if verbose:
        print("🔍 Проверка статусов батчей OpenAI...\n")
    
    try:
        # Получаем список батчей (последние 20)
        batches = client.batches.list(limit=20)
        
        if verbose:
            print(f"Найдено батчей: {len(batches.data)}\n")
        
        active_batches = []
        completed_batches = []
        
        for batch in batches.data:
            batch_id = batch.id
            status = batch.status
            
            if verbose:
                print(f"Batch ID: {batch_id}")
                print(f"  Статус: {status}")
                print(f"  Создан: {batch.created_at}")
                if hasattr(batch, 'completed_at') and batch.completed_at:
                    print(f"  Завершен: {batch.completed_at}")
                if hasattr(batch, 'request_counts'):
                    print(f"  Запросов: {batch.request_counts}")
                print()
            
            # Собираем активные батчи
            if status in ["validating", "in_progress"]:
                active_batches.append(batch_id)
                if verbose:
                    print(f"  ⏳ Активный батч - ожидание завершения...")
            
            # Собираем завершенные батчи
            elif status == "completed":
                completed_batches.append(batch_id)
                if verbose:
                    print(f"  ✅ Завершенный батч")
        
        # Обрабатываем активные батчи
        if active_batches:
            if verbose:
                print(f"\n⏳ Найдено {len(active_batches)} активных батчей. Ожидание завершения...\n")
            
            for batch_id in active_batches:
                wait_for_batch_completion(client, batch_id, verbose=verbose)
        
        # Обрабатываем завершенные батчи
        if completed_batches:
            if verbose:
                print(f"\n📥 Найдено {len(completed_batches)} завершенных батчей. Проверка результатов...\n")
            
            for batch_id in completed_batches:
                process_completed_batch(client, batch_id, verbose=verbose)
        
        if not active_batches and not completed_batches:
            if verbose:
                print("✅ Нет активных или завершенных батчей для обработки")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке батчей: {e}")
        import traceback
        traceback.print_exc()


def wait_for_batch_completion(client, batch_id: str, max_wait_time: int = 3600, verbose: bool = True):
    """Ожидает завершения батча"""
    start_time = time.time()
    poll_interval = 10  # Проверяем каждые 10 секунд
    
    if verbose:
        print(f"⏳ Ожидание завершения батча {batch_id}...")
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_time:
            if verbose:
                print(f"  ⚠️  Батч не завершился за {max_wait_time} секунд")
            return False
        
        try:
            batch_status = client.batches.retrieve(batch_id)
            status = batch_status.status
            
            if status == "completed":
                if verbose:
                    print(f"  ✅ Батч завершен!")
                process_completed_batch(client, batch_id, verbose=verbose)
                return True
            elif status == "failed":
                if verbose:
                    print(f"  ❌ Батч завершился с ошибкой")
                return False
            elif status in ["cancelled", "expired"]:
                if verbose:
                    print(f"  ⚠️  Батч был отменен или истек: {status}")
                return False
            
            if verbose:
                print(f"  → Статус: {status} (прошло {elapsed:.0f} сек)...", end='\r', flush=True)
            
            time.sleep(poll_interval)
        
        except Exception as e:
            if verbose:
                print(f"  ⚠️  Ошибка при проверке статуса: {e}")
            time.sleep(poll_interval)


def process_completed_batch(client, batch_id: str, verbose: bool = True):
    """Обрабатывает завершенный батч и сохраняет результаты в кеш"""
    try:
        batch_detail = client.batches.retrieve(batch_id)
        
        if not hasattr(batch_detail, 'output_file_id') or not batch_detail.output_file_id:
            if verbose:
                print(f"  ⚠️  Батч {batch_id} завершен, но нет output_file_id")
            return
        
        output_file_id = batch_detail.output_file_id
        
        if verbose:
            print(f"  📥 Скачивание результатов батча {batch_id}...")
        
        # Скачиваем результаты
        output_file = client.files.content(output_file_id)
        output_content = output_file.read().decode('utf-8')
        
        # Парсим результаты
        results_count = 0
        asana_tasks_count = 0
        processed_count = 0
        
        summarizer = AsanaTaskSummarizer()
        
        for line in output_content.strip().split('\n'):
            if not line:
                continue
            
            try:
                result_data = json.loads(line)
                custom_id = result_data.get('custom_id', '')
                
                results_count += 1
                
                if custom_id.startswith('asana_task_'):
                    asana_tasks_count += 1
                    
                    # Обрабатываем результат Asana задачи
                    task_gid = custom_id.replace('asana_task_', '')
                    
                    # Извлекаем суммаризированный текст из ответа
                    response_body = result_data.get('response', {}).get('body', {})
                    summary_text = ""
                    
                    # Парсим ответ responses API
                    if 'output_text' in response_body:
                        summary_text = response_body['output_text']
                    elif 'output' in response_body:
                        output = response_body['output']
                        if isinstance(output, str):
                            summary_text = output
                        elif isinstance(output, list):
                            chunks = []
                            for item in output:
                                if isinstance(item, dict):
                                    if 'text' in item:
                                        chunks.append(item['text'])
                                    elif 'content' in item:
                                        for c in item.get('content', []):
                                            if isinstance(c, dict) and 'text' in c:
                                                chunks.append(c['text'])
                                elif hasattr(item, 'text'):
                                    chunks.append(item.text)
                            summary_text = '\n'.join(chunks)
                    
                    if summary_text:
                        # Находим задачу в кеше по task_gid и обновляем summary
                        # Ищем все записи с этим task_gid
                        updated = False
                        for cache_key, cache_value in list(summarizer.summary_cache.items()):
                            if cache_value.get('task_gid') == task_gid:
                                # Обновляем summary
                                cache_value['summary'] = summary_text.strip()
                                cache_value['created_at'] = time.time()
                                cache_value['created_at_iso'] = time.strftime('%Y-%m-%dT%H:%M:%S')
                                updated = True
                                processed_count += 1
                                break
                        
                        # Если задача не найдена в кеше, создаем новую запись
                        # Используем временный hash, так как у нас нет исходной задачи
                        if not updated:
                            # Создаем временный hash на основе task_gid и текущего времени
                            temp_hash = hashlib.sha256(f"{task_gid}_{time.time()}".encode()).hexdigest()
                            cache_key = f"{task_gid}_{temp_hash}"
                            summarizer.summary_cache[cache_key] = {
                                'task_gid': task_gid,
                                'task_hash': temp_hash,
                                'summary': summary_text.strip(),
                                'created_at': time.time(),
                                'created_at_iso': time.strftime('%Y-%m-%dT%H:%M:%S')
                            }
                            processed_count += 1
                            if verbose:
                                print(f"  ✓ Добавлена новая задача {task_gid} в кеш")
                    elif 'error' in result_data.get('response', {}):
                        error_info = result_data['response']['error']
                        if verbose:
                            print(f"  ⚠️  Ошибка для {task_gid}: {error_info}")
            
            except Exception as e:
                if verbose:
                    print(f"  ⚠️  Ошибка парсинга строки: {e}")
                continue
        
        # Сохраняем кеш если были обновления
        if processed_count > 0:
            summarizer._save_summary_cache()
            if verbose:
                print(f"  💾 Кеш обновлен ({processed_count} задач)")
        
        if verbose:
            print(f"  ✅ Обработано результатов: {results_count} (из них Asana задач: {asana_tasks_count}, обновлено в кеше: {processed_count})")
        
    except Exception as e:
        if verbose:
            print(f"  ❌ Ошибка при обработке батча {batch_id}: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Проверка статусов батчей OpenAI")
    parser.add_argument("--verbose", "-v", action="store_true", default=True, help="Подробный вывод")
    parser.add_argument("--wait", "-w", action="store_true", help="Ожидать завершения активных батчей")
    
    args = parser.parse_args()
    
    check_and_process_batches(verbose=args.verbose)

