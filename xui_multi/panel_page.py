import reflex as rx
import requests
from .models import Panel

def test_panel_connection(url: str, username: str, password: str) -> bool:
    """قبل از ذخیره، اتصال به پنل را تست می‌کند."""
    try:
        login_url = f"{url.rstrip('/')}/login"
        response = requests.post(login_url, data={"username": username, "password": password}, timeout=5)
        response.raise_for_status()
        return response.json().get("success", False)
    except Exception:
        return False

class PanelState(rx.State):
    """State برای مدیریت پنل‌ها در UI"""
    
    panels: list[Panel] = []
    error_message: str = ""
    form_domain: str = ""
    form_remark_prefix: str = ""

    async def load_panels(self):
        """پنل‌ها را از دیتابیس بارگذاری می‌کند."""
        with rx.session() as session:
            self.panels = session.query(Panel).all()

    async def handle_submit(self, form_data: dict):
        """وقتی فرم ثبت می‌شود، این تابع اجرا می‌شود."""
        url = form_data.get("url", "").strip()
        username = form_data.get("username", "").strip()
        password = form_data.get("password", "").strip()
        domain = form_data.get("domain", "").strip()
        remark_prefix = form_data.get("remark_prefix", "").strip()

        if not all([url, username, password, domain, remark_prefix]):
            self.error_message = "لطفاً تمام فیلدها را پر کنید."
            return

        if not test_panel_connection(url, username, password):
            self.error_message = "اتصال ناموفق بود. آدرس یا اطلاعات ورود اشتباه است."
            return

        self.error_message = ""
        with rx.session() as session:
            new_panel = Panel(
                url=url,
                username=username,
                password=password,
                domain=domain,
                remark_prefix=remark_prefix
            )
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
                    rx.cond(
                        PanelState.error_message != "",
                        rx.callout(
                            PanelState.error_message,
                            icon="circle_help",
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
                            rx.input(name="domain", placeholder="دامنه یا IP پنل", required=True, width="300px"),
                            rx.input(name="remark_prefix", placeholder="پیشوند توضیحات (مثلا: panel-1)", required=True, width="300px"),
                            rx.button("افزودن پنل", type="submit"),
                            spacing="3",
                        ),
                        on_submit=PanelState.handle_submit,
                    ),
                    spacing="3",
                    align="center",
                ),
                width="400px"
            ),
            rx.divider(width="80%", margin_y="2em"),
            rx.heading("پنل‌های موجود", size="5"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("ID"),
                        rx.table.column_header_cell("آدرس"),
                        rx.table.column_header_cell("دامنه"),
                        rx.table.column_header_cell("پیشوند Remark"),
                    )
                ),
                rx.table.body(
                    rx.foreach(
                        PanelState.panels,
                        lambda panel: rx.table.row(
                            rx.table.cell(panel.id),
                            rx.table.cell(panel.url),
                            rx.table.cell(panel.domain),
                            rx.table.cell(panel.remark_prefix),
                        ),
                    )
                ),
                variant="surface",
                width="80%"
            ),
            spacing="5",
            align="center",
            width="100%",
        ),
        on_mount=PanelState.load_panels,
    )