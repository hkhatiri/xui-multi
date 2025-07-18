import reflex as rx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from .celery_app import celery_app
from .models import ManagedService, Panel, PanelConfig
from .xui_client import XUIClient

@celery_app.task
def sync_usage_task():
    """این وظیفه در پس‌زمینه مصرف را سینک می‌کند."""
    print(f"[{datetime.now()}] --- Running sync job ---")
    # ... (منطق کامل تابع sync_and_enforce_limits که قبلاً داشتیم)
    config = rx.config.get_config()
    engine = create_engine(config.db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with SessionLocal() as session:
        # ... (کد کامل سینک کردن)
        pass
    print(f"[{datetime.now()}] --- Sync job finished ---")