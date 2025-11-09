"""
Сжатие чанков через GPT-5
"""
import time
import hashlib
from pathlib import Path
from typing import Optional
from shared.ai.gpt5_client import get_openai_client, parse_gpt5_response


def compress_chunk(chunk_text: str, client=None) -> str:
    """
    Сжимает один чанк текста используя GPT-5 через responses API.
    
    Args:
        chunk_text: Текст чанка для сжатия
        client: OpenAI клиент (если None, создается новый)
    
    Returns:
        Сжатый текст
    """
    if client is None:
        client = get_openai_client()
    
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
{chunk_text}"""
    
    # Повторные попытки при ошибках соединения
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            if attempt > 1:
                print(f"      Повторная попытка {attempt}/{max_retries}...", flush=True)
            else:
                input_size = len(system_prompt) + len(user_prompt)
                print(f"      Отправка запроса в GPT-5 (размер промпта: {input_size} символов)...", flush=True)
            
            start_time = time.time()
            
            print(f"      → Вызов client.responses.create()...", flush=True)
            print(f"      → Параметры: model=gpt-5, reasoning=low", flush=True)
            
            try:
                # Формат для responses API: input должен быть списком словарей с role/content
                response = client.responses.create(
                    model="gpt-5",
                    input=[
                        {
                            "role": "system",
                            "content": system_prompt
                        },
                        {
                            "role": "user",
                            "content": user_prompt
                        }
                    ],
                    reasoning={"effort": "low"}  # Используем low для быстрого сжатия больших текстов
                )
                print(f"      ✓ Вызов завершен, получен объект response", flush=True)
            except Exception as create_error:
                print(f"      ❌ Ошибка при создании запроса: {create_error}", flush=True)
                print(f"      → Тип ошибки: {type(create_error)}", flush=True)
                import traceback
                print(f"      → Трейсбек: {traceback.format_exc()[:500]}", flush=True)
                raise
            
            # Проверяем статус ответа - возможно нужен polling
            print(f"      → Проверка статуса ответа...", flush=True)
            if hasattr(response, "status"):
                print(f"      → Статус ответа: {response.status}", flush=True)
                if response.status in ["queued", "in_progress"]:
                    # Если ответ еще обрабатывается, делаем polling
                    response_id = response.id if hasattr(response, "id") else None
                    if response_id:
                        print(f"      → Ответ в обработке, делаю polling (ID: {response_id})...", flush=True)
                        max_poll_attempts = 60  # Максимум 60 попыток (5 минут)
                        poll_interval = 5  # Проверяем каждые 5 секунд
                        for poll_attempt in range(1, max_poll_attempts + 1):
                            time.sleep(poll_interval)
                            try:
                                response = client.responses.retrieve(response_id)
                                print(f"      → Poll {poll_attempt}: статус = {response.status}", flush=True)
                                if response.status == "completed":
                                    break
                                elif response.status in ["failed", "cancelled"]:
                                    raise Exception(f"Ответ завершился со статусом: {response.status}")
                            except Exception as poll_error:
                                print(f"      ⚠ Ошибка при polling: {poll_error}", flush=True)
                                if poll_attempt == max_poll_attempts:
                                    raise
            else:
                print(f"      → У ответа нет атрибута status, предполагаем что он готов", flush=True)
            
            elapsed = time.time() - start_time
            print(f"      ✓ Получен ответ от GPT-5 за {elapsed:.1f} сек", flush=True)
            print(f"      → Парсинг ответа...", flush=True)
            
            # Извлекаем текст из ответа GPT-5
            compressed = parse_gpt5_response(response)
            
            if compressed:
                print(f"      ✓ Извлечено {len(compressed)} символов из ответа", flush=True)
                return compressed
            else:
                print(f"      ⚠ Не удалось извлечь текст из ответа", flush=True)
                print(f"      → Тип response: {type(response)}", flush=True)
                print(f"      → Атрибуты response: {[a for a in dir(response) if not a.startswith('_')][:20]}", flush=True)
                # Попробуем вывести весь response для отладки
                try:
                    import json
                    print(f"      → response.__dict__: {json.dumps(str(response.__dict__)[:500], ensure_ascii=False)}", flush=True)
                except:
                    pass
                raise Exception("Пустой ответ от модели")
            
        except Exception as e:
            error_msg = str(e)
            is_connection_error = "Connection" in error_msg or "timeout" in error_msg.lower() or "network" in error_msg.lower()
            
            if is_connection_error and attempt < max_retries:
                wait_time = attempt * 2  # Экспоненциальная задержка: 2, 4, 6 сек
                print(f"      ⚠ Ошибка соединения, жду {wait_time} сек перед повтором...", flush=True)
                time.sleep(wait_time)
                continue
            else:
                print(f"❌ Ошибка при сжатии: {e}")
                import traceback
                print(f"   Детали: {traceback.format_exc()[:200]}")
                # Возвращаем оригинал если не удалось сжать после всех попыток
                return chunk_text
    
    # Если все попытки исчерпаны
    return chunk_text

