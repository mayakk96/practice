"""Odd Orbit: a Python storefront with inventory-safe demonstration checkout.

Run ``python app.py`` for development, or ``gunicorn 'app:create_app()'``.
Amounts use integer US cents. This demo never requests or processes payment data.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from uuid import UUID, uuid4

from flask import Flask, g, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

BASE_DIR = Path(__file__).resolve().parent
SIZES = ("S", "M", "L", "XL")
STANDARD_SHIPPING = 800
EXPRESS_SHIPPING = 1800
FREE_SHIPPING_THRESHOLD = 12000
MAX_QUANTITY = 10


class StoreError(Exception):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 400, details=None):
        super().__init__(message)
        self.message, self.code, self.status, self.details = message, code, status, details


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get("ODD_ORBIT_DATABASE", str(BASE_DIR / "instance" / "store.sqlite3")),
        CATALOG_PATH=str(BASE_DIR / "data" / "catalog.json"),
        MAX_CONTENT_LENGTH=128 * 1024,
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)

    def catalog():
        if "catalog" not in app.extensions:
            with open(app.config["CATALOG_PATH"], encoding="utf-8") as catalog_file:
                value = json.load(catalog_file)
            # Accept a simple list or an explicitly wrapped source catalog.
            products = value.get("products", []) if isinstance(value, dict) else value
            app.extensions["catalog"] = {product["id"]: product for product in products}
        return app.extensions["catalog"]

    def database():
        if "db" not in g:
            database_path = Path(app.config["DATABASE"])
            database_path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(database_path, timeout=15, isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=15000")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS inventory (
                    product_id TEXT NOT NULL,
                    size TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity >= 0),
                    PRIMARY KEY (product_id, size)
                );
                CREATE TABLE IF NOT EXISTS demo_orders (
                    order_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    fingerprint TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # OR IGNORE seeds new catalog variants without replenishing sold stock.
            db.executemany(
                "INSERT OR IGNORE INTO inventory (product_id,size,quantity) VALUES (?,?,?)",
                [(p["id"], size, p["stock"][size]) for p in catalog().values() for size in SIZES],
            )
            g.db = db
        return g.db

    @app.teardown_appcontext
    def close_database(_exception):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(StoreError)
    def handle_store_error(error):
        response = {"error": error.code, "message": error.message}
        if error.details is not None:
            response["details"] = error.details
        return jsonify(response), error.status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error=error.name.lower().replace(" ", "_"), message=error.description), error.code
        return error

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    @app.get("/shop")
    @app.get("/checkout")
    def storefront():
        return render_template("index.html")

    @app.get("/product/<product_id>")
    def product_page(product_id):
        if product_id not in catalog():
            return render_template("index.html"), 404
        return render_template("index.html")

    @app.get("/health")
    def health():
        database().execute("SELECT 1").fetchone()
        return jsonify(status="ok", backend="python", mode="demo")

    @app.get("/api/config")
    def configuration():
        return jsonify(
            mode="demo", backend="python", currency="USD", shipping=STANDARD_SHIPPING,
            express_shipping=EXPRESS_SHIPPING, free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
            tax=0, max_quantity=MAX_QUANTITY,
        )

    @app.get("/api/products")
    def products():
        stock = defaultdict(dict)
        for row in database().execute("SELECT product_id,size,quantity FROM inventory"):
            stock[row["product_id"]][row["size"]] = row["quantity"]
        return jsonify(
            products=[{**product, "stock": stock[product["id"]]} for product in catalog().values()],
            currency="USD", sizes=list(SIZES),
        )

    def validate_checkout(payload):
        if not isinstance(payload, dict):
            raise StoreError("Send a JSON object with items, customer, shipping, and an idempotency key.")
        key = payload.get("idempotency_key")
        try:
            if not isinstance(key, str) or str(UUID(key)) != key.lower():
                raise ValueError
        except (ValueError, AttributeError):
            raise StoreError("A valid UUID idempotency_key is required.", "invalid_idempotency_key") from None

        delivery = payload.get("shipping", "standard")
        if delivery not in ("standard", "express"):
            raise StoreError("Choose standard or express shipping.", "invalid_shipping")
        customer = payload.get("customer")
        if not isinstance(customer, dict):
            raise StoreError("Enter your contact and delivery information.", "invalid_customer")
        cleaned_customer = {}
        field_limits = {"email": 254, "first_name": 80, "last_name": 80, "address": 200,
                        "city": 100, "postal_code": 24, "country": 80}
        for field, limit in field_limits.items():
            value = customer.get(field)
            if (not isinstance(value, str) or not value.strip() or len(value) > limit
                    or any(ord(character) < 32 for character in value)):
                raise StoreError(f"Enter a valid {field.replace('_', ' ')}.", "invalid_customer", details={"field": field})
            cleaned_customer[field] = value.strip()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", cleaned_customer["email"]):
            raise StoreError("Enter a valid email address.", "invalid_customer", details={"field": "email"})

        raw_items = payload.get("items")
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 100:
            raise StoreError("Your bag must contain between 1 and 100 product sizes.", "invalid_items")
        counts = defaultdict(int)
        for item in raw_items:
            if not isinstance(item, dict):
                raise StoreError("Each bag item must be an object.", "invalid_items")
            product_id, size, quantity = item.get("product_id"), item.get("size"), item.get("quantity")
            if not isinstance(product_id, str) or product_id not in catalog():
                raise StoreError("An item in your bag is no longer available.", "unknown_product")
            if not isinstance(size, str) or size not in SIZES:
                raise StoreError("Choose S, M, L, or XL for every item.", "invalid_size")
            if type(quantity) is not int or not 1 <= quantity <= MAX_QUANTITY:
                raise StoreError(f"Choose a quantity between 1 and {MAX_QUANTITY}.", "invalid_quantity")
            counts[(product_id, size)] += quantity
            if counts[(product_id, size)] > MAX_QUANTITY:
                raise StoreError(f"Choose at most {MAX_QUANTITY} of each product size.", "invalid_quantity")
        normalized = [{"product_id": product_id, "size": size, "quantity": quantity}
                      for (product_id, size), quantity in sorted(counts.items())]
        # Hash customer input to enforce exact retry semantics without storing contact data.
        fingerprint = hashlib.sha256(json.dumps(
            {"items": normalized, "customer": cleaned_customer, "shipping": delivery},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return key.lower(), delivery, normalized, fingerprint

    @app.post("/api/checkout")
    def checkout():
        key, delivery, items, fingerprint = validate_checkout(request.get_json(silent=True))
        db = database()
        try:
            # An immediate transaction serializes availability checks and deductions.
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT fingerprint,response_json FROM demo_orders WHERE idempotency_key=?", (key,),
            ).fetchone()
            if existing:
                if existing["fingerprint"] != fingerprint:
                    raise StoreError("That checkout key was already used for a different order.", "idempotency_conflict", 409)
                db.commit()
                return jsonify(json.loads(existing["response_json"]))

            order_items, unavailable = [], []
            for item in items:
                product = catalog()[item["product_id"]]
                available = db.execute(
                    "SELECT quantity FROM inventory WHERE product_id=? AND size=?",
                    (item["product_id"], item["size"]),
                ).fetchone()["quantity"]
                if item["quantity"] > available:
                    unavailable.append({**item, "available": available, "name": product["name"]})
                order_items.append({**item, "name": product["name"], "color": product["color"],
                                    "price": product["price"], "line_total": product["price"] * item["quantity"]})
            if unavailable:
                raise StoreError("Some sizes in your bag have sold out or have fewer pieces left. Please update your bag.",
                                 "insufficient_stock", 409, unavailable)

            subtotal = sum(item["line_total"] for item in order_items)
            shipping = EXPRESS_SHIPPING if delivery == "express" else (
                0 if subtotal >= FREE_SHIPPING_THRESHOLD else STANDARD_SHIPPING)
            response = {
                "order_id": f"OO-{uuid4().hex[:12].upper()}", "items": order_items,
                "subtotal": subtotal, "shipping": shipping, "tax": 0, "total": subtotal + shipping,
                "currency": "USD", "mode": "demo",
                "message": "Demo order confirmed. No payment was collected and no items will be shipped.",
            }
            for item in items:
                db.execute("UPDATE inventory SET quantity=quantity-? WHERE product_id=? AND size=?",
                           (item["quantity"], item["product_id"], item["size"]))
            db.execute("INSERT INTO demo_orders (order_id,idempotency_key,fingerprint,response_json) VALUES (?,?,?,?)",
                       (response["order_id"], key, fingerprint, json.dumps(response)))
            db.commit()
            return jsonify(response), 201
        except Exception:
            db.rollback()
            raise

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
