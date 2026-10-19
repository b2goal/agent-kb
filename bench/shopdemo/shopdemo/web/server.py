"""Web UI: server-rendered pages on the standard library http.server.

Run: python -m shopdemo.web.server --port 8800   (database: SHOPDEMO_DB, default ./shopdemo.db)
"""
import argparse
import hashlib
import html
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .. import db, money
from ..inventory import alerts
from ..orders import adjustments, service
from ..reports import daily

SESSIONS = {}          # sid -> {"username", "role"}
REFUND_REASONS = ["Khách đổi ý", "Hàng lỗi", "Giao sai", "Khác"]

STYLE = """
body{font-family:sans-serif;margin:0;background:#f6f6f4}
nav{background:#223;padding:10px 16px}nav a{color:#fff;margin-right:14px;text-decoration:none}
main{padding:16px 24px}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px}
.badge{background:#c33;color:#fff;border-radius:10px;padding:2px 8px}
.toast{position:fixed;bottom:16px;right:16px;background:#2a2;color:#fff;padding:10px 16px}
#help-bar{position:fixed;bottom:0;left:0;right:0;height:64px;background:#ffd;border-top:1px solid #cc9;padding:8px}
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4)}
.modal{background:#fff;width:360px;margin:120px auto;padding:16px;opacity:0;transition:opacity .6s}
.modal.open{opacity:1}
"""

MODAL_JS = """
function openRefund(){var b=document.getElementById('refund-backdrop');b.style.display='block';
 setTimeout(function(){document.getElementById('refund-modal').classList.add('open')},600);}
function reasonChanged(s){document.getElementById('refund-submit').disabled=!s.value;}
"""


def order_token(order_id):
    """Order pages use an opaque key in the URL, not the order number."""
    return hashlib.sha1(f"so-{order_id}".encode()).hexdigest()[:10]


def order_id_for_token(conn, token):
    for (oid,) in conn.execute("SELECT id FROM orders"):
        if order_token(oid) == token:
            return oid
    return None


def esc(v):
    return html.escape(str(v))


