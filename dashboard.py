"""Read-only local web dashboard for the trading bot.

Bind to 127.0.0.1 by default. Do not expose this unauthenticated dashboard publicly.
"""
from __future__ import annotations
import html, json, os
from wsgiref.simple_server import make_server
from trading_store import TradingStore

STORE = TradingStore()

PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>RSI Bot Dashboard</title><style>
body{font:16px system-ui;background:#0b1020;color:#e8edf7;margin:0;padding:24px}
main{max-width:1100px;margin:auto}h1{font-size:28px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
article{background:#151d32;border:1px solid #293653;border-radius:12px;padding:16px;overflow:auto}
small{color:#9daecb}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:10px;border-bottom:1px solid #293653}
.pill{display:inline-block;background:#233b34;color:#8bf0b4;border-radius:20px;padding:5px 9px}
</style></head><body><main><h1>Crypto RSI Bot</h1><p><span class="pill">Read-only dashboard</span> <small id="updated">Loading…</small></p>
<div class="grid"><article><small>Mode</small><h2 id="mode">—</h2></article><article><small>Latest equity</small><h2 id="equity">—</h2></article>
<article><small>Position size</small><h2 id="position">—</h2></article><article><small>Last mark price</small><h2 id="price">—</h2></article></div>
<h2>Recent trades</h2><article><table><thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Amount</th><th>Price</th><th>Status</th></tr></thead><tbody id="trades"></tbody></table></article>
<h2>Recent bot events</h2><article id="events">No events recorded.</article></main>
<script>
async function refresh(){try{
const [s,t,e]=await Promise.all([fetch('/api/status').then(r=>r.json()),fetch('/api/trades').then(r=>r.json()),fetch('/api/events').then(r=>r.json())]);
document.querySelector('#mode').textContent=s.mode||'No snapshots';document.querySelector('#equity').textContent=s.equity==null?'—':Number(s.equity).toFixed(2)+' '+(s.quote_currency||'');
document.querySelector('#position').textContent=s.position_amount==null?'—':Number(s.position_amount).toPrecision(6);
document.querySelector('#price').textContent=s.mark_price==null?'—':Number(s.mark_price).toPrecision(8);
document.querySelector('#updated').textContent='Updated '+new Date().toLocaleTimeString();
document.querySelector('#trades').innerHTML=t.map(x=>'<tr><td>'+esc(x.created_at)+'</td><td>'+esc(x.symbol)+'</td><td>'+esc(x.side)+'</td><td>'+Number(x.amount).toPrecision(6)+'</td><td>'+Number(x.price).toPrecision(8)+'</td><td>'+esc(x.status)+'</td></tr>').join('')||'<tr><td colspan="6">No trades recorded yet.</td></tr>';
document.querySelector('#events').innerHTML=e.map(x=>'<p><small>'+esc(x.created_at)+'</small> <b>'+esc(x.level)+'</b> '+esc(x.event)+'</p>').join('')||'No events recorded.';
}catch(err){document.querySelector('#updated').textContent='Unable to load local data';}}
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
refresh();setInterval(refresh,10000);
</script></body></html>"""

def application(environ, start_response):
    path = environ.get("PATH_INFO", "/")
    if path == "/":
        body, content_type = PAGE.encode(), "text/html; charset=utf-8"
    elif path == "/api/status":
        snapshots = STORE.recent_snapshots(1)
        body = json.dumps(snapshots[0] if snapshots else {"mode": None}).encode()
        content_type = "application/json"
    elif path == "/api/trades":
        body, content_type = json.dumps(STORE.recent_trades(100)).encode(), "application/json"
    elif path == "/api/events":
        body, content_type = json.dumps(STORE.recent_events(50)).encode(), "application/json"
    else:
        body, content_type = b'{"error":"not found"}', "application/json"
        start_response("404 Not Found", [("Content-Type", content_type)])
        return [body]
    start_response("200 OK", [("Content-Type", content_type), ("Cache-Control", "no-store"),
                              ("X-Content-Type-Options", "nosniff")])
    return [body]

if __name__ == "__main__":
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    print(f"Dashboard listening on http://{host}:{port} (read-only; keep it private)")
    with make_server(host, port, application) as server:
        server.serve_forever()
