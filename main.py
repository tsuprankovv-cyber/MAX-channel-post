import asyncio
import logging
import os
import json
from typing import Dict, Optional

from aiohttp import ClientSession, ClientTimeout
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
CHANNEL_ID = int(os.getenv('MAX_CHANNEL_ID', '-72890925476042'))
BASE_API_URL = "https://api.max.ru"

# Хранилище сессий пользователей
user_sessions: Dict[int, Dict] = {}

# Глобальная сессия для HTTP-запросов
session: Optional[ClientSession] = None


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
    """Отправляет текстовое сообщение в чат"""
    try:
        endpoint = f"/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
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
        
        endpoint = f"/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHANNEL_ID,
            "text": post_data.get('text', ''),
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


# ===== ФУНКЦИЯ ПОЛУЧЕНИЯ ОБНОВЛЕНИЙ (LONG POLLING) =====
async def get_updates(offset: int = 0) -> list:
    """Получает обновления от MAX API"""
    endpoint = f"/bot{BOT_TOKEN}/getUpdates"
    payload = {"offset": offset, "timeout": 30}
    
    try:
        result = await api_request("POST", endpoint, payload)
        if result.get("ok") and "result" in result:
            return result["result"]
        return []
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return []


# ===== ОБРАБОТКА СООБЩЕНИЙ =====
async def handle_message(message: Dict):
    """Обрабатывает входящее сообщение"""
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")
    
    if not chat_id:
        return
    
    logger.info(f"Сообщение от {chat_id}: {text}")
    
    # Команда /start
    if text == "/start":
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"text": "📅 Отложить пост", "callback_data": "schedule_post"}],
                [{"text": "ℹ️ Помощь", "callback_data": "help"}]
            ]
        }
        await send_message(
            chat_id,
            "👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\nНажмите **«Новый пост»** чтобы начать",
            keyboard
        )
        return
    
    # Команда /post
    if text == "/post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 **Шаг 1/3: Текст поста**\n\nОтправьте текст поста.")
        return
    
    # Обработка сессии создания поста
    if chat_id in user_sessions:
        session = user_sessions[chat_id]
        step = session.get("step")
        
        if step == "waiting_text":
            session["text"] = text
            session["step"] = "waiting_photo"
            keyboard = {
                "inline_keyboard": [[{"text": "⏭️ Пропустить фото", "callback_data": "skip_photo"}]]
            }
            await send_message(
                chat_id,
                "🖼️ **Шаг 2/3: Фото**\n\nОтправьте фото для поста (или нажмите «Пропустить фото»)\n\n⚠️ Функция фото временно отключена, фото будет добавлено позже.",
                keyboard
            )
        
        elif step == "waiting_photo":
            # Пропускаем фото для тестирования
            session["photo_id"] = None
            session["step"] = "waiting_button"
            keyboard = {
                "inline_keyboard": [[{"text": "⏭️ Пропустить кнопку", "callback_data": "skip_button"}]]
            }
            await send_message(
                chat_id,
                "🔘 **Шаг 3/3: URL-кнопка**\n\nОтправьте кнопку в формате:\n`Текст кнопки | https://ссылка.com`\n\nИли нажмите «Пропустить кнопку»",
                keyboard
            )
        
        elif step == "waiting_button":
            if "|" in text:
                parts = text.split("|", 1)
                session["button_title"] = parts[0].strip()
                session["button_url"] = parts[1].strip()
            
            success = await publish_to_channel(session)
            
            if success:
                await send_message(chat_id, "✅ **Пост успешно опубликован в канале!**")
            else:
                await send_message(chat_id, "❌ **Ошибка при публикации.** Проверьте права бота в канале.")
            
            del user_sessions[chat_id]


async def handle_callback(callback_query: Dict):
    """Обрабатывает нажатия на inline-кнопки"""
    data = callback_query.get("data", "")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    
    if not chat_id:
        return
    
    logger.info(f"Callback от {chat_id}: {data}")
    
    if data == "new_post":
        user_sessions[chat_id] = {"step": "waiting_text"}
        await send_message(chat_id, "📝 Отправьте текст поста.")
    
    elif data == "skip_photo":
        if chat_id in user_sessions:
            user_sessions[chat_id]["photo_id"] = None
            user_sessions[chat_id]["step"] = "waiting_button"
            await send_message(chat_id, "🔘 Отправьте кнопку в формате: `Текст | https://ссылка`")
    
    elif data == "skip_button":
        if chat_id in user_sessions:
            session = user_sessions[chat_id]
            success = await publish_to_channel(session)
            if success:
                await send_message(chat_id, "✅ Пост опубликован в канале!")
            else:
                await send_message(chat_id, "❌ Ошибка публикации")
            del user_sessions[chat_id]
    
    elif data == "help":
        await send_message(
            chat_id,
            "📖 **Помощь**\n\n"
            "• `/post` — создать новый пост\n"
            "• `/start` — главное меню\n\n"
            "**Как добавить URL-кнопку:**\n"
            "Отправьте текст и ссылку через `|`\n"
            "Пример: `Купить билет | https://example.com`"
        )
    
    elif data == "schedule_post":
        await send_message(chat_id, "⏰ Функция отложенного поста в разработке.")


# ===== ЗАПУСК LONG POLLING =====
async def main():
    global session
    
    logger.info("🚀 Запуск бота MAX Channel Poster...")
    logger.info(f"📢 Канал ID: {CHANNEL_ID}")
    logger.info(f"🤖 Бот токен: {BOT_TOKEN[:15]}...")
    
    session = ClientSession()
    offset = 0
    
    logger.info("✅ Бот запущен и слушает сообщения!")
    
    try:
        while True:
            updates = await get_updates(offset)
            
            for update in updates:
                if "message" in update:
                    await handle_message(update["message"])
                if "callback_query" in update:
                    await handle_callback(update["callback_query"])
                
                # Обновляем offset
                if update.get("update_id", 0) >= offset:
                    offset = update["update_id"] + 1
            
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())
