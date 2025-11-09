"""
Batch обработка чанков через OpenAI Batch API
"""
import json
import time
import tempfile
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from shared.ai.gpt5_client import get_openai_client, parse_gpt5_response


def check_active_batches(metadata_file: Path, client=None) -> List[Dict]:
    """
    Проверяет наличие активных батчей (validating, in_progress).
    Возвращает список активных батчей.
    
    Args:
        metadata_file: Путь к файлу с метаданными батчей
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Список словарей с информацией об активных батчах
    """
    if client is None:
        client = get_openai_client()
    
    active_batches = []
    
    if not metadata_file.exists():
        return active_batches
    
    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            batch_metadata_list = json.load(f)
        
        # Проверяем последние 10 батчей (чтобы не проверять все старые)
        recent_batches = batch_metadata_list[-10:] if len(batch_metadata_list) > 10 else batch_metadata_list
        
        for batch_meta in recent_batches:
            batch_id = batch_meta.get("batch_id")
            if not batch_id:
                continue
            
            try:
                batch_status = client.batches.retrieve(batch_id)
                status = batch_status.status
                
                if status in ["validating", "in_progress"]:
                    active_batches.append({
                        "batch_id": batch_id,
                        "status": status,
                        "created_at": batch_meta.get("created_at_iso", "unknown"),
                        "total_chunks": batch_meta.get("total_chunks", 0)
                    })
            except Exception as e:
                # Батч может быть удален или недоступен - пропускаем
                continue
                
    except Exception as e:
        # Если не удалось прочитать файл - продолжаем без проверки
        pass
    
    return active_batches


def check_duplicate_batches(metadata_file: Path, chunk_hashes: List[str], client=None) -> Optional[Dict]:
    """
    Проверяет наличие батчей с теми же хешами чанков (дубликаты).
    Возвращает информацию о найденном дубликате или None.
    
    Args:
        metadata_file: Путь к файлу с метаданными батчей
        chunk_hashes: Список хешей чанков для проверки
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь с информацией о дубликате или None
    """
    if client is None:
        client = get_openai_client()
    
    if not metadata_file.exists():
        return None
    
    try:
        with open(metadata_file, "r", encoding="utf-8") as f:
            batch_metadata_list = json.load(f)
        
        # Проверяем последние 10 батчей
        recent_batches = batch_metadata_list[-10:] if len(batch_metadata_list) > 10 else batch_metadata_list
        
        # Создаем множество хешей для быстрого сравнения
        new_hashes_set = set(chunk_hashes)
        
        for batch_meta in reversed(recent_batches):  # Проверяем с конца (новые сначала)
            batch_id = batch_meta.get("batch_id")
            if not batch_id:
                continue
            
            # Получаем хеши из метаданных батча
            batch_chunks = batch_meta.get("chunks", [])
            batch_hashes = [chunk.get("chunk_hash") for chunk in batch_chunks if chunk.get("chunk_hash")]
            
            # Проверяем, совпадают ли хеши
            if set(batch_hashes) == new_hashes_set:
                # Проверяем статус батча через API
                try:
                    batch_status = client.batches.retrieve(batch_id)
                    status = batch_status.status
                    
                    return {
                        "batch_id": batch_id,
                        "status": status,
                        "created_at": batch_meta.get("created_at_iso", "unknown"),
                        "total_chunks": len(batch_hashes)
                    }
                except Exception:
                    # Батч может быть удален - пропускаем
                    continue
                    
    except Exception as e:
        # Если не удалось прочитать файл - продолжаем без проверки
        pass
    
    return None


