# xui_multi/panel_page.py

import reflex as rx
from sqlmodel import select
from typing import List, Optional, Dict, Any
from datetime import datetime
import requests
import os

from .models import Panel, Backup
from .auth_state import AuthState
from .xui_client import XUIClient

BACKUP_DIR = os.path.join("static", "backups")

# --- State for Panel Management Page ---
class PanelsState(AuthState):
    panels: List[Panel] = []
    show_dialog: bool = False
    panel_to_edit: Optional[Panel] = None

    def load_panels_with_stats(self):
        """بارگذاری پنل‌ها با آمار با استفاده از کش"""
        self.check_auth()
        
        # بررسی کش برای پنل‌ها
        from .cache_manager import cache_manager, get_cache_key, invalidate_panel_cache
        
        cache_key = get_cache_key('PANEL_LIST')
        cached_panels = cache_manager.get(cache_key)
        
        if cached_panels:
            self.panels = cached_panels
            return
        
        # اگر کش موجود نباشد، از دیتابیس بارگذاری کن
        with rx.session() as session:
            db_panels = session.exec(select(Panel)).all()
            panels_with_stats = []
            for panel in db_panels:
                try:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    panel.online_users = client.get_online_clients_count()
                    traffic_data = client.get_all_inbounds_traffic()
                    total_bytes = traffic_data.get("up", 0) + traffic_data.get("down", 0)
                    panel.total_traffic_gb = round(total_bytes / (1024**3), 2)
                except Exception as e:
                    print(f"Error fetching stats for panel {panel.url}: {e}")
                    panel.online_users = -1
                    panel.total_traffic_gb = -1.0
                panels_with_stats.append(panel)
            
            # ذخیره در کش برای 30 ثانیه
            cache_manager.set(cache_key, panels_with_stats, ttl=30)
            self.panels = panels_with_stats

    def change_dialog_state(self, show: bool):
        self.show_dialog = show
        if not show:
            self.panel_to_edit = None

    def show_add_dialog(self):
        self.panel_to_edit = None
        self.show_dialog = True

    def show_edit_dialog(self, panel: Panel):
        self.panel_to_edit = panel
        self.show_dialog = True

    def save_panel(self, form_data: dict):
        self.check_auth()
        with rx.session() as session:
            panel_to_update = None
            if self.panel_to_edit:
                panel_to_update = session.get(Panel, self.panel_to_edit.id)
                if panel_to_update:
                    panel_to_update.url = form_data["url"]
                    panel_to_update.domain = form_data["domain"]
                    panel_to_update.remark_prefix = form_data["remark_prefix"]
                    panel_to_update.username = form_data["username"]
                    if form_data.get("password"):
                        panel_to_update.password = form_data["password"]
            else:
                panel_to_update = Panel(**form_data)

            session.add(panel_to_update)
            session.commit()
            session.refresh(panel_to_update)

        # حذف کش پنل‌ها
        from .cache_manager import invalidate_panel_cache
        invalidate_panel_cache()
        
        # --- FIX: بستن مودال قبل از نمایش پیغام ---
        self.show_dialog = False
        self.load_panels_with_stats()
        return rx.window_alert("پنل با موفقیت ذخیره شد.")

    def delete_panel(self, panel_id: int):
        self.check_auth()
        with rx.session() as session:
            panel = session.get(Panel, panel_id)
            if panel:
                session.delete(panel)
                session.commit()
                
                # حذف کش پنل‌ها
                from .cache_manager import invalidate_panel_cache
                invalidate_panel_cache()
                
                self.load_panels_with_stats()
                return rx.window_alert("پنل با موفقیت حذف شد.")
        return rx.window_alert("خطا در حذف پنل.")

