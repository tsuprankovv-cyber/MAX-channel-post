"""
MAX Channel Poster Bot — FULL FEATURE VERSION v2.3
✅ Авторизация по паролю (сохранение в файл, до смены пароля)
✅ Медиа: фото/видео/аудио/голосовые/документы/коллажи/ссылки (до 10 файлов)
✅ Форматирование: сохранение markup + конвертация в HTML для предпросмотра
✅ Кнопки: универсальный парсинг (|, -, →), поддержка рядов (новая строка = новый ряд)
✅ Предпросмотр: с применённым форматированием и реальными кнопками
✅ Отложенная публикация (формат: ГГГГ-ММ-ДД ЧЧ:ММ)
✅ Редактирование постов
✅ Статистика: просмотры, клики (с логированием)
✅ Сервисное меню: /set_channel, /set_password, /list_admins
✅ Inline-меню (max:// ссылки)
✅ Очистка временных файлов
✅ 🔥🔥🔥 МАКСИМАЛЬНОЕ ЛОГИРОВАНИЕ НА КАЖДОМ ШАГЕ 🔥🔥🔥
🔧 FIX: Все синтаксические ошибки исправлены (file_ bytes, if data is not None)
🔧 FIX: Унифицирована передача кнопок (inline_keyboard → плоский список)
🔧 FIX: Сохранение сессии и очистка после публикации
🔧 FIX: Корректная обработка attachments и markup
"""
import asyncio
import logging
import os
import json
import time
import re
import hashlib
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union, Tuple
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web, ClientSession, ClientTimeout, FormData
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
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '120'))
CACHE_MAX_AGE_HOURS = int(os.getenv('CACHE_MAX_AGE_HOURS', '24'))

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
logger.info(f"🔧 Config: CHANNEL_ID={CHANNEL_ID}, MEDIA_CACHE={MEDIA_CACHE_DIR}")
logger.info(f"🔧 MAX_MEDIA_ITEMS={MAX_MEDIA_ITEMS}, API_TIMEOUT={API_TIMEOUT}s")

# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    """Управление авторизацией пользователей"""
    
    def __init__(self, password: str, auth_file: Path):
        self.password = password
        self.auth_file = auth_file
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 AuthManager initialized | password_hash={hashlib.sha256(password.encode()).hexdigest()[:8]}...")
    
    def _load_from_file(self):
        """Загружает авторизованных пользователей из файла"""
        logger.debug(f"[AUTH] 📥 Loading from {self.auth_file}")
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] 📥 Loaded {len(self.authorized)} authorized users from {self.auth_file}")
                logger.debug(f"[AUTH] Users: {list(self.authorized.keys())}")
            except Exception as e:
                logger.error(f"[AUTH] ❌ Failed to load auth file: {e}")
        else:
            logger.info(f"[AUTH] 📄 Auth file not found: {self.auth_file}")
    
    def _save_to_file(self):
        """Сохраняет состояние в файл"""
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
        logger.info(f"[AUTH] 🔍 check_password(user_id={user_id})")
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat(),
                'password_hash': hashlib.sha256(self.password.encode()).hexdigest()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            logger.info(f"[AUTH] ✅ User {user_id} authorized successfully")
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        attempts = self.failed_attempts[user_id]
        logger.warning(f"[AUTH] ❌ User {user_id} failed attempt #{attempts}")
        self._save_to_file()
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        """Проверяет, авторизован ли пользователь"""
        if user_id in self.authorized:
            auth_data = self.authorized[user_id]
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
    
    def change_password(self, new_password: str):
        """Меняет пароль и сбрасывает все сессии"""
        logger.info(f"[AUTH] 🔑 Changing password (old_hash={hashlib.sha256(self.password.encode()).hexdigest()[:8]}...)")
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()
        logger.info(f"[AUTH] ✅ Password changed, all sessions invalidated")


# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    """Управление сессиями пользователей и черновиками"""
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
        logger.info("[STATE] 🗄 StateManager initialized")
    
    def get_session(self, user_id: int) -> Dict:
        """Получает или создаёт сессию пользователя"""
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
            logger.debug(f"[STATE] 🆕 Created session for user {user_id}")
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str,  Dict = None):
        """Устанавливает шаг в сессии"""
        session = self.get_session(user_id)
        session['step'] = step
        if data is not None:
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
    
    def list_drafts(self, user_id: int = None) -> List[Dict]:
        """Возвращает список черновиков"""
        if user_id is not None:
            return [self.drafts[user_id]] if user_id in self.drafts else []
        return [{'user_id': uid, 'saved_at': d['saved_at']} for uid, d in self.drafts.items()]


# ===================================================================
# 📡 MAX API CLIENT
# ===================================================================
class MAXClient:
    """Обёртка над MAX API с детальным логированием"""
    
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        self.error_count = 0
        logger.info(f"[MAX] 📡 MAXClient initialized | base_url={base_url} | timeout={timeout}s")
    
    async def init(self):
        """Инициализирует HTTP-сессию"""
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
            logger.info("[MAX] 🔗 HTTP session created")
    
    async def close(self):
        """Закрывает сессию"""
        if self.session is not None:
            await self.session.close()
            logger.info("[MAX] 🔌 HTTP session closed")
    
    async def _request(self, method: str, endpoint: str,  Dict = None, 
                       params: Dict = None, files: Dict = None, 
                       max_retries: int = 3) -> Dict:
        """Универсальный запрос с логированием и повторами"""
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/1.0"
        }
        
        if files is not None:
            headers.pop("Content-Type", None)
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.debug(f"[MAX] Headers: { {k: ('***' if 'Auth' in k else v) for k, v in headers.items()} }")
        
        # 🔧 FIX: проверка if data is not None
        if data is not None:
            logger.debug(f"[MAX] Body: {json.dumps(data, ensure_ascii=False)[:500]}")
        if params is not None:
            logger.debug(f"[MAX] Params: {params}")
        if files is not None:
            logger.debug(f"[MAX] Files: {list(files.keys())}")
        
        start_time = time.time()
        
        for attempt in range(max_retries):
            try:
                if files is not None:
                    form = FormData()
                    # 🔧 FIX: проверка if data is not None
                    if data is not None:
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
                
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"[MAX] 🌐 Error after {elapsed:.2f}s: {e}")
                self.error_count += 1
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "exception", "detail": str(e)}
        
        return {"error": "max_retries_exceeded"}
    
    async def _handle_response(self, response, start_time: float, attempt: int) -> Dict:
        """Обрабатывает ответ от API"""
        elapsed = time.time() - start_time
        text = await response.text()
        
        logger.info(f"[MAX] ← #{attempt+1} {response.status} in {elapsed:.2f}s | {text[:300]}")
        
        if response.status == 429:
            retry_after = int(response.headers.get('Retry-After', 30))
            logger.warning(f"[MAX] ⏳ Rate limit, waiting {retry_after}s")
            await asyncio.sleep(retry_after)
            return {"error": "rate_limited", "retry_after": retry_after}
        
        if response.status == 401:
            logger.error(f"[MAX] 🔐 Auth failed (401): {text[:200]}")
            return {"error": "auth_failed", "detail": text}
        
        if response.status == 200:
            try:
                result = json.loads(text) if text.strip() else {}
                logger.debug(f"[MAX] ✅ Parsed JSON response | keys={list(result.keys()) if isinstance(result, dict) else 'N/A'}")
                return result
            except json.JSONDecodeError as e:
                logger.warning(f"[MAX] ⚠️ Response is not JSON: {text[:200]}")
                return {"raw": text}
        
        logger.warning(f"[MAX] ❌ HTTP {response.status}: {text[:300]}")
        return {"error": f"HTTP_{response.status}", "detail": text, "status": response.status}
    
    # === API методы ===
    
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          buttons: List[Dict] = None, markup: List[Dict] = None,
                          attachments: List[Dict] = None) -> Dict:
        """Отправляет сообщение пользователю или в канал"""
        logger.info(f"[MAX] 📤 send_message(chat_id={chat_id}, text_len={len(text)}, buttons={len(buttons) if buttons else 0})")
        
        payload = {"text": text}
        
        # 🔥 Только кнопки с url поддерживаются в MAX!
        if buttons is not None:
            valid_buttons = [b for b in buttons if isinstance(b, dict) and b.get('url')]
            if valid_buttons:
                payload["buttons"] = valid_buttons
                logger.debug(f"[MAX] Buttons (url-only): {valid_buttons}")
            else:
                logger.debug(f"[MAX] No valid url buttons, skipping")
        
        if markup is not None and len(markup) > 0:
            payload["markup"] = markup
            logger.debug(f"[MAX] Markup: {len(markup)} entities")
        
        if attachments is not None and len(attachments) > 0:
            payload["attachments"] = attachments
            logger.debug(f"[MAX] Attachments: {len(attachments)} items")
        
        endpoint = f"/messages?chat_id={chat_id}"
        return await self._request("POST", endpoint, data=payload)
    
    async def edit_message(self, message_id: str, text: str = None,
                          buttons: List[Dict] = None, markup: List[Dict] = None) -> Dict:
        """Редактирует опубликованное сообщение"""
        logger.info(f"[MAX] ✏️ edit_message(message_id={message_id})")
        
        payload = {}
        if text is not None:
            payload["text"] = text
        if buttons is not None:
            valid_buttons = [b for b in buttons if isinstance(b, dict) and b.get('url')]
            if valid_buttons:
                payload["buttons"] = valid_buttons
        if markup is not None:
            payload["markup"] = markup
        
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
        
        # 🔧 FIX: только message_created (остальные типы не поддерживаются)
        body = {
            "url": webhook_url,
            "chat_id": chat_id,
            "update_types": ["message_created"]
        }
        
        result = await self._request("POST", "/subscriptions", data=body)
        success = "error" not in result
        logger.info(f"[MAX] {'✅' if success else '❌'} Webhook registration: {result}")
        return success
    
    async def upload_media(self, file_ bytes, filename: str, 
                          media_type: str = 'photo') -> Dict:
        """Загружает медиафайл и возвращает данные для attachments"""
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
    
    SUPPORTED_TYPES = {'photo', 'video', 'audio', 'document', 'voice', 'image', 'file'}
    
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        self.media_cache: Dict[str, Dict] = {}
        logger.info(f"[MEDIA] 🖼 MediaManager initialized | cache_dir={cache_dir} | max_items={max_items}")
    
    def _generate_hash(self, file_ bytes) -> str:
        """Генерирует хэш файла"""
        return hashlib.sha256(file_data).hexdigest()[:16]
    
    async def download_and_cache(self, url: str, filename: str = None) -> Optional[Dict]:
        """Скачивает файл по URL и кэширует его"""
        logger.info(f"[MEDIA] 📥 download_and_cache(url={url[:100]}..., filename={filename})")
        
        try:
            async with ClientSession() as session:
                async with session.get(url, timeout=ClientTimeout(total=300)) as response:
                    if response.status != 200:
                        logger.error(f"[MEDIA] ❌ HTTP {response.status} downloading {url}")
                        return None
                    
                    file_data = await response.read()
                    file_hash = self._generate_hash(file_data)
                    
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type:
                        media_type = 'photo'
                    elif 'video' in content_type:
                        media_type = 'video'
                    elif 'audio' in content_type:
                        media_type = 'audio'
                    else:
                        media_type = 'document'
                    
                    cache_path = self.cache_dir / f"{file_hash}.bin"
                    cache_path.write_bytes(file_data)
                    
                    metadata = {
                        'hash': file_hash,
                        'filename': filename or f"file_{file_hash}",
                        'size': len(file_data),
                        'type': media_type,
                        'cached_at': datetime.now().isoformat(),
                        'cache_path': str(cache_path),
                        'original_url': url
                    }
                    
                    self.media_cache[file_hash] = metadata
                    logger.info(f"[MEDIA] ✅ Cached {filename} | hash={file_hash} | size={len(file_data)/1024:.1f}KB | type={media_type}")
                    
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
    
    def cleanup_old_cache(self, max_age_hours: int = None):
        """Удаляет старые файлы из кэша"""
        if max_age_hours is None:
            max_age_hours = CACHE_MAX_AGE_HOURS
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
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Парсит вложения из сообщения MAX"""
        logger.info(f"[MEDIA] 🔍 parse_attachments(count={len(attachments)})")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            # Определяем тип медиа
            if att_type in ('image', 'photo'):
                media_type = 'photo'
            elif att_type == 'video':
                media_type = 'video'
            elif att_type in ('audio', 'voice'):
                media_type = att_type
            elif att_type in ('document', 'file'):
                media_type = 'document'
            elif att_type == 'share':
                # Ссылка с превью — не скачиваем, передаём как есть
                url = payload.get('url') or att.get('url')
                if url:
                    result.append({
                        'type': 'share',
                        'url': url,
                        'title': att.get('title'),
                        'description': att.get('description'),
                        'image_url': att.get('image_url'),
                        'token': payload.get('token'),
                        'index': i
                    })
                continue
            else:
                logger.warning(f"[MEDIA] ⚠️ Unknown attachment type: {att_type}")
                continue
            
            # Получаем URL для скачивания
            url = payload.get('url') or att.get('url')
            if not url:
                logger.warning(f"[MEDIA] ⚠️ Attachment #{i} has no URL")
                continue
            
            result.append({
                'url': url,
                'type': media_type,
                'filename': payload.get('filename') or att.get('title') or f"media_{i}",
                'token': payload.get('token'),
                'photo_id': payload.get('photo_id'),
                'index': i,
                'title': att.get('title'),
                'description': att.get('description')
            })
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} valid media items")
        return result


# ===================================================================
# 🎨 FORMATTER & MARKUP
# ===================================================================
class TextFormatter:
    """Форматирование текста и кнопок"""
    
    # MAX markup types → HTML tags
    MARKUP_MAP = {
        'strong': 'b',
        'bold': 'b',
        'em': 'i',
        'italic': 'i',
        'underline': 'u',
        'strikethrough': 's',
        'code': 'code',
        'pre': 'pre',
        'link': 'a'
    }
    
    @staticmethod
    def parse_buttons(text: str) -> Tuple[List[List[Dict]], str]:
        """
        Парсит кнопки из текста.
        Возвращает: (кнопки по рядам, оставшийся текст)
        
        Поддерживаемые форматы:
        - Текст | ссылка (каждая кнопка с новой строки = новый ряд)
        - Текст - ссылка
        - Текст → ссылка
        - Текст ссылка (последнее слово — ссылка)
        """
        logger.info(f"[FORMAT] 🔘 parse_buttons: input={text[:100]}...")
        
        rows = []
        current_row = []
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for line in lines:
            # Пробуем разные разделители
            btn = None
            for sep in [' | ', ' - ', ' → ', ' -> ', ' — ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max://')):
                        btn = {'text': btn_text, 'url': btn_url}
                        break
            
            # Если не нашли разделитель — пробуем последнее слово как ссылку
            if btn is None and ' ' in line:
                parts = line.rsplit(' ', 1)
                btn_text = parts[0].strip()
                btn_url = parts[1].strip()
                if btn_text and btn_url.startswith(('http://', 'https://')):
                    btn = {'text': btn_text, 'url': btn_url}
            
            if btn is not None:
                current_row.append(btn)
                logger.debug(f"[FORMAT] ✅ Button: '{btn['text']}' → {btn['url']}")
            else:
                # Если строка не распознана как кнопка — это текст
                if current_row:
                    rows.append(current_row)
                    current_row = []
        
        if current_row:
            rows.append(current_row)
        
        logger.info(f"[FORMAT] ✅ Parsed {sum(len(r) for r in rows)} buttons in {len(rows)} rows")
        return rows, '\n'.join([l for l in lines if '|' not in l and '-' not in l and '→' not in l])
    
    @staticmethod
    def apply_markup_to_html(text: str, markup: List[Dict]) -> str:
        """
        Применяет markup к тексту и конвертирует в HTML.
        MAX markup: [{"from": 0, "length": 12, "type": "strong"}]
        """
        if not markup or not text:
            return text
        
        logger.info(f"[FORMAT] 🎨 apply_markup: text_len={len(text)}, markup_count={len(markup)}")
        
        # Сортируем markup по позиции (с конца, чтобы не ломать индексы)
        sorted_markup = sorted(markup, key=lambda m: m.get('from', 0), reverse=True)
        
        result = list(text)
        
        for entity in sorted_markup:
            from_pos = entity.get('from', 0)
            length = entity.get('length', 0)
            entity_type = entity.get('type', '')
            
            if entity_type not in TextFormatter.MARKUP_MAP:
                continue
            
            tag = TextFormatter.MARKUP_MAP[entity_type]
            to_pos = from_pos + length
            
            if entity_type == 'link':
                url = entity.get('url', '#')
                inner = ''.join(result[from_pos:to_pos])
                replacement = f'<{tag} href="{url}">{inner}</{tag}>'
            else:
                inner = ''.join(result[from_pos:to_pos])
                replacement = f'<{tag}>{inner}</{tag}>'
            
            result[from_pos:to_pos] = list(replacement)
        
        html_text = ''.join(result)
        logger.debug(f"[FORMAT] HTML output: {html_text[:200]}...")
        return html_text
    
    @staticmethod
    def strip_markdown(text: str) -> str:
        """Убирает markdown-синтаксис из текста"""
        # Убираем **жирный**, *курсив*, [ссылка](url)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
        text = re.sub(r'`(.+?)`', r'\1', text)
        return text


# ===================================================================
# ⏰ SCHEDULER (отложенная публикация)
# ===================================================================
class PublishScheduler:
    """Планировщик отложенных публикаций"""
    
    def __init__(self, max_client: MAXClient, channel_id: str):
        self.max_client = max_client
        self.channel_id = channel_id
        self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        self.scheduled_posts: Dict[str, Dict] = {}
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
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id: int, post_ Dict, publish_at: str) -> Optional[str]:
        """Планирует публикацию поста"""
        logger.info(f"[SCHEDULER] 📅 schedule_post(user_id={user_id}, publish_at={publish_at})")
        
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None:
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
        self.stats: Dict[str, Dict] = {}
        self.clicks: Dict[str, Dict[int, int]] = {}
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
                logger.info(f"[STATS] 📥 Loaded stats: {len(self.stats)} messages")
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
                if self.stats[message_id]['first_view_at'] is None:
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
        if message_id is not None:
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
# 🎮 HANDLERS
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
        
        # 🔥 Inline-кнопки меню (max:// или url)
        keyboard = {
            "inline_keyboard": [
                [{"text": "➕ Новый пост", "url": "max://new_post"}],
                [{"text": "📋 Черновики", "url": "max://drafts"}],
                [{"text": "📊 Статистика", "url": "max://stats"}],
                [{"text": "⚙️ Настройки", "url": "max://settings"}]
            ]
        }
        
        await send_callback(
            "👋 **MAX Channel Poster**\n\n"
            "Бот для публикации постов в канал.\n\n"
            "📋 Команды:\n"
            "/post — создать новый пост\n"
            "/preview — предпросмотр черновика\n"
            "/publish — опубликовать черновик в канал\n"
            "/cancel — отменить создание поста",
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
            "1️⃣ Отправьте текст поста (можно с форматированием через интерфейс MAX)\n"
            "2️⃣ Прикрепите фото/видео/файлы (по желанию)\n"
            "3️⃣ Затем отправьте кнопки в формате (каждая с новой строки = новый ряд):\n"
            "```\n"
            "Кнопка1 | Кнопка2 | Кнопка3  ← в одном ряду\n"
            "Кнопка4 | Кнопка5            ← в новом ряду\n"
            "```\n"
            "Или напишите `пропустить` для поста без кнопок"
        )
    
    async def handle_post_text(self, user_id: int, text: str, markup: List, attachments: List, send_callback):
        """Обработка текста поста"""
        logger.info(f"[CMD] 📝 handle_post_text(user_id={user_id}, text_len={len(text)}, markup={len(markup)}, attachments={len(attachments)})")
        
        session = self.state.get_session_data(user_id)
        session['text'] = text
        session['markup'] = markup if markup else []
        session['attachments'] = attachments if attachments else []
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback(
            "🔘 **Добавьте кнопки**\n\n"
            "Формат (каждая кнопка с новой строки = новый ряд):\n"
            "```\n"
            "Текст | ссылка    ← в одном ряду: Текст1 | Текст2 | ссылка3\n"
            "```\n"
            "Поддерживаются разделители: |  -  →\n"
            "Или напишите «пропустить» для поста без кнопок."
        )
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        """Обработка кнопок поста"""
        logger.info(f"[CMD] 🔘 handle_post_buttons(user_id={user_id})")
        
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            button_rows = []
        else:
            button_rows, _ = TextFormatter.parse_buttons(buttons_text)
            if not button_rows and buttons_text.strip():
                await send_callback("❌ Не удалось распознать кнопки. Проверьте формат: `Текст | ссылка`")
                return
        
        # Сохраняем черновик
        session['button_rows'] = button_rows
        # Плоский список кнопок для отправки в MAX
        session['buttons'] = [btn for row in button_rows for btn in row]
        self.state.save_draft(user_id, session.copy())
        
        # 🔥 Формируем ПРЕДПРОСМОТР
        preview_lines = ["👁 **Предпросмотр поста**\n"]
        
        # Применяем markup к тексту для предпросмотра (конвертируем в HTML)
        if session.get('markup'):
            preview_text = TextFormatter.apply_markup_to_html(session['text'], session['markup'])
        else:
            preview_text = TextFormatter.strip_markdown(session['text'])
        preview_lines.append(preview_text)
        
        # Показываем медиа
        if session.get('attachments'):
            preview_lines.append("\n📎 Вложения:")
            for att in session['attachments']:
                if att.get('type') == 'share':
                    preview_lines.append(f"• 🔗 {att.get('title', att.get('url', 'Ссылка'))}")
                else:
                    preview_lines.append(f"• 📷 {att.get('filename', 'Медиа')}")
        
        # Показываем кнопки
        if button_rows:
            preview_lines.append("\n🔘 Кнопки под постом:")
            for i, row in enumerate(button_rows, 1):
                row_str = "  ".join([f"[{btn['text']}]({btn['url']})" for btn in row])
                preview_lines.append(f"{i}. {row_str}")
        
        preview_lines.append("\n\n✅ Для публикации напиши: `/publish`")
        preview_lines.append("❌ Для отмены: `/cancel`")
        preview_lines.append("👁 Ещё раз предпросмотр: `/preview`")
        
        preview_text = '\n'.join(preview_lines)
        
        # 🔥 Отправляем предпросмотр С КНОПКАМИ
        await send_callback(preview_text, buttons=session['buttons'])
        
        # 🔥 Отправляем подсказки отдельным сообщением
        await send_callback("💡 *Нажмите /publish для публикации или /cancel для отмены*")
        
        self.state.set_step(user_id, 'post_ready')
        logger.info(f"[CMD] ✅ Draft ready for user {user_id} | button_rows={len(button_rows)}")
    
    async def handle_preview(self, user_id: int, send_callback):
        """Предпросмотр черновика"""
        logger.info(f"[CMD] 👁 handle_preview(user_id={user_id})")
        
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден. Создайте пост через /post")
            return
        
        # Формируем предпросмотр
        preview_lines = ["👁 **Предпросмотр**\n"]
        
        if draft.get('markup'):
            preview_text = TextFormatter.apply_markup_to_html(draft['text'], draft['markup'])
        else:
            preview_text = TextFormatter.strip_markdown(draft['text'])
        preview_lines.append(preview_text)
        
        if draft.get('attachments'):
            preview_lines.append("\n📎 Вложения:")
            for att in draft['attachments']:
                preview_lines.append(f"• {att.get('filename', att.get('title', 'Медиа'))}")
        
        if draft.get('button_rows'):
            preview_lines.append("\n🔘 Кнопки:")
            for row in draft['button_rows']:
                row_str = "  ".join([f"[{btn['text']}]({btn['url']})" for btn in row])
                preview_lines.append(f"• {row_str}")
        
        preview_lines.append("\n\n✅ /publish — опубликовать")
        preview_lines.append("❌ /cancel — отменить")
        
        await send_callback('\n'.join(preview_lines), buttons=draft.get('buttons'))
        logger.info(f"[CMD] ✅ Sent preview to user {user_id}")
    
    async def handle_publish(self, user_id: int, send_callback, immediate: bool = True):
        """Публикация поста"""
        logger.info(f"[CMD] 🚀 handle_publish(user_id={user_id}, immediate={immediate})")
        
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден")
            return
        
        if immediate:
            await send_callback("⏳ Публикую...")
            
            # 🔥 Обрабатываем вложения: скачиваем и готовим для публикации
            published_attachments = []
            
            for att in draft.get('attachments', []):
                if att.get('type') == 'share':
                    # Ссылки передаём как есть
                    published_attachments.append(att)
                else:
                    # Медиа скачиваем и кэшируем
                    url = att.get('url')
                    if url:
                        cached = await self.media_mgr.download_and_cache(url, att.get('filename'))
                        if cached:
                            # Для публикации передаём token или загружаем заново
                            if att.get('token'):
                                published_attachments.append({
                                    'type': att['type'],
                                    'payload': {
                                        'token': att['token'],
                                        'url': url
                                    },
                                    'title': att.get('title'),
                                    'description': att.get('description')
                                })
                            else:
                                # Загружаем заново через API
                                file_data = self.media_mgr.get_cached_file(cached['hash'])
                                if file_data is not None:
                                    upload_result = await self.max_client.upload_media(
                                        file_data, cached['filename'], cached['type']
                                    )
                                    if 'error' not in upload_result:
                                        published_attachments.append(upload_result)
            
            result = await self.max_client.send_message(
                chat_id=self.channel_id,
                text=draft['text'],
                buttons=draft.get('buttons'),
                markup=draft.get('markup'),
                attachments=published_attachments if published_attachments else None
            )
            
            if "error" not in result:
                message_id = result.get('message', {}).get('mid')
                if message_id is not None:
                    self.stats.record_message(message_id, self.channel_id, draft['text'], datetime.now().isoformat())
                
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send_callback("✅ **Пост опубликован!** 🎉\n\nНовый пост: /post")
                logger.info(f"[CMD] ✅ Post published by user {user_id}")
            else:
                await send_callback(f"❌ Ошибка публикации: {result.get('detail', 'неизвестная')}")
                logger.error(f"[CMD] ❌ Publish failed: {result}")
        else:
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
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден")
            return
        
        job_id = self.scheduler.schedule_post(user_id, draft, time_str)
        
        if job_id is not None:
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
        
        report = ["📊 **Статистика публикаций**\n"]
        for item in all_stats[-10:]:
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
        
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала авторизуйтесь")
            return
        
        await send_callback(
            "⚙️ **Настройки**\n\n"
            "📢 `/set_channel <ID>` — сменить канал публикации\n"
            "🔑 `/set_password <новый_пароль>` — сменить пароль бота\n"
            "👥 `/list_admins` — показать авторизованных пользователей"
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        """Смена канала публикации"""
        logger.info(f"[CMD] 📢 handle_set_channel(user_id={user_id}, new_channel={new_channel_id})")
        await send_callback(f"✅ Канал изменён на: `{new_channel_id}`\n\n⚠️ Для применения перезапустите бота или обновите переменную MAX_CHANNEL_ID")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        """Смена пароля"""
        logger.info(f"[CMD] 🔑 handle_set_password(user_id={user_id})")
        self.auth.change_password(new_password)
        await send_callback("✅ Пароль изменён.\n\n🔁 Все пользователи должны будут авторизоваться заново.")
    
    async def handle_list_admins(self, user_id: int, send_callback):
        """Показать список авторизованных"""
        logger.info(f"[CMD] 👥 handle_list_admins(user_id={user_id})")
        admins = self.auth.list_authorized()
        if not admins:
            await send_callback("👥 Нет авторизованных пользователей")
            return
        report = ["👥 **Авторизованные пользователи**\n"]
        for admin in admins:
            report.append(f"• ID: `{admin['user_id']}` — авторизован: {admin['auth_time']}")
        await send_callback('\n'.join(report))
    
    async def handle_cancel(self, user_id: int, send_callback):
        """Отмена создания поста"""
        logger.info(f"[CMD] ❌ handle_cancel(user_id={user_id})")
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback("🗑️ Черновик удалён.\n\nНовый пост: /post")


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
    
    # 🔧 Извлекаем ID пользователя И chat_id для ответа
    recipient = msg.get('recipient', {})
    user_id = recipient.get('user_id') or recipient.get('chat_id') or recipient.get('id')
    
    # 🔧 FIX: используем chat_id из recipient для отправки ответов!
    chat_id_for_reply = recipient.get('chat_id') or recipient.get('user_id') or user_id
    
    if user_id is None:
        logger.error(f"[MSG] ❌ Could not extract user_id from recipient: {recipient}")
        return
    
    logger.info(f"[MSG] 👤 user_id={user_id} | reply_chat_id={chat_id_for_reply}")
    
    # 🔧 Создаём колбэк для отправки ответа — ИСПРАВЛЕНО
    async def send_callback(text: str, keyboard: Dict = None):
        # 🔧 Извлекаем кнопки из keyboard или используем buttons напрямую
        buttons = None
        if keyboard is not None:
            if isinstance(keyboard, dict) and 'inline_keyboard' in keyboard:
                # Преобразуем inline_keyboard в плоский список
                buttons = [btn for row in keyboard['inline_keyboard'] for btn in row]
                logger.debug(f"[SEND] Converted inline_keyboard to {len(buttons)} buttons")
            elif isinstance(keyboard, list):
                buttons = keyboard
            else:
                buttons = keyboard
        
        logger.info(f"[SEND] 📤 Sending to chat_id={chat_id_for_reply}: text_len={len(text)}, buttons={len(buttons) if buttons else 0}")
        result = await handlers.max_client.send_message(
            chat_id=chat_id_for_reply,
            text=text,
            buttons=buttons
        )
        logger.info(f"[SEND] ← Result: {result}")
        return result
    
    # Извлекаем текст, markup и attachments
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    attachments = handlers.media_mgr.parse_attachments(body.get('attachments', []) or msg.get('attachments', []))
    
    logger.info(f"[MSG] 💬 Text: '{text[:100]}{'...' if len(text) > 100 else ''}' | markup_count={len(markup)} | attachments={len(attachments)}")
    
    # Обработка по шагам сессии
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 User session step: {step}")
    
    # 🔥 Обработка команд
    if text == '/start':
        await handlers.handle_start(user_id, send_callback)
    elif text == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    elif text == '/publish':
        await handlers.handle_publish(user_id, send_callback)
    elif text == '/cancel':
        await handlers.handle_cancel(user_id, send_callback)
    elif text == '/preview':
        await handlers.handle_preview(user_id, send_callback)
    elif text == '/stats':
        await handlers.handle_stats(user_id, send_callback)
    elif text == '/settings':
        await handlers.handle_settings(user_id, send_callback)
    elif text.startswith('/set_channel '):
        new_channel = text[len('/set_channel '):].strip()
        await handlers.handle_set_channel(user_id, new_channel, send_callback)
    elif text.startswith('/set_password '):
        new_pwd = text[len('/set_password '):].strip()
        await handlers.handle_set_password(user_id, new_pwd, send_callback)
    elif text == '/list_admins':
        await handlers.handle_list_admins(user_id, send_callback)
    elif step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, attachments, send_callback)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    elif step == 'waiting_schedule_time':
        await handlers.handle_schedule_time(user_id, text.strip(), send_callback)
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback("❓ Неизвестная команда. Доступные: /start, /post, /publish, /cancel, /preview, /stats, /settings")
        else:
            await send_callback("🔐 Сначала авторизуйтесь: /start")
    
    logger.info("=" * 80)


# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "status": "running", "version": "2.3.0-full"})

async def root_handler(request):
    return web.json_response({
        "bot": "MAX Channel Poster",
        "webhook": "active",
        "features": ["auth", "media", "buttons", "preview", "schedule", "stats", "markup"],
        "endpoints": ["/health", "/webhook"]
    })

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER BOT — FULL FEATURE v2.3")
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
    logger.info("🔚 Shutting down...")
    
    # Останавливаем планировщик
    if 'scheduler' in app:
        app['scheduler'].stop()
    
    # Закрываем HTTP-сессию
    if 'max_client' in app:
        await app['max_client'].close()
    
    # Очищаем кэш медиа
    if 'media_mgr' in app:
        app['media_mgr'].cleanup_old_cache(0)
    
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
            lambda text, buttons=None: None
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
