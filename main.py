import os
import asyncio
import json
import logging
from typing import Dict, Optional

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv

# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ===== ЗАГРУЗКА ПЕРЕМЕННЫХ =====
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', 'f9LHodD0cOJ1zU51CUFdStMuwVfX0aNdze31RQduaSV9zy_WezacnZe9eAz0GKesBabkLpdRN_rK6ATTj6Za')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042')
BASE_API_URL = "https://api.max.ru"  # Исправленный URL API MAX

# Хранилище сессий пользователей
user_sessions: Dict[int, Dict] = {}


# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С API MAX =====
async def api_request(method: str, endpoint: str, data: Dict = None) -> Dict:
    """Универсальная функция для запросов к API MAX"""
    headers = {
        "Authorization": f"Bearer {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    url = f"{BASE_API_URL}{endpoint}"
    logger.info(f"API запрос: {method} {url}")
    
    timeout = ClientTimeout(total=30)
    
    try:
        async with ClientSession() as session:
            if method.upper() == "GET":
                async with session.get(url, headers=headers, timeout=timeout) as response:
                    result = await response.json()
                    logger.info(f"API ответ: {response.status}")
                    return result
            else:
                async with session.post(url, headers=headers, json=data, timeout=timeout) as response:
                    result = await response.json()
                    logger.info(f"API ответ: {response.status}")
                    return result
    except Exception as e:
        logger.error(f"API ошибка: {e}")
        return {"error": str(e)}


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправляет текстовое сообщение в чат или канал"""
    try:
        # Определяем тип получателя
        if chat_id > 0:
            endpoint = f"/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": text}
        else:
            endpoint = f"/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": chat_id, "text": text}
        
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)
        
        result = await api_request("POST", endpoint, payload)
        return "ok" in result.get("status", "") or "message_id" in result
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return False


async def publish_to_channel(post_data: Dict) -> bool:
    """Публикует пост в канал"""
    try:
        # Формируем клавиатуру с URL-кнопкой
        keyboard = None
        if 'button_title' in post_data and 'button_url' in post_data:
            keyboard = {
                "inline_keyboard": [[{
                    "text": post_data['button_title'],
                    "url": post_data['button_url']
                }]]
            }
        
        # Отправляем в канал
        channel_id = int(CHANNEL_ID)
        endpoint = f"/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": post_data.get('text', ''),
            "parse_mode": "Markdown"
        }
        
        if keyboard:
            payload["reply_markup"] = json.dumps(keyboard)
        
        # Если есть фото
        if 'photo_id' in post_data and post_data['photo_id']:
            endpoint = f"/bot{BOT_TOKEN}/sendPhoto"
            payload = {
                "chat_id": channel_id,
                "photo": post_data['photo_id'],
                "caption": post_data.get('text', ''),
                "parse_mode": "Markdown"
            }
            if keyboard:
                payload["reply_markup"] = json.dumps(keyboard)
        
        result = await api_request("POST", endpoint, payload)
        logger.info(f"Результат публикации: {result}")
        return "ok" in result.get("status", "") or "message_id" in result
    except Exception as e:
        logger.error(f"Ошибка публикации в канал: {e}")
        return False


# ===== ОБРАБОТЧИКИ ВЕБХУКА =====
async def handle_update(update: Dict) -> Dict:
    """Обрабатывает входящее обновление от MAX"""
    logger.info(f"Получено обновление: {json.dumps(update, ensure_ascii=False)[:500]}")
    
    try:
        # Проверяем тип обновления (для Telegram-like API)
        if "message" in update:
            message = update["message"]
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")
            user_id = message.get("from", {}).get("id", chat_id)
            
            # Обработка команд
            if text == "/start":
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                        [{"text": "📅 Отложить пост", "callback_data": "schedule_post"}],
                        [{"text": "ℹ️ Помощь", "callback_data": "help"}]
                    ]
                }
                await send_message(
                    user_id,
                    "👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\nНажмите **«Новый пост»** чтобы начать",
                    keyboard
                )
                return {"status": "ok"}
            
            if text == "/post":
                user_sessions[user_id] = {"step": "waiting_text"}
                await send_message(user_id, "📝 **Шаг 1/3: Текст поста**\n\nОтправьте текст поста.")
                return {"status": "ok"}
            
            # Обработка сессии
            if user_id in user_sessions:
                await handle_user_message(user_id, text, message)
        
        elif "callback_query" in update:
            callback = update["callback_query"]
            await handle_callback(callback)
        
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Ошибка обработки update: {e}")
        return {"status": "error", "message": str(e)}


async def handle_user_message(user_id: int, text: str, message: Dict):
    """Обрабатывает сообщения от пользователя в сессии"""
    session = user_sessions[user_id]
    step = session.get("step")
    
    # Шаг 1: текст
    if step == "waiting_text":
        session["text"] = text
        session["step"] = "waiting_photo"
        keyboard = {
            "inline_keyboard": [[{"text": "⏭️ Пропустить фото", "callback_data": "skip_photo"}]]
        }
        await send_message(
            user_id,
            "🖼️ **Шаг 2/3: Фото**\n\nОтправьте фото для поста (или нажмите «Пропустить фото»)",
            keyboard
        )
    
    # Шаг 2: фото
    elif step == "waiting_photo":
        photo_id = None
        if "photo" in message:
            photo_id = message["photo"][-1]["file_id"] if isinstance(message["photo"], list) else message["photo"]
        elif "document" in message and message["document"].get("mime_type", "").startswith("image/"):
            photo_id = message["document"]["file_id"]
        
        session["photo_id"] = photo_id
        session["step"] = "waiting_button"
        keyboard = {
            "inline_keyboard": [[{"text": "⏭️ Пропустить кнопку", "callback_data": "skip_button"}]]
        }
        await send_message(
            user_id,
            "🔘 **Шаг 3/3: URL-кнопка**\n\nОтправьте кнопку в формате:\n`Текст кнопки | https://ссылка.com`\n\nИли нажмите «Пропустить кнопку»",
            keyboard
        )
    
    # Шаг 3: кнопка
    elif step == "waiting_button":
        if "|" in text:
            parts = text.split("|", 1)
            session["button_title"] = parts[0].strip()
            session["button_url"] = parts[1].strip()
        
        success = await publish_to_channel(session)
        
        if success:
            await send_message(user_id, "✅ **Пост успешно опубликован в канале!**")
        else:
            await send_message(user_id, "❌ **Ошибка при публикации.** Проверьте права бота в канале.\n\nЛог ошибки отправлен разработчику.")
        
        del user_sessions[user_id]


async def handle_callback(callback: Dict):
    """Обрабатывает нажатия на inline-кнопки"""
    user_id = callback.get("from", {}).get("id")
    data = callback.get("data")
    
    logger.info(f"Callback от {user_id}: {data}")
    
    if data == "new_post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 Отправьте текст поста.")
    
    elif data == "skip_photo":
        if user_id in user_sessions:
            user_sessions[user_id]["photo_id"] = None
            user_sessions[user_id]["step"] = "waiting_button"
            await send_message(user_id, "🔘 Отправьте кнопку в формате: `Текст | https://ссылка`\nИли нажмите «Пропустить»")
    
    elif data == "skip_button":
        if user_id in user_sessions:
            session = user_sessions[user_id]
            success = await publish_to_channel(session)
            if success:
                await send_message(user_id, "✅ Пост опубликован в канале!")
            else:
                await send_message(user_id, "❌ Ошибка публикации")
            del user_sessions[user_id]
    
    elif data == "help":
        await send_message(
            user_id,
            "📖 **Помощь**\n\n"
            "• `/post` — создать новый пост\n"
            "• `/start` — главное меню\n\n"
            "**Как добавить URL-кнопку:**\n"
            "Отправьте текст и ссылку через `|`\n"
            "Пример: `Купить билет | https://example.com`"
        )
    
    elif data == "schedule_post":
        await send_message(user_id, "⏰ Функция отложенного поста в разработке.")


# ===== ЗАПУСК ВЕБ-СЕРВЕРА =====
async def health_handler(request):
    """Health check для Render"""
    return web.json_response({"status": "healthy", "bot": "running", "sessions": len(user_sessions)})


async def webhook_handler(request):
    """Обработчик POST запросов от MAX"""
    try:
        update = await request.json()
        logger.info(f"Webhook вызван")
        result = await handle_update(update)
        return web.json_response(result)
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.json_response({"status": "error"}, status=500)


async def index_handler(request):
    """Корневой обработчик"""
    return web.json_response({
        "status": "ok",
        "message": "MAX Channel Poster Bot is running",
        "endpoints": ["/webhook", "/health"]
    })


async def main():
    """Запуск веб-сервера"""
    app = web.Application()
    app.router.add_get('/', index_handler)
    app.router.add_post('/webhook', webhook_handler)
    app.router.add_get('/health', health_handler)
    
    port = int(os.getenv('PORT', 10000))
    
    logger.info(f"🚀 Запуск сервера на порту {port}")
    logger.info(f"📢 Канал ID: {CHANNEL_ID}")
    logger.info(f"🤖 Бот токен: {BOT_TOKEN[:15]}...")
    logger.info(f"✅ Сервер запущен! Доступен по адресу: https://0.0.0.0:{port}")
    
    # Запускаем веб-сервер
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # Держим сервер запущенным бесконечно
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
