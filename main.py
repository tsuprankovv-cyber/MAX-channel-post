"""
MAX Channel Poster Bot — FULL REWORK v7.0
🔥 Пошаговый алгоритм: фото → текст → кнопки → предпросмотр
🔥 Перебор 5 вариантов форматирования
🔥 Единый предпросмотр (фото+текст+кнопки в одном сообщении)
🔥 Умное меню редактирования
🔥 /skip и /cancel на каждом этапе
🔥 Опциональный пароль (REQUIRE_PASSWORD)
🔥 Максимальное логирование
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

from aiohttp import web, ClientSession, ClientTimeout
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

# ===================================================================
# 🔧 CONFIG
# ===================================================================
load_dotenv()

BOT_TOKEN = os.getenv('MAX_BOT_TOKEN', '').strip()
CHANNEL_ID = os.getenv('MAX_CHANNEL_ID', '-72890925476042').strip()
BASE_API_URL = os.getenv('MAX_API_URL', 'https://platform-api.max.ru').rstrip('/')
RENDER_EXTERNAL_URL = os.getenv('RENDER_EXTERNAL_URL', '')

BOT_PASSWORD = os.getenv('BOT_PASSWORD', '2014').strip()
REQUIRE_PASSWORD = os.getenv('REQUIRE_PASSWORD', 'true').lower() == 'true'
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

# Форматы форматирования для перебора
FORMAT_VARIANTS = [
    "markup_entities",   # markup как entities (текущий)
    "format_html",       # "format": "html" + HTML теги
    "format_markdown",   # "format": "markdown" + Markdown
]

# Логирование
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
logger.info(f"🚀 MAX CHANNEL POSTER v7.0 — FULL REWORK")
logger.info(f"🔧 CHANNEL_ID={CHANNEL_ID}")
logger.info(f"🔧 REQUIRE_PASSWORD={REQUIRE_PASSWORD}")
logger.info(f"🔧 FORMAT_VARIANTS={FORMAT_VARIANTS}")
logger.info(f"🔧 LOG_LEVEL={LOG_LEVEL}")
logger.info("=" * 80)

# ===================================================================
# 🎨 FORMATTING ENGINE (5 ВАРИАНТОВ + ПЕРЕБОР)
# ===================================================================
class FormattingEngine:
    """
    Перебирает варианты форматирования.
    🔥 Пробует все варианты, логирует каждый.
    """
    
    @staticmethod
    def correct_markup_offsets(text: str, markup: List[Dict]) -> List[Dict]:
        """Корректирует UTF-16 offset → Python offset"""
        if not markup:
            return []
        
        logger.debug(f"[FORMAT-OFFSET] Correcting {len(markup)} entities")
        corrected = []
        
        for idx, entity in enumerate(markup):
            entity = entity.copy()
            max_offset = entity.get('from', 0)
            max_length = entity.get('length', 0)
            
            python_offset = 0
            utf16_pos = 0
            for i, char in enumerate(text):
                if utf16_pos >= max_offset:
                    python_offset = i
                    break
                utf16_pos += len(char.encode('utf-16-le')) // 2
            else:
                python_offset = len(text)
            
            python_length = 0
            utf16_pos = max_offset
            for i in range(python_offset, len(text)):
                if utf16_pos >= max_offset + max_length:
                    break
                utf16_pos += len(text[i].encode('utf-16-le')) // 2
                python_length += 1
            
            entity['from'] = python_offset
            entity['length'] = python_length
            corrected.append(entity)
            
            logger.debug(f"[FORMAT-OFFSET] [{idx}] {entity.get('type')}: [{max_offset}:{max_offset+max_length}] → [{python_offset}:{python_offset+python_length}]")
        
        return corrected
    
    @staticmethod
    def markup_to_html(text: str, markup: List[Dict]) -> str:
        """Конвертирует markup entities в HTML теги"""
        if not markup:
            return text
        
        logger.info(f"[FORMAT-HTML] Converting {len(markup)} entities to HTML")
        
        tag_map = {
            "strong": "b", "bold": "b",
            "emphasized": "i", "italic": "i", "em": "i",
            "underline": "u",
            "strikethrough": "s", "strike": "s",
            "code": "code",
            "link": "a", "text_link": "a",
        }
        
        corrected = FormattingEngine.correct_markup_offsets(text, markup)
        sorted_markup = sorted(corrected, key=lambda m: (m.get('from', 0), -m.get('length', 0)))
        
        # Строим карту тегов
        tag_starts = {}
        tag_ends = {}
        
        for entity in sorted_markup:
            offset = entity.get('from', 0)
            length = entity.get('length', 0)
            etype = entity.get('type', '')
            
            if etype not in tag_map:
                continue
            
            tag_name = tag_map[etype]
            
            if etype in ('link', 'text_link', 'url'):
                url = entity.get('url', '').replace('"', '&quot;')
                open_tag = f'<{tag_name} href="{url}">' if url else f'<{tag_name}>'
            else:
                open_tag = f'<{tag_name}>'
            
            close_tag = f'</{tag_name}>'
            
            if offset not in tag_starts:
                tag_starts[offset] = []
            tag_starts[offset].append(open_tag)
            
            end_pos = offset + length
            if end_pos not in tag_ends:
                tag_ends[end_pos] = []
            tag_ends[end_pos].append(close_tag)
        
        # Собираем HTML
        result = []
        for i, char in enumerate(text):
            if i in tag_ends:
                for tag in tag_ends[i]:
                    result.append(tag)
            if i in tag_starts:
                for tag in tag_starts[i]:
                    result.append(tag)
            result.append(char)
        
        last_pos = len(text)
        if last_pos in tag_ends:
            for tag in tag_ends[last_pos]:
                result.append(tag)
        
        final = ''.join(result)
        logger.info(f"[FORMAT-HTML] Output: '{final[:150]}...'")
        return final
    
    @staticmethod
    def markup_to_markdown(text: str, markup: List[Dict]) -> str:
        """Конвертирует markup entities в Markdown"""
        if not markup:
            return text
        
        logger.info(f"[FORMAT-MD] Converting {len(markup)} entities to Markdown")
        
        md_map = {
            "strong": "**", "bold": "**",
            "emphasized": "*", "italic": "*", "em": "*",
            "underline": "++",
            "strikethrough": "~~", "strike": "~~",
            "code": "`",
        }
        
        corrected = FormattingEngine.correct_markup_offsets(text, markup)
        sorted_markup = sorted(corrected, key=lambda m: (m.get('from', 0), -m.get('length', 0)))
        
        # Вставка маркеров
        result = []
        last_pos = 0
        
        for entity in sorted_markup:
            offset = entity.get('from', 0)
            length = entity.get('length', 0)
            etype = entity.get('type', '')
            
            if etype in ('link', 'text_link', 'url'):
                url = entity.get('url', '')
                marker_open = '['
                marker_close = f']({url})'
            elif etype in md_map:
                marker_open = md_map[etype]
                marker_close = md_map[etype]
            else:
                continue
            
            result.append(text[last_pos:offset])
            result.append(marker_open)
            result.append(text[offset:offset+length])
            result.append(marker_close)
            last_pos = offset + length
        
        result.append(text[last_pos:])
        final = ''.join(result)
        logger.info(f"[FORMAT-MD] Output: '{final[:150]}...'")
        return final
    
    @staticmethod
    def build_payload_variants(text: str, markup: List[Dict]) -> List[Dict]:
        """
        Создаёт список вариантов payload для перебора.
        🔥 Возвращает все возможные комбинации!
        """
        logger.info(f"[FORMAT-VARIANTS] ========== BUILDING VARIANTS ==========")
        logger.info(f"[FORMAT-VARIANTS] text='{text[:100]}...'")
        logger.info(f"[FORMAT-VARIANTS] markup={len(markup) if markup else 0} entities")
        
        variants = []
        
        # Вариант 1: markup как entities
        if markup:
            corrected = FormattingEngine.correct_markup_offsets(text, markup)
            variants.append({
                "name": "markup_entities",
                "payload": {"text": text, "markup": corrected},
                "log": f"markup entities: {len(corrected)} items"
            })
        
        # Вариант 2: format: html + HTML теги
        if markup:
            html_text = FormattingEngine.markup_to_html(text, markup)
            variants.append({
                "name": "format_html",
                "payload": {"text": html_text, "format": "html"},
                "log": f"format=html, text='{html_text[:100]}...'"
            })
        
        # Вариант 3: format: markdown + Markdown
        if markup:
            md_text = FormattingEngine.markup_to_markdown(text, markup)
            variants.append({
                "name": "format_markdown",
                "payload": {"text": md_text, "format": "markdown"},
                "log": f"format=markdown, text='{md_text[:100]}...'"
            })
        
        # Вариант 4: Только текст (без форматирования) — всегда последний
        variants.append({
            "name": "plain_text",
            "payload": {"text": text},
            "log": "plain text, no formatting"
        })
        
        logger.info(f"[FORMAT-VARIANTS] Built {len(variants)} variants: {[v['name'] for v in variants]}")
        logger.info(f"[FORMAT-VARIANTS] ========== END VARIANTS ==========")
        
        return variants


# ===================================================================
# 🔐 AUTH MODULE
# ===================================================================
class AuthManager:
    def __init__(self, password: str, auth_file: Path, require_password: bool = True):
        self.password = password
        self.auth_file = auth_file
        self.require_password = require_password
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load_from_file()
        logger.info(f"[AUTH] 🔐 Initialized (require_password={require_password}, users={len(self.authorized)})")
    
    def _load_from_file(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
            except Exception:
                pass
    
    def _save_to_file(self):
        try:
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'users': {str(k): v for k, v in self.authorized.items()},
                    'failed': {str(k): v for k, v in self.failed_attempts.items()},
                    'updated_at': datetime.now().isoformat()
                }, f, indent=2)
        except Exception:
            pass
    
    def is_authorized(self, user_id: int) -> bool:
        if not self.require_password:
            return True
        return user_id in self.authorized
    
    def check_password(self, user_id: int, password: str) -> bool:
        if not self.require_password:
            return True
        if password == self.password:
            self.authorized[user_id] = {
                'auth_time': datetime.now().isoformat()
            }
            self.failed_attempts.pop(user_id, None)
            self._save_to_file()
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save_to_file()
        return False
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save_to_file()
    
    def change_password(self, new_password: str):
        self.password = new_password
        self.authorized.clear()
        self._save_to_file()
        logger.info(f"[AUTH] 🔑 Password changed")

# ===================================================================
# 🗄 STATE MODULE
# ===================================================================
class StateManager:
    # Шаги: photo → text → buttons → preview
    STEPS = ['post_waiting_photo', 'post_waiting_text', 'post_waiting_buttons', 'post_ready']
    
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
        logger.info(f"[STATE] 📍 User {user_id}: {old} → {step} | data_keys={list(session['data'].keys())}")
    
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
        logger.info(f"[STATE] 💾 Draft saved for {user_id} | keys={list(draft.keys())} | has_photo={bool(draft.get('attachments'))} | has_text={bool(draft.get('text'))} | has_buttons={bool(draft.get('buttons'))}")
    
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
        self.formatter = FormattingEngine()
        logger.info(f"[MAX] 📡 Client initialized | base_url={base_url}")
    
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
            "User-Agent": "MAX-Channel-Poster/7.0"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.info(f"[MAX] 📤 BODY: {json.dumps(data, ensure_ascii=False)[:800] if data else 'None'}")
        
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
                    logger.info(f"[MAX] 📥 RESPONSE: {text[:800]}")
                    
                    if response.status == 200:
                        try:
                            result = json.loads(text) if text.strip() else {}
                            # Проверяем наличие форматирования в ответе
                            resp_body = result.get('message', {}).get('body', {})
                            resp_markup = resp_body.get('markup')
                            resp_text = resp_body.get('text', '')
                            logger.info(f"[MAX] 📥 Response has markup: {resp_markup is not None}")
                            logger.info(f"[MAX] 📥 Response text: '{resp_text[:100]}...'")
                            return result
                        except json.JSONDecodeError:
                            return {"raw": text}
                    
                    if response.status == 400:
                        logger.warning(f"[MAX] ⚠️ Bad Request: {text[:300]}")
                        return {"error": "HTTP_400", "detail": text}
                    
                    if response.status == 429:
                        retry_after = int(response.headers.get('Retry-After', 30))
                        logger.warning(f"[MAX] ⏳ Rate limit, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    return {"error": f"HTTP_{response.status}", "detail": text}
                    
            except asyncio.TimeoutError:
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
    
    async def send_message_with_format_retry(self, chat_id, text, markup=None, 
                                             buttons=None, attachments=None) -> Dict:
        """
        Отправляет сообщение с перебором вариантов форматирования.
        🔥 Если markup не применился — пробует следующий вариант!
        """
        logger.info(f"[MAX-FORMAT] ========== FORMAT RETRY ==========")
        logger.info(f"[MAX-FORMAT] chat_id={chat_id}, text='{text[:80]}...', markup={len(markup) if markup else 0}")
        
        # Если нет markup — отправляем как есть
        if not markup:
            logger.info(f"[MAX-FORMAT] No markup, sending as plain text")
            return await self.send_message(chat_id, text, buttons=buttons, attachments=attachments)
        
        # Строим варианты
        variants = self.formatter.build_payload_variants(text, markup)
        
        # Перебираем варианты
        for idx, variant in enumerate(variants):
            logger.info(f"[MAX-FORMAT] 🔄 Trying variant {idx+1}/{len(variants)}: {variant['name']}")
            logger.info(f"[MAX-FORMAT] {variant['log']}")
            
            payload = variant['payload'].copy()
            
            # Добавляем кнопки и вложения
            all_attachments = []
            if attachments:
                all_attachments.extend(attachments)
            if buttons and len(buttons) > 0:
                all_attachments.append({
                    "type": "inline_keyboard",
                    "payload": {"buttons": buttons}
                })
            if all_attachments:
                payload['attachments'] = all_attachments
            
            logger.info(f"[MAX-FORMAT] Payload keys: {list(payload.keys())}")
            
            result = await self._request("POST", f"/messages?chat_id={chat_id}", data=payload)
            
            if "error" in result:
                logger.warning(f"[MAX-FORMAT] ❌ Variant {variant['name']} failed: {result.get('detail', '')[:200]}")
                continue
            
            # Проверяем, применилось ли форматирование
            resp_body = result.get('message', {}).get('body', {})
            resp_markup = resp_body.get('markup')
            resp_text = resp_body.get('text', '')
            
            if resp_markup:
                logger.info(f"[MAX-FORMAT] ✅ Variant {variant['name']} SUCCESS! Markup applied: {len(resp_markup)} entities")
                return result
            
            if variant['name'] == 'format_html' and '<' in resp_text and '>' in resp_text:
                logger.info(f"[MAX-FORMAT] ✅ Variant {variant['name']} SUCCESS! HTML tags in response")
                return result
            
            if variant['name'] == 'format_markdown' and ('**' in resp_text or '*' in resp_text):
                logger.info(f"[MAX-FORMAT] ✅ Variant {variant['name']} SUCCESS! Markdown in response")
                return result
            
            logger.info(f"[MAX-FORMAT] ⚠️ Variant {variant['name']} sent but no formatting detected in response, trying next...")
        
        # Если ни один не сработал — возвращаем последний результат
        logger.warning(f"[MAX-FORMAT] ❌ All variants tried, returning last result")
        return result if 'result' in dir() else {"error": "all_variants_failed"}
    
    async def send_message(self, chat_id, text, markup=None, buttons=None, attachments=None, 
                          skip_format_retry=False) -> Dict:
        """Отправляет сообщение (без перебора форматирования)"""
        logger.info(f"[MAX-SEND] ========== SENDING ==========")
        logger.info(f"[MAX-SEND] chat_id={chat_id}, text='{text[:80]}...', buttons={'YES' if buttons else 'NO'}, attachments={len(attachments) if attachments else 0}")
        
        payload = {"text": text}
        
        if markup:
            payload["markup"] = markup
        
        all_attachments = []
        if attachments:
            all_attachments.extend(attachments)
        if buttons and len(buttons) > 0:
            all_attachments.append({
                "type": "inline_keyboard",
                "payload": {"buttons": buttons}
            })
            logger.info(f"[MAX-SEND] 🔘 Adding keyboard: {len(buttons)} rows")
        if all_attachments:
            payload["attachments"] = all_attachments
        
        logger.info(f"[MAX-SEND] Final keys: {list(payload.keys())}")
        
        endpoint = f"/messages?chat_id={chat_id}"
        result = await self._request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[MAX-SEND] ❌ FAILED")
        else:
            logger.info(f"[MAX-SEND] ✅ SUCCESS")
        
        return result
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        body = {"url": webhook_url, "chat_id": chat_id, "update_types": ["message_created"]}
        result = await self._request("POST", "/subscriptions", data=body)
        return "error" not in result

# ===================================================================
# 🖼 MEDIA MANAGER
# ===================================================================
class MediaManager:
    def __init__(self, cache_dir: Path, max_items: int = 10):
        self.cache_dir = cache_dir
        self.max_items = max_items
    
    def parse_attachments(self, attachments: List[Dict]) -> List[Dict]:
        """Парсит вложения, сохраняя оригинальный payload"""
        logger.info(f"[MEDIA] 🔍 Parsing {len(attachments)} attachments")
        result = []
        
        for i, att in enumerate(attachments):
            if not isinstance(att, dict):
                continue
            
            att_type = att.get('type', '')
            payload = att.get('payload', {})
            
            if att_type in ('image', 'photo', 'video', 'audio', 'voice', 'document', 'file', 'share'):
                parsed = {
                    'type': att_type,
                    'payload': payload.copy(),
                    'url': payload.get('url', ''),
                    'filename': payload.get('filename', f'file_{i}'),
                    'index': i
                }
                result.append(parsed)
                logger.info(f"[MEDIA] [{i}] ✅ type={att_type}")
        
        logger.info(f"[MEDIA] ✅ Parsed {len(result)}/{len(attachments)} items")
        return result

# ===================================================================
# 📊 STATS MODULE
# ===================================================================
class StatsCollector:
    def __init__(self, stats_file: Path):
        self.stats_file = stats_file
        self.stats: Dict[str, Dict] = {}
        self._load()
    
    def _load(self):
        if self.stats_file.exists():
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f).get('messages', {})
            except Exception:
                pass
    
    def _save(self):
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
        self._save()
    
    def get_stats(self, message_id=None):
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
    
    def start(self):
        self.scheduler.start()
    
    def stop(self):
        self.scheduler.shutdown()
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        formats = ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]
        for fmt in formats:
            try:
                return datetime.strptime(dt_str.strip(), fmt)
            except ValueError:
                continue
        return None
    
    def schedule_post(self, user_id, draft, publish_at):
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            return None
        
        job_id = f"post_{user_id}_{int(time.time())}"
        
        async def job():
            await self.max_client.send_message_with_format_retry(
                chat_id=self.channel_id,
                text=draft.get('text', ''),
                markup=draft.get('markup'),
                buttons=draft.get('buttons'),
                attachments=draft.get('attachments')
            )
        
        trigger = DateTrigger(run_date=publish_time)
        self.scheduler.add_job(job, trigger=trigger, id=job_id, replace_existing=True)
        return job_id

# ===================================================================
# 🎮 COMMAND HANDLERS
# ===================================================================
class CommandHandlers:
    def __init__(self, auth, state, max_client, media_mgr, scheduler, stats, channel_id):
        self.auth = auth
        self.state = state
        self.max_client = max_client
        self.media_mgr = media_mgr
        self.scheduler = scheduler
        self.stats = stats
        self.channel_id = channel_id
    
    # ========== ВСПОМОГАТЕЛЬНЫЕ ==========
    
    def _help_text(self) -> str:
        return (
            "📝 /post — создать пост\n"
            "👁 /preview — предпросмотр\n"
            "📊 /stats — статистика\n"
            "⚙️ /settings — настройки\n"
            "❌ /cancel — сброс"
        )
    
    def parse_buttons(self, text: str) -> List[List[Dict]]:
        """Парсит URL-кнопки: Название | url"""
        logger.info(f"[BTN-PARSE] Input: '{text[:200]}...'")
        rows = []
        for line in text.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            for sep in [' | ', ' - ', ' → ']:
                if sep in line:
                    parts = line.split(sep, 1)
                    btn_text = parts[0].strip()
                    btn_url = parts[1].strip()
                    if btn_text and btn_url.startswith(('http://', 'https://')):
                        rows.append([{"type": "link", "text": btn_text, "url": btn_url}])
                        logger.info(f"[BTN-PARSE] ✅ '{btn_text}'")
                        break
        logger.info(f"[BTN-PARSE] Total: {len(rows)} rows")
        return rows
    
    # ========== СТАРТ ==========
    
    async def handle_start(self, user_id, chat_id, send_callback):
        logger.info(f"[CMD] /start user={user_id}")
        
        if self.auth.require_password and not self.auth.is_authorized(user_id):
            await send_callback("🔐 Введите пароль:")
            self.state.set_step(user_id, 'waiting_password')
            return
        
        self.state.clear_session(user_id)
        
        await send_callback(
            f"👋 MAX Channel Poster\n\n{self._help_text()}"
        )
    
    async def handle_password(self, user_id, password, send_callback):
        if self.auth.check_password(user_id, password):
            self.auth.reset_failed_attempts(user_id)
            session = self.state.get_session(user_id)
            chat_id = session.get('chat_id', user_id)
            await self.handle_start(user_id, chat_id, send_callback)
        else:
            attempts = self.auth.get_failed_attempts(user_id)
            remaining = 3 - attempts
            if remaining > 0:
                await send_callback(f"❌ Неверный пароль. Осталось: {remaining}")
            else:
                await send_callback("🔒 Слишком много попыток.")
    
    # ========== ШАГ 1: ФОТО ==========
    
    async def handle_post_command(self, user_id, send_callback):
        logger.info(f"[CMD] /post user={user_id}")
        
        if not self.auth.is_authorized(user_id):
            await send_callback("🔐 Сначала /start")
            return
        
        self.state.clear_session(user_id)
        self.state.set_step(user_id, 'post_waiting_photo')
        
        await send_callback(
            "📸 Шаг 1/3: Отправьте фото/видео\n\n"
            "Или:\n"
            "⏭ /skip — пропустить\n"
            "❌ /cancel — отмена"
        )
    
    async def handle_post_photo(self, user_id, raw_attachments, send_callback):
        logger.info(f"[CMD-PHOTO] Received {len(raw_attachments)} attachments")
        
        session = self.state.get_session_data(user_id)
        
        attachments = self.media_mgr.parse_attachments(raw_attachments)
        session['raw_attachments'] = raw_attachments
        session['attachments'] = attachments
        
        self.state.set_step(user_id, 'post_waiting_text')
        
        await send_callback(
            f"✅ Фото получено ({len(attachments)} шт.)\n\n"
            f"📝 Шаг 2/3: Напишите текст\n\n"
            f"⏭ /skip — пропустить\n"
            f"❌ /cancel — отмена"
        )
    
    # ========== ШАГ 2: ТЕКСТ ==========
    
    async def handle_post_text(self, user_id, text, markup, raw_attachments, send_callback):
        logger.info(f"[CMD-TEXT] ========== TEXT ==========")
        logger.info(f"[CMD-TEXT] text='{text[:100]}...'")
        logger.info(f"[CMD-TEXT] markup={len(markup) if markup else 0} entities")
        
        session = self.state.get_session_data(user_id)
        
        # Добавляем новые вложения если есть
        if raw_attachments:
            new_attachments = self.media_mgr.parse_attachments(raw_attachments)
            existing = session.get('attachments', [])
            session['attachments'] = existing + new_attachments
            session['raw_attachments'] = session.get('raw_attachments', []) + raw_attachments
        
        # Сохраняем текст и markup
        session['text'] = text
        session['markup'] = markup
        
        self.state.set_step(user_id, 'post_waiting_buttons')
        
        await send_callback(
            f"✅ Текст сохранён\n\n"
            f"🔘 Шаг 3/3: Добавьте URL-кнопки\n"
            f"Формат: Название | https://ссылка\n\n"
            f"⏭ /skip — пропустить\n"
            f"❌ /cancel — отмена"
        )
    
    # ========== ШАГ 3: КНОПКИ ==========
    
    async def handle_post_buttons(self, user_id, buttons_text, send_callback):
        logger.info(f"[CMD-BTN] ========== BUTTONS ==========")
        logger.info(f"[CMD-BTN] text='{buttons_text[:150]}...'")
        
        session = self.state.get_session_data(user_id)
        
        buttons = self.parse_buttons(buttons_text)
        session['buttons'] = buttons
        
        self.state.save_draft(user_id, session.copy())
        self.state.set_step(user_id, 'post_ready')
        
        # 🔥 Показываем единый предпросмотр
        await self.send_preview(user_id, send_callback, session)
    
    # ========== ПРЕДПРОСМОТР ==========
    
    async def send_preview(self, user_id, send_callback, draft=None):
        """Единый предпросмотр: фото + текст + кнопки в ОДНОМ сообщении"""
        logger.info(f"[PREVIEW] ========== SENDING PREVIEW ==========")
        
        if draft is None:
            draft = self.state.get_draft(user_id)
        
        if draft is None:
            await send_callback("❌ Нет черновика")
            return
        
        text = draft.get('text', '')
        markup = draft.get('markup', [])
        buttons = draft.get('buttons', [])
        attachments = draft.get('attachments', [])
        
        logger.info(f"[PREVIEW] text='{text[:50]}...', markup={len(markup)}, buttons={len(buttons)}, attachments={len(attachments)}")
        
        chat_id = self.state.get_session(user_id).get('chat_id', user_id)
        
        # Формируем caption с командами
        caption = text if text else ""
        caption += f"\n\n📝 /edit | 🚀 /publish | ❌ /cancel"
        
        # Отправляем ОДНО сообщение: фото + текст + кнопки
        await self.max_client.send_message_with_format_retry(
            chat_id=chat_id,
            text=caption if caption else "Предпросмотр",
            markup=markup,
            buttons=buttons,
            attachments=[{
                'type': att['type'],
                'payload': att['payload']
            } for att in attachments if att.get('payload')]
        )
        
        logger.info(f"[PREVIEW] ========== END PREVIEW ==========")
    
    async def handle_preview(self, user_id, send_callback):
        await self.send_preview(user_id, send_callback)
    
    # ========== РЕДАКТИРОВАНИЕ ==========
    
    async def handle_edit(self, user_id, send_callback):
        logger.info(f"[CMD-EDIT] /edit user={user_id}")
        
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send_callback("❌ Нет черновика. /post — новый пост")
            return
        
        # Показываем меню редактирования
        has_photo = bool(draft.get('attachments'))
        has_text = bool(draft.get('text'))
        has_buttons = bool(draft.get('buttons'))
        
        menu = ["✏️ Что редактируем?\n"]
        
        if has_photo:
            menu.append("🖼 /edit_photo — фото")
        if has_text:
            menu.append("📝 /edit_text — текст")
        if has_buttons:
            menu.append("🔘 /edit_buttons — кнопки")
        
        menu.append("\n👁 /preview — предпросмотр")
        menu.append("❌ /cancel — отмена")
        
        await send_callback('\n'.join(menu))
    
    async def handle_edit_photo(self, user_id, send_callback):
        self.state.set_step(user_id, 'post_waiting_photo')
        await send_callback("🖼 Отправьте новое фото или /skip /cancel")
    
    async def handle_edit_text(self, user_id, send_callback):
        self.state.set_step(user_id, 'post_waiting_text')
        await send_callback("📝 Напишите новый текст или /skip /cancel")
    
    async def handle_edit_buttons(self, user_id, send_callback):
        self.state.set_step(user_id, 'post_waiting_buttons')
        await send_callback("🔘 Введите новые кнопки или /skip /cancel")
    
    # ========== ПУБЛИКАЦИЯ ==========
    
    async def handle_publish(self, user_id, send_callback, immediate=True, schedule_time=None):
        logger.info(f"[CMD-PUBLISH] ========== PUBLISHING ==========")
        logger.info(f"[CMD-PUBLISH] immediate={immediate}")
        
        draft = self.state.get_draft(user_id)
        if draft is None:
            await send_callback("❌ Нет черновика")
            return
        
        logger.info(f"[CMD-PUBLISH] text='{draft.get('text', '')[:50]}...', markup={len(draft.get('markup', []))}, buttons={len(draft.get('buttons', []))}, attachments={len(draft.get('attachments', []))}")
        
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
        
        attachments = []
        for att in draft.get('raw_attachments', []):
            if isinstance(att, dict) and att.get('type'):
                attachments.append({'type': att['type'], 'payload': att.get('payload', {})})
        
        # 🔥 Используем перебор форматирования
        result = await self.max_client.send_message_with_format_retry(
            chat_id=self.channel_id,
            text=draft.get('text', ''),
            markup=draft.get('markup'),
            buttons=draft.get('buttons'),
            attachments=attachments if attachments else None
        )
        
        if "error" not in result:
            message_id = result.get('message', {}).get('body', {}).get('mid')
            if message_id:
                self.stats.record_message(message_id, self.channel_id, draft.get('text', ''), datetime.now().isoformat())
            
            self.state.clear_draft(user_id)
            self.state.clear_session(user_id)
            
            await send_callback(f"✅ Опубликовано! {self._help_text()}")
            logger.info(f"[CMD-PUBLISH] ✅ SUCCESS! msg_id={message_id}")
        else:
            error_detail = result.get('detail', 'неизвестная ошибка')
            await send_callback(f"❌ Ошибка: {error_detail[:200]}")
            logger.error(f"[CMD-PUBLISH] ❌ FAILED: {error_detail[:200]}")
    
    # ========== ОТМЕНА ==========
    
    async def handle_cancel(self, user_id, send_callback):
        logger.info(f"[CMD-CANCEL] /cancel user={user_id}")
        self.state.clear_draft(user_id)
        self.state.clear_session(user_id)
        await send_callback(f"🗑️ Сброшено.\n\n{self._help_text()}")
    
    # ========== ПРОЧЕЕ ==========
    
    async def handle_skip(self, user_id, send_callback):
        """Обрабатывает /skip на любом шаге"""
        step = self.state.get_step(user_id)
        logger.info(f"[CMD-SKIP] /skip at step={step}")
        
        if step == 'post_waiting_photo':
            self.state.set_step(user_id, 'post_waiting_text')
            await send_callback("📝 Шаг 2/3: Напишите текст\n\n⏭ /skip | ❌ /cancel")
        
        elif step == 'post_waiting_text':
            self.state.set_step(user_id, 'post_waiting_buttons')
            await send_callback("🔘 Шаг 3/3: Добавьте URL-кнопки\n\n⏭ /skip | ❌ /cancel")
        
        elif step == 'post_waiting_buttons':
            session = self.state.get_session_data(user_id)
            session['buttons'] = []
            self.state.save_draft(user_id, session.copy())
            self.state.set_step(user_id, 'post_ready')
            await self.send_preview(user_id, send_callback, session)
    
    async def handle_stats(self, user_id, send_callback):
        all_stats = self.stats.get_stats()
        if not all_stats:
            await send_callback("📊 Статистика пуста")
            return
        report = ["📊 Последние посты:\n"]
        for item in all_stats[-10:]:
            mid = item['message_id'][:12]
            report.append(f"• {mid}... | 👁 {item.get('views', 0)}")
        await send_callback('\n'.join(report))
    
    async def handle_settings(self, user_id, send_callback):
        await send_callback(
            "⚙️ Настройки\n\n"
            "/set_channel ID — канал\n"
            "/set_password pwd — пароль\n"
            "/list_admins — админы"
        )
    
    async def handle_set_channel(self, user_id, new_id, send_callback):
        await send_callback(f"✅ Канал: {new_id} (перезапустите бота)")
    
    async def handle_set_password(self, user_id, new_pwd, send_callback):
        self.auth.change_password(new_pwd)
        await send_callback("✅ Пароль изменён")
    
    async def handle_list_admins(self, user_id, send_callback):
        admins = self.auth.authorized
        if not admins:
            await send_callback("👥 Нет авторизованных")
            return
        report = ["👥 Админы:"]
        for uid, data in admins.items():
            report.append(f"• {uid} | {data.get('auth_time', '')[:16]}")
        await send_callback('\n'.join(report))

# ===================================================================
# 🌐 WEBHOOK
# ===================================================================
async def webhook_handler(request, handlers):
    logger.info(f"[WEBHOOK] 📨 {request.method}")
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

async def handle_incoming_message(msg, handlers):
    logger.info("=" * 80)
    logger.info("[MSG] 📨 Processing")
    
    rec = msg.get('recipient', {})
    sender = msg.get('sender', {})
    user_id = rec.get('user_id') or sender.get('user_id')
    chat_id = rec.get('chat_id')
    
    if not user_id:
        logger.error("[MSG] No user_id")
        return
    
    logger.info(f"[MSG] 👤 user={user_id} chat={chat_id}")
    
    handlers.state.get_session(user_id)['chat_id'] = chat_id
    
    async def send_callback(text, markup=None, buttons=None, attachments=None):
        logger.info(f"[SEND] '{text[:50]}...'")
        return await handlers.max_client.send_message_with_format_retry(
            chat_id=chat_id or user_id,
            text=text,
            markup=markup,
            buttons=buttons,
            attachments=attachments
        )
    
    body = msg.get('body', {}) if isinstance(msg.get('body'), dict) else {}
    text = body.get('text', '') or msg.get('text', '')
    markup = body.get('markup', []) or msg.get('markup', [])
    raw_attachments = body.get('attachments', []) or msg.get('attachments', [])
    
    logger.info(f"[MSG] text='{text[:100]}...', markup={len(markup)}, attachments={len(raw_attachments)}")
    
    step = handlers.state.get_step(user_id)
    logger.info(f"[MSG] step={step}")
    
    cmd = text.strip()
    
    # Роутинг
    if cmd == '/start':
        await handlers.handle_start(user_id, chat_id, send_callback)
    elif cmd == '/post':
        await handlers.handle_post_command(user_id, send_callback)
    elif cmd == '/skip':
        await handlers.handle_skip(user_id, send_callback)
    elif cmd == '/preview':
        await handlers.handle_preview(user_id, send_callback)
    elif cmd == '/edit':
        await handlers.handle_edit(user_id, send_callback)
    elif cmd == '/edit_photo':
        await handlers.handle_edit_photo(user_id, send_callback)
    elif cmd == '/edit_text':
        await handlers.handle_edit_text(user_id, send_callback)
    elif cmd == '/edit_buttons':
        await handlers.handle_edit_buttons(user_id, send_callback)
    elif cmd == '/publish':
        await handlers.handle_publish(user_id, send_callback)
    elif cmd.startswith('/schedule '):
        await handlers.handle_publish(user_id, send_callback, immediate=False, schedule_time=cmd.replace('/schedule ', ''))
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
    elif step == 'post_waiting_photo':
        if raw_attachments:
            await handlers.handle_post_photo(user_id, raw_attachments, send_callback)
        else:
            await send_callback("📸 Отправьте фото или /skip")
    elif step == 'post_waiting_text':
        await handlers.handle_post_text(user_id, text, markup, raw_attachments, send_callback)
    elif step == 'post_waiting_buttons':
        await handlers.handle_post_buttons(user_id, text, send_callback)
    elif step == 'post_ready':
        await handlers.handle_edit_text(user_id, text, markup, raw_attachments, send_callback)
    else:
        if handlers.auth.is_authorized(user_id):
            await send_callback(handlers._help_text())
        else:
            await send_callback("🔐 /start")
    
    logger.info("=" * 80)

# ===================================================================
# 🌐 SERVER
# ===================================================================
async def health(request):
    return web.json_response({"ok": True, "version": "7.0"})

async def root(request):
    return web.json_response({"bot": "MAX Channel Poster", "version": "7.0"})

async def on_startup(app):
    logger.info("🚀" * 40)
    logger.info("🚀 STARTING v7.0 — FULL REWORK")
    logger.info("🚀" * 40)
    
    app['auth'] = AuthManager(BOT_PASSWORD, AUTH_FILE, REQUIRE_PASSWORD)
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
    
    logger.info("✅ Ready!")

async def on_cleanup(app):
    logger.info("🔚 Shutting down...")
    if 'scheduler' in app:
        app['scheduler'].stop()
    if 'max_client' in app:
        await app['max_client'].close()

def create_app():
    app = web.Application()
    app.router.add_get('/', root)
    app.router.add_get('/health', health)
    app.router.add_post('/webhook', lambda req: webhook_handler(req, app['handlers']))
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    return app

if __name__ == '__main__':
    port = int(os.getenv('PORT', 10000))
    logger.info(f"🌐 Port {port}")
    web.run_app(create_app(), host='0.0.0.0', port=port, access_log=None)
