"""
MAX Channel Poster Bot — API FIX v5.0
🔥 ИСПРАВЛЕНО: Форматирование передаётся как оригинальный markup
🔥 ИСПРАВЛЕНО: Кнопки через поле buttons (простой массив)
🔥 ИСПРАВЛЕНО: Медиа с оригинальным payload
🔥 ИСПРАВЛЕНО: Превью показывает фото как вложение, а не ссылку
"""
import asyncio
import logging
import os
import json
import time
import re
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Union, Tuple
from pathlib import Path

from aiohttp import web, ClientSession, ClientTimeout, FormData
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===================================================================
# 🔧 CONFIG & INIT
# ===================================================================
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG').upper()
MAX_MEDIA_ITEMS = int(os.getenv('MAX_MEDIA_ITEMS', '10'))
SCHEDULER_TIMEZONE = os.getenv('SCHEDULER_TIMEZONE', 'UTC')
API_TIMEOUT = int(os.getenv('API_TIMEOUT', '120'))

DATA_DIR = Path(os.getenv('DATA_DIR', '/tmp/max-bot'))
DATA_DIR.mkdir(parents=True, exist_ok=True)
AUTH_FILE = DATA_DIR / 'authorized_users.json'
STATS_FILE = DATA_DIR / 'stats.json'
MEDIA_CACHE_DIR = DATA_DIR / 'media_cache'
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

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
logger.info("=" * 80)
logger.info(f"🔧 MAX CHANNEL POSTER v5.0 — API FORMAT FIX")
logger.info(f"🔧 CHANNEL_ID={CHANNEL_ID}")
logger.info(f"🔧 BASE_API_URL={BASE_API_URL}")
logger.info("=" * 80)

# ===================================================================
# 🔧 UTF-16 OFFSET CORRECTION (для markup)
# ===================================================================
def correct_markup_offsets(text: str, markup: List[Dict]) -> List[Dict]:
    """
    Корректирует offset'ы из UTF-16 (MAX) в Python-индексы.
    НЕ меняет структуру markup, ТОЛЬКО корректирует позиции!
    """
    if not markup:
        return []
    
    logger.info(f"[MARKUP-CORRECT] Correcting {len(markup)} entities")
    
    corrected = []
    for idx, entity in enumerate(markup):
        entity = entity.copy()
        max_offset = entity.get('from', 0)
        max_length = entity.get('length', 0)
        
        # Конвертируем UTF-16 offset → Python offset
        python_offset = 0
        utf16_pos = 0
        for i, char in enumerate(text):
            if utf16_pos >= max_offset:
                python_offset = i
                break
            utf16_pos += len(char.encode('utf-16-le')) // 2
        else:
            python_offset = len(text)
        
        # Конвертируем UTF-16 length → Python length
        python_length = 0
        utf16_pos = max_offset
        for i in range(python_offset, len(text)):
            if utf16_pos >= max_offset + max_length:
                break
            utf16_pos += len(text[i].encode('utf-16-le')) // 2
            python_length += 1
        
        entity['from'] = python_offset
        entity['length'] = python_length
        
        logger.debug(f"[MARKUP-CORRECT] [{idx}] {entity.get('type')}: [{max_offset}:{max_offset+max_length}] → [{python_offset}:{python_offset+python_length}] text='{text[python_offset:python_offset+python_length]}'")
        corrected.append(entity)
    
    return corrected

# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    def __init__(self, password: str, auth_file: Path):
        self.password = password
        self.auth_file = auth_file
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 Initialized (users={len(self.authorized)})")
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
                logger.info(f"[AUTH] 📥 Loaded {len(self.authorized)} users")
            except Exception as e:
                logger.error(f"[AUTH] ❌ Load error: {e}")
    
    def _save_to_file(self):
        try:
            data = {
                'users': {str(k): v for k, v in self.authorized.items()},
                'failed': {str(k): v for k, v in self.failed_attempts.items()},
                'updated_at': datetime.now().isoformat()
            }
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[AUTH] ⚠️ Save error: {e}")
    
    def check_password(self, user_id: int, password: str) -> bool:
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat(),
                'password_hash': hashlib.sha256(self.password.encode()).hexdigest()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            logger.info(f"[AUTH] ✅ User {user_id} authorized")
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save_to_file()
        return False
    
    def is_authorized(self, user_id: int) -> bool:
        return user_id in self.authorized
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
    
    def list_authorized(self) -> List[Dict]:
        return [{'user_id': uid, 'auth_time': data['auth_time']} for uid, data in self.authorized.items()]
    
    def change_password(self, new_password: str):
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()
        logger.info(f"[AUTH] 🔑 Password changed, all sessions cleared")

# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
        logger.info("[STATE] 🗄 Initialized")
    
    def get_session(self, user_id: int) -> Dict:
        if user_id not in self.sessions:
            self.sessions[user_id] = {'step': None, 'data': {}}
        return self.sessions[user_id]
    
    def set_step(self, user_id: int, step: str, data: Optional[Dict] = None):
        session = self.get_session(user_id)
        old = session.get('step')
        session['step'] = step
        if data is not None:
            session['data'].update(data)
        logger.info(f"[STATE] 📍 User {user_id}: {old} → {step}")
    
    def get_step(self, user_id: int) -> Optional[str]:
        return self.sessions.get(user_id, {}).get('step')
    
    def get_session_data(self, user_id: int) -> Dict:
        return self.sessions.get(user_id, {}).get('data', {})
    
    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"[STATE] 🧹 Session cleared for {user_id}")
    
    def save_draft(self, user_id: int, draft: Dict):
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
        logger.info(f"[STATE] 💾 Draft saved for {user_id} | keys={list(draft.keys())}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]
            logger.info(f"[STATE] 🗑️ Draft cleared for {user_id}")

# ===================================================================
# 📡 MAX API CLIENT
# ===================================================================
class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        logger.info(f"[MAX] 📡 Client initialized")
    
    async def init(self):
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
    
    async def close(self):
        if self.session is not None:
            await self.session.close()
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None, 
                       max_retries: int = 3) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/5.0"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.info(f"[MAX] 📤 BODY: {json.dumps(data, ensure_ascii=False)[:600] if data else 'None'}")
        
        for attempt in range(max_retries):
            try:
                start = time.time()
                async with self.session.request(
                    method=method, url=url, headers=headers,
                    json=data, timeout=self.timeout
                ) as response:
                    elapsed = time.time() - start
                    text = await response.text()
                    
                    logger.info(f"[MAX] ◀️ #{self.request_count}: {response.status} in {elapsed:.2f}s")
                    logger.info(f"[MAX] 📥 RESPONSE: {text[:600]}")
                    
                    if response.status == 200:
                        try:
                            return json.loads(text) if text.strip() else {}
                        except json.JSONDecodeError:
                            return {"raw": text}
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 30))
                        logger.warning(f"[MAX] ⏳ Rate limit, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    logger.error(f"[MAX] ❌ HTTP {response.status}: {text[:300]}")
                    return {"error": f"HTTP_{response.status}", "detail": text}
                    
            except asyncio.TimeoutError:
                logger.warning(f"[MAX] ⏱ Timeout (attempt {attempt+1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "timeout"}
            except Exception as e:
                logger.error(f"[MAX] 💥 Exception: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return {"error": "exception", "detail": str(e)}
        
        return {"error": "max_retries_exceeded"}
    
    # 🔥 ОСНОВНОЙ МЕТОД ОТПРАВКИ
    async def send_message(self, chat_id: Union[str, int], text: str, 
                          markup: Optional[List[Dict]] = None,
                          buttons: Optional[List[List[Dict]]] = None,
                          attachments: Optional[List[Dict]] = None) -> Dict:
        """
        Отправляет сообщение в MAX.
        
        🔥 text — чистый текст (без HTML!)
        🔥 markup — оригинальный массив entities [{type, from, length}]
        🔥 buttons — массив рядов кнопок [[{text, url}]]
        🔥 attachments — оригинальные вложения с payload
        """
        logger.info(f"[MAX-SEND] ========== SENDING ==========")
        logger.info(f"[MAX-SEND] chat_id={chat_id}")
        logger.info(f"[MAX-SEND] text='{text[:100]}...' (len={len(text)})")
        logger.info(f"[MAX-SEND] markup={len(markup) if markup else 0} entities")
        logger.info(f"[MAX-SEND] buttons={'YES' if buttons else 'NO'}")
        logger.info(f"[MAX-SEND] attachments={len(attachments) if attachments else 0} items")
        
        payload = {"text": text}
        
        # 🔥 markup как есть (entities)
        if markup is not None and len(markup) > 0:
            payload["markup"] = markup
            logger.info(f"[MAX-SEND] Adding markup: {len(markup)} entities")
            for i, m in enumerate(markup):
                logger.debug(f"[MAX-SEND]   [{i}] type={m.get('type')}, from={m.get('from')}, length={m.get('length')}")
        
        # 🔥 buttons — простой массив рядов
        if buttons is not None and len(buttons) > 0:
            payload["buttons"] = buttons
            total_btns = sum(len(row) for row in buttons)
            logger.info(f"[MAX-SEND] Adding buttons: {len(buttons)} rows, {total_btns} buttons")
            for i, row in enumerate(buttons):
                for j, btn in enumerate(row):
                    logger.info(f"[MAX-SEND]   [{i}][{j}]: '{btn.get('text')}' → {btn.get('url', '')[:60]}...")
        
        # 🔥 attachments с оригинальным payload
        if attachments is not None and len(attachments) > 0:
            payload["attachments"] = attachments
            logger.info(f"[MAX-SEND] Adding attachments: {len(attachments)} items")
            for i, att in enumerate(attachments):
                logger.info(f"[MAX-SEND]   [{i}] type={att.get('type')}, payload_keys={list(att.get('payload', {}).keys())}")
        
        logger.info(f"[MAX-SEND] Final payload keys: {list(payload.keys())}")
        
        endpoint = f"/messages?chat_id={chat_id}"
        result = await self._request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[MAX-SEND] ❌ FAILED: {result.get('detail', 'unknown')[:200]}")
        else:
            msg_id = result.get('message', {}).get('body', {}).get('mid', 'unknown')
            logger.info(f"[MAX-SEND] ✅ SUCCESS! msg_id={msg_id}")
        
        logger.info(f"[MAX-SEND] ========== END SEND ==========")
        return result
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        logger.info(f"[MAX] 🔗 Registering webhook: {webhook_url}")
        body = {
            "url": webhook_url,
            "chat_id": chat_id,
            "update_types": ["message_created"]
        }
        result = await self._request("POST", "/subscriptions", data=body)
        success = "error" not in result
        logger.info(f"[MAX] Webhook registration: {'✅' if success else '❌'}")
        return success

# ===================================================================
# 🖼 MEDIA MANAGER
# ===================================================================
class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
        logger.info(f"[MEDIA] 🖼 Initialized")
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """
        Парсит вложения из сообщения MAX.
        🔥 Сохраняет оригинальный payload нетронутым!
        """
        logger.info(f"[MEDIA] 🔍 Parsing {len(attachments)} attachments")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                logger.warning(f"[MEDIA] [{i}] Not a dict, skipping")
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            logger.info(f"[MEDIA] [{i}] type='{att_type}', payload_keys={list(payload.keys())}")
            
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                parsed = {
                    'type': att_type,
                    'payload': payload.copy(),  # 🔥 СОХРАНЯЕМ ОРИГИНАЛЬНЫЙ PAYLOAD
                    'url': payload.get('url') or att.get('url', ''),
                    'filename': payload.get('filename') or att.get('title', f'file_{i}'),
                    'index': i
                }
                result.append(parsed)
                logger.info(f"[MEDIA] [{i}] ✅ Parsed: type={att_type}, url={'present' if parsed['url'] else 'MISSING'}")
            else:
                logger.warning(f"[MEDIA] [{i}] ⚠️ Unknown type '{att_type}'")
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} items")
        return result

# ===================================================================
# 📊 STATS MODULE
# ===================================================================
class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        self._load_from_file()
    
    def _load_from_file(self):
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f).get('messages', {})
            except Exception:
                pass
    
    def _save_to_file(self):
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump({'messages': self.stats, 'updated_at': datetime.now().isoformat()}, f, indent=2)
        except Exception:
            pass
    
    def record_message(self, message_id: str, chat_id: str, text: str, published_at: str):
        self.stats[message_id] = {
            'chat_id': chat_id,
            'text_preview': text[:100],
            'published_at': published_at,
            'views': 0
        }
        self._save_to_file()
    
    def get_stats(self, message_id: Optional[str] = None):
        if message_id:
            return self.stats.get(message_id, {})
        return [{'message_id': mid, **data} for mid, data in self.stats.items()]

# ===================================================================
# ⏰ SCHEDULER
# ===================================================================
class PublishScheduler:
    def __init__(self, max_client: MAXClient, channel_id: str):
        self.max_client = max_client
        self.channel_id = channel_id
        self.scheduler = AsyncIOScheduler(timezone=SCHEDULER_TIMEZONE)
        self.scheduled_posts: Dict[str, Dict] = {}
    
    def start(self):
        self.scheduler.start()
        logger.info("[SCHEDULER] 🚀 Started")
    
    def stop(self):
        self.scheduler.shutdown()
        logger.info("[SCHEDULER] 🛑 Stopped")
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id: int, post_data: Dict, publish_at: str) -> Optional[str]:
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def publish_job():
            await self.max_client.send_message(
                chat_id=self.channel_id,
                text=post_data.get('text', ''),
                markup=post_data.get('markup'),
                buttons=post_data.get('buttons'),
                attachments=post_data.get('attachments')
            )
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(publish_job, trigger=trigger, id=job_id, replace_existing=True)
        self.scheduled_posts[job_id] = {
            'user_id': user_id,
            'publish_at': publish_at,
            'scheduled_at': datetime.now().isoformat()
        }
        return job_id

