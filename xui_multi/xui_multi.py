import reflex as rx
from .api_routes import api
from .panel_page import panels_page # صفحه جدید را ایمپورت می‌کنیم

# صفحه اصلی
def index() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.heading("XUI-Multi Management Panel", size="7"),
            rx.link("مدیریت پنل‌ها", href="/panels"), # لینک به صفحه جدید
        )
    )

# ساخت اپلیکیشن Reflex
app = rx.App(api_transformer=api)
app.add_page(index)
app.add_page(panels_page, route="/panels") # <--- این خط اصلاح شد