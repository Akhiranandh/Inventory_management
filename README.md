# StockPilot

StockPilot is a local warehouse inventory web application built with Python, Flask, SQLite, HTML, CSS, and a small amount of JavaScript. SQLite is the source of truth; no inventory is stored in browser memory.

## Features

- Dashboard counts unique products, total units, low-stock items, expired items, and products expiring within 30 days.
- Search, filter, and sort products by item ID, name, location, stock status, and expiry status.
- Create, view, edit, and delete product records. Product quantity changes are made through stock-in and stock-out operations.
- Transactional stock movements with timestamps, notes, oversell protection, and retained movement history after product deletion.
- Current inventory, low-stock, expired, and expiring-soon reports, plus CSV export.
- Automatic SQLite initialization and safe, repeatable import of valid records from `inventory.json` when that file exists.
- Private, password-hashed accounts; login and logout; no public registration.
- CSRF protection for state-changing forms, secure HTTPS session cookies, and server-side validation.

## Project layout

```text
inventory-management/
|-- app.py
|-- database.py
|-- requirements.txt
|-- README.md
|-- inventory.db          # created automatically on first start
|-- inventory.json        # optional legacy source; never modified by migration
|-- templates/
|   |-- base.html
|   |-- login.html
|   |-- index.html
|   |-- inventory.html
|   |-- product_form.html
|   |-- product_detail.html
|   |-- movements.html
|   |-- reports.html
|   |-- 404.html
|   `-- 500.html
`-- static/
    |-- style.css
    `-- script.js
```

The original `Inventory management.py` console program is retained and is not run by the web application.

## Run on Windows

Open this folder in VS Code. In PowerShell, create and activate a virtual environment, then install the dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:FLASK_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(48))"
flask --app app create-user owner
flask --app app create-user father
python app.py
```

If PowerShell blocks activation, use the current session only:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

The account commands prompt twice for a password without echoing it; use different passphrases of at least 12 characters. There is no public registration page. Keep the PowerShell window open so the generated key remains available to the running server.

Open <http://127.0.0.1:5000> in your browser. The database and tables are initialized automatically. To change the low-stock threshold from its default of 10 units, set `STOCK_LOW_THRESHOLD` before starting the app.

## JSON migration

At startup, StockPilot checks for `inventory.json` in this folder. It expects the legacy list of objects with `item_id`, `name`, `location`, `quantity`, and `expiry` (`DD-MM-YYYY`). Records are validated before import; malformed, invalid, and duplicate IDs are skipped and reported in the application log. Existing SQLite records are never overwritten, and the JSON file is never deleted or changed. The migration is safe to rerun because item IDs are unique. Imported opening quantities are recorded in stock movement history.

If the JSON file cannot be read or its root value is not a list, the issue is logged and the app continues without clearing SQLite data. Back up the JSON file before making independent changes to it.

## Local secret key and debug mode

For a stable local session key, use the generated environment variable from the Windows setup commands above. Keep it for the lifetime of the local PowerShell session; use a different random key for production. Debug mode is off by default. Only enable it for local development with `$env:FLASK_DEBUG = "1"`; never enable it on a public server.

```powershell
$env:FLASK_DEBUG = "1"
python app.py
```

Without a configured key, local development uses a temporary random key and browser sessions end when the server restarts.

## PythonAnywhere deployment

These steps assume a PythonAnywhere account with a web app configured for a supported Python 3 version. Replace every `<username>` placeholder with your PythonAnywhere username. Keep the database in your home directory, outside the project and outside `static/`.

### 1. Back up your existing inventory

Stop the local Flask server. Make a second copy of `inventory.db` before uploading anything. If the file contains valuable records, check that the copy exists and can be opened. Keep a separate copy of `inventory.json` too if it exists. Do not include passwords or `.env` files in an upload.

On PythonAnywhere, create a private data directory such as `/home/<username>/stockpilot-data` and restrict access:

```bash
mkdir -p /home/<username>/stockpilot-data
chmod 700 /home/<username>/stockpilot-data
```

Upload your backed-up `inventory.db` into that directory before the first web-app reload. If you have no database yet, the app can create an empty one automatically. Do not upload a new empty database over a populated one. After uploading, restrict the database file:

```bash
chmod 600 /home/<username>/stockpilot-data/inventory.db
```

### 2. Upload the project and install dependencies

Upload `app.py`, `database.py`, `requirements.txt`, the `templates/` directory, and the `static/` directory to a project folder such as `/home/<username>/stockpilot`. Do not upload `.venv/`, `__pycache__/`, `.env`, or secret files. Upload `inventory.json` only if you intentionally want its valid records imported; migration does not delete or edit it.

In a PythonAnywhere Bash console, create a virtual environment using the same Python version selected for the web app (replace `3.11` if you selected another supported version):

```bash
python3.11 -m venv /home/<username>/.virtualenvs/stockpilot
source /home/<username>/.virtualenvs/stockpilot/bin/activate
python -m pip install --upgrade pip
python -m pip install -r /home/<username>/stockpilot/requirements.txt
```

In the PythonAnywhere **Web** tab, set the virtualenv path to `/home/<username>/.virtualenvs/stockpilot`.

### 3. Configure production settings and WSGI

