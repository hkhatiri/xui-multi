import reflex as rx
from .auth_state import AuthState

def require_login(page: rx.Component) -> rx.Component:
    """
    یک کامپوننت مرتبه بالاتر که قبل از رندر کردن صفحه،
    وضعیت لاگین را بررسی می‌کند.
    """
    return rx.cond(
        AuthState.is_authenticated,  # اگر کاربر لاگین کرده بود...
        page,                        # ... صفحه اصلی را نمایش بده
        rx.center(                   # در غیر این صورت...
            rx.vstack(
                rx.heading("در حال انتقال به صفحه لاگین..."),
                rx.spinner(size="3"),
                # یک هدایت خودکار به صفحه لاگین
                rx.script(f"window.location.href = '/login'")
            ),
            height="100vh"
        )
    )