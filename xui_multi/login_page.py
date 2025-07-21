import reflex as rx
from .auth_state import AuthState

def login_page() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.heading("ورود به پنل مدیریت", size="8", margin_bottom="1em"),
            rx.box(
                rx.input(
                    placeholder="نام کاربری",
                    on_blur=AuthState.set_username, # Use direct state binding
                    margin_bottom="1em",
                    width="100%"
                ),
                rx.input(
                    placeholder="رمز عبور",
                    type="password",
                    on_blur=AuthState.set_password, # Use direct state binding
                    margin_bottom="1em",
                    width="100%"
                ),
                rx.cond(
                    AuthState.error_message,
                    rx.callout(
                        AuthState.error_message,
                        icon="triangle_alert",
                        color_scheme="red",
                        role="alert",
                        width="100%",
                        margin_bottom="1em"
                    ),
                ),
                rx.button(
                    "ورود",
                    on_click=AuthState.login, # Call login without form_data
                    width="100%",
                    size="3",
                    color_scheme="teal"
                ),
                width="350px",
                padding="2em",
                border="1px solid var(--gray-a5)",
                border_radius="var(--radius-4)"
            ),
            align="center",
            spacing="4",
            height="100vh"
        )
    )