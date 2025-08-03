import reflex as rx
import requests
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select
from fastapi.staticfiles import StaticFiles
import base64

# --- وارد کردن تمام کامپوننت‌ها و State های لازم ---
from xui_multi.api_routes import *
from xui_multi.panel_page import panels_page, backups_page
from xui_multi.services_page import services_page
from xui_multi.login_page import login_page
from xui_multi.admin_page import admin_page

from xui_multi.auth_state import AuthState, create_initial_admin_user
from .template import template
from .models import Panel, ManagedService, PanelConfig, Backup, User
from .xui_client import XUIClient
from .tasks import verify_and_fix_subscription_files
# from .redis_worker import start_redis_workers  # Removed - workers run separately now

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
                print(f"درحال گرفتن بکاپ از پنل: {panel.remark_prefix}")
                session_req = requests.Session()
                login_data = {'username': panel.username, 'password': panel.password}
                login_url = f"{panel.url.rstrip('/')}/login"

                res = session_req.post(login_url, data=login_data, timeout=10)
                res.raise_for_status()

                db_url = f"{panel.url.rstrip('/')}/server/getDb"
                res_db = session_req.get(db_url, timeout=20)
                res_db.raise_for_status()

                panel_backup_dir = os.path.join(BACKUP_DIR, str(panel.id))
                os.makedirs(panel_backup_dir, exist_ok=True)

                date_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                file_name = f"backup_{date_str}.db"
                local_file_path = os.path.join(panel_backup_dir, file_name)

                with open(local_file_path, "wb") as f:
                    f.write(res_db.content)

                download_path = f"/static/backups/{panel.id}/{file_name}"
                new_backup = Backup(
                    panel_id=panel.id,
                    file_name=file_name,
                    file_path=download_path
                )
                session.add(new_backup)
                session.commit()
                print(f"بکاپ پنل {panel.remark_prefix} با موفقیت در {local_file_path} ذخیره شد.")

            except requests.exceptions.RequestException as e:
                print(f"خطا در ارتباط با پنل {panel.remark_prefix}: {e}")
            except Exception as e:
                print(f"خطای نامشخص هنگام بکاپ‌گیری از پنل {panel.remark_prefix}: {e}")
    print("پایان فرآیند پشتیبان‌گیری.")

# --- راه‌اندازی اسکجولر ---
scheduler = BackgroundScheduler()
scheduler.add_job(run_all_backups, 'interval', hours=12)
scheduler.add_job(verify_and_fix_subscription_files, 'interval', hours=6)  # Check every 6 hours
scheduler.start()

# --- State و UI صفحه اصلی ---
class IndexState(AuthState):
    panel_count: int = 0
    total_services: int = 0
    inactive_services: int = 0
    total_configs: int = 0
    backup_count: int = 0

    total_traffic_gb: float = 0.0
    total_upload_gb: float = 0.0
    total_download_gb: float = 0.0
    online_configs_count: int = 0

    show_update_dialog: bool = False
    is_updating: bool = False
    update_message: str = ""
    update_status: str = ""

    def load_stats(self):
        """بارگذاری آمار با استفاده از کش"""
        self.check_auth()
        
        # بررسی کش برای آمار
        from .cache_manager import cache_manager, get_cache_key, invalidate_traffic_cache
        
        traffic_cache_key = get_cache_key('TOTAL_TRAFFIC')
        online_cache_key = get_cache_key('ONLINE_USERS')
        
        cached_traffic = cache_manager.get(traffic_cache_key)
        cached_online = cache_manager.get(online_cache_key)
        
        if cached_traffic and cached_online:
            self.total_traffic_gb = cached_traffic.get('total', 0.0)
            self.total_upload_gb = cached_traffic.get('upload', 0.0)
            self.total_download_gb = cached_traffic.get('download', 0.0)
            self.online_configs_count = cached_online
            return
        
        # اگر کش موجود نباشد، از دیتابیس بارگذاری کن
        with rx.session() as session:
            creator = session.query(User).filter(User.username == self.token).first()
            if not creator:
                return

            self.panel_count = session.query(Panel).count()

            if creator.username == "hkhatiri":
                self.total_services = session.query(ManagedService).count()
                self.inactive_services = session.query(ManagedService).filter(ManagedService.end_date < datetime.now()).count()
            else:
                self.total_services = session.query(ManagedService).filter(ManagedService.created_by_id == creator.id).count()
                self.inactive_services = session.query(ManagedService).filter(ManagedService.created_by_id == creator.id, ManagedService.end_date < datetime.now()).count()

            self.total_configs = session.query(PanelConfig).count()
            self.backup_count = session.query(Backup).count()

            self.total_upload_gb = 0.0
            self.total_download_gb = 0.0
            self.online_configs_count = 0
            total_up_bytes = 0
            total_down_bytes = 0

            all_panels = session.query(Panel).all()
            for panel in all_panels:
                try:
                    client = XUIClient(panel.url, panel.username, panel.password)
                    self.online_configs_count += client.get_online_clients_count()
                    traffic_data = client.get_all_inbounds_traffic()
                    total_up_bytes += traffic_data.get("up", 0)
                    total_down_bytes += traffic_data.get("down", 0)
                except Exception as e:
                    print(f"Could not get stats from panel {panel.url}: {e}")

            self.total_upload_gb = total_up_bytes / (1024**3)
            self.total_download_gb = total_down_bytes / (1024**3)
            self.total_traffic_gb = self.total_upload_gb + self.total_download_gb
            
            # ذخیره در کش
            traffic_data = {
                'total': self.total_traffic_gb,
                'upload': self.total_upload_gb,
                'download': self.total_download_gb
            }
            cache_manager.set(traffic_cache_key, traffic_data, ttl=30)
            cache_manager.set(online_cache_key, self.online_configs_count, ttl=30)

    def trigger_update_dialog(self):
        self.update_message = ""
        self.update_status = ""
        self.show_update_dialog = True

    async def sync_services_with_panels(self):
        self.is_updating = True
        self.show_update_dialog = False
        self.update_message = "در حال ارسال درخواست همگام‌سازی به Redis..."
        self.update_status = "info"

        try:
            from .tasks import enqueue_sync_services_with_panels
            task_id = enqueue_sync_services_with_panels()
            
            self.update_message = f"درخواست همگام‌سازی به Redis ارسال شد. Task ID: {task_id}"
            self.update_status = "success"

        except Exception as e:
            self.update_message = f"خطا در ارسال درخواست همگام‌سازی: {str(e)}"
            self.update_status = "error"
        finally:
            self.is_updating = False
            self.load_stats()

