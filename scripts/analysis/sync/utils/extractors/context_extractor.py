#!/usr/bin/env python3
"""
Модуль для извлечения контекста из задач Asana и Telegram
"""
import re
from typing import Dict, Any, Optional


def normalize_text(text: str) -> str:
    """Нормализация текста для сравнения"""
    if not text:
        return ""
    # Приводим к нижнему регистру, убираем лишние пробелы
    text = text.lower().strip()
    # Убираем знаки препинания для более гибкого сравнения
    text = re.sub(r'[^\w\s]', ' ', text)
    # Убираем множественные пробелы
    text = re.sub(r'\s+', ' ', text)
    return text


class AsanaContextExtractor:
    """Класс для извлечения контекста из задач Asana"""
    
    def __init__(self, task_summarizer=None, summarized_tasks_cache=None):
        """
        Инициализация экстрактора контекста
        
        Args:
            task_summarizer: Экземпляр AsanaTaskSummarizer для суммаризации задач
            summarized_tasks_cache: Кеш суммаризированных задач
        """
        self.task_summarizer = task_summarizer
        self.summarized_tasks_cache = summarized_tasks_cache or {}
    
    def extract_asana_task_context(self, asana_task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Извлечь контекстную выжимку из задачи Asana
        
        Использует предварительно суммаризированные версии задач (если доступны)
        для улучшения качества эмбеддингов и сопоставления.
        
        Args:
            asana_task: Задача из Asana
            
        Returns:
            Словарь с контекстной информацией:
            - summary: краткая выжимка (название + ключевые моменты из notes)
            - full_text: полный текст для сравнения (название + даты + исполнитель + суммаризированное описание)
            - embedding_text: компактная версия для эмбеддингов (название + метаданные + суммаризированное описание)
            - key_points: ключевые моменты из описания
            - status: статус задачи
            - implementation_details: детали реализации (если есть в notes)
        """
        name = asana_task.get('name', '')
        notes = asana_task.get('notes', '') or ''
        completed = asana_task.get('completed', False)
        task_gid = asana_task.get('gid', '')
        
        # Собираем метаданные для включения в эмбеддинги
        metadata_parts = []
        
        # Исполнитель
        assignee = asana_task.get('assignee')
        if assignee:
            if isinstance(assignee, dict):
                assignee_name = assignee.get('name', '')
            else:
                assignee_name = str(assignee)
            if assignee_name:
                metadata_parts.append(f"Исполнитель: {assignee_name}")
        
        # Даты
        due_on = asana_task.get('due_on')
        if due_on:
            metadata_parts.append(f"Срок: {due_on}")
        
        created_at = asana_task.get('created_at')
        if created_at:
            # Извлекаем только дату из ISO формата
            if 'T' in str(created_at):
                date_part = str(created_at).split('T')[0]
                metadata_parts.append(f"Создано: {date_part}")
        
        modified_at = asana_task.get('modified_at')
        if modified_at:
            if 'T' in str(modified_at):
                date_part = str(modified_at).split('T')[0]
                metadata_parts.append(f"Изменено: {date_part}")
        
        # Получаем суммаризированную версию (если доступна)
        summarized_text = None
        if self.task_summarizer and task_gid:
            # Проверяем кеш текущей сессии
            if task_gid in self.summarized_tasks_cache:
                summarized_text = self.summarized_tasks_cache[task_gid]
            else:
                # Пробуем получить из кеша суммаризатора
                summarized_text = self.task_summarizer.get_summary(asana_task)
                if summarized_text:
                    self.summarized_tasks_cache[task_gid] = summarized_text
        
        # Используем суммаризированную версию, если доступна, иначе оригинальные notes
        content_text = summarized_text if summarized_text else notes
        
        # Извлекаем ключевые моменты из notes (для обратной совместимости)
        key_points = []
        implementation_details = []
        
        if notes:
            # Ищем маркеры реализации
            lines = notes.split('\n')
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Ключевые слова, указывающие на реализацию
                if any(marker in line.lower() for marker in ['реализовано', 'сделано', 'готово', 'выполнено', 
                                                             'работает', 'внедрено', 'завершено', 'done', 'completed']):
                    implementation_details.append(line)
                elif len(line) > 20:  # Значимые строки
                    key_points.append(line[:200])  # Ограничиваем длину
        
        # Формируем полный текст для сравнения (для GPT-5 проверки)
        # Порядок: название, метаданные (даты, исполнитель), суммаризированное описание
        full_text_parts = [name]
        
        if metadata_parts:
            full_text_parts.append(" ".join(metadata_parts))
        
        if content_text:
            full_text_parts.append(content_text)
        
        full_text = " ".join(full_text_parts).strip()
        
        # Формируем компактную версию для эмбеддингов
        # Используем суммаризированную версию (если доступна) для лучшего качества
        # Суммаризация уже убрала "воду" и оставила только факты
        embedding_text_parts = [name]
        
        if metadata_parts:
            embedding_text_parts.append(" ".join(metadata_parts))
        
        if content_text:
            # Если используется суммаризация, используем её полностью (она уже компактная)
            # Если нет - ограничиваем длину
            if summarized_text:
                embedding_text_parts.append(content_text)
            else:
                # Fallback: первые 2000 символов + ключевые моменты
                notes_start = content_text[:2000].strip()
                embedding_text_parts.append(notes_start)
                if key_points:
                    key_points_text = " ".join(key_points[:3])
                    embedding_text_parts.append(key_points_text)
        
        embedding_text = " ".join(embedding_text_parts).strip()[:8000]  # Лимит OpenAI
        
        # Создаем краткую выжимку
        summary_parts = [name]
        if content_text:
            if summarized_text:
                # Используем суммаризированную версию (уже компактная)
                summary_parts.append(content_text[:500])
            else:
                # Fallback: первые 300 символов
                notes_preview = content_text[:300].strip()
                if len(content_text) > 300:
                    notes_preview += "..."
                summary_parts.append(notes_preview)
        
        summary = "\n".join(summary_parts)
        
        return {
            'summary': summary,
            'full_text': full_text,  # Полный текст для GPT-5 проверки
            'embedding_text': embedding_text,  # Компактная версия для эмбеддингов
            'key_points': key_points[:5],  # Максимум 5 ключевых моментов
            'status': 'completed' if completed else 'in_progress',
            'implementation_details': implementation_details,
            'has_notes': bool(notes),
            'notes_length': len(notes),
            'uses_summarization': bool(summarized_text)  # Флаг использования суммаризации
        }
    
    def create_asana_task_summary(self, asana_task: Dict[str, Any], openai_client=None, use_gpt5: bool = False) -> str:
        """
        Создать краткую выжимку задачи Asana для анализа покрытия
        
        Args:
            asana_task: Задача из Asana
            openai_client: OpenAI клиент (если нужен GPT-5)
            use_gpt5: Использовать GPT-5 для создания выжимки (дорого, но точнее)
            
        Returns:
            Краткая выжимка задачи
        """
        name = asana_task.get('name', '')
        notes = asana_task.get('notes', '') or ''
        
        if use_gpt5 and notes and openai_client:
            # Используем GPT-5 для создания структурированной выжимки
            prompt = f"""Создай краткую выжимку задачи из Asana, выделив:
1. Что реализовано/сделано
2. Что планируется/в процессе
3. Ключевые технические детали

Название задачи: {name}

Описание:
{notes[:2000]}

Выжимка (кратко, структурированно):"""
            
            try:
                response = openai_client.responses.create(
                    model="gpt-5",
                    input=[{"role": "user", "content": prompt}],
                    reasoning={"effort": "low"}
                )
                
                # Извлекаем текст из ответа
                if hasattr(response, 'output') and response.output:
                    if isinstance(response.output, list) and len(response.output) > 0:
                        output_item = response.output[0]
                        if hasattr(output_item, 'content') and output_item.content:
                            if isinstance(output_item.content, list) and len(output_item.content) > 0:
                                content_item = output_item.content[0]
                                if hasattr(content_item, 'text'):
                                    return f"{name}\n\n{content_item.text.strip()}"
            except Exception as e:
                # Fallback на простую выжимку
                pass
        
        # Простая выжимка без GPT-5
        if notes:
            # Берем первые 500 символов
            notes_preview = notes[:500].strip()
            if len(notes) > 500:
                notes_preview += "..."
            return f"{name}\n\n{notes_preview}"
        else:
            return name

