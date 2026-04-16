import asyncio
import logging
import os
import json
from typing import Dict, Optional

import aiohttp
from aiohttp import ClientTimeout
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
# 🔧 НОВАЯ ПЕРЕМЕННАЯ: bearer / bot / none / header_name:Api-Key
MAX_AUTH_TYPE = os.getenv('MAX_AUTH_TYPE', 'none').lower()

user_sessions: Dict[int, Dict] = {}


def build_auth_headers() -> Dict[str, str]:
    """Формирует заголовки авторизации в нужном формате"""
    headers = {"Content-Type": "application/json", "User-Agent": "MAX-Channel-Poster/1.0"}
    
    if MAX_AUTH_TYPE.startswith('header_name:'):
        # Пример: header_name:X-Api-Key
        header_name = MAX_AUTH_TYPE.split(':', 1)[1]
        headers[header_name] = BOT_TOKEN
    elif MAX_AUTH_TYPE == 'bearer':
        headers["Authorization"] = f"Bearer {BOT_TOKEN}"
    elif MAX_AUTH_TYPE == 'bot':
        headers["Authorization"] = f"Bot {BOT_TOKEN}"
    else:
        # По умолчанию: токен без префикса в Authorization
        headers["Authorization"] = BOT_TOKEN
    
    return headers


async def api_request(method: str, endpoint: str, data: Dict = None, params: Dict = None, max_retries: int = 3) -> Dict:
    """Запрос к API MAX с умным бэк-оффом"""
    headers = build_auth_headers()
    url = f"{BASE_API_URL}{endpoint}"
    timeout = ClientTimeout(total=30, connect=10, sock_read=60)
    
    last_error = None
    
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=data
                ) as response:
                    text = await response.text()
                    
                    # 🔧 429 Too Many Requests — особый случай
                    if response.status == 429:
                        retry_after = response.headers.get('Retry-After', '10')
                        wait_time = min(int(retry_after), 60)  # Не ждать больше 60 сек
                        logger.warning(f"⏳ Rate limit. Ждём {wait_time}с перед повтором...")
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
                    else:
                        logger.warning(f"HTTP {response.status}: {text[:300]}")
                        last_error = {"error": f"HTTP_{response.status}", "detail": text}
                        
        except asyncio.TimeoutError:
            logger.warning(f"⏱ Timeout (attempt {attempt+1})")
            last_error = {"error": "timeout"}
        except Exception as e:
            logger.error(f"💥 Request error (attempt {attempt+1}): {e}")
            last_error = {"error": str(e)}
        
        # Экспоненциальная пауза между попытками (но не для 429)
        if attempt < max_retries - 1 and response.status != 429:
            wait = 2 ** attempt
            logger.info(f"🔄 Повтор через {wait}с...")
            await asyncio.sleep(wait)
    
    return last_error or {"error": "unknown"}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    payload = {"text": text}
    if keyboard:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
    
    result = await api_request("POST", f"/messages?user_id={chat_id}", data=payload)
    return "error" not in result


async def publish_to_channel(post_data: Dict) -> bool:
    try:
        keyboard = None
        if post_data.get('button_title') and post_data.get('button_url'):
            keyboard = {
                "inline_keyboard": [[{
                    "text": post_data['button_title'],
                    "url": post_data['button_url']
                }]]
            }
        
        payload = {"text": post_data.get('text', '')}
        if keyboard:
            payload["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
        
        # 🔧 Попробуй разные варианты эндпоинта, если этот не сработает:
        # /messages?chat_id={CHANNEL_ID}
        # /channels/{CHANNEL_ID}/messages
        # /channels/{CHANNEL_ID}/posts
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
        logger.warning(f"get_updates error: {result}")
        return []
    
    return result.get("updates") or result.get("data", {}).get("updates") or []


async def handle_message(message: Dict):
    chat_id = message.get("recipient", {}).get("chat_id") or message.get("from", {}).get("id")
    if not chat_id:
        logger.warning(f"❌ Не удалось определить chat_id: {message}")
        return
    
    body = message.get("body", {})
    text = body.get("text", "") if isinstance(body, dict) else str(body)
    
    logger.info(f"💬 От {chat_id}: {text[:100] if text else '[пусто]'}")
    
    if text == "/start":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"text": "ℹ️ Помощь", "callback_data": "help"}]
            ]
        }
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
                    await send_message(chat_id, "❌ Формат: `Текст | ссылка`. Попробуй ещё раз")
                    return
            
            success = await publish_to_channel(session_data)
            await send_message(chat_id, "✅ Опубликовано!" if success else "❌ Ошибка. Проверь логи")
            del user_sessions[chat_id]


async def handle_callback(callback: Dict):
    data = callback.get("payload", {}).get("data") or callback.get("callback_data")
    user_id = callback.get("user", {}).get("id") or callback.get("from", {}).get("id")
    
    if not user_id:
        return
    
    logger.info(f"🔘 Callback от {user_id}: {data}")
    
    if data == "new_post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 Отправь текст поста")
    elif data == "help":
        await send_message(user_id, "📖 **Помощь**\n/post — создать пост\n/start — меню")


async def main():
    logger.info("🚀 Запуск MAX Channel Poster Bot...")
    logger.info(f"📢 Канал: {CHANNEL_ID}")
    logger.info(f"🌐 API: {BASE_API_URL}")
    logger.info(f"🔐 Auth type: {MAX_AUTH_TYPE or 'default (raw token)'}")
    
    marker = None
    consecutive_errors = 0
    
    try:
        while True:
            updates = await get_updates(marker, timeout=30)
            
            if updates:
                consecutive_errors = 0  # Сброс счётчика ошибок при успехе
                logger.info(f"📥 Получено {len(updates)} обновлений")
                
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
                # 🔧 Если много ошибок подряд — увеличиваем паузу
                if consecutive_errors >= 3:
                    wait = min(30, 5 * consecutive_errors)
                    logger.warning(f"⚠️ {consecutive_errors} ошибок подряд. Пауза {wait}с")
                    await asyncio.sleep(wait)
                    continue
            
            # 🔧 Базовая пауза между запросами (защита от 429)
            await asyncio.sleep(5)
            
    except asyncio.CancelledError:
        logger.info("🛑 Бот остановлен")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
        raise  # Render перезапустит воркер


if __name__ == '__main__':
    asyncio.run(main())
