from flask import Flask, render_template, request, redirect, session, Response
import sqlite3
from datetime import date, datetime, timedelta
import os
import csv
import io
from werkzeug.utils import secure_filename

from ml_model import predict_sales

app = Flask(__name__)
app.secret_key = "inventory_secret"

LOG_FILTER_OPTIONS = [
    {"value": "all", "label": "All"},
    {"value": "admin", "label": "Admin"},
    {"value": "sales", "label": "Sales"},
    {"value": "add_product", "label": "Add Products"},
    {"value": "edit_product", "label": "Edit Product"},
    {"value": "auth", "label": "User Login / Logout"},
]

EXPORT_LOG_FILTER_OPTIONS = [
    {"value": "all", "label": "All"},
    {"value": "sales", "label": "Sales"},
    {"value": "add_product", "label": "Add Products"},
    {"value": "edit_product", "label": "Edit Product"},
    {"value": "auth", "label": "User Login / Logout"},
]

SECTION_LABELS = {
    "admin": "Admin",
    "sales": "Sales",
    "add_product": "Add Products",
    "edit_product": "Edit Product",
    "auth": "User Login / Logout",
}


def ensure_column(conn, table_name, column_name, definition):
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = {row[1] for row in cursor.fetchall()}

    if column_name not in columns:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def ensure_tables(conn):
    cursor = conn.cursor()

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

    ensure_column(conn, "users", "photo", "TEXT")
    ensure_column(conn, "users", "approved", "INTEGER DEFAULT 1")

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


def db():
    conn = sqlite3.connect("inventory.db")
    ensure_tables(conn)
    return conn


def parse_price(value):
    if value in (None, ""):
        return 0.0
    return float(value)


def parse_quantity(value):
    if value in (None, ""):
        return 0
    return int(value)


