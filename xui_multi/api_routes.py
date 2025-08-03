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
from .tasks import build_configs_task

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
            
            subscription_url = f"https://multi.antihknet.com/static/subs/{service_uuid}.txt"
            managed_service.subscription_link = subscription_url
            session.commit()
            
            from .tasks import enqueue_build_configs
            enqueue_build_configs(service_uuid)
            
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

        # Add task to Redis queue
        from .tasks import enqueue_update_service
        task_id = enqueue_update_service(service_uuid, update_data.data_limit_gb, update_data.duration_days)

        return {
            "status": "success", 
            "message": "درخواست آپدیت سرویس در صف قرار گرفت و در حال پردازش است.",
            "task_id": task_id
        }

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
        
        # Add task to Redis queue
        from .tasks import enqueue_delete_service
        task_id = enqueue_delete_service(service_uuid)
        
        return {
            "status": "success", 
            "message": "درخواست حذف سرویس در صف قرار گرفت و در حال پردازش است.",
            "task_id": task_id
        }

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

@api.get("/redis/queue/stats")
async def get_redis_queue_stats(current_user: User = Depends(get_current_user)):
    """Get Redis queue statistics"""
    try:
        from .redis_worker import get_queue_statistics
        stats = get_queue_statistics()
        return {
            "queue_stats": stats,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting queue stats: {e}")

@api.get("/redis/task/{task_id}/status")
async def get_task_status(task_id: str, current_user: User = Depends(get_current_user)):
    """Get status of a specific task"""
    try:
        from .redis_worker import worker_manager
        status = worker_manager.get_task_status(task_id)
        if status:
            return {
                "task_id": task_id,
                "status": status,
                "timestamp": datetime.now().isoformat()
            }
        else:
            raise HTTPException(status_code=404, detail="Task not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting task status: {e}")

@api.get("/redis/workers/status")
async def get_workers_status(current_user: User = Depends(get_current_user)):
    """Get Redis workers status"""
    try:
        from .redis_worker import worker_manager
        return {
            "workers_running": worker_manager.running,
            "active_workers": len(worker_manager.workers),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting workers status: {e}")