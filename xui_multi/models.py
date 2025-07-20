from sqlmodel import Field, Relationship, SQLModel
from typing import List, Optional
import reflex as rx
import datetime

class ManagedService(rx.Model, table=True):
    name: str
    uuid: str
#    protocol: str
    start_date: datetime.datetime
    end_date: datetime.datetime
    data_limit_gb: float
    data_used_gb: float = 0.0
    status: str = "active"
    subscription_link: str = ""
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

class PanelConfig(rx.Model, table=True):
    managed_service_id: Optional[int] = Field(default=None, foreign_key="managedservice.id")
    panel_id: Optional[int] = Field(default=None, foreign_key="panel.id")
    panel_inbound_id: int
    config_link: str
    managed_service: Optional[ManagedService] = Relationship(back_populates="configs")
    panel: Optional[Panel] = Relationship(back_populates="configs")
    
from datetime import datetime
class Backup(rx.Model, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id")
    file_name: str
    file_path: str
    created_at: datetime = Field(default_factory=datetime.now)
    panel: Panel = Relationship(back_populates="backups")
