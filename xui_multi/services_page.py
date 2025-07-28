# xui_multi/services_page.py

import reflex as rx
import httpx
from .models import ManagedService, User
from .auth_state import AuthState
from sqlalchemy.orm import selectinload
import datetime
import math
from typing import List, Dict, Any

# دیکشنری برای ترجمه وضعیت به فارسی
STATUS_TRANSLATIONS = {
    "active": "فعال",
    "expired": "منقضی شده",
    "limit_reached": "حجم تمام شده",
}

def format_remaining_time(end_date: datetime.datetime, status: str) -> str:
    """زمان باقی‌مانده را به فرمت 'Xd, Yh' تبدیل می‌کند."""
    if not end_date:
        return "نامشخص"
    now = datetime.datetime.now(end_date.tzinfo)
    diff = end_date - now
    if diff.total_seconds() <= 0:
        return "منقضی شده"
    days = diff.days
    hours = diff.seconds // 3600
    return f"{days} روز, {hours} ساعت"

class DashboardState(AuthState):
    # --- متغیرهای اصلی ---
    all_services: List[Dict[str, Any]] = []
    services_display: List[Dict[str, Any]] = []

    # --- متغیرهای جستجو و صفحه‌بندی ---
    search_query: str = ""
    current_page: int = 1
    items_per_page: int = 20

    # --- متغیرهای دیالوگ ساخت سرویس ---
    show_create_dialog: bool = False
    new_service_name: str = ""
    new_service_duration: int = 30
    new_service_limit: int = 10
    create_error_message: str = ""
    is_creating: bool = False

    # --- متغیرهای دیالوگ ویرایش سرویس ---
    show_edit_dialog: bool = False
    service_to_edit: Dict[str, Any] = {}
    edit_duration: int = 30
    edit_limit: int = 10
    edit_error_message: str = ""
    is_editing: bool = False

    # --- متغیرهای دیالوگ حذف ---
    show_delete_dialog: bool = False
    service_to_delete: Dict[str, Any] = {}
    is_deleting: bool = False
    show_bulk_delete_dialog: bool = False
    is_bulk_deleting: bool = False

    # --- متغیرهای نمایش پیام ---
    action_message: str = ""
    action_status: str = ""

    # --- تنظیمات API ---
    api_url: str = "http://localhost:8000"
    api_key: str = "SECRET_KEY_12345"
    
    # FIX: Add a state var to hold the current user's API key
    user_api_key: str = ""

    @rx.var
    def total_pages(self) -> int:
        """تعداد کل صفحات را محاسبه می‌کند."""
        if not self.all_services:
            return 1
        return math.ceil(len(self.all_services) / self.items_per_page)

    def set_duration_from_slider(self, value: List[int | float]):
        self.new_service_duration = int(value[0])

    def set_limit_from_slider(self, value: List[int | float]):
        self.new_service_limit = int(value[0])

    def set_edit_duration_from_slider(self, value: List[int | float]):
        self.edit_duration = int(value[0])

    def set_edit_limit_from_slider(self, value: List[int | float]):
        self.edit_limit = int(value[0])

    async def load_and_filter_services(self):
        """سرویس‌ها را از دیتابیس بارگذاری، فیلتر و صفحه‌بندی می‌کند."""
        self.check_auth()
        self.action_message = ""
        with rx.session() as session:
            creator = session.query(User).filter(User.username == self.token).first()
            if not creator:
                return

            # FIX: Store the user's API key in the state
            self.user_api_key = creator.api_key or ""

            query = session.query(ManagedService).options(selectinload(ManagedService.configs))

            if not self.is_admin:
                query = query.filter(ManagedService.created_by_id == creator.id)

            if self.search_query:
                query = query.filter(ManagedService.name.contains(self.search_query))

            services_from_db = query.order_by(ManagedService.id.desc()).all()

            self.all_services = [
                {
                    "name": s.name, "uuid": s.uuid, "status_en": s.status,
                    "status_fa": STATUS_TRANSLATIONS.get(s.status, s.status),
                    "config_count": len(s.configs),
                    "data_usage": f"{s.data_used_gb:.2f} / {s.data_limit_gb} GB",
                    "data_limit_gb": s.data_limit_gb,
                    "remaining_days": (s.end_date - datetime.datetime.now(s.end_date.tzinfo)).days if s.end_date else 0,
                    "remaining_time": format_remaining_time(s.end_date, s.status),
                    "subscription_link": s.subscription_link,
                }
                for s in services_from_db
            ]
        self._paginate_services()

    def _paginate_services(self):
        start_index = (self.current_page - 1) * self.items_per_page
        end_index = start_index + self.items_per_page
        self.services_display = self.all_services[start_index:end_index]

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._paginate_services()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self._paginate_services()

    async def handle_search(self, query: str):
        self.search_query = query
        self.current_page = 1
        await self.load_and_filter_services()

    # --- عملیات ساخت سرویس ---
    def open_create_dialog(self):
        self.show_create_dialog = True
        self.create_error_message = ""
        self.new_service_name = ""
        self.new_service_duration = 30
        self.new_service_limit = 10

    async def handle_create_service(self):
        self.create_error_message = ""
        if not self.new_service_name.strip():
            self.create_error_message = "نام سرویس نمی‌تواند خالی باشد."
            return
        self.is_creating = True
        # FIX: Use the correct header 'x-api-authorization'
        headers = {"X-API-KEY": self.api_key, "x-api-authorization": self.user_api_key}
        payload = {"name": self.new_service_name, "duration_days": self.new_service_duration, "data_limit_gb": self.new_service_limit}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(f"{self.api_url}/service", headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    self.show_create_dialog = False
                    self.action_message = "سرویس با موفقیت ساخته شد."
                    self.action_status = "success"
                    await self.load_and_filter_services()
                    return rx.window_alert("سرویس با موفقیت ایجاد شد.")
                else:
                    self.create_error_message = f"خطا: {response.text}"
        except Exception as e:
            self.create_error_message = f"خطای ارتباطی: {e}"
        finally:
            self.is_creating = False

    # --- عملیات ویرایش سرویس ---
    def open_edit_dialog(self, service: Dict[str, Any]):
        self.service_to_edit = service
        self.edit_duration = service.get('remaining_days', 30)
        self.edit_limit = service.get('data_limit_gb', 10)
        self.edit_error_message = ""
        self.show_edit_dialog = True

    async def handle_edit_service(self):
        self.is_editing = True
        self.edit_error_message = ""
        # FIX: Use the correct header 'x-api-authorization'
        headers = {"X-API-KEY": self.api_key, "x-api-authorization": self.user_api_key}
        payload = {"duration_days": self.edit_duration, "data_limit_gb": self.edit_limit}
        uuid = self.service_to_edit.get("uuid")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(f"{self.api_url}/service/{uuid}", headers=headers, json=payload, timeout=60)
                if response.status_code == 200:
                    self.show_edit_dialog = False
                    self.action_message = "سرویس با موفقیت ویرایش شد."
                    self.action_status = "success"
                    await self.load_and_filter_services()
                    return rx.window_alert("سرویس با موفقیت ویرایش شد.")
                else:
                    self.edit_error_message = f"خطا: {response.text}"
        except Exception as e:
            self.edit_error_message = f"خطای ارتباطی: {e}"
        finally:
            self.is_editing = False

    # --- عملیات حذف سرویس ---
    def open_delete_dialog(self, service: Dict[str, Any]):
        self.service_to_delete = service
        self.show_delete_dialog = True

    async def handle_delete_service(self):
        self.is_deleting = True
        uuid = self.service_to_delete.get("uuid")
        # FIX: Use the correct header 'x-api-authorization'
        headers = {"X-API-KEY": self.api_key, "x-api-authorization": self.user_api_key}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(f"{self.api_url}/service/{uuid}", headers=headers, timeout=60)
                if response.status_code == 200:
                    self.action_message = "سرویس با موفقیت حذف شد."
                    self.action_status = "success"
                    return rx.window_alert("سرویس با موفقیت حذف شد.")
                else:
                    self.action_message = f"خطا در حذف: {response.text}"
                    self.action_status = "error"
        except Exception as e:
            self.action_message = f"خطای ارتباطی: {e}"
            self.action_status = "error"
        finally:
            self.is_deleting = False
            self.show_delete_dialog = False
            await self.load_and_filter_services()

    # --- عملیات حذف گروهی ---
    def trigger_bulk_delete_dialog(self):
        self.show_bulk_delete_dialog = True

    async def confirm_bulk_delete(self):
        self.is_bulk_deleting = True
        self.show_bulk_delete_dialog = False
        # FIX: Use the correct header 'x-api-authorization'
        headers = {"X-API-KEY": self.api_key, "x-api-authorization": self.user_api_key}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(f"{self.api_url}/services/inactive", headers=headers, timeout=120)
                if response.status_code == 200:
                    data = response.json()
                    self.action_message = data.get("message", "عملیات با موفقیت انجام شد.")
                    self.action_status = "success"
                    return rx.window_alert("سرویس‌های غیرفعال با موفقیت حذف شدند.")
                else:
                    self.action_message = f"خطا در حذف گروهی: {response.text}"
                    self.action_status = "error"
            await self.load_and_filter_services()
        except Exception as e:
            self.action_message = f"خطای ارتباطی: {e}"
            self.action_status = "error"
        finally:
            self.is_bulk_deleting = False

    def copy_to_clipboard(self, text: str):
        return rx.call_script(f"""navigator.clipboard.writeText('{text}').then(() => {{ alert('لینک با موفقیت کپی شد!'); }},() => {{ alert('خطا در کپی کردن لینک.'); }});""")

# --- (بقیه فایل services_page.py بدون تغییر باقی می‌ماند) ---

# --- کامپوننت‌های مودال (Dialog) ---

def create_service_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("ساخت سرویس جدید"),
            rx.dialog.description("اطلاعات سرویس جدید را وارد کنید.", margin_bottom="1em"),
            rx.flex(rx.text("نام سرویس:", width="120px", as_="label"), rx.input(placeholder="مثلا: کاربر ۱", on_change=DashboardState.set_new_service_name), spacing="3", align="center"),
            rx.flex(rx.text("مدت زمان (روز):", width="120px", as_="label"), rx.slider(min=1, max=365, value=[DashboardState.new_service_duration], on_change=DashboardState.set_duration_from_slider), rx.text(DashboardState.new_service_duration, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.flex(rx.text("حجم (گیگابایت):", width="120px", as_="label"), rx.slider(min=1, max=1000, value=[DashboardState.new_service_limit], on_change=DashboardState.set_limit_from_slider), rx.text(DashboardState.new_service_limit, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.cond(DashboardState.create_error_message != "", rx.callout(DashboardState.create_error_message, icon="triangle_alert", color_scheme="red", margin_top="1em")),
            rx.flex(rx.dialog.close(rx.button("انصراف", variant="soft", color_scheme="gray")), rx.button("ساخت سرویس", on_click=DashboardState.handle_create_service, loading=DashboardState.is_creating), spacing="3", margin_top="1em", justify="end"),
            style={"direction": "rtl"}
        ),
        open=DashboardState.show_create_dialog, on_open_change=DashboardState.set_show_create_dialog
    )

def edit_service_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(f"ویرایش سرویس: {DashboardState.service_to_edit.get('name', '')}"),
            rx.dialog.description("زمان یا حجم سرویس را تغییر دهید.", margin_bottom="1em"),
            rx.flex(rx.text("افزایش زمان (روز):", width="120px", as_="label"), rx.slider(min=1, max=365, value=[DashboardState.edit_duration], on_change=DashboardState.set_edit_duration_from_slider), rx.text(DashboardState.edit_duration, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.flex(rx.text("افزایش حجم (GB):", width="120px", as_="label"), rx.slider(min=1, max=1000, value=[DashboardState.edit_limit], on_change=DashboardState.set_edit_limit_from_slider), rx.text(DashboardState.edit_limit, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.cond(DashboardState.edit_error_message != "", rx.callout(DashboardState.edit_error_message, icon="triangle_alert", color_scheme="red", margin_top="1em")),
            rx.flex(rx.dialog.close(rx.button("انصراف", variant="soft", color_scheme="gray")), rx.button("ذخیره تغییرات", on_click=DashboardState.handle_edit_service, loading=DashboardState.is_editing), spacing="3", margin_top="1em", justify="end"),
            style={"direction": "rtl"}
        ),
        open=DashboardState.show_edit_dialog, on_open_change=DashboardState.set_show_edit_dialog
    )

def delete_service_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("تایید حذف سرویس"),
            rx.alert_dialog.description(f"آیا از حذف سرویس '{DashboardState.service_to_delete.get('name', '')}' مطمئن هستید؟ این عمل غیرقابل بازگشت است."),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("انصراف", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(rx.button("حذف کن", on_click=DashboardState.handle_delete_service, color_scheme="ruby", loading=DashboardState.is_deleting)),
                spacing="3", margin_top="1em", justify="end"
            ),
            style={"direction": "rtl"}
        ),
        open=DashboardState.show_delete_dialog, on_open_change=DashboardState.set_show_delete_dialog
    )

# --- کامپوننت اصلی صفحه ---
def services_page() -> rx.Component:
    return rx.vstack(
        create_service_dialog(),
        edit_service_dialog(),
        delete_service_dialog(),

        rx.alert_dialog.root(
            rx.alert_dialog.content(
                rx.alert_dialog.title("تایید حذف گروهی"),
                rx.alert_dialog.description("آیا از حذف تمام سرویس‌های غیرفعال مطمئن هستید؟ این عمل غیرقابل بازگشت است."),
                rx.flex(
                    rx.alert_dialog.cancel(rx.button("انصراف", variant="soft", color_scheme="gray")),
                    rx.alert_dialog.action(rx.button("حذف کن", on_click=DashboardState.confirm_bulk_delete, color_scheme="ruby", loading=DashboardState.is_bulk_deleting)),
                    spacing="3", margin_top="1em", justify="end",
                ), style={"direction": "rtl"}
            ), open=DashboardState.show_bulk_delete_dialog, on_open_change=DashboardState.set_show_bulk_delete_dialog
        ),

        rx.heading("مدیریت سرویس‌ها", size="8", margin_bottom="1em", style={"direction": "rtl", "color": "#1a365d"}),
        rx.divider(width="100%", margin_y="1.5em"),
        rx.spacer(),
        rx.hstack(
            rx.hstack(
                rx.tooltip(rx.icon_button(rx.icon("plus"), on_click=DashboardState.open_create_dialog, color_scheme="grass", variant="solid", size="3"), content="ساخت سرویس جدید"),
                
                rx.cond(
                    DashboardState.is_admin,
                    rx.tooltip(rx.icon_button(rx.icon("trash-2"), on_click=DashboardState.trigger_bulk_delete_dialog, color_scheme="ruby", variant="solid", size="3"), content="حذف سرویس‌های غیرفعال"),
                ),
                
                spacing="3",
            ),
            rx.spacer(),
            rx.hstack(
                rx.icon("search", color="gray"),
                rx.debounce_input(rx.input(placeholder="جستجو بر اساس نام...", on_change=DashboardState.handle_search, width="100%"), debounce_timeout=300),
                padding="0.5em 1em", border="1px solid #ddd", border_radius="var(--radius-3)", width="350px", background_color="white",
            ),
            width="90%", margin_bottom="1em", style={"direction": "rtl"}
        ),

        rx.cond(
            DashboardState.action_message,
            rx.callout(
                DashboardState.action_message,
                color_scheme=rx.cond(DashboardState.action_status == "success", "grass", "red"),
                icon=rx.cond(DashboardState.action_status == "success", "check_circ", "triangle_alert"),
                width="90%", margin_y="1em"
            )
        ),

        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("عملیات", text_align="center"),
                    rx.table.column_header_cell("زمان باقی‌مانده", text_align="center"),
                    rx.table.column_header_cell("حجم مصرفی", text_align="center"),
                    rx.table.column_header_cell("تعداد کانفیگ", text_align="center"),
                    rx.table.column_header_cell("پروتکل", text_align="center"),
                    rx.table.column_header_cell("وضعیت", text_align="center"),
                    rx.table.column_header_cell("نام سرویس", text_align="right"),
                )
            ),
            rx.table.body(
                rx.foreach(
                    DashboardState.services_display,
                    lambda service: rx.table.row(
                        rx.table.cell(
                            rx.dropdown_menu.root(
                                rx.dropdown_menu.trigger(rx.button(rx.icon("ellipsis-vertical"), variant="soft")),
                                rx.dropdown_menu.content(
                                    rx.dropdown_menu.item(
                                        rx.hstack(rx.icon("clipboard-copy", size=16), rx.text("کپی لینک"), spacing="2"),
                                        on_click=lambda: DashboardState.copy_to_clipboard(service["subscription_link"])
                                    ),
                                    rx.dropdown_menu.item(
                                        rx.hstack(rx.icon("pencil", size=16), rx.text("ویرایش"), spacing="2"),
                                        on_click=lambda: DashboardState.open_edit_dialog(service)
                                    ),
                                    rx.dropdown_menu.separator(),
                                    rx.dropdown_menu.item(
                                        rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف سرویس"), spacing="2"),
                                        color="red", on_click=lambda: DashboardState.open_delete_dialog(service)
                                    ),
                                ),
                            ), text_align="center"
                        ),
                        rx.table.cell(rx.badge(service["remaining_time"], color_scheme="cyan", variant="soft"), text_align="center"),
                        rx.table.cell(rx.badge(service["data_usage"], color_scheme="blue", variant="soft"), text_align="center"),
                        rx.table.cell(rx.badge(service["config_count"], color_scheme="plum", variant="soft"), text_align="center"),
                        rx.table.cell(rx.badge("VLESS + SS", color_scheme="iris", variant="soft"), text_align="center"),
                        rx.table.cell(rx.badge(service["status_fa"], color_scheme=rx.cond(service["status_en"] == 'active', "grass", "ruby"), variant="solid"), text_align="center"),
                        rx.table.cell(service["name"], text_align="right"),
                    )
                )
            ),
            variant="surface", width="90%", style={"direction": "rtl"}
        ),

        rx.hstack(
            rx.button("صفحه قبل", on_click=DashboardState.prev_page, is_disabled=DashboardState.current_page <= 1),
            rx.text(f"صفحه {DashboardState.current_page} از {DashboardState.total_pages}"),
            rx.button("صفحه بعد", on_click=DashboardState.next_page, is_disabled=DashboardState.current_page >= DashboardState.total_pages),
            spacing="4", justify="center", width="90%", margin_top="1em"
        ),

        on_mount=DashboardState.load_and_filter_services,
        align="center",
        width="100%",
        padding_y="2em",
    )