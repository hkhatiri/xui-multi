import reflex as rx
import requests
import os
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from sqlmodel import select
from fastapi.staticfiles import StaticFiles
import base64
import traceback

# --- وارد کردن تمام کامپوننت‌ها و State های لازم ---
from xui_multi.api_routes import api
from xui_multi.panel_page import panels_page, backups_page
from xui_multi.services_page import services_page
from xui_multi.login_page import login_page
from xui_multi.admin_page import admin_page
from xui_multi.auth_state import AuthState, create_initial_admin_user
from .template import template
from .models import Panel, ManagedService, PanelConfig, Backup, User
from .xui_client import XUIClient

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
        self.check_auth()
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

    def trigger_update_dialog(self):
        self.update_message = ""
        self.update_status = ""
        self.show_update_dialog = True

    async def sync_services_with_panels(self):
        self.is_updating = True
        self.show_update_dialog = False
        self.update_message = "در حال بررسی و همگام‌سازی سرویس‌ها..."
        self.update_status = "info"

        try:
            with rx.session() as session:
                all_services = session.query(ManagedService).all()
                all_panels = session.query(Panel).all()
                if not all_panels:
                    self.update_message = "هیچ پنلی برای همگام‌سازی تعریف نشده است."
                    self.update_status = "error"
                    self.is_updating = False
                    return

                services_updated_count = 0
                configs_created_count = 0

                for service in all_services:
                    was_service_updated = False
                    existing_panel_ids = {config.panel_id for config in service.configs}
                    new_links = []

                    creator = session.query(User).filter(User.id == service.created_by_id).first()
                    if not creator:
                        continue

                    for panel in all_panels:
                        if panel.id not in existing_panel_ids:
                            print(f"Service '{service.name}' is missing on panel '{panel.remark_prefix}'. Creating...")
                            try:
                                client = XUIClient(panel.url, panel.username, panel.password)

                                expiry_time_ms = int(service.end_date.timestamp() * 1000)
                                limit_gb_bytes = int(service.data_limit_gb * 1024 * 1024 * 1024)

                                used_ports = set(client.get_used_ports())
                                base_port = 20000

                                vless_port = base_port
                                while vless_port in used_ports: vless_port += 1
                                used_ports.add(vless_port)

                                shadowsocks_port = vless_port + 1
                                while shadowsocks_port in used_ports: shadowsocks_port += 1

                                remark = f"{panel.remark_prefix}-{creator.remark}"
                                vless_remark = f"{remark}-{vless_port}"
                                vless_result = client.create_vless_inbound(vless_remark, panel.domain, vless_port, 0, 0, expiry_time_ms=expiry_time_ms, total_gb_bytes=limit_gb_bytes)
                                new_links.append(vless_result["link"])
                                session.add(PanelConfig(managed_service_id=service.id, panel_id=panel.id, panel_inbound_id=vless_result["inbound_id"], config_link=vless_result["link"]))
                                configs_created_count += 1

                                ss_remark = f"{remark}-{shadowsocks_port}"
                                ss_result = client.create_shadowsocks_inbound(ss_remark, panel.domain, shadowsocks_port, 0, 0, expiry_time_ms=expiry_time_ms, total_gb_bytes=limit_gb_bytes)
                                new_links.append(ss_result["link"])
                                session.add(PanelConfig(managed_service_id=service.id, panel_id=panel.id, panel_inbound_id=ss_result["inbound_id"], config_link=ss_result["link"]))
                                configs_created_count += 1

                                was_service_updated = True
                            except Exception as e:
                                print(f"Error creating config for service {service.name} on panel {panel.url}: {e}")

                    if was_service_updated:
                        services_updated_count += 1
                        if service.subscription_link and new_links:
                            file_name = service.subscription_link.split("/")[-1]
                            file_path = os.path.join("static/subs", file_name)

                            existing_content = ""
                            if os.path.exists(file_path):
                                with open(file_path, "r") as f:
                                    base64_content = f.read()
                                if base64_content:
                                    try:
                                        existing_content = base64.b64decode(base64_content).decode('utf-8')
                                    except Exception:
                                        existing_content = ""

                            all_links_str = existing_content + "\n" + "\n".join(new_links)
                            new_base64_content = base64.b64encode(all_links_str.encode('utf-8')).decode('utf-8')

                            with open(file_path, "w") as f:
                                f.write(new_base64_content)

                if services_updated_count > 0:
                    session.commit()

            self.update_message = f"همگام‌سازی کامل شد. {configs_created_count} کانفیگ جدید برای {services_updated_count} سرویس ساخته شد."
            self.update_status = "success"

        except Exception as e:
            self.update_message = f"خطا در همگام‌سازی: {traceback.format_exc()}"
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