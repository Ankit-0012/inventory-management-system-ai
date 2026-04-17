import sqlite3


def ensure_column(cursor, table_name, column_name, definition):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}

    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

# USERS TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        email TEXT,
        password TEXT,
        role TEXT,
        photo TEXT,
        approved INTEGER DEFAULT 1
    )
    """
)

ensure_column(cursor, "users", "photo", "TEXT")
ensure_column(cursor, "users", "approved", "INTEGER DEFAULT 1")

# PRODUCTS TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS products(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        price REAL,
        quantity INTEGER
    )
    """
)

# SALES TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        quantity_sold INTEGER,
        sale_date TEXT
    )
    """
)

# AI TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS predictions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        day INTEGER,
        predicted_value INTEGER
    )
    """
)

# SALES HISTORY TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS sales_history(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        product_id INTEGER,
        product_name TEXT,
        quantity INTEGER,
        sale_date TEXT,
        sale_time TEXT,
        total_amount REAL,
        recorded_at TEXT
    )
    """
)

# ACTIVITY LOGS TABLE
cursor.execute(
    """
    CREATE TABLE IF NOT EXISTS activity_logs(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        actor_role TEXT,
        section TEXT,
        details TEXT,
        product_name TEXT,
        log_date TEXT,
        log_time TEXT,
        created_at TEXT
    )
    """
)

# DEFAULT ADMIN
cursor.execute(
    """
    INSERT INTO users(username, email, password, role, approved)
    SELECT 'admin', 'admin@email.com', 'admin123', 'admin', 1
    WHERE NOT EXISTS (
        SELECT 1 FROM users WHERE username='admin'
    )
    """
)

conn.commit()
conn.close()

print("Database Ready")
