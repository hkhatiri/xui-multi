# xui_multi/template.py

import reflex as rx
from .auth_state import AuthState
from functools import wraps

def sidebar_link(text: str, url: str, icon: str) -> rx.Component:
    """A link to a page in the sidebar."""
    return rx.link(
        rx.hstack(
            rx.icon(icon, size=24),
            rx.text(text, size="4"),
            align="center",
            spacing="4",
        ),
        href=url,
        display="block",
        padding="0.75em",
        border_radius="var(--radius-3)",
        _hover={"background_color": "var(--accent-a3)"},
        width="100%",
    )

def sidebar() -> rx.Component:
    """The sidebar for the app."""
    return rx.vstack(
        rx.image(src="/logo2.png"),
        rx.hstack(
            rx.icon("bar-chart-big", size=32),
            rx.heading("XUI-Multi", size="7"),
            align="center",
            width="100%",
            padding_bottom="1em"
        ),
        rx.divider(),
        sidebar_link("داشبورد اصلی", "/", "layout-dashboard"),
        sidebar_link("مدیریت سرویس‌ها", "/dashboard", "users"),
        sidebar_link("مدیریت پنل‌ها", "/panels", "server"),

        # --- Conditional display for the admin menu ---
        rx.cond(
            AuthState.is_admin,
            sidebar_link("مدیریت ادمین‌ها", "/admin", "user-cog"),
        ),

        rx.spacer(),
        rx.hstack(
            rx.avatar(fallback=AuthState.username, weight="bold"),
            rx.vstack(
                rx.button(
                    "خروج از حساب",
                    on_click=AuthState.logout,
                    variant="soft",
                    color_scheme="ruby",
                    width="100%"
                ),
                align="start",
                spacing="1"
            ),
            rx.spacer(),
            align="center"
        
        ),
        padding="1.5em",
        border_right="1px solid var(--gray-a5)",
        background_color="var(--gray-a2)",
        height="100%",
        align="start",
        spacing="3",
        width="280px" 
    )


def template(page_function):
    """The main template decorator for all pages."""
    @wraps(page_function)
    def wrapper(*args, **kwargs):
        # Call the original page function to get its component content
        page_content = page_function(*args, **kwargs)

        # Return the content wrapped in the main layout
        return rx.hstack(
            sidebar(),
            rx.box(
                page_content,
                padding="2em",
                width="100%",
                height="100vh",
                overflow_y="auto",
            ),
            align="start",
            height="100vh",
            width="100%"
        )
    return wrapper