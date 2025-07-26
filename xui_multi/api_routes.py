# xui_multi/api_routes.py

from fastapi import FastAPI, Request, HTTPException, Depends, Header
import pydantic
import reflex as rx
from typing import List, Annotated
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import os
import threading
import json
import traceback

from sqlmodel import select

from .models import ManagedService, Panel, PanelConfig, User
from .xui_client import XUIClient

api = FastAPI()
service_creation_lock = threading.Lock()

class CreateServiceRequest(pydantic.BaseModel):
    name: str
    duration_days: float
    data_limit_gb: float

class ServiceUpdateRequest(pydantic.BaseModel):
    duration_days: int
    data_limit_gb: int

# --- توابع وابستگی برای احراز هویت ---

async def verify_api_key(request: Request):
    """کلید اصلی API برنامه را بررسی می‌کند."""
    api_key = request.headers.get("X-API-KEY")
    if api_key != "SECRET_KEY_12345":
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

async def get_current_user(x_api_authorization: Annotated[str, Header()]):
    """کاربر را بر اساس کلید API اختصاصی‌اش از هدر پیدا کرده و برمی‌گرداند."""
    if not x_api_authorization:
        raise HTTPException(status_code=401, detail="Missing X-API-Authorization header")

    with rx.session() as session:
        user = session.exec(select(User).where(User.api_key == x_api_authorization)).first()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid User API Key")
        return user

# --- مسیرهای API ---

@api.post("/service")
async def create_service(
    request: Request,
    service_data: CreateServiceRequest,
    creator: User = Depends(get_current_user)
):
    """یک سرویس جدید با کانفیگ‌های مربوطه ایجاد می‌کند."""
    with service_creation_lock:
        with rx.session() as session:
            all_panels = session.query(Panel).all()
            if not all_panels:
                raise HTTPException(status_code=500, detail="هیچ پنلی در سیستم تعریف نشده است.")

            service_uuid = str(uuid4())
            start = datetime.now()
            end = start + timedelta(days=service_data.duration_days)

            managed_service = ManagedService(
                name=service_data.name,
                uuid=service_uuid,
                start_date=start,
                end_date=end,
                data_limit_gb=service_data.data_limit_gb,
                created_by_id=creator.id,
            )
            session.add(managed_service)
            session.flush()

            all_configs_list = []
            base_port = 20000
            for panel in all_panels:
                try:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    used_ports = set(client.get_used_ports())

                    vless_port = base_port
                    while vless_port in used_ports:
                        vless_port += 1
                    
                    shadowsocks_port = vless_port + 1
                    while shadowsocks_port in used_ports:
                        shadowsocks_port += 1

                    remark_with_user = f"{panel.remark_prefix}-{creator.remark}"
                    
                    vless_remark = f"{remark_with_user}-{vless_port}"
                    vless_result = client.create_vless_inbound(
                        remark=vless_remark,
                        domain=panel.domain,
                        port=vless_port,
                        expiry_days=service_data.duration_days,
                        limit_gb=service_data.data_limit_gb
                    )

                    shadowsocks_remark = f"{remark_with_user}-{shadowsocks_port}"
                    shadowsocks_result = client.create_shadowsocks_inbound(
                        remark=shadowsocks_remark,
                        domain=panel.domain,
                        port=shadowsocks_port,
                        expiry_days=service_data.duration_days,
                        limit_gb=service_data.data_limit_gb
                    )

                    vless_panel_config = PanelConfig(managed_service_id=managed_service.id, panel_id=panel.id, panel_inbound_id=vless_result["inbound_id"], config_link=vless_result["link"])
                    ss_panel_config = PanelConfig(managed_service_id=managed_service.id, panel_id=panel.id, panel_inbound_id=shadowsocks_result["inbound_id"], config_link=shadowsocks_result["link"])
                    session.add_all([vless_panel_config, ss_panel_config])

                    all_configs_list.extend([vless_result["link"], shadowsocks_result["link"]])

                except Exception as e:
                    session.rollback()
                    raise HTTPException(status_code=500, detail=f"خطا در ایجاد کانفیگ روی پنل {panel.url}: {e}")

            subscription_content = "\n".join(all_configs_list)
            base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
            subs_dir = "static/subs"
            os.makedirs(subs_dir, exist_ok=True)
            file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
            with open(file_path, "w") as f:
                f.write(base64_content)
            
            base_url = str(request.base_url).rstrip('/')
            subscription_url = f"{base_url}/static/subs/{service_uuid}.txt"
            managed_service.subscription_link = subscription_url
            session.commit()
            
            return {"status": "success", "subscription_link": subscription_url}

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

        if service.created_by_id != current_user.id:
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
                print(f"خطا در آپدیت کانفیگ روی پنل {p_config.panel.url}: {e}")
                # ادامه می‌دهیم تا پنل‌های دیگر آپدیت شوند

        service.data_limit_gb = update_data.data_limit_gb
        service.end_date = new_end_date
        session.commit()

        return {"status": "success", "message": f"سرویس {service_uuid} با موفقیت آپدیت شد."}

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

        if service.created_by_id != current_user.id:
            raise HTTPException(status_code=403, detail="شما اجازه دسترسی به این سرویس را ندارید.")

        for p_config in service.configs:
            try:
                panel = p_config.panel
                client = XUIClient(panel.url, panel.username, panel.password)
                client.delete_inbound(p_config.panel_inbound_id)
            except Exception as e:
                print(f"خطای غیربحرانی: حذف کانفیگ {p_config.panel_inbound_id} از پنل {panel.url} با مشکل مواجه شد: {e}")
            session.delete(p_config)
        
        if service.subscription_link:
            file_name = service.subscription_link.split("/")[-1]
            file_path = os.path.join("static/subs", file_name)
            if os.path.exists(file_path):
                os.remove(file_path)

        session.delete(service)
        session.commit()
        return {"status": "success", "message": f"سرویس {service_uuid} با موفقیت حذف شد."}

@api.delete("/services/inactive")
async def delete_inactive_services(
    current_user: User = Depends(get_current_user)
):
    """تمام سرویس‌های غیرفعال را حذف می‌کند (فقط ادمین اصلی)."""
    if current_user.username != "hkhatiri":
        raise HTTPException(status_code=403, detail="شما اجازه انجام این عملیات را ندارید.")

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
                        print(f"خطای غیربحرانی: حذف کانفیگ {p_config.panel_inbound_id} از پنل {panel.url} با مشکل مواجه شد: {e}")
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
async def get_service_stats(service_uuid: str,current_user: User = Depends(get_current_user)):
    """
    زمان و حجم باقی‌مانده یک سرویس را برمی‌گرداند.
    """
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