def log_activity(username, actor_role, section, details, product_name=None, conn=None, logged_at=None):
    if not username:
        return

    own_connection = conn is None
    if own_connection:
        conn = db()

    timestamp = logged_at or datetime.now()
    conn.execute(
        """
        INSERT INTO activity_logs(username, actor_role, section, details, product_name, log_date, log_time, created_at)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            username,
            actor_role,
            section,
            details,
            product_name,
            timestamp.strftime("%Y-%m-%d"),
            timestamp.strftime("%H:%M:%S"),
            timestamp.isoformat(),
        ),
    )

    if own_connection:
        conn.commit()
        conn.close()


def build_product_update_details(existing_product, name, category, price, quantity):
    changes = []

    if existing_product[1] != name:
        changes.append(f'name "{existing_product[1]}" to "{name}"')
    if (existing_product[2] or "") != category:
        changes.append(f'category "{existing_product[2] or ""}" to "{category}"')
    if float(existing_product[3] or 0) != float(price):
        changes.append(f"price {existing_product[3] or 0} to {price}")
    if int(existing_product[4] or 0) != int(quantity):
        changes.append(f"quantity {existing_product[4] or 0} to {quantity}")

    if changes:
        return f'edited product "{existing_product[1]}" - ' + ", ".join(changes)

    return f'edited product "{name}"'


def build_user_update_details(existing_user, username, email, role, password_changed):
    changes = []

    if existing_user[1] != username:
        changes.append(f'username "{existing_user[1]}" to "{username}"')
    if existing_user[2] != email:
        changes.append(f'email "{existing_user[2]}" to "{email}"')
    if existing_user[4] != role:
        changes.append(f'role "{existing_user[4]}" to "{role}"')
    if password_changed:
        changes.append("password reset")

    if changes:
        return f'edited user "{existing_user[1]}" - ' + ", ".join(changes)

    return f'edited user "{username}"'


def build_profile_update_details(old_name, new_name, old_email, new_email, photo_changed):
    changes = []

    if old_name != new_name:
        changes.append(f'name "{old_name}" to "{new_name}"')
    if old_email != new_email:
        changes.append(f'email "{old_email}" to "{new_email}"')
    if photo_changed:
        changes.append("updated profile photo")

    if changes:
        return "updated profile - " + ", ".join(changes)

    return "updated profile"


def fetch_logs(selected_filter, export_mode=False):
    valid_filters = {
        option["value"]
        for option in (EXPORT_LOG_FILTER_OPTIONS if export_mode else LOG_FILTER_OPTIONS)
    }

    if selected_filter not in valid_filters:
        selected_filter = "all"

    conn = db()
    cur = conn.cursor()

    query = """
        SELECT username, actor_role, section, details, product_name, log_time, log_date
        FROM activity_logs
    """
    params = []

    if selected_filter == "admin":
        query += " WHERE actor_role=?"
        params.append("admin")
    elif selected_filter == "all":
        if export_mode:
            query += " WHERE section IN (?,?,?,?)"
            params.extend(["sales", "add_product", "edit_product", "auth"])
    else:
        query += " WHERE section=?"
        params.append(selected_filter)

    query += " ORDER BY created_at DESC"

    cur.execute(query, params)
    logs = cur.fetchall()
    conn.close()

    return selected_filter, logs


def format_log_line(log):
    username, _, section, details, product_name, log_time, log_date = log

    if section == "sales":
        return f"{product_name} / {username} / {log_time} / {log_date}"

    return f"{username} / {details} / {log_time} / {log_date}"


@app.route("/")
def home():
    if "user" in session:
        return redirect("/dashboard")
    return redirect("/login")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password),
        )

        user = cur.fetchone()

        if user:
            session["user"] = user[1]
            session["role"] = user[4]

            if len(user) > 5 and user[5]:
                session["photo"] = user[5]
            else:
                session.pop("photo", None)

            log_activity(
                user[1],
                user[4],
                "auth",
                "logged in",
                conn=conn,
            )

            conn.commit()
            conn.close()
            return redirect("/dashboard")

        conn.close()
        return "Account not approved"

    return render_template("login.html")


# LOGOUT
@app.route("/logout")
def logout():
    username = session.get("user")
    actor_role = session.get("role")

    if username:
        conn = db()
        log_activity(username, actor_role, "auth", "logged out", conn=conn)
        conn.commit()
        conn.close()

    session.clear()
    return redirect("/login")


# DASHBOARD
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM products")
    total_products = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM products WHERE quantity<=5")
    low_stock = cur.fetchone()[0]

    cur.execute("SELECT SUM(quantity) FROM products")
    total_stock = cur.fetchone()[0]

    cur.execute("SELECT id, name, quantity FROM products")
    products = cur.fetchall()

    cur.execute(
        """
        SELECT name, quantity
        FROM products
        WHERE quantity <= 5
        """
    )
    low_stock_products = cur.fetchall()

    if total_stock is None:
        total_stock = 0

    cur.execute(
        """
        SELECT sale_date, SUM(quantity_sold)
        FROM sales
        GROUP BY sale_date
        """
    )
    sales = cur.fetchall()

    dates = [row[0] for row in sales]
    values = [row[1] for row in sales]

    conn.close()

    return render_template(
        "dashboard.html",
        total_products=total_products,
        low_stock=low_stock,
        total_stock=total_stock,
        chart_labels=dates,
        chart_values=values,
        products=products,
        low_stock_products=low_stock_products,
    )


# ANALYTICS
@app.route("/analytics")
def analytics():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT strftime('%Y-%m', sale_date) as month, SUM(quantity_sold)
        FROM sales
        GROUP BY month
        ORDER BY month
        """
    )
    data = cur.fetchall()

    months = [row[0] for row in data]
    totals = [row[1] for row in data]

    total_sales = sum(totals) if totals else 0
    last_month_sales = totals[-1] if totals else 0
    prev_month_sales = totals[-2] if len(totals) > 1 else 0
    mom_change = last_month_sales - prev_month_sales

    if prev_month_sales:
        mom_pct = round((mom_change / prev_month_sales) * 100, 1)
        mom_pct_display = f"{mom_pct}%"
    else:
        mom_pct_display = "N/A"

    cur.execute(
        """
        SELECT p.name, COALESCE(SUM(s.quantity_sold), 0) as total_sold
        FROM products p
        LEFT JOIN sales s ON s.product_id = p.id
        GROUP BY p.id
        ORDER BY total_sold DESC
        """
    )
    top_products = cur.fetchall()

    selected_days = request.args.get("daily_days", "14")

    try:
        selected_days = int(selected_days)
    except ValueError:
        selected_days = 14

    if selected_days not in {7, 14, 30}:
        selected_days = 14

    cur.execute(
        """
        SELECT sale_date, SUM(quantity_sold)
        FROM sales
        GROUP BY sale_date
        ORDER BY sale_date DESC
        LIMIT ?
        """,
        (selected_days,),
    )

    daily_rows = cur.fetchall()
    daily_rows.reverse()
    daily_labels = [row[0] for row in daily_rows]
    daily_totals = [row[1] for row in daily_rows]

    conn.close()

    return render_template(
        "analytics.html",
        months=months,
        totals=totals,
        daily_labels=daily_labels,
        daily_totals=daily_totals,
        daily_days=selected_days,
        total_sales=total_sales,
        last_month_sales=last_month_sales,
        mom_change=mom_change,
        mom_pct_display=mom_pct_display,
        top_products=top_products,
    )


