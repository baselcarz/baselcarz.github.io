import html
import json
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTS_JS = ROOT / "assets" / "products.js"
PRODUCTS_DIR = ROOT / "products"
ASSET_PRODUCTS_DIR = ROOT / "assets" / "products"
DETAILS_JSON = ROOT / "tmp-ebay-details.json"
SELLER_SEARCH_CACHE = ROOT / "tmp-seller-search.html"
DISCOUNT_PERCENT = 15
STORE_URL = "https://www.ebay.com/usr/basel.carz"
SELLER_SEARCH_URL = (
    "https://www.ebay.com/sch/basel.carz/m.html"
    "?_dkr=1&iconV2Request=true&_blrs=recall_filtering"
    "&_ssn=basel.carz&_oac=1&_ipg=240"
)
CSS_VERSION = "gallery-arrows-1"
STORE_VERSION = "paypal-order-summary-1"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_text(url):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read().decode("utf-8", errors="replace")


def normalize_text(value):
    value = html.unescape(value or "")
    replacements = {
        "\u00a0": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u00b0": "deg",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def parse_price(value):
    value = html.unescape(value or "")
    match = re.search(r"\$([0-9][0-9,]*(?:\.[0-9]{1,2})?)", value)
    if not match:
        raise ValueError(f"Could not parse price from {value!r}")
    return round(float(match.group(1).replace(",", "")), 2)


def money(value):
    return f"${value:,.2f}"


def html_escape(value):
    return html.escape(str(value), quote=True)


def js_string(value):
    return json.dumps(value, ensure_ascii=False)


def load_existing_products():
    text = PRODUCTS_JS.read_text(encoding="utf-8")
    text = re.sub(r"^window\.BASEL_PRODUCTS\s*=\s*", "", text).rstrip()
    if text.endswith(";"):
        text = text[:-1]
    products = json.loads(text)
    return {product["id"]: product for product in products}


def parse_listing_cards(markup):
    products = []
    article_pattern = re.compile(
        r"<article\s+data-testid=ig-(\d{12})\b(?P<body>.*?)</article>",
        re.DOTALL,
    )
    for match in article_pattern.finditer(markup):
        item_id = match.group(1)
        body = match.group("body")
        title_match = re.search(
            r'<span class=str-text-span aria-hidden=true>(.*?)</span>',
            body,
            re.DOTALL,
        )
        if not title_match:
            title_match = re.search(r'aria-label="([^"]+)"', body)
        price_match = re.search(
            r'str-item-card__property-displayPrice">([^<]+)</span>',
            body,
            re.DOTALL,
        )
        image_match = re.search(
            r"https://i\.ebayimg\.com/images/g/[^\"'\s>]+/s-l300\.jpg",
            body,
        )
        if not title_match or not price_match:
            continue
        title = normalize_text(title_match.group(1))
        original_price = parse_price(price_match.group(1))
        profile_image = image_match.group(0) if image_match else None
        products.append(
            {
                "id": item_id,
                "title": title,
                "originalPrice": original_price,
                "profileImage": profile_image,
            }
        )
    return products


def parse_seller_search_cards(markup):
    products = []
    item_pattern = re.compile(
        r'<li\b(?=[^>]*class="s-card[^"]*")(?=[^>]*data-listingid=(?P<id>\d{12})(?!\d))[^>]*>(?P<body>.*?)</li>',
        re.DOTALL,
    )
    for match in item_pattern.finditer(markup):
        item_id = match.group("id")
        body = match.group("body")
        if f"/itm/{item_id}" not in body:
            continue
        title_match = re.search(
            r'class=s-card__title>.*?<span class="su-styled-text primary default">(.*?)</span>',
            body,
            re.DOTALL,
        )
        if not title_match:
            title_match = re.search(r'alt="([^"]+)"', body)
        price_match = re.search(
            r's-card__price">([^<]+)</span>',
            body,
            re.DOTALL,
        )
        image_match = re.search(
            r"https://i\.ebayimg\.com/images/g/[^\"'\s>]+/s-l(?:500|300|140)\.jpg",
            body,
        )
        if not title_match or not price_match:
            continue
        title = normalize_text(title_match.group(1))
        original_price = parse_price(price_match.group(1))
        profile_image = image_match.group(0) if image_match else None
        products.append(
            {
                "id": item_id,
                "title": title,
                "originalPrice": original_price,
                "profileImage": profile_image,
            }
        )
    return products


def fetch_seller_search_listings():
    try:
        markup = fetch_text(SELLER_SEARCH_URL)
        SELLER_SEARCH_CACHE.write_text(markup, encoding="utf-8", newline="\n")
    except Exception:
        if not SELLER_SEARCH_CACHE.exists():
            powershell_fetch(SELLER_SEARCH_URL, SELLER_SEARCH_CACHE)
        print("seller search: using cached eBay HTML")
        markup = SELLER_SEARCH_CACHE.read_text(encoding="utf-8", errors="replace")
    listings = []
    seen = set()
    for item in parse_seller_search_cards(markup):
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        listings.append(item)
    print(f"seller search: {len(listings)} cards")
    return listings


def powershell_fetch(url, destination):
    command = (
        "$headers=@{"
        "'User-Agent'='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36';"
        "'Accept-Language'='en-US,en;q=0.9'"
        "};"
        f"$r=Invoke-WebRequest -Uri '{url}' -UseBasicParsing -Headers $headers -TimeoutSec 45;"
        f"Set-Content -LiteralPath '{destination}' -Value $r.Content -Encoding UTF8"
    )
    subprocess.check_call(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=str(ROOT),
    )


def fetch_current_listings(max_pages=8, quiet_pages_to_stop=2):
    search_listings = fetch_seller_search_listings()
    if search_listings:
        return search_listings

    listings = []
    seen = set()
    quiet_pages = 0
    for page in range(1, max_pages + 1):
        url = STORE_URL if page == 1 else f"{STORE_URL}?_pgn={page}"
        markup = fetch_text(url)
        page_items = parse_listing_cards(markup)
        new_on_page = 0
        for item in page_items:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            listings.append(item)
            new_on_page += 1
        print(f"page {page}: {len(page_items)} cards, {new_on_page} new")
        if page > 1 and new_on_page == 0:
            quiet_pages += 1
        else:
            quiet_pages = 0
        if page > 2 and quiet_pages >= quiet_pages_to_stop:
            break
        time.sleep(0.25)
    return listings


def load_browser_details():
    if not DETAILS_JSON.exists():
        return {}
    return json.loads(DETAILS_JSON.read_text(encoding="utf-8"))


def image_url_to_jpg(url):
    url = url.replace(".webp", ".jpg")
    url = re.sub(r"/s-l\d+\.(jpg|webp)$", "/s-l1600.jpg", url)
    return url


def download_file(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        destination.write_bytes(response.read())


def ensure_new_images(product, details):
    item_id = product["id"]
    item_dir = ASSET_PRODUCTS_DIR / item_id
    existing_images = sorted(item_dir.glob("*.jpg"))
    if existing_images:
        return [f"/assets/products/{item_id}/{path.name}" for path in existing_images]

    detail = details.get(item_id, {})
    urls = detail.get("imageUrls") or []
    if not urls and product.get("profileImage"):
        urls = [product["profileImage"]]
    if not urls:
        raise RuntimeError(f"No images found for new product {item_id}")

    urls = [image_url_to_jpg(url) for url in urls]
    unique_urls = []
    seen_urls = set()
    for url in urls:
        if url in seen_urls:
            continue
        seen_urls.add(url)
        unique_urls.append(url)

    item_dir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(unique_urls, start=1):
        download_file(url, item_dir / f"{index:02d}.jpg")
    return [f"/assets/products/{item_id}/{index:02d}.jpg" for index in range(1, len(unique_urls) + 1)]


def product_from_listing(listing, existing, details):
    item_id = listing["id"]
    original_price = listing["originalPrice"]
    sale_price = round(original_price * (100 - DISCOUNT_PERCENT) / 100, 2)
    savings = round(original_price - sale_price, 2)
    old = existing.get(item_id, {})
    if old.get("images"):
        images = old["images"]
    else:
        images = ensure_new_images(listing, details)
    return {
        "id": item_id,
        "title": listing["title"],
        "originalPrice": original_price,
        "salePrice": sale_price,
        "savings": savings,
        "discountPercent": DISCOUNT_PERCENT,
        "currency": "USD",
        "quantityText": "1 remaining",
        "image": images[0],
        "images": images,
        "detailUrl": f"/products/{item_id}.html",
    }


def render_header():
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
"""


def render_meta(title, description, url, page_type="website"):
    escaped_title = html_escape(title)
    escaped_description = html_escape(description)
    escaped_url = html_escape(url)
    return f"""  <title>{escaped_title}</title>
  <meta name="description" content="{escaped_description}">
  <link rel="canonical" href="{escaped_url}">
  <meta property="og:type" content="{page_type}">
  <meta property="og:site_name" content="Basel Carz">
  <meta property="og:title" content="{escaped_title}">
  <meta property="og:description" content="{escaped_description}">
  <meta property="og:url" content="{escaped_url}">
  <meta property="og:image" content="https://baselcarz.github.io/assets/basel-carz-social-card.jpg?v=social-preview-1">
  <meta property="og:image:secure_url" content="https://baselcarz.github.io/assets/basel-carz-social-card.jpg?v=social-preview-1">
  <meta property="og:image:type" content="image/jpeg">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="Basel Carz logo with Diecast Model Cars text">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{escaped_title}">
  <meta name="twitter:description" content="{escaped_description}">
  <meta name="twitter:image" content="https://baselcarz.github.io/assets/basel-carz-social-card.jpg?v=social-preview-1">
  <meta name="twitter:image:alt" content="Basel Carz logo with Diecast Model Cars text">
  <link rel="stylesheet" href="/assets/styles.css?v={CSS_VERSION}">
</head>
<body>
"""


def render_nav():
    return """  <header class="topbar">
    <nav class="nav" aria-label="Main navigation">
      <a class="brand" href="/" aria-label="Basel Carz home">
        <strong>Basel Carz</strong>
        <span>Collectible diecast and resin model cars</span>
      </a>
      <div class="nav-links">
        <a href="/#product-grid">Shop</a>
        <a class="cart-link" href="#cart-panel">Cart <span id="nav-cart-count">0</span></a>
      </div>
    </nav>
  </header>
"""


def render_price_row(product, detail=False):
    klass = "price-row detail-price" if detail else "price-row"
    return (
        f'<div class="{klass}" aria-label="Price with discount">'
        f'<span class="original-price">{money(product["originalPrice"])}</span>'
        f'<span class="sale-price">{money(product["salePrice"])}</span></div>'
    )


def render_cart_panel():
    return """      <aside class="cart-panel" id="cart-panel" aria-label="Shopping cart">
        <h2>Your Cart</h2>
        <p class="cart-note">Add items, choose a delivery area, then pay with PayPal when U.S. shipping is available.</p>
        <p class="empty-cart" id="empty-cart">Your cart is empty.</p>
        <div class="cart-items" id="cart-items"></div>
        <section class="shipping-section" aria-label="Shipping options">
          <h3>Shipping</h3>
          <label class="shipping-field" for="shipping-zone">
            Delivery area
            <select id="shipping-zone">
              <option value="usa">U.S. shipping</option>
              <option value="international">International order</option>
            </select>
          </label>
          <div class="shipping-rate-card" id="us-shipping-message">
            <p><strong>U.S. shipping</strong><span id="shipping-rate-note">Add cars to see the shipping cost.</span></p>
          </div>
          <div class="international-message" id="international-message" hidden>
            <p>International buyers: Please contact us on Instagram for a shipping quote, or purchase through our eBay store.</p>
            <div class="international-actions">
              <a class="button" id="instagram-link" href="https://www.instagram.com/basel_carz/" target="_blank" rel="noopener">Contact Us on Instagram</a>
              <a class="button secondary" id="ebay-link" href="https://www.ebay.com/usr/basel.carz" target="_blank" rel="noopener">Shop on eBay</a>
            </div>
          </div>
        </section>
        <div class="totals" aria-live="polite">
          <div><span>Original subtotal</span><strong id="original-subtotal">$0.00</strong></div>
          <div><span>Discount</span><strong id="discount-total">-$0.00</strong></div>
          <div><span>Sale subtotal</span><strong id="sale-subtotal">$0.00</strong></div>
          <div><span>Shipping</span><strong id="shipping-total">$0.00</strong></div>
          <div class="total-row"><span>Total</span><strong id="cart-total">$0.00</strong></div>
        </div>
        <button class="button" id="paypal-button" type="button">Pay with PayPal</button>
        <p class="paypal-message" id="paypal-message">Add at least one item to continue to PayPal.</p>
      </aside>
"""


def render_footer():
    return f"""  <footer class="footer">
    <div class="footer-inner">
      <div>
        <span class="footer-brand">Basel Carz</span>
        <span class="footer-copy">U.S. shipping is calculated by the number of cars in your cart. International buyers, please contact us for a quote.</span>
      </div>
      <div class="footer-social" aria-label="Basel Carz links">
        <a class="footer-social-card" href="https://www.ebay.com/usr/basel.carz" target="_blank" rel="noopener">
          <span class="social-logo social-logo-ebay">eBay</span>
          <span><span class="social-action">Shop on eBay</span><span class="social-platform">Basel Carz eBay store</span></span>
        </a>
        <a class="footer-social-card" href="https://www.instagram.com/basel_carz/" target="_blank" rel="noopener">
          <span class="social-logo" aria-hidden="true"><svg viewBox="0 0 24 24" role="img"><path d="M7.5 2h9A5.5 5.5 0 0 1 22 7.5v9a5.5 5.5 0 0 1-5.5 5.5h-9A5.5 5.5 0 0 1 2 16.5v-9A5.5 5.5 0 0 1 7.5 2Zm0 2A3.5 3.5 0 0 0 4 7.5v9A3.5 3.5 0 0 0 7.5 20h9a3.5 3.5 0 0 0 3.5-3.5v-9A3.5 3.5 0 0 0 16.5 4h-9Zm4.5 3.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Zm0 2a2.5 2.5 0 1 0 0 5 2.5 2.5 0 0 0 0-5Zm5.1-2.55a1.05 1.05 0 1 1 0 2.1 1.05 1.05 0 0 1 0-2.1Z"/></svg></span>
          <span><span class="social-action">Follow us on Instagram</span><span class="social-platform">@basel_carz</span></span>
        </a>
        <a class="footer-social-card" href="https://www.facebook.com/basel.carz/" target="_blank" rel="noopener">
          <span class="social-logo" aria-hidden="true"><svg viewBox="0 0 24 24" role="img"><path d="M14 8h3V4h-3c-3 0-5 2-5 5v3H6v4h3v6h4v-6h3.2l.8-4h-4V9c0-.6.4-1 1-1Z"/></svg></span>
          <span><span class="social-action">Follow us on Facebook</span><span class="social-platform">Basel Carz</span></span>
        </a>
      </div>
    </div>
  </footer>
  <script src="/assets/products.js"></script><script src="/assets/store.js?v={STORE_VERSION}"></script>
</body>
</html>
"""


def render_card(product):
    title = html_escape(product["title"])
    detail_url = html_escape(product["detailUrl"])
    data_title = html_escape(product["title"].lower())
    return f"""
          <article class="product-card" data-id="{product['id']}" data-title="{data_title}">
            <a class="product-image-wrap" href="{detail_url}" aria-label="View {title}">
              <img src="{html_escape(product['image'])}" alt="{title}" loading="lazy">
            </a>
            <div class="product-body">
              <div class="product-meta"><span>Item #{product['id']}</span><span>{len(product['images'])} photos</span></div>
              <h3><a href="{detail_url}">{title}</a></h3>
              {render_price_row(product)}
              <p class="discount-note">{DISCOUNT_PERCENT}% off. You save {money(product['savings'])}.</p>
              <div class="card-actions">
                <button class="button add-button" type="button" data-add-to-cart="{product['id']}">Add to cart</button>
                <a class="button secondary" href="{detail_url}">View details</a>
              </div>
            </div>
          </article>
"""


def render_index(products):
    count = len(products)
    photo_count = sum(len(product["images"]) for product in products)
    description = (
        "Basel Carz collectible diecast and resin model cars with cart, "
        "PayPal checkout, and U.S. shipping by cart size."
    )
    cards = "".join(render_card(product) for product in products)
    return (
        render_header()
        + render_meta("Basel Carz | Diecast Model Cars", description, "https://baselcarz.github.io/")
        + render_nav()
        + f"""  <main id="top" class="section">
    <section class="section-title" aria-labelledby="inventory-heading">
      <p class="eyebrow">Current Collection</p>
      <h1 id="inventory-heading">Basel Carz</h1>
      <p class="lead">Browse {count} collectible model cars. Every item has a full photo page, {DISCOUNT_PERCENT}% sale pricing, PayPal checkout, and U.S. shipping by cart size.</p>
      <div class="summary-row" aria-label="Store summary">
        <span class="pill">{count} products</span>
        <span class="pill">{photo_count} product photos</span>
        <span class="pill">{DISCOUNT_PERCENT}% off every item</span>
        <span class="pill">USD pricing</span>
        <span class="pill">U.S. shipping by car count</span>
      </div>
    </section>
    <div class="store-layout">
      <section aria-label="Products">
        <div class="toolbar">
          <input class="search-box" id="inventory-search" type="search" placeholder="Search by model, brand, or item number" aria-label="Search products">
          <p class="result-count" id="result-count">Showing {count} products</p>
        </div>
        <div class="product-grid" id="product-grid">
{cards}        </div>
        <p class="no-results" id="no-results">No products match your search.</p>
      </section>
{render_cart_panel()}    </div>
  </main>
"""
        + render_footer()
    )


def render_product_page(product):
    title = product["title"]
    escaped_title = html_escape(title)
    description = (
        f"{title} at Basel Carz with {len(product['images'])} product photos, "
        f"{DISCOUNT_PERCENT}% sale pricing, and PayPal checkout."
    )
    thumbs = "\n".join(
        f'              <button class="thumb-button{" is-active" if i == 0 else ""}" type="button" data-gallery-thumb="{i}" aria-label="Show photo {i + 1} of {len(product["images"])}"><img src="{html_escape(src)}" alt=""></button>'
        for i, src in enumerate(product["images"])
    )
    return (
        render_header()
        + render_meta(
            f"{title} | Basel Carz",
            description,
            f"https://baselcarz.github.io/products/{product['id']}.html",
            page_type="product",
        )
        + render_nav()
        + f"""  <main class="section product-detail">
    <a class="breadcrumb" href="/#product-grid">Back to shop</a>
    <div class="detail-layout">
      <section class="gallery" data-gallery data-product-id="{product['id']}" aria-label="Product photo gallery">
        <div class="gallery-main">
          <button class="gallery-arrow prev" type="button" data-gallery-prev aria-label="Previous photo">&lt;</button>
          <img id="gallery-main-image" src="{html_escape(product['images'][0])}" alt="{escaped_title} photo 1">
          <button class="gallery-arrow next" type="button" data-gallery-next aria-label="Next photo">&gt;</button>
        </div>
        <div class="gallery-status"><span>Photos</span><strong id="gallery-count">1 / {len(product['images'])}</strong></div>
        <div class="thumb-strip" aria-label="Photo thumbnails">
{thumbs}
        </div>
      </section>
      <div>
        <section class="detail-panel">
          <p class="eyebrow">Item #{product['id']}</p>
          <h1>{escaped_title}</h1>
          {render_price_row(product, detail=True)}
          <p class="discount-note">{DISCOUNT_PERCENT}% off. You save {money(product['savings'])}.</p>
          <ul class="detail-list">
            <li><span>Photos</span><strong>{len(product['images'])}</strong></li>
            <li><span>Availability</span><strong>{html_escape(product['quantityText'])}</strong></li>
            <li><span>Currency</span><strong>USD</strong></li>
            <li><span>U.S. shipping</span><strong>Calculated in cart</strong></li>
            <li><span>International orders</span><strong>Quote required</strong></li>
          </ul>
          <button class="button" type="button" data-add-to-cart="{product['id']}">Add to cart</button>
        </section>
        <div style="height:18px"></div>
{render_cart_panel()}      </div>
    </div>
  </main>
"""
        + render_footer()
    )


def cleanup_removed_products(active_ids):
    active = set(active_ids)
    for path in PRODUCTS_DIR.glob("*.html"):
        item_id = path.stem
        if item_id not in active:
            path.unlink()
    for path in ASSET_PRODUCTS_DIR.iterdir():
        if path.name in active:
            continue
        if path.is_dir() and re.fullmatch(r"\d{12}", path.name):
            shutil.rmtree(path)


def write_site(products):
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    index_html = render_index(products)
    (ROOT / "index.html").write_text(index_html, encoding="utf-8", newline="\n")
    for product in products:
        (PRODUCTS_DIR / f"{product['id']}.html").write_text(
            render_product_page(product),
            encoding="utf-8",
            newline="\n",
        )
    payload = json.dumps(products, ensure_ascii=False, separators=(",", ":"))
    PRODUCTS_JS.write_text(f"window.BASEL_PRODUCTS = {payload};\n", encoding="utf-8", newline="\n")


def main():
    existing = load_existing_products()
    details = load_browser_details()
    listings = fetch_current_listings()
    if len(listings) < 20:
        raise RuntimeError(f"Only found {len(listings)} eBay listings; refusing to overwrite site.")

    products = [product_from_listing(item, existing, details) for item in listings]
    cleanup_removed_products([product["id"] for product in products])
    write_site(products)

    existing_ids = set(existing)
    active_ids = {product["id"] for product in products}
    added = [product["id"] for product in products if product["id"] not in existing_ids]
    removed = [item_id for item_id in existing if item_id not in active_ids]
    print(json.dumps({
        "products": len(products),
        "photos": sum(len(product["images"]) for product in products),
        "added": added,
        "removed": removed,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
