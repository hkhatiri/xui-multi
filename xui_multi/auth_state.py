import reflex as rx
from typing import Optional

class AuthState(rx.State):
    """وضعیت احرازهویت کاربر را مدیریت می‌کند."""
    username: str = ""
    password: str = ""
    error_message: str = ""
    
    token: Optional[str] = rx.Cookie(name="token")

    @rx.var
    def is_authenticated(self) -> bool:
        """بررسی می‌کند که آیا کاربر لاگین کرده است یا خیر."""
        return self.token is not None

    # ---> متد جدید برای بررسی امن
    def check_auth(self):
        """اگر کاربر احرازهویت نشده باشد، به صفحه لاگین هدایت می‌شود."""
        if not self.is_authenticated:
            return rx.redirect("/login")

    def do_login(self):
        """منطق لاگین را اجرا می‌کند."""
        if self.username == "hkhatiri" and self.password == "Kiri.BashaKoni1471":
            self.token = f"token_for_{self.username}"
            self.error_message = ""
            return rx.redirect("/dashboard")
        else:
            self.error_message = "نام کاربری یا رمز عبور اشتباه است."
            self.password = ""

    def do_logout(self):
        """کاربر را از سیستم خارج می‌کند."""
        self.reset()
        self.token = None
        return rx.redirect("/login")