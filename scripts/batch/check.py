#!/usr/bin/env python3
"""
Проверка статусов всех батчей через OpenAI API
"""
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

print("🔍 Проверка всех батчей через OpenAI API...\n")

# Получаем список батчей (последние 10)
try:
    batches = client.batches.list(limit=10)
    
    print(f"Найдено батчей: {len(batches.data)}\n")
    
    for batch in batches.data:
        print(f"Batch ID: {batch.id}")
        print(f"  Статус: {batch.status}")
        print(f"  Создан: {batch.created_at}")
        if hasattr(batch, 'completed_at') and batch.completed_at:
            print(f"  Завершен: {batch.completed_at}")
        if hasattr(batch, 'failed_at') and batch.failed_at:
            print(f"  Провален: {batch.failed_at}")
        if hasattr(batch, 'request_counts'):
            print(f"  Запросов: {batch.request_counts}")
        print()
        
        # Если батч завершен, проверяем детали
        if batch.status == "completed":
            print(f"  📥 Проверка результатов...")
            try:
                batch_detail = client.batches.retrieve(batch.id)
                if hasattr(batch_detail, 'output_file_id') and batch_detail.output_file_id:
                    print(f"  ✓ Output file ID: {batch_detail.output_file_id}")
                    # Можно скачать и посмотреть результаты
                    output_file = client.files.content(batch_detail.output_file_id)
                    output_content = output_file.read().decode('utf-8')
                    lines = [l for l in output_content.strip().split('\n') if l.strip()]
                    print(f"  ✓ Результатов: {len(lines)}")
                else:
                    print(f"  ⚠ Нет output_file_id")
            except Exception as e:
                print(f"  ❌ Ошибка при получении деталей: {e}")
        print("-" * 60)
        print()
        
except Exception as e:
    print(f"❌ Ошибка при получении списка батчей: {e}")

