import reflex as rx
from .auth_state import AuthState

def login_page() -> rx.Component:
    """صفحه لاگین با فرم ورود."""
    return rx.center(
        rx.vstack(
            rx.heading("ورود به پنل مدیریت", size="7", margin_bottom="1em"),
            rx.input(
                placeholder="نام کاربری",
                on_change=AuthState.set_username,
                value=AuthState.username,
                width="300px",
                text_align="center",
            ),
            rx.input(
                placeholder="رمز عبور",
                type="password",
                on_change=AuthState.set_password,
                value=AuthState.password,
                width="300px",
                text_align="center",
            ),
            rx.button(
                "ورود",
                on_click=AuthState.do_login,
                width="300px",
                margin_top="1em",
            ),
            rx.cond(
                AuthState.error_message != "",
                rx.callout(
                    AuthState.error_message,
                    icon="triangle_alert",
                    color_scheme="red",
                    role="alert",
                    width="300px",
                    margin_top="1em",
                )
            ),
            spacing="3",
            align="center",
            padding="2em",
            border="1px solid #ddd",
            border_radius="10px",
            box_shadow="lg",
            bg="var(--gray-1)",
        ),
        height="100vh", # صفحه را در مرکز عمودی قرار می‌دهد
    )