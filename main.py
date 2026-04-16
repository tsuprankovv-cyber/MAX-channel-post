import os
import asyncio
import json
from typing import Dict, Optional

from aiohttp import ClientSession, ClientTimeout
from dotenv import load_dotenv

# ===== ЗАГРУЗКА ПЕРЕМЕННЫХ =====
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', 'f9LHodD0cOJ1zU51CUFdStMuwVfX0aNdze31RQduaSV9zy_WezacnZe9eAz0GKesBabkLpdRN_rK6ATTj6Za')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042')
BASE_API_URL = "https://platform-api.max.ru"

# Хранилище сессий пользователей
user_sessions: Dict[int, Dict] = {}


# ===== ФУНКЦИИ ДЛЯ РАБОТЫ С API MAX =====
async def api_request(method: str, endpoint: str, data: Dict = None) -> Dict:
    """Универсальная функция для запросов к API MAX"""
    headers = {
        "Authorization": BOT_TOKEN,
        "Content-Type": "application/json"
    }
    
    url = f"{BASE_API_URL}{endpoint}"
    timeout = ClientTimeout(total=30)
    
    async with ClientSession() as session:
        if method.upper() == "GET":
            async with session.get(url, headers=headers, timeout=timeout) as response:
                return await response.json()
        else:
            async with session.post(url, headers=headers, json=data, timeout=timeout) as response:
                return await response.json()


async def send_message(chat_id: int, text: str, keyboard: Dict = None) -> bool:
    """Отправляет текстовое сообщение в чат или канал"""
    try:
        payload = {"text": text}
        if keyboard:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard
            }]
        
        endpoint = f"/messages?user_id={chat_id}" if chat_id > 0 else f"/messages?channel_id={abs(chat_id)}"
        result = await api_request("POST", endpoint, payload)
        return "message_id" in result
    except Exception as e:
        print(f"Ошибка отправки сообщения: {e}")
        return False


async def send_photo(chat_id: int, photo_file_id: str, caption: str = "", keyboard: Dict = None) -> bool:
    """Отправляет фото в чат или канал"""
    try:
        # Для фото используем send_file метод
        payload = {
            "file_id": photo_file_id,
            "caption": caption
        }
        if keyboard:
            payload["attachments"] = [{
                "type": "inline_keyboard",
                "payload": keyboard
            }]
        
        endpoint = f"/sendFile?user_id={chat_id}" if chat_id > 0 else f"/sendFile?channel_id={abs(chat_id)}"
        result = await api_request("POST", endpoint, payload)
        return "message_id" in result
    except Exception as e:
        print(f"Ошибка отправки фото: {e}")
        return False


def create_url_button(text: str, url: str) -> Dict:
    """Создает URL-кнопку для inline-клавиатуры"""
    return {
        "buttons": [[{
            "type": "link",
            "text": text,
            "url": url
        }]]
    }


async def publish_to_channel(post_data: Dict) -> bool:
    """Публикует пост в канал"""
    try:
        keyboard = None
        if 'button_title' in post_data and 'button_url' in post_data:
            keyboard = create_url_button(post_data['button_title'], post_data['button_url'])
        
        channel_id = abs(int(CHANNEL_ID))
        
        if 'photo_id' in post_data and post_data['photo_id']:
            return await send_photo(channel_id, post_data['photo_id'], post_data.get('text', ''), keyboard)
        else:
            return await send_message(channel_id, post_data.get('text', ''), keyboard)
    except Exception as e:
        print(f"Ошибка публикации в канал: {e}")
        return False


# ===== ОБРАБОТКА ВХОДЯЩИХ СООБЩЕНИЙ (WEBHOOK) =====
async def handle_update(update: Dict) -> Dict:
    """Обрабатывает входящее обновление от MAX"""
    try:
        # Проверяем тип обновления
        if "message" in update:
            message = update["message"]
            chat_id = message.get("chat", {}).get("id")
            text = message.get("text", "")
            sender_id = message.get("from", {}).get("id")
            
            # Если сообщение из чата с ботом
            if chat_id and chat_id > 0:
                return await handle_user_message(sender_id, text, message)
        
        elif "callback_query" in update:
            callback = update["callback_query"]
            return await handle_callback(callback)
        
        return {"status": "ok"}
    except Exception as e:
        print(f"Ошибка обработки update: {e}")
        return {"status": "error", "message": str(e)}


