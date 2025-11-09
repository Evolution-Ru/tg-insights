#!/usr/bin/env python3
"""
Обработка результатов батча и сохранение в кеш
"""
import json
import os
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

# Загружаем .env
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent  # tg-analyz/
account_env_path = project_root / "data" / "accounts" / "ychukaev" / ".env"

if account_env_path.exists():
    load_dotenv(account_env_path, override=True)

load_dotenv(project_root / ".env")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY не найден")

client = OpenAI(api_key=api_key, timeout=600.0)

# ID батча (можно передать как аргумент командной строки)
import sys
batch_id = sys.argv[1] if len(sys.argv) > 1 else "batch_691064ceb7088190a65faf2142f5458d"

# Путь к кешу
cache_dir = project_root / "results" / "farma" / "compressed_parts" / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)

print(f"📥 Обработка результатов батча {batch_id}...\n")

# Получаем детали батча
batch_detail = client.batches.retrieve(batch_id)
if batch_detail.status != "completed" or not batch_detail.output_file_id:
    print(f"❌ Батч не завершен или нет output файла")
    exit(1)

# Скачиваем результаты
output_file = client.files.content(batch_detail.output_file_id)
output_content = output_file.read().decode('utf-8')

# Парсим результаты
results_data = []
for line in output_content.strip().split('\n'):
    if line.strip():
        result = json.loads(line)
        results_data.append(result)

print(f"✓ Получено {len(results_data)} результатов\n")

# Обрабатываем каждый результат
processed_count = 0
for result_data in results_data:
    custom_id = result_data.get('custom_id', '')
    
    # Извлекаем hash из custom_id (формат: chunk_{idx}_{hash})
    parts = custom_id.split('_')
    if len(parts) < 3:
        print(f"⚠ Пропущен результат с неверным custom_id: {custom_id}")
        continue
    
    chunk_hash = parts[2]
    cache_file = cache_dir / f"{chunk_hash}.txt"
    
    # Если уже есть в кеше, пропускаем
    if cache_file.exists():
        print(f"✓ Уже в кеше: {chunk_hash}")
        continue
    
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
            compressed = '\n'.join(chunks)
    
    if compressed:
        # Сохраняем в кеш
        with open(cache_file, 'w', encoding='utf-8') as f:
            f.write(compressed.strip())
        print(f"✓ Сохранено в кеш: {chunk_hash} ({len(compressed)} символов)")
        processed_count += 1
    else:
        print(f"⚠ Не удалось извлечь текст для {chunk_hash}")

print(f"\n✓ Обработано {processed_count} новых результатов")
print(f"📁 Кеш: {cache_dir}")

# Обновляем метаданные батча
metadata_file = cache_dir.parent / "batch_metadata.json"
batch_metadata = {
    "batch_id": batch_id,
    "created_at": batch_detail.created_at,
    "created_at_iso": None,  # Можно добавить конвертацию timestamp
    "status": "completed",
    "completed_at": batch_detail.completed_at,
    "completed_at_iso": None,
    "input_file_id": batch_detail.input_file_id if hasattr(batch_detail, 'input_file_id') else None,
    "output_file_id": batch_detail.output_file_id,
    "total_chunks": len(results_data),
    "processed_chunks": processed_count
}

batch_metadata_list = []
if metadata_file.exists():
    with open(metadata_file, 'r', encoding='utf-8') as f:
        batch_metadata_list = json.load(f)

# Обновляем или добавляем метаданные
found = False
for bm in batch_metadata_list:
    if bm.get("batch_id") == batch_id:
        bm.update(batch_metadata)
        found = True
        break

if not found:
    batch_metadata_list.append(batch_metadata)

with open(metadata_file, 'w', encoding='utf-8') as f:
    json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)

print(f"💾 Метаданные обновлены: {metadata_file}")