# PRODUCTS
@app.route("/products")
def products():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products")
    products = cur.fetchall()

    conn.close()
    return render_template("products.html", products=products)


# ADD PRODUCT
@app.route("/add_product", methods=["GET", "POST"])
def add_product():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        price = parse_price(request.form["price"])
        quantity = parse_quantity(request.form["quantity"])

        conn = db()
        cur = conn.cursor()

        cur.execute(
            "INSERT INTO products(name, category, price, quantity) VALUES(?,?,?,?)",
            (name, category, price, quantity),
        )

        log_activity(
            session["user"],
            session.get("role"),
            "add_product",
            f'added product "{name}"',
            product_name=name,
            conn=conn,
        )

        conn.commit()
        conn.close()

        return redirect("/products")

    return render_template("add_product.html")


# EDIT PRODUCT
@app.route("/edit_product/<int:id>", methods=["GET", "POST"])
def edit_product(id):
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products WHERE id=?", (id,))
    product = cursor.fetchone()

    if not product:
        conn.close()
        return redirect("/products")

    if request.method == "POST":
        name = request.form["name"]
        category = request.form["category"]
        price = parse_price(request.form["price"])
        quantity = parse_quantity(request.form["quantity"])

        details = build_product_update_details(product, name, category, price, quantity)

        cursor.execute(
            "UPDATE products SET name=?, category=?, price=?, quantity=? WHERE id=?",
            (name, category, price, quantity, id),
        )

        log_activity(
            session["user"],
            session.get("role"),
            "edit_product",
            details,
            product_name=name,
            conn=conn,
        )

        conn.commit()
        conn.close()
        return redirect("/products")

    conn.close()
    return render_template("edit_product.html", product=product)


# DELETE PRODUCT
@app.route("/delete_product/<int:id>")
def delete_product(id):
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM products WHERE id=?", (id,))
    product = cursor.fetchone()

    if not product:
        conn.close()
        return redirect("/products")

    cursor.execute("DELETE FROM products WHERE id=?", (id,))

    log_activity(
        session["user"],
        session.get("role"),
        "edit_product",
        f'deleted product "{product[0]}"',
        product_name=product[0],
        conn=conn,
    )

    conn.commit()
    conn.close()
    return redirect("/products")


