import asyncio
import logging
import os
import json
from typing import Dict, Optional

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv

# Настройка логирования
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
MAX_AUTH_TYPE = os.getenv('MAX_AUTH_TYPE', 'query').lower()

# Глобалы
user_sessions: Dict[int, Dict] = {}
api_session: Optional[ClientSession] = None
bot_task: Optional[asyncio.Task] = None


def build_auth_params() -> tuple[Dict[str, str], Dict[str, str]]:
    """Возвращает (заголовки, query-параметры) для авторизации"""
    headers = {"Content-Type": "application/json", "User-Agent": "MAX-Poster/1.0"}
    params = {}
    
    if MAX_AUTH_TYPE == 'bearer':
        headers["Authorization"] = f"Bearer {BOT_TOKEN}"
    elif MAX_AUTH_TYPE == 'bot':
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    elif MAX_AUTH_TYPE == 'header':
        headers["X-Api-Key"] = BOT_TOKEN
    elif MAX_AUTH_TYPE == 'query':
        params["access_token"] = BOT_TOKEN  # 🔥 Скорее всего нужен этот вариант
    else:
        headers["Authorization"] = BOT_TOKEN
    
    return headers, params


async def api_request(method: str, endpoint: str,  Dict = None, params: Dict = None, max_retries: int = 3) -> Dict:
    """Запрос к API MAX с обработкой 401/429"""
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
                
                # 🔥 429 — читаем Retry-After
                if response.status == 429:
                    retry_after = response.headers.get('Retry-After', '30')
                    wait_time = min(int(retry_after), 120)
                    logger.warning(f"⏳ Rate limit. Ждём {wait_time}с...")
                    await asyncio.sleep(wait_time)
                    continue
                
                if response.status == 401:
                    logger.error(f"❌ AUTH FAILED (401): {text[:200]}")
                    return {"error": "auth_failed", "detail": text}
                
                if response.status == 200:
                    try:
                        result = json.loads(text) if text.strip() else {}
                        if result.get("error") or result.get("status") == "failed":
                            return {"error": "api_logic_error", "detail": result}
                        return result
                    except json.JSONDecodeError:
                        return {"raw": text}
                
                logger.warning(f"HTTP {response.status}: {text[:300]}")
                
        except asyncio.TimeoutError:
            logger.warning(f"⏱ Timeout (attempt {attempt+1})")
        except Exception as e:
            logger.error(f"💥 Request error (attempt {attempt+1}): {e}")
        
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)
    
    return {"error": "max_retries_exceeded"}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    payload = {"text": text}
    if keyboard:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
    result = await api_request("POST", f"/messages?user_id={chat_id}", data=payload)
    return "error" not in result


async def publish_to_channel(post_ Dict) -> bool:
    try:
        keyboard = None
        if post_data.get('button_title') and post_data.get('button_url'):
            keyboard = {"inline_keyboard": [[{"text": post_data['button_title'], "url": post_data['button_url']}]]}
        
        payload = {"text": post_data.get('text', '')}
        if keyboard:
            payload["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
        
        result = await api_request("POST", f"/channels/{CHANNEL_ID}/messages", data=payload)
        return "error" not in result
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False


async def get_updates(marker: int = None, timeout: int = 30) -> list:
    params = {"timeout": timeout}
    if marker:
        params["marker"] = marker
    result = await api_request("GET", "/updates", params=params)
    if "error" in result:
        return []
    return result.get("updates") or result.get("data", {}).get("updates") or []


async def handle_message(message: Dict):
    chat_id = message.get("recipient", {}).get("chat_id") or message.get("from", {}).get("id")
    if not chat_id:
        return
    body = message.get("body", {})
    text = body.get("text", "") if isinstance(body, dict) else str(body)
    
    if text == "/start":
        keyboard = {"inline_keyboard": [[{"text": "➕ Новый пост", "callback_data": "new_post"}], [{"text": "ℹ️ Помощь", "callback_data": "help"}]]}
        await send_message(chat_id, "👋 **MAX Channel Poster**\n\nНажми «Новый пост»", keyboard)
        return
    if text == "/post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправь текст поста")
        return
    if chat_id in user_sessions:
        session_data = user_sessions[chat_id]
        step = session_data.get("step")
        if step == "waiting_text":
            session_data["text"] = text
            session_data["step"] = "waiting_button"
            await send_message(chat_id, "🔘 Кнопка: `Текст | ссылка`\nИли `пропустить`")
        elif step == "waiting_button":
            if text.lower() not in ("пропустить", "skip", "-"):
                if "|" in text:
                    parts = text.split("|", 1)
                    session_data["button_title"] = parts[0].strip()
                    session_data["button_url"] = parts[1].strip()
                else:
                    await send_message(chat_id, "❌ Формат: `Текст | ссылка`")
                    return
            success = await publish_to_channel(session_data)
            await send_message(chat_id, "✅ Опубликовано!" if success else "❌ Ошибка")
            del user_sessions[chat_id]


