from fastapi import FastAPI, Request, HTTPException, Depends
import pydantic
import reflex as rx
from typing import List, Literal
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import os
import threading # <--- ایمپورت جدید برای قفل
from .models import ManagedService, Panel, PanelConfig
from .xui_client import XUIClient

api = FastAPI()
# یک قفل برای اطمینان از اینکه هر بار فقط یک درخواست ساخت سرویس پردازش می‌شود
service_creation_lock = threading.Lock()

# ... (کلاس‌های Pydantic و تابع verify_api_key بدون تغییر) ...
class CreateServiceRequest(pydantic.BaseModel):
    name: str
    protocol: Literal["vless", "shadowsocks"]
    duration_days: int = 30
    data_limit_gb: int = 50

class ServiceStatusResponse(pydantic.BaseModel):
    id: int
    name: str
    uuid: str
    protocol: str
    data_limit_gb: float
    status: str
    end_date: datetime
    subscription_link: str
    class Config:
        from_attributes = True

async def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if api_key != "SECRET_KEY_12345":
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

@api.post("/service")
async def create_service(request: Request, service_data: CreateServiceRequest, is_auth: bool = Depends(verify_api_key)):
    # درخواست‌ها در اینجا منتظر می‌مانند تا قفل آزاد شود
    with service_creation_lock:
        with rx.session() as session:
            # تمام منطق ساخت سرویس که در tasks.py بود، به اینجا منتقل شد
            all_panels = session.query(Panel).all()
            if not all_panels:
                raise HTTPException(status_code=500, detail="No panels configured.")
            
            panels_data = [
                {"id": p.id, "url": p.url, "username": p.username, "password": p.password, "domain": p.domain, "remark_prefix": p.remark_prefix}
                for p in all_panels
            ]

            service_uuid = str(uuid4())
            start = datetime.now()
            end = start + timedelta(days=service_data.duration_days)
            managed_service = ManagedService(
                name=service_data.name, uuid=service_uuid, protocol=service_data.protocol,
                start_date=start, end_date=end, data_limit_gb=service_data.data_limit_gb
            )
            session.add(managed_service)
            session.flush()

            all_configs_list = []
            base_port = 20000
            for panel_data in panels_data:
                try:
                    client = XUIClient(panel_data['url'], panel_data['username'], panel_data['password'])
                    used_ports = set(client.get_used_ports())
                    new_port = base_port
                    while new_port in used_ports: new_port += 1
                    remark = f"{panel_data['remark_prefix']}-{new_port}"
                    if service_data.protocol == "vless":
                        result = client.create_vless_inbound(remark=remark, domain=panel_data['domain'], port=new_port, expiry_days=service_data.duration_days, limit_gb=service_data.data_limit_gb)
                    else: # shadowsocks
                        result = client.create_shadowsocks_inbound(remark=remark, domain=panel_data['domain'], port=new_port, expiry_days=service_data.duration_days, limit_gb=service_data.data_limit_gb)
                    
                    panel_config = PanelConfig(managed_service_id=managed_service.id, panel_id=panel_data['id'], panel_inbound_id=result["inbound_id"], config_link=result["link"])
                    session.add(panel_config)
                    all_configs_list.append(result["link"])
                except Exception as e:
                    session.rollback()
                    raise HTTPException(status_code=500, detail=f"Failed on panel {panel_data['url']}: {str(e)}")

            subscription_content = "\n".join(all_configs_list)
            base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
            subs_dir = "static/subs"
            os.makedirs(subs_dir, exist_ok=True)
            file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
            with open(file_path, "w") as f: f.write(base64_content)
            
            base_url = str(request.base_url)
            subscription_url = f"{base_url}static/subs/{service_uuid}.txt"
            managed_service.subscription_link = subscription_url
            session.commit()
            
            return {
                "status": "success",
                "service_uuid": service_uuid,
                "individual_configs": all_configs_list,
                "subscription_link": subscription_url
            }


@api.get("/service/{service_uuid}", response_model=ServiceStatusResponse)
async def get_service_status(service_uuid: str, is_auth: bool = Depends(verify_api_key)):
    """وضعیت یک سرویس را از دیتابیس می‌خواند."""
    with rx.session() as session:
        service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")
        return service

@api.delete("/service/{service_uuid}")
async def delete_service(service_uuid: str, is_auth: bool = Depends(verify_api_key)):
    """
    این تابع سرویس را حذف می‌کند. چون حذف سریع است، نیازی به Celery ندارد.
    """
    # این منطق بدون تغییر باقی می‌ماند چون باید سریع و مستقیم انجام شود
    with rx.session() as session:
        # ... (منطق کامل حذف که قبلاً داشتیم)
        pass # شما باید منطق کامل حذف را اینجا قرار دهید
    return {"status": "success", "message": f"Service {service_uuid} deleted."}