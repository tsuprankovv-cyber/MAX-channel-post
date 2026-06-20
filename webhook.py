"""
Вспомогательные утилиты
"""
from datetime import datetime
from typing import List
from config.settings import LOG_FILE


def read_logs_by_period(start_time: datetime, end_time: datetime) -> List[str]:
    """Читает логи за период"""
    lines = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log_time = datetime.strptime(line[:19], "%Y-%m-%d %H:%M:%S")
                    if start_time <= log_time <= end_time:
                        lines.append(line)
                except:
                    continue
    except FileNotFoundError:
        pass
    return lines


def read_logs_last_lines(count: int) -> List[str]:
    """Читает последние N строк"""
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
        return all_lines[-count:]
    except FileNotFoundError:
        return []


def split_text(text: str, max_chars: int = 3000) -> List[str]:
    """Разбивает текст на части"""
    parts = []
    while len(text) > max_chars:
        split_at = text.rfind('\n', 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        parts.append(text[:split_at])
        text = text[split_at:]
    parts.append(text)
    return parts
