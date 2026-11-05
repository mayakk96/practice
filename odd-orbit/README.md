# Odd Orbit

A playful, futuristic unisex clothing storefront built with **Python and Flask**. Pastel colors, original product artwork, and a responsive shopping experience carry the brand from the landing page through checkout.

This is a complete **demo shop**. Checkout creates a demo order and updates inventory; it does not collect card details, charge money, send email, or arrange fulfillment.

## Included

- A landing page, searchable product catalog, product detail views, shopping bag, and checkout.
- Exactly **47 products**: 19 shirts, 16 hoodies, and 12 jackets, each with its own original SVG product illustration.
- Unisex sizes **S, M, L, XL**, with complete sellouts and size-specific stock shortages.
- USD prices, stock-aware size choices, and server-validated demo orders.
- SQLite inventory and idempotent checkout to prevent duplicate order submissions.
- Backend tests, a Docker image definition, and a GitHub Actions test workflow.

## Run locally

Use Python 3.12 or later. From this project's directory:

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

On Windows PowerShell, activate the environment with `.venv\Scripts\Activate.ps1` instead.

Open **http://127.0.0.1:5000**. Keep the terminal running while using the shop. Inventory is initialized from `data/catalog.json` on first use and then stored in `instance/store.sqlite3`.

`HOST` and `PORT` configure the development server. `ODD_ORBIT_DATABASE` can point to a different SQLite file on persistent storage. Export these variables in your shell or set them through your host; `.env.example` documents them and is not loaded automatically. No secrets or external API keys are required.

## Try the shopping flow

1. Browse the collection or narrow it by category.
2. Open a product and choose an available size. Sold-out sizes cannot be purchased.
3. Add one or more products to the bag and continue to checkout.
4. Enter sample contact and shipping details and submit the demo order.

Use fictional information when reviewing the demo. Contact and address fields are validated but are not stored in the demo order database. Standard shipping costs **$8**, or is free for merchandise subtotals of **$120 or more**. Express shipping costs **$18**. No sales tax is calculated in this demo. All displayed amounts are USD.

To restore the original demo stock, stop the server, delete `instance/store.sqlite3` (or your configured database file), and restart. This also removes all demo orders. Editing seed stock alone does not replenish quantities already saved in the database.

## Tests

```sh
python -m unittest discover -s tests -v
```

The suite checks catalog integrity, stock validation, checkout totals, malformed requests, and duplicate submission behavior. Tests use isolated temporary databases.

## Deployment

Run Flask behind a production WSGI server:

```sh
gunicorn --bind 0.0.0.0:8000 --workers 2 app:app
```

The included container runs Gunicorn on port 8000:

```sh
docker build -t odd-orbit .
docker run --rm -p 8000:8000 -v odd-orbit-data:/app/instance odd-orbit
```

Keep the SQLite database on persistent storage. A single application instance with a shared local database suits this demo; do not deploy independent replicas with separate database copies. A real shop will also need payment processing, tax handling, fulfillment, customer communications, and appropriate operational controls.

GitHub Pages cannot execute Python. Use a hosting service that supports a Python web process or containers for the complete application.

## Static review preview

The complete project uses the Python backend above. For reviewing the design on a static host, an optional export bundles the same interface with a browser-local demo API:

```sh
python tools/export_preview.py
python -m http.server 8000 --directory dist
```

Open **http://127.0.0.1:8000**. This exported preview runs entirely in the browser: its inventory and demo receipts are saved in namespaced local storage and are separate from the Python application's database. Checkout still checks available sizes, quantities, prices, shipping, and duplicate submissions, but it does not contact a Python server. Contact and address fields are not saved. Clearing the preview's site data resets its inventory and receipts.

The export includes `odd-orbit-project.zip`, a complete Python project download that excludes local environments, databases, temporary work, Git metadata, and the current preview's hosting identity. Run the exporter again after source changes to refresh both the static preview and its source archive. Static review is suitable for this fictional demo; use the Flask application for server-controlled inventory.

## API

| Route | Purpose |
| --- | --- |
| `GET /api/products` | Catalog with current size-level stock, currency, and available sizes |
| `GET /api/config` | Demo mode and shipping configuration |
| `POST /api/checkout` | Validate stock, calculate totals, and create a demo order |
| `GET /health` | Check the application and database connection |

Checkout accepts a JSON body shaped like this:

```json
{
  "items": [
    {"product_id": "orbit-club-tee", "size": "M", "quantity": 1}
  ],
  "customer": {
    "email": "reviewer@example.com",
    "first_name": "Demo",
    "last_name": "Customer",
    "address": "123 Sample Street",
    "city": "New York",
    "postal_code": "10001",
    "country": "US"
  },
  "shipping": "standard",
  "idempotency_key": "6a3eb810-f542-4a77-916c-66f96a021e85"
}
```

Use an actual product ID returned by `/api/products`, an available size, and a new UUID for each distinct order. Repeat the same key and identical request to retrieve the same order. Reusing a key for a changed order is rejected. Prices, shipping, and stock are checked on the server; client-provided totals are not trusted. Monetary values in the API and catalog are integer cents.

## Project layout

```text
app.py                     Python application and checkout API
data/catalog.json          The 47-product seed catalog
templates/index.html       Storefront shell
static/                    Styles, browser interactions, and original artwork
tests/test_store.py        Backend test suite
instance/                  Local database; generated and excluded from Git
requirements.txt           Python dependencies
Dockerfile                 Production container
.github/workflows/         Automated checks
tools/export_preview.py    Optional static review and source ZIP export
tools/preview-runtime.js   Browser-local API adapter for that export only
```

The backend runs in Python. Browser interactions use standard HTML, CSS, and JavaScript. Product illustrations are bundled locally, so the shop does not depend on third-party image URLs.

## GitHub handoff

The project is prepared for review before it is pushed. For the existing `mayakk96/practice` repository, place this complete directory under `odd-orbit/` on a new branch so the repository's existing application remains intact. The test workflow supports the standalone project as well as that nested layout; GitHub only discovers workflows placed in the repository's top-level `.github/workflows/` directory.

To regenerate the original catalog illustrations, run `python tools/generate_assets.py`. This rewrites seed catalog and artwork; it does not reset persisted SQLite inventory.
