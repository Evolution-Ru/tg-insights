#!/usr/bin/env python3
"""
Тестовый скрипт для отправки одного запроса в Batch API с правильным форматом
"""
import json
import tempfile
from pathlib import Path
from openai import OpenAI
import os
from dotenv import load_dotenv
import time

# Загружаем .env из аккаунта
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.parent  # tg-analyz/
account_env_path = project_root / "data" / "accounts" / "ychukaev" / ".env"

if account_env_path.exists():
    load_dotenv(account_env_path, override=True)
    print(f"✓ Загружен .env из {account_env_path}")
else:
    print(f"⚠ .env не найден: {account_env_path}")

# Также пробуем загрузить из корня проекта
load_dotenv(project_root / ".env")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError(f"OPENAI_API_KEY не найден в переменных окружения. Проверьте {account_env_path}")

print(f"✓ OpenAI API ключ загружен (длина: {len(api_key)})")

client = OpenAI(
    api_key=api_key,
    timeout=600.0
)

# Тестовый запрос - сжатие небольшого текста
test_chunk = """2024-10-15
Юрий: Привет, как дела с проектом?
Евгений: Привет! Всё хорошо, работаем над задачей по каталогу.
Юрий: Отлично, когда планируем завершить?
Евгений: К концу недели должны успеть.
Юрий: Супер, жду результат."""

