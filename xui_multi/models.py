import reflex as rx
import datetime
from typing import List, Optional
from sqlmodel import Field, Relationship

# کلاس خالی PanelConfig از اینجا حذف شد.

class ManagedService(rx.Model, table=True):
    """مدل سرویس کلی که کاربر درخواست می‌دهد"""
    name: str
    uuid: str
    start_date: datetime.datetime
    end_date: datetime.datetime
    data_limit_gb: float
    is_active: bool = True
    
    configs: List["PanelConfig"] = Relationship(back_populates="managed_service")

class Panel(rx.Model, table=True):
    """مدل پنل‌ها با فیلدهای جدید"""
    url: str
    username: str
    password: str
    domain: str  # <--- فیلد جدید برای دامنه
    remark_prefix: str
    
    configs: List["PanelConfig"] = Relationship(back_populates="panel")

class PanelConfig(rx.Model, table=True):
    """جدول جدید: اطلاعات کانفیگ هر سرویس روی هر پنل مجزا"""
    managed_service_id: Optional[int] = Field(default=None, foreign_key="managedservice.id")
    panel_id: Optional[int] = Field(default=None, foreign_key="panel.id")
    
    panel_inbound_id: int
    config_link: str

    managed_service: Optional[ManagedService] = Relationship(back_populates="configs")
    panel: Optional[Panel] = Relationship(back_populates="configs")