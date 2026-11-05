"""Run with: python -m unittest discover -s tests -v."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from app import BASE_DIR, create_app


class StoreTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        value = json.loads((BASE_DIR / "data" / "catalog.json").read_text())
        cls.catalog = value["products"] if isinstance(value, dict) else value

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({"TESTING": True, "DATABASE": str(Path(self.temp.name) / "store.sqlite3")})
        self.client = self.app.test_client()
        self.available = next(p for p in self.catalog if all(p["stock"].values()))
        self.unavailable = next(p for p in self.catalog if not any(p["stock"].values()))

    def payload(self, items=None, **overrides):
        result = {
            "idempotency_key": str(uuid4()), "shipping": "standard",
            "customer": {"email": "tester@example.com", "first_name": "Space", "last_name": "Friend",
                         "address": "42 Moon Lane", "city": "Orbit", "postal_code": "10001", "country": "US"},
            "items": ([{"product_id": self.available["id"], "size": "M", "quantity": 1}]
                      if items is None else items),
        }
        result.update(overrides)
        return result

    def stock(self, product_id, size):
        products = self.client.get("/api/products").get_json()["products"]
        return next(p for p in products if p["id"] == product_id)["stock"][size]

    def test_catalog_has_47_unique_unisex_products_and_local_assets(self):
        self.assertEqual(len(self.catalog), 47)
        self.assertEqual(len({p["id"] for p in self.catalog}), 47)
        self.assertEqual({p["category"] for p in self.catalog}, {"shirts", "hoodies", "jackets"})
        full, partial, sold = 0, 0, 0
        for product in self.catalog:
            self.assertEqual(set(product["stock"]), {"S", "M", "L", "XL"})
            self.assertTrue(all(type(n) is int and n >= 0 for n in product["stock"].values()))
            self.assertIs(type(product["price"]), int)
            self.assertGreater(product["price"], 0)
            self.assertTrue((BASE_DIR / product["image"].lstrip("/")).is_file())
            if not any(product["stock"].values()): sold += 1
            elif not all(product["stock"].values()): partial += 1
            else: full += 1
        self.assertGreaterEqual(sold, 1)
        self.assertGreaterEqual(partial, 1)
        self.assertGreaterEqual(full, 1)

    def test_api_products_and_config(self):
        response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["products"]), 47)
        self.assertEqual(response.get_json()["sizes"], ["S", "M", "L", "XL"])
        config = self.client.get("/api/config").get_json()
        self.assertEqual(config["backend"], "python")
        self.assertEqual(config["mode"], "demo")
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_checkout_recalculates_price_and_decrements_only_selected_size(self):
        initial = self.stock(self.available["id"], "M")
        other = self.stock(self.available["id"], "L")
        payload = self.payload()
        payload["items"][0]["price"] = 1
        payload["total"] = 1
        response = self.client.post("/api/checkout", json=payload)
        self.assertEqual(response.status_code, 201)
        order = response.get_json()
        self.assertEqual(order["subtotal"], self.available["price"])
        expected_shipping = 0 if order["subtotal"] >= 12000 else 800
        self.assertEqual(order["total"], self.available["price"] + expected_shipping)
        self.assertEqual(order["mode"], "demo")
        self.assertEqual(self.stock(self.available["id"], "M"), initial - 1)
        self.assertEqual(self.stock(self.available["id"], "L"), other)

    def test_standard_free_shipping_and_express(self):
        expensive = max((p for p in self.catalog if p["stock"]["M"] >= 2), key=lambda p: p["price"])
        payload = self.payload(items=[{"product_id": expensive["id"], "size": "M", "quantity": 2}])
        order = self.client.post("/api/checkout", json=payload).get_json()
        self.assertGreaterEqual(order["subtotal"], 12000)
        self.assertEqual(order["shipping"], 0)
        payload = self.payload(shipping="express")
        order = self.client.post("/api/checkout", json=payload).get_json()
        self.assertEqual(order["shipping"], 1800)

    def test_out_of_stock_does_not_partially_decrement_cart(self):
        before = self.stock(self.available["id"], "M")
        payload = self.payload(items=[
            {"product_id": self.available["id"], "size": "M", "quantity": 1},
            {"product_id": self.unavailable["id"], "size": "S", "quantity": 1},
        ])
        response = self.client.post("/api/checkout", json=payload)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "insufficient_stock")
        self.assertEqual(self.stock(self.available["id"], "M"), before)

    def test_partial_size_sellout_is_enforced(self):
        partial = next(p for p in self.catalog if any(p["stock"].values()) and not all(p["stock"].values()))
        sold_size = next(size for size, stock in partial["stock"].items() if stock == 0)
        response = self.client.post("/api/checkout", json=self.payload(items=[
            {"product_id": partial["id"], "size": sold_size, "quantity": 1}]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["details"][0]["available"], 0)

    def test_retry_returns_same_order_without_second_deduction(self):
        before = self.stock(self.available["id"], "M")
        payload = self.payload()
        first = self.client.post("/api/checkout", json=payload)
        second = self.client.post("/api/checkout", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.get_json(), second.get_json())
        self.assertEqual(self.stock(self.available["id"], "M"), before - 1)
        payload["shipping"] = "express"
        self.assertEqual(self.client.post("/api/checkout", json=payload).status_code, 409)

    def test_duplicate_lines_are_aggregated_and_cannot_bypass_quantity_limit(self):
        before = self.stock(self.available["id"], "M")
        line = {"product_id": self.available["id"], "size": "M", "quantity": 1}
        response = self.client.post("/api/checkout", json=self.payload(items=[line, line]))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.get_json()["items"]), 1)
        self.assertEqual(response.get_json()["items"][0]["quantity"], 2)
        self.assertEqual(self.stock(self.available["id"], "M"), before - 2)
        line["quantity"] = 6
        response = self.client.post("/api/checkout", json=self.payload(items=[line, line]))
        self.assertEqual(response.status_code, 400)

    def test_malformed_and_invalid_inputs(self):
        for value in (None, [], "invalid", 42):
            with self.subTest(value=value):
                response = self.client.post("/api/checkout", json=value)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post("/api/checkout", data="{oops", content_type="application/json").status_code, 400)
        for quantity in (0, -1, 11, 1.5, True, "1", None):
            with self.subTest(quantity=quantity):
                payload = self.payload()
                payload["items"][0]["quantity"] = quantity
                self.assertEqual(self.client.post("/api/checkout", json=payload).status_code, 400)
        for key, value in (("size", "XXL"), ("size", []), ("product_id", "unknown"), ("product_id", {})):
            payload = self.payload()
            payload["items"][0][key] = value
            self.assertEqual(self.client.post("/api/checkout", json=payload).status_code, 400)
        for field in ("email", "first_name", "last_name", "address", "city", "postal_code", "country"):
            payload = self.payload()
            payload["customer"][field] = " "
            self.assertEqual(self.client.post("/api/checkout", json=payload).status_code, 400)
        payload = self.payload()
        payload["customer"]["email"] = "invalid@email"
        self.assertEqual(self.client.post("/api/checkout", json=payload).status_code, 400)
        self.assertEqual(self.client.post("/api/checkout", json=self.payload(idempotency_key="wrong")).status_code, 400)
        self.assertEqual(self.client.post("/api/checkout", json=self.payload(shipping="teleport")).status_code, 400)
        self.assertEqual(self.client.post("/api/checkout", json=self.payload(items=[])).status_code, 400)

    def test_concurrent_last_item_cannot_be_oversold(self):
        # Set one variant to a single remaining piece, then race two checkouts.
        self.client.get("/api/products")
        import sqlite3
        with sqlite3.connect(self.app.config["DATABASE"]) as db:
            db.execute("UPDATE inventory SET quantity=1 WHERE product_id=? AND size='M'", (self.available["id"],))
        def place_order(_):
            with self.app.test_client() as client:
                response = client.post("/api/checkout", json=self.payload())
                return response.status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(place_order, range(2)))
        self.assertEqual(sorted(results), [201, 409])
        self.assertEqual(self.stock(self.available["id"], "M"), 0)


if __name__ == "__main__":
    unittest.main()
