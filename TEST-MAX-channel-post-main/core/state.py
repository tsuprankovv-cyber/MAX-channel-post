"""
Менеджер состояний и черновиков
"""
from datetime import datetime
from typing import Dict, Optional
from core.logger import get_logger

logger = get_logger(__name__)


class StateManager:
    STEPS = [
        'post_waiting_photo',
        'post_waiting_text',
        'post_waiting_inline',
        'post_waiting_inline_confirm',
        'post_waiting_buttons',
        'post_waiting_buttons_confirm',
        'post_ready',
        # Шаги добавления шаблонов
        'inline_add_name',
        'btn_add_name',
    ]
    
    def __init__(self):
        self.sessions: Dict[int, Dict] = {}
        self.drafts: Dict[int, Dict] = {}
        logger.info("[STATE] Initialized")
    
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
        logger.info(f"[STATE] user={user_id} {old} → {step}")
    
    def get_step(self, user_id: int) -> Optional[str]:
        return self.sessions.get(user_id, {}).get('step')
    
    def get_session_data(self, user_id: int) -> Dict:
        return self.sessions.get(user_id, {}).get('data', {})
    
    def clear_session(self, user_id: int):
        if user_id in self.sessions:
            del self.sessions[user_id]
            logger.info(f"[STATE] 🧹 session user={user_id}")
    
    def save_draft(self, user_id: int, draft: Dict):
        draft['saved_at'] = datetime.now().isoformat()
        self.drafts[user_id] = draft
        logger.info(f"[STATE] 💾 draft user={user_id} photo={bool(draft.get('attachments'))} text={bool(draft.get('text'))} inline={bool(draft.get('inline_links'))} buttons={bool(draft.get('buttons'))}")
    
    def get_draft(self, user_id: int) -> Optional[Dict]:
        return self.drafts.get(user_id)
    
    def clear_draft(self, user_id: int):
        if user_id in self.drafts:
            del self.drafts[user_id]
            logger.info(f"[STATE] 🗑️ draft user={user_id}")
