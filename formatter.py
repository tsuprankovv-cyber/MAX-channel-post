"""
Парсер вложений MAX
"""
from typing import List, Dict
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        logger.info(f"[MEDIA] Initialized max={max_items}")
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        logger.info(f"[MEDIA] Parsing {len(attachments)} attachments")
        result = []
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                result.append({
                    'type': att_type,
                    'payload': payload.copy(),
                    'url': payload.get('url', ''),
                    'filename': payload.get('filename', f'file_{i}'),
                    'index': i
                })
                logger.info(f"[MEDIA] [{i}] {att_type}")
        logger.info(f"[MEDIA] ✅ {len(result)}/{len(attachments)}")
        return result
