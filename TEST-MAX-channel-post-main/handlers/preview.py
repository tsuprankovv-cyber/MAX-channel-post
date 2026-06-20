"""
Предпросмотр поста
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def send_preview(user_id, send, state, max_client=None):
    logger.info(f"[PREVIEW] user={user_id}")
    
    draft = state.get_draft(user_id)
    if draft is None:
        logger.warning(f"[PREVIEW] No draft")
        await send("❌ Нет черновика")
        return
    
    text = draft.get('text', '')
    buttons = draft.get('buttons', [])
    attachments = draft.get('attachments', [])
    
    logger.info(f"[PREVIEW] text='{text[:50]}...' buttons={len(buttons)} attachments={len(attachments)}")
    
    chat_id = state.get_session(user_id).get('chat_id', user_id)
    
    # 🔥 Всегда отправляем с HTML-форматом
    if max_client:
        logger.info(f"[PREVIEW] Sending full preview with media")
        await max_client.send_message(
            chat_id=chat_id,
            text=text or "Предпросмотр",
            buttons=buttons,
            attachments=[{'type': a['type'], 'payload': a['payload']} for a in attachments if a.get('payload')],
            use_html_format=True  # 🔥 Всегда True
        )
    else:
        logger.info(f"[PREVIEW] No max_client, sending text only")
        if text:
            await send(text)
    
    # Команды под чертой
    await send(
        "─────────────────\n"
        "🚀 /publish — опубликовать\n"
        "✏️ /edit — редактировать\n"
        "❌ /cancel — отмена"
    )
