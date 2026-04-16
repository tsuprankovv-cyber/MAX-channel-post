import os
import asyncio
from typing import Dict, Optional

from maxapi import Bot, Dispatcher
from maxapi.types import MessageCreated, Command, BotStarted
from maxapi.keyboard import InlineKeyboard, InlineKeyboardButton

# ===== КОНФИГУРАЦИЯ =====
BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', 'f9LHodD0cOJ1zU51CUFdStMuwVfX0aNdze31RQduaSV9zy_WezacnZe9eAz0GKesBabkLpdRN_rK6ATTj6Za')
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042')
PORT = int(os.getenv('PORT', 10000))

# ===== ИНИЦИАЛИЗАЦИЯ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище сессий пользователей
user_sessions: Dict[int, Dict] = {}


# ===== ФУНКЦИЯ ПУБЛИКАЦИИ В КАНАЛ =====
async def publish_to_channel(post_data: Dict) -> bool:
    """Публикует пост в канал с поддержкой URL-кнопок"""
    try:
        # Создаем клавиатуру с URL-кнопкой если есть
        keyboard = None
        if 'button_title' in post_data and 'button_url' in post_data:
            keyboard = InlineKeyboard([
                [InlineKeyboardButton(
                    text=post_data['button_title'],
                    url=post_data['button_url']
                )]
            ])
        
        # Отправляем сообщение в канал
        if 'photo_id' in post_data and post_data['photo_id']:
            await bot.send_photo(
                chat_id=CHANNEL_ID,
                photo=post_data['photo_id'],
                caption=post_data.get('text', ''),
                parse_mode='markdown',
                reply_markup=keyboard
            )
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=post_data.get('text', ''),
                parse_mode='markdown',
                reply_markup=keyboard
            )
        return True
    except Exception as e:
        print(f"Ошибка публикации: {e}")
        return False


