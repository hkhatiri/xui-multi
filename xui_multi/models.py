# xui_multi/models.py

from typing import List, Optional
import datetime
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import BigInteger

class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    password_hash: str
    api_key: Optional[str] = Field(default=None, unique=True, index=True)
    remark: Optional[str] = Field(default=None)

class ManagedService(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    uuid: str
    name: str
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

class Panel(SQLModel, table=True):
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
    inbound_cache: List["PanelInboundCache"] = Relationship(back_populates="panel")

class PanelConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    managed_service_id: Optional[int] = Field(default=None, foreign_key="managedservice.id")
    panel_id: Optional[int] = Field(default=None, foreign_key="panel.id")
    panel_inbound_id: int
    config_link: str
    managed_service: Optional[ManagedService] = Relationship(back_populates="configs")
    panel: Optional[Panel] = Relationship(back_populates="configs")

class Backup(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id")
    file_name: str
    file_path: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    panel: "Panel" = Relationship(back_populates="backups")

class PanelInboundCache(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    panel_id: int = Field(foreign_key="panel.id")
    inbound_id: int
    remark: Optional[str] = None
    up: int = Field(default=0, sa_column=BigInteger())  # Upload traffic in bytes
    down: int = Field(default=0, sa_column=BigInteger())  # Download traffic in bytes
    total: int = Field(default=0, sa_column=BigInteger())  # Total limit in bytes
    expiry_time: int = Field(default=0, sa_column=BigInteger())  # Expiry time in milliseconds
    enable: bool = Field(default=True)
    protocol: Optional[str] = None
    port: Optional[int] = None
    settings: Optional[str] = None  # JSON settings
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now)
    
    # Relationship
    panel: Panel = Relationship(back_populates="inbound_cache")