from fastapi import FastAPI, Request, HTTPException, Depends
import pydantic
import reflex as rx
from typing import List, Literal
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import os
from .models import ManagedService, Panel, PanelConfig
from .xui_client import XUIClient
import traceback # <--- این را ایمپورت کنید

api = FastAPI()

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
    # is_active: bool # این فیلد در مدل شما وجود ندارد
    status: str
    end_date: datetime
    class Config:
        from_attributes = True

async def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if api_key != "SECRET_KEY_12345":
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True


@api.post("/service")
async def create_service(request: Request, service_data: CreateServiceRequest, is_auth: bool = Depends(verify_api_key)):
    # ... (این تابع بدون تغییر باقی می‌ماند)
    service_uuid = str(uuid4())
    start = datetime.now()
    end = start + timedelta(days=service_data.duration_days)
    with rx.session() as session:
        managed_service = ManagedService(name=service_data.name, uuid=service_uuid, protocol=service_data.protocol, start_date=start, end_date=end, data_limit_gb=service_data.data_limit_gb)
        session.add(managed_service)
        session.flush()
        all_panels = session.query(Panel).all()
        if not all_panels: raise HTTPException(status_code=500, detail="No panels configured.")
        all_configs_list = []
        base_port = 20000
        for panel in all_panels:
            try:
                client = XUIClient(panel.url, panel.username, panel.password)
                used_ports = set(client.get_used_ports())
                new_port = base_port
                while new_port in used_ports: new_port += 1
                remark = f"{panel.remark_prefix}-{new_port}"
                if service_data.protocol == "vless":
                    result = client.create_vless_inbound(remark=remark, domain=panel.domain, port=new_port, expiry_days=service_data.duration_days, limit_gb=service_data.data_limit_gb)
                elif service_data.protocol == "shadowsocks":
                    result = client.create_shadowsocks_inbound(remark=remark, domain=panel.domain, port=new_port, expiry_days=service_data.duration_days, limit_gb=service_data.data_limit_gb)
                else:
                    raise HTTPException(status_code=400, detail=f"Unsupported protocol: {service_data.protocol}")
                panel_config = PanelConfig(managed_service_id=managed_service.id, panel_id=panel.id, panel_inbound_id=result["inbound_id"], config_link=result["link"])
                session.add(panel_config)
                all_configs_list.append(result["link"])
            except Exception as e:
                session.rollback()
                raise HTTPException(status_code=500, detail=f"Failed on panel {panel.url}: {str(e)}")
        subscription_content = "\n".join(all_configs_list)
        base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
        subs_dir = "static/subs"
        file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
        with open(file_path, "w") as f: f.write(base64_content)
        base_url = str(request.base_url)
        subscription_url = f"{base_url}static/subs/{service_uuid}.txt"
        managed_service.subscription_link = subscription_url
        session.commit()
        return {"status": "success", "service_uuid": service_uuid, "individual_configs": all_configs_list, "subscription_link": subscription_url}

@api.get("/service/{service_uuid}", response_model=ServiceStatusResponse)
async def get_service_status(service_uuid: str, is_auth: bool = Depends(verify_api_key)):
    # ... (این تابع بدون تغییر باقی می‌ماند)
    with rx.session() as session:
        service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
        if not service: raise HTTPException(status_code=404, detail="Service not found")
        return service


# --- تابع حذف اصلاح شده ---
@api.delete("/service/{service_uuid}")
async def delete_service(service_uuid: str, is_auth: bool = Depends(verify_api_key)):
    try:
        with rx.session() as session:
            service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
            if not service:
                raise HTTPException(status_code=404, detail="Service not found")

            panel_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
            
            for p_config in panel_configs:
                try:
                    panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                    client = XUIClient(panel.url, panel.username, panel.password)
                    client.delete_inbound(p_config.panel_inbound_id)
                except Exception as e:
                    print(f"NON-FATAL ERROR: Could not delete inbound {p_config.panel_inbound_id} from panel {panel.url}: {e}")

                session.delete(p_config)
            
            session.delete(service)
            session.commit()
        return {"status": "success", "message": f"Service {service_uuid} deleted."}
    except Exception as e:
        # اگر هر خطای پیش‌بینی نشده‌ای رخ دهد، آن را به صورت JSON برمی‌گردانیم تا سرور کرش نکند
        tb_str = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"A critical error occurred: {str(e)}\nTraceback:\n{tb_str}")