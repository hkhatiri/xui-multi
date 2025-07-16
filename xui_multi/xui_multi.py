import reflex as rx
from .api_routes import api
from .panel_page import panels_page
from .dashboard_page import dashboard_page # <--- ایمپورت به این شکل باشد
from fastapi.staticfiles import StaticFiles
import os

# بخش مدیریت پوشه static
STATIC_DIR = "static/subs"
os.makedirs(STATIC_DIR, exist_ok=True)
api.mount("/static", StaticFiles(directory="static"), name="static")

# صفحه اصلی
def index() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.heading("XUI-Multi Management Panel", size="7"),
            rx.link("مدیریت پنل‌ها", href="/panels"),
            rx.link("داشبورد سرویس‌ها", href="/dashboard"),
            spacing="3"
        )
    )

# ساخت اپلیکیشن Reflex
app = rx.App(api_transformer=api)
app.add_page(index)
app.add_page(panels_page, route="/panels")
app.add_page(dashboard_page, route="/dashboard") # <--- اینجا باید تابع پاس داده شود