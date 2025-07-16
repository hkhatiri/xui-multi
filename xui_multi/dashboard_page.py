import reflex as rx
import httpx
from .models import ManagedService
from sqlalchemy.orm import selectinload

class DashboardState(rx.State):
    services: list[ManagedService] = []

    # متغیرها برای مدیریت پنجره Dialog
    show_link_dialog: bool = False
    current_link_to_show: str = ""
    
    # متغیر برای نمایش خطای حذف
    delete_error_message: str = ""
    
    api_url: str = "http://localhost:8000"
    api_key: str = "SECRET_KEY_12345"

    async def load_services(self):
        """سرویس‌ها را از دیتابیس بارگذاری می‌کند."""
        self.delete_error_message = ""
        with rx.session() as session:
            self.services = session.query(ManagedService).options(
                selectinload(ManagedService.configs)
            ).order_by(ManagedService.id.desc()).all()

    async def delete_service(self, uuid: str):
        """سرویس را از طریق API حذف کرده و خطا را مدیریت می‌کند."""
        self.delete_error_message = ""
        headers = {"X-API-KEY": self.api_key}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.delete(f"{self.api_url}/service/{uuid}", headers=headers)
                
                if response.status_code != 200:
                    try:
                        error_data = response.json()
                        self.delete_error_message = error_data.get("detail", f"Error: {response.status_code}")
                    except:
                        self.delete_error_message = f"Error: {response.status_code} - {response.text}"
                    return

            await self.load_services()
        except httpx.RequestError as e:
            self.delete_error_message = f"Connection error: {e}"
        except Exception as e:
            self.delete_error_message = f"An unexpected client-side error occurred: {e}"

    def open_link_dialog(self, link: str):
        """پنجره نمایش لینک را باز می‌کند."""
        self.current_link_to_show = link
        self.show_link_dialog = True

    def close_link_dialog(self):
        """پنجره نمایش لینک را می‌بندد."""
        self.show_link_dialog = False

def link_display_dialog() -> rx.Component:
    """پنجره Dialog برای نمایش لینک اشتراک."""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("لینک اشتراک"),
            rx.dialog.description("این لینک را کپی کرده و در کلاینت خود استفاده کنید:"),
            rx.box(
                rx.text_area(
                    value=DashboardState.current_link_to_show,
                    is_read_only=True,
                    width="100%",
                    height="100px",
                    resize="vertical",
                ),
                padding_top="1em"
            ),
            rx.flex(
                rx.dialog.close(
                    rx.button("بستن", on_click=DashboardState.close_link_dialog, margin_top="1em", variant="soft", color_scheme="gray")
                ),
                justify="end",
            ),
            style={"max_width": "550px", "direction": "rtl"}
        ),
        open=DashboardState.show_link_dialog,
    )

def dashboard_page() -> rx.Component:
    """UI صفحه داشبورد با کدهای سازگار و نمایش خطا"""
    return rx.vstack(
        link_display_dialog(),
        
        rx.cond(
            DashboardState.delete_error_message != "",
            rx.callout(
                DashboardState.delete_error_message,
                icon="alert_triangle",
                color_scheme="red",
                role="alert",
                width="90%",
                margin_y="1em",
            )
        ),

        rx.heading("داشبورد مدیریت سرویس‌ها", size="7", margin_bottom="1em"),
        rx.table.root(
            rx.table.header(
                rx.table.row(
                    rx.table.column_header_cell("نام سرویس"),
                    rx.table.column_header_cell("وضعیت"),
                    rx.table.column_header_cell("پروتکل"),
                    rx.table.column_header_cell("تعداد کانفیگ"),
                    rx.table.column_header_cell("حجم مصرفی / محدودیت"),
                    rx.table.column_header_cell("تاریخ انقضا"),
                    rx.table.column_header_cell("عملیات"),
                )
            ),
            rx.table.body(
                rx.foreach(
                    DashboardState.services,
                    lambda service: rx.table.row(
                        rx.table.cell(service.name),
                        rx.table.cell(rx.badge(service.status, color_scheme=rx.cond(service.status == 'active', "grass", "ruby"))),
                        rx.table.cell(service.protocol),
                        rx.table.cell(rx.text(service.configs.length(), align="center")),
                        rx.table.cell(f"{service.data_used_gb:.2f} / {service.data_limit_gb} GB"),
                        rx.table.cell(rx.text(service.end_date)),
                        rx.table.cell(
                            rx.hstack(
                                rx.tooltip(
                                    rx.icon_button(
                                        rx.icon("link"),
                                        # *** این خط اصلاح شد ***
                                        on_click=lambda: DashboardState.open_link_dialog(service.subscription_link),
                                        size="1"
                                    ),
                                    content="نمایش لینک اشتراک",
                                ),
                                rx.alert_dialog.root(
                                    rx.alert_dialog.trigger(
                                        rx.icon_button(rx.icon("trash-2"), color_scheme="ruby", size="1")
                                    ),
                                    rx.alert_dialog.content(
                                        rx.alert_dialog.title("تایید حذف"),
                                        rx.alert_dialog.description(f"آیا از حذف سرویس '{service.name}' مطمئن هستید؟"),
                                        rx.flex(
                                            rx.alert_dialog.cancel(rx.button("انصراف", variant="soft", color_scheme="gray")),
                                            rx.alert_dialog.action(rx.button("حذف", on_click=lambda: DashboardState.delete_service(service.uuid), color_scheme="ruby")),
                                            spacing="3", margin_top="1em", justify="end",
                                        ),
                                    ),
                                ),
                                spacing="2"
                            )
                        ),
                    )
                )
            ),
            variant="surface",
            width="90%"
        ),
        on_mount=DashboardState.load_services,
        align="center",
        width="100%"
    )