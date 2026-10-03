import sqlite3
import os
import json
import hashlib
import binascii

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "sns_filterhub.db")

def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password: str) -> str:
    """Generate a secure salted PBKDF2-HMAC-SHA256 password hash."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return f"pbkdf2:sha256:100000${binascii.hexlify(salt).decode('ascii')}${binascii.hexlify(dk).decode('ascii')}"

def verify_password(stored_hash: str, password: str) -> bool:
    """Verify password against stored PBKDF2 hash."""
    try:
        if not stored_hash or not stored_hash.startswith("pbkdf2:sha256:"):
            return False
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False
        meta, salt_hex, hash_hex = parts
        iterations = int(meta.split(":")[2])
        salt = binascii.unhexlify(salt_hex.encode("ascii"))
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return binascii.hexlify(dk).decode("ascii") == hash_hex
    except Exception:
        return False

def init_db():
    """Initialize database tables according to specifications."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'USER',
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS user_filters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        attribute_name TEXT NOT NULL,
        operator TEXT NOT NULL,
        attribute_value TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        sns_topic_arn TEXT NOT NULL,
        sqs_queue_url TEXT,
        filter_policy TEXT,
        status TEXT DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        payload TEXT NOT NULL,
        attributes TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS message_deliveries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        subscription_id INTEGER REFERENCES subscriptions(id) ON DELETE SET NULL,
        status TEXT NOT NULL,
        reason TEXT,
        matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        delivered_at TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        message_id TEXT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        read_status INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DATABASE_PATH)
