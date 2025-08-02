import reflex as rx

config = rx.Config(
    app_name="xui_multi",
    db_url="postgresql://hkhatiri:Kiri.BashaKoni1471@localhost:5432/xui_multi", # PostgreSQL connection
    disable_plugins=['reflex.plugins.sitemap.SitemapPlugin'],
    # Disable HTTPS redirect for development
    frontend_port=3000,
    backend_port=8000,
    # Force HTTP mode
    api_url="http://localhost:8000",
    deploy_url="http://multi.antihknet.com:3000"
)
