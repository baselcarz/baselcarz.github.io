(() => {
  const PRODUCTS = window.BASEL_PRODUCTS || [];
  const CONFIG = {
    currency: 'USD',
    paypalBusiness: 'samhouri@mail.ru',
    shipping: { usa: 30, international: 100 }
  };
  const productsById = new Map(PRODUCTS.map((product) => [product.id, product]));
  const money = new Intl.NumberFormat('en-US', { style: 'currency', currency: CONFIG.currency });
  const CART_KEY = 'basel-carz-cart-v2';
  let cart = loadCart();

  function loadCart() {
    try {
      const saved = JSON.parse(localStorage.getItem(CART_KEY) || '[]');
      if (Array.isArray(saved)) return saved.filter((id) => productsById.has(id));
    } catch (error) {}
    return [];
  }
  function saveCart() { localStorage.setItem(CART_KEY, JSON.stringify(cart)); }
  function formatMoney(value) { return money.format(Number(value || 0)); }
  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));
  }
  function cartTotals() {
    const selected = cart.map((id) => productsById.get(id)).filter(Boolean);
    const originalSubtotal = selected.reduce((sum, item) => sum + item.originalPrice, 0);
    const saleSubtotal = selected.reduce((sum, item) => sum + item.salePrice, 0);
    const discountTotal = originalSubtotal - saleSubtotal;
    const shippingSelect = document.getElementById('shipping-zone');
    const shippingKey = shippingSelect ? shippingSelect.value : 'usa';
    const shipping = selected.length ? CONFIG.shipping[shippingKey] : 0;
    return { count: selected.length, originalSubtotal, saleSubtotal, discountTotal, shipping, total: saleSubtotal + shipping };
  }
  function addToCart(id) {
    if (!productsById.has(id)) return;
    if (!cart.includes(id)) cart.push(id);
    saveCart();
    renderCart();
    const panel = document.getElementById('cart-panel');
    if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function removeFromCart(id) {
    cart = cart.filter((itemId) => itemId !== id);
    saveCart();
    renderCart();
  }
  function renderCart() {
    const cartItems = document.getElementById('cart-items');
    const emptyCart = document.getElementById('empty-cart');
    const navCartCount = document.getElementById('nav-cart-count');
    const paypalMessage = document.getElementById('paypal-message');
    if (!cartItems) return;
    cartItems.innerHTML = '';
    cart.forEach((id) => {
      const product = productsById.get(id);
      if (!product) return;
      const item = document.createElement('div');
      item.className = 'cart-item';
      item.innerHTML = '<img src="' + product.image + '" alt="">' +
        '<div><strong>' + escapeHtml(product.title) + '</strong><span>' + formatMoney(product.salePrice) + '</span></div>' +
        '<button class="remove-item" type="button" aria-label="Remove ' + escapeHtml(product.title) + '" data-remove="' + product.id + '">Remove</button>';
      cartItems.appendChild(item);
    });
    const totals = cartTotals();
    if (emptyCart) emptyCart.style.display = totals.count ? 'none' : 'block';
    if (navCartCount) navCartCount.textContent = String(totals.count);
    const setText = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
    setText('original-subtotal', formatMoney(totals.originalSubtotal));
    setText('discount-total', '-' + formatMoney(totals.discountTotal));
    setText('sale-subtotal', formatMoney(totals.saleSubtotal));
    setText('shipping-total', formatMoney(totals.shipping));
    setText('cart-total', formatMoney(totals.total));
    document.querySelectorAll('[data-add-to-cart]').forEach((button) => {
      const inCart = cart.includes(button.dataset.addToCart);
      button.classList.toggle('added', inCart);
      button.textContent = inCart ? 'In cart' : 'Add to cart';
    });
    if (paypalMessage) {
      if (!totals.count) {
        paypalMessage.textContent = 'Add at least one item to continue to PayPal.';
        paypalMessage.className = 'paypal-message';
      } else {
        paypalMessage.textContent = 'Ready for PayPal checkout.';
        paypalMessage.className = 'paypal-message ready';
      }
    }
  }
  function checkoutWithPaypal() {
    const totals = cartTotals();
    const paypalMessage = document.getElementById('paypal-message');
    if (!totals.count) {
      if (paypalMessage) {
        paypalMessage.textContent = 'Add at least one item to continue to PayPal.';
        paypalMessage.className = 'paypal-message error';
      }
      return;
    }
    const form = document.createElement('form');
    form.method = 'post';
    form.action = 'https://www.paypal.com/cgi-bin/webscr';
    form.target = '_blank';
    form.style.display = 'none';
    const addField = (name, value) => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = name;
      input.value = String(value);
      form.appendChild(input);
    };
    addField('cmd', '_cart');
    addField('upload', '1');
    addField('business', CONFIG.paypalBusiness);
    addField('currency_code', CONFIG.currency);
    addField('charset', 'utf-8');
    addField('no_note', '0');
    addField('lc', 'US');
    addField('return', window.location.origin + '/');
    addField('cancel_return', window.location.origin + window.location.pathname + '#cart-panel');
    cart.forEach((id, index) => {
      const product = productsById.get(id);
      const n = index + 1;
      addField('item_name_' + n, product.title.slice(0, 127));
      addField('item_number_' + n, product.id);
      addField('amount_' + n, product.salePrice.toFixed(2));
      addField('quantity_' + n, '1');
    });
    const shippingIndex = cart.length + 1;
    const shippingZone = document.getElementById('shipping-zone');
    const shippingLabel = shippingZone && shippingZone.value === 'international' ? 'International flat shipping' : 'USA flat shipping';
    addField('item_name_' + shippingIndex, shippingLabel);
    addField('amount_' + shippingIndex, totals.shipping.toFixed(2));
    addField('quantity_' + shippingIndex, '1');
    document.body.appendChild(form);
    form.submit();
    form.remove();
  }
  function initSearch() {
    const searchInput = document.getElementById('inventory-search');
    const resultCount = document.getElementById('result-count');
    const noResults = document.getElementById('no-results');
    const cards = Array.from(document.querySelectorAll('.product-card'));
    if (!searchInput || !resultCount) return;
    const updateSearch = () => {
      const query = searchInput.value.trim().toLowerCase();
      let visible = 0;
      cards.forEach((card) => {
        const haystack = (card.dataset.title || '') + ' ' + (card.dataset.id || '');
        const isVisible = !query || haystack.includes(query);
        card.classList.toggle('is-hidden', !isVisible);
        if (isVisible) visible += 1;
      });
      resultCount.textContent = 'Showing ' + visible + ' product' + (visible === 1 ? '' : 's');
      if (noResults) noResults.classList.toggle('is-visible', visible === 0);
    };
    searchInput.addEventListener('input', updateSearch);
    searchInput.addEventListener('change', updateSearch);
    searchInput.addEventListener('search', updateSearch);
    updateSearch();
  }
  function initGallery() {
    const gallery = document.querySelector('[data-gallery]');
    if (!gallery) return;
    const product = productsById.get(gallery.dataset.productId);
    if (!product || !product.images.length) return;
    const main = document.getElementById('gallery-main-image');
    const count = document.getElementById('gallery-count');
    const thumbs = Array.from(document.querySelectorAll('[data-gallery-thumb]'));
    let index = 0;
    const show = (nextIndex) => {
      index = (nextIndex + product.images.length) % product.images.length;
      main.src = product.images[index];
      main.alt = product.title + ' photo ' + (index + 1);
      if (count) count.textContent = (index + 1) + ' / ' + product.images.length;
      thumbs.forEach((thumb) => thumb.classList.toggle('is-active', Number(thumb.dataset.galleryThumb) === index));
      const active = thumbs.find((thumb) => Number(thumb.dataset.galleryThumb) === index);
      if (active) active.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' });
    };
    document.querySelectorAll('[data-gallery-prev]').forEach((button) => button.addEventListener('click', () => show(index - 1)));
    document.querySelectorAll('[data-gallery-next]').forEach((button) => button.addEventListener('click', () => show(index + 1)));
    thumbs.forEach((thumb) => thumb.addEventListener('click', () => show(Number(thumb.dataset.galleryThumb))));
    document.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft') show(index - 1);
      if (event.key === 'ArrowRight') show(index + 1);
    });
    show(0);
  }
  document.addEventListener('click', (event) => {
    const addButton = event.target.closest('[data-add-to-cart]');
    if (addButton) addToCart(addButton.dataset.addToCart);
    const removeButton = event.target.closest('[data-remove]');
    if (removeButton) removeFromCart(removeButton.dataset.remove);
  });
  const shippingZone = document.getElementById('shipping-zone');
  if (shippingZone) shippingZone.addEventListener('change', renderCart);
  const paypalButton = document.getElementById('paypal-button');
  if (paypalButton) paypalButton.addEventListener('click', checkoutWithPaypal);
  initSearch();
  initGallery();
  renderCart();
})();
