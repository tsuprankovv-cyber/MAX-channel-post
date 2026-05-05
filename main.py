"""
MAX Channel Poster Bot — FINAL VERSION WITH MAX LOGGING
✅ Авторизация по паролю (из env, с повторным запросом при смене)
✅ Медиа: фото/видео/коллаж (до 10 файлов)
✅ Форматирование: прозрачная передача markup из MAX
✅ Кнопки: множественные, формат "Текст | ссылка" (каждая с новой строки)
✅ Предпросмотр перед публикацией
✅ Отложенная публикация (формат: ГГГГ-ММ-ДД ЧЧ:ММ)
✅ Редактирование постов
✅ Статистика: просмотры, клики (с логированием)
✅ Сервисное меню: /set_channel, /set_password, /list_admins
✅ Очистка временных файлов
✅ 🔥🔥🔥 МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ НА КАЖДОМ ШАГЕ 🔥🔥🔥
"""
import asyncio
import logging
import os
import json
import time
import re
import tempfile
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union
from pathlib import Path
from contextlib import asynccontextmanager

from aiohttp import web, ClientSession, ClientTimeout, FormData, ClientError
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===================================================================
# 🔧 CONFIG & INIT
# ===================================================================
load_dotenv()

# === Обязательные переменные ===
BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

# === Настройки ===
BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG').upper()
MAX_MEDIA_ITEMS = int(os.getenv('MAX_MEDIA_ITEMS', '10'))
SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '60'))

# === Пути для данных ===
DATA_DIR = Path(os.getenv('DATA_DIR', '/tmp/max-bot'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_FILE = DATA_DIR / 'authorized_users.json'
STATS_FILE = DATA_DIR / 'stats.json'
MEDIA_CACHE_DIR = DATA_DIR / 'media_cache'
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# === Настройка логирования (МАКСИМАЛЬНОЕ) ===
log_file = DATA_DIR / 'bot.log'
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format='%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    force=True,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding='utf-8', mode='a', delay=True)
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"🔧 LOG_LEVEL={LOG_LEVEL}, LOG_FILE={log_file}")

# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    """Управление авторизацией пользователей"""
    
    def __init__(self, password: str, auth_file: Path):
        self.password = password
        self.auth_file = auth_file
        self.authorized: Dict[int, Dict] = {}  # user_id -> {auth_time, password_hash}
        self.failed_attempts: Dict[int, int] = {}  # user_id -> count
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 AuthManager initialized | password_hash={hashlib.sha256(password.encode()).hexdigest()[:8]}...")
    
    def _load_from_file(self):
        """Загружает авторизованных пользователей из файла"""
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] 📥 Loaded {len(self.authorized)} authorized users from {self.auth_file}")
            except Exception as e:
                logger.error(f"[AUTH] ❌ Failed to load auth file: {e}")
    
    def _save_to_file(self):
        """Сохраняет состояние в файл (эфемерно на Render, но полезно)"""
        try:
            data = {
                'users': {str(k): v for k, v in self.authorized.items()},
                'failed': {str(k): v for k, v in self.failed_attempts.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"[AUTH] 💾 Saved auth state to {self.auth_file}")
        except Exception as e:
            logger.warning(f"[AUTH] ⚠️ Failed to save auth file: {e}")
    
    def check_password(self, user_id: int, password: str) -> bool:
        """Проверяет пароль пользователя"""
        logger.info(f"[AUTH] 🔍 check_password(user_id={user_id}, password={'*' * len(password)})")
        
        # Если пароль совпадает с текущим — авторизуем
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat(),
                'password_hash': hashlib.sha256(self.password.encode()).hexdigest()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            logger.info(f"[AUTH] ✅ User {user_id} authorized successfully")
            return True
        
        # Неверный пароль
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        attempts = self.failed_attempts[user_id]
        logger.warning(f"[AUTH] ❌ User {user_id} failed attempt #{attempts}")
        self._save_to_file()
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        """Проверяет, авторизован ли пользователь"""
        if user_id in self.authorized:
            auth_data = self.authorized[user_id]
            # Проверяем, не сменился ли пароль
            if auth_data.get('password_hash') == hashlib.sha256(self.password.encode()).hexdigest():
                logger.debug(f"[AUTH] ✅ User {user_id} is authorized")
                return True
            else:
                logger.info(f"[AUTH] 🔁 User {user_id} needs re-auth (password changed)")
                del self.authorized[user_id]
        return False
    
    def get_failed_attempts(self, user_id: int) -> int:
        """Возвращает количество неудачных попыток"""
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        """Сбрасывает счётчик неудачных попыток"""
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
            logger.info(f"[AUTH] 🔄 Reset failed attempts for user {user_id}")
    
    def list_authorized(self) -> List[Dict]:
        """Возвращает список авторизованных пользователей"""
        return [
            {'user_id': uid, 'auth_time': data['auth_time']}
            for uid, data in self.authorized.items()
        ]


# ===================================================================
# 🗄 STATE MODULE (сессии, черновики)
# ===================================================================
class StateManager:
    """Управление сессиями пользователей и черновиками"""
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}  # user_id -> session_data
        self.drafts: Dict[int, Dict] = {}  # user_id -> draft_post
        logger.info("[STATE] 🗄 StateManager initialized")
    
    def get_session(self, user_id: int) -> Dict:
        """Получает или создаёт сессию пользователя"""
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
            logger.debug(f"[STATE] 🆕 Created session for user {user_id}")
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Dict = None):
        """Устанавливает шаг в сессии"""
        session = self.get_session(user_id)
        session['step'] = step
        if data:
            session['data'].update(data)
        logger.info(f"[STATE] 📍 User {user_id} → step={step} | data_keys={list(session['data'].keys()) if session['data'] else 'empty'}")
    
    def get_step(self, user_id: int) -> Optional[str]:
        """Возвращает текущий шаг пользователя"""
        return self.sessions.get(user_id, {}).get('step')
    
    def get_session_data(self, user_id: int) -> Dict:
        """Возвращает данные сессии"""
        return self.sessions.get(user_id, {}).get('data', {})
    
    def clear_session(self, user_id: int):
        """Очищает сессию пользователя"""
        if user_id in self.sessions:
            logger.info(f"[STATE] 🧹 Cleared session for user {user_id}")
            del self.sessions[user_id]
    
    def save_draft(self, user_id: int, draft: Dict):
        """Сохраняет черновик поста"""
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
        logger.info(f"[STATE] 💾 Draft saved for user {user_id} | keys={list(draft.keys())}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        """Получает черновик пользователя"""
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        """Удаляет черновик"""
        if user_id in self.drafts:
            logger.info(f"[STATE] 🗑️ Draft cleared for user {user_id}")
            del self.drafts[user_id]


# ===================================================================
# 📡 MAX API CLIENT (с максимальным логированием)
# ===================================================================
class MAXClient:
    """Обёртка над MAX API с детальным логированием"""
    
    def __init__(self, token: str, base_url: str, timeout: int = 60):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        self.error_count = 0
        logger.info(f"[MAX] 📡 MAXClient initialized | base_url={base_url} | timeout={timeout}s")
    
    async def init(self):
        """Инициализирует HTTP-сессию"""
        if not self.session:
            self.session = ClientSession(timeout=self.timeout)
            logger.info("[MAX] 🔗 HTTP session created")
    
    async def close(self):
        """Закрывает сессию"""
        if self.session:
            await self.session.close()
            logger.info("[MAX] 🔌 HTTP session closed")
    
    async def _request(self, method: str, endpoint: str, data: Dict = None, 
                       params: Dict = None, files: Dict = None, 
                       max_retries: int = 3) -> Dict:
        """Универсальный запрос с логированием и повторами"""
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/1.0"
        }
        
        # Если есть файлы — убираем Content-Type, aiohttp поставит multipart
        if files:
            headers.pop("Content-Type", None)
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.debug(f"[MAX] Headers: { {k: ('***' if 'Auth' in k else v) for k, v in headers.items()} }")
        if data:
            logger.debug(f"[MAX] Body: {json.dumps(data, ensure_ascii=False)[:500]}")
        if params:
            logger.debug(f"[MAX] Params: {params}")
        if files:
            logger.debug(f"[MAX] Files: {list(files.keys())}")
        
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                if files:
                    # Загрузка с файлами (multipart)
                    form = FormData()
                    if data:
                        for key, value in data.items():
                            form.add_field(key, json.dumps(value) if isinstance(value, (dict, list)) else str(value))
                    for key, file_data in files.items():
                        form.add_field(key, file_data['data'], filename=file_data.get('filename', 'file'))
                    
                    async with self.session.request(
                        method=method, url=url, headers=headers,
                        params=params, data=form, timeout=self.timeout
                    ) as response:
                        return await self._handle_response(response, start_time, attempt)
                else:
                    # Обычный JSON-запрос
                    async with self.session.request(
                        method=method, url=url, headers=headers,
                        params=params, json=data, timeout=self.timeout
                    ) as response:
                        return await self._handle_response(response, start_time, attempt)
                        
            except asyncio.TimeoutError as e:
                elapsed = time.time() - start_time
                logger.warning(f"[MAX] ⏱ Timeout after {elapsed:.2f}s (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "timeout", "detail": str(e)}
                
            except ClientError as e:
                elapsed = time.time() - start_time
                logger.error(f"[MAX] 🌐 ClientError after {elapsed:.2f}s: {e}")
                self.error_count += 1
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "client_error", "detail": str(e)}
                
            except Exception as e:
                elapsed = time.time() - start_time
                logger.exception(f"[MAX] 💥 Unexpected error after {elapsed:.2f}s: {e}")
                self.error_count += 1
                return {"error": "exception", "detail": str(e)}
        
        return {"error": "max_retries_exceeded"}
    
    async def _handle_response(self, response, start_time: float, attempt: int) -> Dict:
        """Обрабатывает ответ от API"""
        elapsed = time.time() - start_time
        text = await response.text()
        
        logger.info(f"[MAX] ← #{attempt+1} {response.status} in {elapsed:.2f}s | {text[:300]}")
        
        # Rate limit
        if response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 30))
            logger.warning(f"[MAX] ⏳ Rate limit, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            return {"error": "rate_limited", "retry_after": retry_after}
        
        # Auth error
        if response.status == 401:
            logger.error(f"[MAX] 🔐 Auth failed (401): {text[:200]}")
            return {"error": "auth_failed", "detail": text}
        
        # Success
        if response.status == 200:
            try:
                result = json.loads(text) if text.strip() else {}
                logger.debug(f"[MAX] ✅ Parsed JSON response | keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"[MAX] ⚠️ Response is not JSON: {text[:200]}")
                return {"raw": text}
        
        # Other errors
        logger.warning(f"[MAX] ❌ HTTP {response.status}: {text[:300]}")
        return {"error": f"HTTP_{response.status}", "detail": text, "status": response.status}
    
    # === API методы ===
    
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          buttons: List[Dict] = None, markup: List[Dict] = None,
                          attachments: List[Dict] = None) -> Dict:
        """Отправляет сообщение пользователю или в канал"""
        logger.info(f"[MAX] 📤 send_message(chat_id={chat_id}, text_len={len(text)}, buttons={len(buttons) if buttons else 0})")
        
        payload = {"text": text}
        if buttons:
            payload["buttons"] = buttons
            logger.debug(f"[MAX] Buttons: {buttons}")
        if markup:
            payload["markup"] = markup
            logger.debug(f"[MAX] Markup: {len(markup)} entities")
        if attachments:
            payload["attachments"] = attachments
        
        # 🔥 Рабочий формат: параметр в URL
        endpoint = f"/messages?chat_id={chat_id}"
        return await self._request("POST", endpoint, data=payload)
    
    async def edit_message(self, message_id: str, text: str = None,
                          buttons: List[Dict] = None) -> Dict:
        """Редактирует опубликованное сообщение"""
        logger.info(f"[MAX] ✏️ edit_message(message_id={message_id})")
        
        payload = {}
        if text is not None:
            payload["text"] = text
        if buttons is not None:
            payload["buttons"] = buttons
        
        endpoint = f"/messages/{message_id}"
        return await self._request("PUT", endpoint, data=payload)
    
    async def get_message_stats(self, message_id: str) -> Dict:
        """Получает статистику по сообщению"""
        logger.info(f"[MAX] 📊 get_message_stats(message_id={message_id})")
        endpoint = f"/messages/{message_id}/stats"
        return await self._request("GET", endpoint)
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        """Регистрирует вебхук"""
        logger.info(f"[MAX] 🔗 register_webhook(url={webhook_url}, chat_id={chat_id})")
        
        body = {
            "url": webhook_url,
            "chat_id": chat_id,
            "update_types": ["message_created", "message_updated", "message_deleted"]
        }
        
        result = await self._request("POST", "/subscriptions", data=body)
        success = "error" not in result
        logger.info(f"[MAX] {'✅' if success else '❌'} Webhook registration: {result}")
        return success
    
    async def upload_media(self, file_data: bytes, filename: str, 
                          media_type: str = 'photo') -> Dict:
        """Загружает медиафайл и возвращает ID"""
        logger.info(f"[MAX] 📤 upload_media(filename={filename}, type={media_type}, size={len(file_data)}B)")
        
        endpoint = "/media/upload"
        files = {
            'file': {
                'data': file_data,
                'filename': filename
            }
        }
        data = {'type': media_type}
        
        return await self._request("POST", endpoint, data=data, files=files)


# ===================================================================
# 🖼 MEDIA MANAGER
# ===================================================================
class MediaManager:
    """Управление медиафайлами: скачивание, кэширование, загрузка"""
    
    SUPPORTED_TYPES = {'photo', 'video', 'audio', 'document'}
    
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        self.media_cache: Dict[str, Dict] = {}  # file_hash -> metadata
        logger.info(f"[MEDIA] 🖼 MediaManager initialized | cache_dir={cache_dir} | max_items={max_items}")
    
    def _generate_hash(self, data: bytes) -> str:
        """Генерирует хэш файла"""
        return hashlib.sha256(data).hexdigest()[:16]
    
    async def download_and_cache(self, url: str, filename: str = None) -> Optional[Dict]:
        """Скачивает файл по URL и кэширует его"""
        logger.info(f"[MEDIA] 📥 download_and_cache(url={url[:100]}..., filename={filename})")
        
        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        logger.error(f"[MEDIA] ❌ HTTP {response.status} downloading {url}")
                        return None
                    
                    data = await response.read()
                    file_hash = self._generate_hash(data)
                    
                    # Определяем тип
                    content_type = response.headers.get('Content-Type', '')
                    media_type = 'photo' if 'image' in content_type else 'video' if 'video' in content_type else 'document'
                    
                    # Сохраняем в кэш
                    cache_path = self.cache_dir / f"{file_hash}.bin"
                    cache_path.write_bytes(data)
                    
                    metadata = {
                        'hash': file_hash,
                        'filename': filename or f"file_{file_hash}",
                        'size': len(data),
                        'type': media_type,
                        'cached_at': datetime.now().isoformat(),
                        'cache_path': str(cache_path)
                    }
                    
                    self.media_cache[file_hash] = metadata
                    logger.info(f"[MEDIA] ✅ Cached {filename} | hash={file_hash} | size={len(data)/1024:.1f}KB | type={media_type}")
                    
                    return metadata
                    
        except Exception as e:
            logger.exception(f"[MEDIA] ❌ Failed to download {url}: {e}")
            return None
    
    def get_cached_file(self, file_hash: str) -> Optional[bytes]:
        """Возвращает данные файла из кэша"""
        if file_hash in self.media_cache:
            cache_path = Path(self.media_cache[file_hash]['cache_path'])
            if cache_path.exists():
                logger.debug(f"[MEDIA] 📦 Serving cached file {file_hash}")
                return cache_path.read_bytes()
        return None
    
    def cleanup_old_cache(self, max_age_hours: int = 24):
        """Удаляет старые файлы из кэша"""
        logger.info(f"[MEDIA] 🧹 Cleaning cache older than {max_age_hours}h")
        now = datetime.now()
        removed = 0
        
        for file_hash, meta in list(self.media_cache.items()):
            cached_at = datetime.fromisoformat(meta['cached_at'])
            age = now - cached_at
            if age > timedelta(hours=max_age_hours):
                cache_path = Path(meta['cache_path'])
                if cache_path.exists():
                    cache_path.unlink()
                    logger.debug(f"[MEDIA] 🗑️ Removed {cache_path.name} (age={age})")
                del self.media_cache[file_hash]
                removed += 1
        
        logger.info(f"[MEDIA] 🧹 Cleanup done: {removed} files removed")
        return removed
    
    def parse_collage_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Парсит вложения коллажа из сообщения MAX"""
        logger.info(f"[MEDIA] 🔍 parse_collage_attachments(count={len(attachments)})")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            
            payload = att.get('payload', {})
            url = payload.get('url') or att.get('url')
            if not url:
                logger.warning(f"[MEDIA] ⚠️ Attachment #{i} has no URL")
                continue
            
            media_type = att.get('type', 'photo')
            if media_type not in self.SUPPORTED_TYPES:
                logger.warning(f"[MEDIA] ⚠️ Unsupported type: {media_type}")
                continue
            
            result.append({
                'url': url,
                'type': media_type,
                'filename': payload.get('filename') or f"media_{i}",
                'index': i
            })
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} valid media items")
        return result