# RECORD SALE
@app.route("/record_sale", methods=["GET", "POST"])
def record_sale():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, quantity, price FROM products")
    products = cursor.fetchall()

    if request.method == "POST":
        product_id = request.form["product_id"]
        quantity = parse_quantity(request.form["quantity"])

        cursor.execute("SELECT name, quantity, price FROM products WHERE id=?", (product_id,))
        product_row = cursor.fetchone()

        if not product_row:
            conn.close()
            return "Product not found"

        stock = product_row[1]
        if quantity > stock:
            conn.close()
            return "Not enough stock!"

        today = date.today().isoformat()
        now = datetime.now()

        cursor.execute(
            """
            SELECT id, quantity_sold
            FROM sales
            WHERE product_id=? AND sale_date=?
            """,
            (product_id, today),
        )
        existing_sale = cursor.fetchone()

        if existing_sale:
            new_qty = existing_sale[1] + quantity
            cursor.execute(
                """
                UPDATE sales
                SET quantity_sold=?
                WHERE id=?
                """,
                (new_qty, existing_sale[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO sales(product_id, quantity_sold, sale_date)
                VALUES(?,?,?)
                """,
                (product_id, quantity, today),
            )

        cursor.execute(
            """
            UPDATE products
            SET quantity = quantity - ?
            WHERE id=?
            """,
            (quantity, product_id),
        )

        sale_time = now.strftime("%H:%M:%S")
        recorded_at = now.isoformat()
        unit_price = product_row[2] or 0
        total_amount = unit_price * quantity

        cursor.execute(
            """
            INSERT INTO sales_history(username, product_id, product_name, quantity, sale_date, sale_time, total_amount, recorded_at)
            VALUES(?,?,?,?,?,?,?,?)
            """,
            (
                session["user"],
                product_id,
                product_row[0],
                quantity,
                today,
                sale_time,
                total_amount,
                recorded_at,
            ),
        )

        log_activity(
            session["user"],
            session.get("role"),
            "sales",
            f"sold {quantity} unit(s)",
            product_name=product_row[0],
            conn=conn,
            logged_at=now,
        )

        conn.commit()
        conn.close()
        return redirect("/record_sale")

    seven_days_ago = (date.today() - timedelta(days=6)).isoformat()

    cursor.execute(
        """
        SELECT product_name, quantity, sale_time, sale_date, total_amount
        FROM sales_history
        WHERE username=? AND sale_date >= ?
        ORDER BY recorded_at DESC
        """,
        (session["user"], seven_days_ago),
    )
    history = cursor.fetchall()

    conn.close()
    return render_template("record_sale.html", products=products, history=history)


# ADMIN USERS
@app.route("/admin/users")
def users():
    if session.get("role") != "admin":
        return "Access denied"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users")
    users = cur.fetchall()

    conn.close()
    return render_template("manage_users.html", users=users)


# ADMIN LOGS
@app.route("/admin/logs")
def admin_logs():
    if session.get("role") != "admin":
        return "Access denied"

    selected_filter, logs = fetch_logs(request.args.get("section", "all"))

    return render_template(
        "logs.html",
        logs=logs,
        filter_options=LOG_FILTER_OPTIONS,
        export_filter_options=EXPORT_LOG_FILTER_OPTIONS,
        selected_filter=selected_filter,
        section_labels=SECTION_LABELS,
        selected_export_filter="all",
    )


@app.route("/admin/logs/export")
def export_logs():
    if session.get("role") != "admin":
        return "Access denied"

    selected_filter, logs = fetch_logs(request.args.get("section", "all"), export_mode=True)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Section", "Log Details"])

    for log in logs:
        writer.writerow(
            [
                SECTION_LABELS.get(log[2], log[2].replace("_", " ").title()),
                format_log_line(log),
            ]
        )

    filename = f"logs_{selected_filter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# AI FORECAST
@app.route("/ai_forecast", methods=["GET"])
def ai_forecast():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, quantity FROM products")
    products = cursor.fetchall()

    multi_predictions = []
    for prod in products:
        prod_pred = predict_sales(prod[0])
        multi_predictions.append(
            {
                "name": prod[1],
                "stock": prod[2],
                "daily": prod_pred["daily"],
                "weekly": prod_pred["weekly"],
                "monthly": prod_pred["monthly"],
            }
        )

    cursor.execute(
        """
        SELECT p.name, COALESCE(SUM(s.quantity_sold), 0) as total_sold
        FROM products p
        LEFT JOIN sales s ON s.product_id = p.id
        GROUP BY p.id
        ORDER BY total_sold DESC
        """
    )
    top_products = cursor.fetchall()

    product_id = request.args.get("product")
    days = []
    forecast = []
    actual_sales = []
    prediction = {"daily": 0, "weekly": 0, "monthly": 0}

    if product_id:
        cursor.execute(
            """
            SELECT day, predicted_value
            FROM predictions
            WHERE product_id=?
            ORDER BY day
            """,
            (product_id,),
        )
        saved_predictions = cursor.fetchall()

        if len(saved_predictions) >= 30:
            for row in saved_predictions:
                days.append(f"Day {row[0]}")
                forecast.append(row[1])

            prediction = predict_sales(product_id)
        else:
            prediction = predict_sales(product_id)
            ai_prediction = prediction["forecast"]

            for i, value in enumerate(ai_prediction):
                day = i + 1
                forecast.append(value)
                days.append(f"Day {day}")

                cursor.execute(
                    """
                    INSERT INTO predictions(product_id, day, predicted_value)
                    VALUES(?,?,?)
                    """,
                    (product_id, day, value),
                )

            conn.commit()

        cursor.execute(
            """
            SELECT sale_date, SUM(quantity_sold)
            FROM sales
            WHERE product_id=?
            GROUP BY sale_date
            ORDER BY sale_date
            LIMIT 30
            """,
            (product_id,),
        )
        sales_data = cursor.fetchall()

        for sale in sales_data:
            actual_sales.append(sale[1])

    conn.close()

    return render_template(
        "ai_forecast.html",
        products=products,
        prediction=prediction,
        days=days,
        forecast=forecast,
        actual_sales=actual_sales,
        selected_product=product_id,
        predictions=multi_predictions,
        top_products=top_products,
    )


# CHANGE ROLE
@app.route("/change_role/<int:id>/<role>")
def change_role(id, role):
    if session.get("role") != "admin":
        return "Access denied"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT username, role FROM users WHERE id=?", (id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/admin/users")

    cur.execute("UPDATE users SET role=? WHERE id=?", (role, id))

    log_activity(
        session["user"],
        session.get("role"),
        "admin",
        f'changed role for "{user[0]}" from "{user[1]}" to "{role}"',
        conn=conn,
    )

    conn.commit()
    conn.close()
    return redirect("/admin/users")


# ADD USER
@app.route("/admin/add_user", methods=["GET", "POST"])
def admin_add_user():
    if session.get("role") != "admin":
        return "Access denied"

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        role = request.form["role"]

        conn = db()
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO users(username, email, password, role, approved)
            VALUES(?,?,?,?,1)
            """,
            (username, email, password, role),
        )

        log_activity(
            session["user"],
            session.get("role"),
            "admin",
            f'added user "{username}" with role "{role}"',
            conn=conn,
        )

        conn.commit()
        conn.close()
        return redirect("/admin/users")

    return render_template("add_user.html")


# DELETE USER
@app.route("/delete_user/<int:id>")
def delete_user(id):
    if session.get("role") != "admin":
        return "Access denied"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE id=?", (id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/admin/users")

    cur.execute("DELETE FROM users WHERE id=?", (id,))

    log_activity(
        session["user"],
        session.get("role"),
        "admin",
        f'deleted user "{user[0]}"',
        conn=conn,
    )

    conn.commit()
    conn.close()
    return redirect("/admin/users")


# EDIT USER
@app.route("/edit_user/<int:id>", methods=["GET", "POST"])
def edit_user(id):
    if session.get("role") != "admin":
        return "Access denied"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id=?", (id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/admin/users")

    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        role = request.form["role"]
        password = request.form.get("password")
        password_changed = bool(password)

        details = build_user_update_details(user, username, email, role, password_changed)

        if password_changed:
            cur.execute(
                "UPDATE users SET username=?, email=?, role=?, password=? WHERE id=?",
                (username, email, role, password, id),
            )
        else:
            cur.execute(
                "UPDATE users SET username=?, email=?, role=? WHERE id=?",
                (username, email, role, id),
            )

        log_activity(
            session["user"],
            session.get("role"),
            "admin",
            details,
            conn=conn,
        )

        conn.commit()
        conn.close()
        return redirect("/admin/users")

    conn.close()
    return render_template("edit_user.html", user=user)


