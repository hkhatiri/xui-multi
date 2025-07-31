# xui_multi/admin_page.py

import reflex as rx
from sqlmodel import select, func
from typing import List, Optional
import secrets

from .models import User, ManagedService
from .auth_state import AuthState, hash_password

class AdminState(AuthState):
    users: List[User] = []
    service_counts: dict[int, int] = {}
    total_volumes: dict[int, float] = {}
    show_dialog: bool = False
    admin_to_edit: Optional[User] = None

    @rx.var
    def form_remark(self) -> str:
        if self.admin_to_edit:
            return self.admin_to_edit.remark or ""
        return ""

    def on_load(self):
        self.check_auth()
        self.load_users()

    def load_users(self):
        with rx.session() as session:
            self.users = session.exec(select(User).where(User.username != "hkhatiri")).all()
            for user in self.users:
                self.service_counts[user.id] = session.query(ManagedService).filter(ManagedService.created_by_id == user.id).count()
                self.total_volumes[user.id] = session.query(func.sum(ManagedService.data_limit_gb)).filter(ManagedService.created_by_id == user.id).scalar() or 0.0

    def change_dialog_state(self, show: bool):
        self.show_dialog = show
        if not show:
            self.admin_to_edit = None

    def show_add_dialog(self):
        self.admin_to_edit = None
        self.show_dialog = True

    def show_edit_dialog(self, user: User):
        self.admin_to_edit = user
        self.show_dialog = True

    def save_admin(self, form_data: dict):
        self.check_auth()
        username = form_data.get("username")
        password = form_data.get("password")
        remark = form_data.get("remark")

        if not username:
            return rx.window_alert("نام کاربری نمی‌تواند خالی باشد.")

        with rx.session() as session:
            if self.admin_to_edit:
                user_to_update = session.get(User, self.admin_to_edit.id)
                if user_to_update:
                    user_to_update.username = username
                    user_to_update.remark = remark
                    if password:
                        user_to_update.password_hash = hash_password(password)
                    session.add(user_to_update)
            else:
                if not password:
                    return rx.window_alert("برای کاربر جدید، رمز عبور الزامی است.")
                existing = session.exec(select(User).where(User.username == username)).first()
                if existing:
                    return rx.window_alert(f"کاربری با نام '{username}' از قبل وجود دارد.")
                
                hashed_pw = hash_password(password)
                api_key = secrets.token_hex(20)
                new_user = User(username=username, password_hash=hashed_pw, remark=remark, api_key=api_key)
                session.add(new_user)
            session.commit()

        # --- FIX: بستن مودال قبل از نمایش پیغام ---
        self.show_dialog = False
        self.load_users()
        return rx.window_alert("ادمین با موفقیت ذخیره شد.")


    def delete_user(self, user_id: int):
        self.check_auth()
        with rx.session() as session:
            user_to_delete = session.get(User, user_id)
            if user_to_delete:
                session.delete(user_to_delete)
                session.commit()
            self.load_users()
        return rx.window_alert("ادمین با موفقیت حذف شد.")

    def copy_to_clipboard(self, text: str):
        """کپی کردن متن به کلیپ‌بورد با مدیریت خطا"""
        return rx.call_script(f"""
        try {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText('{text}').then(() => {{
                    alert('کد API با موفقیت کپی شد!');
                }}).catch(() => {{
                    // Fallback for older browsers
                    const textArea = document.createElement('textarea');
                    textArea.value = '{text}';
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    alert('کد API با موفقیت کپی شد!');
                }});
            }} else {{
                // Fallback for browsers without clipboard API
                const textArea = document.createElement('textarea');
                textArea.value = '{text}';
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                alert('کد API با موفقیت کپی شد!');
            }}
        }} catch (error) {{
            alert('خطا در کپی کردن کد API: ' + error.message);
        }}
        """)

