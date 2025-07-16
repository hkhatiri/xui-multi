import base64
import requests
import json
import uuid as os_uuid
from datetime import datetime, timedelta

class XUIClient:
    """کلاسی برای تعامل با API پنل 3x-ui (مدل Inbound-per-Config)"""
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.login(username, password)

    def login(self, username, password):
        """برای لاگین و گرفتن کوکی جلسه تلاش می‌کند."""
        login_url = f"{self.base_url}/login"
        try:
            r = self.session.post(login_url, data={'username': username, 'password': password}, timeout=10)
            r.raise_for_status()
            if not r.json().get("success"):
                raise ConnectionError(f"Login failed: {r.json().get('msg')}")
        except Exception as e:
            raise ConnectionError(f"Failed to login to {self.base_url}: {e}")

    def create_vless_inbound(self, remark: str, domain: str, port: int, expiry_days: int, limit_gb: int) -> dict:
        client_id = str(os_uuid.uuid4())
        expiry_time = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000) if expiry_days > 0 else 0
        traffic_bytes = int(limit_gb * 1024**3)
        settings = {"clients": [{"id": client_id, "email": f"{remark}@refle.x", "flow": "xtls-rprx-vision"}],"decryption": "none", "fallbacks": []}
        stream_settings = {"network": "ws", "security": "none", "wsSettings": {"path": "/", "headers": {}}}
        payload = {"up": 0, "down": 0, "total": traffic_bytes, "remark": remark, "enable": True, "expiryTime": expiry_time, "port": port, "protocol": "vless", "settings": json.dumps(settings), "streamSettings": json.dumps(stream_settings), "sniffing": json.dumps({"enabled": True, "destOverride": ["http", "tls"]}),}
        add_url = f"{self.base_url}/panel/api/inbounds/add"
        try:
            response = self.session.post(add_url, data=payload, timeout=15)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"): raise Exception(f"API Error: {result.get('msg')}")
            config_link = f"vless://{client_id}@{domain}:{port}?path=%2F&security=none&type=ws#{remark}"
            return {"inbound_id": result["obj"]["id"], "link": config_link}
        except Exception as e: raise ConnectionError(f"Failed to create inbound on {self.base_url}: {e}")
        
    def create_shadowsocks_inbound(self, remark: str, domain: str, port: int, expiry_days: int, limit_gb: int) -> dict:
        """یک inbound جدید از نوع Shadowsocks می‌سازد."""
        password = str(os_uuid.uuid4()) # یک پسورد رندوم
        method = "chacha20-ietf-poly1305"
        expiry_time = int((datetime.now() + timedelta(days=expiry_days)).timestamp() * 1000) if expiry_days > 0 else 0
        traffic_bytes = int(limit_gb * 1024**3)

        settings = {"password": password, "method": method, "network": "tcp,udp"}
        
        payload = {
            "up": 0, "down": 0, "total": traffic_bytes, "remark": remark,
            "enable": True, "expiryTime": expiry_time, "port": port, "protocol": "shadowsocks",
            "settings": json.dumps(settings),
            "streamSettings": json.dumps({"network": "tcp"}), # تنظیمات ساده برای شدوساکس
            "sniffing": json.dumps({"enabled": True, "destOverride": ["http", "tls"]}),
        }
        
        add_url = f"{self.base_url}/panel/api/inbounds/add"
        try:
            response = self.session.post(add_url, data=payload, timeout=15)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise Exception(f"API Error: {result.get('msg')}")
            
            # ساخت لینک کانفیگ Shadowsocks
            auth_str = f"{method}:{password}"
            encoded_auth = base64.b64encode(auth_str.encode()).decode()
            config_link = f"ss://{encoded_auth}@{domain}:{port}#{remark}"
            
            return {"inbound_id": result["obj"]["id"], "link": config_link}
        except Exception as e:
            raise ConnectionError(f"Failed to create inbound on {self.base_url}: {e}")


    def delete_inbound(self, inbound_id: int):
        """یک inbound را با شناسه‌اش حذف می‌کند."""
        del_url = f"{self.base_url}/panel/api/inbounds/del/{inbound_id}"
        try:
            response = self.session.post(del_url, timeout=10)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise Exception(f"API Error: {result.get('msg')}")
        except Exception as e:
            raise ConnectionError(f"Failed to delete inbound {inbound_id} on {self.base_url}: {e}")

    def get_used_ports(self) -> list[int]:
        """لیست تمام پورت‌های در حال استفاده در پنل را برمی‌گرداند."""
        list_url = f"{self.base_url}/panel/api/inbounds/list"
        try:
            response = self.session.get(list_url, timeout=15)
            response.raise_for_status()
            result = response.json()
            if not result.get("success"):
                raise Exception(f"API Error: {result.get('msg')}")
            
            used_ports = [inbound.get("port", 0) for inbound in result.get("obj", [])]
            return [port for port in used_ports if port != 0]
        except Exception as e:
            raise ConnectionError(f"Failed to get used ports from {self.base_url}: {e}")
        
    def get_inbound(self, inbound_id: int) -> dict | None:
        """اطلاعات یک inbound خاص را بر اساس ID آن برمی‌گرداند."""
        get_url = f"{self.base_url}/panel/api/inbounds/get/{inbound_id}"
        try:
            response = self.session.get(get_url, timeout=10)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                return result.get("obj")
            return None
        except Exception as e:
            print(f"Could not get inbound {inbound_id} from {self.base_url}: {e}")
            return None        