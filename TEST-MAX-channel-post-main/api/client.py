"""
MAX API клиент
"""
import json
import time
from typing import Optional, List, Dict, Union
from aiohttp import ClientSession, ClientTimeout
from core.logger import get_logger

logger = get_logger(__name__)


class MAXClient:
    def __init__(self, token: str, base_url: str, timeout: int = 120):
        self.token = token
        self.base_url = base_url
        self.timeout = ClientTimeout(total=timeout, connect=10, sock_read=timeout)
        self.session: Optional[ClientSession] = None
        self.request_count = 0
        logger.info(f"[MAX] Client initialized base={base_url}")
    
    async def init(self):
        if self.session is None:
            self.session = ClientSession(timeout=self.timeout)
            logger.info("[MAX] Session created")
    
    async def close(self):
        if self.session is not None:
            await self.session.close()
            logger.info("[MAX] Session closed")
    
    async def _request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict:
        await self.init()
        
        headers = {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "User-Agent": "MAX-Channel-Poster/7.1"
        }
        
        url = f"{self.base_url}{endpoint}"
        self.request_count += 1
        
        logger.info(f"[MAX] ▶️ #{self.request_count} {method} {url}")
        logger.info(f"[MAX] 📤 {json.dumps(data, ensure_ascii=False)[:400] if data else 'None'}")
        
        try:
            start = time.time()
            async with self.session.request(method=method, url=url, headers=headers, json=data, timeout=self.timeout) as resp:
                elapsed = time.time() - start
                text = await resp.text()
                logger.info(f"[MAX] ◀️ #{self.request_count}: {resp.status} in {elapsed:.2f}s")
                logger.info(f"[MAX] 📥 {text[:400]}")
                
                if resp.status == 200:
                    return json.loads(text) if text.strip() else {}
                
                logger.error(f"[MAX] ❌ HTTP {resp.status}: {text[:200]}")
                return {"error": f"HTTP_{resp.status}", "detail": text}
        except Exception as e:
            logger.error(f"[MAX] 💥 {e}")
            return {"error": "exception", "detail": str(e)}
    
    async def send_message(self, chat_id: Union[str, int], text: str,
                          buttons: Optional[List[List[Dict]]] = None,
                          attachments: Optional[List[Dict]] = None,
                          use_html_format: bool = False) -> Dict:
        logger.info(f"[MAX-SEND] chat={chat_id} text='{text[:50]}...' btns={'YES' if buttons else 'NO'} html={use_html_format}")
        
        payload = {"text": text}
        
        if use_html_format:
            payload["format"] = "html"
        
        all_attachments = []
        if attachments:
            all_attachments.extend(attachments)
        if buttons and len(buttons) > 0:
            all_attachments.append({"type": "inline_keyboard", "payload": {"buttons": buttons}})
            logger.info(f"[MAX-SEND] 🔘 {len(buttons)} rows")
        
        if all_attachments:
            payload["attachments"] = all_attachments
        
        endpoint = f"/messages?chat_id={chat_id}"
        result = await self._request("POST", endpoint, data=payload)
        
        if "error" in result:
            logger.error(f"[MAX-SEND] ❌ {result.get('detail', '')[:100]}")
        else:
            logger.info(f"[MAX-SEND] ✅")
        
        return result
    
    async def register_webhook(self, webhook_url: str, chat_id: str) -> bool:
        body = {"url": webhook_url, "chat_id": chat_id, "update_types": ["message_created"]}
        result = await self._request("POST", "/subscriptions", data=body)
        success = "error" not in result
        logger.info(f"[MAX] Webhook {'✅' if success else '❌'}")
        return success