Generate a strong key in the Bash console; do not use this example as a real key:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Open the WSGI configuration file linked from the PythonAnywhere **Web** tab. Replace its default Flask import block with the following, updating the project path, database path, username, and secret placeholder. Keep just one WSGI variable named `application`. The WSGI file is outside the project repository; keep its secret private and do not paste the real key into `app.py`, README, or a committed file.

```python
import os
import sys

project_home = "/home/<username>/stockpilot"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

os.environ["STOCKPILOT_ENV"] = "production"
os.environ["FLASK_SECRET_KEY"] = "paste-the-generated-random-key-here"
os.environ["STOCKPILOT_DATABASE_PATH"] = "/home/<username>/stockpilot-data/inventory.db"
os.environ["SESSION_COOKIE_SECURE"] = "1"

from app import app as application
```

Set these environment values before importing `app`. Production startup refuses to run without a secret key, an absolute database path, and HTTPS-secure cookies. It also forces Flask debug mode off. PythonAnywhere serves HTTPS; enable or force HTTPS for the site in its Web settings. The Flask static route exposes only files in `static/`; it does not provide a route to the project root or SQLite file.

### 4. Create accounts without putting passwords in code

In the Bash console, activate the same virtual environment and set the same production values used by WSGI. The `read` command prompts without echo, so the key is not part of the shell command/history. Enter the exact key already configured in the WSGI file:

```bash
export STOCKPILOT_ENV=production
read -rsp 'Enter the WSGI FLASK_SECRET_KEY: ' FLASK_SECRET_KEY; echo
export FLASK_SECRET_KEY
export STOCKPILOT_DATABASE_PATH='/home/<username>/stockpilot-data/inventory.db'
export SESSION_COOKIE_SECURE=1
source /home/<username>/.virtualenvs/stockpilot/bin/activate
cd /home/<username>/stockpilot
flask --app app create-user owner
flask --app app create-user father
```

Each command prompts twice for a password without displaying it. Use a unique passphrase of at least 12 characters for each account. Passwords are stored as one-way hashes. There is no public account-registration page. Run `create-user` again to add another authorized person; usernames must be unique.

### 5. Reload and verify the site

Click **Reload** in the PythonAnywhere Web tab and open the HTTPS URL assigned to your web app. Confirm that an unauthenticated visit redirects to `/login`, sign in with each account, add a test product, record a stock movement, download a CSV, sign out, and confirm the dashboard redirects to login again. Remove test data afterward. Check the PythonAnywhere error log if startup fails; do not turn on debug mode on the public site.

### Database and schema migration notes

The existing `products` and `stock_movements` table definitions are unchanged. Startup only uses `CREATE TABLE IF NOT EXISTS` and creates indexes; it never drops or resets these tables. The new `accounts` table is additive and starts empty. Existing product rows and stock movement history remain in place. The configured production database path is absolute and is not derived from the process working directory.

If moving an existing database, stop the local app, back up the file, upload the copy to the exact configured PythonAnywhere database path, and only then reload the web app. If PythonAnywhere has already created an empty database at that path, stop/reload the web app and carefully replace it with your verified backup; retain the empty file separately until you confirm the uploaded database opens with the expected records. Never overwrite a populated remote database without backing it up first.

For a PythonAnywhere backup, stop/reload the app before copying the database, or use SQLite's backup API. A stopped-app copy can be made in Bash like this:

```bash
mkdir -p /home/<username>/stockpilot-backups
chmod 700 /home/<username>/stockpilot-backups
cp -p /home/<username>/stockpilot-data/inventory.db "/home/<username>/stockpilot-backups/inventory-$(date +%F-%H%M%S).db"
```

Keep dated backups in a private home-directory folder and test a copy before relying on it. The database contains inventory and movement history; treat it as private business data.

### Add or change a user password

There is no self-service password reset page. To rotate an account password, set the production environment variables as above, activate the project virtual environment, then run `flask --app app set-password owner`. The command prompts for the replacement twice without echo and stores a new hash. To remove an account, first back up the database and use a trusted SQLite maintenance session; do not expose an unauthenticated account-management route.

## Backups

Stop the app, then copy `inventory.db` to a separate backup location. For a consistent SQLite backup while the app is running, use Python's built-in SQLite backup API rather than copying a live database file. Keep the optional `inventory.json` backup separately if you need to preserve the original import source.

## Troubleshooting

- **`No module named flask` or `flask_wtf`:** activate `.venv` and run `python -m pip install -r requirements.txt`.
- **Port 5000 is already in use:** stop the other local service before starting StockPilot; alternatively, change the port in the `app.run` call in `app.py`.
- **PowerShell will not activate the environment:** use the process-scoped execution policy command above, or run `.venv\Scripts\python.exe -m pip install -r requirements.txt` and `.venv\Scripts\python.exe app.py` directly.
- **A legacy row was skipped:** check the logged record number and ensure all five required fields are present, quantity is a positive integer, and expiry is a real `DD-MM-YYYY` date.
- **A form reports an expired session:** reload the page to get a current CSRF token and submit again.
- **Inventory appears empty:** verify that VS Code's terminal is running in this folder and inspect the startup log for JSON migration issues. The SQLite database is created next to `app.py`.

## Data and compatibility

Products retain the legacy fields: item ID, name, location, quantity, and expiry. Stock is constrained to a nonnegative integer in SQLite; normal product creation and imported records require a positive quantity. Product details can be edited without changing stock. Stock movements preserve the item ID and audit history even after a product is deleted.