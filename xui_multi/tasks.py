import os
import json
import tempfile
from datetime import datetime
import reflex as rx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from .models import ManagedService, Panel, PanelConfig, User
from .xui_client import XUIClient
import logging

# Configure logging
logging.basicConfig(level=logging.ERROR)
logging.getLogger("httpx").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

def sync_usage_task():
    """تسک همگام‌سازی حجم استفاده شده سرویس‌ها با استفاده از فایل‌های JSON"""
    # Silent execution - no logging to reduce log file size
    
    # Create temporary directory for JSON files
    temp_dir = tempfile.mkdtemp(prefix="xui_cache_")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            # Get all panels
            panels = session.query(Panel).all()
            
            # Step 1: Fetch data from all panels and save to JSON files
            for panel in panels:
                try:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    inbounds_data = client.get_all_inbounds_data()
                    
                    # Save to JSON file
                    json_file = os.path.join(temp_dir, f"panel_{panel.id}.json")
                    with open(json_file, 'w', encoding='utf-8') as f:
                        json.dump(inbounds_data, f, ensure_ascii=False, indent=2)
                    
                except Exception as e:
                    continue
            
            # Step 2: Process services using JSON files
            services = session.query(ManagedService).filter(
                ManagedService.status == "active"
            ).all()
            
            for service in services:
                total_usage_gb = 0
                service_configs = session.query(PanelConfig).filter(
                    PanelConfig.managed_service_id == service.id
                ).all()
                
                for config in service_configs:
                    try:
                        # Load panel data from JSON file
                        json_file = os.path.join(temp_dir, f"panel_{config.panel_id}.json")
                        if os.path.exists(json_file):
                            with open(json_file, 'r', encoding='utf-8') as f:
                                panel_data = json.load(f)
                            
                            # Find inbound data
                            inbound_data = None
                            for inbound in panel_data:
                                if inbound.get("id") == config.panel_inbound_id:
                                    inbound_data = inbound
                                    break
                            
                            if inbound_data:
                                # Calculate usage
                                up_gb = inbound_data.get("up", 0) / (1024 * 1024 * 1024)
                                down_gb = inbound_data.get("down", 0) / (1024 * 1024 * 1024)
                                traffic_gb = up_gb + down_gb
                                total_usage_gb += traffic_gb
                            else:
                                pass
                        else:
                            pass
                            
                    except Exception as e:
                        continue
                
                # Update service usage
                service.data_used_gb = total_usage_gb
                
                # Check if service should be disabled
                if total_usage_gb >= service.data_limit_gb:
                    for config in service_configs:
                        try:
                            panel = session.query(Panel).filter(Panel.id == config.panel_id).first()
                            client = XUIClient(panel.url, panel.username, panel.password)
                            client.disable_inbound(config.panel_inbound_id)
                        except Exception as e:
                            pass
                
                session.add(service)
            
            session.commit()
            
    except Exception as e:
        pass
    
    finally:
        # Step 3: Clean up JSON files
        try:
            import shutil
            shutil.rmtree(temp_dir)
        except Exception as e:
            pass

