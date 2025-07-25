from fastapi import FastAPI, Request, HTTPException, Depends
import pydantic
import reflex as rx
from typing import List
from datetime import datetime, timedelta
from uuid import uuid4
import base64
import os
import threading
import json
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

async def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-KEY")
    if api_key != "SECRET_KEY_12345":
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

@api.post("/service")
async def create_service(request: Request, service_data: CreateServiceRequest, is_auth: bool = Depends(verify_api_key)):
    with service_creation_lock:
        with rx.session() as session:
            # Get the current user from the token
            token = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not token:
                raise HTTPException(status_code=401, detail="Missing authorization token")

            creator = session.query(User).filter(User.username == token).first()
            if not creator:
                raise HTTPException(status_code=401, detail="Invalid authorization token")

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
            for panel_data in panels_data:
                try:
                    client = XUIClient(panel_data['url'], panel_data['username'], panel_data['password'])
                    used_ports = set(client.get_used_ports())

                    vless_port = base_port
                    while vless_port in used_ports:
                        vless_port += 1

                    shadowsocks_port = vless_port + 1
                    while shadowsocks_port in used_ports:
                        shadowsocks_port += 1

                    remark = f"{panel_data['remark_prefix']}-{creator.remark}"
                    vless_remark = f"{remark}-{vless_port}"
                    vless_result = client.create_vless_inbound(
                        remark=vless_remark,
                        domain=panel_data['domain'],
                        port=vless_port,
                        expiry_days=service_data.duration_days,
                        limit_gb=service_data.data_limit_gb
                    )

                    shadowsocks_remark = f"{remark}-{shadowsocks_port}"
                    shadowsocks_result = client.create_shadowsocks_inbound(
                        remark=shadowsocks_remark,
                        domain=panel_data['domain'],
                        port=shadowsocks_port,
                        expiry_days=service_data.duration_days,
                        limit_gb=service_data.data_limit_gb
                    )

                    vless_panel_config = PanelConfig(
                        managed_service_id=managed_service.id,
                        panel_id=panel_data['id'],
                        panel_inbound_id=vless_result["inbound_id"],
                        config_link=vless_result["link"]
                    )
                    ss_panel_config = PanelConfig(
                        managed_service_id=managed_service.id,
                        panel_id=panel_data['id'],
                        panel_inbound_id=shadowsocks_result["inbound_id"],
                        config_link=shadowsocks_result["link"]
                    )
                    session.add(vless_panel_config)
                    session.add(ss_panel_config)

                    all_configs_list.append(vless_result["link"])
                    all_configs_list.append(shadowsocks_result["link"])

                except Exception as e:
                    session.rollback()
                    raise HTTPException(status_code=500, detail=f"Failed on panel {panel_data['url']}: {str(e)}")

            subscription_content = "\n".join(all_configs_list)
            base64_content = base64.b64encode(subscription_content.encode('utf-8')).decode('utf-8')
            subs_dir = "static/subs"
            os.makedirs(subs_dir, exist_ok=True)
            file_path = os.path.join(subs_dir, f"{service_uuid}.txt")
            with open(file_path, "w") as f:
                f.write(base64_content)

            base_url = str(request.base_url)
            subscription_url = f"{base_url}static/subs/{service_uuid}.txt"
            managed_service.subscription_link = subscription_url
            session.commit()

            return {
                "status": "success",
                "subscription_link": subscription_url
            }


@api.put("/service/{service_uuid}")
async def update_service(service_uuid: str, update_data: ServiceUpdateRequest, is_auth: bool = Depends(verify_api_key)):
    with rx.session() as session:
        service = session.query(ManagedService).filter(ManagedService.uuid == service_uuid).first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found")

        panel_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()

        # ---> اصلاحیه نهایی: محاسبه حجم و زمان به صورت جایگزینی <---
        new_total_gb = update_data.data_limit_gb
        new_total_gb_bytes = int(new_total_gb * 1024 * 1024 * 1024)

        # زمان انقضای جدید از همین لحظه محاسبه می‌شود
        new_end_date = datetime.now() + timedelta(days=update_data.duration_days)
        new_expiry_time_ms = int(new_end_date.timestamp() * 1000)

        for p_config in panel_configs:
            try:
                panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                client = XUIClient(panel.url, panel.username, panel.password)

                client.update_inbound(
                    inbound_id=p_config.panel_inbound_id,
                    new_total_gb=new_total_gb_bytes,
                    new_expiry_time_ms=new_expiry_time_ms
                )

            except Exception as e:
                import traceback
                raise HTTPException(status_code=500, detail=f"Failed to update on panel {panel.url}: {traceback.format_exc()}")

        # آپدیت مقادیر نهایی در دیتابیس محلی
        service.data_limit_gb = new_total_gb
        service.end_date = new_end_date
        session.commit()

        return {"status": "success", "message": f"Service {service_uuid} updated successfully."}


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

            if service.subscription_link:
                file_name = service.subscription_link.split("/")[-1]
                file_path = os.path.join("static/subs", file_name)
                if os.path.exists(file_path):
                    os.remove(file_path)

            session.delete(service)
            session.commit()
        return {"status": "success", "message": f"Service {service_uuid} deleted."}
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"A critical error occurred: {str(e)}\nTraceback:\n{tb_str}")


@api.delete("/services/inactive")
async def delete_inactive_services(is_auth: bool = Depends(verify_api_key)):
    deleted_count = 0
    errors = []
    with rx.session() as session:
        inactive_services = session.query(ManagedService).filter(
            ManagedService.status.in_(["expired", "limit_reached"])
        ).all()

        if not inactive_services:
            return {"status": "success", "message": "No inactive services to delete.", "deleted_count": 0}

        for service in inactive_services:
            try:
                panel_configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()

                for p_config in panel_configs:
                    try:
                        panel = session.query(Panel).filter(Panel.id == p_config.panel_id).one()
                        client = XUIClient(panel.url, panel.username, panel.password)
                        client.delete_inbound(p_config.panel_inbound_id)
                    except Exception as e:
                        print(f"NON-FATAL: Could not delete inbound {p_config.panel_inbound_id} from panel {panel.url}: {e}")

                    session.delete(p_config)

                if service.subscription_link:
                    file_name = service.subscription_link.split("/")[-1]
                    file_path = os.path.join("static/subs", file_name)
                    if os.path.exists(file_path):
                        os.remove(file_path)

                session.delete(service)
                deleted_count += 1
            except Exception as e:
                errors.append(f"Failed to delete service {service.uuid}: {e}")
                session.rollback()

        session.commit()

    if errors:
        raise HTTPException(status_code=500, detail={"message": "Some services could not be deleted.", "errors": errors})

    return {"status": "success", "message": f"Successfully deleted {deleted_count} inactive services."}