import reflex as rx
from sqlmodel import select
from typing import Optional
import bcrypt
# این خط را اضافه کنید تا بتوانیم نوع خطا را شناسایی کنیم
from sqlalchemy.exc import OperationalError

from .models import User

# تابع هش کردن رمز عبور
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# تابع بررسی رمز عبور
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

# ایجاد ادمین پیش‌فرض در اولین اجرا
def create_initial_admin_user():
    with rx.session() as session:
        try:
            # تلاش برای اجرای کوئری روی جدول user
            existing_user = session.exec(select(User)).first()
            if not existing_user:
                print("کاربری یافت نشد. در حال ایجاد کاربر ادمین پیش‌فرض...")
                default_username = "hkhatiri"
                default_password = "Hkhatiri1471"
                hashed_pw = hash_password(default_password)

                admin_user = User(username=default_username, password_hash=hashed_pw)
                session.add(admin_user)
                session.commit()
                print(f"کاربر '{default_username}' با رمز عبور '{default_password}' ایجاد شد.")
                print("!!! لطفاً پس از اولین ورود، رمز عبور پیش‌فرض را تغییر دهید. !!!")

        except OperationalError as e:
            # اگر خطا مربوط به عدم وجود جدول بود، آن را نادیده بگیر
            # این حالت دقیقا در زمان اجرای `reflex db init` رخ می‌دهد
            if "no such table" in str(e):
                print("Info: Skipping initial user creation because tables do not exist yet (during `db init`).")
                pass
            else:
                # اگر خطای دیگری بود، آن را نمایش بده
                raise e

class AuthState(rx.State):
    """منطق احراز هویت که اکنون از دیتابیس استفاده می‌کند."""
    token: Optional[str] = rx.LocalStorage()
    is_authenticated: bool = False
    is_admin: bool = False
    username: str = ""
    password: str = ""
    error_message: str = ""
    user_api_key: str = ""  # API key will be loaded from database
    user_id: int = 0  # User ID for filtering services

    def check_auth(self):
        """بررسی می‌کند که آیا توکن کاربر معتبر است یا خیر."""
        if not self.token:
            self.is_authenticated = False
            return rx.redirect("/login")

        with rx.session() as session:
            user = session.exec(select(User).where(User.username == self.token)).first()
            if user:
                self.is_authenticated = True
                self.username = user.username
                self.is_admin = self.username == "hkhatiri"
                # Load API key from database
                self.user_api_key = user.api_key
                self.user_id = user.id
            else:
                self.logout()

    def login(self): # The form data is now directly in the state
        """کاربر را با استفاده از اطلاعات فرم لاگین می‌کند."""
        if not self.username or not self.password:
            self.error_message = "نام کاربری و رمز عبور الزامی است."
            return

        with rx.session() as session:
            user = session.exec(select(User).where(User.username == self.username)).first()
            if user and verify_password(self.password, user.password_hash):
                self.token = user.username
                self.is_authenticated = True
                self.error_message = ""
                # Load API key from database
                self.user_api_key = user.api_key
                self.user_id = user.id
                # Clear the password field after login attempt
                self.password = ""
                return rx.redirect("/")
            else:
                self.error_message = "نام کاربری یا رمز عبور نامعتبر است."
                # Clear the password field after login attempt
                self.password = ""

    def logout(self):
        """کاربر را از سیستم خارج می‌کند."""
        self.reset()
        return rx.redirect("/login")