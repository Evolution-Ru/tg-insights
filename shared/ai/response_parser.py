"""
Парсинг ответов GPT-5 через responses API
"""
from typing import Optional
import json
import re
from shared.ai.gpt5_client import parse_gpt5_response, parse_json_from_markdown


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
        json_match = re.search(r'\{.*\}', json_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
    
    return None

