"""
test_app.py
A tiny Flask web app with INTENTIONAL bugs planted in it.
This is our test target for the crawler.

Bugs planted:
  1. /broken-button  — a button with wrong JS that throws an error
  2. /slow-page      — sleeps 4 seconds before responding (slow load)
  3. /blank          — returns almost empty page
  4. /checkout       — a multi-step form flow

Run: python test_app.py  (starts on http://localhost:5001)
"""
import time
from flask import Flask, redirect, url_for

app = Flask(__name__)

NAV = """
<nav style="font-family:sans-serif;padding:12px;background:#f0f0f0;">
  <a href="/" style="margin-right:12px">Home</a>
  <a href="/about" style="margin-right:12px">About</a>
  <a href="/products" style="margin-right:12px">Products</a>
  <a href="/checkout" style="margin-right:12px">Checkout</a>
  <a href="/broken-button" style="margin-right:12px">Broken Button</a>
  <a href="/blank" style="margin-right:12px">Blank Page</a>
  <a href="/slow-page">Slow Page</a>
</nav>
"""

@app.route("/")
def home():
    return f"""<!DOCTYPE html><html><head><title>TestShop</title></head><body>
{NAV}
<h1 style="font-family:sans-serif;margin:24px">Welcome to TestShop</h1>
<p style="font-family:sans-serif;margin:24px">
  A demo e-commerce site for ProductValidation OS testing.<br>
  Browse our products, checkout, or hit one of the intentionally broken pages.
</p>
<a href="/products" style="font-family:sans-serif;padding:10px 20px;background:#185FA5;
   color:white;border-radius:6px;text-decoration:none;margin:24px;display:inline-block">
  Shop Now
</a>
</body></html>"""

@app.route("/about")
def about():
    return f"""<!DOCTYPE html><html><head><title>About — TestShop</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px">
  <h1>About Us</h1>
  <p>We sell books, electronics, and other things. Established 2024.</p>
  <p>Contact: <a href="mailto:test@testshop.com">test@testshop.com</a></p>
</div></body></html>"""

@app.route("/products")
def products():
    items = [("Python Crash Course", "$29"), ("Clean Code", "$34"), ("DDIA", "$45")]
    cards = "".join(
        '<div style="border:1px solid #ddd;padding:16px;border-radius:8px;width:160px">'
        f'<p style="font-weight:bold">{name}</p><p style="color:#666">{price}</p>'
        f'<a href="/checkout" '
        'style="background:#185FA5;color:white;padding:6px 12px;border-radius:4px;'
        'text-decoration:none;font-size:13px">Buy</a></div>'
        for name, price in items
    )
    return f"""<!DOCTYPE html><html><head><title>Products — TestShop</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px">
  <h1>Products</h1>
  <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:16px">{cards}</div>
</div></body></html>"""

@app.route("/checkout")
def checkout():
    return f"""<!DOCTYPE html><html><head><title>Checkout — TestShop</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px;max-width:400px">
  <h1>Checkout</h1>
  <label>Name<br><input type="text" id="name" placeholder="Your name" style="width:100%;padding:8px;margin:4px 0 12px"></label>
  <label>Email<br><input type="email" id="email" placeholder="you@example.com" style="width:100%;padding:8px;margin:4px 0 12px"></label>
  <button onclick="submitOrder()"
    style="background:#185FA5;color:white;padding:10px 24px;border:none;border-radius:6px;cursor:pointer;font-size:15px">
    Place Order
  </button>
</div>
<script>
function submitOrder() {{
  var name = document.getElementById('name').value;
  if (!name) {{ alert('Please enter your name'); return; }}
  window.location.href = '/order-confirmed';
}}
</script>
</body></html>"""

@app.route("/order-confirmed")
def order_confirmed():
    return f"""<!DOCTYPE html><html><head><title>Order Confirmed!</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px;text-align:center">
  <h1 style="color:#0F6E56">Order Confirmed!</h1>
  <p>Thank you for your purchase. Your order is being processed.</p>
  <a href="/">Back to home</a>
</div></body></html>"""

# ── BUGGY PAGES ────────────────────────────────────────────────────────────

@app.route("/broken-button")
def broken_button():
    """BUG 1: Button fires a JS ReferenceError."""
    return f"""<!DOCTYPE html><html><head><title>Broken Button</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px">
  <h1>Special Offer</h1>
  <p>Click the button below to claim your discount:</p>
  <button onclick="claimDiscount()"
    style="background:#D85A30;color:white;padding:10px 24px;border:none;
           border-radius:6px;cursor:pointer;font-size:15px">
    Claim 20% Off
  </button>
</div>
<script>
// BUG: claimDiscount is not defined — will throw ReferenceError
// (pretending the dev forgot to include the script)
</script>
</body></html>"""

@app.route("/blank")
def blank():
    """BUG 2: Nearly empty page (broken template)."""
    return """<!DOCTYPE html><html><head><title></title></head><body>
</body></html>"""

@app.route("/slow-page")
def slow_page():
    """BUG 3: Page takes 4.5 seconds to respond."""
    time.sleep(4.5)
    return f"""<!DOCTYPE html><html><head><title>Slow Page</title></head><body>
{NAV}
<div style="font-family:sans-serif;margin:24px">
  <h1>Analytics Dashboard</h1>
  <p>This page loads slowly because it waits for a heavy DB query.</p>
</div></body></html>"""

if __name__ == "__main__":
    print("Starting TestShop on http://localhost:5001")
    print("Bugs planted: /broken-button (JS error), /blank (empty page), /slow-page (4.5s load)")
    app.run(port=5001, debug=False)
