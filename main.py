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
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID')
BASE_API_URL = "https://platform-api.max.ru"

user_sessions: Dict[int, Dict] = {}
session: Optional[aiohttp.ClientSession] = None


async def api_request(method: str, endpoint: str, data: Dict = None, params: Dict = None) -> Dict:
    """Универсальный запрос к API MAX"""
    headers = {
        "Authorization": BOT_TOKEN,
        "Content-Type": "application/json"
    }
    
    url = f"{BASE_API_URL}{endpoint}"
    logger.info(f"API {method} {url}")
    if params:
        logger.info(f"Params: {params}")
    if data:
        logger.info(f"Data: {json.dumps(data, ensure_ascii=False)[:200]}")
    
    timeout = ClientTimeout(total=30)
    
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
            logger.info(f"Response status: {response.status}")
            logger.info(f"Response body: {text[:500]}")
            
            if response.status == 200:
                try:
                    return json.loads(text) if text else {}
                except:
                    return {"raw": text}
            else:
                logger.error(f"HTTP {response.status}: {text}")
                return {"error": f"HTTP {response.status}", "detail": text}
    except Exception as e:
        logger.error(f"Request error: {e}")
        return {"error": str(e)}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправка сообщения пользователю"""
    payload = {"text": text}
    if keyboard:
        payload["attachments"] = [{
            "type": "inline_keyboard",
            "payload": keyboard
        }]
    
    result = await api_request(
        "POST",
        f"/messages?user_id={chat_id}",
        data=payload
    )
    return "error" not in result


async def publish_to_channel(post_data: Dict) -> bool:
    """Публикация в канал"""
    try:
        keyboard = None
        if 'button_title' in post_data and 'button_url' in post_data:
            keyboard = {
                "inline_keyboard": [[{
                    "text": post_data['button_title'],
                    "url": post_data['button_url']
                }]]
            }
        
        payload = {"text": post_data.get('text', '')}
        if keyboard:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard
            }]
        
        result = await api_request(
            "POST",
            f"/messages?chat_id={CHANNEL_ID}",
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
        return []
    
    # API возвращает { "updates": [...], "marker": ... }
    return result.get("updates", [])


async def handle_message(message: Dict):
    """Обработка входящего сообщения"""
    # Структура сообщения из API MAX
    chat_id = message.get("chat", {}).get("id") or message.get("recipient", {}).get("chat_id")
    text = message.get("body", {}).get("text", "")
    
    if not chat_id:
        # Пробуем другие поля
        chat_id = message.get("from", {}).get("id")
    
    logger.info(f"Message from {chat_id}: {text[:100] if text else '[no text]'}")
    
    if text == "/start":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"text": "ℹ️ Помощь", "callback_data": "help"}]
            ]
        }
        await send_message(
            chat_id,
            "👋 **MAX Channel Poster Bot**\n\nПубликую посты в канал.\n\nНажмите «Новый пост»",
            keyboard
        )
        return
    
    if chat_id in user_sessions:
        session_data = user_sessions[chat_id]
        step = session_data.get("step")
        
        if step == "waiting_text":
            session_data["text"] = text
            session_data["step"] = "waiting_button"
            await send_message(
                chat_id,
                "🔘 Отправьте кнопку в формате:\n`Текст | https://ссылка`\n\nИли отправьте 'пропустить'"
            )
        
        elif step == "waiting_button":
            if "|" in text:
                parts = text.split("|", 1)
                session_data["button_title"] = parts[0].strip()
                session_data["button_url"] = parts[1].strip()
            
            success = await publish_to_channel(session_data)
            await send_message(
                chat_id,
                "✅ Пост опубликован!" if success else "❌ Ошибка публикации"
            )
            del user_sessions[chat_id]


async def handle_callback(callback: Dict):
    """Обработка нажатий на кнопки"""
    # Структура callback из API MAX
    data = callback.get("payload", {}).get("data", "")
    chat_id = callback.get("user", {}).get("id")
    
    logger.info(f"Callback from {chat_id}: {data}")
    
    if data == "new_post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправьте текст поста")


async def main():
    global session
    
    logger.info("🚀 Запуск бота MAX Channel Poster...")
    logger.info(f"📢 Канал ID: {CHANNEL_ID}")
    logger.info(f"🤖 Токен: {BOT_TOKEN[:15]}...")
    logger.info(f"🌐 API URL: {BASE_API_URL}")
    
    session = aiohttp.ClientSession()
    marker = None
    
    logger.info("✅ Бот запущен, ожидаем сообщения...")
    
    try:
        while True:
            updates = await get_updates(marker, timeout=30)
            
            for update in updates:
                logger.info(f"Processing update: {json.dumps(update, ensure_ascii=False)[:200]}")
                
                if "message_created" in update:
                    await handle_message(update["message_created"])
                if "message_callback" in update:
                    await handle_callback(update["message_callback"])
                
                # Обновляем marker
                if "marker" in update:
                    marker = update["marker"]
            
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())
