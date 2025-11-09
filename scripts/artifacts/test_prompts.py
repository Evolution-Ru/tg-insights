#!/usr/bin/env python3
"""
Ручное тестирование промптов на реальных контекстах.
Использует GPT-4o для проверки качества извлечения артефактов.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any
from dotenv import load_dotenv
from openai import OpenAI


def load_account_env(account_name: str) -> None:
    """Load environment from account .env"""
    current_dir = Path(__file__).resolve().parent
    env_path = current_dir.parent.parent / "accounts" / account_name / ".env"
    
    if not env_path.exists():
        raise SystemExit(f"Environment file not found: {env_path}")
    
    load_dotenv(env_path)


def get_sample_contexts(db_path: Path, limit: int = 10) -> List[Dict[str, Any]]:
    """Получить случайные контексты из БД"""
    conn = sqlite3.connect(str(db_path))
    
    query = """
        SELECT 
            id,
            dialog_id,
            message_date,
            context_text
        FROM dialog_contexts
        WHERE LENGTH(context_text) > 100
        ORDER BY RANDOM()
        LIMIT ?
    """
    
    cursor = conn.execute(query, (limit,))
    contexts = []
    
    for row in cursor.fetchall():
        contexts.append({
            "id": row[0],
            "dialog_id": row[1],
            "message_date": row[2],
            "context_text": row[3]
        })
    
    conn.close()
    return contexts


def screening_prompt(context_text: str) -> str:
    """Промпт для скрининга контекста (Уровень 1)"""
    return f"""Ты анализируешь контекст диалога из Telegram для поиска важных артефактов коммуникации.

ТИПЫ АРТЕФАКТОВ:
1. commitment - обязательство (кто-то обещает что-то сделать к определенному сроку)
2. request - запрос (кто-то просит помощи, информации, действия)
3. decision - решение (принято важное решение о проекте, продукте, процессе)
4. deadline - дедлайн (упоминается конкретная дата завершения задачи/проекта)
5. agreement - договоренность (согласованы встречи, условия, планы)

КОНТЕКСТ ДИАЛОГА:
```
{context_text}
```

ЗАДАЧА:
Определи, содержит ли этот контекст хотя бы один из артефактов выше.

ОТВЕТ (строго JSON):
{{
  "has_artifacts": true/false,
  "artifact_types": ["commitment", "request", ...],
  "confidence": 0.0-1.0,
  "reasoning": "краткое объяснение на русском"
}}