def build_configs_task(service_uuid: str):
    """تسک ساخت کانفیگ‌ها برای سرویس"""
    logger.info(f"[{datetime.now()}] Starting build_configs_task for service: {service_uuid}")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"Service with UUID {service_uuid} not found")
                return
            
            # Get all panels
            panels = session.query(Panel).all()
            
            for panel in panels:
                try:
                    logger.info(f"[{datetime.now()}] Processing panel: {panel.url}")
                    logger.info(f"[{datetime.now()}] Attempt 1 for panel {panel.url}")
                    
                    client = XUIClient(panel.url, panel.username, panel.password)
                    
                    # Find available port
                    used_ports = client.get_used_ports()
                    port = 20000
                    while port in used_ports:
                        port += 1
                    
                    # Create inbound based on service protocol
                    if service.protocol == "vless":
                        remark = f"{panel.remark_prefix}-{service.name}"
                        result = client.create_vless_inbound(
                            remark=remark,
                            domain=panel.domain,
                            port=port,
                            expiry_days=(service.end_date - service.start_date).days,
                            limit_gb=service.data_limit_gb
                        )
                    elif service.protocol == "shadowsocks":
                        remark = f"{panel.remark_prefix}-{service.name}"
                        result = client.create_shadowsocks_inbound(
                            remark=remark,
                            domain=panel.domain,
                            port=port,
                            expiry_days=(service.end_date - service.start_date).days,
                            limit_gb=service.data_limit_gb
                        )
                    else:
                        logger.warning(f"Unsupported protocol: {service.protocol}")
                        continue
                    
                    # Verify result has valid data
                    if not result.get("link") or not result.get("inbound_id"):
                        logger.error(f"[{datetime.now()}] ERROR: Invalid result from panel {panel.url}: {result}")
                        continue
                    
                    # Save config to database
                    config = PanelConfig(
                        managed_service_id=service.id,
                        panel_id=panel.id,
                        panel_inbound_id=result["inbound_id"],
                        config_link=result["link"]
                    )
                    session.add(config)
                    session.commit()
                    
                    logger.info(f"[{datetime.now()}] Added panel config to database with link: {result['link'][:50]}...")
                    
                    # Verify config_link was saved correctly
                    if not config.config_link or config.config_link.strip() == '':
                        logger.error(f"[{datetime.now()}] ERROR: config_link is empty after saving! Panel: {panel.url}")
                        # Try to regenerate config_link
                        try:
                            inbound_data = client.get_inbound(result["inbound_id"])
                            if inbound_data:
                                config_link = client._construct_config_link(inbound_data, panel.domain)
                                config.config_link = config_link
                                session.commit()
                                logger.info(f"[{datetime.now()}] Regenerated config_link for panel {panel.url}")
                        except Exception as e:
                            logger.error(f"[{datetime.now()}] Failed to regenerate config_link: {e}")
                    
                except Exception as e:
                    logger.error(f"Error processing panel {panel.url}: {e}")
                    continue
            
            # Create subscription file
            configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            if configs:
                subscription_content = "\n".join([config.config_link for config in configs if config.config_link])
                
                if subscription_content.strip():
                    # Create subscription file
                    subs_dir = "static/subs"
                    os.makedirs(subs_dir, exist_ok=True)
                    file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
                    
                    # Encode to base64
                    import base64
                    encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                    
                    with open(file_path, "w", encoding='utf-8') as f:
                        f.write(encoded_content)
                    
                    # Also update service.subscription_link
                    service.subscription_link = subscription_content
                    session.commit()
                    
                    logger.info(f"[{datetime.now()}] Created subscription file with {len(configs)} configs")
                    logger.info(f"[{datetime.now()}] File path: {file_path}")
                    logger.info(f"[{datetime.now()}] Content length: {len(subscription_content)}")
                else:
                    logger.warning(f"[{datetime.now()}] No valid config_links found for service {service.name}")
            else:
                logger.warning(f"[{datetime.now()}] No configs found for service {service.name}")
            
            logger.info(f"[{datetime.now()}] Celery background config building completed for service {service_uuid}")
            
    except Exception as e:
        logger.error(f"Build configs job failed with error: {e}")
        raise

def cleanup_deleted_panels_task():
    """تسک پاک کردن کانفیگ‌های مربوط به پنل‌های حذف شده"""
    logger.info(f"[{datetime.now()}] Starting cleanup_deleted_panels_task...")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            # Get all configs
            configs = session.query(PanelConfig).all()
            
            for config in configs:
                panel = session.query(Panel).filter(Panel.id == config.panel_id).first()
                if not panel:
                    # Panel was deleted, remove config
                    session.delete(config)
                    logger.info(f"Removed config {config.id} for deleted panel")
            
            session.commit()
            logger.info(f"[{datetime.now()}] Cleanup completed")
            
    except Exception as e:
        logger.error(f"Cleanup job failed with error: {e}")
        raise

def update_service_task(service_uuid: str, **updates):
    """تسک به‌روزرسانی سرویس"""
    logger.info(f"[{datetime.now()}] Starting update_service_task for service: {service_uuid}")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"Service with UUID {service_uuid} not found")
                return
            
            # Update service fields
            for field, value in updates.items():
                if hasattr(service, field):
                    setattr(service, field, value)
            
            session.commit()
            logger.info(f"[{datetime.now()}] Service {service_uuid} updated successfully")
            
    except Exception as e:
        logger.error(f"Update service job failed with error: {e}")
        raise

def delete_service_task(service_uuid: str):
    """تسک حذف سرویس"""
    logger.info(f"[{datetime.now()}] Starting delete_service_task for service: {service_uuid}")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"Service with UUID {service_uuid} not found")
                return
            
            # Delete related configs
            configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            for config in configs:
                session.delete(config)
            
            # Delete service
            session.delete(service)
            session.commit()
            logger.info(f"[{datetime.now()}] Service {service_uuid} deleted successfully")
            
    except Exception as e:
        logger.error(f"Delete service job failed with error: {e}")
        raise

