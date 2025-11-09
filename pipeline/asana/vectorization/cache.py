"""
Менеджер кеша эмбеддингов
Поддерживает локальный кеш и кеш OpenAI
Обеспечивает переиспользование кеша между запусками
"""
import json
import hashlib
import time
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

# Добавляем корень проекта в путь для импорта
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent.parent.parent.parent  # cache -> vectorization -> asana -> pipeline -> ai-pmtool
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.ai.gpt5_client import get_openai_client


class EmbeddingCache:
    """Менеджер кеша эмбеддингов"""
    
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        use_local_cache: bool = True,
        use_openai_cache: bool = True
    ):
        """
        Инициализация менеджера кеша
        
        Args:
            cache_dir: Директория для локального кеша
            use_local_cache: Использовать локальный кеш
            use_openai_cache: Использовать кеш OpenAI (параметр cache_control)
        """
        self.use_local_cache = use_local_cache
        self.use_openai_cache = use_openai_cache
        self.cache_dir = cache_dir or Path(__file__).parent.parent.parent.parent / "cache" / "embeddings"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.local_cache_file = self.cache_dir / "embeddings_cache.json"
        self.local_cache = self._load_local_cache()
        
        # Статистика использования кеша
        self.cache_stats = {
            'hits': 0,      # Попаданий в кеш
            'misses': 0,    # Промахов (нужно запросить у API)
            'saves': 0      # Сохранений в кеш
        }
        
        # Флаг для отслеживания изменений (чтобы не сохранять без изменений)
        self.cache_modified = False
        
        self.openai_client = None
    
    def _load_local_cache(self) -> Dict[str, Dict[str, Any]]:
        """
        Загружает локальный кеш из файла
        
        Returns:
            Словарь {hash: {embedding, model, text_preview, created_at, last_used_at}}
        """
        if not self.use_local_cache or not self.local_cache_file.exists():
            return {}
        
        try:
            with open(self.local_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                
                # Проверяем формат кеша (может быть старый формат без метаданных)
                if not cache_data:
                    return {}
                
                # Берем первую запись для проверки формата
                first_value = next(iter(cache_data.values()))
                if isinstance(first_value, dict) and 'embedding' in first_value:
                    # Проверяем наличие метаданных
                    if 'created_at' in first_value:
                        # Новый формат с метаданными
                        return cache_data
                    else:
                        # Старый формат - конвертируем
                        converted_cache = {}
                        current_time = time.time()
                        for key, value in cache_data.items():
                            if isinstance(value, dict) and 'embedding' in value:
                                converted_cache[key] = {
                                    **value,
                                    'created_at': current_time,
                                    'last_used_at': current_time
                                }
                        return converted_cache
                else:
                    # Неожиданный формат
                    print(f"      ⚠️  Неожиданный формат кеша, создаем новый")
                    return {}
        except Exception as e:
            print(f"      ⚠️  Ошибка загрузки локального кеша: {e}")
            return {}
    
    def _save_local_cache(self, force: bool = False):
        """
        Сохраняет локальный кеш в файл
        
        Args:
            force: Принудительное сохранение даже если не было изменений
        """
        if not self.use_local_cache:
            return
        
        # Сохраняем только если были изменения или принудительно
        if not force and not self.cache_modified:
            return
        
        try:
            # Создаем резервную копию перед сохранением
            if self.local_cache_file.exists():
                backup_file = self.local_cache_file.with_suffix('.json.backup')
                try:
                    import shutil
                    shutil.copy2(self.local_cache_file, backup_file)
                except Exception:
                    pass  # Игнорируем ошибки резервного копирования
            
            with open(self.local_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.local_cache, f, ensure_ascii=False, indent=2)
            
            self.cache_modified = False
        except Exception as e:
            print(f"      ⚠️  Ошибка сохранения локального кеша: {e}")
    
    def flush_cache(self):
        """Принудительно сохраняет кеш (вызывать перед завершением)"""
        self._save_local_cache(force=True)
    
    def _get_text_hash(self, text: str) -> str:
        """Вычисляет хеш текста для кеша"""
        return hashlib.sha256(text.encode('utf-8')).hexdigest()
    
    def get_embedding(
        self,
        text: str,
        model: str = "text-embedding-3-small",
        client=None
    ) -> Optional[List[float]]:
        """
        Получает эмбеддинг с использованием кеша
        
        Args:
            text: Текст для получения эмбеддинга
            model: Модель для эмбеддингов
            client: OpenAI клиент (если None, создается новый)
            
        Returns:
            Эмбеддинг или None при ошибке
        """
        if not text or not text.strip():
            return None
        
        # Нормализуем текст для кеша
        normalized_text = text.strip()[:8000]  # Ограничение OpenAI
        text_hash = self._get_text_hash(normalized_text)
        
        # Проверяем локальный кеш
        if self.use_local_cache and text_hash in self.local_cache:
            cached_data = self.local_cache[text_hash]
            # Проверяем, что модель совпадает
            if cached_data.get("model") == model:
                # Обновляем время последнего использования
                cached_data["last_used_at"] = time.time()
                self.cache_stats['hits'] += 1
                return cached_data.get("embedding")
        
        # Промах кеша
        self.cache_stats['misses'] += 1
        
        # Если нет в локальном кеше, запрашиваем у OpenAI
        if client is None:
            client = get_openai_client()
        
        try:
            # Используем кеш OpenAI если доступен
            kwargs = {
                "model": model,
                "input": normalized_text
            }
            
            # Добавляем cache_control для кеширования OpenAI
            if self.use_openai_cache:
                # OpenAI cache control (если поддерживается API)
                # Пока используем стандартный вызов, кеш OpenAI работает автоматически
                pass
            
            response = client.embeddings.create(**kwargs)
            embedding = response.data[0].embedding
            
            # Сохраняем в локальный кеш
            if self.use_local_cache:
                current_time = time.time()
                self.local_cache[text_hash] = {
                    "text": normalized_text[:100],  # Сохраняем превью для отладки
                    "model": model,
                    "embedding": embedding,
                    "created_at": current_time,
                    "last_used_at": current_time
                }
                self.cache_stats['saves'] += 1
                self.cache_modified = True
                # Сохраняем периодически (не после каждого запроса)
                if self.cache_stats['saves'] % 10 == 0:
                    self._save_local_cache()
            
            return embedding
        except Exception as e:
            print(f"      ⚠️  Ошибка при получении эмбеддинга: {e}")
            return None
    
    def get_embeddings_batch(
        self,
        texts: List[str],
        model: str = "text-embedding-3-small",
        batch_size: int = 100,
        client=None
    ) -> List[Optional[List[float]]]:
        """
        Получает эмбеддинги для списка текстов батчами с использованием кеша
        
        Args:
            texts: Список текстов
            model: Модель для эмбеддингов
            batch_size: Размер батча
            client: OpenAI клиент
            
        Returns:
            Список эмбеддингов (может содержать None для ошибок)
        """
        if client is None:
            client = get_openai_client()
        
        embeddings = []
        
        # Обрабатываем батчами
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_embeddings = []
            
            # Проверяем кеш для каждого текста в батче
            texts_to_fetch = []
            indices_to_fetch = []
            
            for idx, text in enumerate(batch_texts):
                if not text or not text.strip():
                    batch_embeddings.append(None)
                    continue
                
                normalized_text = text.strip()[:8000]
                text_hash = self._get_text_hash(normalized_text)
                
                # Проверяем локальный кеш
                if self.use_local_cache and text_hash in self.local_cache:
                    cached_data = self.local_cache[text_hash]
                    if cached_data.get("model") == model:
                        # Обновляем время последнего использования
                        cached_data["last_used_at"] = time.time()
                        batch_embeddings.append(cached_data.get("embedding"))
                        self.cache_stats['hits'] += 1
                        continue
                
                # Промах кеша
                self.cache_stats['misses'] += 1
                
                # Нужно запросить у OpenAI
                texts_to_fetch.append(normalized_text)
                indices_to_fetch.append(idx)
                batch_embeddings.append(None)  # Заполнитель
            
            # Запрашиваем эмбеддинги для текстов без кеша
            if texts_to_fetch:
                try:
                    response = client.embeddings.create(
                        model=model,
                        input=texts_to_fetch
                    )
                    
                    # Заполняем эмбеддинги и сохраняем в кеш
                    for idx, embedding_item in enumerate(response.data):
                        original_idx = indices_to_fetch[idx]
                        embedding = embedding_item.embedding
                        batch_embeddings[original_idx] = embedding
                        
                        # Сохраняем в локальный кеш
                        if self.use_local_cache:
                            text = texts_to_fetch[idx]
                            text_hash = self._get_text_hash(text)
                            current_time = time.time()
                            self.local_cache[text_hash] = {
                                "text": text[:100],
                                "model": model,
                                "embedding": embedding,
                                "created_at": current_time,
                                "last_used_at": current_time
                            }
                            self.cache_stats['saves'] += 1
                            self.cache_modified = True
                    
                    # Сохраняем кеш периодически (не после каждого батча для оптимизации)
                    if self.use_local_cache and self.cache_stats['saves'] % 50 == 0:
                        self._save_local_cache()
                except Exception as e:
                    print(f"      ⚠️  Ошибка при получении эмбеддингов батча {i//batch_size + 1}: {e}")
                    # Оставляем None для ошибок
            
            embeddings.extend(batch_embeddings)
        
        return embeddings
    
    def clear_cache(self, older_than_days: Optional[int] = None):
        """
        Очищает кеш
        
        Args:
            older_than_days: Очистить только записи старше N дней (None = очистить все)
        """
        if older_than_days:
            # Очистка по возрасту
            current_time = time.time()
            threshold_time = current_time - (older_than_days * 86400)
            
            to_remove = []
            for key, entry in self.local_cache.items():
                if isinstance(entry, dict):
                    created_at = entry.get('created_at', current_time)
                    if created_at < threshold_time:
                        to_remove.append(key)
            
            for key in to_remove:
                del self.local_cache[key]
            
            self.cache_modified = True
            self._save_local_cache(force=True)
            print(f"      ✅ Очищено {len(to_remove)} записей старше {older_than_days} дней")
        else:
            self.local_cache = {}
            self.cache_stats = {'hits': 0, 'misses': 0, 'saves': 0}
            self.cache_modified = True
            self._save_local_cache(force=True)
            print(f"      ✅ Локальный кеш очищен")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Возвращает статистику кеша
        
        Returns:
            Словарь со статистикой использования кеша
        """
        total_requests = self.cache_stats['hits'] + self.cache_stats['misses']
        hit_rate = (self.cache_stats['hits'] / total_requests * 100) if total_requests > 0 else 0
        
        # Подсчитываем возраст записей
        current_time = time.time()
        ages = []
        for entry in self.local_cache.values():
            if isinstance(entry, dict) and 'created_at' in entry:
                age_days = (current_time - entry['created_at']) / 86400
                ages.append(age_days)
        
        return {
            "local_cache_size": len(self.local_cache),
            "cache_file": str(self.local_cache_file),
            "use_local_cache": self.use_local_cache,
            "use_openai_cache": self.use_openai_cache,
            "cache_hits": self.cache_stats['hits'],
            "cache_misses": self.cache_stats['misses'],
            "cache_saves": self.cache_stats['saves'],
            "hit_rate_percent": round(hit_rate, 2),
            "avg_entry_age_days": round(sum(ages) / len(ages), 1) if ages else 0,
            "oldest_entry_days": round(max(ages), 1) if ages else 0
        }
    
    def print_cache_stats(self):
        """Выводит статистику использования кеша"""
        stats = self.get_cache_stats()
        print(f"\n   💾 Статистика кеша эмбеддингов:")
        print(f"      Размер кеша: {stats['local_cache_size']} записей")
        print(f"      Попаданий (hits): {stats['cache_hits']}")
        print(f"      Промахов (misses): {stats['cache_misses']}")
        print(f"      Сохранений: {stats['cache_saves']}")
        if stats['hit_rate_percent'] > 0:
            print(f"      Hit rate: {stats['hit_rate_percent']:.1f}%")
        if stats['avg_entry_age_days'] > 0:
            print(f"      Средний возраст записей: {stats['avg_entry_age_days']:.1f} дней")

