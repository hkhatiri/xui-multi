import reflex as rx
import requests
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select
from fastapi.staticfiles import StaticFiles

from xui_multi.api_routes import api
from xui_multi.panel_page import panels_page, backups_page # وارد کردن صفحه بکاپ
from xui_multi.servies_page import servies_page
from xui_multi.login_page import login_page
from xui_multi.auth_state import AuthState
from .template import template
from .models import Panel, ManagedService, PanelConfig, Backup

# --- تنظیمات پایه ---
base_style = {"direction": "rtl", "font_family": "IRANSans"}
BACKUP_DIR = os.path.join("static", "backups")
os.makedirs(BACKUP_DIR, exist_ok=True)
api.mount("/static", StaticFiles(directory="static"), name="static")

# --- منطق پشتیبان‌گیری ---
def run_all_backups():
    """یک جاب که برای تمام پنل‌ها اجرا شده و از آن‌ها بکاپ می‌گیرد."""
    print(f"[{datetime.now()}] شروع فرآیند پشتیبان‌گیری خودکار...")
    with rx.session() as session:
        panels = session.exec(select(Panel)).all()
        for panel in panels:
            try:
                print(f"درحال گرفتن بکاپ از پنل: {panel.name}")
                session_req = requests.Session()
                login_data = {'username': panel.username, 'password': panel.password}
                login_url = f"{panel.url.rstrip('/')}/login"
                
                # تلاش برای لاگین و دریافت کوکی
                res = session_req.post(login_url, data=login_data, timeout=10)
                res.raise_for_status()

                # دریافت فایل دیتابیس
                db_url = f"{panel.url.rstrip('/')}/server/getDb"
                res_db = session_req.get(db_url, timeout=20)
                res_db.raise_for_status()

                # ساخت پوشه و ذخیره فایل
                panel_backup_dir = os.path.join(BACKUP_DIR, str(panel.id))
                os.makedirs(panel_backup_dir, exist_ok=True)
                
                date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"backup_{date_str}.db"
                local_file_path = os.path.join(panel_backup_dir, file_name)
                
                with open(local_file_path, "wb") as f:
                    f.write(res_db.content)
                
                # ذخیره اطلاعات بکاپ در دیتابیس
                download_path = f"/static/backups/{panel.id}/{file_name}"
                new_backup = Backup(
                    panel_id=panel.id, 
                    file_name=file_name, 
                    file_path=download_path
                )
                session.add(new_backup)
                session.commit()
                print(f"بکاپ پنل {panel.name} با موفقیت در {local_file_path} ذخیره شد.")

            except requests.exceptions.RequestException as e:
                print(f"خطا در ارتباط با پنل {panel.name}: {e}")
            except Exception as e:
                print(f"خطای نامشخص هنگام بکاپ‌گیری از پنل {panel.name}: {e}")
    print("پایان فرآیند پشتیبان‌گیری.")


# --- راه‌اندازی اسکجولر ---
scheduler = BackgroundScheduler()
# هر 12 ساعت یک‌بار تابع بکاپ را اجرا می‌کند
scheduler.add_job(run_all_backups, 'interval', hours=12)
# برای تست فوری می‌توانید این خط را از کامنت خارج کنید
# scheduler.add_job(run_all_backups, 'interval', seconds=30) 
scheduler.start()


# --- State و UI صفحه اصلی ---
class IndexState(AuthState):
    panel_count: int = 0
    total_services: int = 0
    inactive_services: int = 0
    total_configs: int = 0
    backup_count: int = 0 # ✨ آمار جدید

    def load_stats(self):
        self.check_auth()
        with rx.session() as session:
            self.panel_count = session.query(Panel).count()
            self.total_services = session.query(ManagedService).count()
            self.inactive_services = session.query(ManagedService).filter(ManagedService.end_date < datetime.now()).count()
            self.total_configs = session.query(PanelConfig).count()
            self.backup_count = session.query(Backup).count() # ✨ شمارش بکاپ‌ها

def stat_card(title: str, value: rx.Var[int], icon: str, color: str):
    return rx.card(rx.hstack(rx.icon(icon, size=48, color=color), rx.vstack(rx.heading(value.to_string(), size="7"), rx.text(title, color="gray"),align="start"),spacing="4",align="center"),size="3",width="250px",height="120px")

@template
def index() -> rx.Component:
    return rx.center(rx.vstack(rx.heading("آمار کلی سیستم", size="8", margin_bottom="1.5em"), rx.hstack(
        stat_card("تعداد پنل‌ها", IndexState.panel_count, "server", "orange"),
        stat_card("کل سرویس‌ها", IndexState.total_services, "users", "blue"),
        stat_card("سرویس‌های غیرفعال", IndexState.inactive_services, "user-x", "red"),
        stat_card("تعداد بکاپ‌ها", IndexState.backup_count, "database", "purple"), # ✨ کارت جدید
        spacing="5", justify="center", wrap="wrap"),
        spacing="4", align="center"),
        on_mount=IndexState.load_stats, width="100%", height="80vh")

# --- Wrapper ها و تعریف اپلیکیشن ---
@template
def protected_panels() -> rx.Component: return panels_page()

@template
def protected_backups() -> rx.Component: return backups_page()

@template
def protected_dashboard() -> rx.Component: return servies_page()

app = rx.App(api_transformer=api, style=base_style, stylesheets=["/styles.css"])
app.add_page(login_page, route="/login")
app.add_page(index, route="/", title="داشبورد", on_load=AuthState.check_auth)
app.add_page(protected_panels, route="/panels", title="مدیریت پنل‌ها", on_load=AuthState.check_auth)
# ✨ روت جدید برای صفحه بکاپ‌ها
app.add_page(protected_backups, route="/panels/[panel_id]/backups", title="لیست بکاپ‌ها", on_load=AuthState.check_auth)
app.add_page(protected_dashboard, route="/dashboard", title="داشبورد سرویس‌ها", on_load=AuthState.check_auth)