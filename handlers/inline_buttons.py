"""
Обработчик inline-кнопок (слова-ссылки в тексте)
"""
import re
from typing import List, Dict
from core.logger import get_logger

logger = get_logger(__name__)


def parse_inline_links(text: str) -> List[Dict]:
    links = []
    pattern = r'\[(.+?)\]\((https?://[^\s)]+)\)'
    for match in re.finditer(pattern, text):
        links.append({"text": match.group(1), "url": match.group(2)})
    return links


def apply_inline_links(text: str) -> str:
    pattern = r'\[(.+?)\]\((https?://[^\s)]+)\)'
    return re.sub(pattern, r'<a href="\2">\1</a>', text)


async def handle_inline_text(user_id, text, send, state, max_client=None):
    logger.info(f"[INLINE-TEXT] user={user_id}")
    
    session = state.get_session_data(user_id)
    links = parse_inline_links(text)
    
    if links:
        current_text = session.get('text', '')
        inline_block = '\n\n🔗 Полезные ссылки:\n'
        for link in links:
            inline_block += f'• [{link["text"]}]({link["url"]})\n'
        
        session['text'] = current_text + inline_block
        session['text'] = apply_inline_links(session['text'])
        session['inline_links'] = links
    
    state.set_step(user_id, 'post_waiting_buttons')
    await send(
        "<b>✅ Ссылки добавлены</b>\n\n"
        "<b>🔘 Шаг 4/4: Добавьте URL-кнопки</b>\n\n"
        "Вручную: <code>Название | https://url</code>\n"
        "📋 /btn_use — использовать шаблоны\n\n"
        "─────────────────\n"
        "⏭ /skip — пропустить\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_use(user_id, send, state, max_client=None):
    logger.info(f"[INLINE-USE] user={user_id}")
    
    from handlers.templates import load_inline_templates
    templates = load_inline_templates(user_id)
    
    if not templates:
        await send(
            "❌ Нет сохранённых шаблонов\n\n"
            "Введите вручную: <code>[слово](https://url)</code>\n\n"
            "─────────────────\n"
            "⏭ /skip | ❌ /cancel"
        )
        return
    
    # 🔥 Предпросмотр с КЛИКАБЕЛЬНЫМИ ссылками
    preview_text = "<b>👁 Предпросмотр ссылок:</b>\n🔗 Полезные ссылки:\n"
    for t in templates:
        preview_text += f"• <a href=\"{t['url']}\">{t['text']}</a>\n"
    
    preview_text += "\n─────────────────\n"
    preview_text += "✅ /inline_yes — добавить\n"
    preview_text += "❌ /skip — пропустить"
    
    await send(preview_text)
    state.set_step(user_id, 'post_waiting_inline_confirm', {'pending_inline': templates})


async def handle_inline_confirm(user_id, send, state, max_client=None):
    logger.info(f"[INLINE-CONFIRM] user={user_id}")
    
    session = state.get_session_data(user_id)
    templates = session.get('pending_inline', [])
    
    if not templates:
        await send("❌ Нет данных")
        state.set_step(user_id, 'post_waiting_buttons')
        return
    
    current_text = session.get('text', '')
    inline_block = '\n\n🔗 Полезные ссылки:\n'
    for t in templates:
        inline_block += f'• [{t["text"]}]({t["url"]})\n'
    
    session['text'] = (current_text + inline_block) if current_text else inline_block
    session['text'] = apply_inline_links(session['text'])
    session['inline_links'] = templates
    session.pop('pending_inline', None)
    
    state.set_step(user_id, 'post_waiting_buttons')
    await send(
        f"<b>✅ Добавлено {len(templates)} ссылок</b>\n\n"
        "<b>🔘 Шаг 4/4: Добавьте URL-кнопки</b>\n\n"
        "Вручную: <code>Название | https://url</code>\n"
        "📋 /btn_use — шаблоны\n\n"
        "─────────────────\n"
        "⏭ /skip — пропустить\n"
        "❌ /cancel — отмена"
    )
