"""
Web server — создание приложения, startup, cleanup
"""
import asyncio
import logging
import os
from aiohttp import web, ClientSession

from config.settings import (
    BOT_TOKEN, CHANNEL_ID, BASE_API_URL, RENDER_EXTERNAL_URL,
    BOT_PASSWORD, REQUIRE_PASSWORD, LOG_LEVEL,
    MAX_MEDIA_ITEMS, SCHEDULER_TIMEZONE, API_TIMEOUT,
    AUTH_FILE, STATS_FILE, MEDIA_CACHE_DIR, LOG_FILE, DATA_DIR
)
from core.logger import setup_logger, get_logger
from core.auth import AuthManager
from core.state import StateManager
from core.stats import StatsCollector
from api.client import MAXClient
from api.media import MediaManager
from services.scheduler import PublishScheduler

logger = get_logger(__name__)


async def self_ping():
    """Каждые 5 минут пингует самого себя чтобы не засыпать"""
    await asyncio.sleep(60)  # Ждём 1 минуту после старта
    
    while True:
        try:
            async with ClientSession() as session:
                url = f"{RENDER_EXTERNAL_URL}/health"
                async with session.get(url) as resp:
                    logger.info(f"[PING] Self-ping: {resp.status}")
        except Exception as e:
            logger.warning(f"[PING] Failed: {e}")
        
        await asyncio.sleep(300)  # 5 минут


async def health_check(request):
    return web.json_response({"ok": True, "version": "7.1", "timestamp": int(asyncio.get_event_loop().time())})


async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "7.1"})


async def webhook_route(request):
    app = request.app
    result = await webhook_handler(request, app['router'])
    if result is None:
        return web.Response(status=405)
    return web.Response(status=200)


def create_app():
    # Настройка логгера
    setup_logger(LOG_LEVEL, LOG_FILE)
    logger.info("=" * 60)
    logger.info("🚀 MAX Channel Poster v7.1")
    logger.info(f"📡 Channel: {CHANNEL_ID}")
    logger.info(f"🔗 Webhook: {RENDER_EXTERNAL_URL}/webhook")
    logger.info(f"📁 Data dir: {DATA_DIR}")
    logger.info("=" * 60)
    
    # Инициализация компонентов
    auth = AuthManager(BOT_PASSWORD, AUTH_FILE, REQUIRE_PASSWORD)
    state = StateManager()
    max_client = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    media_mgr = MediaManager(MEDIA_CACHE_DIR, MAX_MEDIA_ITEMS)
    stats = StatsCollector(STATS_FILE)
    scheduler = PublishScheduler(max_client, CHANNEL_ID, SCHEDULER_TIMEZONE)
    
    # Импорт handlers router
    from handlers.router import create_router
    router = create_router(auth, state, max_client, media_mgr, scheduler, stats, CHANNEL_ID)
    
    # Импорт webhook handler
    from web.webhook import webhook_handler as wh
    
    async def wh_route(request):
        result = await wh(request, router)
        if result is None:
            return web.Response(status=405)
        return web.Response(status=200)
    
    # Создание приложения
    app = web.Application()
    app['auth'] = auth
    app['state'] = state
    app['max_client'] = max_client
    app['media_mgr'] = media_mgr
    app['stats'] = stats
    app['scheduler'] = scheduler
    app['router'] = router
    
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_post('/webhook', wh_route)
    
    async def on_startup(app):
        scheduler.start()
        if RENDER_EXTERNAL_URL:
            await max_client.register_webhook(f"{RENDER_EXTERNAL_URL}/webhook", CHANNEL_ID)
        
        # Запускаем самопинг
        asyncio.create_task(self_ping())
        
        logger.info("✅ Ready!")
    
    async def on_cleanup(app):
        scheduler.stop()
        await max_client.close()
        logger.info("🔚 Shutdown")
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app
