#!/usr/bin/env python3
"""
Скачивание и обработка результатов батча
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

print(f"📥 Скачивание результатов батча {batch_id}...\n")

# Получаем детали батча
batch_detail = client.batches.retrieve(batch_id)
print(f"Статус: {batch_detail.status}")
print(f"Запросов: {batch_detail.request_counts}")

if batch_detail.status == "completed" and batch_detail.output_file_id:
    print(f"\n📥 Скачивание output файла: {batch_detail.output_file_id}")
    output_file = client.files.content(batch_detail.output_file_id)
    output_content = output_file.read().decode('utf-8')
    
    # Парсим результаты
    results = []
    for line in output_content.strip().split('\n'):
        if line.strip():
            result = json.loads(line)
            results.append(result)
    
    print(f"✓ Получено {len(results)} результатов\n")
    
    # Проверяем структуру первого результата
    if results:
        print("📋 Структура первого результата:")
        print(json.dumps(results[0], ensure_ascii=False, indent=2)[:1000])
        print("...")
        
        # Извлекаем текст из первого результата
        response_body = results[0].get('response', {}).get('body', {})
        print(f"\n📝 Извлечение текста из первого результата...")
        
        output_text = None
        if 'output_text' in response_body:
            output_text = response_body['output_text']
        elif 'output' in response_body:
            output = response_body['output']
            if isinstance(output, str):
                output_text = output
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
                output_text = '\n'.join(chunks)
        
        if output_text:
            print(f"✓ Текст извлечен ({len(output_text)} символов):")
            print(output_text[:500])
            print("...")
        else:
            print("⚠ Не удалось извлечь текст")
            print(f"Полная структура response.body: {json.dumps(response_body, ensure_ascii=False, indent=2)}")
    
    # Сохраняем результаты в файл для анализа
    output_file_path = project_root / "results" / "farma" / "compressed_parts" / f"batch_{batch_id}_results.json"
    output_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n💾 Результаты сохранены в: {output_file_path}")

