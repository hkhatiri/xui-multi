from fastapi import FastAPI, Request, HTTPException, Depends, Header, BackgroundTasks
import pydantic
import reflex as rx
from typing import List, Annotated, Literal
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import os
import threading
import time
import logging
import json

from sqlmodel import select

from .models import ManagedService, Panel, PanelConfig, User
from .xui_client import XUIClient

api = FastAPI()
service_creation_lock = threading.Lock()
MAX_RETRIES = 3

# Configure logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ServiceUpdateRequest(pydantic.BaseModel):
    duration_days: int
    data_limit_gb: int

class CreateServiceRequest(pydantic.BaseModel):
    name: str
    duration_days: float
    data_limit_gb: float
    protocol: Literal["vless", "shadowsocks"]

async def get_current_user(x_api_authorization: Annotated[str, Header()]):
    """کاربر را بر اساس کلید API اختصاصی‌اش از هدر پیدا کرده و برمی‌گرداند."""
    if not x_api_authorization:
        raise HTTPException(status_code=401, detail="Missing X-API-Authorization header")

    with rx.session() as session:
        user = session.exec(select(User).where(User.api_key == x_api_authorization)).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid User API Key")
        return user

async def build_configs_background(service_uuid: str, creator_id: int, protocol: str, duration_days: float, data_limit_gb: float):
    """ساخت کانفیگ‌ها در پس‌زمینه و ذخیره در فایل"""
    try:
        with rx.session() as session:
            service = session.exec(select(ManagedService).where(ManagedService.uuid == service_uuid)).first()
            if not service:
                logger.error(f"Service {service_uuid} not found for background config building")
                return
            
            creator = session.exec(select(User).where(User.id == creator_id)).first()
            if not creator:
                logger.error(f"User {creator_id} not found for background config building")
                return
            
            all_panels = session.query(Panel).all()
            if not all_panels:
                logger.error(f"No panels found for background config building")
                return

            all_configs_list = []
            base_port = 20000
            
            for panel in all_panels:
                last_exception = None
                for attempt in range(MAX_RETRIES):
                    try:
                        client = XUIClient(panel.url, panel.username, panel.password)
                        used_ports = set(client.get_used_ports())
                        
                        port = base_port
                        while port in used_ports:
                            port += 1
                        
                        panel_side_remark = f"{panel.remark_prefix}-{creator.username}-{port}"

                        if protocol == "vless":
                            result = client._create_inbound(
                                {
                                    "up": "0",
                                    "down": "0",
                                    "total": "0",
                                    "remark": panel_side_remark,
                                    "enable": "true",
                                    "expiryTime": "0",
                                    "listen": "",
                                    "port": str(port),
                                    "protocol": "vless",
                                    "settings": json.dumps({
                                        "clients": [{
                                            "id": service.uuid,
                                            "flow": "",
                                            "email": f"{creator.username}@{service.name}",
                                            "limitIp": 0,
                                            "totalGB": 0,
                                            "expiryTime": 0,
                                            "enable": True,
                                            "tgId": "",
                                            "reset": 0,
                                            "subId": 1
                                        }]
                                    }),
                                    "streamSettings": json.dumps({
                                        "network": "tcp",
                                        "security": "none",
                                        "tcpSettings": {
                                            "header": {
                                                "type": "none"
                                            }
                                        }
                                    }),
                                    "sniffing": json.dumps({
                                        "enabled": True,
                                        "destOverride": ["http", "tls"]
                                    })
                                },
                                panel.domain,
                                f"{creator.username}@{service.name}"
                            )
                        
                        panel_config = PanelConfig(managed_service_id=service.id, panel_id=panel.id, panel_inbound_id=result["inbound_id"], config_link=result["link"])
                        session.add(panel_config)
                        all_configs_list.append(result["link"])
                        break
                    
                    except Exception as e:
                        last_exception = e
                        logger.error(f"Attempt {attempt + 1} failed for panel {panel.url}: {e}")
                        time.sleep(1)

                if last_exception:
                    logger.error(f"Failed to create config on panel {panel.url} after {MAX_RETRIES} attempts: {last_exception}")
                    continue

            if all_configs_list:
                subscription_content = "\n".join(all_configs_list)
                base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
                
                subs_dir = "static/subs"
                os.makedirs(subs_dir, exist_ok=True)
                file_path = os.path.join(subs_dir, f"{service.uuid}.txt")
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(base64_content)
                
                service.subscription_link = f"http://multi.antihknet.com:8000/static/subs/{service.uuid}.txt"
                session.commit()
            else:
                logger.error(f"No configs were created for service {service_uuid}")
                
    except Exception as e:
        logger.error(f"Error in background config building for service {service_uuid}: {e}")
        import traceback
        traceback.print_exc()

