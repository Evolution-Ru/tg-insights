#!/usr/bin/env python3
"""Тест GPT-5 через responses.create() API"""
from openai import OpenAI
import os
from dotenv import load_dotenv
import json
from pathlib import Path

# Загружаем .env
script_dir = Path(__file__).resolve().parent
project_root = script_dir  # test_gpt5.py находится в tg-analyz/
account_env_path = project_root / "data" / "accounts" / "ychukaev" / ".env"

if account_env_path.exists():
    load_dotenv(account_env_path, override=True)
    print(f"✓ Загружен .env из {account_env_path}")
else:
    print(f"⚠ .env не найден: {account_env_path}")

load_dotenv(project_root / ".env")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("❌ OPENAI_API_KEY не найден")
    exit(1)

client = OpenAI(api_key=api_key)

print("🧪 Тестирую GPT-5 через responses.create() API...\n")

# Тест 1: Простой текстовый запрос
print("📝 Тест 1: Простой текстовый запрос (сжатие)")
try:
    response = client.responses.create(
        model="gpt-5",
        input=[
            {"role": "user", "content": "Сожми этот текст до ключевых моментов:\n\nМы обсуждали проект Фарма+. Нужно сделать интеграцию с API. Дедлайн - завтра. Также нужно обновить документацию. И проверить работу системы."}
        ],
        reasoning={"effort": "low"}
    )
    
    text = ""
    if getattr(response, "output", None):
        for item in response.output:
            if getattr(item, "content", None):
                for c in item.content:
                    if getattr(c, "text", None):
                        text += c.text
    
    print(f"✅ Ответ получен ({len(text)} символов):")
    print(f"   {text[:200]}...\n")
except Exception as e:
    print(f"❌ Ошибка: {e}\n")
    import traceback
    print(traceback.format_exc()[:300])

# Тест 2: Запрос с system prompt и JSON
print("📝 Тест 2: Запрос с system prompt и JSON")
try:
    response = client.responses.create(
        model="gpt-5",
        input=[
            {"role": "system", "content": "Ты помогаешь извлекать задачи из переписок. Отвечай только валидным JSON."},
            {"role": "user", "content": """Извлеки задачи из текста:

"Нужно сделать интеграцию с API до завтра. Также обновить документацию."

Верни JSON: {"tasks": [{"title": "...", "deadline": "..."}]}"""}
        ],
        reasoning={"effort": "low"}
    )
    
    text = ""
    if getattr(response, "output", None):
        for item in response.output:
            if getattr(item, "content", None):
                for c in item.content:
                    if getattr(c, "text", None):
                        text += c.text
    
    # Убираем markdown если есть
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    
    print(f"✅ Ответ получен:")
    print(f"   {text}\n")
    
    # Пробуем распарсить JSON
    try:
        result = json.loads(text)
        print(f"✅ JSON успешно распарсен: {len(result.get('tasks', []))} задач")
        print(f"   Задачи: {json.dumps(result, ensure_ascii=False, indent=2)}")
    except Exception as e:
        print(f"⚠️ JSON не распарсился: {e}")
        print(f"   Но текст получен: {text[:100]}...")
        
except Exception as e:
    print(f"❌ Ошибка: {e}\n")
    import traceback
    print(traceback.format_exc()[:300])

print("\n✅ Тестирование завершено")

