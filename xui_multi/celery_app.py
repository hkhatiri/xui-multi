from celery import Celery
from celery.schedules import crontab

# آدرس سرور Redis با استفاده از IP مستقیم
REDIS_URL = "redis://127.0.0.1:6379/0"

# ساخت اپلیکیشن Celery
celery_app = Celery(
    "xui_multi",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["xui_multi.tasks"]
)

# تنظیمات Celery Beat برای اجرای دوره‌ای
celery_app.conf.beat_schedule = {
    'sync-every-2-minutes': {
        'task': 'xui_multi.tasks.sync_usage_task',
        'schedule': crontab(minute='*/2'),
    },
}