# ===================================================================
# 🎮 COMMAND HANDLERS
# ===================================================================
class CommandHandlers:
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
        logger.info(f"[HANDLERS] 🎮 Initialized")
    
    async def handle_start(self, user_id: int, chat_id: int, send_callback):
        logger.info(f"[CMD] /start user={user_id}")
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль для доступа:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        menu_buttons = [
            [{"text": "➕ Новый пост", "url": "max://new_post"}],
            [{"text": "📊 Статистика", "url": "max://stats"}],
            [{"text": "⚙️ Настройки", "url": "max://settings"}]
        ]
        
        await send_callback(
            "👋 MAX Channel Poster\n\n"
            "/post — создать пост\n"
            "/preview — предпросмотр\n"
            "/publish — опубликовать\n"
            "/cancel — отменить",
            buttons=menu_buttons
        )
    
    async def handle_password(self, user_id: int, password: str, send_callback):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            self.state.clear_session(user_id)
            session = self.state.get_session(user_id)
            chat_id = session.get('chat_id', user_id)
            await self.handle_start(user_id, chat_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось попыток: {remaining}")
            else:
                await send_callback("🔒 Слишком много попыток.")
    
    async def handle_post_command(self, user_id: int, send_callback):
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала /start")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        await send_callback(
            "📝 Создание поста\n\n"
            "1. Отправьте текст с форматированием\n"
            "2. Прикрепите фото/видео/файлы\n"
            "3. Добавьте кнопки в формате:\n"
            "Название кнопки | https://ссылка\n\n"
            "Каждая кнопка с новой строки"
        )
    
    # 🔥 ИСПРАВЛЕНО: Сохраняем оригинальный markup
    async def handle_post_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        logger.info(f"[CMD-TEXT] ========== RECEIVED TEXT ==========")
        logger.info(f"[CMD-TEXT] text='{text[:100]}...' (len={len(text)})")
        logger.info(f"[CMD-TEXT] markup={len(markup)} entities")
        logger.info(f"[CMD-TEXT] attachments={len(raw_attachments)} items")
        
        if markup:
            for idx, m in enumerate(markup):
                logger.info(f"[CMD-TEXT] markup[{idx}]: type={m.get('type')}, from={m.get('from')}, length={m.get('length')}")
        
        session = self.state.get_session_data(user_id)
        
        # 🔥 Корректируем offset'ы, но НЕ меняем структуру markup
        corrected_markup = correct_markup_offsets(text, markup)
        
        session['text'] = text
        session['markup'] = corrected_markup
        
        # Парсим вложения (сохраняем оригинальный payload)
        attachments = self.media_mgr.parse_attachments(raw_attachments)
        session['raw_attachments'] = raw_attachments
        session['attachments'] = attachments
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        
        await send_callback(
            "🔘 Добавьте кнопки\n\n"
            "Формат: Название | https://ссылка\n\n"
            "Пример:\n"
            "Купить | https://shop.ru\n"
            "Подробнее | https://info.ru\n\n"
            "Напишите пропустить если не нужны"
        )
    
    def parse_buttons(self, text: str) -> List[List[Dict]]:
        """Парсит кнопки: Название | url"""
        logger.info(f"[BTN-PARSE] Parsing: '{text[:200]}...'")
        rows = []
        lines = text.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            for sep in [' | ', ' - ', ' → ', ' -> ', ' — ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://', 't.me/', 'max://')):
                        rows.append([{'text': btn_text, 'url': btn_url}])
                        logger.info(f"[BTN-PARSE] ✅ '{btn_text}' → {btn_url[:60]}...")
                        break
        
        logger.info(f"[BTN-PARSE] Total: {len(rows)} button rows")
        return rows
    
    async def handle_post_buttons(self, user_id: int, buttons_text: str, send_callback):
        logger.info(f"[CMD-BTN] ========== RECEIVED BUTTONS ==========")
        logger.info(f"[CMD-BTN] text='{buttons_text[:150]}...'")
        
        session = self.state.get_session_data(user_id)
        
        if buttons_text.lower().strip() in ('пропустить', 'skip', '-'):
            button_rows = []
        else:
            button_rows = self.parse_buttons(buttons_text)
        
        session['buttons'] = button_rows
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        # 🔥 Отправляем превью
        await self.send_preview(user_id, send_callback, session)
    
    # 🔥 ПРЕДПРОСМОТР
    async def send_preview(self, user_id: int, send_callback, draft: Optional[Dict] = None):
        """Превью с фото и кнопками"""
        logger.info(f"[PREVIEW] ========== SENDING PREVIEW ==========")
        
        if draft is None:
            draft = self.state.get_draft(user_id)
        
        if draft is None or 'text' not in draft:
            await send_callback("❌ Нет черновика")
            return
        
        text = draft['text']
        markup = draft.get('markup', [])
        buttons = draft.get('buttons', [])
        attachments = draft.get('attachments', [])
        
        logger.info(f"[PREVIEW] text='{text[:80]}...', markup={len(markup)}, buttons={len(buttons)}, attachments={len(attachments)}")
        
        chat_id = self.state.get_session(user_id).get('chat_id', user_id)
        
        # 🔥 1. Отправляем медиа (фото/видео) как вложения
        media_sent = False
        for att in attachments:
            att_type = att.get('type', '')
            
            if att_type in ('image', 'photo') and att.get('payload'):
                logger.info(f"[PREVIEW] 📸 Sending photo as attachment")
                caption = text if not media_sent else ""
                
                await self.max_client.send_message(
                    chat_id=chat_id,
                    text=caption if caption else "🖼",
                    markup=markup if not media_sent else None,
                    attachments=[{
                        'type': att_type,
                        'payload': att['payload']
                    }]
                )
                media_sent = True
                await asyncio.sleep(0.3)
        
        # 🔥 2. Если фото не было — отправляем текст
        if not media_sent:
            await self.max_client.send_message(
                chat_id=chat_id,
                text=text,
                markup=markup
            )
        
        # 🔥 3. Отправляем кнопки поста (если есть)
        if buttons:
            logger.info(f"[PREVIEW] 🔘 Sending {len(buttons)} post buttons")
            await self.max_client.send_message(
                chat_id=chat_id,
                text="🔘 Кнопки поста:",
                buttons=buttons
            )
        
        # 🔥 4. Кнопки действий
        action_buttons = [
            [
                {"text": "✅ Опубликовать", "url": "max://publish"},
                {"text": "✏️ Редактировать", "url": "max://edit"}
            ],
            [
                {"text": "❌ Отмена", "url": "max://cancel"}
            ]
        ]
        
        await self.max_client.send_message(
            chat_id=chat_id,
            text="⚙️ Действия:",
            buttons=action_buttons
        )
        
        logger.info(f"[PREVIEW] ========== END PREVIEW ==========")
    
    async def handle_preview(self, user_id: int, send_callback):
        await self.send_preview(user_id, send_callback)
    
    async def handle_edit(self, user_id: int, send_callback):
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send_callback("❌ Нет черновика. /post — новый пост")
            return
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        await send_callback(
            "✏️ Редактирование\n\n"
            "Отправьте новый текст или фото\n"
            "/buttons — редактировать кнопки\n"
            "/preview — предпросмотр"
        )
    
    async def handle_edit_text(self, user_id: int, text: str, markup: List, 
                               raw_attachments: List, send_callback):
        logger.info(f"[CMD-EDIT] Editing text for {user_id}")
        
        session = self.state.get_session_data(user_id)
        
        corrected_markup = correct_markup_offsets(text, markup)
        session['text'] = text
        session['markup'] = corrected_markup
        
        if raw_attachments:
            new_attachments = self.media_mgr.parse_attachments(raw_attachments)
            existing = session.get('attachments', [])
            session['attachments'] = existing + new_attachments
            session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
        
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        await send_callback("✅ Текст обновлён!")
        await self.send_preview(user_id, send_callback, session)
    
    # 🔥 ПУБЛИКАЦИЯ — передаём всё как есть
    async def handle_publish(self, user_id: int, send_callback, 
                            immediate: bool = True, schedule_time: Optional[str] = None):
        logger.info(f"[CMD-PUBLISH] ========== PUBLISHING ==========")
        logger.info(f"[CMD-PUBLISH] immediate={immediate}")
        
        draft = self.state.get_draft(user_id)
        if draft is None or 'text' not in draft:
            await send_callback("❌ Черновик не найден")
            return
        
        logger.info(f"[CMD-PUBLISH] text='{draft['text'][:80]}...'")
        logger.info(f"[CMD-PUBLISH] markup={len(draft.get('markup', []))} entities")
        logger.info(f"[CMD-PUBLISH] buttons={len(draft.get('buttons', []))} rows")
        logger.info(f"[CMD-PUBLISH] attachments={len(draft.get('raw_attachments', []))} items")
        
        if not immediate and schedule_time:
            job_id = self.scheduler.schedule_post(user_id, draft, schedule_time)
            if job_id:
                self.state.clear_draft(user_id)
                self.state.clear_session(user_id)
                await send_callback(f"✅ Запланировано на {schedule_time}")
            else:
                await send_callback("❌ Неверный формат даты (ГГГГ-ММ-ДД ЧЧ:ММ)")
            return
        
        await send_callback("⏳ Публикую...")
        
        # 🔥 Формируем attachments с оригинальным payload
        attachments = []
        for att in draft.get('raw_attachments', []):
            if isinstance(att, dict) and att.get('type'):
                attachments.append({
                    'type': att['type'],
                    'payload': att.get('payload', {})
                })
        
        # 🔥 Отправляем в канал
        result = await self.max_client.send_message(
            chat_id=self.channel_id,
            text=draft['text'],
            markup=draft.get('markup'),
            buttons=draft.get('buttons'),
            attachments=attachments if attachments else None
        )
        
        if "error" not in result:
            message_id = result.get('message', {}).get('body', {}).get('mid')
            if message_id is not None:
                self.stats.record_message(message_id, self.channel_id, draft['text'], datetime.now().isoformat())
            
            self.state.clear_draft(user_id)
            self.state.clear_session(user_id)
            
            await send_callback("✅ Пост опубликован! /post — новый пост")
            logger.info(f"[CMD-PUBLISH] ✅ SUCCESS! msg_id={message_id}")
        else:
            error_detail = result.get('detail', 'неизвестная ошибка')
            await send_callback(f"❌ Ошибка публикации: {error_detail[:200]}")
            logger.error(f"[CMD-PUBLISH] ❌ FAILED: {error_detail[:200]}")
        
        logger.info(f"[CMD-PUBLISH] ========== END PUBLISH ==========")
    
    async def handle_cancel(self, user_id: int, send_callback):
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback("🗑️ Черновик удалён. /post — новый пост")
    
    async def handle_stats(self, user_id: int, send_callback):
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пока пуста")
            return
        report = ["📊 Последние посты:\n"]
        for item in all_stats[-10:]:
            mid = item['message_id'][:12]
            report.append(f"• {mid}... | 👁 {item.get('views', 0)}")
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id: int, send_callback):
        await send_callback(
            "⚙️ Настройки\n\n"
            "/set_channel ID — сменить канал\n"
            "/set_password pwd — сменить пароль\n"
            "/list_admins — список админов"
        )
    
    async def handle_set_channel(self, user_id: int, new_channel_id: str, send_callback):
        await send_callback(f"✅ Канал: {new_channel_id} (перезапустите бота)")
    
    async def handle_set_password(self, user_id: int, new_password: str, send_callback):
        self.auth.change_password(new_password)
        await send_callback("✅ Пароль изменён.")
    
    async def handle_list_admins(self, user_id: int, send_callback):
        admins = self.auth.list_authorized()
        if not admins:
            await send_callback("👥 Нет авторизованных")
            return
        report = ["👥 Авторизованные:"]
        for a in admins:
            report.append(f"• ID: {a['user_id']} | {a['auth_time'][:16]}")
        await send_callback('\n'.join(report))

