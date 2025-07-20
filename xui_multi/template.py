import reflex as rx
from .auth_state import AuthState

# استایل برای سایدبار
sidebar_style = {
    "direction": "rtl",
    "position": "fixed",
    "right": 0,
    "top": 0,
    "height": "100%",
    "width": "250px",
    "bg": "var(--gray-2)",
    "border_left": "1px solid var(--gray-4)",
    "padding": "2em 1em",
    "display": "flex",
    "flex_direction": "column",
    "align_items": "center",
    "spacing": "5",
}

# استایل برای محتوای اصلی که در کنار سایدبار قرار می‌گیرد
main_content_style = {
    "margin_right": "250px", # به اندازه عرض سایدبار
    "padding": "2em",
    "width": "calc(100% - 250px)",
}

# استایل پس‌زمینه متحرک
animated_background_style = {
    "background": "linear-gradient(45deg, #e6fffa, #e6f7ff, #ebf5ff)",
    "background_size": "400% 400%",
    "animation": "wave 15s ease infinite",
    "min_height": "100vh",
}

def template(page_function: callable) -> rx.Component:
    def templated_page(*args, **kwargs):
        page_content = page_function(*args, **kwargs)
        return rx.theme(
            rx.box(
                rx.vstack(
                    rx.heading("XUI-Multi", size="7", margin_bottom="1em"),
                    rx.link("صفحه اصلی", href="/", width="100%"),
                    rx.link("مدیریت سرویس ها", href="/dashboard", width="100%"),
                    rx.link("مدیریت پنل‌ها", href="/panels", width="100%"),
                    rx.spacer(),
                    rx.button(
                        "خروج از حساب",
                        on_click=AuthState.do_logout,
                        variant="soft",
                        color_scheme="ruby",
                        width="100%"
                    ),
                    style=sidebar_style,
                ),
                rx.box(
                    page_content,
                    style=main_content_style,
                ),
                **animated_background_style
            ),
            accent_color="teal",
            gray_color="slate",
            radius="large",
            scaling="100%",
            panel_background="solid",
        )
    return templated_page