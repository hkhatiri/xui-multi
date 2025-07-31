import os
import time
import base64
import logging
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import select
import reflex as rx

from .celery_app import *
from .models import ManagedService, Panel, PanelConfig, User
from .xui_client import XUIClient
from .subscription_manager import SubscriptionManager

# Configure logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@celery_app.task
def sync_usage_task():
    """این وظیفه در پس‌زمینه مصرف را سینک می‌کند و محدودیت‌ها را اعمال می‌کند."""
    config = rx.config.get_config()
    engine = create_engine(config.db_url)
    
    with Session(engine) as session:
        try:
            active_services = session.query(ManagedService).filter(ManagedService.status == "active").all()
            for service in active_services:
                total_traffic_gb = 0
                service_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
                
                for config in service_configs:
                    try:
                        panel = session.query(Panel).filter(Panel.id == config.panel_id).first()
                        if not panel:
                            continue
                        client = XUIClient(panel.url, panel.username, panel.password)
                        traffic_gb = client.get_inbound_traffic_gb(config.panel_inbound_id)
                        total_traffic_gb += traffic_gb
                    except Exception as e:
                        logger.error(f"Could not get traffic for inbound ID {config.panel_inbound_id}. Error: {e}")
                service.data_used_gb = total_traffic_gb
                
                if datetime.now() > service.end_date:
                    should_disable = True
                    reason = "expired"
                elif total_traffic_gb >= service.data_limit_gb:
                    should_disable = True
                    reason = "limit_reached"
                else:
                    should_disable = False
                    reason = None
                
                if should_disable:
                    for config in service_configs:
                        try:
                            panel = session.query(Panel).filter(Panel.id == config.panel_id).first()
                            client = XUIClient(panel.url, panel.username, panel.password)
                            client.disable_inbound(config.panel_inbound_id)
                        except Exception as e:
                            logger.error(f"Failed to disable inbound ID {config.panel_inbound_id} on panel {panel.url}. Error: {e}")
                    service.status = reason
                session.add(service)
            session.commit()
        except Exception as e:
            logger.error(f"Sync job failed with error: {e}")
            session.rollback()
            raise