# ===================================================================
# 🌐 WEBHOOK HANDLER
# ===================================================================
async def webhook_handler(request, handlers: CommandHandlers):
    logger.info(f"[WEBHOOK] 📨 {request.method} from {request.remote}")
    if request.method != 'POST':
        return web.Response(status=405)
    
    try:
        body = await request.json()
        logger.info(f"[WEBHOOK] 📦 {json.dumps(body, ensure_ascii=False)[:800]}")
        
        if body.get('update_type') == 'message_created' and (msg := body.get('message')):
            await handle_incoming_message(msg, handlers)
        
        return web.Response(status=200)
    except Exception as e:
        logger.exception(f"[WEBHOOK] Error: {e}")
        return web.Response(status=500)

async def handle_incoming_message(msg: Dict, handlers: CommandHandlers):
    logger.info("=" * 80)
    logger.info("[MSG] 📨 Processing incoming message")
    
    rec = msg.get('recipient', {})
    sender = msg.get('sender', {})
    
    user_id = rec.get('user_id') or sender.get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        logger.error("[MSG] Cannot determine user_id")
        return
    
    logger.info(f"[MSG] 👤 user_id={user_id} | chat_id={chat_id}")
    
    # Сохраняем chat_id
    session = handlers.state.get_session(user_id)
    session['chat_id'] = chat_id
    
    # 🔥 send_callback
    async def send_callback(text: str, 
                           markup: Optional[List[Dict]] = None,
                           buttons: Optional[List[List[Dict]]] = None,
                           attachments: Optional[List[Dict]] = None):
        logger.info(f"[SEND] 📤 To {chat_id or user_id}: '{text[:50]}...'")
        result = await handlers.max_client.send_message(
            chat_id=chat_id or user_id,
            text=text,
            markup=markup,
            buttons=buttons,
            attachments=attachments
        )
        return result
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    logger.info(f"[MSG] 💬 text='{text[:100]}...' (len={len(text)})")
    logger.info(f"[MSG] 🎨 markup={len(markup)} entities")
    logger.info(f"[MSG] 📎 attachments={len(raw_attachments)} items")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] 📍 step={step}")
    
    cmd = text.strip()
    
    # Маршрутизация
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send_callback)
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send_callback)
    elif cmd == '/edit':
        await handlers.handle_edit(user_id, send_callback)
    elif cmd == '/buttons':
        handlers.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback("🔘 Отправьте кнопки (или пропустить):")
    elif cmd == '/publish':
        await handlers.handle_publish(user_id, send_callback)
    elif cmd.startswith('/schedule '):
        time_str = cmd.replace('/schedule ', '').strip()
        await handlers.handle_publish(user_id, send_callback, immediate=False, schedule_time=time_str)
    elif cmd == '/cancel':
        await handlers.handle_cancel(user_id, send_callback)
    elif cmd == '/stats':
        await handlers.handle_stats(user_id, send_callback)
    elif cmd == '/settings':
        await handlers.handle_settings(user_id, send_callback)
    elif cmd.startswith('/set_channel '):
        await handlers.handle_set_channel(user_id, cmd.split()[1], send_callback)
    elif cmd.startswith('/set_password '):
        await handlers.handle_set_password(user_id, cmd.split()[1], send_callback)
    elif cmd == '/list_admins':
        await handlers.handle_list_admins(user_id, send_callback)
    elif step == 'waiting_password':
        await handlers.handle_password(user_id, text.strip(), send_callback)
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send_callback)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    elif step == 'post_ready':
        await handlers.handle_edit_text(user_id, text, markup, raw_attachments, send_callback)
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback(
                "MAX Channel Poster\n\n"
                "/post — создать пост\n"
                "/preview — предпросмотр\n"
                "/edit — редактировать\n"
                "/publish — опубликовать"
            )
        else:
            await send_callback("🔐 /start для авторизации")
    
    logger.info("=" * 80)

