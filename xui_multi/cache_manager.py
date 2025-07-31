import time
import threading
from typing import Dict, Any, Optional
from datetime import datetime, timedelta

class CacheManager:
    def __init__(self):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_lock = threading.Lock()
        self._default_ttl = 30

    def get(self, key: str) -> Optional[Any]:
        """دریافت مقدار از کش"""
        with self._cache_lock:
            if key in self._cache:
                cache_entry = self._cache[key]
                if time.time() < cache_entry['expires_at']:
                    return cache_entry['value']
                else:
                    del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl: int = None) -> None:
        """ذخیره مقدار در کش"""
        if ttl is None:
            ttl = self._default_ttl

        with self._cache_lock:
            self._cache[key] = {
                'value': value,
                'expires_at': time.time() + ttl
            }

    def invalidate(self, key: str) -> None:
        """حذف کلید از کش"""
        with self._cache_lock:
            if key in self._cache:
                del self._cache[key]

    def invalidate_pattern(self, pattern: str) -> None:
        """حذف کلیدهایی که با الگوی خاصی مطابقت دارند"""
        with self._cache_lock:
            keys_to_remove = [key for key in self._cache.keys() if pattern in key]
            for key in keys_to_remove:
                del self._cache[key]

    def clear(self) -> None:
        """پاک کردن تمام کش"""
        with self._cache_lock:
            self._cache.clear()

    def cleanup_expired(self) -> None:
        """حذف کش‌های منقضی شده"""
        current_time = time.time()
        with self._cache_lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if current_time >= entry['expires_at']
            ]
            for key in expired_keys:
                del self._cache[key]

cache_manager = CacheManager()

CACHE_KEYS = {
    'PANEL_STATS': 'panel_stats_{panel_id}',
    'SERVICE_STATS': 'service_stats_{service_id}',
    'TOTAL_TRAFFIC': 'total_traffic',
    'ONLINE_USERS': 'online_users',
    'ALL_SERVICES': 'all_services',
    'PANEL_LIST': 'panel_list',
}

def get_cache_key(key_type: str, **kwargs) -> str:
    """ساخت کلید کش با پارامترهای داده شده"""
    if key_type in CACHE_KEYS:
        return CACHE_KEYS[key_type].format(**kwargs)
    return f"{key_type}_{'_'.join(f'{k}_{v}' for k, v in kwargs.items())}"

def invalidate_service_cache(service_id: int = None):
    """حذف کش مربوط به سرویس‌ها"""
    if service_id:
        cache_manager.invalidate(get_cache_key('SERVICE_STATS', service_id=service_id))
    cache_manager.invalidate_pattern('service_')
    cache_manager.invalidate('ALL_SERVICES')

def invalidate_panel_cache(panel_id: int = None):
    """حذف کش مربوط به پنل‌ها"""
    if panel_id:
        cache_manager.invalidate(get_cache_key('PANEL_STATS', panel_id=panel_id))
    cache_manager.invalidate_pattern('panel_')
    cache_manager.invalidate('PANEL_LIST')

def invalidate_traffic_cache():
    """حذف کش مربوط به ترافیک"""
    cache_manager.invalidate('TOTAL_TRAFFIC')
    cache_manager.invalidate('ONLINE_USERS') 