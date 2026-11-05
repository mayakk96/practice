/* Static review adapter. The complete project uses the Python API in app.py. */
(() => {
  'use strict';

  const CATALOG = __ODD_ORBIT_CATALOG__;
  const SIZES = ['S', 'M', 'L', 'XL'];
  const STATE_KEY = 'odd-orbit-static-preview-v1';
  const LOCK_NAME = 'odd-orbit-static-preview-checkout-v1';
  const PRODUCTS = new Map(CATALOG.map(product => [product.id, product]));
  const SETTINGS = Object.freeze({
    mode: 'demo', backend: 'browser-preview', currency: 'USD',
    shipping: 800, express_shipping: 1800, free_shipping_threshold: 12000,
    tax: 0, max_quantity: 10, inventory_scope: 'browser',
    source_download: '/odd-orbit-project.zip',
  });
  const realFetch = window.fetch.bind(window);
  let memoryState = null;
  let storageUnavailable = false;
  let pendingCheckout = Promise.resolve();

  // Directory-based static hosts may redirect a deep link to a trailing slash.
  if (/^\/(shop|checkout|product\/[^/]+)\/$/.test(location.pathname)) {
    history.replaceState(history.state, '', location.pathname.slice(0, -1) + location.search + location.hash);
  }

  function freshState() {
    return {
      version: 1,
      inventory: Object.fromEntries(CATALOG.map(product => [product.id, {...product.stock}])),
      orders: {},
    };
  }

  function validState(state) {
    return state && state.version === 1 && state.inventory && state.orders
      && typeof state.orders === 'object' && !Array.isArray(state.orders)
      && CATALOG.every(product => state.inventory[product.id]
        && SIZES.every(size => Number.isInteger(state.inventory[product.id][size])
          && state.inventory[product.id][size] >= 0
          && state.inventory[product.id][size] <= product.stock[size]));
  }

  function readState() {
    if (!storageUnavailable) {
      try {
        const stored = JSON.parse(localStorage.getItem(STATE_KEY));
        if (validState(stored)) return stored;
      } catch (_) { storageUnavailable = true; }
    }
    if (!validState(memoryState)) memoryState = freshState();
    return structuredClone(memoryState);
  }

  function writeState(state) {
    memoryState = structuredClone(state);
    try { localStorage.setItem(STATE_KEY, JSON.stringify(state)); }
    catch (_) { storageUnavailable = true; }
  }

  function json(body, status = 200) {
    return new Response(JSON.stringify(body), {
      status, headers: {'Content-Type': 'application/json', 'Cache-Control': 'no-store'},
    });
  }

  function invalid(message, code = 'invalid_request', status = 400, details) {
    const error = new Error(message);
    error.code = code;
    error.status = status;
    error.details = details;
    throw error;
  }

  function validate(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      invalid('Send a JSON object with items, customer, shipping, and an idempotency key.');
    }
    if (typeof payload.idempotency_key !== 'string'
      || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(payload.idempotency_key)) {
      invalid('A valid UUID idempotency_key is required.', 'invalid_idempotency_key');
    }
    const shipping = payload.shipping ?? 'standard';
    if (shipping !== 'standard' && shipping !== 'express') {
      invalid('Choose standard or express shipping.', 'invalid_shipping');
    }
    if (!payload.customer || typeof payload.customer !== 'object' || Array.isArray(payload.customer)) {
      invalid('Enter your contact and delivery information.', 'invalid_customer');
    }
    const customer = {};
    const limits = {email: 254, first_name: 80, last_name: 80, address: 200, city: 100, postal_code: 24, country: 80};
    for (const [field, limit] of Object.entries(limits)) {
      const value = payload.customer[field];
      if (typeof value !== 'string' || !value.trim() || value.length > limit || /[\u0000-\u001f]/.test(value)) {
        invalid(`Enter a valid ${field.replaceAll('_', ' ')}.`, 'invalid_customer', 400, {field});
      }
      customer[field] = value.trim();
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(customer.email)) {
      invalid('Enter a valid email address.', 'invalid_customer', 400, {field: 'email'});
    }
    if (!Array.isArray(payload.items) || payload.items.length < 1 || payload.items.length > 100) {
      invalid('Your bag must contain between 1 and 100 product sizes.', 'invalid_items');
    }
    const aggregated = new Map();
    for (const item of payload.items) {
      if (!item || typeof item !== 'object' || Array.isArray(item)) invalid('Each bag item must be an object.', 'invalid_items');
      if (typeof item.product_id !== 'string' || !PRODUCTS.has(item.product_id)) {
        invalid('An item in your bag is no longer available.', 'unknown_product');
      }
      if (!SIZES.includes(item.size)) invalid('Choose S, M, L, or XL for every item.', 'invalid_size');
      if (!Number.isInteger(item.quantity) || item.quantity < 1 || item.quantity > SETTINGS.max_quantity) {
        invalid('Choose a quantity between 1 and 10.', 'invalid_quantity');
      }
      const key = `${item.product_id}:${item.size}`;
      const quantity = (aggregated.get(key)?.quantity ?? 0) + item.quantity;
      if (quantity > SETTINGS.max_quantity) invalid('Choose at most 10 of each product size.', 'invalid_quantity');
      aggregated.set(key, {product_id: item.product_id, size: item.size, quantity});
    }
    const items = [...aggregated.values()].sort((a, b) => {
      const left = `${a.product_id}:${a.size}`, right = `${b.product_id}:${b.size}`;
      return left < right ? -1 : left > right ? 1 : 0;
    });
    return {key: payload.idempotency_key.toLowerCase(), items, customer, shipping};
  }

  async function fingerprint(order) {
    const encoded = new TextEncoder().encode(JSON.stringify({
      items: order.items, customer: order.customer, shipping: order.shipping,
    }));
    const digest = await crypto.subtle.digest('SHA-256', encoded);
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }

  async function checkout(payload) {
    try {
      const order = validate(payload);
      const requestHash = await fingerprint(order);
      const state = readState();
      const previous = state.orders[order.key];
      if (previous) {
        if (previous.fingerprint !== requestHash) {
          invalid('That checkout key was already used for a different order.', 'idempotency_conflict', 409);
        }
        return json(previous.response);
      }
      const unavailable = order.items.filter(item => item.quantity > state.inventory[item.product_id][item.size])
        .map(item => ({...item, available: state.inventory[item.product_id][item.size], name: PRODUCTS.get(item.product_id).name}));
      if (unavailable.length) {
        invalid('Some sizes in your bag have sold out or have fewer pieces left. Please update your bag.',
          'insufficient_stock', 409, unavailable);
      }
      const items = order.items.map(item => {
        const product = PRODUCTS.get(item.product_id);
        return {...item, name: product.name, color: product.color, price: product.price, line_total: product.price * item.quantity};
      });
      const subtotal = items.reduce((sum, item) => sum + item.line_total, 0);
      const shipping = order.shipping === 'express' ? SETTINGS.express_shipping
        : subtotal >= SETTINGS.free_shipping_threshold ? 0 : SETTINGS.shipping;
      const response = {
        order_id: `OO-PREVIEW-${crypto.randomUUID().replaceAll('-', '').slice(0, 12).toUpperCase()}`,
        items, subtotal, shipping, tax: 0, total: subtotal + shipping,
        currency: 'USD', mode: 'demo', backend: 'browser-preview',
        message: 'Browser-local demo order confirmed. No payment was collected and no items will be shipped.',
      };
      for (const item of order.items) state.inventory[item.product_id][item.size] -= item.quantity;
      // Only the request hash and order receipt persist; contact fields do not.
      state.orders[order.key] = {fingerprint: requestHash, response};
      writeState(state);
      return json(response, 201);
    } catch (error) {
      return json({error: error.code ?? 'preview_error', message: error.status ? error.message
        : 'The browser preview could not complete this demo order. Please try again.',
      ...(error.details === undefined ? {} : {details: error.details})}, error.status ?? 500);
    }
  }

  function serializedCheckout(payload) {
    if (navigator.locks?.request) return navigator.locks.request(LOCK_NAME, () => checkout(payload));
    const result = pendingCheckout.then(() => checkout(payload));
    pendingCheckout = result.then(() => undefined, () => undefined);
    return result;
  }

  window.fetch = async function previewFetch(input, init) {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url, location.href);
    if (url.origin !== location.origin || !['/api/products', '/api/config', '/api/checkout'].includes(url.pathname)) {
      return realFetch(input, init);
    }
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (url.pathname === '/api/config' && method === 'GET') return json(SETTINGS);
    if (url.pathname === '/api/products' && method === 'GET') {
      const state = readState();
      return json({products: CATALOG.map(product => ({...product, stock: {...state.inventory[product.id]}})),
        currency: 'USD', sizes: SIZES});
    }
    if (url.pathname === '/api/checkout' && method === 'POST') {
      let payload;
      try {
        const body = init?.body !== undefined ? init.body : input instanceof Request ? await input.clone().text() : '';
        if (typeof body !== 'string' || body.length > 128 * 1024) return json({message: 'Send a valid JSON checkout request.'}, 400);
        payload = JSON.parse(body);
      } catch (_) { return json({message: 'Send a valid JSON checkout request.'}, 400); }
      return serializedCheckout(payload);
    }
    return json({error: 'method_not_allowed', message: 'That action is not available.'}, 405);
  };
})();
