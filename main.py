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
    force=True  # Гарантирует вывод логов в stdout на Render
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID')
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru')  # Можно переопределить

user_sessions: Dict[int, Dict] = {}
session: Optional[aiohttp.ClientSession] = None


async def api_request(method: str, endpoint: str, data: Dict = None, params: Dict = None, max_retries: int = 3) -> Dict:
    """Универсальный запрос к API MAX с повторами"""
    # 🔧 ФИКС: Добавлен префикс Bearer (проверь в доке MAX, возможно нужен "Bot")
    headers = {
        "Authorization": f"Bearer {BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "MAX-Channel-Poster/1.0"
    }
    
    url = f"{BASE_API_URL}{endpoint}"
    
    timeout = ClientTimeout(total=30, connect=10, sock_read=60)
    
    for attempt in range(max_retries):
        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                json=data,
                timeout=timeout
            ) as response:
                text = await response.text()
                
                if response.status == 200:
                    try:
                        result = json.loads(text) if text.strip() else {}
                        # 🔧 ФИКС: Проверка на семантическую ошибку в теле ответа
                        if result.get("error") or result.get("status") == "failed":
                            logger.warning(f"API error in body: {result}")
                            return {"error": "api_logic_error", "detail": result}
                        return result
                    except json.JSONDecodeError:
                        return {"raw": text}
                else:
                    logger.warning(f"HTTP {response.status} (attempt {attempt+1}): {text[:300]}")
                    if response.status in (401, 403):
                        logger.error("❌ AUTH FAILED! Проверь формат токена и права бота")
                        return {"error": f"HTTP_{response.status}", "detail": text}
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff
        except asyncio.TimeoutError:
            logger.warning(f"Timeout on attempt {attempt+1}")
            if attempt == max_retries - 1:
                return {"error": "timeout"}
        except Exception as e:
            logger.error(f"Request error (attempt {attempt+1}): {e}")
            if attempt == max_retries - 1:
                return {"error": str(e)}
    
    return {"error": "max_retries_exceeded"}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправка сообщения пользователю"""
    payload = {"text": text}
    if keyboard:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": keyboard}]
    
    result = await api_request("POST", f"/messages?user_id={chat_id}", data=payload)
    return "error" not in result


async def publish_to_channel(post_data: Dict) -> bool:
    """Публикация поста в канал"""
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
        
        # 🔧 ФИКС: Убедись, что CHANNEL_ID передаётся в правильном формате (строка/число)
        result = await api_request(
            "POST", 
            f"/channels/{CHANNEL_ID}/messages",  # ← Проверь в доке: может быть /messages?chat_id= или /channels/{id}/posts
            data=payload
        )
        return "error" not in result
    except Exception as e:
        logger.error(f"Publish error: {e}")
        return False


async def get_updates(marker: int = None, timeout: int = 30) -> list:
    """Long polling для получения обновлений"""
    params = {"timeout": timeout}
    if marker:
        params["marker"] = marker
    
    result = await api_request("GET", "/updates", params=params)
    
    if "error" in result:
        logger.warning(f"get_updates error: {result}")
        return []
    
    # 🔧 ФИКС: Поддержка разных форматов ответа
    return result.get("updates") or result.get("data", {}).get("updates") or []


async def handle_message(message: Dict):
    """Обработка входящего сообщения"""
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
    """Обработка нажатий на кнопки"""
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
    global session
    
    # 🔧 ФИКС: Не логируем токен даже частично
    logger.info("🚀 Запуск MAX Channel Poster Bot...")
    logger.info(f"📢 Канал: {CHANNEL_ID}")
    logger.info(f"🌐 API: {BASE_API_URL}")
    
    async with aiohttp.ClientSession() as session:
        marker = None
        logger.info("✅ Бот запущен (Long Polling)")
        
        try:
            while True:
                updates = await get_updates(marker, timeout=30)
                
                if not updates:
                    await asyncio.sleep(1)
                    continue
                
                for update in updates:
                    if "message" in update:
                        await handle_message(update["message"])
                    elif "callback" in update or "callback_query" in update:
                        cb = update.get("callback") or update.get("callback_query")
                        await handle_callback(cb)
                    
                    # Обновляем маркер для long polling
                    marker = update.get("marker") or update.get("update_id") or marker
                    if isinstance(marker, int):
                        marker += 1
                
                await asyncio.sleep(0.3)  # Небольшая пауза чтобы не спамить API
                
        except asyncio.CancelledError:
            logger.info("🛑 Бот остановлен (CancelledError)")
        except Exception as e:
            logger.error(f"💥 Критическая ошибка: {e}", exc_info=True)
            # На Render это приведёт к рестарту воркера — это нормально
        finally:
            logger.info("🔚 Завершение работы")


if __name__ == '__main__':
    asyncio.run(main())
