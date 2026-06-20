"""
Обработчик пароля
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_password(user_id, password, send, auth, state):
    logger.info(f"[PASS] user={user_id}")
    
    if auth.check_password(user_id, password):
        auth.reset_failed_attempts(user_id)
        session = state.get_session(user_id)
        chat_id = session.get('chat_id', user_id)
        from handlers.start import handle_start
        await handle_start(user_id, chat_id, send, auth, state)
    else:
        remaining = 3 - auth.get_failed_attempts(user_id)
        if remaining > 0:
            await send(f"❌ Неверный пароль. Осталось: {remaining}")
        else:
            await send("🔒 Заблокировано.")
