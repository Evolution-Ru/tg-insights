"""
Общий клиент GPT-5 и утилиты для работы с OpenAI API
"""
import os
from pathlib import Path
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv


def get_openai_client(timeout: float = 600.0) -> OpenAI:
    """
    Создает и возвращает настроенный клиент OpenAI.
    Загружает API ключ из .env файла аккаунта или корня проекта.
    """
    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent.parent.parent  # tg-analyz/
    account_env_path = project_root / "data" / "accounts" / "ychukaev" / ".env"
    
    if account_env_path.exists():
        load_dotenv(account_env_path, override=True)
    else:
        load_dotenv(project_root / ".env")
    
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(f"OPENAI_API_KEY не найден в переменных окружения. Проверьте {account_env_path}")
    
    return OpenAI(
        api_key=api_key,
        timeout=timeout
    )


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

