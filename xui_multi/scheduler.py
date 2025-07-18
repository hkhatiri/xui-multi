import reflex as rx
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# ایمپورت کردن مدل‌ها و کلاینت
from xui_multi.models import ManagedService, Panel, PanelConfig
from xui_multi.xui_client import XUIClient

def sync_and_enforce_limits():
    """
    تابع اصلی که به صورت دوره‌ای اجرا می‌شود.
    """
    print(f"[{datetime.now()}] --- Running sync job ---")
    
    # --- بخش اصلاح شده برای اتصال به دیتابیس ---
    config = rx.config.get_config()
    engine = create_engine(config.db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    # --- پایان بخش اصلاح شده ---

    with SessionLocal() as session:
        # 1. تمام سرویس‌های فعال را پیدا کن
        active_services = session.query(ManagedService).filter(ManagedService.status == "active").all()
        
        for service in active_services:
            print(f"Checking service: {service.name} (UUID: {service.uuid})")
            
            total_usage_bytes = 0
            all_configs_on_panels = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()

            # 2. جمع‌آوری مصرف از تمام پنل‌ها
            for p_config in all_configs_on_panels:
                panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                try:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    inbound_data = client.get_inbound(p_config.panel_inbound_id)
                    if inbound_data:
                        total_usage_bytes += inbound_data.get("up", 0) + inbound_data.get("down", 0)
                except Exception as e:
                    print(f"  - Could not sync from panel {panel.url}: {e}")
            
            # 3. آپدیت مصرف در دیتابیس
            service.data_used_gb = total_usage_bytes / (1024**3)
            
            # 4. بررسی محدودیت‌ها
            limit_reached = service.data_used_gb >= service.data_limit_gb
            time_expired = datetime.now() >= service.end_date
            
            if limit_reached or time_expired:
                reason = "limit_reached" if limit_reached else "expired"
                print(f"  - Deactivating service {service.name} due to: {reason}")
                service.status = reason
                
                # 5. حذف inbound ها از تمام پنل‌ها
                for p_config in all_configs_on_panels:
                    panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                    try:
                        client = XUIClient(panel.url, panel.username, panel.password)
                        client.delete_inbound(p_config.panel_inbound_id)
                        print(f"  - Deleted inbound {p_config.panel_inbound_id} from panel {panel.url}")
                    except Exception as e:
                        print(f"  - FAILED to delete inbound {p_config.panel_inbound_id} from {panel.url}: {e}")
            
            session.commit()
    print(f"[{datetime.now()}] --- Sync job finished ---")

if __name__ == "__main__":
    scheduler = BlockingScheduler()
    scheduler.add_job(sync_and_enforce_limits, 'interval', minutes=2)
    
    print("Scheduler started. Syncing every 2 minutes. Press Ctrl+C to exit.")
    sync_and_enforce_limits()
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass