# xui_multi/services_page.py

import reflex as rx
import datetime
import logging
from typing import List, Dict, Any
from .auth_state import AuthState
from .models import ManagedService, User, PanelConfig
from .cache_manager import cache_manager

# Configure logging
logging.basicConfig(
    filename='xui_multi.log',
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def format_remaining_time(end_date: datetime.datetime, status: str) -> str:
    """فرمت کردن زمان باقی‌مانده"""
    if status != "active":
        return f"وضعیت: {status}"
    
    remaining = end_date - datetime.datetime.now()
    if remaining.total_seconds() <= 0:
        return "منقضی شده"
    
    days = remaining.days
    hours = remaining.seconds // 3600
    minutes = (remaining.seconds % 3600) // 60
    
    if days > 0:
        return f"{days} روز {hours} ساعت"
    elif hours > 0:
        return f"{hours} ساعت {minutes} دقیقه"
    else:
        return f"{minutes} دقیقه"

class DashboardState(AuthState):
    all_services: List[Dict[str, Any]] = []
    services_display: List[Dict[str, Any]] = []
    search_query: str = ""
    current_page: int = 1
    items_per_page: int = 20

    show_create_dialog: bool = False
    new_service_name: str = ""
    new_service_duration: int = 30
    new_service_limit: int = 10
    new_service_protocol: str = "vless"
    create_error_message: str = ""
    is_creating: bool = False

    show_edit_dialog: bool = False
    service_to_edit: Dict[str, Any] = {}
    edit_duration: int = 30
    edit_limit: int = 10
    edit_error_message: str = ""
    is_editing: bool = False

    show_delete_dialog: bool = False
    service_to_delete: Dict[str, Any] = {}
    is_deleting: bool = False
    show_bulk_delete_dialog: bool = False
    is_bulk_deleting: bool = False

    action_message: str = ""
    action_status: str = ""

    api_url: str = "http://localhost:8000"

    @rx.var
    def total_pages(self) -> int:
        """محاسبه تعداد کل صفحات"""
        return max(1, (len(self.services_display) + self.items_per_page - 1) // self.items_per_page)

    @rx.var
    def service_config_counts(self) -> List[str]:
        """Get config counts for all services in display"""
        return [str(service.get("config_count", 0)) for service in self.services_display]

    @rx.var
    def config_count_mapping(self) -> Dict[str, str]:
        """Create a mapping of service names to config counts"""
        mapping = {}
        for service in self.services_display:
            name = service.get("name", "")
            count = service.get("config_count", 0)
            mapping[name] = str(count)
        return mapping

    def set_new_service_name(self, name: str):
        self.new_service_name = name

    def set_new_service_duration(self, duration: str):
        """تنظیم مدت زمان از ورودی متنی"""
        try:
            self.new_service_duration = int(duration)
        except ValueError:
            self.new_service_duration = 30

    def set_new_service_limit(self, limit: str):
        """تنظیم حجم از ورودی متنی"""
        try:
            self.new_service_limit = int(limit)
        except ValueError:
            self.new_service_limit = 10

    def set_new_service_protocol(self, protocol: str):
        self.new_service_protocol = protocol

    def set_edit_duration(self, duration: str):
        """تنظیم مدت زمان ویرایش از ورودی متنی"""
        try:
            self.edit_duration = int(duration)
        except ValueError:
            self.edit_duration = 30

    def set_edit_limit(self, limit: str):
        """تنظیم حجم ویرایش از ورودی متنی"""
        try:
            self.edit_limit = int(limit)
        except ValueError:
            self.edit_limit = 10

    async def load_and_filter_services(self):
        """بارگذاری و فیلتر کردن سرویس‌ها با استفاده از کش"""
        try:
            cache_key = 'ALL_SERVICES'
            # Clear cache to ensure fresh data
            cache_manager.invalidate(cache_key)
            # Temporarily disable caching to debug
            cached_data = None
            # cached_data = cache_manager.get(cache_key)
            
            if cached_data:
                self.all_services = cached_data
            else:
                # Clear the list before adding new data
                self.all_services = []
                with rx.session() as session:
                    if self.username == "hkhatiri":
                        # ادمین اصلی همه سرویس‌ها را می‌بیند
                        services = session.query(ManagedService).all()
                    else:
                        # سایر کاربران فقط سرویس‌های خودشان را می‌بینند
                        services = session.query(ManagedService).filter(ManagedService.created_by_id == self.user_id).all()
                    
                    for service in services:
                        configs = session.query(PanelConfig).filter(PanelConfig.managed_service_id == service.id).all()
                        
                        service_data = {
                            "id": service.id,
                            "uuid": service.uuid,
                            "name": service.name,
                            "status": service.status,
                            "status_en": service.status,
                            "status_fa": "فعال" if service.status == "active" else "غیرفعال",
                            "protocol": service.protocol,
                            "config_count": len(configs),
                            "data_usage": f"{service.data_used_gb:.2f} / {service.data_limit_gb:.1f} GB",
                            "remaining_time": format_remaining_time(service.end_date, service.status),
                            "subscription_link": f"https://multi.antihknet.com/static/subs/{service.uuid}.txt",
                            "created_by": service.creator.username if service.creator else "نامشخص",
                            "created_by_id": service.creator.id if service.creator else None
                        }
                        
                        self.all_services.append(service_data)
                
                cache_manager.set(cache_key, self.all_services, ttl=30)
            
            self._filter_services()
            
        except Exception as e:
            logger.error(f"Error loading services: {e}")
            self.all_services = []

    def _filter_services(self):
        """فیلتر کردن سرویس‌ها بر اساس جستجو"""
        if not self.search_query:
            self.services_display = self.all_services.copy()
        else:
            query = self.search_query.lower()
            self.services_display = [
                service for service in self.all_services
                if query in service["name"].lower() or query in service["status_fa"].lower()
            ]
        
        self.current_page = 1
        self._paginate_services()

    def _paginate_services(self):
        """صفحه‌بندی سرویس‌ها"""
        start_idx = (self.current_page - 1) * self.items_per_page
        end_idx = start_idx + self.items_per_page
        self.services_display = self.services_display[start_idx:end_idx]

    def next_page(self):
        """صفحه بعدی"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._paginate_services()

    def prev_page(self):
        """صفحه قبلی"""
        if self.current_page > 1:
            self.current_page -= 1
            self._paginate_services()

    async def handle_search(self, query: str):
        """مدیریت جستجو"""
        self.search_query = query
        await self.load_and_filter_services()

    def open_create_dialog(self):
        """باز کردن دیالوگ ساخت سرویس"""
        self.show_create_dialog = True
        self.new_service_name = ""
        self.new_service_duration = 30
        self.new_service_limit = 10
        self.new_service_protocol = "vless"
        self.create_error_message = ""

    async def handle_create_service(self):
        """مدیریت ساخت سرویس جدید"""
        if not self.new_service_name.strip():
            self.create_error_message = "نام سرویس الزامی است."
            return

        self.is_creating = True
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.api_url}/service",
                    json={
                        "name": self.new_service_name,
                        "duration_days": self.new_service_duration,
                        "data_limit_gb": self.new_service_limit,
                        "protocol": self.new_service_protocol
                    },
                    headers={"X-API-Authorization": self.user_api_key}
                )
                
                if response.status_code == 200:
                    self.show_create_dialog = False
                    await self.load_and_filter_services()
                    self.action_message = "سرویس با موفقیت ایجاد شد."
                    self.action_status = "success"
                    # حذف کش‌ها
                    try:
                        from .cache_manager import invalidate_service_cache
                        invalidate_service_cache()
                    except ImportError:
                        pass
                else:
                    error_data = response.json()
                    self.create_error_message = error_data.get("detail", "خطا در ایجاد سرویس")
        except Exception as e:
            self.create_error_message = f"خطا در ارتباط با سرور: {str(e)}"
        finally:
            self.is_creating = False

    def open_edit_dialog(self, service: Dict[str, Any]):
        """باز کردن دیالوگ ویرایش سرویس"""
        self.service_to_edit = service
        self.show_edit_dialog = True
        self.edit_duration = 30
        self.edit_limit = 10
        self.edit_error_message = ""

    async def handle_edit_service(self):
        """مدیریت ویرایش سرویس"""
        self.is_editing = True
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.put(
                    f"{self.api_url}/service/{self.service_to_edit['uuid']}",
                    json={
                        "duration_days": self.edit_duration,
                        "data_limit_gb": self.edit_limit
                    },
                    headers={"X-API-Authorization": self.user_api_key}
                )
                
                if response.status_code == 200:
                    self.show_edit_dialog = False
                    await self.load_and_filter_services()
                    self.action_message = "سرویس با موفقیت ویرایش شد."
                    self.action_status = "success"
                    # حذف کش‌ها
                    try:
                        from .cache_manager import invalidate_service_cache
                        invalidate_service_cache()
                    except ImportError:
                        pass
                else:
                    error_data = response.json()
                    self.edit_error_message = error_data.get("detail", "خطا در ویرایش سرویس")
        except Exception as e:
            self.edit_error_message = f"خطا در ارتباط با سرور: {str(e)}"
        finally:
            self.is_editing = False

    def open_delete_dialog(self, service: Dict[str, Any]):
        """باز کردن دیالوگ حذف سرویس"""
        self.service_to_delete = service
        self.show_delete_dialog = True

    async def handle_delete_service(self):
        """مدیریت حذف سرویس"""
        self.is_deleting = True
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.api_url}/service/{self.service_to_delete['uuid']}",
                    headers={"X-API-Authorization": self.user_api_key}
                )
                
                if response.status_code == 200:
                    self.show_delete_dialog = False
                    await self.load_and_filter_services()
                    self.action_message = "سرویس با موفقیت حذف شد."
                    self.action_status = "success"
                    # حذف کش‌ها
                    try:
                        from .cache_manager import invalidate_service_cache
                        invalidate_service_cache()
                    except ImportError:
                        pass
                else:
                    error_data = response.json()
                    self.action_message = error_data.get("detail", "خطا در حذف سرویس")
                    self.action_status = "error"
        except Exception as e:
            self.action_message = f"خطا در ارتباط با سرور: {str(e)}"
            self.action_status = "error"
        finally:
            self.is_deleting = False

    def trigger_bulk_delete_dialog(self):
        """باز کردن دیالوگ حذف گروهی"""
        self.show_bulk_delete_dialog = True

    async def confirm_bulk_delete(self):
        """تایید حذف گروهی"""
        self.is_bulk_deleting = True
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.delete(
                    f"{self.api_url}/services/inactive",
                    headers={"X-API-Authorization": self.user_api_key}
                )
                
                if response.status_code == 200:
                    self.show_bulk_delete_dialog = False
                    await self.load_and_filter_services()
                    self.action_message = "سرویس‌های غیرفعال با موفقیت حذف شدند."
                    self.action_status = "success"
                    # حذف کش‌ها
                    try:
                        from .cache_manager import invalidate_service_cache
                        invalidate_service_cache()
                    except ImportError:
                        pass
                else:
                    error_data = response.json()
                    self.action_message = error_data.get("detail", "خطا در حذف گروهی")
                    self.action_status = "error"
        except Exception as e:
            self.action_message = f"خطا در ارتباط با سرور: {str(e)}"
            self.action_status = "error"
        finally:
            self.is_bulk_deleting = False

    def copy_to_clipboard(self, text: str):
        """کپی کردن متن به کلیپ‌بورد با مدیریت خطا"""
        return rx.call_script(f"""
        try {{
            if (navigator.clipboard && navigator.clipboard.writeText) {{
                navigator.clipboard.writeText('{text}').then(() => {{
                    alert('لینک با موفقیت کپی شد!');
                }}).catch(() => {{
                    const textArea = document.createElement('textarea');
                    textArea.value = '{text}';
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    alert('لینک با موفقیت کپی شد!');
                }});
            }} else {{
                const textArea = document.createElement('textarea');
                textArea.value = '{text}';
                document.body.appendChild(textArea);
                textArea.select();
                document.execCommand('copy');
                document.body.removeChild(textArea);
                alert('لینک با موفقیت کپی شد!');
            }}
        }} catch (error) {{
            alert('خطا در کپی کردن لینک: ' + error.message);
        }}
        """)

    def get_config_count_display(self, service: Dict[str, Any]) -> str:
        """Get config count display for a service"""
        count = service.get("config_count", 0)
        return str(count)

    def get_service_config_count(self, service_name: str) -> str:
        """Get config count for a specific service"""
        for service in self.all_services:
            if service.get("name") == service_name:
                count = service.get("config_count", 0)
                return str(count)
        return "0"

def create_service_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("ساخت سرویس جدید"),
            rx.dialog.description("اطلاعات سرویس جدید را وارد کنید.", margin_bottom="1em"),
            rx.flex(rx.text("نام سرویس:", width="120px", as_="label"), rx.input(placeholder="مثلا: کاربر ۱", on_change=DashboardState.set_new_service_name), spacing="3", align="center"),
            rx.flex(
                rx.text("پروتکل:", width="120px", as_="label"),
                rx.select.root(
                    rx.select.trigger(placeholder="انتخاب پروتکل..."),
                    rx.select.content(
                        rx.select.item("VLESS", value="vless"),
                        rx.select.item("ShadowSocks", value="shadowsocks"),
                    ),
                    on_change=DashboardState.set_new_service_protocol,
                    value=DashboardState.new_service_protocol,
                    default_value="vless"
                ),
                spacing="3", align="center", margin_top="1em"
            ),
            rx.flex(rx.text("مدت زمان (روز):", width="120px", as_="label"), rx.input(placeholder="مثلا: 30", on_change=DashboardState.set_new_service_duration), rx.text(DashboardState.new_service_duration, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.flex(rx.text("حجم (گیگابایت):", width="120px", as_="label"), rx.input(placeholder="مثلا: 10", on_change=DashboardState.set_new_service_limit), rx.text(DashboardState.new_service_limit, width="30px"), spacing="3", align="center", margin_top="1em"),
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
            rx.flex(rx.text("افزایش زمان (روز):", width="120px", as_="label"), rx.input(placeholder="مثلا: 30", on_change=DashboardState.set_edit_duration), rx.text(DashboardState.edit_duration, width="30px"), spacing="3", align="center", margin_top="1em"),
            rx.flex(rx.text("افزایش حجم (GB):", width="120px", as_="label"), rx.input(placeholder="مثلا: 10", on_change=DashboardState.set_edit_limit), rx.text(DashboardState.edit_limit, width="30px"), spacing="3", align="center", margin_top="1em"),
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
            rx.input(
                placeholder="جستجو در سرویس‌ها...",
                on_change=DashboardState.handle_search,
                width="300px",
                style={"direction": "rtl"}
            ),
            width="100%",
            margin_bottom="1em"
        ),

        rx.cond(
            DashboardState.action_message != "",
            rx.callout(
                DashboardState.action_message,
                icon=rx.cond(
                    DashboardState.action_status == "success",
                    "check_circle",
                    "alert_triangle"
                ),
                color_scheme=rx.cond(
                    DashboardState.action_status == "success",
                    "green",
                    "red"
                ),
                margin_bottom="1em"
            )
        ),

        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("عملیات", text_align="center", width="5%"),
                    rx.table.column_header_cell("زمان باقی مانده", text_align="center"),
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
                                rx.dropdown_menu.trigger(rx.icon_button(rx.icon("ellipsis-vertical"), variant="soft")),
                                rx.dropdown_menu.content(
                                    rx.dropdown_menu.item(rx.hstack(rx.icon("pencil", size=16), rx.text("ویرایش")), on_click=lambda: DashboardState.open_edit_dialog(service)),
                                    rx.dropdown_menu.separator(),
                                    rx.dropdown_menu.item(rx.hstack(rx.icon("trash-2", size=16), rx.text("حذف")), color="red", on_click=lambda: DashboardState.open_delete_dialog(service)),
                                    rx.dropdown_menu.item(rx.hstack(rx.icon("copy", size=16), rx.text("کپی لینک")), on_click=lambda: DashboardState.copy_to_clipboard(service["subscription_link"])),
                                    align="center",
                                    spacing="2"
                                )
                            ),
                        ),
                        rx.table.cell(service["remaining_time"], text_align="center"),
                        rx.table.cell(service["data_usage"], text_align="center"),
                        rx.table.cell(
                            rx.text(
                                f"{service['config_count']}",
                                text_align="center",
                                font_weight="bold"
                            )
                        ),
                        rx.table.cell(
                            rx.badge(service["protocol"], color_scheme="purple", size="1")
                        ),
                        rx.table.cell(
                            rx.badge(
                                service["status_fa"], 
                                color_scheme=rx.cond(
                                    service["status"] == "active",
                                    "green",
                                    "red"
                                ), 
                                size="1"
                            )
                        ),
                        rx.table.cell(service["name"], text_align="right", font_weight="medium"),
                    ),
                )
            ),
            variant="surface",
            style={"width": "100%", "border": "1px solid #e2e8f0", "border_radius": "8px"}
        ),

        rx.hstack(
            rx.button("قبلی", on_click=DashboardState.prev_page, disabled=DashboardState.current_page == 1),
            rx.text(f"صفحه {DashboardState.current_page} از {DashboardState.total_pages}"),
            rx.button("بعدی", on_click=DashboardState.next_page, disabled=DashboardState.current_page == DashboardState.total_pages),
            justify="center",
            margin_top="1em"
        ),

        on_mount=DashboardState.load_and_filter_services,
        width="100%",
        max_width="1200px",
        align="center",
        padding_x="2em",
    )