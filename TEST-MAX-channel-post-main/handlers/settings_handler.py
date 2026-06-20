"""
Обработчики настроек и статистики
"""
from core.logger import get_logger

logger = get_logger(__name__)


async def handle_stats(send, stats):
    logger.info("[STATS] Requested")
    all_stats = stats.get_stats()
    if not all_stats:
        await send(
            "<b>📊 Статистика пуста</b>\n\n"
            "─────────────────\n"
            "📝 /post | 🔙 /start"
        )
        return
    
    report = ["<b>📊 Последние посты:</b>\n"]
    for item in all_stats[-10:]:
        report.append(f"• <code>{item['message_id'][:12]}...</code> | 👁 {item.get('views', 0)}")
    report.append("\n─────────────────")
    report.append("📝 /post | 🔙 /start")
    await send('\n'.join(report))


async def handle_settings(send):
    logger.info("[SETTINGS] Requested")
    await send(
        "<b>⚙️ Настройки</b>\n\n"
        "📋 /templates — управление шаблонами\n"
        "🔑 /set_password — сменить пароль\n"
        "👥 /list_admins — список админов\n"
        "📡 /set_channel — сменить канал\n\n"
        "─────────────────\n"
        "📝 /post | 🔙 /start"
    )


async def handle_set_channel(user_id, new_id, send):
    logger.info(f"[SET-CH] user={user_id} channel={new_id}")
    await send(
        f"<b>✅ Канал изменён</b>\n"
        f"Новый ID: <code>{new_id}</code>\n"
        "Требуется перезапуск бота.\n\n"
        "─────────────────\n"
        "🔙 /settings — назад"
    )


async def handle_set_password(user_id, new_pwd, send, auth):
    logger.info(f"[SET-PASS] user={user_id}")
    auth.change_password(new_pwd)
    await send(
        "<b>✅ Пароль изменён</b>\n\n"
        "Все пользователи должны авторизоваться заново.\n\n"
        "─────────────────\n"
        "🔙 /settings — назад"
    )


async def handle_list_admins(send, auth):
    logger.info("[LIST-ADMINS] Requested")
    admins = auth.authorized
    if not admins:
        await send(
            "<b>👥 Нет авторизованных</b>\n\n"
            "─────────────────\n"
            "🔙 /settings — назад"
        )
        return
    
    report = ["<b>👥 Авторизованные:</b>\n"]
    for uid, data in admins.items():
        report.append(f"• <code>{uid}</code> | {data.get('auth_time', '')[:16]}")
    report.append("\n─────────────────")
    report.append("🔙 /settings — назад")
    await send('\n'.join(report))
