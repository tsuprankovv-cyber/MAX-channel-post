"""
Webhook handler
"""
import json
from core.logger import get_logger

logger = get_logger(__name__)


async def webhook_handler(request, handlers_router):
    if request.method != 'POST':
        return None  # Вернём 405 в server.py
    
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 {json.dumps(body, ensure_ascii=False)[:600]}")
        
        if body.get('update_type') == 'message_created' and (msg := body.get('message')):
            await handlers_router(msg)
            return True
        
        return False
    except Exception as e:
        logger.exception(f"[WEBHOOK] 💥 {e}")
        return False
