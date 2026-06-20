"""
Коллектор статистики
"""
import json
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f).get('messages', {})
                logger.info(f"[STATS] Loaded {len(self.stats)} records")
            except Exception as e:
                logger.error(f"[STATS] Load error: {e}")
    
    def _save(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump({'messages': self.stats}, f, indent=2)
        except Exception as e:
            logger.error(f"[STATS] Save error: {e}")
    
    def record_message(self, message_id: str, chat_id: str, text: str, published_at: str):
        self.stats[message_id] = {
            'chat_id': chat_id,
            'text_preview': text[:100],
            'published_at': published_at,
            'views': 0
        }
        self._save()
        logger.info(f"[STATS] Recorded msg_id={message_id}")
    
    def get_stats(self, message_id=None):
        if message_id:
            return self.stats.get(message_id, {})
        return [{'message_id': mid, **data} for mid, data in self.stats.items()]
