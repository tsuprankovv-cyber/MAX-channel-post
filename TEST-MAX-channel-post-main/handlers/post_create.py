"""
Создание поста: шаги фото → текст → слова-ссылки → кнопки
"""
from core.formatter import markup_to_html
from handlers.buttons import parse_buttons
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_post_command(user_id, send, auth, state):
    if not auth.is_authorized(user_id):
        await send("🔐 /start")
        return
    
    state.clear_session(user_id)
    state.set_step(user_id, 'post_waiting_photo')
    await send(
        "<b>📸 Шаг 1/4: Отправьте фото/видео</b>\n\n"
        "Просто прикрепите файл к сообщению.\n\n"
        "─────────────────\n"
        "⏭ /skip — пропустить\n"
        "❌ /cancel — отмена"
    )


async def handle_post_photo(user_id, raw_attachments, send, state, media_mgr):
    session = state.get_session_data(user_id)
    attachments = media_mgr.parse_attachments(raw_attachments)
    session['raw_attachments'] = raw_attachments
    session['attachments'] = attachments
    state.set_step(user_id, 'post_waiting_text')
    await send(
        f"<b>✅ Фото ({len(attachments)} шт.)</b>\n\n"
        "<b>📝 Шаг 2/4: Напишите текст</b>\n\n"
        "Используйте форматирование MAX.\n\n"
        "─────────────────\n"
        "⏭ /skip | ❌ /cancel"
    )


async def handle_post_text(user_id, text, markup, raw_attachments, send, state, media_mgr):
    session = state.get_session_data(user_id)
    
    if raw_attachments:
        new = media_mgr.parse_attachments(raw_attachments)
        session['attachments'] = session.get('attachments', []) + new
        session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
    
    session['text'] = markup_to_html(text, markup) if markup else text
    session['raw_text'] = text
    session['markup'] = markup
    
    state.set_step(user_id, 'post_waiting_inline')
    await send(
        "<b>✅ Текст сохранён</b>\n\n"
        "<b>🔗 Шаг 3/4: Добавьте слова-ссылки</b>\n\n"
        "Вручную: <code>[слово](https://url)</code>\n"
        "📋 /inline_use — использовать шаблоны\n\n"
        "─────────────────\n"
        "⏭ /skip | ❌ /cancel"
    )


async def handle_post_buttons(user_id, buttons_text, send, state, max_client=None):
    session = state.get_session_data(user_id)
    session['buttons'] = parse_buttons(buttons_text)
    state.save_draft(user_id, session.copy())
    state.set_step(user_id, 'post_ready')
    from handlers.preview import send_preview
    await send_preview(user_id, send, state, max_client)


async def handle_skip(user_id, send, state):
    step = state.get_step(user_id)
    
    if step == 'post_waiting_photo':
        state.set_step(user_id, 'post_waiting_text')
        await send("<b>📝 Шаг 2/4: Напишите текст</b>\n\n─────────────────\n⏭ /skip | ❌ /cancel")
    
    elif step == 'post_waiting_text':
        state.set_step(user_id, 'post_waiting_inline')
        await send("<b>🔗 Шаг 3/4: Слова-ссылки</b>\n\nВручную: <code>[слово](url)</code>\n📋 /inline_use — шаблоны\n\n─────────────────\n⏭ /skip | ❌ /cancel")
    
    elif step == 'post_waiting_inline':
        state.set_step(user_id, 'post_waiting_buttons')
        await send("<b>🔘 Шаг 4/4: URL-кнопки</b>\n\nВручную: <code>Название | url</code>\n📋 /btn_use — шаблоны\n\n─────────────────\n⏭ /skip | ❌ /cancel")
    
    elif step == 'post_waiting_inline_confirm':
        state.set_step(user_id, 'post_waiting_buttons')
        await send("<b>🔘 Шаг 4/4: URL-кнопки</b>\n\n📋 /btn_use — шаблоны\n\n─────────────────\n⏭ /skip | ❌ /cancel")
    
    elif step in ('post_waiting_buttons', 'post_waiting_buttons_confirm'):
        session = state.get_session_data(user_id)
        session['buttons'] = []
        session.pop('pending_buttons', None)
        state.save_draft(user_id, session.copy())
        state.set_step(user_id, 'post_ready')
        from handlers.preview import send_preview
        await send_preview(user_id, send, state)
    
    elif step == 'post_ready':
        from handlers.preview import send_preview
        await send_preview(user_id, send, state)