def sync_services_with_panels_task():
    """تسک همگام‌سازی سرویس‌ها با پنل‌ها"""
    logger.info(f"[{datetime.now()}] Starting sync_services_with_panels_task...")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            # Get all services (not just active ones)
            services = session.query(ManagedService).all()
            panels = session.query(Panel).all()
            
            logger.info(f"[{datetime.now()}] Processing {len(services)} services with {len(panels)} panels")
            
            for service in services:
                logger.info(f"[{datetime.now()}] Processing service: {service.name} (UUID: {service.uuid})")
                
                for panel in panels:
                    # Check if config exists for this service-panel combination
                    existing_config = session.query(PanelConfig).filter(
                        PanelConfig.managed_service_id == service.id,
                        PanelConfig.panel_id == panel.id
                    ).first()
                    
                    if not existing_config:
                        # Create config for this service on this panel
                        try:
                            logger.info(f"[{datetime.now()}] Creating config for service {service.name} on panel {panel.url}")
                            
                            client = XUIClient(panel.url, panel.username, panel.password)
                            used_ports = client.get_used_ports()
                            port = 20000
                            while port in used_ports:
                                port += 1
                            
                            if service.protocol in ["vless", "shadowsocks"]:
                                remark = f"{panel.remark_prefix}-{service.name}"
                                if service.protocol == "vless":
                                    result = client.create_vless_inbound(
                                        remark=remark,
                                        domain=panel.domain,
                                        port=port,
                                        expiry_days=(service.end_date - service.start_date).days,
                                        limit_gb=service.data_limit_gb
                                    )
                                else:
                                    result = client.create_shadowsocks_inbound(
                                        remark=remark,
                                        domain=panel.domain,
                                        port=port,
                                        expiry_days=(service.end_date - service.start_date).days,
                                        limit_gb=service.data_limit_gb
                                    )
                                
                                config = PanelConfig(
                                    managed_service_id=service.id,
                                    panel_id=panel.id,
                                    panel_inbound_id=result["inbound_id"],
                                    config_link=result["link"]
                                )
                                session.add(config)
                                session.commit()  # Commit immediately to avoid conflicts
                                
                                # Verify config_link was saved correctly
                                if not config.config_link or config.config_link.strip() == '':
                                    logger.error(f"ERROR: config_link is empty after saving! Panel: {panel.url}")
                                    # Try to regenerate config_link
                                    try:
                                        inbound_data = client.get_inbound(result["inbound_id"])
                                        if inbound_data:
                                            config_link = client._construct_config_link(inbound_data, panel.domain)
                                            config.config_link = config_link
                                            session.commit()
                                            logger.info(f"Regenerated config_link for panel {panel.url}")
                                    except Exception as e:
                                        logger.error(f"Failed to regenerate config_link: {e}")
                                else:
                                    logger.info(f"Created config for service {service.name} on panel {panel.url} with link: {result['link'][:50]}...")
                            else:
                                logger.warning(f"Unsupported protocol {service.protocol} for service {service.name}")
                        
                        except Exception as e:
                            logger.error(f"Error creating config for service {service.name} on panel {panel.url}: {e}")
                            continue
                    else:
                        logger.info(f"Config already exists for service {service.name} on panel {panel.url}")
                
                # Update subscription file for this service
                try:
                    configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
                    if configs:
                        subscription_content = "\n".join([config.config_link for config in configs if config.config_link])
                        
                        # Create subscription file
                        subs_dir = "static/subs"
                        os.makedirs(subs_dir, exist_ok=True)
                        file_path = os.path.join(subs_dir, f"{service.uuid}.txt")
                        
                        # Encode to base64
                        import base64
                        encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                        
                        with open(file_path, "w", encoding='utf-8') as f:
                            f.write(encoded_content)
                        
                        logger.info(f"[{datetime.now()}] Updated subscription file for service {service.name} with {len(configs)} configs")
                    else:
                        logger.warning(f"No configs found for service {service.name}")
                        
                except Exception as e:
                    logger.error(f"Error updating subscription file for service {service.name}: {e}")
            
            logger.info(f"[{datetime.now()}] Sync services with panels completed")
            
    except Exception as e:
        logger.error(f"Sync services with panels job failed with error: {e}")
        raise

# Helper functions for enqueuing tasks
def enqueue_sync_usage():
    """Enqueue sync_usage task"""
    from .redis_queue import redis_queue
    task_id = f"sync_usage_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("sync_usage", task_id, {})
    # Silent execution - no logging
    return task_id