# --- State for Backups Page ---
class PanelBackupsState(AuthState):
    panel: Optional[Panel] = None
    backup_views: List[Dict[str, Any]] = []
    is_backing_up: bool = False

    @rx.var
    def current_panel_id(self) -> str:
        try:
            path = self.router.url
            parts = path.strip("/").split("/")
            if len(parts) == 3 and parts[0] == "panels" and parts[2] == "backups":
                return parts[1]
        except Exception:
            return "0"
        return "0"

    def load_backups(self):
        self.check_auth()
        with rx.session() as session:
            panel_id_str = self.current_panel_id
            if panel_id_str.isdigit():
                panel_id_int = int(panel_id_str)
                self.panel = session.get(Panel, panel_id_int)
                if self.panel:
                    backups_from_db = session.exec(select(Backup).where(Backup.panel_id == panel_id_int).order_by(Backup.created_at.desc())).all()
                    self.backup_views = [
                        {
                            "id": b.id, "file_name": b.file_name, "file_path": b.file_path,
                            "created_at_formatted": b.created_at.strftime('%Y-%m-%d %H:%M:%S')
                        } for b in backups_from_db
                    ]

    def delete_backup(self, backup_id: int):
        self.check_auth()
        with rx.session() as session:
            backup_to_delete = session.get(Backup, backup_id)
            if backup_to_delete:
                session.delete(backup_to_delete)
                session.commit()
            self.load_backups()

    async def manual_backup(self):
        if not self.panel: return
        self.is_backing_up = True
        yield
        try:
            with rx.session() as session:
                panel_in_session = session.get(Panel, self.panel.id)
                if not panel_in_session: return
                session_req = requests.Session()
                res = session_req.post(f"{panel_in_session.url.rstrip('/')}/login", data={'username': panel_in_session.username, 'password': panel_in_session.password}, timeout=10)
                res.raise_for_status()
                res_db = session_req.get(f"{panel_in_session.url.rstrip('/')}/server/getDb", timeout=20)
                res_db.raise_for_status()
                panel_backup_dir = os.path.join(BACKUP_DIR, str(panel_in_session.id))
                os.makedirs(panel_backup_dir, exist_ok=True)
                date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"manual_backup_{date_str}.db"
                local_file_path = os.path.join(panel_backup_dir, file_name)
                with open(local_file_path, "wb") as f: f.write(res_db.content)
                download_path = f"/static/backups/{panel_in_session.id}/{file_name}"
                new_backup = Backup(panel_id=panel_in_session.id, file_name=file_name, file_path=download_path)
                session.add(new_backup)
                session.commit()
                self.load_backups()
        except Exception as e:
            print(f"خطا در بکاپ دستی: {e}")
            yield rx.window_alert(f"خطا در ایجاد بکاپ: {e}")
        finally:
            self.is_backing_up = False

# --- UI Components ---
def add_edit_panel_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(PanelsState.panel_to_edit, "ویرایش پنل", "افزودن پنل جدید")),
            rx.form(
                rx.vstack(
                    rx.input(placeholder="آدرس پنل", name="url", default_value=rx.cond(PanelsState.panel_to_edit, PanelsState.panel_to_edit.url, ""), required=True),
                    rx.input(placeholder="دامین یا آیپی سرور", name="domain", default_value=rx.cond(PanelsState.panel_to_edit, PanelsState.panel_to_edit.domain, ""), required=True),
                    rx.input(placeholder="remark سرویس", name="remark_prefix", default_value=rx.cond(PanelsState.panel_to_edit, PanelsState.panel_to_edit.remark_prefix, ""), required=True),
                    rx.input(placeholder="نام کاربری", name="username", default_value=rx.cond(PanelsState.panel_to_edit, PanelsState.panel_to_edit.username, ""), required=True),
                    rx.input(placeholder="رمز عبور (برای ویرایش، خالی بگذارید)", name="password", type="password", required=rx.cond(~PanelsState.panel_to_edit, True, False)),
                    rx.hstack(
                        rx.dialog.close(rx.button("انصراف", variant="soft", color_scheme="gray")),
                        rx.button("ذخیره", type="submit"),
                        justify="end", spacing="3", width="100%", padding_top="1em"
                    ),
                    spacing="3",
                ),
                on_submit=PanelsState.save_panel,
                reset_on_submit=True,
            ),
            style={"maxWidth": 450, "direction": "rtl"}
        ),
        open=PanelsState.show_dialog,
        on_open_change=PanelsState.change_dialog_state,
    )

