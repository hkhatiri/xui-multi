# xui_multi/models.py

from sqlmodel import Field, Relationship, SQLModel
from typing import List, Optional
import reflex as rx
import datetime

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    remark: Optional[str] = Field(default=None)
    api_key: Optional[str] = Field(default=None, unique=True, index=True) # <<< این خط اضافه شد

class ManagedService(rx.Model, table=True):
    name: str
    uuid: str
    start_date: datetime.datetime
    end_date: datetime.datetime
    data_limit_gb: float
    data_used_gb: float = 0.0
    status: str = "active"
    protocol: str = "vless"  # Added protocol field
    subscription_link: str = ""
    created_by_id: Optional[int] = Field(default=None, foreign_key="user.id")
    creator: Optional[User] = Relationship()
    configs: List["PanelConfig"] = Relationship(back_populates="managed_service")

class Panel(rx.Model, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    username: str
    password: str
    domain: str
    remark_prefix: str
    configs: List["PanelConfig"] = Relationship(back_populates="panel")
    status: str = "نامشخص"
    cookie: Optional[str] = Field(default=None)
    backups: List["Backup"] = Relationship(back_populates="panel")
    online_users: int = 0
    total_traffic_gb: float = 0.0

class PanelConfig(rx.Model, table=True):
    managed_service_id: Optional[int] = Field(default=None, foreign_key="managedservice.id")
    panel_id: Optional[int] = Field(default=None, foreign_key="panel.id")
    panel_inbound_id: int
    config_link: str
    managed_service: Optional[ManagedService] = Relationship(back_populates="configs")
    panel: Optional[Panel] = Relationship(back_populates="configs")

class Backup(rx.Model, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id")
    file_name: str
    file_path: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    panel: "Panel" = Relationship(back_populates="backups")