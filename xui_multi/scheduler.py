import os
import sys
import time
from datetime import datetime

project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.append(project_root)

from xui_multi.models import ManagedService, PanelConfig, Panel
from xui_multi.xui_client import XUIClient
import reflex as rx

def check_and_update_services():
    """سرویس‌ها را بررسی کرده، حجم را آپدیت و در صورت نیاز آن‌ها را غیرفعال می‌کند."""
    print(f"[{datetime.now()}] --- Scheduler started ---")
    
    with rx.session() as session:
        # فقط سرویس‌های فعال را بررسی می‌کنیم
        active_services = session.query(ManagedService).filter(ManagedService.status == "active").all()
        
        print(f"Found {len(active_services)} active services to check.")

        for service in active_services:
            total_traffic_gb = 0
            is_still_active = True
            
            # گرفتن تمام کانفیگ‌های این سرویس
            service_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            
            # ۱. جمع‌آوری حجم مصرفی از تمام پنل‌ها
            for config in service_configs:
                try:
                    panel = session.query(Panel).filter(Panel.id == config.panel_id).one()
                    client = XUIClient(panel.url, panel.username, panel.password)
                    
                    # گرفتن حجم مصرفی این کانفیگ خاص
                    traffic_gb = client.get_inbound_traffic_gb(config.panel_inbound_id)
                    total_traffic_gb += traffic_gb
                    print(f"  - Traffic for inbound {config.panel_inbound_id} on panel {panel.url}: {traffic_gb:.3f} GB")
                
                except Exception as e:
                    print(f"  - WARNING: Could not get traffic for inbound ID {config.panel_inbound_id}. Error: {e}")
            
            # ۲. آپدیت حجم مصرفی در دیتابیس
            service.data_used_gb = total_traffic_gb
            print(f"  -> Total traffic for service '{service.name}' is {total_traffic_gb:.3f} GB.")
            
            # ۳. بررسی شرایط برای غیرفعال کردن سرویس
            should_disable = False
            reason = ""

            # شرط ۱: تاریخ انقضا
            if datetime.now() > service.end_date:
                should_disable = True
                reason = "expired"

            # شرط ۲: حجم مصرفی
            elif service.data_used_gb >= service.data_limit_gb:
                should_disable = True
                reason = "limit_reached"

            # ۴. اگر یکی از شرایط برقرار بود، سرویس را غیرفعال کن
            if should_disable:
                print(f"Disabling service '{service.name}' (UUID: {service.uuid}) due to: {reason}")
                
                for config in service_configs:
                    try:
                        panel = session.query(Panel).filter(Panel.id == config.panel_id).one()
                        client = XUIClient(panel.url, panel.username, panel.password)
                        client.disable_inbound(config.panel_inbound_id)
                        print(f"  - Successfully disabled inbound ID {config.panel_inbound_id} on panel {panel.url}")
                    
                    except Exception as e:
                        print(f"  - FAILED to disable inbound ID {config.panel_inbound_id} on panel {panel.url}. Error: {e}")

                # آپدیت نهایی وضعیت سرویس در دیتابیس
                service.status = reason
                print(f"Service '{service.name}' status updated to '{reason}' in the database.")
            
            # ذخیره تغییرات (حجم آپدیت شده و وضعیت جدید در صورت غیرفعال شدن)
            session.add(service)
            session.commit()

    print(f"[{datetime.now()}] --- Scheduler finished ---")


if __name__ == "__main__":
    run_interval_seconds = 60  # اجرای هر ۶۰ ثانیه یک بار
    while True:
        try:
            check_and_update_services()
        except Exception as e:
            import traceback
            print(f"A critical error occurred in the scheduler main loop: {e}")
            traceback.print_exc()
        
        print(f"Waiting for {run_interval_seconds} seconds before the next run...")
        time.sleep(run_interval_seconds)