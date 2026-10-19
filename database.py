import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


LOGGER = logging.getLogger(__name__)
DATABASE_PATH = Path(__file__).resolve().with_name("inventory.db")
JSON_PATH = Path(__file__).with_name("inventory.json")
DATE_FORMAT = "%d-%m-%Y"


def parse_expiry(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{2}-\d{2}-\d{4}", value):
        return None
    try:
        return datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        return None


def get_connection(database_path=None):
    path = Path(database_path or DATABASE_PATH).expanduser()
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def connection_scope(database_path=None):
    connection = get_connection(database_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path=None, json_path=None):
    with connection_scope(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY,
                item_id TEXT NOT NULL UNIQUE CHECK (length(trim(item_id)) > 0),
                name TEXT NOT NULL CHECK (length(trim(name)) > 0),
                location TEXT NOT NULL CHECK (length(trim(location)) > 0),
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                expiry TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS stock_movements (
                id INTEGER PRIMARY KEY,
                product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
                item_id TEXT NOT NULL,
                movement_type TEXT NOT NULL CHECK (movement_type IN ('stock_in', 'stock_out')),
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(trim(username)) > 0),
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
            CREATE INDEX IF NOT EXISTS idx_products_location ON products(location);
            CREATE INDEX IF NOT EXISTS idx_products_expiry ON products(expiry);
            CREATE INDEX IF NOT EXISTS idx_movements_created ON stock_movements(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_movements_item ON stock_movements(item_id);
            """
        )
    return migrate_json(json_path, database_path)


def get_account_by_username(username, database_path=None):
    with connection_scope(database_path) as connection:
        return connection.execute(
            "SELECT id, username, password_hash FROM accounts WHERE username = ?",
            (username,),
        ).fetchone()


def get_account_by_id(account_id, database_path=None):
    with connection_scope(database_path) as connection:
        return connection.execute(
            "SELECT id, username FROM accounts WHERE id = ?",
            (account_id,),
        ).fetchone()


def create_account(username, password_hash, database_path=None):
    with connection_scope(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO accounts (username, password_hash) VALUES (?, ?)",
            (username, password_hash),
        )
        return cursor.lastrowid


def update_account_password(username, password_hash, database_path=None):
    with connection_scope(database_path) as connection:
        cursor = connection.execute(
            "UPDATE accounts SET password_hash = ? WHERE username = ?",
            (password_hash, username),
        )
        return cursor.rowcount > 0


def migrate_json(json_path=None, database_path=None):
    source = Path(json_path or JSON_PATH)
    summary = {"imported": 0, "skipped": 0, "errors": []}
    if not source.exists():
        return summary

    try:
        with source.open("r", encoding="utf-8") as file:
            records = json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        summary["errors"].append(f"Could not read {source.name}: {error}")
        LOGGER.warning("JSON inventory migration: %s", summary["errors"][-1])
        return summary

    if not isinstance(records, list):
        summary["errors"].append("The JSON root must be a list; no records were imported.")
        LOGGER.warning("JSON inventory migration: %s", summary["errors"][-1])
        return summary

    with connection_scope(database_path) as connection:
        for index, record in enumerate(records, start=1):
            if not isinstance(record, dict):
                summary["skipped"] += 1
                summary["errors"].append(f"Record {index}: expected an object.")
                continue

            item_id = record.get("item_id")
            name = record.get("name")
            location = record.get("location")
            quantity = record.get("quantity")
            expiry = record.get("expiry")
            valid_quantity = (
                isinstance(quantity, int)
                and not isinstance(quantity, bool)
                and 0 < quantity <= 9223372036854775807
            )
            if not all(isinstance(value, str) and value.strip() for value in (item_id, name, location)):
                valid = False
            else:
                valid = valid_quantity and parse_expiry(expiry) is not None

            if not valid:
                summary["skipped"] += 1
                summary["errors"].append(f"Record {index}: missing or invalid inventory fields.")
                continue

            cursor = connection.execute(
                """INSERT OR IGNORE INTO products (item_id, name, location, quantity, expiry)
                   VALUES (?, ?, ?, ?, ?)""",
                (item_id.strip(), name.strip(), location.strip(), quantity, expiry),
            )
            if cursor.rowcount == 0:
                summary["skipped"] += 1
                summary["errors"].append(f"Record {index}: item ID {item_id.strip()} already exists; kept database record.")
                continue

            product_id = cursor.lastrowid
            connection.execute(
                """INSERT INTO stock_movements (product_id, item_id, movement_type, quantity, notes)
                   VALUES (?, ?, 'stock_in', ?, 'Initial quantity imported from inventory.json')""",
                (product_id, item_id.strip(), quantity),
            )
            summary["imported"] += 1

    if summary["imported"] or summary["skipped"] or summary["errors"]:
        LOGGER.info(
            "JSON inventory migration finished: %s imported, %s skipped, %s issue(s).",
            summary["imported"], summary["skipped"], len(summary["errors"]),
        )
        for error in summary["errors"]:
            LOGGER.warning("JSON inventory migration: %s", error)
    return summary


def create_product(item_id, name, location, quantity, expiry, database_path=None):
    with connection_scope(database_path) as connection:
        cursor = connection.execute(
            "INSERT INTO products (item_id, name, location, quantity, expiry) VALUES (?, ?, ?, ?, ?)",
            (item_id, name, location, quantity, expiry),
        )
        product_id = cursor.lastrowid
        connection.execute(
            """INSERT INTO stock_movements (product_id, item_id, movement_type, quantity, notes)
               VALUES (?, ?, 'stock_in', ?, 'Opening stock')""",
            (product_id, item_id, quantity),
        )
        return product_id


def update_product(product_id, name, location, expiry, database_path=None):
    with connection_scope(database_path) as connection:
        cursor = connection.execute(
            "UPDATE products SET name = ?, location = ?, expiry = ? WHERE id = ?",
            (name, location, expiry, product_id),
        )
        return cursor.rowcount > 0


def record_stock_movement(product_id, movement_type, quantity, notes="", database_path=None):
    if movement_type not in ("stock_in", "stock_out") or not 0 < quantity <= 9223372036854775807:
        raise ValueError("A valid movement type and positive quantity are required.")

    with connection_scope(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        product = connection.execute(
            "SELECT item_id, quantity FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        if product is None:
            return None
        if movement_type == "stock_out" and quantity > product["quantity"]:
            raise ValueError("Stock out quantity exceeds the available stock.")
        if movement_type == "stock_in" and quantity > 9223372036854775807 - product["quantity"]:
            raise ValueError("Stock in quantity exceeds the supported stock limit.")

        operator = "+" if movement_type == "stock_in" else "-"
        connection.execute(
            f"UPDATE products SET quantity = quantity {operator} ? WHERE id = ?",
            (quantity, product_id),
        )
        connection.execute(
            """INSERT INTO stock_movements (product_id, item_id, movement_type, quantity, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (product_id, product["item_id"], movement_type, quantity, notes.strip()),
        )
        return product["quantity"] + quantity if movement_type == "stock_in" else product["quantity"] - quantity