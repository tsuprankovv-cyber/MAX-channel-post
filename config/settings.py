"""
Настройки бота из .env
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# === Основные ===
BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

# === Безопасность ===
BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
REQUIRE_PASSWORD = os.getenv('REQUIRE_PASSWORD', 'true').lower() == 'true'

# === Настройки ===
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG').upper()
MAX_MEDIA_ITEMS = int(os.getenv('MAX_MEDIA_ITEMS', '10'))
SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '120'))

# === Пути ===
# 🔥 Используем корень проекта вместо /tmp/ чтобы файлы не удалялись при сне
DATA_DIR = Path(os.getenv('DATA_DIR', '.'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_FILE = DATA_DIR / 'authorized_users.json'
STATS_FILE = DATA_DIR / 'stats.json'
MEDIA_CACHE_DIR = DATA_DIR / 'media_cache'
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = DATA_DIR / 'bot.log'
