import reflex as rx
from .models import Panel, Backup
from .auth_state import AuthState
from sqlmodel import select
from typing import List
from datetime import datetime
import requests
import os

BACKUP_DIR = os.path.join("static", "backups")

class PanelManageState(AuthState):
    panels: List[Panel] = []
    show_dialog: bool = False
    panel_to_edit: Panel | None = None

    def load_panels(self):
        self.check_auth()
        with rx.session() as session:
            self.panels = session.exec(select(Panel)).all()

    def change_dialog_state(self, show: bool):
        self.show_dialog = show
        if not show:
            self.panel_to_edit = None

    def open_edit_dialog(self, panel: Panel):
        self.panel_to_edit = panel
        self.change_dialog_state(True)

    def save_panel(self, form_data: dict):
        with rx.session() as session:
            if self.panel_to_edit:
                panel = session.get(Panel, self.panel_to_edit.id)
                for key, value in form_data.items():
                    setattr(panel, key, value)
            else:
                panel = Panel(**form_data)
                session.add(panel)
            
            session.commit()
            session.refresh(panel)
        
        self.load_panels()
        self.change_dialog_state(False)

    def delete_panel(self, panel_id: int):
        with rx.session() as session:
            panel = session.get(Panel, panel_id)
            if panel:
                session.delete(panel)
                session.commit()
        self.load_panels()

    async def manual_backup(self, panel_id: int):
        try:
            with rx.session() as session:
                panel = session.get(Panel, panel_id)
                if not panel: return
                session_req = requests.Session()
                res = session_req.post(f"{panel.url.rstrip('/')}/login", data={'username': panel.username, 'password': panel.password}, timeout=10)
                res.raise_for_status()
                res_db = session_req.get(f"{panel.url.rstrip('/')}/server/getDb", timeout=20)
                res_db.raise_for_status()
                panel_backup_dir = os.path.join(BACKUP_DIR, str(panel.id))
                os.makedirs(panel_backup_dir, exist_ok=True)
                date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"manual_backup_{date_str}.db"
                local_file_path = os.path.join(panel_backup_dir, file_name)
                with open(local_file_path, "wb") as f: f.write(res_db.content)
                new_backup = Backup(panel_id=panel.id, file_name=file_name, file_path=f"/static/backups/{panel.id}/{file_name}")
                session.add(new_backup)
                session.commit()
        except Exception as e: print(f"خطا در بکاپ فوری: {e}")

# --- UI Components ---
def panel_card(panel: Panel) -> rx.Component:
    """A card to display panel info with all action buttons."""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.heading(panel.remark_prefix, size="5"),
                rx.spacer(),
                # ✨ FIX: Replaced python `if/else` with `rx.cond`
                rx.cond(
                    panel.domain,
                    rx.badge(panel.domain, color_scheme="gray"),
                    rx.text("") # Render empty text if no domain
                ),
                align="center"
            ),
            rx.text(panel.url, color_scheme="gray", size="2"),
            rx.divider(),
            rx.hstack(
                rx.button("ویرایش", on_click=lambda: PanelManageState.open_edit_dialog(panel), variant="outline", icon="edit"),
                rx.button("بکاپ فوری", on_click=lambda: PanelManageState.manual_backup(panel.id), variant="outline", icon="download"),
                rx.link(rx.button("مدیریت بکاپ", variant="soft", icon="database"), href=f"/panels/{panel.id}/backups"),
                rx.spacer(),
                rx.button("حذف", on_click=lambda: PanelManageState.delete_panel(panel.id), color_scheme="red", variant="surface"),
                width="100%",
                spacing="3",
            ),
            spacing="3",
            width="100%"
        )
    )

