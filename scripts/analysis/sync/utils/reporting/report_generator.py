#!/usr/bin/env python3
"""
Модуль для генерации отчетов о синхронизации задач
"""
import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
from datetime import datetime

from ..extractors.context_extractor import AsanaContextExtractor
from ..transformers.task_transformer import enrich_asana_task_with_telegram


def analyze_coverage(
    matches: List[Tuple[Dict, Dict, float]],
    telegram_tasks: List[Dict[str, Any]],
    asana_tasks: List[Dict[str, Any]],
    context_extractor: AsanaContextExtractor
) -> Dict[str, Any]:
    """
    Анализ покрытия: что из Telegram уже реализовано в Asana
    
    Args:
        matches: Список совпадений (tg_task, asana_task, score)
        telegram_tasks: Все задачи из Telegram
        asana_tasks: Все задачи из Asana
        context_extractor: Экстрактор контекста для задач Asana
        
    Returns:
        Словарь с анализом покрытия
    """
    coverage = {
        'total_telegram_tasks': len(telegram_tasks),
        'covered_tasks': len(matches),
        'coverage_percentage': (len(matches) / len(telegram_tasks) * 100) if telegram_tasks else 0,
        'implementation_status': {
            'completed_in_asana': 0,
            'in_progress_in_asana': 0,
            'not_started_in_asana': 0
        },
        'detailed_matches': []
    }
    
    for tg_task, asana_task, score in matches:
        asana_completed = asana_task.get('completed', False)
        tg_status = tg_task.get('status', '')
        
        # Определяем статус реализации
        if asana_completed:
            status = 'completed_in_asana'
            coverage['implementation_status']['completed_in_asana'] += 1
        elif tg_status == 'в процессе' or not asana_completed:
            status = 'in_progress_in_asana'
            coverage['implementation_status']['in_progress_in_asana'] += 1
        else:
            status = 'not_started_in_asana'
            coverage['implementation_status']['not_started_in_asana'] += 1
        
        # Извлекаем контекст Asana для анализа
        asana_context = context_extractor.extract_asana_task_context(asana_task)
        
        coverage['detailed_matches'].append({
            'telegram_title': tg_task.get('title', ''),
            'asana_name': asana_task.get('name', ''),
            'similarity_score': score,
            'implementation_status': status,
            'asana_summary': asana_context['summary'][:300],
            'has_implementation_details': len(asana_context['implementation_details']) > 0,
            'asana_has_notes': asana_context['has_notes']
        })
    
    return coverage


def generate_sync_report(
    matching_result: Dict[str, List],
    output_file: Path,
    context_extractor: AsanaContextExtractor
) -> Dict[str, Any]:
    """
    Генерировать отчет о синхронизации с анализом покрытия
    
    Args:
        matching_result: Результат сопоставления задач
        output_file: Путь к файлу для сохранения отчета
        context_extractor: Экстрактор контекста для задач Asana
        
    Returns:
        Словарь с отчетом о синхронизации
    """
    coverage = matching_result.get('coverage', {})
    
    report = {
        'timestamp': datetime.now().isoformat(),
        'summary': {
            'total_telegram_tasks': len(matching_result['matches']) + len(matching_result['telegram_only']),
            'total_asana_tasks': len(matching_result['matches']) + len(matching_result['asana_only']),
            'matched_tasks': len(matching_result['matches']),
            'telegram_only': len(matching_result['telegram_only']),
            'asana_only': len(matching_result['asana_only']),
            'coverage_percentage': coverage.get('coverage_percentage', 0)
        },
        'coverage_analysis': coverage,
        'matches': [
            {
                'telegram_task': match[0],
                'asana_task': {
                    'gid': match[1].get('gid'),
                    'name': match[1].get('name'),
                    'notes': match[1].get('notes', '')[:200] + '...' if len(match[1].get('notes', '')) > 200 else match[1].get('notes', '')
                },
                'similarity_score': match[2],
                'recommended_updates': enrich_asana_task_with_telegram(match[1], match[0]),
                'asana_context': context_extractor.extract_asana_task_context(match[1])  # Добавляем контекстную выжимку
            }
            for match in matching_result['matches']
        ],
        'telegram_only': matching_result['telegram_only'],
        'asana_only': [
            {
                'gid': task.get('gid'),
                'name': task.get('name'),
                'notes': task.get('notes', '')[:200] + '...' if len(task.get('notes', '')) > 200 else task.get('notes', '')
            }
            for task in matching_result['asana_only']
        ]
    }
    
    # Сохраняем отчет в файл
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    
    return report

