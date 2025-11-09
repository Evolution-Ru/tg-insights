"""
Парсинг ответов GPT-5 через responses API
"""
from typing import Optional
import json


def parse_gpt5_response(response) -> Optional[str]:
    """
    Парсит ответ от GPT-5 через responses API.
    Поддерживает различные форматы ответа.
    
    Returns:
        Извлеченный текст или None если не удалось извлечь
    """
    # Вариант 1: response.output_text (основной способ)
    if hasattr(response, 'output_text') and response.output_text:
        return str(response.output_text).strip()
    
    # Вариант 2: response.output (парсим структуру)
    if hasattr(response, 'output') and response.output:
        if isinstance(response.output, str):
            return response.output.strip()
        elif isinstance(response.output, list):
            chunks = []
            for item in response.output:
                if isinstance(item, dict):
                    if 'text' in item:
                        chunks.append(item['text'])
                    elif 'content' in item:
                        for c in item.get('content', []):
                            if isinstance(c, dict) and 'text' in c:
                                chunks.append(c['text'])
                elif hasattr(item, 'content') and item.content:
                    for c in item.content:
                        if hasattr(c, 'text') and c.text:
                            chunks.append(c.text)
                elif hasattr(item, 'text') and item.text:
                    chunks.append(item.text)
            if chunks:
                return '\n'.join(chunks).strip()
    
    # Вариант 3: response.choices[].message.content (fallback)
    if hasattr(response, 'choices') and response.choices:
        chunks = []
        for choice in response.choices:
            if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                chunks.append(choice.message.content)
        if chunks:
            return '\n'.join(chunks).strip()
    
    return None


def parse_json_from_markdown(text: str) -> str:
    """
    Извлекает JSON из markdown код-блоков если они есть.
    """
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text


def parse_json_response(response_text: str) -> Optional[dict]:
    """
    Парсит JSON из ответа GPT-5.
    Сначала извлекает из markdown блоков, затем парсит JSON.
    """
    # Извлекаем из markdown если нужно
    json_text = parse_json_from_markdown(response_text)
    
    # Пробуем парсить JSON
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        # Пробуем найти JSON блок в тексте
        import re
        json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
    
    return None