# ===================================================================
# 🌐 WEB SERVER
# ===================================================================
async def health_check(request):
    return web.json_response({"ok": True, "version": "5.0-api-fix"})

async def root_handler(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "5.0"})

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING MAX CHANNEL POSTER v5.0")
    logger.info("🚀" * 40)
    
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE)
    app['state'] = StateManager()
    app['max_client'] = MAXClient(BOT_TOKEN, BASE_API_URL, API_TIMEOUT)
    app['media_mgr'] = MediaManager(MEDIA_CACHE_DIR, MAX_MEDIA_ITEMS)
    app['stats'] = StatsCollector(STATS_FILE)
    
    app['scheduler'] = PublishScheduler(app['max_client'], CHANNEL_ID)
    app['scheduler'].start()
    
    app['handlers'] = CommandHandlers(
        app['auth'], app['state'], app['max_client'],
        app['media_mgr'], app['scheduler'], app['stats'], CHANNEL_ID
    )
    
    if RENDER_EXTERNAL_URL:
        await app['max_client'].register_webhook(f"{RENDER_EXTERNAL_URL}/webhook", CHANNEL_ID)
    
    logger.info("✅ All components initialized")

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if 'scheduler' in app:
        app['scheduler'].stop()
    if 'max_client' in app:
        await app['max_client'].close()
    logger.info("🔚 Cleanup complete")

def create_app():
    app = web.Application()
    
    app.router.add_get('/', root_handler)
    app.router.add_get('/health', health_check)
    app.router.add_post('/webhook', lambda req: webhook_handler(req, app['handlers']))
    
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Starting server on port {port}")
    app = create_app()
    web.run_app(app, host='0.0.0.0', port=port, access_log=None)
