import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager
from .config import settings
def get_connection(db_path: str = None) -> sqlite3.Connection:
    path = db_path or settings.DB_PATH
    conn = sqlite3.connect(path, timeout=20.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Enable Write-Ahead Logging (WAL) for superior concurrency and reader/writer separation
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn
def init_db(db_path: str = None):
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        price REAL NOT NULL,
        available_stock INTEGER NOT NULL CHECK (available_stock >= 0),
        reserved_stock INTEGER NOT NULL DEFAULT 0 CHECK (reserved_stock >= 0),
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reservations (
        reservation_id TEXT PRIMARY KEY,
        order_id TEXT NOT NULL,
        product_id TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK (quantity > 0),
        status TEXT NOT NULL, -- RESERVED, CONFIRMED, RELEASED
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    );
    """)
    # Seed default products if table is empty
    cursor.execute("SELECT COUNT(*) AS cnt FROM products;")
     if cursor.fetchone()["cnt"] == 0:
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
        INSERT INTO products (product_id, name, price, available_stock, reserved_stock, version, created_at, updated_at)
        VALUES 
            ('PROD-IPHONE15', 'iPhone 15 Pro Max (Flash Sale)', 999.0, 5, 0, 1, ?, ?),
            ('PROD-HEADPHONE', 'Sony WH-1000XM5 Wireless Headphones', 399.0, 50, 0, 1, ?, ?),
            ('PROD-CHARGER', 'Anker 65W GaN Fast Charger', 35.0, 200, 0, 1, ?, ?);
        """, (now, now, now, now, now, now))
        
    conn.close()
def reset_product_stock(product_id: str, stock: int, db_path: str = None):
    conn = get_connection(db_path)
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.cursor()
    cursor.execute("BEGIN IMMEDIATE;")
    cursor.execute("""
        UPDATE products 
        SET available_stock = ?, reserved_stock = 0, version = version + 1, updated_at = ?
        WHERE product_id = ?;
    """, (stock, now, product_id))
    cursor.execute("DELETE FROM reservations WHERE product_id = ?;", (product_id,))
    cursor.execute("COMMIT;")
    conn.close()