@celery_app.task
def build_configs_task(service_uuid: str, creator_id: int, protocol: str, duration_days: float, data_limit_gb: float):
    """ساخت کانفیگ‌ها در پس‌زمینه با استفاده از Celery"""
    logger.info(f"[{datetime.now()}] Starting Celery config building for service {service_uuid}")
    try:
        config = rx.config.get_config()
        engine = create_engine(config.db_url)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        with SessionLocal() as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"[{datetime.now()}] ERROR: Service {service_uuid} not found for background config building")
                return
            
            logger.info(f"[{datetime.now()}] Found service: {service.name}")
            
            creator = session.query(User).filter(User.id == creator_id).first()
            if not creator:
                logger.error(f"[{datetime.now()}] ERROR: User {creator_id} not found for background config building")
                return
            
            logger.info(f"[{datetime.now()}] Found creator: {creator.username}")
            
            all_panels = session.query(Panel).all()
            if not all_panels:
                logger.error(f"[{datetime.now()}] ERROR: No panels found for background config building")
                return

            logger.info(f"[{datetime.now()}] Found {len(all_panels)} panels to process")
            for panel in all_panels:
                logger.info(f"[{datetime.now()}] Panel: {panel.url}, Domain: {panel.domain}, Remark Prefix: {panel.remark_prefix}")

            all_configs_list = []
            base_port = 20000
            MAX_RETRIES = 3
            
            for panel in all_panels:
                logger.info(f"[{datetime.now()}] Processing panel: {panel.url}")
                last_exception = None
                for attempt in range(MAX_RETRIES):
                    try:
                        logger.info(f"[{datetime.now()}] Attempt {attempt + 1} for panel {panel.url}")
                        client = XUIClient(panel.url, panel.username, panel.password)
                        used_ports = set(client.get_used_ports())
                        config_link_remark = f"{panel.remark_prefix}{creator.remark}"
                        
                        port = base_port
                        while port in used_ports:
                            port += 1
                        used_ports.add(port)
                        panel_side_remark = f"{panel.remark_prefix}-{creator.username}-{port}"

                        logger.info(f"[{datetime.now()}] Creating {protocol} inbound on panel {panel.url}, port {port}, remark: {panel_side_remark}")

                        if protocol == "vless":
                            result = client.create_vless_inbound(
                                remark=panel_side_remark, domain=panel.domain, port=port,
                                expiry_days=duration_days, limit_gb=data_limit_gb,
                                config_remark=config_link_remark
                            )
                        elif protocol == "shadowsocks":
                            result = client.create_shadowsocks_inbound(
                                remark=panel_side_remark, domain=panel.domain, port=port,
                                expiry_days=duration_days, limit_gb=data_limit_gb,
                                config_remark=config_link_remark
                            )
                        
                        logger.info(f"[{datetime.now()}] Successfully created inbound with ID: {result['inbound_id']}")
                        
                        panel_config = PanelConfig(managed_service_id=service.id, panel_id=panel.id, panel_inbound_id=result["inbound_id"], config_link=result["link"])
                        session.add(panel_config)
                        all_configs_list.append(result["link"])
                        
                        logger.info(f"[{datetime.now()}] Added panel config to database")
                        break
                    
                    except Exception as e:
                        last_exception = e
                        logger.error(f"[{datetime.now()}] ATTEMPT {attempt + 1} FAILED for panel {panel.url}: {e}")
                        time.sleep(1)

                if last_exception:
                    logger.error(f"[{datetime.now()}] Failed to create config on panel {panel.url} after {MAX_RETRIES} attempts: {last_exception}")
                    continue

            if all_configs_list:
                logger.info(f"[{datetime.now()}] Creating subscription file with {len(all_configs_list)} configs")
                subscription_content = "\n".join(all_configs_list)
                base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                subs_dir = "static/subs"
                os.makedirs(subs_dir, exist_ok=True)
                file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
                with open(file_path, "w") as f:
                    f.write(base64_content)
                
                session.commit()
                logger.info(f"[{datetime.now()}] Celery background config building completed for service {service_uuid}")
            else:
                logger.error(f"[{datetime.now()}] ERROR: No configs were created for service {service_uuid}")
                
    except Exception as e:
        logger.error(f"[{datetime.now()}] ERROR in Celery background config building for service {service_uuid}: {e}")
        import traceback
        traceback.print_exc()

@celery_app.task
def cleanup_deleted_panels_task():
    """حذف کانفیگ‌های مربوط به پنل‌های حذف شده از فایل‌های subscription"""
    logger.info(f"[{datetime.now()}] --- Running cleanup job ---")
    
    config = rx.config.get_config()
    engine = create_engine(config.db_url)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    with SessionLocal() as session:
        try:
            all_services = session.query(ManagedService).all()
            
            for service in all_services:
                logger.info(f"Processing service: {service.name}")
                
                service_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
                
                valid_configs = []
                for config in service_configs:
                    panel = session.query(Panel).filter(Panel.id == config.panel_id).first()
                    if panel:
                        valid_configs.append(config)
                    else:
                        logger.warning(f"  - Removing config {config.id} (panel {config.panel_id} not found)")
                        session.delete(config)
                
                if valid_configs:
                    config_links = [config.config_link for config in valid_configs]
                    subscription_content = "\n".join(config_links)
                    base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                    
                    subs_dir = "static/subs"
                    os.makedirs(subs_dir, exist_ok=True)
                    file_path = os.path.join(subs_dir, f"{service.uuid}.txt")
                    
                    with open(file_path, "w") as f:
                        f.write(base64_content)
                    
                    logger.info(f"  - Updated subscription file for service {service.uuid}")
                else:
                    subs_dir = "static/subs"
                    file_path = os.path.join(subs_dir, f"{service.uuid}.txt")
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        logger.info(f"  - Removed empty subscription file for service {service.uuid}")
            
            session.commit()
            logger.info(f"[{datetime.now()}] --- Cleanup job finished ---")
            
        except Exception as e:
            logger.error(f"[{datetime.now()}] --- Cleanup job failed with error: {e} ---")
            session.rollback()
            raise