"""
Главная функция сжатия диалогов с инкрементальной обработкой и скользящим окном
"""
import json
import hashlib
from pathlib import Path
from typing import List, Dict, Any
from .chunking import split_thread_by_dates
from .compressor import compress_chunk
from .batch_processor import process_chunks_via_batch_with_dates
from .sliding_window import apply_sliding_window
from shared.ai.gpt5_client import get_openai_client


def compress_thread_with_smart_model(
    thread_text: str, 
    max_chunk_size: int = 10000,
    output_dir: Path = None,
    client=None
) -> str:
    """
    Сжимает диалог до ключевых моментов используя умную модель (gpt-5).
    Разбивает на части по дням и символам - каждый блок заканчивается законченным днем.
    
    ВАЖНО: Разбиение стабильное - границы частей определяются по датам, 
    поэтому добавление новых сообщений в конец не меняет границы существующих частей.
    
    Инкрементальная обработка: обрабатывает только части с новыми датами.
    Скользящая выжимка: использует последние 3 части + предыдущая выжимка.
    
    Args:
        thread_text: Текст диалога для сжатия
        max_chunk_size: Максимальный размер чанка в символах
        output_dir: Директория для сохранения результатов (если None, используется дефолтная)
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Финальная сжатая выжимка диалога
    """
    if client is None:
        client = get_openai_client()
    
    # Определяем директорию для результатов
    if output_dir is None:
        script_dir = Path(__file__).resolve().parent
        project_root = script_dir.parent.parent.parent  # tg-analyz/
        output_dir = project_root / "results" / "farma" / "compressed_parts"
    
    cache_dir = output_dir / "cache"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    total_length = len(thread_text)
    print(f"\n🧠 Сжатие диалога ({total_length} символов)...")
    
    # Если текст небольшой, сжимаем целиком
    if total_length <= max_chunk_size:
        return compress_chunk(thread_text, client)
    
    # Разбиваем на части по датам
    print(f"   Текст большой, разбиваю на части по дням (макс. {max_chunk_size} символов)...")
    chunks_meta = split_thread_by_dates(thread_text, max_chunk_size)
    
    print(f"   Разбито на {len(chunks_meta)} частей")
    for i, meta in enumerate(chunks_meta, 1):
        date_info = f" ({meta['first_date']} - {meta['last_date']})" if meta['first_date'] else ""
        print(f"      Часть {i}: {len(meta['chunk'])} символов{date_info}")
    
    # Загружаем метаданные о обработанных частях
    parts_metadata_file = output_dir / "parts_metadata.json"
    processed_parts = {}  # {hash: {dates, compressed_text_hash}}
    if parts_metadata_file.exists():
        with open(parts_metadata_file, "r", encoding="utf-8") as f:
            processed_parts = json.load(f)
    
    # Определяем, какие части нужно обработать (инкрементально)
    chunks_to_process = []  # [(index, chunk_meta, hash)]
    cached_results = {}  # {hash: compressed_text}
    new_dates = set()  # Все даты из новых сообщений
    
    # Сначала определяем, какие даты уже обработаны
    processed_dates = set()
    for part_hash, part_info in processed_parts.items():
        if 'date_range' in part_info:
            processed_dates.update(part_info['date_range'])
    
    print(f"\n   Проверка кеша для {len(chunks_meta)} частей...")
    print(f"   Уже обработано дат: {len(processed_dates)}")
    
    for i, meta in enumerate(chunks_meta, 1):
        chunk = meta['chunk']
        chunk_hash = hashlib.sha256(chunk.encode('utf-8')).hexdigest()[:16]
        cache_file = cache_dir / f"{chunk_hash}.txt"
        
        # Проверяем, содержит ли часть новые даты
        part_dates = set(meta['date_range']) if meta['date_range'] else set()
        has_new_dates = bool(part_dates - processed_dates)
        
        if cache_file.exists() and not has_new_dates:
            # Часть уже обработана и не содержит новых дат
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_results[chunk_hash] = f.read()
            print(f"   ✓ Часть {i}: найдена в кеше ({chunk_hash})")
        else:
            # Часть нужно обработать (новая или содержит новые даты)
            chunks_to_process.append((i, meta, chunk_hash))
            new_dates.update(part_dates)
            if has_new_dates:
                print(f"   ⏳ Часть {i}: содержит новые даты {sorted(part_dates - processed_dates)} ({chunk_hash})")
            else:
                print(f"   ⏳ Часть {i}: нужна обработка ({chunk_hash})")
    
    # Если есть части для обработки, используем батч
    if chunks_to_process:
        print(f"\n   📦 Обработка {len(chunks_to_process)} частей через Batch API...")
        batch_results = process_chunks_via_batch_with_dates(
            chunks_to_process, 
            cache_dir, 
            parts_metadata_file,
            client
        )
        cached_results.update(batch_results)
    
    # Собираем результаты в правильном порядке
    compressed_chunks = []
    for i, meta in enumerate(chunks_meta, 1):
        chunk_hash = hashlib.sha256(meta['chunk'].encode('utf-8')).hexdigest()[:16]
        
        # Проверяем наличие результата в кеше
        if chunk_hash not in cached_results:
            # Пробуем загрузить из файлового кеша (возможно файл был создан, но не попал в словарь)
            cache_file = cache_dir / f"{chunk_hash}.txt"
            if cache_file.exists():
                print(f"   ⚠ Часть {i}: результат не найден в памяти, загружаю из кеша...")
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_results[chunk_hash] = f.read()
            else:
                # Fallback: обрабатываем напрямую если батч не вернул результат
                print(f"   ⚠ Часть {i}: результат не найден, обрабатываю напрямую...")
                try:
                    compressed = compress_chunk(meta['chunk'], client)
                    cached_results[chunk_hash] = compressed
                    # Сохраняем в кеш для будущего использования
                    with open(cache_file, "w", encoding="utf-8") as f:
                        f.write(compressed)
                    print(f"   ✓ Часть {i}: обработана напрямую и сохранена в кеш")
                except Exception as e:
                    print(f"   ❌ Ошибка при обработке части {i}: {e}")
                    # Используем оригинальный текст как fallback
                    cached_results[chunk_hash] = meta['chunk']
                    print(f"   ⚠ Использую оригинальный текст для части {i}")
        
        # Теперь гарантированно есть результат в cached_results
        compressed = cached_results[chunk_hash]
        compressed_chunks.append(compressed)
        
        # Сохраняем каждую сжатую часть отдельно (для удобства просмотра)
        part_file = output_dir / f"part_{i:02d}_compressed.txt"
        with open(part_file, "w", encoding="utf-8") as f:
            f.write(compressed)
        print(f"   💾 Часть {i} сохранена: {part_file} ({len(compressed)} символов)")
    
    # Скользящая выжимка: анализируем последние 3 выжимки + предыдущая финальная выжимка
    final_summary = apply_sliding_window(compressed_chunks, output_dir, cache_dir, client)
    
    return final_summary