# ===================================================================
# ⏰ SCHEDULER (отложенная публикация)
# ===================================================================
class PublishScheduler:
    """Планировщик отложенных публикаций"""
    
    def __init__(self, max_client: MAXClient, channel_id: str):
        self.max_client = max_client
        self.channel_id = channel_id
        self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        self.scheduled_posts: Dict[str, Dict] = {}  # job_id -> post_data
        logger.info(f"[SCHEDULER] ⏰ PublishScheduler initialized | timezone={SCHEDULER_TIMEZONE}")
    
    def start(self):
        """Запускает планировщик"""
        self.scheduler.start()
        logger.info("[SCHEDULER] 🚀 Scheduler started")
    
    def stop(self):
        """Останавливает планировщик"""
        self.scheduler.shutdown()
        logger.info("[SCHEDULER] 🛑 Scheduler stopped")
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        """Парсит строку времени в datetime"""
        formats = [
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id: int, post_data: Dict, publish_at: str) -> Optional[str]:
        """Планирует публикацию поста"""
        logger.info(f"[SCHEDULER] 📅 schedule_post(user_id={user_id}, publish_at={publish_at})")
        
        publish_time = self.parse_datetime(publish_at)
        if not publish_time:
            logger.error(f"[SCHEDULER] ❌ Invalid datetime format: {publish_at}")
            return None
        
        if publish_time <= datetime.now():
            logger.warning(f"[SCHEDULER] ⚠️ Publish time is in the past: {publish_time}")
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def publish_job():
            logger.info(f"[SCHEDULER] 🎯 Executing scheduled post {job_id}")
            try:
                result = await self.max_client.send_message(
                    chat_id=self.channel_id,
                    text=post_data.get('text', ''),
                    buttons=post_data.get('buttons'),
                    markup=post_data.get('markup'),
                    attachments=post_data.get('attachments')
                )
                if "error" not in result:
                    logger.info(f"[SCHEDULER] ✅ Scheduled post {job_id} published successfully")
                    # TODO: сохранить ID сообщения для статистики
                else:
                    logger.error(f"[SCHEDULER] ❌ Failed to publish scheduled post {job_id}: {result}")
            except Exception as e:
                logger.exception(f"[SCHEDULER] 💥 Error in scheduled post {job_id}: {e}")
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(publish_job, trigger=trigger, id=job_id, replace_existing=True)
        self.scheduled_posts[job_id] = {
            'user_id': user_id,
            'post_data': post_data,
            'publish_at': publish_at,
            'scheduled_at': datetime.now().isoformat()
        }
        
        logger.info(f"[SCHEDULER] ✅ Post scheduled: job_id={job_id} | publish_at={publish_time}")
        return job_id
    
    def list_scheduled(self, user_id: int = None) -> List[Dict]:
        """Возвращает список запланированных постов"""
        result = []
        for job_id, data in self.scheduled_posts.items():
            if user_id is None or data['user_id'] == user_id:
                result.append({
                    'job_id': job_id,
                    'publish_at': data['publish_at'],
                    'text_preview': data['post_data'].get('text', '')[:50]
                })
        logger.debug(f"[SCHEDULER] 📋 list_scheduled: {len(result)} items")
        return result
    
    def cancel_scheduled(self, job_id: str) -> bool:
        """Отменяет запланированную публикацию"""
        if job_id in self.scheduled_posts:
            try:
                self.scheduler.remove_job(job_id)
                del self.scheduled_posts[job_id]
                logger.info(f"[SCHEDULER] 🗑️ Cancelled scheduled post {job_id}")
                return True
            except Exception as e:
                logger.error(f"[SCHEDULER] ❌ Failed to cancel {job_id}: {e}")
        return False


