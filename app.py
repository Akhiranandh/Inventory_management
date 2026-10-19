import csv
import io
import logging
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import click
from flask import Flask, Response, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

import database

csrf = CSRFProtect()
DATE_FORMAT = "%d-%m-%Y"


def environment_flag(name, default=False):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


def safe_redirect_target(target):
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    destination = urlsplit(urljoin(request.host_url, target))
    origin = urlsplit(request.host_url)
    return destination.scheme in {"http", "https"} and destination.netloc == origin.netloc


def expiry_status(value, today=None):
    expiry = database.parse_expiry(value)
    if expiry is None:
        return "Invalid date"
    today = today or date.today()
    if expiry < today:
        return "Expired"
    if (expiry - today).days <= 30:
        return "Expiring soon"
    return "In date"


def stock_status(quantity, threshold):
    return "Low stock" if quantity <= threshold else "Normal stock"


def parse_product_form(form, include_item_id=True, include_quantity=True):
    errors = []
    item_id = form.get("item_id", "").strip()
    name = form.get("name", "").strip()
    location = form.get("location", "").strip()
    expiry = form.get("expiry", "").strip()
    quantity_text = form.get("quantity", "").strip()

    if include_item_id and not item_id:
        errors.append("Item ID is required.")
    if not name:
        errors.append("Product name is required.")
    if not location:
        errors.append("Warehouse location is required.")
    if database.parse_expiry(expiry) is None:
        errors.append("Enter a real expiry date in DD-MM-YYYY format.")

    quantity = None
    if include_quantity:
        if not re.fullmatch(r"[0-9]+", quantity_text) or len(quantity_text) > 19:
            errors.append("Quantity must be a positive whole number.")
        else:
            quantity = int(quantity_text)
            if not 1 <= quantity <= 9223372036854775807:
                errors.append("Quantity must be a positive whole number within SQLite's supported range.")
    return {"item_id": item_id, "name": name, "location": location, "expiry": expiry, "quantity": quantity}, errors