def enqueue_build_configs(service_uuid: str):
    """Enqueue build_configs task"""
    from .redis_queue import redis_queue
    task_id = f"build_configs_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("build_configs", task_id, {"service_uuid": service_uuid})
    logger.info(f"Build configs task enqueued: {task_id}")
    return task_id

def enqueue_cleanup_panels():
    """Enqueue cleanup_panels task"""
    from .redis_queue import redis_queue
    task_id = f"cleanup_panels_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("cleanup_panels", task_id, {})
    logger.info(f"Cleanup panels task enqueued: {task_id}")
    return task_id

def enqueue_update_service(service_uuid: str, **updates):
    """Enqueue update_service task"""
    from .redis_queue import redis_queue
    task_id = f"update_service_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("update_service", task_id, {"service_uuid": service_uuid, "updates": updates})
    logger.info(f"Update service task enqueued: {task_id}")
    return task_id

def enqueue_delete_service(service_uuid: str):
    """Enqueue delete_service task"""
    from .redis_queue import redis_queue
    task_id = f"delete_service_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("delete_service", task_id, {"service_uuid": service_uuid})
    logger.info(f"Delete service task enqueued: {task_id}")
    return task_id

def enqueue_sync_services_with_panels():
    """Enqueue sync_services_with_panels task"""
    from .redis_queue import redis_queue
    task_id = f"sync_services_with_panels_{int(datetime.now().timestamp() * 1000)}"
    redis_queue.enqueue_task("sync_services_with_panels", task_id, {})
    logger.info(f"Sync services with panels task enqueued: {task_id}")
    return task_id

def verify_and_fix_subscription_files():
    """Verify and fix subscription files automatically"""
    logger.info(f"[{datetime.now()}] Starting subscription files verification...")
    
    try:
        import base64
        import glob
        import os
        
        subs_dir = "static/subs"
        if not os.path.exists(subs_dir):
            logger.info(f"Subscription directory not found: {subs_dir}")
            return
        
        # Get all txt files
        txt_files = glob.glob(os.path.join(subs_dir, "*.txt"))
        logger.info(f"Found {len(txt_files)} subscription files")
        
        fixed_count = 0
        for file_path in txt_files:
            filename = os.path.basename(file_path)
            service_uuid = filename.replace('.txt', '')
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if not content.strip():
                    logger.warning(f"Empty file: {filename}")
                    continue
                
                # Try to decode base64
                try:
                    decoded = base64.b64decode(content).decode('utf-8')
                    
                    # Check for broken content patterns
                    broken_patterns = [
                        "در حال ساخت کانفیگ‌ها",
                        "2K/YsSDYrdin2YQg2LPYp9iu2Kog2qnYp9mG2YHbjNqv4oCM2YfYpy4uLgrZhNi32YHYp9mLINqG2YbYryDZhNit2LjZhyDYtdio",
                        "لطفاً چند لحظه صبر کنید"
                    ]
                    
                    is_broken = False
                    for pattern in broken_patterns:
                        if pattern in decoded:
                            is_broken = True
                            break
                    
                    if is_broken or len(decoded.strip()) < 10:
                        logger.warning(f"Broken content detected: {filename}")
                        # Fix the service
                        if fix_service_subscription(service_uuid):
                            fixed_count += 1
                            logger.info(f"Fixed: {filename}")
                    
                except Exception as e:
                    logger.warning(f"Error decoding {filename}: {e}")
                    
            except Exception as e:
                logger.error(f"Error reading {filename}: {e}")
        
        logger.info(f"Fixed {fixed_count} subscription files")
        
    except Exception as e:
        logger.error(f"Error in verify_and_fix_subscription_files: {e}")

def fix_service_subscription(service_uuid):
    """Fix subscription for a specific service"""
    try:
        import base64
        import os
        
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"Service with UUID {service_uuid} not found")
                return False
            
            logger.info(f"Fixing subscription for service: {service.name}")
            
            # Get all configs for this service
            configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            
            if configs:
                # Create new subscription content
                subscription_content = "\n".join([config.config_link for config in configs if config.config_link])
                
                if subscription_content.strip():
                    # Create subscription file
                    subs_dir = "static/subs"
                    os.makedirs(subs_dir, exist_ok=True)
                    file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
                    
                    # Encode to base64
                    encoded_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                    
                    with open(file_path, "w", encoding='utf-8') as f:
                        f.write(encoded_content)
                    
                    logger.info(f"Updated subscription file for service {service.name} with {len(configs)} configs")
                    return True
                else:
                    logger.error(f"No valid config_links found for service {service.name}")
                    return False
            else:
                logger.error(f"No configs found for service {service.name}")
                return False
                
    except Exception as e:
        logger.error(f"Error fixing service subscription: {e}")
        return False

