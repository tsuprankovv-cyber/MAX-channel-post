"""
Парсинг URL-кнопок
"""
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)


def parse_buttons(text: str) -> List[List[Dict]]:
    """
    Парсит: Название | https://url | стиль(опционально)
    Поддерживает стили: primary, secondary, success, danger, warning
    Или HEX-цвет: #FF6600
    """
    logger.info(f"[BTN] Parsing: '{text[:150]}...'")
    rows = []
    
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        
        for sep in [' | ', ' - ', ' → ']:
            if sep in line:
                parts = line.split(sep)
                
                if len(parts) >= 2:
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    
                    if btn_text and btn_url.startswith(('http://', 'https://')):
                        btn_data = {"type": "link", "text": btn_text, "url": btn_url}
                        
                        # Проверяем стиль (третий параметр)
                        if len(parts) >= 3:
                            style = parts[2].strip().lower()
                            valid_styles = ['primary', 'secondary', 'success', 'danger', 'warning']
                            if style in valid_styles:
                                btn_data['style'] = style
                                logger.info(f"[BTN] Style: {style}")
                            elif style.startswith('#'):
                                btn_data['color'] = style
                                logger.info(f"[BTN] Color: {style}")
                        
                        rows.append([btn_data])
                        logger.info(f"[BTN] ✅ '{btn_text}' → {btn_url[:50]}...")
                        break
    
    logger.info(f"[BTN] Total: {len(rows)} rows")
    return rows