def create_app(test_config=None):
    application = Flask(__name__)
    production_mode = os.environ.get("STOCKPILOT_ENV", "").strip().lower() == "production"
    configured_database_path = os.environ.get("STOCKPILOT_DATABASE_PATH")
    secret_key = os.environ.get("FLASK_SECRET_KEY")
    database_path = Path(configured_database_path).expanduser() if configured_database_path else database.DATABASE_PATH
    application.config.from_mapping(
        SECRET_KEY=secret_key or (None if production_mode else secrets.token_hex(32)),
        STOCKPILOT_ENV="production" if production_mode else "development",
        DATABASE_PATH=str(database_path),
        LOW_STOCK_THRESHOLD=int(os.environ.get("STOCK_LOW_THRESHOLD", "10")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=environment_flag("SESSION_COOKIE_SECURE", production_mode),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_NAME="__Host-stockpilot_session" if production_mode else "stockpilot_session",
        SESSION_COOKIE_PATH="/",
        SESSION_COOKIE_DOMAIN=None,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        SESSION_REFRESH_EACH_REQUEST=True,
        DEBUG=environment_flag("FLASK_DEBUG", False),
    )
    if test_config:
        application.config.update(test_config)
    production_mode = application.config["STOCKPILOT_ENV"] == "production"
    if production_mode and not application.config.get("SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY must be configured in production.")
    if production_mode and not configured_database_path and not (test_config and test_config.get("DATABASE_PATH")):
        raise RuntimeError("STOCKPILOT_DATABASE_PATH must be configured in production.")
    if production_mode and not Path(application.config["DATABASE_PATH"]).expanduser().is_absolute():
        raise RuntimeError("STOCKPILOT_DATABASE_PATH must be an absolute path in production.")
    if production_mode and not application.config["SESSION_COOKIE_SECURE"]:
        raise RuntimeError("SESSION_COOKIE_SECURE must be enabled in production.")
    if not application.config.get("SECRET_KEY"):
        raise RuntimeError("FLASK_SECRET_KEY is required.")
    if production_mode:
        application.config["DEBUG"] = False
        application.config["PREFERRED_URL_SCHEME"] = "https"
        application.config["SESSION_COOKIE_NAME"] = "__Host-stockpilot_session"
    if not secret_key and not production_mode and not test_config:
        logging.getLogger(__name__).warning(
            "FLASK_SECRET_KEY is unset; using a temporary local-development key."
        )

    csrf.init_app(application)
    migration = database.initialize_database(application.config["DATABASE_PATH"])
    if migration["imported"] or migration["skipped"]:
        application.logger.info(
            "Legacy JSON migration: %s imported, %s skipped.",
            migration["imported"], migration["skipped"],
        )

    @application.context_processor
    def inject_template_helpers():
        return {
            "expiry_status": expiry_status,
            "now": datetime.now,
            "current_username": lambda: getattr(g, "current_username", ""),
            "stock_status": lambda quantity: stock_status(
                quantity, application.config["LOW_STOCK_THRESHOLD"]
            ),
            "low_stock_threshold": application.config["LOW_STOCK_THRESHOLD"],
        }

    def connection():
        return database.connection_scope(current_app.config["DATABASE_PATH"])

    @application.before_request
    def require_authenticated_account():
        if request.endpoint in {"login", "static"} or request.endpoint is None:
            return None
        account_id = session.get("account_id")
        if not isinstance(account_id, int):
            target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=target))
        account = database.get_account_by_id(account_id, current_app.config["DATABASE_PATH"])
        if account is None:
            session.clear()
            return redirect(url_for("login"))
        g.current_username = account["username"]
        return None

    @application.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
        )
        if current_app.config["STOCKPILOT_ENV"] == "production":
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if session.get("account_id"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.route("/login", methods=["GET", "POST"])
    def login():
        if isinstance(session.get("account_id"), int):
            return redirect(url_for("dashboard"))
        next_url = request.values.get("next", "")
        if request.method == "POST":
            username = request.form.get("username", "").strip().lower()
            password = request.form.get("password", "")
            account = database.get_account_by_username(username, current_app.config["DATABASE_PATH"])
            if account and len(password) <= 1024 and check_password_hash(account["password_hash"], password):
                session.clear()
                session["account_id"] = account["id"]
                session.permanent = True
                flash("You are signed in.", "success")
                if safe_redirect_target(next_url):
                    return redirect(next_url)
                return redirect(url_for("dashboard"))
            flash("Username or password was not recognized.", "error")
            return render_template("login.html", next_url=next_url), 401
        return render_template("login.html", next_url=next_url)

    @application.post("/logout")
    def logout():
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @application.cli.command("create-user")
    @click.argument("username")
    def create_user_command(username):
        normalized_username = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,50}", normalized_username):
            raise click.ClickException(
                "Username must be 3-50 characters: letters, numbers, dot, underscore, or hyphen."
            )
        password = click.prompt("Password (at least 12 characters)", hide_input=True)
        confirmation = click.prompt("Confirm password", hide_input=True)
        if not 12 <= len(password) <= 256:
            raise click.ClickException("Password must contain between 12 and 256 characters.")
        if password != confirmation:
            raise click.ClickException("Passwords did not match.")
        if database.get_account_by_username(normalized_username, current_app.config["DATABASE_PATH"]):
            raise click.ClickException("That username already exists.")
        try:
            database.create_account(
                normalized_username,
                generate_password_hash(password),
                current_app.config["DATABASE_PATH"],
            )
        except sqlite3.IntegrityError as error:
            raise click.ClickException("That username already exists.") from error
        click.echo(f"Account created for {normalized_username}.")

    @application.cli.command("set-password")
    @click.argument("username")
    def set_password_command(username):
        normalized_username = username.strip().lower()
        account = database.get_account_by_username(normalized_username, current_app.config["DATABASE_PATH"])
        if account is None:
            raise click.ClickException("No account exists with that username.")
        password = click.prompt("New password (at least 12 characters)", hide_input=True)
        confirmation = click.prompt("Confirm password", hide_input=True)
        if not 12 <= len(password) <= 256:
            raise click.ClickException("Password must contain between 12 and 256 characters.")
        if password != confirmation:
            raise click.ClickException("Passwords did not match.")
        database.update_account_password(
            normalized_username,
            generate_password_hash(password),
            current_app.config["DATABASE_PATH"],
        )
        click.echo(f"Password updated for {normalized_username}.")

    def find_product(product_id):
        with connection() as db_connection:
            product = db_connection.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
        if product is None:
            abort(404)
        return product

    def filtered_products():
        search = request.args.get("q", "").strip()
        clauses = []
        parameters = []
        if search:
            pattern = f"%{search}%"
            clauses.append("(item_id LIKE ? OR name LIKE ? OR location LIKE ?)")
            parameters.extend((pattern, pattern, pattern))
        query = "SELECT * FROM products"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        with connection() as db_connection:
            products = [dict(row) for row in db_connection.execute(query, parameters).fetchall()]

        expiry_filter = request.args.get("expiry", "all")
        stock_filter = request.args.get("stock", "all")
        if expiry_filter in {"expired", "soon", "in-date"}:
            wanted = {"expired": "Expired", "soon": "Expiring soon", "in-date": "In date"}[expiry_filter]
            products = [item for item in products if expiry_status(item["expiry"]) == wanted]
        if stock_filter in {"low", "normal"}:
            wanted = "Low stock" if stock_filter == "low" else "Normal stock"
            products = [
                item for item in products
                if stock_status(item["quantity"], current_app.config["LOW_STOCK_THRESHOLD"]) == wanted
            ]

        sort_key = request.args.get("sort", "name")
        sort_keys = {"name": "name", "quantity": "quantity", "expiry": "expiry", "location": "location"}
        if sort_key not in sort_keys:
            sort_key = "name"
        if sort_key == "expiry":
            products.sort(key=lambda item: database.parse_expiry(item["expiry"]) or date.max)
        else:
            products.sort(key=lambda item: item[sort_keys[sort_key]].casefold() if isinstance(item[sort_keys[sort_key]], str) else item[sort_keys[sort_key]])
        if request.args.get("direction") == "desc":
            products.reverse()
        return products

    @application.get("/")
    def dashboard():
        with connection() as db_connection:
            products = [dict(row) for row in db_connection.execute("SELECT * FROM products").fetchall()]
        today = date.today()
        low_stock = [item for item in products if item["quantity"] <= current_app.config["LOW_STOCK_THRESHOLD"]]
        expired = [item for item in products if expiry_status(item["expiry"], today) == "Expired"]
        expiring = [item for item in products if expiry_status(item["expiry"], today) == "Expiring soon"]
        relevant = sorted(
            low_stock + [item for item in expiring if item not in low_stock],
            key=lambda item: (database.parse_expiry(item["expiry"]) or date.max, item["name"].casefold()),
        )[:8]
        return render_template(
            "index.html",
            total_products=len(products),
            total_units=sum(item["quantity"] for item in products),
            low_stock_count=len(low_stock),
            expired_count=len(expired),
            expiring_count=len(expiring),
            relevant_products=relevant,
        )

    @application.get("/inventory")
    def inventory_list():
        return render_template("inventory.html", products=filtered_products())

    @application.route("/inventory/new", methods=["GET", "POST"])
    def create_inventory_item():
        if request.method == "POST":
            item, errors = parse_product_form(request.form)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_template("product_form.html", product=item, form_title="Add product"), 400
            try:
                database.create_product(
                    item["item_id"], item["name"], item["location"], item["quantity"], item["expiry"],
                    current_app.config["DATABASE_PATH"],
                )
            except sqlite3.IntegrityError:
                flash("That item ID already exists. Choose a unique ID.", "error")
                return render_template("product_form.html", product=item, form_title="Add product"), 400
            flash(f"{item['name']} was added to inventory.", "success")
            return redirect(url_for("inventory_list"))
        return render_template("product_form.html", product={}, form_title="Add product")

    @application.get("/inventory/<int:product_id>")
    def product_detail(product_id):
        product = find_product(product_id)
        with connection() as db_connection:
            movements = db_connection.execute(
                "SELECT * FROM stock_movements WHERE product_id = ? ORDER BY created_at DESC, id DESC LIMIT 10",
                (product_id,),
            ).fetchall()
        return render_template("product_detail.html", product=product, movements=movements)

    @application.route("/inventory/<int:product_id>/edit", methods=["GET", "POST"])
    def edit_inventory_item(product_id):
        existing = find_product(product_id)
        if request.method == "POST":
            item, errors = parse_product_form(request.form, include_item_id=False, include_quantity=False)
            if errors:
                for error in errors:
                    flash(error, "error")
                item.update(item_id=existing["item_id"], quantity=existing["quantity"])
                return render_template("product_form.html", product=item, form_title="Edit product", editing=True), 400
            database.update_product(
                product_id, item["name"], item["location"], item["expiry"], current_app.config["DATABASE_PATH"]
            )
            flash("Product details updated.", "success")
            return redirect(url_for("product_detail", product_id=product_id))
        return render_template("product_form.html", product=dict(existing), form_title="Edit product", editing=True)

    @application.post("/inventory/<int:product_id>/delete")
    def delete_inventory_item(product_id):
        product = find_product(product_id)
        with connection() as db_connection:
            db_connection.execute("DELETE FROM products WHERE id = ?", (product_id,))
        flash(f"{product['name']} was removed. Its movement history is retained.", "success")
        return redirect(url_for("inventory_list"))

    def change_stock(product_id, movement_type):
        find_product(product_id)
        quantity_text = request.form.get("quantity", "").strip()
        notes = request.form.get("notes", "").strip()[:500]
        if not re.fullmatch(r"[0-9]+", quantity_text) or len(quantity_text) > 19 or int(quantity_text) < 1:
            flash("Movement quantity must be a positive whole number.", "error")
            return redirect(url_for("product_detail", product_id=product_id))
        try:
            new_quantity = database.record_stock_movement(
                product_id, movement_type, int(quantity_text), notes, current_app.config["DATABASE_PATH"]
            )
        except ValueError as error:
            flash(str(error), "error")
            return redirect(url_for("product_detail", product_id=product_id))
        if new_quantity is None:
            abort(404)
        action = "received" if movement_type == "stock_in" else "dispatched"
        flash(f"{quantity_text} units {action}. Current stock: {new_quantity}.", "success")
        return redirect(url_for("product_detail", product_id=product_id))

    @application.post("/inventory/<int:product_id>/stock-in")
    def stock_in(product_id):
        return change_stock(product_id, "stock_in")

    @application.post("/inventory/<int:product_id>/stock-out")
    def stock_out(product_id):
        return change_stock(product_id, "stock_out")

    @application.get("/movements")
    def movement_history():
        search = request.args.get("q", "").strip()
        with connection() as db_connection:
            if search:
                pattern = f"%{search}%"
                movements = db_connection.execute(
                    """SELECT * FROM stock_movements WHERE item_id LIKE ? OR notes LIKE ?
                       ORDER BY created_at DESC, id DESC LIMIT 500""",
                    (pattern, pattern),
                ).fetchall()
            else:
                movements = db_connection.execute(
                    "SELECT * FROM stock_movements ORDER BY created_at DESC, id DESC LIMIT 500"
                ).fetchall()
        return render_template("movements.html", movements=movements)

    @application.get("/reports")
    def reports():
        report_type = request.args.get("type", "all")
        report_types = {"all", "low", "expired", "soon"}
        if report_type not in report_types:
            report_type = "all"
        products = filtered_products()
        if report_type == "low":
            products = [item for item in products if item["quantity"] <= current_app.config["LOW_STOCK_THRESHOLD"]]
        elif report_type in {"expired", "soon"}:
            target = "Expired" if report_type == "expired" else "Expiring soon"
            products = [item for item in products if expiry_status(item["expiry"]) == target]
        return render_template("reports.html", products=products, report_type=report_type)

    @application.get("/export.csv")
    def export_csv():
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["Item ID", "Product name", "Warehouse location", "Quantity", "Expiry date", "Expiry status", "Stock status"])
        for product in filtered_products():
            writer.writerow([
                product["item_id"], product["name"], product["location"], product["quantity"],
                product["expiry"], expiry_status(product["expiry"]),
                stock_status(product["quantity"], current_app.config["LOW_STOCK_THRESHOLD"]),
            ])
        return Response(
            "\ufeff" + output.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=stockpilot-inventory.csv"},
        )

    @application.errorhandler(404)
    def not_found(error):
        del error
        return render_template("404.html"), 404

    @application.errorhandler(500)
    def server_error(error):
        current_app.logger.error("Unhandled application error: %s", error)
        return render_template("500.html"), 500

    @application.errorhandler(CSRFError)
    def csrf_error(error):
        del error
        return render_template("500.html", message="Your form session expired. Reload the page and try again."), 400

    return application


app = create_app()


if __name__ == "__main__":
    app.run(debug=app.config["DEBUG"])