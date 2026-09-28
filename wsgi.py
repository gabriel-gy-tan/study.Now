from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app

app = create_app()

# Render terminates TLS upstream and forwards the real scheme in headers, so
# without this every request looks like plain HTTP: `request.is_secure` is
# False, no session cookie gets `Secure`, and HSTS is never sent. The hop
# counts match Render's single proxy hop and the headers it actually sets.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
