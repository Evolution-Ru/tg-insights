"""
Разбиение потоков на части по датам и размеру
"""
from typing import List, Dict, Any


def split_thread_by_dates(thread_text: str, max_chunk_size: int = 10000) -> List[Dict[str, Any]]:
    """
    Разбивает поток на части по датам и размеру.
    Возвращает список словарей с информацией о каждой части:
    {
        'chunk': текст части,
        'first_date': первая дата в части (YYYY-MM-DD),
        'last_date': последняя дата в части (YYYY-MM-DD),
        'date_range': список всех дат в части
    }
    """
    lines = thread_text.split('\n')
    date_boundaries = []  # [(index, date_str)]
    
    # Находим все даты и их индексы
    for i, line in enumerate(lines):
        if line.startswith('📅 '):
            date_str = line.replace('📅 ', '').strip()[:10]  # YYYY-MM-DD
            date_boundaries.append((i, date_str))
    
    if not date_boundaries:
        # Если нет дат, разбиваем просто по размеру
        chunks_meta = []
        current_chunk_lines = []
        current_size = 0
        for line in lines:
            line_size = len(line) + 1
            if current_size + line_size > max_chunk_size and current_chunk_lines:
                chunks_meta.append({
                    'chunk': '\n'.join(current_chunk_lines),
                    'first_date': None,
                    'last_date': None,
                    'date_range': []
                })
                current_chunk_lines = [line]
                current_size = line_size
            else:
                current_chunk_lines.append(line)
                current_size += line_size
        if current_chunk_lines:
            chunks_meta.append({
                'chunk': '\n'.join(current_chunk_lines),
                'first_date': None,
                'last_date': None,
                'date_range': []
            })
        return chunks_meta
    
    # Разбиваем по датам - это делает границы стабильными
    chunks_meta = []
    current_chunk_lines = []
    current_size = 0
    current_dates = []  # Список дат в текущем чанке
    
    date_idx = 0
    for i, line in enumerate(lines):
        line_size = len(line) + 1
        
        # Проверяем, начинается ли новая дата
        is_new_date = False
        current_date_str = None
        if date_idx < len(date_boundaries) and i == date_boundaries[date_idx][0]:
            is_new_date = True
            current_date_str = date_boundaries[date_idx][1]
            date_idx += 1
        
        # Если начинается новая дата и текущий чанк уже достаточно большой, завершаем его
        if is_new_date and current_size > max_chunk_size * 0.7 and current_chunk_lines:
            chunks_meta.append({
                'chunk': '\n'.join(current_chunk_lines),
                'first_date': current_dates[0] if current_dates else None,
                'last_date': current_dates[-1] if current_dates else None,
                'date_range': current_dates.copy()
            })
            current_chunk_lines = [line]
            current_size = line_size
            current_dates = [current_date_str] if current_date_str else []
            continue
        
        # Если добавление строки превысит лимит
        if current_size + line_size > max_chunk_size and current_chunk_lines:
            # Если это новая дата, начинаем новый чанк с неё
            if is_new_date:
                chunks_meta.append({
                    'chunk': '\n'.join(current_chunk_lines),
                    'first_date': current_dates[0] if current_dates else None,
                    'last_date': current_dates[-1] if current_dates else None,
                    'date_range': current_dates.copy()
                })
                current_chunk_lines = [line]
                current_size = line_size
                current_dates = [current_date_str] if current_date_str else []
            else:
                # Ищем ближайшую предыдущую дату и завершаем чанк после неё
                last_date_in_chunk = None
                for j in range(len(current_chunk_lines) - 1, -1, -1):
                    if current_chunk_lines[j].startswith('📅 '):
                        last_date_in_chunk = j
                        break
                
                if last_date_in_chunk is not None:
                    # Завершаем чанк после последней даты
                    chunk_to_save = current_chunk_lines[:last_date_in_chunk + 1]
                    # Определяем даты в сохраняемом чанке
                    saved_dates = []
                    for l in chunk_to_save:
                        if l.startswith('📅 '):
                            date_str = l.replace('📅 ', '').strip()[:10]
                            if date_str not in saved_dates:
                                saved_dates.append(date_str)
                    
                    chunks_meta.append({
                        'chunk': '\n'.join(chunk_to_save),
                        'first_date': saved_dates[0] if saved_dates else None,
                        'last_date': saved_dates[-1] if saved_dates else None,
                        'date_range': saved_dates
                    })
                    # Начинаем новый чанк с оставшихся строк
                    current_chunk_lines = current_chunk_lines[last_date_in_chunk + 1:] + [line]
                    current_size = sum(len(l) + 1 for l in current_chunk_lines)
                    # Обновляем список дат для нового чанка
                    current_dates = []
                    for l in current_chunk_lines:
                        if l.startswith('📅 '):
                            date_str = l.replace('📅 ', '').strip()[:10]
                            if date_str not in current_dates:
                                current_dates.append(date_str)
                else:
                    # Если даты нет, просто завершаем чанк
                    current_chunk_lines.append(line)
                    chunks_meta.append({
                        'chunk': '\n'.join(current_chunk_lines),
                        'first_date': current_dates[0] if current_dates else None,
                        'last_date': current_dates[-1] if current_dates else None,
                        'date_range': current_dates.copy()
                    })
                    current_chunk_lines = []
                    current_size = 0
                    current_dates = []
        else:
            current_chunk_lines.append(line)
            current_size += line_size
            if is_new_date and current_date_str:
                if current_date_str not in current_dates:
                    current_dates.append(current_date_str)
    
    # Добавляем последний чанк
    if current_chunk_lines:
        chunks_meta.append({
            'chunk': '\n'.join(current_chunk_lines),
            'first_date': current_dates[0] if current_dates else None,
            'last_date': current_dates[-1] if current_dates else None,
            'date_range': current_dates.copy()
        })
    
    return chunks_meta