system_prompt = "Ты помогаешь сжимать переписки до ключевых моментов."

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
{test_chunk}"""

# Формат для responses API в Batch: input должен быть списком словарей с role/content
request_data = {
    "custom_id": "test_chunk_1",
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

# Создаем временный JSONL файл с одним запросом
temp_jsonl = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False, encoding='utf-8')
temp_jsonl.write(json.dumps(request_data, ensure_ascii=False) + '\n')
temp_jsonl.close()
jsonl_path = Path(temp_jsonl.name)

print(f"\n{'='*60}")
print(f"📤 Тестовая отправка батча с одним запросом")
print(f"{'='*60}")
print(f"📄 Файл: {jsonl_path}")
print(f"📏 Размер запроса: {len(user_prompt)} символов")

# Загружаем файл
print(f"\n📤 Загрузка файла в OpenAI...")
with open(jsonl_path, 'rb') as f:
    uploaded_file = client.files.create(
        file=f,
        purpose="batch"
    )
print(f"✓ Файл загружен: {uploaded_file.id}")

# Создаем батч
print(f"\n📦 Создание батча...")
batch = client.batches.create(
    input_file_id=uploaded_file.id,
    endpoint="/v1/responses",
    completion_window="24h"
)
batch_id = batch.id
print(f"✓ Батч создан: {batch_id}")

# Сохраняем метаданные
output_dir = project_root / "results" / "farma" / "compressed_parts"
output_dir.mkdir(parents=True, exist_ok=True)
metadata_file = output_dir / "batch_metadata.json"

batch_metadata = {
    "batch_id": batch_id,
    "created_at": time.time(),
    "created_at_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
    "status": "created",
    "input_file_id": uploaded_file.id,
    "test": True,
    "total_chunks": 1
}

batch_metadata_list = []
if metadata_file.exists():
    with open(metadata_file, "r", encoding="utf-8") as f:
        batch_metadata_list = json.load(f)

batch_metadata_list.append(batch_metadata)
with open(metadata_file, "w", encoding="utf-8") as f:
    json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)

print(f"💾 Метаданные батча сохранены: {metadata_file}")
print(f"\n⏳ Ожидание завершения батча (проверяем каждые 10 секунд)...")
print(f"   Batch ID: {batch_id}")
print(f"   Проверить статус можно командой: openai batches retrieve {batch_id}")

# Дожидаемся завершения батча
max_wait_time = 3600  # Максимум 1 час
start_time = time.time()
poll_interval = 10  # Проверяем каждые 10 секунд

while True:
    elapsed = time.time() - start_time
    if elapsed > max_wait_time:
        print(f"\n⏰ Превышено максимальное время ожидания ({max_wait_time} секунд)")
        break
    
    batch_status = client.batches.retrieve(batch_id)
    status = batch_status.status
    
    print(f"   [{elapsed:.0f}s] Статус: {status}", end='\r')
    
    if status == "completed":
        print(f"\n✓ Батч завершен!")
        batch_metadata["status"] = "completed"
        batch_metadata["completed_at"] = time.time()
        batch_metadata["completed_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
        batch_metadata["processing_time_seconds"] = elapsed
        batch_metadata["output_file_id"] = batch_status.output_file_id if hasattr(batch_status, 'output_file_id') else None
        
        # Обновляем метаданные
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                batch_metadata_list = json.load(f)
            for bm in batch_metadata_list:
                if bm.get("batch_id") == batch_id:
                    bm.update(batch_metadata)
                    break
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
        
        # Скачиваем результаты
        if batch_status.output_file_id:
            print(f"\n📥 Скачивание результатов...")
            output_file = client.files.content(batch_status.output_file_id)
            output_content = output_file.read().decode('utf-8')
            
            # Парсим результаты
            results = []
            for line in output_content.strip().split('\n'):
                if line.strip():
                    result = json.loads(line)
                    results.append(result)
            
            print(f"✓ Получено {len(results)} результатов")
            
            # Выводим результат
            if results:
                result = results[0]
                print(f"\n{'='*60}")
                print(f"📋 Результат:")
                print(f"{'='*60}")
                
                # Извлекаем текст из ответа
                response_obj = result.get("response", {}).get("body", {})
                output_text = None
                
                if isinstance(response_obj, dict):
                    # Проверяем разные возможные форматы ответа
                    if "output" in response_obj:
                        output = response_obj["output"]
                        if isinstance(output, list):
                            # Список объектов с content/text
                            chunks = []
                            for item in output:
                                if isinstance(item, dict):
                                    if "content" in item:
                                        for content_item in item.get("content", []):
                                            if isinstance(content_item, dict) and "text" in content_item:
                                                chunks.append(content_item["text"])
                                    elif "text" in item:
                                        chunks.append(item["text"])
                            output_text = '\n'.join(chunks).strip()
                        elif isinstance(output, str):
                            output_text = output
                    elif "output_text" in response_obj:
                        output_text = response_obj["output_text"]
                    elif "text" in response_obj:
                        output_text = response_obj["text"]
                
                if output_text:
                    print(output_text)
                else:
                    print("⚠ Не удалось извлечь текст из ответа")
                    print(f"Полный ответ: {json.dumps(response_obj, ensure_ascii=False, indent=2)}")
        
        break
    elif status == "failed" or status == "expired" or status == "cancelled":
        print(f"\n❌ Батч завершился со статусом: {status}")
        batch_metadata["status"] = status
        batch_metadata[f"{status}_at"] = time.time()
        batch_metadata[f"{status}_at_iso"] = time.strftime("%Y-%m-%d %H:%M:%S")
        
        # Обновляем метаданные
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                batch_metadata_list = json.load(f)
            for bm in batch_metadata_list:
                if bm.get("batch_id") == batch_id:
                    bm.update(batch_metadata)
                    break
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
        
        if hasattr(batch_status, 'errors'):
            print(f"Ошибки: {batch_status.errors}")
        break
    else:
        # Обновляем статус в метаданных
        batch_metadata["status"] = status
        if metadata_file.exists():
            with open(metadata_file, "r", encoding="utf-8") as f:
                batch_metadata_list = json.load(f)
            for bm in batch_metadata_list:
                if bm.get("batch_id") == batch_id:
                    bm.update(batch_metadata)
                    break
            with open(metadata_file, "w", encoding="utf-8") as f:
                json.dump(batch_metadata_list, f, ensure_ascii=False, indent=2)
    
    time.sleep(poll_interval)

# Удаляем временный файл
jsonl_path.unlink()
print(f"\n✓ Временный файл удален")