# --- کامپوننت‌های قابل استفاده مجدد ---
def stat_card(title: str, value: rx.Var, icon: str, color: str):
    return rx.card(rx.hstack(rx.icon(icon, size=48, color=color), rx.vstack(rx.heading(value.to_string(), size="7"), rx.text(title, color="gray"),align="start"),spacing="4",align="center"),size="3",width="250px")

def traffic_stat_card() -> rx.Component:
    return rx.card(rx.vstack(rx.hstack(rx.icon("arrow-down-up", size=40, color="green"),rx.vstack(rx.heading(f"{IndexState.total_traffic_gb:.2f} GB", size="6"),rx.text("کل ترافیک مصرفی", color="gray"),align="start",),spacing="4",align="center",),rx.divider(margin_y="0.5em"),rx.hstack(rx.badge(rx.text(f"D: {IndexState.total_download_gb:.2f} GB"), color_scheme="blue", variant="soft"),rx.spacer(),rx.badge(rx.text(f"U: {IndexState.total_upload_gb:.2f} GB"), color_scheme="orange", variant="soft"),width="100%",justify="between",),spacing="3",width="100%",),size="3",width="250px")

def update_services_dialog() -> rx.Component:
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("تایید همگام‌سازی سرویس‌ها"),
            rx.alert_dialog.description("این عملیات تمام سرویس‌ها را با تمام پنل‌ها بررسی می‌کند و در صورت نیاز کانفیگ‌های جدید می‌سازد. این کار ممکن است زمان‌بر باشد. آیا مطمئن هستید؟"),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("انصراف", variant="soft", color_scheme="gray")),
                rx.alert_dialog.action(rx.button("بله، همگام‌سازی کن", on_click=IndexState.sync_services_with_panels, color_scheme="teal")),
                spacing="3", margin_top="1em", justify="end",
            ), style={"direction": "rtl"}
        ),
        open=IndexState.show_update_dialog, on_open_change=IndexState.set_show_update_dialog
    )

# --- تعریف صفحه اصلی ---
def index() -> rx.Component:
    return rx.center(rx.vstack(
        update_services_dialog(),
        rx.hstack(
            rx.heading("آمار کلی سیستم", size="8"),
            rx.spacer(),
            rx.button("آپدیت سرویس ها", on_click=IndexState.trigger_update_dialog, size="3", high_contrast=True, color_scheme="teal", variant="soft", loading=IndexState.is_updating),
            align="center", width="100%", margin_bottom="1.5em"
        ),
        rx.cond(
            IndexState.update_message,
            rx.callout(
                IndexState.update_message,
                color_scheme=rx.cond(IndexState.update_status == "success", "grass", rx.cond(IndexState.update_status == "error", "red", "blue")),
                icon=rx.cond(IndexState.update_status == "success", "check_circ", rx.cond(IndexState.update_status == "error", "triangle_alert", "info")),
                width="100%", margin_y="1em"
            )
        ),
        rx.hstack(
            stat_card("کل سرویس‌ها", IndexState.total_services, "users", "blue"),
            stat_card("سرویس‌های غیرفعال", IndexState.inactive_services, "user-x", "red"),
            stat_card("کاربران آنلاین", IndexState.online_configs_count, "wifi", "teal"),
            traffic_stat_card(),
            stat_card("تعداد پنل‌ها", IndexState.panel_count, "server", "orange"),
            stat_card("تعداد بکاپ‌ها", IndexState.backup_count, "database", "purple"),
            spacing="5", justify="center", wrap="wrap"
        ),
        spacing="4", align="center"),
        on_mount=IndexState.load_stats, width="100%", height="80vh"
    )

# --- تعریف اپلیکیشن با تم ---
app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color="teal",
        gray_color="slate",
        panel_background="solid",
        radius="large"
    ),
    style=base_style,
    stylesheets=["/styles.css"],
    api_transformer=api,
)

# --- افزودن صفحات به اپلیکیشن ---
app.add_page(login_page, route="/login")
app.add_page(template(index), route="/", title="داشبورد", on_load=AuthState.check_auth)
app.add_page(template(panels_page), route="/panels", title="مدیریت پنل‌ها", on_load=AuthState.check_auth)
app.add_page(template(backups_page), route="/panels/[panel_id]/backups", title="لیست بکاپ‌ها", on_load=AuthState.check_auth)
app.add_page(template(services_page), route="/dashboard", title="داشبورد سرویس‌ها", on_load=AuthState.check_auth)
app.add_page(template(admin_page), route="/admin", title="مدیریت ادمین‌ها", on_load=AuthState.check_auth)


# --- ایجاد کاربر ادمین اولیه در زمان راه‌اندازی ---
create_initial_admin_user()

# --- Redis Workers are now running separately in background ---
# Use: ./manage_redis_workers.sh {start|stop|restart|status|logs}
# start_redis_workers()  # Removed - workers run separately now