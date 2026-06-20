"""
Публикация поста
"""
from datetime import datetime
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_publish(user_id, send, state, max_client, scheduler, stats, channel_id, 
                        immediate=True, schedule_time=None):
    logger.info(f"[PUBLISH] user={user_id} immediate={immediate}")
    
    draft = state.get_draft(user_id)
    if draft is None:
        await send("❌ Нет черновика")
        return
    
    if not immediate and schedule_time:
        job_id = scheduler.schedule_post(user_id, draft, schedule_time)
        if job_id:
            state.clear_draft(user_id)
            state.clear_session(user_id)
            await send(
                f"<b>✅ Запланировано</b>\n"
                f"На {schedule_time}\n\n"
                f"─────────────────\n"
                f"📝 /post | 🔙 /start"
            )
        else:
            await send(
                "❌ Неверная дата\n"
                "Формат: <code>/schedule ГГГГ-ММ-ДД ЧЧ:ММ</code>"
            )
        return
    
    # Первое сообщение
    await send("⏳ Публикую...")
    
    attachments = []
    for att in draft.get('raw_attachments', []):
        if isinstance(att, dict) and att.get('type'):
            attachments.append({'type': att['type'], 'payload': att.get('payload', {})})
    
    result = await max_client.send_message(
        chat_id=channel_id,
        text=draft.get('text', ''),
        buttons=draft.get('buttons'),
        attachments=attachments if attachments else None,
        use_html_format=True
    )
    
    if "error" not in result:
        message_id = result.get('message', {}).get('body', {}).get('mid')
        if message_id:
            stats.record_message(message_id, channel_id, draft.get('text', ''), datetime.now().isoformat())
        
        state.clear_draft(user_id)
        state.clear_session(user_id)
        
        from handlers.start import help_text
        
        # Второе сообщение — отдельно "Опубликовано"
        await send("<b>✅ Опубликовано!</b>")
        
        # Третье сообщение — главное меню
        await send(help_text())
        
        logger.info(f"[PUBLISH] ✅ msg_id={message_id}")
    else:
        error_detail = result.get('detail', '')[:200]
        await send(f"<b>❌ Ошибка публикации:</b>\n{error_detail}")
        logger.error(f"[PUBLISH] ❌ {error_detail}")
