import asyncio
import logging
import os
import json
from typing import Dict, Optional

import aiohttp
from aiohttp import ClientTimeout, web
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
PORT = int(os.getenv('PORT', 10000))

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
            
            if response.status == 200:
                try:
                    return json.loads(text) if text else {}
                except:
                    return {"raw": text}
            else:
                logger.error(f"HTTP {response.status}: {text[:500]}")
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
    """Публикация поста в канал"""
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
    
    return result.get("updates", [])


async def handle_message(message: Dict):
    """Обработка входящего сообщения"""
    chat_id = message.get("recipient", {}).get("chat_id")
    if not chat_id:
        chat_id = message.get("from", {}).get("id")
    
    body = message.get("body", {})
    text = body.get("text", "") if isinstance(body, dict) else ""
    
    if not chat_id:
        logger.warning(f"Не удалось определить chat_id из сообщения: {message}")
        return
    
    logger.info(f"Сообщение от {chat_id}: {text[:100] if text else '[без текста]'}")
    
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
    
    if text == "/post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправьте текст поста")
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
    data = callback.get("payload", {}).get("data", "")
    user_id = callback.get("user", {}).get("id")
    
    logger.info(f"Callback от {user_id}: {data}")
    
    if data == "new_post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 Отправьте текст поста")
    
    elif data == "help":
        await send_message(
            user_id,
            "📖 **Помощь**\n\n/post — создать пост\n/start — меню\n\nФормат кнопки: Текст | https://ссылка"
        )


# ===== HEALTH-СЕРВЕР ДЛЯ RENDER =====
async def health_check(request):
    """Health check endpoint для Render"""
    return web.json_response({"status": "healthy", "bot": "running"})


async def run_health_server():
    """Запускает HTTP-сервер для health check"""
    app = web.Application()
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Health-сервер запущен на порту {PORT}")
    
    # Держим сервер живым
    while True:
        await asyncio.sleep(3600)


# ===== ОСНОВНОЙ ЗАПУСК =====
async def main():
    global session
    
    logger.info("🚀 Запуск бота MAX Channel Poster...")
    logger.info(f"📢 Канал ID: {CHANNEL_ID}")
    logger.info(f"🤖 Токен: {BOT_TOKEN[:15]}...")
    logger.info(f"🌐 API URL: {BASE_API_URL}")
    
    session = aiohttp.ClientSession()
    
    # Запускаем health-сервер в фоне
    asyncio.create_task(run_health_server())
    
    marker = None
    logger.info("✅ Бот запущен в режиме Long Polling")
    logger.info("📨 Ожидание сообщений...")
    
    try:
        while True:
            updates = await get_updates(marker, timeout=30)
            
            for update in updates:
                logger.info(f"Обработка update: {json.dumps(update, ensure_ascii=False)[:200]}")
                
                if "message" in update:
                    await handle_message(update["message"])
                if "callback" in update:
                    await handle_callback(update["callback"])
                if "message_created" in update:
                    await handle_message(update["message_created"])
                if "message_callback" in update:
                    await handle_callback(update["message_callback"])
                
                if "marker" in update:
                    marker = update["marker"]
                elif "update_id" in update:
                    marker = update["update_id"] + 1
            
            await asyncio.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())
