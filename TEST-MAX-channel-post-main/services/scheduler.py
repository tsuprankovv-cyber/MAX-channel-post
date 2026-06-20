"""
Планировщик отложенных публикаций
"""
from datetime import datetime
from typing import Optional, Dict
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from core.logger import get_logger

logger = get_logger(__name__)


class PublishScheduler:
    def __init__(self, max_client, channel_id: str, timezone: str = 'UTC'):
        self.max_client = max_client
        self.channel_id = channel_id
        self.scheduler = AsyncIOScheduler(timezone=timezone)
        logger.info(f"[SCHEDULER] Initialized tz={timezone}")
    
    def start(self):
        self.scheduler.start()
        logger.info("[SCHEDULER] Started")
    
    def stop(self):
        self.scheduler.shutdown()
        logger.info("[SCHEDULER] Stopped")
    
    def parse_datetime(self, dt_str: str) -> Optional[datetime]:
        for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M"]:
            try:
                result = datetime.strptime(dt_str.strip(), fmt)
                logger.info(f"[SCHEDULER] Parsed '{dt_str}' as {fmt}")
                return result
            except ValueError:
                continue
        logger.error(f"[SCHEDULER] Failed to parse '{dt_str}'")
        return None
    
    def schedule_post(self, user_id: int, draft: Dict, publish_at: str) -> Optional[str]:
        publish_time = self.parse_datetime(publish_at)
        if publish_time is None or publish_time <= datetime.now():
            return None
        
        job_id = f"post_{user_id}_{int(datetime.now().timestamp())}"
        
        async def job():
            logger.info(f"[SCHEDULER] 🎯 Executing {job_id}")
            await self.max_client.send_message(
                chat_id=self.channel_id,
                text=draft.get('text', ''),
                buttons=draft.get('buttons'),
                attachments=draft.get('attachments'),
                use_html_format=True
            )
        
        self.scheduler.add_job(job, DateTrigger(run_date=publish_time), id=job_id, replace_existing=True)
        logger.info(f"[SCHEDULER] ✅ {job_id} at {publish_time}")
        return job_id
