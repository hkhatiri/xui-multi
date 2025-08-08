# xui_multi/xui_client.py

import base64
import httpx
import json
import urllib.parse
from uuid import uuid4
from datetime import datetime, timedelta
import os
from typing import Optional, Dict, List, Any

# Configure logging
import logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class XUIClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.session_cookie = self._login()

    def _login(self):
        login_url = f"{self.base_url}/login"
        try:
            with httpx.Client() as client:
                response = client.post(login_url, data={"username": self.username, "password": self.password})
                response.raise_for_status()
                if "session" not in response.cookies:
                    raise Exception("Login failed: 'session' cookie not found.")
                return {"session": response.cookies["session"]}
        except Exception as e:
            raise Exception(f"Login failed for panel {self.base_url}: {e}")

    def _get_inbounds_list(self):
        list_url = f"{self.base_url}/panel/inbound/list"
        with httpx.Client(cookies=self.session_cookie) as client:
            response = client.post(list_url)
            response.raise_for_status()
            data = response.json()
            if data and data.get("success"):
                return data.get("obj", [])
        raise Exception("Failed to get inbounds list.")

    def get_inbound(self, inbound_id: int):
        try:
            all_inbounds = self._get_inbounds_list()
            for inbound in all_inbounds:
                if inbound.get("id") == inbound_id:
                    return inbound
            return None
        except Exception as e:
            logger.error(f"Error getting inbound {inbound_id} from {self.base_url}: {e}")
            raise

    def _construct_config_link(self, inbound_data, domain, config_remark: Optional[str] = None):
        protocol = inbound_data.get("protocol")
        
        if config_remark is None:
            config_remark = inbound_data.get("remark", "")
            
        remark = urllib.parse.quote(config_remark)
        port = inbound_data.get("port")
        settings_str = inbound_data.get("settings", "{}")
        settings = json.loads(settings_str)

        if protocol == "vless":
            uuid = settings["clients"][0]["id"]
            return f"vless://{uuid}@{domain}:{port}?type=tcp&security=none&headerType=http#{remark}"

        elif protocol == "shadowsocks":
            password = settings["clients"][0].get("password")
            method = settings["clients"][0].get("method")
            encoded_part = base64.b64encode(f"{method}:{password}".encode()).decode()
            return f"ss://{encoded_part}@{domain}:{port}#{remark}"

        raise ValueError(f"Link construction for protocol '{protocol}' is not supported.")

    def _create_inbound(self, payload, domain, config_remark: Optional[str] = None):
        add_url = f"{self.base_url}/panel/inbound/add"
        with httpx.Client(cookies=self.session_cookie) as client:
            response = client.post(add_url, data=payload)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise Exception(f"Failed to create inbound: {result.get('msg')}")
            
            # Wait a moment for the inbound to be properly created
            import time
            time.sleep(1)
            
            inbound_id = self._get_id_from_remark(payload['remark'])
            if inbound_id is None:
                # Try again after a longer delay
                time.sleep(2)
                inbound_id = self._get_id_from_remark(payload['remark'])
                if inbound_id is None:
                    raise Exception(f"Could not find inbound with remark '{payload['remark']}' after creation")
            
            inbound_data = self.get_inbound(inbound_id)
            if not inbound_data:
                raise Exception(f"Could not get inbound data for ID {inbound_id}")
            
            config_link = self._construct_config_link(inbound_data, domain, config_remark)
            return {"link": config_link, "inbound_id": inbound_id}

    def create_vless_inbound(self, remark, domain, port, expiry_days, limit_gb, config_remark: Optional[str] = None, expiry_time_ms: Optional[int] = None, total_gb_bytes: Optional[int] = None):
        if expiry_time_ms is None:
            expiry_time_ms = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000)
        if total_gb_bytes is None:
            total_gb_bytes = int(limit_gb * 1024 * 1024 * 1024)

        client_id = str(uuid4())
        # Use remark as email since remark is now unique
        settings = {"clients": [{"id": client_id, "email": remark, "totalGB": total_gb_bytes, "expiryTime": expiry_time_ms, "enable": True}], "decryption": "none", "fallbacks": []}
        stream_settings = {"network": "tcp", "security": "none", "tcpSettings": {"header": {"type": "http", "request": {"version": "1.1", "method": "GET", "path": ["/"], "headers": {}}, "response": {"version": "1.1", "status": "200", "reason": "OK", "headers": {}}}}}
        sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic", "fakedns"]}

        inbound_payload = {
            "remark": remark, "port": port, "protocol": "vless", "enable": "true",
            "expiryTime": expiry_time_ms, "total": total_gb_bytes, "listen": "",
            "settings": json.dumps(settings),
            "streamSettings": json.dumps(stream_settings),
            "sniffing": json.dumps(sniffing)
        }
        return self._create_inbound(inbound_payload, domain, config_remark)

    def create_shadowsocks_inbound(self, remark, domain, port, expiry_days, limit_gb, config_remark: Optional[str] = None, expiry_time_ms: Optional[int] = None, total_gb_bytes: Optional[int] = None):
        if expiry_time_ms is None:
            expiry_time_ms = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000)
        if total_gb_bytes is None:
            total_gb_bytes = int(limit_gb * 1024 * 1024 * 1024)

        method = "chacha20-ietf-poly1305"
        main_password = base64.b64encode(os.urandom(32)).decode('utf-8')
        client_password = base64.b64encode(os.urandom(32)).decode('utf-8')

        # Use remark as email since remark is now unique
        settings = {
            "method": method, "password": main_password,
            "clients": [{"method": method, "password": client_password, "email": remark, "totalGB": total_gb_bytes, "expiryTime": expiry_time_ms, "enable": True}]
        }
        stream_settings = {"network": "tcp", "security": "none", "tcpSettings": {"header": {"type": "none"}}}
        sniffing = {"enabled": True, "destOverride": ["http", "tls", "quic", "fakedns"]}

        inbound_payload = {
            "remark": remark, "port": port, "protocol": "shadowsocks", "enable": "true",
            "expiryTime": expiry_time_ms, "total": total_gb_bytes, "listen": "",
            "settings": json.dumps(settings),
            "streamSettings": json.dumps(stream_settings),
            "sniffing": json.dumps(sniffing)
        }
        return self._create_inbound(inbound_payload, domain, config_remark)

    def update_inbound(self, inbound_id: int, new_total_gb: int, new_expiry_time_ms: int) -> bool:
        original_inbound = self.get_inbound(inbound_id)
        if not original_inbound:
            raise Exception(f"Cannot update: Inbound {inbound_id} not found.")

        settings = json.loads(original_inbound.get("settings", "{}"))

        if "clients" not in settings or not settings["clients"]:
            raise Exception("No clients found in settings to update.")

        if original_inbound.get("protocol") == "shadowsocks":
            settings["clients"][0]["method"] = "chacha20-ietf-poly1305"

        settings["clients"][0]["totalGB"] = new_total_gb
        settings["clients"][0]["expiryTime"] = new_expiry_time_ms

        new_settings_str = json.dumps(settings)

        client_uuid = settings["clients"][0].get("id")
        if client_uuid:
            update_client_url = f"{self.base_url}/panel/inbound/updateClient/{client_uuid}"
            client_payload = {'id': inbound_id, 'settings': new_settings_str}
            with httpx.Client(cookies=self.session_cookie) as client:
                client_response = client.post(update_client_url, data=client_payload)
                if not (client_response.status_code == 200 and client_response.json().get('success')):
                     logger.error(f"updateClient call failed for {client_uuid}: {client_response.text}")

        update_inbound_url = f"{self.base_url}/panel/inbound/update/{inbound_id}"

        update_payload = {
            "id": original_inbound.get("id"),
            "enable": True,
            "remark": original_inbound.get("remark"),
            "expiryTime": new_expiry_time_ms,
            "total": new_total_gb,
            "settings": new_settings_str,
            "streamSettings": original_inbound.get("streamSettings", {}),
            "port": original_inbound.get("port"),
            "protocol": original_inbound.get("protocol"),
            "sniffing": original_inbound.get("sniffing", {}),
            "listen": original_inbound.get("listen", ""),
        }

        with httpx.Client(cookies=self.session_cookie) as client:
            response = client.post(update_inbound_url, json=update_payload)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise Exception(f"Main inbound update failed. Panel response: {result.get('msg')}")

        return True

    def update_inbound_simple(self, inbound_id: int, expiry_days: int, limit_gb: int) -> bool:
        """به‌روزرسانی ساده inbound با روزهای انقضا و محدودیت حجم"""
        try:
            # Convert expiry_days to milliseconds
            expiry_time_ms = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000)
            
            # Convert limit_gb to bytes
            total_gb_bytes = limit_gb * 1024 * 1024 * 1024
            
            return self.update_inbound(inbound_id, total_gb_bytes, expiry_time_ms)
        except Exception as e:
            logger.error(f"Error updating inbound {inbound_id}: {e}")
            raise

    def get_all_inbounds_data(self) -> List[Dict[str, Any]]:
        """تمام دیتای inbound ها را یکبار دریافت می‌کند برای کش کردن"""
        try:
            all_inbounds = self._get_inbounds_list()
            return all_inbounds
        except Exception as e:
            logger.error(f"Error getting all inbounds data from {self.base_url}: {e}")
            return []

    def get_inbound_traffic_gb(self, inbound_id: int) -> float:
        inbound_data = self.get_inbound(inbound_id)
        if not inbound_data: return 0.0
        try:
            up = inbound_data.get("up", 0)
            down = inbound_data.get("down", 0)
            return (up + down) / (1024 * 1024 * 1024)
        except (json.JSONDecodeError, IndexError):
            return 0.0

    def get_all_inbounds_traffic(self) -> dict:
        """مجموع ترافیک آپلود و دانلود را برای همه ورودی‌ها دریافت می‌کند."""
        all_inbounds = self._get_inbounds_list()
        total_up = 0
        total_down = 0
        for inbound in all_inbounds:
            total_up += inbound.get("up", 0)
            total_down += inbound.get("down", 0)
        return {"up": total_up, "down": total_down}

    def get_online_clients_count(self) -> int:
        """تعداد کاربران آنلاین را دریافت می‌کند."""
        onlines_url = f"{self.base_url}/panel/inbound/onlines"
        try:
            with httpx.Client(cookies=self.session_cookie) as client:
                response = client.post(onlines_url)
                response.raise_for_status()
                data = response.json()
                if data and data.get("success"):
                    online_clients = data.get("obj")
                    return len(online_clients or [])
                return 0
        except Exception as e:
            logger.error(f"Could not get online clients from {self.base_url}: {e}")
            return 0

    def get_used_ports(self):
        all_inbounds = self._get_inbounds_list()
        return [inbound.get("port") for inbound in all_inbounds]

    def _get_id_from_remark(self, remark):
        all_inbounds = self._get_inbounds_list()
        for inbound in all_inbounds:
            if inbound.get("remark") == remark: 
                return inbound.get("id")
        logger.error(f"Could not find inbound with remark '{remark}' after creation.")
        # Instead of raising exception, return None and let caller handle it
        return None

    def delete_inbound(self, inbound_id: int):
        del_url = f"{self.base_url}/panel/inbound/del/{inbound_id}"
        with httpx.Client(cookies=self.session_cookie) as client:
            response = client.post(del_url)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"): raise Exception(f"Failed to delete inbound {inbound_id}: {result.get('msg')}")
        return True

    def disable_inbound(self, inbound_id: int):
        """غیرفعال کردن inbound بدون حذف آن"""
        try:
            inbound_data = self.get_inbound(inbound_id)
            if not inbound_data:
                raise Exception(f"Inbound {inbound_id} not found")
            
            update_url = f"{self.base_url}/panel/inbound/update/{inbound_id}"
            update_payload = {
                "id": inbound_id,
                "enable": False,
                "remark": inbound_data.get("remark", ""),
                "expiryTime": inbound_data.get("expiryTime", 0),
                "total": inbound_data.get("total", 0),
                "settings": inbound_data.get("settings", "{}"),
                "streamSettings": inbound_data.get("streamSettings", {}),
                "port": inbound_data.get("port"),
                "protocol": inbound_data.get("protocol"),
                "sniffing": inbound_data.get("sniffing", {}),
                "listen": inbound_data.get("listen", ""),
            }
            
            with httpx.Client(cookies=self.session_cookie) as client:
                response = client.post(update_url, json=update_payload)
                response.raise_for_status()
                result = response.json()
                if not result.get("success"):
                    raise Exception(f"Failed to disable inbound {inbound_id}: {result.get('msg')}")
            
            return True
        except Exception as e:
            logger.error(f"Error disabling inbound {inbound_id}: {e}")
            raise