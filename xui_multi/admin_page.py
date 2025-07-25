import reflex as rx
from sqlmodel import select
from typing import List, Optional

from .models import User
from .auth_state import AuthState, hash_password
from .template import template

# نام کاربری ادمین اصلی که نباید نمایش داده شود
# این نام باید با چیزی که در auth_state.py تعریف شده یکسان باشد
PRIMARY_ADMIN_USERNAME = "hkhatiri"

class AdminState(AuthState):
    """State برای مدیریت کاربران ادمین با UI جدید."""
    users: List[User] = []
    
    # State برای دیالوگ افزودن/ویرایش
    show_dialog: bool = False
    admin_to_edit: Optional[User] = None
    
    def on_load(self):
        """بارگذاری اولیه کاربران هنگام باز شدن صفحه."""
        self.check_auth()
        self.load_users()

    def load_users(self):
        """
        کاربران را از دیتابیس بارگذاری می‌کند و ادمین اصلی را فیلتر می‌کند.
        """
        with rx.session() as session:
            # ادمین اصلی را از لیست نمایش حذف کن
            self.users = session.exec(
                select(User).where(User.username != PRIMARY_ADMIN_USERNAME)
            ).all()

    def change_dialog_state(self, show: bool):
        """دیالوگ را باز یا بسته می‌کند و فرم را ریست می‌کند."""
        self.show_dialog = show
        if not show:
            self.admin_to_edit = None

    def show_add_dialog(self):
        """دیالوگ را برای افزودن کاربر جدید آماده می‌کند."""
        self.admin_to_edit = None
        self.show_dialog = True

    def show_edit_dialog(self, user: User):
        """دیالوگ را برای ویرایش کاربر موجود آماده می‌کند."""
        self.admin_to_edit = user
        self.show_dialog = True
        
    def save_admin(self, form_data: dict):
        """کاربر جدید را ذخیره یا کاربر موجود را ویرایش می‌کند."""
        self.check_auth()
        username = form_data.get("username")
        password = form_data.get("password")

        if not username:
            return rx.window_alert("نام کاربری نمی‌تواند خالی باشد.")

        with rx.session() as session:
            # اگر در حالت ویرایش هستیم
            if self.admin_to_edit:
                user_to_update = session.get(User, self.admin_to_edit.id)
                if user_to_update:
                    user_to_update.username = username
                    # رمز عبور فقط در صورتی که وارد شده باشد، آپدیت می‌شود
                    if password:
                        user_to_update.password_hash = hash_password(password)
                    session.add(user_to_update)
            # اگر در حالت افزودن هستیم
            else:
                if not password:
                    return rx.window_alert("برای کاربر جدید، رمز عبور الزامی است.")
                
                existing = session.exec(select(User).where(User.username == username)).first()
                if existing:
                    return rx.window_alert(f"کاربری با نام '{username}' از قبل وجود دارد.")
                
                hashed_pw = hash_password(password)
                user_to_update = User(username=username, password_hash=hashed_pw)
                session.add(user_to_update)
            
            session.commit()
        
        # بستن دیالوگ و بارگذاری مجدد لیست
        self.show_dialog = False
        self.load_users()
        return rx.window_alert("عملیات با موفقیت انجام شد.")

    def delete_user(self, user_id: int):
        """حذف کاربر از دیتابیس."""
        self.check_auth()
        with rx.session() as session:
            user_to_delete = session.get(User, user_id)
            if user_to_delete:
                session.delete(user_to_delete)
                session.commit()
            self.load_users()
        return rx.window_alert("کاربر با موفقیت حذف شد.")

# --- کامپوننت‌های UI ---

def add_edit_admin_dialog() -> rx.Component:
    """دیالوگ برای افزودن یا ویرایش ادمین."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(AdminState.admin_to_edit, "ویرایش ادمین", "افزودن ادمین جدید")),
            rx.form(
                rx.vstack(
                    rx.input(
                        placeholder="نام کاربری",
                        name="username",
                        default_value=rx.cond(AdminState.admin_to_edit, AdminState.admin_to_edit.username, ""),
                        required=True
                    ),
                    rx.input(
                        placeholder="رمز عبور جدید",
                        name="password",
                        type="password",
                        # رمز عبور فقط برای کاربر جدید اجباری است
                        required=rx.cond(~AdminState.admin_to_edit, True, False)
                    ),
                    rx.text(
                        "برای ویرایش، اگر نمی‌خواهید رمز عبور تغییر کند، این فیلد را خالی بگذارید.",
                        size="1",
                        color_scheme="gray",
                        display=rx.cond(AdminState.admin_to_edit, "block", "none")
                    ),
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
                on_submit=AdminState.save_admin,
                reset_on_submit=True, # فرم بعد از ثبت ریست می‌شود
            ),
            style={"maxWidth": 450, "direction": "rtl"}
        ),
        open=AdminState.show_dialog,
        on_open_change=AdminState.change_dialog_state,
    )

def admin_table() -> rx.Component:
    """جدول نمایش لیست ادمین‌ها با منوی عملیات."""
    return rx.table.root(
        rx.table.header(
            rx.table.row(
                rx.table.column_header_cell("عملیات", text_align="center", width="5%"),
                rx.table.column_header_cell("نام کاربری", text_align="right"),
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
                                rx.dropdown_menu.item(
                                    rx.hstack(rx.icon("pencil", size=16), rx.text("ویرایش")),
                                    on_click=lambda: AdminState.show_edit_dialog(user)
                                ),
                                rx.dropdown_menu.separator(),
                                rx.dropdown_menu.item(
                                    rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف")),
                                    color="red",
                                    on_click=lambda: AdminState.delete_user(user.id)
                                ),
                            ),
                        ),
                        text_align="center"
                    ),
                    rx.table.cell(user.username),
                ),
            )
        ),
        variant="surface",
    )

@template
def admin_page() -> rx.Component:
    """صفحه اصلی مدیریت ادمین‌ها."""
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