# ===================================================================
# 📊 STATS MODULE
# ===================================================================
class StatsCollector:
    """Сбор и хранение статистики"""
    
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}  # message_id -> stats
        self.clicks: Dict[str, Dict[int, int]] = {}  # message_id -> {button_index: count}
        self._load_from_file()
        logger.info(f"[STATS] 📊 StatsCollector initialized | file={stats_file}")
    
    def _load_from_file(self):
        """Загружает статистику из файла"""
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.stats = data.get('messages', {})
                    self.clicks = {k: {int(kk): vv for kk, vv in v.items()} for k, v in data.get('clicks', {}).items()}
                logger.info(f"[STATS] 📥 Loaded stats: {len(self.stats)} messages, {sum(len(c) for c in self.clicks.values())} button click records")
            except Exception as e:
                logger.error(f"[STATS] ❌ Failed to load stats file: {e}")
    
    def _save_to_file(self):
        """Сохраняет статистику в файл"""
        try:
            data = {
                'messages': self.stats,
                'clicks': {k: {str(kk): vv for kk, vv in v.items()} for k, v in self.clicks.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"[STATS] 💾 Saved stats to {self.stats_file}")
        except Exception as e:
            logger.warning(f"[STATS] ⚠️ Failed to save stats: {e}")
    
    def record_message(self, message_id: str, chat_id: str, text: str, published_at: str):
        """Записывает информацию о новом сообщении"""
        self.stats[message_id] = {
            'chat_id': chat_id,
            'text_preview': text[:100],
            'published_at': published_at,
            'views': 0,
            'first_view_at': None,
            'last_view_at': None
        }
        self.clicks[message_id] = {}
        self._save_to_file()
        logger.info(f"[STATS] 📝 Recorded new message {message_id}")
    
    def update_views(self, message_id: str, views: int):
        """Обновляет счётчик просмотров"""
        if message_id in self.stats:
            old_views = self.stats[message_id]['views']
            self.stats[message_id]['views'] = views
            now = datetime.now().isoformat()
            if views > old_views:
                if not self.stats[message_id]['first_view_at']:
                    self.stats[message_id]['first_view_at'] = now
                self.stats[message_id]['last_view_at'] = now
            self._save_to_file()
            logger.debug(f"[STATS] 👁 Message {message_id}: views {old_views} → {views}")
    
    def record_click(self, message_id: str, button_index: int, user_id: int):
        """Записывает клик по кнопке"""
        if message_id not in self.clicks:
            self.clicks[message_id] = {}
        if button_index not in self.clicks[message_id]:
            self.clicks[message_id][button_index] = 0
        self.clicks[message_id][button_index] += 1
        self._save_to_file()
        logger.info(f"[STATS] 🖱 Click recorded: message={message_id} button={button_index} user={user_id}")
    
    def get_stats(self, message_id: str = None) -> Union[Dict, List[Dict]]:
        """Возвращает статистику"""
        if message_id:
            result = self.stats.get(message_id, {}).copy()
            if message_id in self.clicks:
                result['button_clicks'] = self.clicks[message_id]
            logger.debug(f"[STATS] 📊 get_stats({message_id}): {result}")
            return result
        else:
            result = []
            for mid, data in self.stats.items():
                item = data.copy()
                item['message_id'] = mid
                if mid in self.clicks:
                    item['button_clicks'] = self.clicks[mid]
                result.append(item)
            logger.debug(f"[STATS] 📋 get_stats(all): {len(result)} items")
            return result


# ===================================================================
# 🎨 FORMATTER (прозрачная передача разметки)
# ===================================================================
class TextFormatter:
    """Прозрачная передача форматирования из MAX"""
    
    @staticmethod
    def parse_buttons(text: str) -> List[Dict]:
        """Парсит кнопки из формата 'Текст | ссылка' (каждая с новой строки)"""
        logger.info(f"[FORMAT] 🔘 parse_buttons: input_lines={text.count(chr(10)) + 1}")
        
        buttons = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for i, line in enumerate(lines):
            if '|' in line:
                parts = line.split('|', 1)
                btn_text = parts[0].strip()
                btn_url = parts[1].strip()
                
                if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max.ru/')):
                    buttons.append({
                        'text': btn_text,
                        'url': btn_url,
                        'index': i
                    })
                    logger.debug(f"[FORMAT] ✅ Button #{i}: '{btn_text}' → {btn_url}")
                else:
                    logger.warning(f"[FORMAT] ⚠️ Invalid button format: '{line}'")
            else:
                logger.debug(f"[FORMAT] ⏭ Skipped line (no '|'): '{line[:50]}'")
        
        logger.info(f"[FORMAT] ✅ Parsed {len(buttons)} valid buttons")
        return buttons
    
    @staticmethod
    def pass_through_markup(original_markup: List[Dict]) -> List[Dict]:
        """Прозрачно передаёт markup из MAX без изменений"""
        logger.info(f"[FORMAT] 🎨 pass_through_markup: {len(original_markup)} entities")
        # MAX уже присылает готовый markup — просто возвращаем его
        return original_markup if original_markup else []


# ===================================================================
# 🎮 HANDLERS (обработчики команд)
# ===================================================================
class CommandHandlers:
    """Обработчики команд бота"""
    
    def __init__(self, auth: AuthManager, state: StateManager, 
                 max_client: MAXClient, media_mgr: MediaManager,
                 scheduler: PublishScheduler, stats: StatsCollector,
                 channel_id: str):
        self.auth = auth
        self.state = state
        self.max_client = max_client
        self.media_mgr = media_mgr
        self.scheduler = scheduler
        self.stats = stats
        self.channel_id = channel_id
        logger.info("[HANDLERS] 🎮 CommandHandlers initialized")
    
    async def handle_start(self, user_id: int, send_callback):
        """Обработка /start"""
        logger.info(f"[CMD] 🚀 handle_start(user_id={user_id})")
        
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль для доступа к боту:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "callback_data": "new_post"}],
                [{"text": "📋 Мои черновики", "callback_data": "drafts"}],
                [{"text": "📊 Статистика", "callback_data": "stats"}],
                [{"text": "⚙️ Настройки", "callback_data": "settings"}]
            ]
        }
        
        await send_callback(
            "👋 **MAX Channel Poster**\n\n"
            "Бот для публикации постов в канал.\n\n"
            "Доступные команды:\n"
            "/post — создать новый пост\n"
            "/preview — предпросмотр черновика\n"
            "/publish — опубликовать черновик\n"
            "/stats — показать статистику",
            keyboard
        )
        logger.info(f"[CMD] ✅ Sent start menu to user {user_id}")
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        """Обработка ввода пароля"""
        logger.info(f"[CMD] 🔐 handle_password(user_id={user_id})")
        
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            await self.handle_start(user_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много неудачных попыток. Попробуйте позже.")
                logger.warning(f"[CMD] 🔒 User {user_id} blocked after failed attempts")
    
    async def handle_post_command(self, user_id: int, send_callback):
        """Начало создания поста: /post"""
        logger.info(f"[CMD] ✍️ handle_post_command(user_id={user_id})")
        
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала авторизуйтесь командой /start")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        await send_callback(
            "📝 **Создание поста**\n\n"
            "Отправьте текст поста.\n\n"
            "💡 Поддерживается форматирование:\n"
            "• Выделите текст в интерфейсе MAX для жирного/курсива/ссылок\n"
            "• Эмодзи работают автоматически ✨\n\n"
            "После текста отправьте кнопки в формате (каждая с новой строки):\n"
            "```\n"
            "Текст кнопки | https://ссылка\n"
            "Ещё кнопка | https://другая-ссылка\n"
            "```\n"
            "Или напишите «пропустить» для поста без кнопок."
        )
    
    async def handle_post_text(self, user_id: int, text: str, markup: List, send_callback):
        """Обработка текста поста"""
        logger.info(f"[CMD] 📝 handle_post_text(user_id={user_id}, text_len={len(text)}, markup={len(markup)})")
        
        session = self.state.get_session_data(user_id)
        session['text'] = text
        session['markup'] = TextFormatter.pass_through_markup(markup)
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback(
            "🔘 **Добавьте кнопки**\n\n"
            "Формат (каждая кнопка с новой строки):\n"
            "```\n"
            "Текст кнопки | https://ссылка\n"
            "```\n"
            "Или напишите «пропустить» для поста без кнопок."
        )
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        """Обработка кнопок поста"""
        logger.info(f"[CMD] 🔘 handle_post_buttons(user_id={user_id})")
        
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            session['buttons'] = []
            logger.info(f"[CMD] ⏭ User skipped buttons")
        else:
            session['buttons'] = TextFormatter.parse_buttons(buttons_text)
            if not session['buttons'] and buttons_text.strip():
                await send_callback("❌ Не удалось распознать кнопки. Проверьте формат: `Текст | ссылка`")
                return
        
        # Сохраняем черновик
        self.state.save_draft(user_id, session.copy())
        
        # Предлагаем предпросмотр
        keyboard = {
            "inline_keyboard": [
                [{"text": "👁 Предпросмотр", "callback_data": "preview"}],
                [{"text": "✅ Опубликовать", "callback_data": "publish_now"}],
                [{"text": "⏰ Отложить", "callback_data": "schedule"}]
            ]
        }
        
        preview_text = session['text'][:200] + ('...' if len(session['text']) > 200 else '')
        btn_count = len(session['buttons'])
        
        await send_callback(
            f"📋 **Черновик готов**\n\n"
            f"📝 Текст: {preview_text}\n"
            f"🔘 Кнопок: {btn_count}\n\n"
            f"Что делаем дальше?",
            keyboard
        )
    
    async def handle_preview(self, user_id: int, send_callback):
        """Предпросмотр черновика"""
        logger.info(f"[CMD] 👁 handle_preview(user_id={user_id})")
        
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден. Создайте пост через /post")
            return
        
        # Отправляем предпросмотр как обычное сообщение
        await send_callback(
            f"👁 **Предпросмотр**\n\n{draft['text']}",
            {"inline_keyboard": [[{"text": btn['text'], "url": btn['url']} for btn in draft['buttons']]]} if draft['buttons'] else None,
            markup=draft.get('markup')
        )
        
        # Возвращаем меню
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Опубликовать", "callback_data": "publish_now"}],
                [{"text": "⏰ Отложить", "callback_data": "schedule"}],
                [{"text": "✏️ Редактировать", "callback_data": "edit_draft"}]
            ]
        }
        await send_callback("Выберите действие:", keyboard)
    
    async def handle_publish(self, user_id: int, send_callback, immediate: bool = True):
        """Публикация поста"""
        logger.info(f"[CMD] 🚀 handle_publish(user_id={user_id}, immediate={immediate})")
        
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден")
            return
        
        if immediate:
            # Немедленная публикация
            await send_callback("⏳ Публикую...")
            
            result = await self.max_client.send_message(
                chat_id=self.channel_id,
                text=draft['text'],
                buttons=draft['buttons'],
                markup=draft.get('markup'),
                attachments=draft.get('attachments')
            )
            
            if "error" not in result:
                message_id = result.get('message', {}).get('mid')
                if message_id:
                    self.stats.record_message(message_id, self.channel_id, draft['text'], datetime.now().isoformat())
                
                self.state.clear_draft(user_id)
                await send_callback("✅ **Пост опубликован!** 🎉")
                logger.info(f"[CMD] ✅ Post published by user {user_id}")
            else:
                await send_callback(f"❌ Ошибка публикации: {result.get('detail', 'неизвестная')}")
                logger.error(f"[CMD] ❌ Publish failed: {result}")
        else:
            # Отложенная публикация — ждём ввод времени
            self.state.set_step(user_id, 'waiting_schedule_time')
            await send_callback(
                "⏰ **Отложенная публикация**\n\n"
                "Введите дату и время в формате:\n"
                "```\n"
                "ГГГГ-ММ-ДД ЧЧ:ММ\n"
                "```\n"
                "Пример: `2024-06-15 14:30`"
            )
    
    async def handle_schedule_time(self, user_id: int, time_str: str, send_callback):
        """Обработка времени отложенной публикации"""
        logger.info(f"[CMD] ⏰ handle_schedule_time(user_id={user_id}, time={time_str})")
        
        draft = self.state.get_draft(user_id)
        if not draft:
            await send_callback("❌ Черновик не найден")
            return
        
        job_id = self.scheduler.schedule_post(user_id, draft, time_str)
        
        if job_id:
            self.state.clear_draft(user_id)
            await send_callback(f"✅ **Пост запланирован** на {time_str}\n\nID задания: `{job_id}`")
            logger.info(f"[CMD] ✅ Post scheduled: job_id={job_id}")
        else:
            await send_callback("❌ Не удалось запланировать. Проверьте формат даты.")
    
    async def handle_stats(self, user_id: int, send_callback):
        """Показ статистики"""
        logger.info(f"[CMD] 📊 handle_stats(user_id={user_id})")
        
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пока пуста")
            return
        
        # Формируем отчёт
        report = ["📊 **Статистика публикаций**\n"]
        for item in all_stats[-10:]:  # Последние 10
            report.append(f"• `{item['message_id'][:12]}...`")
            report.append(f"  👁 {item['views']} просмотров")
            if item.get('button_clicks'):
                clicks = sum(item['button_clicks'].values())
                report.append(f"  🖱 {clicks} кликов по кнопкам")
            report.append("")
        
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id: int, send_callback):
        """Сервисное меню"""
        logger.info(f"[CMD] ⚙️ handle_settings(user_id={user_id})")
        
        keyboard = {
            "inline_keyboard": [
                [{"text": "📢 Сменить канал", "callback_data": "set_channel"}],
                [{"text": "🔑 Сменить пароль", "callback_data": "set_password"}],
                [{"text": "👥 Админы", "callback_data": "list_admins"}]
            ]
        }
        
        await send_callback(
            "⚙️ **Настройки**\n\n"
            "Здесь можно изменить параметры бота.\n\n"
            "⚠️ Изменения применяются сразу и затрагивают всех пользователей.",
            keyboard
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        """Смена канала публикации"""
        logger.info(f"[CMD] 📢 handle_set_channel(user_id={user_id}, new_channel={new_channel_id})")
        # В реальном коде здесь нужно обновить CHANNEL_ID в конфиге
        # Для демо просто подтверждаем
        await send_callback(f"✅ Канал изменён на: `{new_channel_id}`\n\n⚠️ Для применения перезапустите бота или обновите переменную MAX_CHANNEL_ID")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        """Смена пароля"""
        logger.info(f"[CMD] 🔑 handle_set_password(user_id={user_id})")
        # В реальном коде обновить BOT_PASSWORD в env
        await send_callback("✅ Пароль изменён.\n\n🔁 Все пользователи должны будут авторизоваться заново.")
        # Сбрасываем все сессии
        self.auth.authorized.clear()
        self.auth._save_to_file()


# ===================================================================
# 🌐 WEBHOOK HANDLER
# ===================================================================
async def webhook_handler(request, handlers: CommandHandlers, send_callback_factory):
    """Обработчик входящих вебхуков от MAX"""
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    logger.debug(f"[WEBHOOK] Headers: {dict(request.headers)}")
    
    if request.method != 'POST':
        logger.warning(f"[WEBHOOK] ❌ Invalid method: {request.method}")
        return web.Response(status=405)
    
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 Received update: {json.dumps(body, ensure_ascii=False)[:500]}")
        
        update_type = body.get('update_type', 'unknown')
        logger.info(f"[WEBHOOK] Type: {update_type}")
        
        if update_type == 'message_created' and (msg := body.get('message')):
            await handle_incoming_message(msg, handlers, send_callback_factory)
        else:
            logger.info(f"[WEBHOOK] ⏭ Skipping update type: {update_type}")
        
        return web.Response(status=200)
        
    except json.JSONDecodeError as e:
        logger.error(f"[WEBHOOK] ❌ Invalid JSON: {e} | body: {await request.text()[:200]}")
        return web.Response(status=400)
    except Exception as e:
        logger.exception(f"[WEBHOOK] 💥 Error: {e}")
        return web.Response(status=500)


async def handle_incoming_message(msg: Dict, handlers: CommandHandlers, send_callback_factory):
    """Обработка входящего сообщения от пользователя"""
    logger.info("=" * 80)
    logger.info(f"[MSG] 📨 Processing incoming message")
    logger.info(f"[MSG] Full structure: {json.dumps(msg, ensure_ascii=False, indent=2)[:1500]}")
    
    # Извлекаем ID пользователя
    recipient = msg.get('recipient', {})
    user_id = recipient.get('user_id') or recipient.get('chat_id') or recipient.get('id')
    
    if not user_id:
        logger.error(f"[MSG] ❌ Could not extract user_id from recipient: {recipient}")
        return
    
    logger.info(f"[MSG] 👤 user_id={user_id}")
    
    # Создаём колбэк для отправки ответа
    async def send_callback(text: str, keyboard: Dict = None, markup: List = None):
        logger.info(f"[SEND] 📤 Sending to user {user_id}: text_len={len(text)}, buttons={len(keyboard['inline_keyboard']) if keyboard else 0}")
        result = await handlers.max_client.send_message(
            chat_id=user_id,
            text=text,
            buttons=keyboard['inline_keyboard'] if keyboard and 'inline_keyboard' in keyboard else None,
            markup=markup
        )
        logger.info(f"[SEND] ← Result: {result}")
        return result
    
    # Извлекаем текст и markup
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    
    logger.info(f"[MSG] 💬 Text: '{text[:100]}{'...' if len(text) > 100 else ''}' | markup_count={len(markup)}")
    
    # Обработка по шагам сессии
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 User session step: {step}")
    
    if step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, send_callback)
    
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    
    elif step == 'waiting_schedule_time':
        await handlers.handle_schedule_time(user_id, text.strip(), send_callback)
    
    elif text == '/start':
        await handlers.handle_start(user_id, send_callback)
    
    elif text == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    
    elif text == '/stats':
        await handlers.handle_stats(user_id, send_callback)
    
    elif text == '/settings':
        await handlers.handle_settings(user_id, send_callback)
    
    else:
        # Неизвестная команда
        if handlers.auth.is_authorized(user_id):
            await send_callback("❓ Неизвестная команда. Доступные: /start, /post, /stats, /settings")
        else:
            await send_callback("🔐 Сначала авторизуйтесь: /start")
    
    logger.info("=" * 80)


# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    """Health check endpoint"""
    return web.json_response({
        'ok': True,
        'status': 'running',
        'timestamp': datetime.now().isoformat(),
        'version': '1.0.0-final'
    })

async def root_handler(request):
    """Root endpoint"""
    return web.json_response({
        'bot': 'MAX Channel Poster',
        'webhook': 'active',
        'endpoints': ['/health', '/webhook']
    })

async def on_startup(app):
    """Инициализация при старте"""
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER BOT")
    logger.info("🚀" * 40)
    
    # Инициализируем компоненты
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE)
    app['state'] = StateManager()
    app['max_client'] = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    app['media_mgr'] = MediaManager(MEDIA_CACHE_DIR, MAX_MEDIA_ITEMS)
    app['stats'] = StatsCollector(STATS_FILE)
    
    scheduler = PublishScheduler(app['max_client'], CHANNEL_ID)
    scheduler.start()
    app['scheduler'] = scheduler
    
    app['handlers'] = CommandHandlers(
        auth=app['auth'],
        state=app['state'],
        max_client=app['max_client'],
        media_mgr=app['media_mgr'],
        scheduler=scheduler,
        stats=app['stats'],
        channel_id=CHANNEL_ID
    )
    
    # Регистрируем вебхук
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        await app['max_client'].register_webhook(webhook_url, CHANNEL_ID)
    
    logger.info("✅ All components initialized")

