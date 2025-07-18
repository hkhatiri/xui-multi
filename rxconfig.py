import reflex as rx

config = rx.Config(
    app_name="xui_multi",
    db_url="sqlite:///reflex.db", # برای شروع از SQLite استفاده می‌کنیم
    disable_plugins=['reflex.plugins.sitemap.SitemapPlugin']
)