import asyncio
import logging
import os
import json
from typing import Dict, Optional, List

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    force=True
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

user_sessions: Dict[int, Dict] = {}
api_session: Optional[ClientSession] = None


# ===================================================================
# API ЗАПРОСЫ (как в рабочем боте)
# ===================================================================
async def api_request(method: str, endpoint: str,  Dict = None, max_retries: int = 3):
    headers = {
        "Authorization": BOT_TOKEN,  # 🔥 Сырой токен, без префиксов!
        "Content-Type": "application/json",
        "User-Agent": "MAX-Channel-Poster/1.0"
    }
    url = f"{BASE_API_URL}{endpoint}"
    timeout = ClientTimeout(total=30)
    
    for attempt in range(max_retries):
        try:
            async with api_session.request(
                method=method, url=url, headers=headers,
                json=data, timeout=timeout
            ) as response:
                text = await response.text()
                logger.info(f"[API] {method} {endpoint} → {response.status}")
                
                if response.status == 429:
                    wait = int(response.headers.get('Retry-After', 30))
                    logger.warning(f"⏳ Rate limit, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                
                if response.status == 200:
                    try:
                        return json.loads(text) if text.strip() else {}
                    except:
                        return {"raw": text}
                
                logger.warning(f"[API] HTTP {response.status}: {text[:200]}")
                return {"error": f"HTTP_{response.status}", "detail": text}
                
        except Exception as e:
            logger.error(f"[API] Error (attempt {attempt+1}): {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
    
    return {"error": "max_retries"}


# ===================================================================
# ОТПРАВКА СООБЩЕНИЙ (исправленные эндпоинты)
# ===================================================================
async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправка сообщения пользователю"""
    buttons = []
    if keyboard and "inline_keyboard" in keyboard:
        for row in keyboard["inline_keyboard"]:
            for btn in row:
                btn_data = {"text": btn.get("text", "")}
                if btn.get("url"): btn_data["url"] = btn["url"]
                if btn.get("callback_data"): btn_data["callback_data"] = btn["callback_data"]
                buttons.append(btn_data)
    
    payload = {"text": text, "buttons": buttons if buttons else []}
    # 🔥 Исправленный эндпоинт (как в рабочем боте)
    endpoint = f"/chats/{chat_id}/messages"
    
    result = await api_request("POST", endpoint, data=payload)
    return "error" not in result


async def publish_to_channel(post_ Dict) -> bool:
    """Публикация поста в канал"""
    try:
        buttons = []
        if post_data.get('button_title') and post_data.get('button_url'):
            buttons.append({"text": post_data['button_title'], "url": post_data['button_url']})
        
        payload = {"text": post_data.get('text', ''), "buttons": buttons if buttons else []}
        # 🔥 Эндпоинт для канала (аналогично чату)
        endpoint = f"/chats/{CHANNEL_ID}/messages"
        
        result = await api_request("POST", endpoint, data=payload)
        return "error" not in result
    except Exception as e:
        logger.error(f"[PUBLISH] Error: {e}")
        return False


# ===================================================================
# РЕГИСТРАЦИЯ ВЕБХУКА (как в рабочем боте!)
# ===================================================================
async def register_webhook(webhook_url: str) -> bool:
    """Регистрирует вебхук в MAX API"""
    logger.info(f"[WEBHOOK] Registering: {webhook_url} for chat {CHANNEL_ID}")
    
    body = {
        "url": webhook_url,
        "chat_id": CHANNEL_ID,
        "update_types": ["message_created"]  # 🔥 Ключевое поле!
    }
    
    result = await api_request("POST", "/subscriptions", data=body)
    
    if "error" not in result:
        logger.info("[WEBHOOK] ✅ Registered successfully")
        return True
    else:
        logger.error(f"[WEBHOOK] ❌ Failed: {result}")
        return False


# ===================================================================
# ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ (вебхук)
# ===================================================================
async def webhook_handler(request):
    """Принимает обновления от MAX API"""
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    
    if request.method != 'POST':
        return web.Response(status=405)
    
    try:
        body = await request.json()
        update_type = body.get('update_type', 'unknown')
        logger.info(f"[WEBHOOK] Type: {update_type}")
        
        # 🔥 MAX присылает message внутри поля 'message' при update_type='message_created'
        if update_type == 'message_created' and (msg := body.get('message')):
            await handle_max_message(msg)
        
        return web.Response(status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] Invalid JSON: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.error(f"[WEBHOOK] Error: {e}", exc_info=True)
        return web.Response(status=500)


async def handle_max_message(msg: Dict):
    """Обработка сообщения от пользователя"""
    # 🔥 Извлекаем данные как в рабочем боте
    inner = msg
    body = inner.get('body', {})
    text = body.get('text', '') or inner.get('text', '')
    chat_id = inner.get('from', {}).get('id')
    
    if not chat_id:
        logger.warning("[HANDLE] ❌ No chat_id")
        return
    
    logger.info(f"[HANDLE] 💬 From {chat_id}: {text[:100] if text else '[empty]'}")
    
    # Обработка команд
    if text == "/start":
        kb = {"inline_keyboard": [
            [{"text": "➕ Новый пост", "callback_data": "new_post"}],
            [{"text": "ℹ️ Помощь", "callback_data": "help"}]
        ]}
        await send_message(chat_id, "👋 **MAX Channel Poster**\n\nНажми «Новый пост»", kb)
    
    elif text == "/post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправь текст поста")
    
    elif chat_id in user_sessions:
        sd = user_sessions[chat_id]
        step = sd.get("step")
        
        if step == "waiting_text":
            sd["text"] = text
            sd["step"] = "waiting_button"
            await send_message(chat_id, "🔘 Кнопка: `Текст | ссылка`\nИли `пропустить`")
        
        elif step == "waiting_button":
            if text and text.lower() not in ("пропустить", "skip", "-"):
                if "|" in text:
                    parts = text.split("|", 1)
                    sd["button_title"] = parts[0].strip()
                    sd["button_url"] = parts[1].strip()
                else:
                    await send_message(chat_id, "❌ Формат: `Текст | ссылка`")
                    return
            ok = await publish_to_channel(sd)
            await send_message(chat_id, "✅ Опубликовано!" if ok else "❌ Ошибка")
            del user_sessions[chat_id]


# ===================================================================
# WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "status": "running"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "webhook": "active"})

async def on_startup(app):
    global api_session
    logger.info("🚀 Starting MAX Channel Poster (Webhook mode)")
    api_session = ClientSession()
    
    # 🔥 Авто-регистрация вебхука при старте
    if RENDER_EXTERNAL_URL and CHANNEL_ID:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await register_webhook(webhook_url)

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if api_session:
        await api_session.close()

app = web.Application()
app.add_routes([
    web.get('/', root_handler),
    web.get('/health', health_check),
    web.post('/webhook', webhook_handler),
])
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Server on port {port}")
    logger.info(f"🔗 Webhook: {RENDER_EXTERNAL_URL}/webhook if set")
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
