# Synthetic files

Every identifier and amount is fictional. `external-evidence.json` matches the default end-to-end demo's external references and deliberately understates one payment by 5,000 USD minor units ($50.00). Its duplicate import is detected by the import fingerprint.

`clearing-template.csv` documents the exact CSV header and valid field types. Replace the placeholder transaction UUIDs and network references with captured transaction values before importing; the template cannot clear nonexistent transactions. `clearing-invalid.csv` deliberately demonstrates rejected rows. The live demo script creates valid account/transaction identifiers dynamically and submits matching clearing records.

All supported currencies currently have two minor-unit decimal places: 50000 means USD500.00, EUR500.00 or GBP500.00 according to the currency field. There is no conversion between currencies.
