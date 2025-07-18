# xui_multi.py

import reflex as rx
# Corrected: Use absolute imports from the 'xui_multi' package
from xui_multi.api_routes import api
from xui_multi.panel_page import panels_page
from xui_multi.dashboard_page import dashboard_page
from fastapi.staticfiles import StaticFiles
import os
from .template import template
# The rest of the file remains the same
# بخش مدیریت پوشه static

base_style = {
    "direction": "rtl",
    "font_family": "IRANSans, Arial, sans-serif",
    "font_weight": "normal",
}

STATIC_DIR = "static/subs"
os.makedirs(STATIC_DIR, exist_ok=True)
api.mount("/static", StaticFiles(directory="static"), name="static")

# صفحه اصلی
@template
def index() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.heading("XUI-Multi Management Panel", size="7"),
            rx.link("مدیریت پنل‌ها", href="/panels"),
            rx.link("داشبورد سرویس‌ها", href="/dashboard"),
            spacing="3"
        )
    )

# ساخت اپلیکیشن Reflex با استایل و فونت جدید
app = rx.App(
    api_transformer=api,
    style=base_style,
    stylesheets=["/styles.css"],
)

# اضافه کردن صفحات به همراه route مشخص
app.add_page(index, route="/")
app.add_page(panels_page, route="/panels")
app.add_page(dashboard_page, route="/dashboard")