def process_chunks_via_batch(
    chunks_to_process: List[Tuple[int, str, str]], 
    cache_dir: Path,
    client=None
) -> Dict[str, str]:
    """
    Обрабатывает части через Batch API для снижения стоимости.
    Используется ТОЛЬКО Batch API (без fallback на обычные запросы).
    Возвращает словарь {hash: compressed_text}
    
    Args:
        chunks_to_process: Список кортежей (index, chunk_text, chunk_hash)
        cache_dir: Директория для кеша
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь {hash: compressed_text}
    """
    if client is None:
        client = get_openai_client()
    
    # Проверяем наличие активных батчей и дубликатов перед созданием нового
    metadata_file = cache_dir.parent / "batch_metadata.json"
    
    # Извлекаем хеши чанков для проверки дубликатов
    chunk_hashes = [chunk_hash for _, _, chunk_hash in chunks_to_process]
    
    # Проверяем дубликаты по хешам
    duplicate = check_duplicate_batches(metadata_file, chunk_hashes, client)
    if duplicate:
        if duplicate["status"] == "completed":
            print(f"\n      ✅ Найден завершенный батч-дубликат: {duplicate['batch_id']}")
            print(f"      💡 Используем результаты существующего батча вместо создания нового.\n")
            # Возвращаем пустой словарь - результаты будут обработаны из существующего батча
            return {}
        else:
            print(f"\n      ⚠️  Найден активный батч-дубликат: {duplicate['batch_id']} ({duplicate['status']})")
            print(f"      💡 Дожидаемся завершения существующего батча вместо создания нового.\n")
            # Возвращаем пустой словарь - дожидаемся завершения существующего батча
            return {}
    
    # Проверяем активные батчи (для предупреждения)
    active_batches = check_active_batches(metadata_file, client)
    if active_batches:
        print(f"\n      ⚠️  Обнаружено {len(active_batches)} активных батчей:")
        for ab in active_batches:
            print(f"         - {ab['batch_id']}: {ab['status']} ({ab['total_chunks']} частей, создан {ab['created_at']})")
        print(f"      💡 Создаю новый батч, но рекомендуется дождаться завершения активных.\n")
    
    print(f"      📝 Создание JSONL файла для батча...")
    
    # Создаем временный JSONL файл
    temp_jsonl = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
    
    system_prompt = "Ты помогаешь сжимать переписки до ключевых моментов."
    
    for idx, chunk, chunk_hash in chunks_to_process:
        user_prompt = f"""Ты анализируешь переписку по проекту Фарма+. 

Сожми диалог до ключевых моментов:
- Основные темы обсуждений
- Принятые решения
- Поставленные задачи и обязательства
- Дедлайны и сроки
- Важные детали по проекту

Сохрани структуру диалога (чаты, участники, даты), но удали:
- Повторы и уточнения
- Мелкие детали
- Приветствия и прощания
- Несущественные комментарии

Верни сжатый диалог, сохраняя важный контекст для понимания задач и решений.

Исходный диалог:
{chunk}"""
        
        # Формат для responses API в Batch: input должен быть списком словарей с role/content
        request_data = {
            "custom_id": f"chunk_{idx}_{chunk_hash}",
            "method": "POST",
            "url": "/v1/responses",
            "body": {
                "model": "gpt-5",
                "input": [
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ],
                "reasoning": {"effort": "low"}
            }
        }
        
        temp_jsonl.write(json.dumps(request_data, ensure_ascii=False) + '\n')
    
    temp_jsonl.close()
    jsonl_path = Path(temp_jsonl.name)
    
    print(f"      📤 Загрузка файла в OpenAI...")
    # Загружаем файл
    with open(jsonl_path, 'rb') as f:
        uploaded_file = client.files.create(
            file=f,
            purpose="batch"
        )
    print(f"      ✓ Файл загружен: {uploaded_file.id}")
    
    # Создаем батч
    print(f"      📦 Создание батча...")
    batch = client.batches.create(
        input_file_id=uploaded_file.id,
        endpoint="/v1/responses",
        completion_window="24h"
    )
    batch_id = batch.id
    print(f"      ✓ Батч создан: {batch_id}")
    
    # Сохраняем метаданные батча
    batch_metadata = {
        "batch_id": batch_id,
        "created_at": time.time(),
        "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "chunks": [
            {
                "index": idx,
                "chunk_hash": chunk_hash,
                "custom_id": f"chunk_{idx}_{chunk_hash}",
                "chunk_size": len(chunk)
            }
            for idx, chunk, chunk_hash in chunks_to_process
        ],
        "total_chunks": len(chunks_to_process),
        "status": "created",
        "input_file_id": uploaded_file.id
    }
    
    # metadata_file уже определен выше при проверке активных батчей
    batch_metadata_list = []
    if metadata_file.exists():
        with open(metadata_file, "r", encoding="utf-8") as f:
            batch_metadata_list = json.load(f)
    
    batch_metadata_list.append(batch_metadata)
    with open(metadata_file, "w", encoding="utf-8") as f:
        json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
    
    print(f"      💾 Метаданные батча сохранены: {metadata_file}")
    print(f"      ⏳ Ожидание завершения батча (это может занять время)...")
    
    # Дожидаемся завершения батча
    max_wait_time = 3600  # Максимум 1 час
    start_time = time.time()
    poll_interval = 10  # Проверяем каждые 10 секунд
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > max_wait_time:
            raise Exception(f"Батч не завершился за {max_wait_time} секунд")
        
        batch_status = client.batches.retrieve(batch_id)
        status = batch_status.status
        
        if status == "completed":
            print(f"      ✓ Батч завершен!")
            # Обновляем метаданные батча
            batch_metadata["status"] = "completed"
            batch_metadata["completed_at"] = time.time()
            batch_metadata["completed_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
            batch_metadata["processing_time_seconds"] = elapsed
            batch_metadata["output_file_id"] = batch_status.output_file_id if hasattr(batch_status, 'output_file_id') else None
            
            # Обновляем в списке метаданных
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    batch_metadata_list = json.load(f)
                # Находим наш батч и обновляем
                for bm in batch_metadata_list:
                    if bm.get("batch_id") == batch_id:
                        bm.update(batch_metadata)
                        break
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
            break
        elif status == "failed":
            # Обновляем метаданные при ошибке
            batch_metadata["status"] = "failed"
            batch_metadata["failed_at"] = time.time()
            batch_metadata["failed_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    batch_metadata_list = json.load(f)
                for bm in batch_metadata_list:
                    if bm.get("batch_id") == batch_id:
                        bm.update(batch_metadata)
                        break
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
            raise Exception(f"Батч завершился с ошибкой: {batch_status}")
        elif status in ["cancelled", "expired"]:
            # Обновляем метаданные при отмене/истечении
            batch_metadata["status"] = status
            batch_metadata[f"{status}_at"] = time.time()
            batch_metadata[f"{status}_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if metadata_file.exists():
                with open(metadata_file, "r", encoding="utf-8") as f:
                    batch_metadata_list = json.load(f)
                for bm in batch_metadata_list:
                    if bm.get("batch_id") == batch_id:
                        bm.update(batch_metadata)
                        break
                with open(metadata_file, "w", encoding="utf-8") as f:
                    json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
            raise Exception(f"Батч был отменен или истек: {status}")
        
        print(f"      → Статус: {status} (прошло {elapsed:.0f} сек)...", flush=True)
        time.sleep(poll_interval)
    
    # Скачиваем результаты
    print(f"      📥 Скачивание результатов...")
    output_file_id = batch_status.output_file_id
    if not output_file_id:
        raise Exception("Нет output_file_id в завершенном батче")
    
    output_file = client.files.content(output_file_id)
    output_content = output_file.read().decode('utf-8')
    
    # Парсим результаты
    print(f"      🔍 Парсинг результатов...")
    results = {}
    for line in output_content.strip().split('\n'):
        if not line:
            continue
        result_data = json.loads(line)
        custom_id = result_data.get('custom_id', '')
        
        # Извлекаем compressed текст из ответа
        response_body = result_data.get('response', {}).get('body', {})
        compressed = ""
        
        # Парсим ответ responses API
        if 'output_text' in response_body:
            compressed = response_body['output_text']
        elif 'output' in response_body:
            output = response_body['output']
            if isinstance(output, str):
                compressed = output
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
                compressed = '\n'.join(chunks)
        
        if not compressed:
            # Fallback: пробуем извлечь из error или другого поля
            if 'error' in result_data.get('response', {}):
                error_info = result_data['response']['error']
                print(f"      ⚠ Ошибка для {custom_id}: {error_info}")
                continue
        
        # Извлекаем hash из custom_id
        if custom_id.startswith('chunk_'):
            parts = custom_id.split('_')
            if len(parts) >= 3:
                chunk_hash = parts[2]
                results[chunk_hash] = compressed.strip()
                
                # Сохраняем в кеш
                cache_file = cache_dir / f"{chunk_hash}.txt"
                with open(cache_file, "w", encoding="utf-8") as f:
                    f.write(compressed.strip())
                print(f"      ✓ Обработан {custom_id}: {len(compressed)} символов")
    
    print(f"      ✓ Обработано {len(results)}/{len(chunks_to_process)} частей")
    
    # Удаляем временный файл
    try:
        jsonl_path.unlink()
    except:
        pass
    
    return results


def process_chunks_via_batch_with_dates(
    chunks_to_process: List[Tuple[int, Dict, str]], 
    cache_dir: Path,
    parts_metadata_file: Path,
    client=None
) -> Dict[str, str]:
    """
    Обрабатывает части через Batch API с сохранением метаданных о датах.
    Возвращает словарь {hash: compressed_text}
    
    Args:
        chunks_to_process: Список кортежей (index, chunk_meta, hash) где chunk_meta - словарь с 'chunk', 'date_range' и т.д.
        cache_dir: Директория для кеша
        parts_metadata_file: Файл для сохранения метаданных частей
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Словарь {hash: compressed_text}
    """
    # Преобразуем в формат для process_chunks_via_batch: (idx, chunk_text, hash)
    chunks_for_batch = [(idx, meta['chunk'], chunk_hash) for idx, meta, chunk_hash in chunks_to_process]
    
    # Используем существующую функцию
    results = process_chunks_via_batch(chunks_for_batch, cache_dir, client)
    
    # Обновляем метаданные частей с информацией о датах
    processed_parts = {}
    if parts_metadata_file.exists():
        with open(parts_metadata_file, "r", encoding="utf-8") as f:
            processed_parts = json.load(f)
    
    for idx, meta, chunk_hash in chunks_to_process:
        processed_parts[chunk_hash] = {
            'index': idx,
            'first_date': meta.get('first_date'),
            'last_date': meta.get('last_date'),
            'date_range': meta.get('date_range', []),
            'chunk_size': len(meta['chunk']),
            'compressed_size': len(results.get(chunk_hash, ''))
        }
    
    with open(parts_metadata_file, "w", encoding="utf-8") as f:
        json.dump(processed_parts, f, ensure_ascii=False, indent=2)
    
    return results

