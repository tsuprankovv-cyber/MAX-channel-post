"""
Редактирование поста
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_edit(user_id, send, state):
    logger.info(f"[EDIT] user={user_id}")
    
    draft = state.get_draft(user_id)
    if draft is None:
        await send("❌ Нет черновика. /post")
        return
    
    menu = ["✏️ Что редактируем?\n"]
    if draft.get('attachments'):
        menu.append("🖼 /edit_photo — фото")
    if draft.get('text'):
        menu.append("📝 /edit_text — текст")
    if draft.get('buttons'):
        menu.append("🔘 /edit_buttons — кнопки")
    menu.append("\n👁 /preview | ❌ /cancel")
    
    await send('\n'.join(menu))


async def handle_edit_photo(user_id, send, state):
    logger.info(f"[EDIT-PHOTO] user={user_id}")
    state.set_step(user_id, 'post_waiting_photo')
    await send("🖼 Новое фото или /skip /cancel")


async def handle_edit_text(user_id, send, state):
    logger.info(f"[EDIT-TEXT] user={user_id}")
    state.set_step(user_id, 'post_waiting_text')
    await send("📝 Новый текст или /skip /cancel")


async def handle_edit_buttons(user_id, send, state):
    logger.info(f"[EDIT-BTN] user={user_id}")
    state.set_step(user_id, 'post_waiting_buttons')
    await send("🔘 Новые кнопки или /skip /cancel")
