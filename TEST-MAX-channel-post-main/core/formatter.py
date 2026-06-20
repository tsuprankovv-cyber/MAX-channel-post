"""
Конвертация MAX markup → HTML (format=html)
"""
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)

TAG_MAP = {
    "strong": "b", "bold": "b",
    "emphasized": "i", "italic": "i", "em": "i",
    "underline": "u",
    "strikethrough": "s", "strike": "s",
    "code": "code",
    "spoiler": "tg-spoiler",
    "link": "a", "text_link": "a",
}


def _correct_offsets(text: str, markup: List[Dict]) -> List[Dict]:
    if not markup:
        return []
    corrected = []
    for entity in markup:
        entity = entity.copy()
        max_offset = entity.get('from', 0)
        max_length = entity.get('length', 0)
        
        py_offset = 0
        utf16_pos = 0
        for i, char in enumerate(text):
            if utf16_pos >= max_offset:
                py_offset = i
                break
            utf16_pos += len(char.encode('utf-16-le')) // 2
        else:
            py_offset = len(text)
        
        py_length = 0
        utf16_pos = max_offset
        for i in range(py_offset, len(text)):
            if utf16_pos >= max_offset + max_length:
                break
            utf16_pos += len(text[i].encode('utf-16-le')) // 2
            py_length += 1
        
        entity['from'] = py_offset
        entity['length'] = py_length
        corrected.append(entity)
    return corrected


def markup_to_html(text: str, markup: List[Dict]) -> str:
    if not markup:
        return text
    
    logger.info(f"[FORMAT] Converting {len(markup)} entities")
    
    corrected = _correct_offsets(text, markup)
    sorted_markup = sorted(corrected, key=lambda m: (m.get('from', 0), -m.get('length', 0)))
    
    filtered = []
    for i, entity in enumerate(sorted_markup):
        etype = entity.get('type', '')
        offset = entity.get('from', 0)
        end = offset + entity.get('length', 0)
        is_nested = False
        for j, other in enumerate(sorted_markup):
            if i == j or other.get('type') != etype:
                continue
            o_offset = other.get('from', 0)
            o_end = o_offset + other.get('length', 0)
            if o_offset <= offset and o_end >= end and (o_offset < offset or o_end > end):
                is_nested = True
                break
        if not is_nested:
            filtered.append(entity)
    
    tag_starts = {}
    tag_ends = {}
    
    for entity in filtered:
        offset = entity.get('from', 0)
        length = entity.get('length', 0)
        etype = entity.get('type', '')
        
        if etype not in TAG_MAP:
            continue
        
        tag_name = TAG_MAP[etype]
        
        if etype in ('link', 'text_link'):
            url = entity.get('url', '').replace('"', '&quot;')
            open_tag = f'<{tag_name} href="{url}">' if url else f'<{tag_name}>'
        else:
            open_tag = f'<{tag_name}>'
        
        close_tag = f'</{tag_name}>'
        
        tag_starts.setdefault(offset, []).append(open_tag)
        tag_ends.setdefault(offset + length, []).append(close_tag)
    
    result = []
    for i, char in enumerate(text):
        if i in tag_ends:
            for tag in tag_ends[i]:
                result.append(tag)
        if i in tag_starts:
            for tag in tag_starts[i]:
                result.append(tag)
        result.append(char)
    
    last_pos = len(text)
    if last_pos in tag_ends:
        for tag in tag_ends[last_pos]:
            result.append(tag)
    
    final = ''.join(result)
    logger.info(f"[FORMAT] '{final[:100]}...'")
    return final