ПРАВИЛА:
- Если не уверен на 70%+ → has_artifacts: false
- Указывай ВСЕ найденные типы артефактов
- confidence отражает уверенность (0.0 = совсем не уверен, 1.0 = абсолютно уверен)"""


def test_screening(client: OpenAI, contexts: List[Dict[str, Any]], model: str = "gpt-4o"):
    """Тестируем промпт скрининга на контекстах"""
    print(f"\n{'='*80}")
    print(f"🧪 ТЕСТИРОВАНИЕ СКРИНИНГА (Уровень 1)")
    print(f"📊 Модель: {model}")
    print(f"📝 Контекстов: {len(contexts)}")
    print(f"{'='*80}\n")
    
    results = []
    
    for i, ctx in enumerate(contexts, 1):
        print(f"\n{'─'*80}")
        print(f"📄 Контекст #{i} (ID: {ctx['id']}, Дата: {ctx['message_date']})")
        print(f"{'─'*80}")
        
        # Показываем первые 300 символов контекста
        preview = ctx['context_text'][:300] + "..." if len(ctx['context_text']) > 300 else ctx['context_text']
        print(f"\n📖 Текст контекста:\n{preview}\n")
        
        # Отправляем в модель
        try:
            prompt = screening_prompt(ctx['context_text'])
            
            # o1 модели не поддерживают system messages и response_format
            if model.startswith("o1"):
                # Для o1 - только user message
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "user", "content": prompt}
                    ]
                )
            elif model.startswith("gpt-5"):
                # GPT-5 не поддерживает temperature, top_p, logprobs
                # Использует reasoning_effort и verbosity
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Ты профессиональный ассистент для анализа бизнес-коммуникаций. Всегда возвращай валидный JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    reasoning_effort="low",  # minimal | low | medium | high
                    # verbosity="medium"  # low | medium | high (опционально)
                )
            else:
                # Для обычных моделей (gpt-4o, gpt-4o-mini)
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Ты профессиональный ассистент для анализа бизнес-коммуникаций. Всегда возвращай валидный JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.3
                )
            
            result = json.loads(response.choices[0].message.content)
            
            # Красивый вывод результата
            print(f"🎯 Результат:")
            print(f"   Has artifacts: {'✅ ДА' if result.get('has_artifacts') else '❌ НЕТ'}")
            
            if result.get('has_artifacts'):
                types = result.get('artifact_types', [])
                print(f"   Types: {', '.join(types)}")
            
            print(f"   Confidence: {result.get('confidence', 0):.2f}")
            print(f"   Reasoning: {result.get('reasoning', 'N/A')}")
            
            # Токены
            usage = response.usage
            print(f"\n💰 Использовано токенов:")
            print(f"   Input: {usage.prompt_tokens}")
            print(f"   Output: {usage.completion_tokens}")
            print(f"   Total: {usage.total_tokens}")
            
            # Сохраняем для статистики
            results.append({
                "context_id": ctx['id'],
                "has_artifacts": result.get('has_artifacts', False),
                "types": result.get('artifact_types', []),
                "confidence": result.get('confidence', 0),
                "tokens": usage.total_tokens
            })
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            results.append({
                "context_id": ctx['id'],
                "error": str(e)
            })
    
    # Итоговая статистика
    print(f"\n\n{'='*80}")
    print(f"📊 ИТОГОВАЯ СТАТИСТИКА")
    print(f"{'='*80}\n")
    
    total = len(results)
    with_artifacts = sum(1 for r in results if r.get('has_artifacts'))
    total_tokens = sum(r.get('tokens', 0) for r in results)
    avg_confidence = sum(r.get('confidence', 0) for r in results) / total if total > 0 else 0
    
    print(f"✅ Обработано контекстов: {total}")
    print(f"🎯 С артефактами: {with_artifacts} ({with_artifacts/total*100:.1f}%)")
    print(f"💰 Всего токенов: {total_tokens}")
    print(f"📈 Средний confidence: {avg_confidence:.2f}")
    
    # Распределение по типам
    all_types = []
    for r in results:
        all_types.extend(r.get('types', []))
    
    if all_types:
        print(f"\n📊 Распределение по типам артефактов:")
        type_counts = {}
        for t in all_types:
            type_counts[t] = type_counts.get(t, 0) + 1
        
        for artifact_type, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            print(f"   - {artifact_type}: {count}")
    
    # Оценка стоимости
    cost_per_1m = {
        "gpt-4o": (2.50, 10.00),           # input, output
        "gpt-4o-mini": (0.15, 0.60),
        "o1-preview": (15.00, 60.00),
        "o1-mini": (3.00, 12.00),
        "gpt-5": (5.00, 15.00),            # примерная цена для gpt-5
    }
    
    if model in cost_per_1m:
        input_price, output_price = cost_per_1m[model]
        # Примерно 60/40 input/output
        input_cost = (total_tokens * 0.6) / 1_000_000 * input_price
        output_cost = (total_tokens * 0.4) / 1_000_000 * output_price
        total_cost = input_cost + output_cost
        print(f"\n💵 Оценочная стоимость: ${total_cost:.4f}")
    
    return results


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Тестирование промптов на реальных контекстах")
    parser.add_argument("--account", default="ychukaev", help="Account name")
    parser.add_argument("--limit", type=int, default=10, help="Number of contexts to test")
    parser.add_argument("--model", default="gpt-4o", help="Model to use (gpt-5, gpt-4o, gpt-4o-mini, o1-preview, o1-mini)")
    
    args = parser.parse_args()
    
    # Load environment
    load_account_env(args.account)
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY not found in environment")
    
    # Database path
    current_dir = Path(__file__).resolve().parent
    db_path = current_dir.parent.parent / "accounts" / args.account / "messages.sqlite"
    
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    
    # Initialize OpenAI client
    client = OpenAI(api_key=api_key)
    
    # Get sample contexts
    print(f"📚 Загружаю {args.limit} случайных контекстов из {db_path.name}...")
    contexts = get_sample_contexts(db_path, args.limit)
    
    if not contexts:
        raise SystemExit("No contexts found in database")
    
    # Test screening
    results = test_screening(client, contexts, model=args.model)
    
    # Save results
    output_path = Path(__file__).parent / "test_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "model": args.model,
            "contexts_tested": len(contexts),
            "results": results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"\n💾 Результаты сохранены: {output_path}")


if __name__ == "__main__":
    main()

