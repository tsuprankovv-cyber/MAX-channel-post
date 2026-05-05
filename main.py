import asyncio
import logging
import os
import json

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

user_sessions = {}
api_session = None


# ===================================================================
# API ЗАПРОСЫ
# ===================================================================
async def api_request(method, endpoint, data=None, max_retries=3):
    headers = {
        "Authorization": BOT_TOKEN,
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
# ОТПРАВКА СООБЩЕНИЙ
# ===================================================================
async def send_message(chat_id, text, keyboard=None):
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
    endpoint = f"/chats/{chat_id}/messages"
    
    logger.info(f"[SEND] → {endpoint} | text_len={len(text)} | buttons={len(buttons)}")
    result = await api_request("POST", endpoint, data=payload)
    
    if "error" in result:
        logger.error(f"[SEND] ❌ Failed: {result}")
    else:
        logger.info(f"[SEND] ✅ Sent successfully")
    
    return "error" not in result


async def publish_to_channel(post_data):
    """Публикация поста в канал"""
    try:
        buttons = []
        if post_data.get('button_title') and post_data.get('button_url'):
            buttons.append({"text": post_data['button_title'], "url": post_data['button_url']})
        
        payload = {"text": post_data.get('text', ''), "buttons": buttons if buttons else []}
        endpoint = f"/chats/{CHANNEL_ID}/messages"
        
        logger.info(f"[PUBLISH] → {endpoint} | text_len={len(payload['text'])}")
        result = await api_request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[PUBLISH] ❌ Failed: {result}")
        else:
            logger.info(f"[PUBLISH] ✅ Published successfully")
        
        return "error" not in result
    except Exception as e:
        logger.error(f"[PUBLISH] Error: {e}")
        return False


# ===================================================================
# РЕГИСТРАЦИЯ ВЕБХУКА
# ===================================================================
async def register_webhook(webhook_url):
    """Регистрирует вебхук в MAX API"""
    logger.info(f"[WEBHOOK] Registering: {webhook_url} for chat {CHANNEL_ID}")
    
    body = {
        "url": webhook_url,
        "chat_id": CHANNEL_ID,
        "update_types": ["message_created"]
    }
    
    result = await api_request("POST", "/subscriptions", data=body)
    
    if "error" not in result:
        logger.info("[WEBHOOK] ✅ Registered successfully")
        return True
    else:
        logger.error(f"[WEBHOOK] ❌ Failed: {result}")
        return False


# ===================================================================
# ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ
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
        logger.info(f"[WEBHOOK] Full body preview: {json.dumps(body, ensure_ascii=False)[:500]}")
        
        if update_type == 'message_created' and (msg := body.get('message')):
            await handle_max_message(msg)
        
        return web.Response(status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] Invalid JSON: {e}")
        return web.Response(status=400)
    except Exception as e:
        logger.error(f"[WEBHOOK] Error: {e}", exc_info=True)
        return web.Response(status=500)


async def handle_max_message(msg):
    """Обработка сообщения от пользователя — с ПОЛНЫМ логированием"""
    
    # 🔥 Логируем ВСЮ структуру сообщения для отладки
    logger.info("=" * 80)
    logger.info(f"[HANDLE] 📦 FULL MESSAGE STRUCTURE:")
    logger.info(json.dumps(msg, ensure_ascii=False, indent=2)[:2000])
    logger.info(f"[HANDLE] Top-level keys: {list(msg.keys())}")
    
    # 🔥 Пробуем ВСЕ возможные пути извлечения chat_id
    chat_id = None
    chat_id_source = None
    
    # Путь 1: recipient.id (на основе логов!)
    if isinstance(msg.get('recipient'), dict):
        cid = msg['recipient'].get('id') or msg['recipient'].get('chat_id') or msg['recipient'].get('user_id')
        if cid:
            chat_id = cid
            chat_id_source = 'recipient'
            logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in recipient")
    
    # Путь 2: sender.id
    if not chat_id and isinstance(msg.get('sender'), dict):
        cid = msg['sender'].get('id') or msg['sender'].get('chat_id') or msg['sender'].get('user_id')
        if cid:
            chat_id = cid
            chat_id_source = 'sender'
            logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in sender")
    
    # Путь 3: from.id (на всякий случай)
    if not chat_id and isinstance(msg.get('from'), dict):
        cid = msg['from'].get('id')
        if cid:
            chat_id = cid
            chat_id_source = 'from'
            logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in from")
    
    # Путь 4: body.from.id
    if not chat_id and isinstance(msg.get('body'), dict):
        body = msg['body']
        if isinstance(body.get('from'), dict):
            cid = body['from'].get('id')
            if cid:
                chat_id = cid
                chat_id_source = 'body.from'
                logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in body.from")
    
    # Путь 5: body.user_id / body.chat_id
    if not chat_id and isinstance(msg.get('body'), dict):
        cid = msg['body'].get('user_id') or msg['body'].get('chat_id')
        if cid:
            chat_id = cid
            chat_id_source = 'body'
            logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in body")
    
    # Путь 6: напрямую в корне
    if not chat_id:
        cid = msg.get('user_id') or msg.get('chat_id') or msg.get('id')
        if cid:
            chat_id = cid
            chat_id_source = 'root'
            logger.info(f"[HANDLE] ✅ Found chat_id={chat_id} in root")
    
    # 🔥 Извлекаем текст
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    
    # 🔥 Если chat_id не найден — логируем детали и выходим
    if not chat_id:
        logger.error(f"[HANDLE] ❌ CRITICAL: No chat_id found!")
        logger.error(f"[HANDLE] recipient keys: {list(msg.get('recipient', {}).keys()) if isinstance(msg.get('recipient'), dict) else 'N/A'}")
        logger.error(f"[HANDLE] sender keys: {list(msg.get('sender', {}).keys()) if isinstance(msg.get('sender'), dict) else 'N/A'}")
        logger.error(f"[HANDLE] body keys: {list(body.keys()) if isinstance(body, dict) else 'N/A'}")
        return
    
    logger.info(f"[HANDLE] 💬 From {chat_id} (via {chat_id_source}): '{text[:100] if text else '[empty]'}'")
    
    # 🔥 Обработка команд
    if text == "/start":
        logger.info(f"[HANDLE] 🎯 Processing /start for {chat_id}")
        kb = {"inline_keyboard": [
            [{"text": "➕ Новый пост", "callback_data": "new_post"}],
            [{"text": "ℹ️ Помощь", "callback_data": "help"}]
        ]}
        await send_message(chat_id, "👋 **MAX Channel Poster**\n\nНажми «Новый пост»", kb)
    
    elif text == "/post":
        logger.info(f"[HANDLE] 🎯 Processing /post for {chat_id}")
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправь текст поста")
    
    elif chat_id in user_sessions:
        sd = user_sessions[chat_id]
        step = sd.get("step")
        logger.info(f"[HANDLE] 🎯 Session step={step} for {chat_id}")
        
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
    
    logger.info("=" * 80)


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