# PROFILE
@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    cur = conn.cursor()

    cur.execute(
        "SELECT username, email, photo FROM users WHERE username=?",
        (session["user"],),
    )
    existing_user = cur.fetchone()

    if request.method == "POST":
        old_name = session["user"]
        old_email = existing_user[1] if existing_user else ""
        name = request.form["name"]
        email = request.form["email"]
        photo = request.files["photo"]
        filename = None
        photo_changed = False

        if photo and photo.filename != "":
            filename = secure_filename(photo.filename)
            path = os.path.join("static/profile", filename)
            photo.save(path)

            cur.execute(
                "UPDATE users SET username=?, email=?, photo=? WHERE username=?",
                (name, email, filename, session["user"]),
            )
            session["photo"] = filename
            photo_changed = True
        else:
            cur.execute(
                "UPDATE users SET username=?, email=? WHERE username=?",
                (name, email, session["user"]),
            )

        details = build_profile_update_details(old_name, name, old_email, email, photo_changed)
        log_section = "admin" if session.get("role") == "admin" else "auth"

        log_activity(
            old_name,
            session.get("role"),
            log_section,
            details,
            conn=conn,
        )

        conn.commit()
        session["user"] = name

    cur.execute(
        "SELECT username, email FROM users WHERE username=?",
        (session["user"],),
    )
    user = cur.fetchone()

    conn.close()
    return render_template("profile.html", user=user)


@app.route("/approve/<int:id>")
def approve(id):
    if session.get("role") != "admin":
        return "Access denied"

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT username FROM users WHERE id=?", (id,))
    user = cur.fetchone()

    if not user:
        conn.close()
        return redirect("/admin/users")

    cur.execute("UPDATE users SET approved=1 WHERE id=?", (id,))

    log_activity(
        session["user"],
        session.get("role"),
        "admin",
        f'approved user "{user[0]}"',
        conn=conn,
    )

    conn.commit()
    conn.close()
    return redirect("/admin/users")


if __name__ == "__main__":
    app.run(debug=True)
