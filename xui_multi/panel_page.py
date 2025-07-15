import reflex as rx
import requests
from .models import Panel

def test_panel_connection(url: str, username: str, password: str) -> bool:
    try:
        login_url = f"{url.rstrip('/')}/login"
        response = requests.post(login_url, data={"username": username, "password": password}, timeout=5)
        response.raise_for_status()
        return response.json().get("success", False)
    except Exception:
        return False

class PanelState(rx.State):
    panels: list[Panel] = []
    
    # متغیر جدید برای نگهداری پیام خطا
    error_message: str = ""

    async def load_panels(self):
        with rx.session() as session:
            self.panels = session.query(Panel).all()

    async def handle_submit(self, form_data: dict):
        url = form_data.get("url", "").strip()
        username = form_data.get("username", "").strip()
        password = form_data.get("password", "").strip()

        if not all([url, username, password]):
            self.error_message = "لطفاً تمام فیلدها را پر کنید."
            return

        # تست اتصال
        if not test_panel_connection(url, username, password):
            # به جای print، پیام خطا را در State ذخیره می‌کنیم
            self.error_message = "اتصال ناموفق بود. آدرس یا اطلاعات ورود اشتباه است."
            return

        # اگر موفق بود، خطا را پاک کرده و پنل را ذخیره می‌کنیم
        self.error_message = ""
        with rx.session() as session:
            new_panel = Panel(url=url, username=username, password=password)
            session.add(new_panel)
            session.commit()
        
        await self.load_panels()


def panels_page() -> rx.Component:
    """UI صفحه مدیریت پنل‌ها"""
    return rx.fragment(
        rx.vstack(
            rx.heading("مدیریت پنل‌های X-UI", size="7"),
            
            rx.card(
                rx.vstack(
                    # نمایش پیام خطا در صورت وجود
                    rx.cond(
                        PanelState.error_message != "",
                        rx.callout(
                            PanelState.error_message,
                            icon="circle-x",
                            color_scheme="red",
                            role="alert",
                            width="300px",
                        )
                    ),
                    rx.form(
                        rx.vstack(
                            rx.input(name="url", placeholder="آدرس پنل (http://...)", required=True, width="300px"),
                            rx.input(name="username", placeholder="نام کاربری", required=True, width="300px"),
                            rx.input(name="password", placeholder="رمز عبور", type="password", required=True, width="300px"),
                            rx.button("افزودن و تست پنل", type="submit"),
                            spacing="3",
                        ),
                        on_submit=PanelState.handle_submit,
                    ),
                    spacing="3",
                    align="center",
                ),
                width="400px"
            ),
            
            # ... بقیه کد جدول بدون تغییر ...
            rx.divider(width="80%", margin_y="2em"),
            rx.heading("پنل‌های موجود", size="5"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("ID"),
                        rx.table.column_header_cell("آدرس"),
                        rx.table.column_header_cell("نام کاربری"),
                    )
                ),
                rx.table.body(rx.foreach(PanelState.panels, lambda panel: rx.table.row(rx.table.cell(panel.id), rx.table.cell(panel.url), rx.table.cell(panel.username)))),
                variant="surface",
                width="80%"
            ),
        ),
        on_mount=PanelState.load_panels,
    )