@api.post("/service")
async def create_service(
    request: Request,
    service_data: CreateServiceRequest,
    background_tasks: BackgroundTasks,
    creator: User = Depends(get_current_user)
):
    """یک سرویس جدید ایجاد می‌کند و فایل subscription را می‌سازد، سپس کانفیگ‌ها را در پس‌زمینه می‌سازد."""
    with service_creation_lock:
        with rx.session() as session:
            service_uuid = str(uuid4())
            start = datetime.now()
            end = start + timedelta(days=service_data.duration_days)

            # ایجاد سرویس در دیتابیس
            managed_service = ManagedService(
                name=service_data.name, uuid=service_uuid, start_date=start,
                end_date=end, data_limit_gb=service_data.data_limit_gb, 
                protocol=service_data.protocol, created_by_id=creator.id,
            )
            session.add(managed_service)
            session.flush()

            subs_dir = "static/subs"
            os.makedirs(subs_dir, exist_ok=True)
            file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
            
            initial_content = "در حال ساخت کانفیگ‌ها...\nلطفاً چند لحظه صبر کنید."
            base64_content = base64.b64encode(initial_content.encode('utf-8')).decode('utf-8')
            with open(file_path, "w") as f:
                f.write(base64_content)
            
            base_url = str(request.base_url).rstrip('/')
            subscription_url = f"{base_url}/static/subs/{service_uuid}.txt"
            managed_service.subscription_link = subscription_url
            session.commit()
            
            build_configs_task.delay(service_uuid, creator.id, service_data.protocol, service_data.duration_days, service_data.data_limit_gb)
            
            try:
                from .cache_manager import invalidate_service_cache, invalidate_traffic_cache
                invalidate_service_cache()
                invalidate_traffic_cache()
            except ImportError:
                pass
            
            return {"status": "success", "subscription_link": subscription_url, "message": "سرویس ایجاد شد. کانفیگ‌ها در حال ساخت هستند."}

@api.put("/service/{service_uuid}")
async def update_service(
    service_uuid: str,
    update_data: ServiceUpdateRequest,
    current_user: User = Depends(get_current_user)
):
    """یک سرویس موجود را آپدیت می‌کند."""
    with rx.session() as session:
        service = session.exec(select(ManagedService).where(ManagedService.uuid == service_uuid)).first()
        if not service:
            raise HTTPException(status_code=404, detail="سرویس یافت نشد.")

        if service.created_by_id != current_user.id and current_user.username != "hkhatiri":
            raise HTTPException(status_code=403, detail="شما اجازه دسترسی به این سرویس را ندارید.")

        new_total_gb_bytes = int(update_data.data_limit_gb * 1024 * 1024 * 1024)
        new_end_date = datetime.now() + timedelta(days=update_data.duration_days)
        new_expiry_time_ms = int(new_end_date.timestamp() * 1000)

        for p_config in service.configs:
            try:
                panel = p_config.panel
                client = XUIClient(panel.url, panel.username, panel.password)
                client.update_inbound(
                    inbound_id=p_config.panel_inbound_id,
                    new_total_gb=new_total_gb_bytes,
                    new_expiry_time_ms=new_expiry_time_ms
                )
            except Exception as e:
                logger.error(f"خطا در آپدیت کانفیگ روی پنل {p_config.panel.url}: {e}")

        service.data_limit_gb = update_data.data_limit_gb
        service.end_date = new_end_date
        session.commit()

        try:
            from .cache_manager import invalidate_service_cache, invalidate_traffic_cache
            invalidate_service_cache()
            invalidate_traffic_cache()
        except ImportError:
            pass

        return {"status": "success", "message": "سرویس با موفقیت آپدیت شد."}