def page(title, body, user=None, extra_head=""):
    nav = ""
    if user:
        nav = ("<nav><a href='/dashboard'>Tổng quan</a><a href='/orders'>Đơn hàng</a><a href='/customers'>Khách hàng</a>"
               "<a href='/reports'>Báo cáo</a><a href='/settings'>Cài đặt</a>"
               f"<a href='/logout'>Đăng xuất ({esc(user['username'])})</a></nav>")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{esc(title)} · shopdemo</title>"
            f"<style>{STYLE}</style>{extra_head}</head><body>{nav}<main><h1>{esc(title)}</h1>{body}</main>"
            "<div id='help-bar'>Cần hỗ trợ? Gọi 1900-0000 (giờ hành chính).</div></body></html>")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # ------------------------------------------------------------------ helpers
    def conn(self):
        return db.connect()

    def user(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sid" and v in SESSIONS:
                return SESSIONS[v]
        return None

    def send_html(self, body, code=200, headers=None):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to, headers=None):
        self.send_response(303)
        self.send_header("Location", to)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8")).items()}

    # ------------------------------------------------------------------ routing
    def do_GET(self):
        self._safe(self._get)

    def do_POST(self):
        self._safe(self._post)

    def _safe(self, fn):
        try:
            fn()
        except Exception as exc:          # show a plain 500 page instead of dropping the connection
            self.send_html(page("Lỗi máy chủ", f"<p>500 Internal Server Error: {esc(type(exc).__name__)}</p>"), 500)

    def _get(self):
        url = urlparse(self.path)
        qs = {k: v[0] for k, v in parse_qs(url.query).items()}
        parts = [p for p in url.path.split("/") if p]
        if url.path == "/login":
            return self.login_page()
        user = self.user()
        if not user:
            return self.redirect("/login")
        if url.path in ("/", ""):
            return self.redirect("/dashboard")
        if url.path == "/logout":
            return self.redirect("/login", {"Set-Cookie": "sid=; Max-Age=0"})
        if url.path == "/dashboard":
            return self.dashboard(user)
        if parts == ["orders"]:
            return self.orders(user, int(qs.get("page", 1)), qs.get("q", ""))
        if len(parts) == 3 and parts[:2] == ["orders", "o"]:
            oid = order_id_for_token(self.conn(), parts[2])
            if oid is None:
                return self.send_html(page("Không tìm thấy", "<p>Đơn hàng không tồn tại.</p>", user), 404)
            return self.order_detail(user, oid, qs)
        if parts == ["customers"]:
            return self.customers(user)
        if parts == ["reports"]:
            return self.reports(user)
        if parts == ["settings"]:
            return self.settings_menu(user)
        if parts == ["settings", "ops", "inventory"]:
            if qs.get("tab") == "alerts":
                return self.settings_alerts(user, qs)
            return self.settings_inventory(user)
        return self.send_html(page("Không tìm thấy", "<p>Trang không tồn tại.</p>", user), 404)

    def _post(self):
        url = urlparse(self.path)
        parts = [p for p in url.path.split("/") if p]
        if url.path == "/login":
            return self.login_submit()
        user = self.user()
        if not user:
            return self.redirect("/login")
        if len(parts) == 4 and parts[:2] == ["orders", "o"] and parts[3] == "refund":
            oid = order_id_for_token(self.conn(), parts[2])
            if oid is None:
                return self.send_html(page("Không tìm thấy", "", user), 404)
            return self.refund_submit(user, oid)
        if parts == ["settings", "ops", "inventory", "alerts"]:
            return self.settings_alerts_submit(user)
        return self.send_html(page("Không tìm thấy", "", user), 404)

    # ------------------------------------------------------------------ pages
    def login_page(self, error=""):
        body = ((f"<p style='color:#c33'>{esc(error)}</p>" if error else "") +
                "<form method='post' action='/login'><p><label>Tên đăng nhập <input name='username'></label></p>"
                "<p><label>Mật khẩu <input name='password' type='password'></label></p>"
                "<button type='submit'>Đăng nhập</button></form>")
        return self.send_html(page("Đăng nhập", body))

    def login_submit(self):
        f = self.form()
        conn = self.conn()
        row = conn.execute("SELECT * FROM users WHERE username=? AND password=?",
                           (f.get("username", ""), f.get("password", ""))).fetchone()
        if not row:
            return self.login_page("Sai tên đăng nhập hoặc mật khẩu")
        sid = secrets.token_hex(16)
        SESSIONS[sid] = {"username": row["username"], "role": row["role"]}
        return self.redirect("/dashboard", {"Set-Cookie": f"sid={sid}; Path=/; HttpOnly"})

    def dashboard(self, user):
        conn = self.conn()
        n_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        low = alerts.low_stock_count(conn)
        body = (f"<p>Tổng số đơn: {n_orders}</p>"
                f"<p>Sắp hết hàng: <span id='low-stock-badge' class='badge'>{low}</span> sản phẩm "
                f"(ngưỡng {alerts.get_threshold(conn)})</p>")
        return self.send_html(page("Tổng quan", body, user))

    def orders(self, user, page_no, q=""):
        conn = self.conn()
        rows, total = service.list_orders(conn, page_no)
        if q:
            num = "".join(c for c in q if c.isdigit())
            rows = [service.get_order(conn, int(num))] if num and service.get_order(conn, int(num)) else []
            total = len(rows)
        trs = "".join(f"<tr><td><a href='/orders/o/{order_token(r['id'])}'>SO-{r['id']}</a></td><td>{esc(r['customer'])}</td>"
                      f"<td>{esc(r['status'])}</td><td>{money.format_display(service.order_total(conn, r), service.order_currency(r))}</td></tr>"
                      for r in rows)
        pages = (total + 19) // 20
        links = " ".join(f"<a href='/orders?page={i}'>{i}</a>" for i in range(1, pages + 1))
        search = "<form method='get' action='/orders'><input name='q' placeholder='Mã đơn, ví dụ SO-1001'> <button>Tìm</button></form>"
        body = search + f"<table><tr><th>Mã</th><th>Khách</th><th>Trạng thái</th><th>Tổng</th></tr>{trs}</table><p>Trang: {links}</p>"
        return self.send_html(page("Đơn hàng", body, user))

    def order_detail(self, user, order_id, qs):
        conn = self.conn()
        order = service.get_order(conn, order_id)
        if order is None:
            return self.send_html(page("Không tìm thấy", "<p>Đơn hàng không tồn tại.</p>", user), 404)
        cur = service.order_currency(order)
        lines = service.order_lines(conn, order_id)
        subtotal = service.order_subtotal(conn, order_id)
        after = service._apply_discount(subtotal, order["discount_pct"])
        trs = "".join(f"<tr><td>{esc(l['sku'])}</td><td>{l['quantity']}</td>"
                      f"<td>{money.format_display(l['unit_price_minor'], cur)}</td></tr>" for l in lines)
        refunds = conn.execute("SELECT * FROM refunds WHERE order_id=? ORDER BY id", (order_id,)).fetchall()
        rtrs = "".join(f"<li>{money.format_display(r['amount_minor'], r['currency'])} — {esc(r['reason'])}</li>"
                       for r in refunds) or "<li>Chưa có</li>"
        options = "".join(f"<option>{esc(r)}</option>" for r in REFUND_REASONS)
        toast = "<div class='toast' id='toast'>Đã hoàn tiền</div>" if qs.get("ok") else ""
        err = f"<p style='color:#c33' id='refund-error'>{esc(qs['error'])}</p>" if qs.get("error") else ""
        body = (f"<h2>Đơn hàng SO-{order_id}</h2><p>Khách: {esc(order['customer'])} · Trạng thái: {esc(order['status'])}</p>"
                f"<table><tr><th>SKU</th><th>SL</th><th>Đơn giá</th></tr>{trs}</table>"
                f"<p>Tạm tính: {money.format_display(subtotal, cur)} · Giảm {order['discount_pct']}% · "
                f"Tổng: <b>{money.format_display(after, cur)}</b></p>{err}"
                f"<h3>Hoàn tiền</h3><ul>{rtrs}</ul><button onclick='openRefund()'>Hoàn tiền</button>"
                f"<div class='modal-backdrop' id='refund-backdrop'><div class='modal' id='refund-modal'>"
                f"<form method='post' action='/orders/o/{order_token(order_id)}/refund'><h3>Hoàn tiền đơn SO-{order_id}</h3>"
                f"<p><label>Số tiền ({cur}) <input name='amount' id='refund-amount'></label></p>"
                f"<p><label>Lý do <select name='reason' id='refund-reason' onchange='reasonChanged(this)'>"
                f"<option value=''>-- chọn --</option>{options}</select></label></p>"
                f"<button type='submit' id='refund-submit' disabled>Gửi yêu cầu</button></form></div></div>{toast}")
        return self.send_html(page(f"Đơn hàng SO-{order_id}", body, user, f"<script>{MODAL_JS}</script>"))

    def refund_submit(self, user, order_id):
        conn = self.conn()
        order = service.get_order(conn, order_id)
        if order is None:
            return self.send_html(page("Không tìm thấy", "", user), 404)
        f = self.form()
        try:
            amount = money.parse_amount(f.get("amount", ""), service.order_currency(order))
            adjustments.create_refund(conn, order_id, amount, f.get("reason", ""))
        except (ValueError, adjustments.RefundError) as exc:
            return self.redirect(f"/orders/o/{order_token(order_id)}?error={esc(str(exc))}")
        return self.redirect(f"/orders/o/{order_token(order_id)}?ok=1")

    def customers(self, user):
        conn = self.conn()
        trs = "".join(f"<tr><td>{r['id']}</td><td>{esc(r['name'])}</td></tr>"
                      for r in conn.execute("SELECT * FROM customers ORDER BY id"))
        return self.send_html(page("Khách hàng", f"<table>{trs}</table>", user))

    def reports(self, user):
        conn = self.conn()
        trs = "".join(f"<tr><td>{d}</td><td>{money.format_display(v, 'VND')}</td></tr>"
                      for d, v in sorted(daily.daily_totals(conn).items()))
        return self.send_html(page("Báo cáo doanh thu ngày", f"<table>{trs}</table>", user))

    def settings_menu(self, user):
        body = ("<details><summary>Chung</summary><ul><li><a href='/settings/store'>Cửa hàng</a></li>"
                "<li><a href='/settings/users'>Người dùng</a></li></ul></details>"
                "<details><summary>Bán hàng</summary><ul><li><a href='/settings/sales/payments'>Thanh toán</a></li>"
                "<li><a href='/settings/sales/shipping'>Vận chuyển</a></li></ul></details>"
                "<details><summary>Vận hành</summary><ul><li><a href='/settings/ops/inventory'>Kho hàng</a></li>"
                "<li><a href='/settings/ops/returns'>Đổi trả</a></li></ul></details>")
        return self.send_html(page("Cài đặt", body, user))

    def settings_inventory(self, user):
        body = ("<p><a href='/settings/ops/inventory?tab=units'>Đơn vị tính</a> | <a href='/settings/ops/inventory?tab=warehouses'>Kho</a>"
                " | <a href='/settings/ops/inventory?tab=alerts'>Cảnh báo</a></p><p>Chọn một tab.</p>")
        return self.send_html(page("Cài đặt kho hàng", body, user))

    def settings_alerts(self, user, qs):
        if user["role"] != "admin":
            body = "<p>Cần quyền quản trị. <a href='/logout'>Đăng nhập bằng tài khoản quản trị</a></p>"
            return self.send_html(page("Không có quyền", body, user), 403)
        conn = self.conn()
        saved = "<p class='toast'>Đã lưu</p>" if qs.get("saved") else ""
        body = (f"{saved}<form method='post' action='/settings/ops/inventory/alerts'>"
                f"<p><label>Ngưỡng tồn kho thấp <input name='threshold' value='{alerts.get_threshold(conn)}'></label></p>"
                "<button type='submit'>Lưu</button></form>")
        return self.send_html(page("Cảnh báo tồn kho", body, user))

    def settings_alerts_submit(self, user):
        if user["role"] != "admin":
            return self.send_html(page("Không có quyền", "", user), 403)
        f = self.form()
        alerts.set_threshold(self.conn(), f.get("threshold", "0"))
        return self.redirect("/settings/ops/inventory?tab=alerts&saved=1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args()
    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"shopdemo on http://127.0.0.1:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
