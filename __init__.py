"""
Управление шаблонами слов-ссылок и кнопок
"""
import json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from core.logger import get_logger

logger = get_logger(__name__)

INLINE_TEMPLATES_FILE = Path('/tmp/max-bot/inline_templates.json')
BUTTON_TEMPLATES_FILE = Path('/tmp/max-bot/button_templates.json')


def _load(file_path: Path) -> Dict:
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(file_path: Path, data: Dict):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def parse_name_url(text: str) -> Tuple[Optional[str], Optional[str]]:
    separators = [' | ', ' - ', ' — ', ' → ', '\t', ' |', '| ', ' -', '- ', ' —', '— ', ' →', '→ ']
    for sep in separators:
        if sep in text:
            parts = text.split(sep, 1)
            name = parts[0].strip()
            url = parts[1].strip()
            if url.startswith(('http://', 'https://')):
                return name, url
    words = text.split()
    for word in words:
        if word.startswith(('http://', 'https://')):
            return text.replace(word, '').strip(), word
    return None, None


# === INLINE ===

def load_inline_templates(user_id: int) -> List[Dict]:
    return _load(INLINE_TEMPLATES_FILE).get(str(user_id), {}).get('templates', [])


def save_inline_template(user_id: int, text: str, url: str):
    data = _load(INLINE_TEMPLATES_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {'templates': []}
    data[uid]['templates'].append({"text": text, "url": url})
    _save(INLINE_TEMPLATES_FILE, data)


def delete_inline_template(user_id: int, index: int) -> bool:
    data = _load(INLINE_TEMPLATES_FILE)
    uid = str(user_id)
    if uid in data and 0 <= index < len(data[uid]['templates']):
        data[uid]['templates'].pop(index)
        _save(INLINE_TEMPLATES_FILE, data)
        return True
    return False


def find_duplicate_inline(user_id: int, url: str) -> Optional[Dict]:
    for t in load_inline_templates(user_id):
        if t['url'] == url:
            return t
    return None


# === BUTTONS ===

def load_button_templates(user_id: int) -> List[Dict]:
    return _load(BUTTON_TEMPLATES_FILE).get(str(user_id), {}).get('templates', [])


def save_button_template(user_id: int, text: str, url: str):
    data = _load(BUTTON_TEMPLATES_FILE)
    uid = str(user_id)
    if uid not in data:
        data[uid] = {'templates': []}
    data[uid]['templates'].append({"type": "link", "text": text, "url": url})
    _save(BUTTON_TEMPLATES_FILE, data)


def delete_button_template(user_id: int, index: int) -> bool:
    data = _load(BUTTON_TEMPLATES_FILE)
    uid = str(user_id)
    if uid in data and 0 <= index < len(data[uid]['templates']):
        data[uid]['templates'].pop(index)
        _save(BUTTON_TEMPLATES_FILE, data)
        return True
    return False


def find_duplicate_button(user_id: int, url: str) -> Optional[Dict]:
    for t in load_button_templates(user_id):
        if t['url'] == url:
            return t
    return None


# === МЕНЮ ===

async def handle_templates_menu(send):
    await send(
        "<b>📋 Управление шаблонами</b>\n\n"
        "<b>🔗 Слова-ссылки:</b>\n"
        "➕ /inline_add — добавить\n"
        "📋 /inline_list — список\n"
        "🗑 /inline_del N — удалить\n\n"
        "<b>🔘 Кнопки под постом:</b>\n"
        "➕ /btn_add — добавить\n"
        "📋 /btn_list — список\n"
        "🗑 /btn_del N — удалить\n\n"
        "─────────────────\n"
        "📝 /post | 🏠 /start"
    )


# === ДОБАВЛЕНИЕ ===

async def handle_inline_add_start(user_id, send, state):
    state.set_step(user_id, 'inline_add_name')
    await send(
        "<b>➕ Новые слова-ссылки</b>\n\n"
        "Отправьте названия и ссылки:\n"
        "<code>Название | https://url</code>\n\n"
        "Разделители: <code>|</code> <code>-</code> <code>—</code> <code>→</code>\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_inline_add_name(user_id, text, send, state):
    added, duplicates, errors = [], [], []
    
    for line in text.strip().split('\n'):
        if not line.strip():
            continue
        name, url = parse_name_url(line)
        if not name or not url:
            errors.append(line[:50])
            continue
        dup = find_duplicate_inline(user_id, url)
        if dup:
            duplicates.append((name, url, dup['text']))
            continue
        save_inline_template(user_id, name, url)
        added.append((name, url))
    
    state.set_step(user_id, None)
    
    # Сначала дубликаты — отдельным сообщением
    if duplicates:
        dup_lines = [f"<b>⚠️ Уже есть ({len(duplicates)}):</b>"]
        for name, _, existing in duplicates:
            dup_lines.append(f"• {name} → уже «{existing}»")
        dup_lines.append("\n❌ Не добавлено.")
        dup_lines.append("\n─────────────────")
        dup_lines.append("➕ /inline_add | 📋 /inline_list")
        dup_lines.append("🔙 /templates | 🏠 /start")
        await send('\n'.join(dup_lines))
    
    # Потом добавленное + предпросмотр
    if added or errors:
        response = []
        
        if added:
            response.append(f"<b>✅ Добавлено ({len(added)}):</b>")
            for name, _ in added:
                response.append(f"• {name}")
        
        if errors:
            response.append(f"\n<b>❌ Не распознано ({len(errors)}):</b>")
            for e in errors:
                response.append(f"• {e}")
        
        templates = load_inline_templates(user_id)
        if templates:
            response.append(f"\n<b>👁 Предпросмотр:</b>")
            response.append("🔗 Полезные ссылки:")
            for t in templates:
                response.append(f"• <a href=\"{t['url']}\">{t['text']}</a>")
        
        response.append("\n─────────────────")
        response.append("➕ /inline_add | 📋 /inline_list")
        response.append("🔙 /templates | 🏠 /start")
        await send('\n'.join(response))
    
    if not added and not errors and not duplicates:
        await send(
            "❌ Ничего не добавлено.\n\n"
            "─────────────────\n"
            "➕ /inline_add | 🔙 /templates | 🏠 /start"
        )


async def handle_btn_add_start(user_id, send, state):
    state.set_step(user_id, 'btn_add_name')
    await send(
        "<b>➕ Новые кнопки</b>\n\n"
        "Отправьте названия и ссылки:\n"
        "<code>Название | https://url</code>\n\n"
        "Разделители: <code>|</code> <code>-</code> <code>—</code> <code>→</code>\n\n"
        "─────────────────\n"
        "❌ /cancel — отмена"
    )


async def handle_btn_add_name(user_id, text, send, state, max_client=None):
    added, duplicates, errors = [], [], []
    
    for line in text.strip().split('\n'):
        if not line.strip():
            continue
        name, url = parse_name_url(line)
        if not name or not url:
            errors.append(line[:50])
            continue
        dup = find_duplicate_button(user_id, url)
        if dup:
            duplicates.append((name, url, dup['text']))
            continue
        save_button_template(user_id, name, url)
        added.append((name, url))
    
    state.set_step(user_id, None)
    
    # Сначала дубликаты — отдельным сообщением
    if duplicates:
        dup_lines = [f"<b>⚠️ Уже есть ({len(duplicates)}):</b>"]
        for name, _, existing in duplicates:
            dup_lines.append(f"• {name} → уже «{existing}»")
        dup_lines.append("\n❌ Не добавлено.")
        dup_lines.append("\n─────────────────")
        dup_lines.append("➕ /btn_add | 📋 /btn_list")
        dup_lines.append("🔙 /templates | 🏠 /start")
        await send('\n'.join(dup_lines))
    
    # Потом добавленное + предпросмотр кнопками В ОДНОМ СООБЩЕНИИ
    if added or errors:
        response = []
        
        if added:
            response.append(f"<b>✅ Добавлено ({len(added)}):</b>")
            for name, _ in added:
                response.append(f"• {name}")
        
        if errors:
            response.append(f"\n<b>❌ Не распознано ({len(errors)}):</b>")
            for e in errors:
                response.append(f"• {e}")
        
        templates = load_button_templates(user_id)
        
        if templates:
            response.append(f"\n<b>👁 Предпросмотр кнопок:</b>")
            
            # ОДНО сообщение: текст + кнопки приклеены
            await send(
                '\n'.join(response),
                buttons=[[t] for t in templates]
            )
        else:
            await send('\n'.join(response))
        
        # Меню отдельно
        await send(
            "─────────────────\n"
            "➕ /btn_add | 📋 /btn_list\n"
            "🔙 /templates | 🏠 /start"
        )
    
    if not added and not errors and not duplicates:
        await send(
            "❌ Ничего не добавлено.\n\n"
            "─────────────────\n"
            "➕ /btn_add | 🔙 /templates | 🏠 /start"
        )


# === ПРОСМОТР И УДАЛЕНИЕ ===

async def handle_inline_list(user_id, send):
    templates = load_inline_templates(user_id)
    if not templates:
        await send("📋 Список пуст\n\n─────────────────\n➕ /inline_add | 🔙 /templates | 🏠 /start")
        return
    
    lines = ["<b>📋 Слова-ссылки:</b>\n"]
    for i, t in enumerate(templates, 1):
        lines.append(f"{i}. {t['text']}")
    lines.append(f"\n<b>👁 Предпросмотр:</b>\n🔗 Полезные ссылки:")
    for t in templates:
        lines.append(f"• <a href=\"{t['url']}\">{t['text']}</a>")
    lines.append("\n─────────────────")
    lines.append("➕ /inline_add | 🗑 /inline_del N")
    lines.append("🔙 /templates | 🏠 /start")
    await send('\n'.join(lines))


async def handle_inline_del(user_id, index_str, send):
    try:
        index = int(index_str) - 1
        if delete_inline_template(user_id, index):
            templates = load_inline_templates(user_id)
            lines = [f"<b>✅ Удалён #{index + 1}</b>\n"]
            if templates:
                lines.append("<b>📋 Остались:</b>")
                for i, t in enumerate(templates, 1):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("📋 Список пуст")
            lines.append("\n─────────────────")
            lines.append("➕ /inline_add | 📋 /inline_list")
            lines.append("🔙 /templates | 🏠 /start")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер")
    except ValueError:
        await send("❌ Укажите номер: /inline_del 1")


async def handle_btn_list(user_id, send, max_client=None):
    templates = load_button_templates(user_id)
    if not templates:
        await send("📋 Список пуст\n\n─────────────────\n➕ /btn_add | 🔙 /templates | 🏠 /start")
        return
    
    lines = ["<b>🔘 Кнопки:</b>\n"]
    for i, t in enumerate(templates, 1):
        lines.append(f"{i}. {t['text']}")
    lines.append("\n─────────────────")
    lines.append("➕ /btn_add | 🗑 /btn_del N")
    lines.append("🔙 /templates | 🏠 /start")
    await send('\n'.join(lines))


async def handle_btn_del(user_id, index_str, send):
    try:
        index = int(index_str) - 1
        if delete_button_template(user_id, index):
            templates = load_button_templates(user_id)
            lines = [f"<b>✅ Удалён #{index + 1}</b>\n"]
            if templates:
                lines.append("<b>🔘 Остались:</b>")
                for i, t in enumerate(templates, 1):
                    lines.append(f"{i}. {t['text']}")
            else:
                lines.append("🔘 Список пуст")
            lines.append("\n─────────────────")
            lines.append("➕ /btn_add | 📋 /btn_list")
            lines.append("🔙 /templates | 🏠 /start")
            await send('\n'.join(lines))
        else:
            await send("❌ Неверный номер")
    except ValueError:
        await send("❌ Укажите номер: /btn_del 1")


# === ИСПОЛЬЗОВАНИЕ ===

async def handle_btn_use(user_id, send, state, max_client=None):
    templates = load_button_templates(user_id)
    
    if not templates:
        await send(
            "❌ Нет сохранённых кнопок\n\n"
            "Введите вручную: <code>Название | https://url</code>\n\n"
            "─────────────────\n"
            "⏭ /skip | ❌ /cancel"
        )
        return
    
    chat_id = state.get_session(user_id).get('chat_id', user_id)
    if max_client:
        await max_client.send_message(
            chat_id=chat_id,
            text="<b>👁 Предпросмотр кнопок:</b>",
            buttons=[[t] for t in templates],
            use_html_format=True
        )
    
    await send(
        "─────────────────\n"
        "✅ /btn_yes — добавить\n"
        "❌ /skip — пропустить"
    )
    
    state.set_step(user_id, 'post_waiting_buttons_confirm', {'pending_buttons': templates})


async def handle_btn_confirm(user_id, send, state, max_client=None):
    session = state.get_session_data(user_id)
    templates = session.get('pending_buttons', [])
    
    if not templates:
        await send("❌ Нет данных")
        state.set_step(user_id, 'post_waiting_buttons')
        return
    
    session['buttons'] = [[t] for t in templates]
    session.pop('pending_buttons', None)
    state.save_draft(user_id, session.copy())
    state.set_step(user_id, 'post_ready')
    
    from handlers.preview import send_preview
    await send_preview(user_id, send, state, max_client)