@api.delete("/service/{service_uuid}")
async def delete_service(
    service_uuid: str,
    current_user: User = Depends(get_current_user)
):
    """یک سرویس و تمام کانفیگ‌های مرتبط با آن را حذف می‌کند."""
    with rx.session() as session:
        service = session.exec(select(ManagedService).where(ManagedService.uuid == service_uuid)).first()
        if not service:
            raise HTTPException(status_code=404, detail="سرویس یافت نشد.")
        
        if service.created_by_id != current_user.id and current_user.username != "hkhatiri":
            raise HTTPException(status_code=403, detail="شما اجازه دسترسی به این سرویس را ندارید.")
        
        for p_config in service.configs:
            try:
                panel = p_config.panel
                if panel:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    client.delete_inbound(p_config.panel_inbound_id)
                else:
                    logger.warning(f"Panel not found for config {p_config.id}")
            except Exception as e:
                panel_url = panel.url if panel else "unknown"
                logger.error(f"خطای غیربحرانی: حذف کانفیگ {p_config.panel_inbound_id} از پنل {panel_url} با مشکل مواجه شد: {e}")
            session.delete(p_config)
        
        if service.subscription_link:
            file_name = service.subscription_link.split("/")[-1]
            file_path = os.path.join("static/subs", file_name)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        session.delete(service)
        session.commit()
        
        try:
            from .cache_manager import invalidate_service_cache, invalidate_traffic_cache
            invalidate_service_cache()
            invalidate_traffic_cache()
        except ImportError:
            pass
        
        return {"status": "success", "message": f"سرویس {service_uuid} با موفقیت حذف شد."}

@api.delete("/services/inactive")
async def delete_inactive_services(
    current_user: User = Depends(get_current_user)
):
    """تمام سرویس‌های غیرفعال را حذف می‌کند."""
    if current_user.username != "hkhatiri":
        raise HTTPException(status_code=403, detail="فقط ادمین اصلی می‌تواند این عملیات را انجام دهد.")
    
    deleted_count = 0
    errors = []
    with rx.session() as session:
        inactive_services = session.query(ManagedService).filter(
            ManagedService.status.in_(["expired", "limit_reached"])
        ).all()

        if not inactive_services:
            return {"status": "success", "message": "هیچ سرویس غیرفعالی برای حذف وجود ندارد.", "deleted_count": 0}

        for service in inactive_services:
            try:
                for p_config in service.configs:
                    try:
                        panel = p_config.panel
                        client = XUIClient(panel.url, panel.username, panel.password)
                        client.delete_inbound(p_config.panel_inbound_id)
                    except Exception as e:
                        logger.error(f"خطای غیربحرانی: حذف کانفیگ {p_config.panel_inbound_id} از پنل {panel.url} با مشکل مواجه شد: {e}")
                    session.delete(p_config)
                
                if service.subscription_link:
                    file_name = service.subscription_link.split("/")[-1]
                    file_path = os.path.join("static/subs", file_name)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                
                session.delete(service)
                deleted_count += 1
            except Exception as e:
                errors.append(f"خطا در حذف سرویس {service.uuid}: {e}")
                session.rollback()

        session.commit()

    if errors:
        raise HTTPException(status_code=500, detail={"message": "برخی از سرویس‌ها حذف نشدند.", "errors": errors})

    return {"status": "success", "message": f"{deleted_count} سرویس غیرفعال با موفقیت حذف شد."}

@api.get("/service/{service_uuid}/stats")
async def get_service_stats(service_uuid: str, current_user: User = Depends(get_current_user)):
    """زمان و حجم باقی‌مانده یک سرویس را برمی‌گرداند."""
    with rx.session() as session:
        service = session.exec(select(ManagedService).where(ManagedService.uuid == service_uuid)).first()
        if not service:
            raise HTTPException(status_code=404, detail="سرویس یافت نشد.")
        
        if service.created_by_id != current_user.id and current_user.username != "hkhatiri":
            raise HTTPException(status_code=403, detail="شما اجازه دسترسی به این سرویس را ندارید.")

        remaining_gb = service.data_limit_gb - service.data_used_gb
        remaining_days = (service.end_date - datetime.now()).days if service.end_date > datetime.now() else 0

        return {
            "remaining_gb": round(remaining_gb, 2),
            "remaining_days": remaining_days,
            "status": service.status
        }