def add_edit_panel_dialog() -> rx.Component:
    """A dialog for adding or editing a panel."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.cond(
                    PanelManageState.panel_to_edit,
                    "ویرایش پنل",
                    "افزودن پنل جدید"
                )
            ),
            rx.form(
                rx.vstack(
                    rx.input(placeholder="نام نمایشی", name="name", default_value=PanelManageState.panel_to_edit.remark_prefix, required=True),
                    rx.input(placeholder="آدرس پنل (بدون http)", name="url", default_value=PanelManageState.panel_to_edit.url, required=True),
                    rx.input(placeholder="دامنه (اختیاری)", name="domain", default_value=PanelManageState.panel_to_edit.domain),
                    # ✨ Field added
                    rx.input(placeholder="پیشوند Remark (اختیاری)", name="remark_prefix", default_value=PanelManageState.panel_to_edit.remark_prefix),
                    rx.input(placeholder="نام کاربری", name="username", default_value=PanelManageState.panel_to_edit.username, required=True),
                    rx.input(placeholder="رمز عبور", name="password", type="password", default_value=PanelManageState.panel_to_edit.password, required=True),
                    rx.hstack(
                        rx.dialog.close(rx.button("انصراف", variant="soft", color_scheme="gray")),
                        rx.button("ذخیره", type="submit"),
                        justify="end",
                        spacing="3",
                        width="100%",
                        padding_top="1em"
                    ),
                    spacing="3",
                ),
                on_submit=PanelManageState.save_panel,
                reset_on_submit=True,
            ),
        ),
        open=PanelManageState.show_dialog,
        on_open_change=PanelManageState.change_dialog_state,
    )

def panels_page() -> rx.Component:
    """The main panel management page."""
    return rx.vstack(
        add_edit_panel_dialog(),
        rx.hstack(
            rx.heading("مدیریت پنل‌ها", size="8"),
            rx.spacer(),
            rx.button("افزودن پنل", on_click=lambda: PanelManageState.change_dialog_state(True), icon="plus", size="3"),
            align="center",
            width="100%",
            margin_bottom="1em",
        ),
        rx.grid(
            rx.foreach(PanelManageState.panels, panel_card),
            columns={"initial": "1", "md": "2", "lg": "3"},
            spacing="4",
            width="100%"
        ),
        on_mount=PanelManageState.load_panels,
        width="100%",
        align="center",
        spacing="4",
        padding="2em"
    )

# --- Backups Page (No Changes) ---
class PanelBackupsState(AuthState):
    panel: Panel | None = None
    backups: list[Backup] = []
    def load_backups(self):
        self.check_auth()
        panel_id = self.router.page.params.get("panel_id")
        if not panel_id: return rx.redirect("/panels")
        with rx.session() as session:
            self.panel = session.get(Panel, int(panel_id))
            if self.panel: self.backups = sorted(self.panel.backups, key=lambda b: b.created_at, reverse=True)

def backup_table_row(backup: Backup):
    return rx.table.row(rx.table.cell(backup.file_name), rx.table.cell(backup.created_at.to_string()), rx.table.cell(rx.link(rx.button("دانلود", variant="outline", icon="download"), href=backup.file_path, download=True)), align="center")

def backups_page() -> rx.Component:
    return rx.vstack(rx.cond(PanelBackupsState.panel, rx.vstack(rx.hstack(rx.heading("بکاپ‌های پنل: ", size="7"), rx.heading(PanelBackupsState.panel.remark_prefix, size="7", color_scheme="blue"), align="center"), rx.divider(margin_y="1em"), rx.cond(PanelBackupsState.backups, rx.card(rx.table.root(rx.table.header(rx.table.row(rx.table.column_header_cell("نام فایل"), rx.table.column_header_cell("تاریخ ایجاد"), rx.table.column_header_cell("عملیات"))), rx.table.body(rx.foreach(PanelBackupsState.backups, backup_table_row)), variant="surface", width="100%")), rx.text("هیچ بکاپی یافت نشد.")), width="100%", align="center", spacing="4"), rx.center(rx.spinner(size="3"), height="80vh")), on_mount=PanelBackupsState.load_backups, padding="2em", width="100%")