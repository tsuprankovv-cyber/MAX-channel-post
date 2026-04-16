import asyncio
import logging
import os
import json
from typing import Dict, Optional

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    force=True
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID')
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru')
MAX_AUTH_TYPE = os.getenv('MAX_AUTH_TYPE', 'none').lower()

user_sessions: Dict[int, Dict] = {}
api_session: Optional[ClientSession] = None
bot_task: Optional[asyncio.Task] = None


def build_auth_params():
    """Возвращает заголовки и параметры для авторизации"""
    headers = {"Content-Type": "application/json", "User-Agent": "MAX-Poster/1.0"}
    params = {}
    if MAX_AUTH_TYPE == 'bearer':
        headers["Authorization"] = f"Bearer {BOT_TOKEN}"
    elif MAX_AUTH_TYPE == 'bot':
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    elif MAX_AUTH_TYPE == 'header':
        headers["X-Api-Key"] = BOT_TOKEN
    elif MAX_AUTH_TYPE == 'query':
        params["access_token"] = BOT_TOKEN
    else:
        headers["Authorization"] = BOT_TOKEN
    return headers, params


async def api_request(method: str, endpoint: str,  Dict = None, params: Dict = None, max_retries: int = 3):
    """Универсальный запрос к API MAX"""
    headers, auth_params = build_auth_params()
    all_params = {**(params or {}), **auth_params}
    url = f"{BASE_API_URL}{endpoint}"
    timeout = ClientTimeout(total=30, connect=10, sock_read=60)
    
    for attempt in range(max_retries):
        try:
            async with api_session.request(
                method=method,
                url=url,
                headers=headers,
                params=all_params,
                json=data,
                timeout=timeout
            ) as response:
                text = await response.text()
                
                if response.status == 429:
                    wait = min(int(response.headers.get('Retry-After', 30)), 120)
                    logger.warning(f"⏳ Rate limit. Ждём {wait}с...")
                    await asyncio.sleep(wait)
                    continue
                
                if response.status == 401:
                    logger.error(f"❌ AUTH FAILED: {text[:200]}")
                    return {"error": "auth_failed"}
                
                if response.status == 200:
                    try:
                        result = json.loads(text) if text.strip() else {}
                        if result.get("error") or result.get("status") == "failed":
                            return {"error": "api_error", "detail": result}
                        return result
                    except:
                        return {"raw": text}
                
                logger.warning(f"HTTP {response.status}: {text[:200]}")
                
        except Exception as e:
            logger.error(f"Request error (attempt {attempt+1}): {e}")
        
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)
    
    return {"error": "max_retries"}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправка сообщения пользователю"""
    buttons = []
    if keyboard and "inline_keyboard" in keyboard:
        for row in keyboard["inline_keyboard"]:
            for btn in row:
                btn_data = {"text": btn.get("text", "")}
                if btn.get("url"):
                    btn_data["url"] = btn["url"]
                if btn.get("callback_data"):
                    btn_data["callback_data"] = btn["callback_data"]
                buttons.append(btn_data)
    
    payload = {
        "text": text,
        "buttons": buttons
    }
    
    result = await api_request("POST", f"/messages?user_id={chat_id}", data=payload)
    return "error" not in result


async def publish_to_channel(post_ Dict) -> bool:
    """Публикация поста в канал"""
    try:
        buttons = []
        if post_data.get('button_title') and post_data.get('button_url'):
            buttons.append({
                "text": post_data['button_title'],
                "url": post_data['button_url']
            })
        
        payload = {
            "text": post_data.get('text', ''),
            "buttons": buttons
        }
        
        result = await api_request("POST", f"/channels/{CHANNEL_ID}/messages", data=payload)
        return "error" not in result
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False


async def get_updates(marker: int = None, timeout: int = 30):
    """Получение обновлений (long polling)"""
    params = {"timeout": timeout}
    if marker:
        params["marker"] = marker
    result = await api_request("GET", "/updates", params=params)
    if "error" in result:
        return []
    return result.get("updates") or result.get("data", {}).get("updates") or []


async def handle_message(message: Dict):
    """Обработка входящего сообщения"""
    chat_id = message.get("recipient", {}).get("chat_id") or message.get("from", {}).get("id")
    if not chat_id:
        return
    body = message.get("body", {})
    text = body.get("text", "") if isinstance(body, dict) else str(body)
    
    if text == "/start":
        kb = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"text": "ℹ️ Помощь", "callback_data": "help"}]
            ]
        }
        await send_message(chat_id, "👋 **MAX Channel Poster**\n\nНажми «Новый пост»", kb)
        return
    
    if text == "/post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправь текст поста")
        return
    
    if chat_id in user_sessions:
        sd = user_sessions[chat_id]
        step = sd.get("step")
        
        if step == "waiting_text":
            sd["text"] = text
            sd["step"] = "waiting_button"
            await send_message(chat_id, "🔘 Кнопка: `Текст | ссылка`\nИли `пропустить`")
        
        elif step == "waiting_button":
            if text.lower() not in ("пропустить", "skip", "-"):
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


async def handle_callback(callback: Dict):
    """Обработка нажатий на кнопки"""
    data = callback.get("payload", {}).get("data") or callback.get("callback_data")
    user_id = callback.get("user", {}).get("id") or callback.get("from", {}).get("id")
    if not user_id:
        return
    if data == "new_post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 Отправь текст поста")
    elif data == "help":
        await send_message(user_id, "📖 **Помощь**\n/post — создать пост")


# 🔥 ФОНОВАЯ ЗАДАЧА БОТА
async def bot_polling():
    logger.info("🤖 Bot polling started")
    marker = None
    while True:
        try:
            updates = await get_updates(marker, timeout=30)
            if updates:
                for update in updates:
                    if "message" in update:
                        await handle_message(update["message"])
                    elif "callback" in update or "callback_query" in update:
                        cb = update.get("callback") or update.get("callback_query")
                        await handle_callback(cb)
                    marker = update.get("marker") or update.get("update_id") or marker
                    if isinstance(marker, int):
                        marker += 1
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("🛑 Bot polling cancelled")
            break
        except Exception as e:
            logger.error(f"Polling error: {e}")
            await asyncio.sleep(10)


# 🔥 WEB-СЕРВЕР
async def health_check(request):
    return web.json_response({"status": "ok"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "status": "running"})

async def on_startup(app):
    global api_session, bot_task
    logger.info("🚀 Starting MAX Channel Poster (Web Service)")
    api_session = ClientSession()
    bot_task = asyncio.create_task(bot_polling())

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    if api_session:
        await api_session.close()

app = web.Application()
app.add_routes([
    web.get('/', root_handler),
    web.get('/health', health_check),
])
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Server starting on port {port}")
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
