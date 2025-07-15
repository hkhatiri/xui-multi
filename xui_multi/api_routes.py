from fastapi import FastAPI, Request, HTTPException, Depends
import pydantic
import reflex as rx
from typing import List
from datetime import datetime, timedelta
from uuid import uuid4

from xui_multi.xui_client import XUIClient

# ایمپورت مدل‌ها
from .models import ManagedService, Panel, PanelConfig

# ساخت یک اپلیکیشن FastAPI برای مدیریت API ها
api = FastAPI()

# --- مدل‌های Pydantic (بدون تغییر) ---
class CreateServiceRequest(pydantic.BaseModel):
    name: str
    duration_days: int = 30
    data_limit_gb: int = 50

class ServiceStatusResponse(pydantic.BaseModel):
    id: int
    name: str
    uuid: str
    data_limit_gb: float
    data_used_gb: float
    end_date: datetime
    is_active: bool

    class Config:
        from_attributes = True

# --- تابع امن‌سازی (بدون تغییر) ---
async def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if api_key != "SECRET_KEY_12345":
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

# --- تعریف اندپوینت‌ها با دکوراتورهای FastAPI ---

@api.post("/service")
async def create_service(service_data: CreateServiceRequest, is_auth: bool = Depends(verify_api_key)):
    # یک شناسه کلی برای این سرویس در سیستم خودمان
    service_uuid = str(uuid4())
    start = datetime.now()
    end = start + timedelta(days=service_data.duration_days)

    with rx.session() as session:
        # 1. ساخت رکورد اصلی سرویس
        managed_service = ManagedService(
            name=service_data.name, uuid=service_uuid, start_date=start, 
            end_date=end, data_limit_gb=service_data.data_limit_gb
        )
        session.add(managed_service)
        session.flush() # برای گرفتن ID سرویس قبل از commit نهایی

        all_panels = session.query(Panel).all()
        if not all_panels:
            raise HTTPException(status_code=500, detail="No panels configured.")
        
        # 2. به ازای هر پنل یک inbound جدید بساز
        all_configs = []
        # TODO: این مقادیر باید از ورودی یا تنظیمات خوانده شوند
        port = 2082 
        domain = "your-domain.com"
        remark = f"{service_data.name}-{port}"

        for panel in all_panels:
            try:
                client = XUIClient(panel.url, panel.username, panel.password)
                result = client.create_vless_inbound(
                    remark=remark, domain=domain, port=port,
                    expiry_days=service_data.duration_days,
                    limit_gb=service_data.data_limit_gb
                )
                
                # 3. اطلاعات کانفیگ ساخته شده را در دیتابیس ذخیره کن
                panel_config = PanelConfig(
                    managed_service_id=managed_service.id,
                    panel_id=panel.id,
                    panel_inbound_id=result["inbound_id"],
                    config_link=result["link"]
                )
                session.add(panel_config)
                all_configs.append(result["link"])

            except Exception as e:
                # TODO: منطق Rollback در اینجا پیچیده‌تر است و باید پیاده‌سازی شود
                session.rollback()
                raise HTTPException(status_code=500, detail=f"Failed on panel {panel.url}: {str(e)}")
        
        session.commit()
        return {"status": "success", "service_uuid": service_uuid, "configs": all_configs}

@api.delete("/service/{service_uuid}")
async def delete_service(service_uuid: str, is_auth: bool = Depends(verify_api_key)):
    with rx.session() as session:
        service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        # تمام کانفیگ‌های مرتبط با این سرویس را پیدا کن
        panel_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
        
        for p_config in panel_configs:
            try:
                panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                client = XUIClient(panel.url, panel.username, panel.password)
                client.delete_inbound(p_config.panel_inbound_id)
            except Exception as e:
                print(f"Could not delete inbound {p_config.panel_inbound_id} from panel {panel.url}: {e}")

            session.delete(p_config) # حذف رکورد از جدول panel_configs
        
        session.delete(service) # حذف رکورد اصلی سرویس
        session.commit()
    return {"status": "success", "message": f"Service {service_uuid} deleted."}


@api.get("/api/service/{uuid}", response_model=ServiceStatusResponse)  # <--- /api اضافه شد
async def get_service_status(uuid: str, is_auth: bool = Depends(verify_api_key)):
    with rx.session() as session:
        service = session.query(ManagedService).filter(ManagedService.uuid == uuid).first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        return service