import reflex as rx
import datetime
from typing import List, Optional
from sqlmodel import Field, Relationship

class ManagedService(rx.Model, table=True):
    name: str
    uuid: str
    protocol: str
    start_date: datetime.datetime
    end_date: datetime.datetime
    data_limit_gb: float
    data_used_gb: float = 0.0
    status: str = "active"
    subscription_link: str = ""
    configs: List["PanelConfig"] = Relationship(back_populates="managed_service")

class Panel(rx.Model, table=True):
    url: str
    username: str
    password: str
    domain: str
    remark_prefix: str
    configs: List["PanelConfig"] = Relationship(back_populates="panel")

class PanelConfig(rx.Model, table=True):
    managed_service_id: Optional[int] = Field(default=None, foreign_key="managedservice.id")
    panel_id: Optional[int] = Field(default=None, foreign_key="panel.id")
    panel_inbound_id: int
    config_link: str
    managed_service: Optional[ManagedService] = Relationship(back_populates="configs")
    panel: Optional[Panel] = Relationship(back_populates="configs")