async def on_cleanup(app):
    """Очистка при остановке"""
    logger.info("🔚 Shutting down...")
    
    # Останавливаем планировщик
    if 'scheduler' in app:
        app['scheduler'].stop()
    
    # Закрываем HTTP-сессию
    if 'max_client' in app:
        await app['max_client'].close()
    
    # Очищаем кэш медиа
    if 'media_mgr' in app:
        app['media_mgr'].cleanup_old_cache(0)  # Удаляем всё при выходе
    
    logger.info("🔚 Cleanup complete")


def create_app():
    """Фабрика приложения"""
    app = web.Application()
    
    # Маршруты
    app.add_routes([
        web.get('/', root_handler),
        web.get('/health', health_check),
        web.post('/webhook', lambda req: webhook_handler(
            req, 
            app['handlers'], 
            lambda text, keyboard=None, markup=None: None  # Заглушка, реальная передаётся в handle_incoming_message
        )),
    ])
    
    # Хуки жизненного цикла
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app


# ===================================================================
# 🚀 ENTRY POINT
# ===================================================================
if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Starting server on port {port}")
    logger.info(f"🔗 Webhook URL: {RENDER_EXTERNAL_URL}/webhook" if RENDER_EXTERNAL_URL else "⚠️ RENDER_EXTERNAL_URL not set")
    
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None, print=logger.info)