# --- UI Components ---
def add_edit_admin_dialog() -> rx.Component:
    """Dialog for adding or editing an admin."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(AdminState.admin_to_edit, "ویرایش ادمین", "افزودن ادمین جدید")),
            rx.form(
                rx.vstack(
                    rx.input(
                        placeholder="نام کاربری",
                        name="username",
                        default_value=rx.cond(AdminState.admin_to_edit, AdminState.admin_to_edit.username, ""),
                        required=True,
                    ),
                    rx.input(
                        placeholder="رمز عبور جدید",
                        name="password",
                        type="password",
                        required=rx.cond(~AdminState.admin_to_edit, True, False),
                    ),
                    rx.input(
                        placeholder="ریمارک",
                        name="remark",
                        default_value=AdminState.form_remark,
                        required=True,
                    ),
                    rx.text(
                        "برای ویرایش، اگر نمی‌خواهید رمز عبور تغییر کند، این فیلد را خالی بگذارید.",
                        size="1",
                        color_scheme="gray",
                        display=rx.cond(AdminState.admin_to_edit, "block", "none"),
                    ),
                    rx.hstack(
                        rx.dialog.close(rx.button("انصراف", variant="soft", color_scheme="gray")),
                        rx.button("ذخیره", type="submit"),
                        justify="end",
                        spacing="3",
                        width="100%",
                        padding_top="1em",
                    ),
                    spacing="3",
                ),
                on_submit=AdminState.save_admin,
                reset_on_submit=True,
            ),
            style={"maxWidth": 450, "direction": "rtl"}
        ),
        open=AdminState.show_dialog,
        on_open_change=AdminState.change_dialog_state,
    )

def admin_table() -> rx.Component:
    """Table for displaying the list of admins."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("عملیات", text_align="center", width="5%"),
                rx.table.column_header_cell("نام کاربری", text_align="right"),
                rx.table.column_header_cell("ریمارک", text_align="center"),
                rx.table.column_header_cell("تعداد سرویس‌ها", text_align="center"),
                rx.table.column_header_cell("حجم کل (GB)", text_align="center"),
            )
        ),
        rx.table.body(
            rx.foreach(
                AdminState.users,
                lambda user: rx.table.row(
                    rx.table.cell(
                        rx.dropdown_menu.root(
                            rx.dropdown_menu.trigger(rx.icon_button(rx.icon("ellipsis-vertical"), variant="soft")),
                            rx.dropdown_menu.content(
                                rx.dropdown_menu.item(rx.hstack(rx.icon("pencil", size=16), rx.text("ویرایش")), on_click=lambda: AdminState.show_edit_dialog(user)),
                                rx.dropdown_menu.separator(),
                                rx.dropdown_menu.item(rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف")), color="red", on_click=lambda: AdminState.delete_user(user.id)),
                                rx.dropdown_menu.item(rx.hstack(rx.icon("copy", size=16), rx.text("کپی کد API")), on_click=lambda: AdminState.copy_to_clipboard(user.api_key)),
                                align="center",
                                spacing="2"
                            )
                        ),
                    ),
                    rx.table.cell(user.username),
                    rx.table.cell(user.remark),
                    rx.table.cell(AdminState.service_counts.get(user.id, 0)),
                    rx.table.cell(AdminState.total_volumes.get(user.id, 0.0)),
                ),
            )
        ),
        variant="surface",
    )

def admin_page() -> rx.Component:
    """The main admin management page."""
    return rx.container(
        add_edit_admin_dialog(),
        rx.vstack(
            rx.hstack(
                rx.heading("مدیریت ادمین‌ها", size="8"),
                rx.spacer(),
                rx.button("افزودن ادمین جدید", on_click=AdminState.show_add_dialog, size="3", high_contrast=True),
                align="center",
                width="100%",
            ),
            rx.divider(width="100%", margin_y="1.5em"),
            admin_table(),
            spacing="5",
            width="100%",
            max_width="800px",
            align="center",
            padding_x="2em",
        ),
        on_mount=AdminState.on_load,
    )