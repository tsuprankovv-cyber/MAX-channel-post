"""
Менеджер авторизации
"""
import json
from datetime import datetime
from typing import Dict
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)


class AuthManager:
    def __init__(self, password: str, auth_file: Path, require_password: bool = True):
        self.password = password
        self.auth_file = auth_file
        self.require_password = require_password
        self.authorized: Dict[int, Dict] = {}
        self.failed_attempts: Dict[int, int] = {}
        self._load()
        logger.info(f"[AUTH] require_password={require_password} users={len(self.authorized)}")
    
    def _load(self):
        if self.auth_file.exists():
            try:
                with open(self.auth_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.authorized = {int(k): v for k, v in data.get('users', {}).items()}
                    self.failed_attempts = {int(k): v for k, v in data.get('failed', {}).items()}
            except Exception:
                pass
    
    def _save(self):
        try:
            with open(self.auth_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'users': {str(k): v for k, v in self.authorized.items()},
                    'failed': {str(k): v for k, v in self.failed_attempts.items()},
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
            self.authorized[user_id] = {'auth_time': datetime.now().isoformat()}
            self.failed_attempts.pop(user_id, None)
            self._save()
            logger.info(f"[AUTH] ✅ user={user_id}")
            return True
        self.failed_attempts[user_id] = self.failed_attempts.get(user_id, 0) + 1
        self._save()
        logger.warning(f"[AUTH] ❌ user={user_id} attempt={self.failed_attempts[user_id]}")
        return False
    
    def get_failed_attempts(self, user_id: int) -> int:
        return self.failed_attempts.get(user_id, 0)
    
    def reset_failed_attempts(self, user_id: int):
        if user_id in self.failed_attempts:
            del self.failed_attempts[user_id]
            self._save()
            logger.info(f"[AUTH] 🔄 reset user={user_id}")
    
    def change_password(self, new_password: str):
        self.password = new_password
        self.authorized.clear()
        self._save()
        logger.info("[AUTH] 🔑 Password changed")