# ===== ОБРАБОТЧИК ЗАПУСКА БОТА =====
@dp.bot_started()
async def on_bot_started(event: BotStarted):
    """Когда пользователь нажимает 'Начать' в диалоге с ботом"""
    keyboard = InlineKeyboard([
        [InlineKeyboardButton(text="➕ Новый пост", callback_data="new_post")],
        [InlineKeyboardButton(text="📅 Отложить пост", callback_data="schedule_post")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    await event.bot.send_message(
        chat_id=event.chat_id,
        text="👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\n📌 **Что умею:**\n• Текст с форматированием\n• Фото + подпись\n• URL-кнопки под постом\n\nНажмите **«Новый пост»** чтобы начать",
        reply_markup=keyboard,
        parse_mode='markdown'
    )


# ===== ОБРАБОТЧИК КОМАНДЫ /START =====
@dp.message_created(Command('start'))
async def cmd_start(event: MessageCreated):
    keyboard = InlineKeyboard([
        [InlineKeyboardButton(text="➕ Новый пост", callback_data="new_post")],
        [InlineKeyboardButton(text="📅 Отложить пост", callback_data="schedule_post")],
        [InlineKeyboardButton(text="ℹ️ Помощь", callback_data="help")]
    ])
    await event.message.answer(
        "👋 **MAX Channel Poster Bot**\n\nЯ помогаю публиковать посты в каналы.\n\nНажмите **«Новый пост»** чтобы начать",
        reply_markup=keyboard,
        parse_mode='markdown'
    )


# ===== ОБРАБОТЧИК КОМАНДЫ /POST =====
@dp.message_created(Command('post'))
async def cmd_post(event: MessageCreated):
    user_sessions[event.chat_id] = {'step': 'waiting_text'}
    await event.message.answer(
        "📝 **Шаг 1/3: Текст поста**\n\nОтправьте текст поста.\nПоддерживается **жирный** и *курсив*\n\nПример:\n`**Заголовок**\nТекст поста`",
        parse_mode='markdown'
    )


# ===== ОБРАБОТЧИК ТЕКСТОВЫХ СООБЩЕНИЙ =====
@dp.message_created()
async def handle_message(event: MessageCreated):
    chat_id = event.chat_id
    
    if chat_id not in user_sessions:
        return
    
    session = user_sessions[chat_id]
    step = session.get('step')
    
    # Шаг 1: получение текста
    if step == 'waiting_text':
        session['text'] = event.message.body.text
        session['step'] = 'waiting_photo'
        
        keyboard = InlineKeyboard([
            [InlineKeyboardButton(text="⏭️ Пропустить фото", callback_data="skip_photo")]
        ])
        await event.message.answer(
            "🖼️ **Шаг 2/3: Фото**\n\nОтправьте фото для поста (или нажмите «Пропустить фото»)",
            reply_markup=keyboard,
            parse_mode='markdown'
        )
    
    # Шаг 2: получение фото
    elif step == 'waiting_photo':
        # Проверяем, есть ли фото в сообщении
        photo_id = None
        if hasattr(event.message, 'attachments') and event.message.attachments:
            for attach in event.message.attachments:
                if attach.type == 'image':
                    photo_id = attach.payload.file_id
                    break
        
        session['photo_id'] = photo_id
        session['step'] = 'waiting_button'
        
        await event.message.answer(
            "🔘 **Шаг 3/3: URL-кнопка**\n\nОтправьте кнопку в формате:\n`Текст кнопки | https://ссылка.com`\n\nИли нажмите «Пропустить кнопку»",
            reply_markup=InlineKeyboard([
                [InlineKeyboardButton(text="⏭️ Пропустить кнопку", callback_data="skip_button")]
            ]),
            parse_mode='markdown'
        )
    
    # Шаг 3: получение кнопки
    elif step == 'waiting_button':
        text = event.message.body.text
        
        if '|' in text:
            parts = text.split('|', 1)
            session['button_title'] = parts[0].strip()
            session['button_url'] = parts[1].strip()
        
        # Публикуем пост в канал
        success = await publish_to_channel(session)
        
        if success:
            await event.message.answer("✅ **Пост успешно опубликован в канале!**", parse_mode='markdown')
        else:
            await event.message.answer("❌ **Ошибка при публикации.** Проверьте права бота в канале.", parse_mode='markdown')
        
        del user_sessions[chat_id]


# ===== ОБРАБОТЧИК НАЖАТИЙ НА INLINE-КНОПКИ =====
@dp.callback_query()
async def handle_callback(event):
    """Обработка нажатий на inline-кнопки"""
    data = event.callback_query.data
    chat_id = event.chat_id
    
    if data == "new_post":
        user_sessions[chat_id] = {'step': 'waiting_text'}
        await event.bot.send_message(
            chat_id=chat_id,
            text="📝 Отправьте текст поста. Поддерживается **жирный** и *курсив*",
            parse_mode='markdown'
        )
        await event.answer()
    
    elif data == "skip_photo":
        if chat_id in user_sessions:
            user_sessions[chat_id]['photo_id'] = None
            user_sessions[chat_id]['step'] = 'waiting_button'
            await event.bot.send_message(
                chat_id=chat_id,
                text="🔘 Отправьте кнопку в формате: `Текст | https://ссылка`\nИли нажмите «Пропустить»",
                parse_mode='markdown'
            )
        await event.answer()
    
    elif data == "skip_button":
        if chat_id in user_sessions:
            session = user_sessions[chat_id]
            success = await publish_to_channel(session)
            if success:
                await event.bot.send_message(chat_id=chat_id, text="✅ Пост опубликован в канале!")
            else:
                await event.bot.send_message(chat_id=chat_id, text="❌ Ошибка публикации")
            del user_sessions[chat_id]
        await event.answer()
    
    elif data == "help":
        await event.bot.send_message(
            chat_id=chat_id,
            text="📖 **Помощь**\n\n"
                 "• `/post` — создать новый пост\n"
                 "• `/start` — главное меню\n\n"
                 "**Как добавить URL-кнопку:**\n"
                 "Отправьте текст и ссылку через `|`\n"
                 "Пример: `Купить билет | https://example.com`\n\n"
                 "**Форматирование текста:**\n"
                 "`**жирный**` *курсив* `код`",
            parse_mode='markdown'
        )
        await event.answer()
    
    elif data == "schedule_post":
        await event.bot.send_message(
            chat_id=chat_id,
            text="⏰ Функция отложенного поста в разработке. Будет готова в следующей версии."
        )
        await event.answer()


# ===== ЗАПУСК БОТА (LONG POLLING) =====
async def main():
    print("🚀 Запуск бота MAX Channel Poster...")
    print(f"📢 Канал ID: {CHANNEL_ID}")
    print(f"🤖 Бот токен: {BOT_TOKEN[:15]}...")
    
    # Удаляем старые вебхуки, если были
    await bot.delete_webhook()
    
    # Запускаем long polling (проще для Render)
    await dp.start_polling(bot)
    print("✅ Бот запущен и слушает сообщения!")


if __name__ == '__main__':
    asyncio.run(main())