async def handle_callback(callback: Dict):
    data = callback.get("payload", {}).get("data") or callback.get("callback_data")
    user_id = callback.get("user", {}).get("id") or callback.get("from", {}).get("id")
    if not user_id:
        return
    if data == "new_post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 Отправь текст поста")
    elif data == "help":
        await send_message(user_id, "📖 **Помощь**\n/post — создать пост\n/start — меню")


# 🔥 ФОНОВАЯ ЗАДАЧА БОТА
async def bot_polling_task():
    """Long polling цикл — работает в фоне"""
    logger.info("🤖 Bot polling task started")
    marker = None
    consecutive_errors = 0
    
    while True:
        try:
            updates = await get_updates(marker, timeout=30)
            if updates:
                consecutive_errors = 0
                for update in updates:
                    if "message" in update:
                        await handle_message(update["message"])
                    elif "callback" in update or "callback_query" in update:
                        cb = update.get("callback") or update.get("callback_query")
                        await handle_callback(cb)
                    marker = update.get("marker") or update.get("update_id") or marker
                    if isinstance(marker, int):
                        marker += 1
            else:
                consecutive_errors += 1
                if consecutive_errors >= 3:
                    wait = min(60, 10 * consecutive_errors)
                    logger.warning(f"⚠️ {consecutive_errors} ошибок. Пауза {wait}с")
                    await asyncio.sleep(wait)
                    continue
            # 🔥 Базовая пауза между запросами (защита от 429)
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            logger.info("🛑 Bot polling task cancelled")
            break
        except Exception as e:
            logger.error(f"💥 Polling error: {e}", exc_info=True)
            await asyncio.sleep(10)


# 🔥 WEB-СЕРВЕР: эндпоинты для Render
async def health_check(request):
    """Health check для Render"""
    return web.json_response({"status": "ok", "service": "max-channel-poster"})

async def root_handler(request):
    """Корневой эндпоинт"""
    return web.json_response({"message": "MAX Channel Poster Bot is running", "endpoints": ["/health"]})

async def on_startup(app):
    """Инициализация при старте сервера"""
    global api_session, bot_task
    logger.info("🚀 Starting MAX Channel Poster (Web Service mode)")
    api_session = ClientSession()
    # Запускаем бота как фоновую задачу
    bot_task = asyncio.create_task(bot_polling_task())

async def on_cleanup(app):
    """Очистка при остановке"""
    logger.info("🔚 Shutting down...")
    if bot_task and not bot_task.done():
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass
    if api_session:
        await api_session.close()


# 🔥 Создаём приложение aiohttp
app = web.Application()
app.add_routes([
    web.get('/', root_handler),
    web.get('/health', health_check),
])
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)


# 🔥 Точка входа для Render Web Service
if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))  # Render задаёт $PORT
    logger.info(f"🌐 Starting web server on port {port}")
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
