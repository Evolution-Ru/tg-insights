#!/usr/bin/env python3
"""
Модуль для расчета семантической схожести текстов через GPT-5
"""
import re
from typing import Optional


def calculate_similarity_gpt5(
    text1: str,
    text2: str,
    openai_client,
    verbose: bool = False
) -> float:
    """
    Вычисление семантической схожести двух текстов через GPT-5
    Возвращает значение от 0 до 1
    
    Args:
        text1: Первый текст для сравнения
        text2: Второй текст для сравнения
        openai_client: OpenAI клиент
        verbose: Выводить предупреждения при ошибках
        
    Returns:
        Значение схожести от 0.0 до 1.0
    """
    if not text1 or not text2:
        return 0.0
    
    prompt = f"""Сравни два текста и определи, насколько они похожи по смыслу (не по словам, а по содержанию).

Текст 1: {text1[:500]}
Текст 2: {text2[:500]}

Ответь одним числом от 0 до 1, где:
- 1.0 = это одна и та же задача/тема
- 0.8-0.9 = очень похожие задачи, но есть различия
- 0.6-0.7 = связанные задачи, но разные
- 0.3-0.5 = частично связаны
- 0.0-0.2 = разные задачи

Только число, без объяснений:"""
    
    try:
        response = openai_client.responses.create(
            model="gpt-5",
            input=[{"role": "user", "content": prompt}],
            reasoning={"effort": "low"}
        )
        
        # Извлекаем число из ответа
        result_text = None
        if hasattr(response, 'output') and response.output:
            if isinstance(response.output, list) and len(response.output) > 0:
                output_item = response.output[0]
                if hasattr(output_item, 'content') and output_item.content:
                    if isinstance(output_item.content, list) and len(output_item.content) > 0:
                        content_item = output_item.content[0]
                        if hasattr(content_item, 'text'):
                            result_text = content_item.text.strip()
                        elif isinstance(content_item, dict) and 'text' in content_item:
                            result_text = content_item['text'].strip()
                        else:
                            result_text = str(content_item).strip()
                    else:
                        result_text = str(output_item.content).strip()
                elif isinstance(output_item, dict):
                    if 'content' in output_item:
                        content = output_item['content']
                        if isinstance(content, list) and len(content) > 0:
                            if isinstance(content[0], dict) and 'text' in content[0]:
                                result_text = content[0]['text'].strip()
                            else:
                                result_text = str(content[0]).strip()
                        else:
                            result_text = str(content).strip()
                    else:
                        result_text = str(output_item).strip()
                else:
                    result_text = str(output_item).strip()
            else:
                result_text = str(response.output).strip()
        else:
            result_text = str(response).strip()
        
        # Ищем число в ответе (более гибкий паттерн)
        if result_text:
            # Пробуем разные форматы чисел
            match = re.search(r'\b(0?\.\d+|1\.0|0|1)\b', result_text)
            if not match:
                # Пробуем найти любое число от 0 до 1
                match = re.search(r'([01]\.?\d*)', result_text)
            
            if match:
                similarity = float(match.group())
                # Нормализуем: если число > 1, делим на 10 (возможно, GPT вернул 0-10)
                if similarity > 1.0:
                    similarity = similarity / 10.0
                return min(max(similarity, 0.0), 1.0)
            else:
                # Если не найдено число, возвращаем 0.0 (лучше пропустить неточное совпадение)
                if verbose:
                    print(f"      ⚠️  GPT-5 вернул нечисловой ответ: '{result_text[:100]}', возвращаем 0.0")
                return 0.0
        else:
            if verbose:
                print(f"      ⚠️  GPT-5 вернул пустой ответ, возвращаем 0.0")
            return 0.0
    except Exception as e:
        # При ошибке GPT-5 возвращаем 0.0 (лучше пропустить, чем использовать неточный fallback)
        if verbose:
            print(f"      ⚠️  Ошибка GPT-5 проверки: {e}, возвращаем 0.0")
        return 0.0