def fix_specific_service_configs(service_uuid: str):
    """Fix configs for a specific service"""
    logger.info(f"[{datetime.now()}] Starting fix_specific_service_configs for service: {service_uuid}")
    
    try:
        engine = create_engine(rx.config.get_config().db_url)
        with Session(engine) as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                logger.error(f"Service with UUID {service_uuid} not found")
                return False
            
            panels = session.query(Panel).all()
            logger.info(f"[{datetime.now()}] Processing service: {service.name} with {len(panels)} panels")
            
            for panel in panels:
                # Check if config exists for this service-panel combination
                existing_config = session.query(PanelConfig).filter(
                    PanelConfig.managed_service_id == service.id,
                    PanelConfig.panel_id == panel.id
                ).first()
                
                if existing_config:
                    # Try to regenerate config_link for existing config
                    try:
                        logger.info(f"[{datetime.now()}] Regenerating config_link for service {service.name} on panel {panel.url}")
                        
                        client = XUIClient(panel.url, panel.username, panel.password)
                        inbound_data = client.get_inbound(existing_config.panel_inbound_id)
                        
                        if inbound_data:
                            # Regenerate config_link
                            config_link = client._construct_config_link(inbound_data, panel.domain, existing_config.config_link)
                            existing_config.config_link = config_link
                            session.commit()
                            logger.info(f"Regenerated config_link for service {service.name} on panel {panel.url}")
                        else:
                            logger.warning(f"Inbound {existing_config.panel_inbound_id} not found on panel {panel.url}")
                    
                    except Exception as e:
                        logger.error(f"Error regenerating config_link for service {service.name} on panel {panel.url}: {e}")
                        continue
                else:
                    try:
                        logger.info(f"[{datetime.now()}] Creating config for service {service.name} on panel {panel.url}")
                        
                        client = XUIClient(panel.url, panel.username, panel.password)
                        used_ports = client.get_used_ports()
                        port = 20000
                        while port in used_ports:
                            port += 1
                        
                        if service.protocol in ["vless", "shadowsocks"]:
                            remark = f"{panel.remark_prefix}-{service.name}"
                            if service.protocol == "vless":
                                result = client.create_vless_inbound(
                                    remark=remark,
                                    domain=panel.domain,
                                    port=port,
                                    expiry_days=(service.end_date - service.start_date).days,
                                    limit_gb=service.data_limit_gb
                                )
                            else:
                                result = client.create_shadowsocks_inbound(
                                    remark=remark,
                                    domain=panel.domain,
                                    port=port,
                                    expiry_days=(service.end_date - service.start_date).days,
                                    limit_gb=service.data_limit_gb
                                )
                            
                            config = PanelConfig(
                                managed_service_id=service.id,
                                panel_id=panel.id,
                                panel_inbound_id=result["inbound_id"],
                                config_link=result["link"]
                            )
                            session.add(config)
                            session.commit()
                            logger.info(f"Created config for service {service.name} on panel {panel.url}")
                        else:
                            logger.warning(f"Unsupported protocol {service.protocol} for service {service.name}")
                    
                    except Exception as e:
                        logger.error(f"Error creating config for service {service.name} on panel {panel.url}: {e}")
                        continue
            
            # Update subscription file
            configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            if configs:
                subscription_content = "\n".join([config.config_link for config in configs if config.config_link])
                
                # Create subscription file
                subs_dir = "static/subs"
                os.makedirs(subs_dir, exist_ok=True)
                file_path = os.path.join(subs_dir, f"{service.uuid}.txt")
                
                logger.info(f"[{datetime.now()}] Writing subscription file: {file_path}")
                logger.info(f"[{datetime.now()}] Subscription content length: {len(subscription_content)}")
                logger.info(f"[{datetime.now()}] First 100 chars: {subscription_content[:100]}")
                
                with open(file_path, "w", encoding='utf-8') as f:
                    f.write(subscription_content)
                
                logger.info(f"[{datetime.now()}] Updated subscription file for service {service.name} with {len(configs)} configs")
                return True
            else:
                logger.warning(f"No configs found for service {service.name}")
                return False
                
    except Exception as e:
        logger.error(f"Fix specific service configs failed with error: {e}")
        return False