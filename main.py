import os
import asyncio
from typing import Dict, Optional

from maxbot.bot import Bot
from maxbot.dispatcher import Dispatcher
from maxbot.types import Message, Callback, InlineKeyboardMarkup, InlineKeyboardButton

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', 'f9LHodD0cOJ1zU51CUFdStMuwVfX0aNdze31RQduaSV9zy_WezacnZe9eAz0GKesBabkLpdRN_rK6ATTj6Za')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042')

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

# Хранилище сессий пользователей
user_sessions: Dict[int, Dict] = {}


# ===== ФУНКЦИЯ ПУБЛИКАЦИИ =====
async def publish_to_channel(post_data: Dict) -> bool:
    """Публикует пост в канал с поддержкой URL-кнопок"""
    try:
        keyboard = None
        if 'button_title' in post_data and 'button_url' in post_data:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=post_data['button_title'],
                    url=post_data['button_url']      # type="link" для URL-кнопки
                )]
            ])
        
        if 'photo_id' in post_data and post_data['photo_id']:
            await bot.send_file(
                chat_id=CHANNEL_ID,
                file_id=post_data['photo_id'],
                caption=post_data.get('text', ''),
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_data.get('text', ''),
                notify=True,
                reply_markup=keyboard,
                format="markdown"
            )
        return True
    except Exception as e:
        print(f"Ошибка публикации: {e}")
        return True


# ===== ОБРАБОТЧИК КОМАНДЫ /START =====
@dp.message(lambda msg: msg.text == '/start')
async def cmd_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый пост", callback_data="new_post")],
        [InlineKeyboardButton(text="📅 Отложить пост", callback_data="schedule_post")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    await bot.send_message(
        chat_id=message.sender.id,
        text="👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\nНажмите **«Новый пост»** чтобы начать",
        reply_markup=keyboard,
        format="markdown"
    )


# ===== ОБРАБОТЧИК КОМАНДЫ /POST =====
@dp.message(lambda msg: msg.text == '/post')
async def cmd_post(message: Message):
    user_sessions[message.sender.id] = {'step': 'waiting_text'}
    await bot.send_message(
        chat_id=message.sender.id,
        text="📝 **Шаг 1/3: Текст поста**\n\nОтправьте текст поста.\nПоддерживается **жирный** и *курсив*",
        format="markdown"
    )


# ===== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ =====
@dp.message()
async def handle_message(message: Message):
    chat_id = message.sender.id
    
    if chat_id not in user_sessions:
        return
    
    session = user_sessions[chat_id]
    step = session.get('step')
    
    # Шаг 1: текст
    if step == 'waiting_text':
        session['text'] = message.text
        session['step'] = 'waiting_photo'
        await bot.send_message(
            chat_id=chat_id,
            text="🖼️ **Шаг 2/3: Фото**\n\nОтправьте фото для поста (или отправьте слово 'пропустить')",
            format="markdown"
        )
    
    # Шаг 2: фото
    elif step == 'waiting_photo':
        if message.text and message.text.lower() == 'пропустить':
            session['photo_id'] = None
            session['step'] = 'waiting_button'
            await bot.send_message(
                chat_id=chat_id,
                text="🔘 **Шаг 3/3: URL-кнопка**\n\nОтправьте в формате:\n`Текст кнопки | https://ссылка.com`\n\nИли отправьте 'пропустить'",
                format="markdown"
            )
        else:
            photo_id = None
            if hasattr(message, 'attachments') and message.attachments:
                for attach in message.attachments:
                    if attach.type == 'image':
                        photo_id = attach.id
                        break
            
            if photo_id:
                session['photo_id'] = photo_id
                session['step'] = 'waiting_button'
                await bot.send_message(
                    chat_id=chat_id,
                    text="🔘 **Шаг 3/3: URL-кнопка**\n\nОтправьте в формате:\n`Текст кнопки | https://ссылка.com`\n\nИли отправьте 'пропустить'",
                    format="markdown"
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Фото не найдено. Попробуйте еще раз или отправьте 'пропустить'"
                )
    
    # Шаг 3: кнопка
    elif step == 'waiting_button':
        if message.text and message.text.lower() == 'пропустить':
            success = await publish_to_channel(session)
        elif '|' in message.text:
            parts = message.text.split('|', 1)
            session['button_title'] = parts[0].strip()
            session['button_url'] = parts[1].strip()
            success = await publish_to_channel(session)
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ Неверный формат. Используйте: `Текст | ссылка` или отправьте 'пропустить'",
                format="markdown"
            )
            return
        
        if success:
            await bot.send_message(
                chat_id=chat_id,
                text="✅ **Пост успешно опубликован в канале!**",
                format="markdown"
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text="❌ **Ошибка при публикации.** Проверьте права бота в канале.",
                format="markdown"
            )
        del user_sessions[chat_id]


# ===== ОБРАБОТЧИК НАЖАТИЙ НА INLINE-КНОПКИ =====
@dp.callback()
async def handle_callback(callback: Callback):
    chat_id = callback.user.id
    data = callback.payload
    
    if data == "new_post":
        user_sessions[chat_id] = {'step': 'waiting_text'}
        await bot.send_message(
            chat_id=chat_id,
            text="📝 Отправьте текст поста"
        )
    
    elif data == "help":
        await bot.send_message(
            chat_id=chat_id,
            text="📖 **Помощь**\n\n"
                 "• `/post` — создать новый пост\n"
                 "• `/start` — главное меню\n\n"
                 "**Как добавить URL-кнопку:**\n"
                 "Отправьте текст и ссылку через `|`\n"
                 "Пример: `Купить билет | https://example.com`",
            format="markdown"
        )
    
    elif data == "schedule_post":
        await bot.send_message(
            chat_id=chat_id,
            text="⏰ Функция отложенного поста в разработке"
        )


# ===== ЗАПУСК =====
async def main():
    print("🚀 Запуск бота...")
    print(f"📢 Канал ID: {CHANNEL_ID}")
    await dp.start_polling()
    print("✅ Бот запущен и слушает сообщения!")


if __name__ == '__main__':
    asyncio.run(main())
