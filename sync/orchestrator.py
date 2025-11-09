#!/usr/bin/env python3
"""
Оркестратор синхронизации задач между Telegram и Asana
"""
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

# Добавляем корень проекта в путь
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from shared.ai.gpt5_client import get_openai_client
from pipeline.telegram.vectorization.embeddings import get_embedding, cosine_similarity_embedding
from pipeline.asana.matching.time_windows import TimeWindowMatcher
from pipeline.asana.vectorization.cache import EmbeddingCache
from pipeline.asana.summarization.summarizer import AsanaTaskSummarizer
from pipeline.asana.matching.semantic_search import AsanaContextExtractor, normalize_text
from pipeline.asana.matching.similarity import calculate_similarity_gpt5
from sync.transformer import enrich_asana_task_with_telegram, create_asana_task_from_telegram
from sync.reporter import analyze_coverage, generate_sync_report
from sync.loader import load_telegram_tasks, load_telegram_projects
from sync.matcher import find_matching_tasks


# Конфигурация Asana
ASANA_WORKSPACE_GID = "624391999090674"
ASANA_USER_GID = "1169547205416171"
ASANA_PROJECT_GID = "1210655252186716"  # Фарма+
ASANA_ESTIMATED_TIME_FIELD_GID = "1204112099563346"


class AsanaSync:
    """Класс для синхронизации задач между Telegram и Asana"""
    
    def __init__(
        self,
        mcp_client=None,
        openai_client=None,
        use_time_windows: bool = True,
        use_embedding_cache: bool = True,
        use_task_summarization: bool = True
    ):
        """
        Инициализация синхронизатора
        
        Args:
            mcp_client: Клиент MCP для работы с Asana API
            openai_client: Клиент OpenAI для семантического сравнения
            use_time_windows: Использовать временные окна для фильтрации задач
            use_embedding_cache: Использовать кеш эмбеддингов
            use_task_summarization: Использовать предварительную суммаризацию задач через GPT-5
        """
        self.mcp_client = mcp_client
        self.openai_client = openai_client or get_openai_client()
        self.workspace_gid = ASANA_WORKSPACE_GID
        self.project_gid = ASANA_PROJECT_GID
        self.use_time_windows = use_time_windows
        self.time_window_matcher = TimeWindowMatcher() if use_time_windows else None
        self.embedding_cache = EmbeddingCache(use_local_cache=use_embedding_cache) if use_embedding_cache else None
        self.use_task_summarization = use_task_summarization
        self.task_summarizer = AsanaTaskSummarizer(client=self.openai_client) if use_task_summarization else None
        # Кеш суммаризированных задач для текущей сессии
        self._summarized_tasks_cache = {}
        # Инициализируем экстрактор контекста
        self.context_extractor = AsanaContextExtractor(
            task_summarizer=self.task_summarizer,
            summarized_tasks_cache=self._summarized_tasks_cache
        )
        
    def load_telegram_tasks(self, tasks_file: Path) -> List[Dict[str, Any]]:
        """Загрузить задачи из Telegram анализа"""
        return load_telegram_tasks(tasks_file)
    
    def load_telegram_projects(self, projects_file: Path) -> List[Dict[str, Any]]:
        """Загрузить проекты из Telegram анализа"""
        return load_telegram_projects(projects_file)
    
    def normalize_text(self, text: str) -> str:
        """Нормализация текста для сравнения"""
        return normalize_text(text)
    
    def extract_asana_task_context(self, asana_task: Dict[str, Any]) -> Dict[str, Any]:
        """Извлечь контекстную выжимку из задачи Asana"""
        return self.context_extractor.extract_asana_task_context(asana_task)
    
    def create_asana_task_summary(self, asana_task: Dict[str, Any], use_gpt5: bool = False) -> str:
        """Создать краткую выжимку задачи Asana"""
        return self.context_extractor.create_asana_task_summary(
            asana_task,
            openai_client=self.openai_client if use_gpt5 else None,
            use_gpt5=use_gpt5
        )
    
    def calculate_similarity(self, text1: str, text2: str, verbose: bool = False) -> float:
        """Вычисление семантической схожести через GPT-5"""
        return calculate_similarity_gpt5(text1, text2, self.openai_client, verbose)
    
    def find_matching_tasks(
        self,
        telegram_tasks: List[Dict[str, Any]],
        asana_tasks: List[Dict[str, Any]],
        similarity_threshold: float = 0.75,
        verbose: bool = True,
        use_embeddings: bool = True,
        use_gpt5_verification: bool = False,
        low_threshold: float = 0.65,
        use_two_stage_matching: bool = True
    ) -> Dict[str, List]:
        """
        Поиск совпадений с использованием временных окон и кеша эмбеддингов
        
        Делегирует в sync.matcher.find_matching_tasks
        """
        return find_matching_tasks(
            self,
            telegram_tasks,
            asana_tasks,
            similarity_threshold=similarity_threshold,
            verbose=verbose,
            use_embeddings=use_embeddings,
            use_gpt5_verification=use_gpt5_verification,
            low_threshold=low_threshold,
            use_two_stage_matching=use_two_stage_matching
        )
    
    def generate_sync_report(
        self,
        matching_result: Dict[str, List],
        output_file: Path
    ):
        """Генерировать отчет о синхронизации"""
        return generate_sync_report(matching_result, output_file, self.context_extractor)
    
    def enrich_asana_task_with_telegram(
        self,
        asana_task: Dict[str, Any],
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Дополнить задачу из Asana данными из Telegram"""
        return enrich_asana_task_with_telegram(asana_task, telegram_task)
    
    def create_asana_task_from_telegram(
        self,
        telegram_task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Подготовить данные для создания задачи в Asana"""
        return create_asana_task_from_telegram(
            telegram_task,
            workspace_gid=self.workspace_gid,
            project_gid=self.project_gid,
            assignee_gid=ASANA_USER_GID
        )

