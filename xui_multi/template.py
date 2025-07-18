import reflex as rx

def template(page: rx.Component) -> rx.Component:
    """یک تمپلیت پایه که تمام صفحات را در بر می‌گیرد."""
    return rx.theme(
        rx.box(
            page(), # <-- این خط اصلاح شد
            padding="2em",
            width="100%",
        ),
        accent_color="teal",
        gray_color="slate",
        radius="large",
        scaling="100%",
        panel_background="solid",
    )