async def handle_user_message(user_id: int, text: str, message: Dict) -> Dict:
    """Обрабатывает сообщения от пользователя"""
    
    # Команда /start
    if text == "/start":
        keyboard = {
            "buttons": [
                [{"type": "callback", "text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"type": "callback", "text": "📅 Отложить пост", "callback_data": "schedule_post"}],
                [{"type": "callback", "text": "ℹ️ Помощь", "callback_data": "help"}]
            ]
        }
        await send_message(
            user_id,
            "👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\n📌 **Что умею:**\n• Текст с форматированием\n• Фото + подпись\n• URL-кнопки под постом\n\nНажмите **«Новый пост»** чтобы начать",
            keyboard
        )
        return {"status": "ok"}
    
    # Команда /post
    if text == "/post":
        user_sessions[user_id] = {"step": "waiting_text"}
        await send_message(user_id, "📝 **Шаг 1/3: Текст поста**\n\nОтправьте текст поста.")
        return {"status": "ok"}
    
    # Обработка сессии создания поста
    if user_id in user_sessions:
        session = user_sessions[user_id]
        step = session.get("step")
        
        # Шаг 1: текст
        if step == "waiting_text":
            session["text"] = text
            session["step"] = "waiting_photo"
            keyboard = {
                "buttons": [[{"type": "callback", "text": "⏭️ Пропустить фото", "callback_data": "skip_photo"}]]
            }
            await send_message(
                user_id,
                "🖼️ **Шаг 2/3: Фото**\n\nОтправьте фото для поста (или нажмите «Пропустить фото»)",
                keyboard
            )
        
        # Шаг 2: фото (проверяем вложения)
        elif step == "waiting_photo":
            # Проверяем, есть ли фото в сообщении
            photo_id = None
            if "attachments" in message:
                for attach in message["attachments"]:
                    if attach.get("type") == "image":
                        photo_id = attach.get("file_id")
                        break
            
            session["photo_id"] = photo_id
            session["step"] = "waiting_button"
            keyboard = {
                "buttons": [[{"type": "callback", "text": "⏭️ Пропустить кнопку", "callback_data": "skip_button"}]]
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
                await send_message(user_id, "❌ **Ошибка при публикации.** Проверьте права бота в канале.")
            
            del user_sessions[user_id]
    
    return {"status": "ok"}


async def handle_callback(callback: Dict) -> Dict:
    """Обрабатывает нажатия на inline-кнопки"""
    user_id = callback.get("from", {}).get("id")
    data = callback.get("data")
    
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
    
    return {"status": "ok"}


# ===== ЗАПУСК ВЕБ-СЕРВЕРА (ДЛЯ RENDER) =====
async def main():
    """Запуск веб-сервера для приема webhook"""
    from aiohttp import web
    
    app = web.Application()
    
    async def webhook_handler(request):
        """Обработчик POST запросов от MAX"""
        try:
            update = await request.json()
            result = await handle_update(update)
            return web.json_response(result)
        except Exception as e:
            print(f"Webhook error: {e}")
            return web.json_response({"status": "error"}, status=500)
    
    async def health_handler(request):
        """Health check для Render"""
        return web.json_response({"status": "healthy"})
    
    app.router.add_post('/webhook', webhook_handler)
    app.router.add_get('/health', health_handler)
    
    port = int(os.getenv('PORT', 10000))
    print(f"🚀 Запуск сервера на порту {port}")
    print(f"📢 Канал ID: {CHANNEL_ID}")
    print(f"🤖 Бот токен: {BOT_TOKEN[:15]}...")
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    print(f"✅ Сервер запущен! Webhook доступен по адресу: /webhook")
    
    # Держим сервер запущенным
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