def panel_table() -> rx.Component:
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("عملیات", text_align="center", width="5%"),
                rx.table.column_header_cell("ترافیک مصرفی (GB)", text_align="center"),
                rx.table.column_header_cell("کاربران آنلاین", text_align="center"),
                rx.table.column_header_cell("آدرس پنل", text_align="center"),
                rx.table.column_header_cell("پیشوند", text_align="right"),
            )
        ),
        rx.table.body(
            rx.foreach(
                PanelsState.panels,
                lambda panel: rx.table.row(
                    rx.table.cell(
                        rx.dropdown_menu.root(
                            rx.dropdown_menu.trigger(rx.icon_button(rx.icon("ellipsis-vertical"), variant="soft")),
                            rx.dropdown_menu.content(
                                rx.cond(PanelsState.is_admin, rx.dropdown_menu.item(rx.hstack(rx.icon("pencil", size=16), rx.text("ویرایش پنل")), on_click=lambda: PanelsState.show_edit_dialog(panel))),
                                rx.dropdown_menu.item(rx.hstack(rx.icon("database", size=16), rx.text("مشاهده بکاپ‌ها")), on_click=rx.redirect(f"/panels/{panel.id}/backups")),
                                rx.cond(PanelsState.is_admin, rx.dropdown_menu.separator()),
                                rx.cond(PanelsState.is_admin, rx.dropdown_menu.item(rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف پنل")), color="red", on_click=lambda: PanelsState.delete_panel(panel.id))),
                            ),
                        ),
                        text_align="center"
                    ),
                    rx.table.cell(rx.badge(rx.cond(panel.total_traffic_gb >= 0, panel.total_traffic_gb.to_string(), "خطا"), color_scheme=rx.cond(panel.total_traffic_gb >= 0, "blue", "red"))),
                    rx.table.cell(rx.badge(rx.cond(panel.online_users >= 0, panel.online_users.to_string(), "خطا"), color_scheme=rx.cond(panel.online_users >= 0, "teal", "red"))),
                    rx.table.cell(rx.code(panel.url, style={"direction": "ltr"})),
                    rx.table.cell(panel.remark_prefix),
                ),
            )
        ),
        variant="surface",
    )

def backup_table_row(backup: Dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(
            rx.dropdown_menu.root(
                rx.dropdown_menu.trigger(rx.icon_button(rx.icon("ellipsis-vertical"), variant="soft")),
                rx.dropdown_menu.content(
                    rx.dropdown_menu.item(rx.hstack(rx.icon("download", size=16), rx.text("دانلود")), on_click=rx.download(url=backup["file_path"], filename=backup["file_name"])),
                    rx.cond(PanelBackupsState.is_admin, rx.dropdown_menu.separator()),
                    rx.cond(PanelBackupsState.is_admin, rx.dropdown_menu.item(rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف")), color="red", on_click=lambda: PanelBackupsState.delete_backup(backup["id"]))),
                ),
            ),
            text_align="center"
        ),
        rx.table.cell(rx.text(backup["created_at_formatted"], style={"direction": "ltr"})),
        rx.table.cell(backup["file_name"]),
    )

# --- Pages ---
def panels_page() -> rx.Component:
    return rx.container(
        add_edit_panel_dialog(),
        rx.vstack(
            rx.hstack(
                rx.heading("مدیریت پنل‌های X-UI", size="8"),
                rx.spacer(),
                rx.cond(PanelsState.is_admin, rx.button("افزودن پنل جدید", on_click=PanelsState.show_add_dialog, size="3", high_contrast=True)),
                align="center",
                width="100%",
            ),
            rx.divider(width="100%", margin_y="1.5em"),
            panel_table(),
            spacing="5",
            width="100%",
            padding_x="2em",
        ),
        on_mount=PanelsState.load_panels_with_stats,
    )

def backups_page() -> rx.Component:
    return rx.container(
        rx.cond(
            PanelBackupsState.panel,
            rx.vstack(
                rx.hstack(
                    rx.heading("لیست بکاپ‌های پنل: ", PanelBackupsState.panel.remark_prefix, size="7"),
                    rx.spacer(),
                    rx.cond(PanelBackupsState.is_admin, rx.button("ایجاد بکاپ جدید", icon="download-cloud", on_click=PanelBackupsState.manual_backup, loading=PanelBackupsState.is_backing_up, color_scheme="green")),
                    rx.link(rx.button("بازگشت"), href="/panels"),
                    align="center",
                    width="100%",
                    spacing="4"
                ),
                rx.divider(width="100%", margin_y="1.5em"),
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("عملیات", text_align="center", width="5%"),
                            rx.table.column_header_cell("تاریخ ایجاد", text_align="center"),
                            rx.table.column_header_cell("نام فایل", text_align="right"),
                        )
                    ),
                    rx.table.body(rx.foreach(PanelBackupsState.backup_views, backup_table_row)),
                    variant="surface"
                ),
                spacing="5",
                width="100%",
                padding_x="2em",
            ),
            rx.center(
                rx.vstack(
                    rx.heading("درحال بارگذاری..."),
                    rx.spinner(size="3"),
                ),
                height="50vh"
            )
        ),
        on_mount=PanelBackupsState.load_backups,
    )