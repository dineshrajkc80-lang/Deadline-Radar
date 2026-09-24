import hashlib
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime
from email.message import EmailMessage
from flask import Flask, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, "database")
DB_PATH = os.path.join(DB_DIR, "deadline_radar.db")
GUEST_NAME = "Guest User"
GUEST_EMAIL = "guest@deadline-radar.local"

app = Flask(__name__, template_folder=BASE_DIR, static_folder=BASE_DIR, static_url_path="")
app.config.update(
    JSON_SORT_KEYS=False,
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)


def hash_password(password):
    return generate_password_hash(password)


def verify_password(stored_password, password):
    if stored_password.startswith(("scrypt:", "pbkdf2:")):
        return check_password_hash(stored_password, password)
    return hashlib.sha256(password.encode("utf-8")).hexdigest() == stored_password


def get_db_connection():
    connection = sqlite3.connect(
        app.config.get("DATABASE", DB_PATH),
        timeout=10,
    )
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.row_factory = sqlite3.Row
    return connection


def ensure_guest_user(connection):
    guest = connection.execute("SELECT * FROM users WHERE email = ?", (GUEST_EMAIL,)).fetchone()
    if guest is not None:
        return dict(guest)

    connection.execute(
        "INSERT OR IGNORE INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (GUEST_NAME, GUEST_EMAIL, hash_password("guest-local-only")),
    )
    connection.commit()
    user = connection.execute("SELECT * FROM users WHERE email = ?", (GUEST_EMAIL,)).fetchone()
    return dict(user) if user else None


def get_current_user():
    user_id = session.get("user_id")
    connection = get_db_connection()
    if user_id:
        user = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        connection.close()
        if user:
            return dict(user)
        session.pop("user_id", None)

    guest = ensure_guest_user(connection)
    connection.close()
    return guest


def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    connection = get_db_connection()
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS deadlines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            course TEXT,
            due_date TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Medium',
            notes TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            reminder_email TEXT,
            reminder_sent INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_user_due ON deadlines (user_id, due_date)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_deadlines_user_status ON deadlines (user_id, status)")
    ensure_guest_user(connection)
    connection.commit()
    connection.close()


def serialize_deadline(row):
    if row is None:
        return None

    try:
        due_date = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
        today = datetime.today().date()
        days_left = (due_date - today).days
    except ValueError:
        days_left = None

    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "course": row["course"],
        "due_date": row["due_date"],
        "priority": row["priority"],
        "notes": row["notes"],
        "status": row["status"],
        "reminder_email": row["reminder_email"],
        "reminder_sent": bool(row["reminder_sent"]),
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
        "days_left": days_left,
    }


def require_auth():
    return get_current_user()


@app.after_request
def add_security_headers(response):
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://cdnjs.cloudflare.com 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data:; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.errorhandler(404)
def handle_not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found."}), 404
    return send_file(os.path.join(BASE_DIR, "index.html"), mimetype="text/html")


@app.errorhandler(405)
def handle_method_not_allowed(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Method not allowed."}), 405
    return send_file(os.path.join(BASE_DIR, "index.html"), mimetype="text/html")


@app.errorhandler(500)
def handle_server_error(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Internal server error."}), 500
    return "Internal server error.", 500


@app.route("/")
def index():
    return send_file(os.path.join(BASE_DIR, "index.html"), mimetype="text/html")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "message": "Deadline Radar backend is running."})


@app.route("/api/signup", methods=["POST"])
def signup():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not name or not email or len(password) < 6:
        return jsonify({"error": "Name, email, and password (minimum 6 characters) are required."}), 400

    connection = get_db_connection()
    existing = connection.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        connection.close()
        return jsonify({"error": "Email already registered."}), 409

    try:
        cursor = connection.execute(
            "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
            (name, email, hash_password(password)),
        )
    except sqlite3.IntegrityError:
        connection.close()
        return jsonify({"error": "Email already registered."}), 409
    connection.commit()
    user_id = cursor.lastrowid
    connection.close()

    session["user_id"] = user_id
    return jsonify({"id": user_id, "name": name, "email": email}), 201


@app.route("/api/login", methods=["POST"])
def login():
    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")

    if not email or not password:
        return jsonify({"error": "Email and password are required."}), 400

    connection = get_db_connection()
    user = connection.execute(
        "SELECT * FROM users WHERE email = ?",
        (email,),
    ).fetchone()
    connection.close()

    if not user or not verify_password(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    if not user["password_hash"].startswith(("scrypt:", "pbkdf2:")):
        connection = get_db_connection()
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user["id"]),
        )
        connection.commit()
        connection.close()

    session["user_id"] = user["id"]
    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out successfully."})


@app.route("/api/me")
def me():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    return jsonify({"id": user["id"], "name": user["name"], "email": user["email"]})


@app.route("/api/profile", methods=["GET"])
def profile():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    total = connection.execute("SELECT COUNT(*) FROM deadlines WHERE user_id = ?", (user["id"],)).fetchone()[0]
    pending = connection.execute(
        "SELECT COUNT(*) FROM deadlines WHERE user_id = ? AND status = 'pending'",
        (user["id"],),
    ).fetchone()[0]
    connection.close()

    return jsonify({
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "total_deadlines": total,
        "pending_deadlines": pending,
        "joined_at": user.get("created_at"),
    })


@app.route("/api/profile", methods=["PUT"])
def update_profile():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password")

    if not name or not email:
        return jsonify({"error": "Name and email are required."}), 400

    if password is not None and len(str(password)) < 6:
        return jsonify({"error": "Password must be at least 6 characters long."}), 400

    connection = get_db_connection()
    try:
        if password:
            connection.execute(
                "UPDATE users SET name = ?, email = ?, password_hash = ? WHERE id = ?",
                (name, email, hash_password(str(password)), user["id"]),
            )
        else:
            connection.execute(
                "UPDATE users SET name = ?, email = ? WHERE id = ?",
                (name, email, user["id"]),
            )
    except sqlite3.IntegrityError:
        connection.close()
        return jsonify({"error": "Email already registered."}), 409

    connection.commit()
    updated = connection.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    connection.close()

    return jsonify({
        "id": updated["id"],
        "name": updated["name"],
        "email": updated["email"],
    })


@app.route("/api/deadlines", methods=["GET"])
def get_deadlines():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    status_filter = (request.args.get("status") or "all").strip().lower()
    search_query = (request.args.get("q") or "").strip().lower()
    sort_by = (request.args.get("sort") or "due_date_asc").strip().lower()

    connection = get_db_connection()
    query = "SELECT * FROM deadlines WHERE user_id = ?"
    params = [user["id"]]

    if status_filter in {"pending", "completed"}:
        query += " AND status = ?"
        params.append(status_filter)

    if search_query:
        query += " AND (LOWER(title) LIKE ? OR LOWER(course) LIKE ? OR LOWER(notes) LIKE ?)"
        like_query = f"%{search_query}%"
        params.extend([like_query, like_query, like_query])

    if sort_by == "priority_desc":
        query += " ORDER BY CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END ASC, due_date ASC"
    elif sort_by == "priority_asc":
        query += " ORDER BY CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 WHEN 'Low' THEN 3 ELSE 4 END DESC, due_date ASC"
    elif sort_by == "created_at_desc":
        query += " ORDER BY created_at DESC"
    else:
        query += " ORDER BY due_date ASC, id DESC"

    rows = connection.execute(query, params).fetchall()
    connection.close()
    return jsonify([serialize_deadline(row) for row in rows])


@app.route("/api/deadlines", methods=["POST"])
def create_deadline():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    due_date = (payload.get("due_date") or "").strip()

    if not title or not due_date:
        return jsonify({"error": "Title and due date are required."}), 400

    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Due date must use YYYY-MM-DD format."}), 400

    course = (payload.get("course") or "").strip() or "General"
    priority = (payload.get("priority") or "Medium").strip().title()
    notes = (payload.get("notes") or "").strip()
    reminder_email = (payload.get("reminder_email") or user["email"]).strip().lower()

    if priority not in {"Low", "Medium", "High"}:
        priority = "Medium"

    connection = get_db_connection()
    cursor = connection.execute(
        """
        INSERT INTO deadlines (user_id, title, course, due_date, priority, notes, status, reminder_email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user["id"], title, course, due_date, priority, notes, "pending", reminder_email),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM deadlines WHERE id = ?", (cursor.lastrowid,)).fetchone()
    connection.close()
    return jsonify(serialize_deadline(row)), 201


@app.route("/api/deadlines/<int:deadline_id>", methods=["PUT"])
def update_deadline(deadline_id):
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    payload = request.get_json(silent=True) or {}
    title = (payload.get("title") or "").strip()
    due_date = (payload.get("due_date") or "").strip()

    if not title or not due_date:
        return jsonify({"error": "Title and due date are required."}), 400

    try:
        datetime.strptime(due_date, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "Due date must use YYYY-MM-DD format."}), 400

    course = (payload.get("course") or "").strip() or "General"
    priority = (payload.get("priority") or "Medium").strip().title()
    notes = (payload.get("notes") or "").strip()
    reminder_email = (payload.get("reminder_email") or user["email"]).strip().lower()

    if priority not in {"Low", "Medium", "High"}:
        priority = "Medium"

    connection = get_db_connection()
    row = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    if row is None:
        connection.close()
        return jsonify({"error": "Deadline not found."}), 404

    connection.execute(
        """
        UPDATE deadlines
        SET title = ?, course = ?, due_date = ?, priority = ?, notes = ?, reminder_email = ?
        WHERE id = ? AND user_id = ?
        """,
        (title, course, due_date, priority, notes, reminder_email, deadline_id, user["id"]),
    )
    connection.commit()
    updated = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    connection.close()
    return jsonify(serialize_deadline(updated))


@app.route("/api/deadlines/<int:deadline_id>", methods=["DELETE"])
def delete_deadline(deadline_id):
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    row = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    if row is None:
        connection.close()
        return jsonify({"error": "Deadline not found."}), 404

    connection.execute("DELETE FROM deadlines WHERE id = ? AND user_id = ?", (deadline_id, user["id"]))
    connection.commit()
    connection.close()
    return jsonify({"message": "Deadline deleted successfully."})


@app.route("/api/deadlines/<int:deadline_id>/toggle", methods=["PATCH"])
def toggle_deadline(deadline_id):
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    row = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    if row is None:
        connection.close()
        return jsonify({"error": "Deadline not found."}), 404

    new_status = "completed" if row["status"] == "pending" else "pending"
    completed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if new_status == "completed" else None

    connection.execute(
        "UPDATE deadlines SET status = ?, completed_at = ? WHERE id = ? AND user_id = ?",
        (new_status, completed_at, deadline_id, user["id"]),
    )
    connection.commit()
    updated = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    connection.close()
    return jsonify(serialize_deadline(updated))


@app.route("/api/summary")
def summary():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    total = connection.execute("SELECT COUNT(*) FROM deadlines WHERE user_id = ?", (user["id"],)).fetchone()[0]
    pending = connection.execute(
        "SELECT COUNT(*) FROM deadlines WHERE user_id = ? AND status = 'pending'",
        (user["id"],),
    ).fetchone()[0]
    completed = connection.execute(
        "SELECT COUNT(*) FROM deadlines WHERE user_id = ? AND status = 'completed'",
        (user["id"],),
    ).fetchone()[0]
    urgent = connection.execute(
        "SELECT COUNT(*) FROM deadlines WHERE user_id = ? AND status = 'pending' AND priority = 'High'",
        (user["id"],),
    ).fetchone()[0]
    connection.close()

    return jsonify({
        "total": total,
        "pending": pending,
        "completed": completed,
        "urgent": urgent,
    })


@app.route("/api/reminders")
def reminders():
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    rows = connection.execute(
        "SELECT * FROM deadlines WHERE user_id = ? AND status = 'pending' ORDER BY due_date ASC",
        (user["id"],),
    ).fetchall()
    connection.close()

    due_soon = []
    today = datetime.today().date()
    for row in rows:
        try:
            due_date = datetime.strptime(row["due_date"], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue
        days_left = (due_date - today).days
        if days_left <= 7:
            due_soon.append({
                "id": row["id"],
                "title": row["title"],
                "due_date": row["due_date"],
                "days_left": days_left,
                "priority": row["priority"],
                "reminder_email": row["reminder_email"],
                "reminder_sent": bool(row["reminder_sent"]),
            })

    return jsonify(due_soon)


@app.route("/api/reminders/send/<int:deadline_id>", methods=["POST"])
def send_reminder(deadline_id):
    user = require_auth()
    if not user:
        return jsonify({"error": "Not authenticated."}), 401

    connection = get_db_connection()
    row = connection.execute(
        "SELECT * FROM deadlines WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    ).fetchone()
    if row is None:
        connection.close()
        return jsonify({"error": "Reminder not found."}), 404

    smtp_host = os.environ.get("SMTP_HOST")
    try:
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    except ValueError:
        smtp_port = 587
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    send_status = "mock-sent"
    email_to = row["reminder_email"] or user["email"]

    if smtp_host and smtp_user and smtp_pass:
        try:
            message = EmailMessage()
            message["Subject"] = f"Reminder: {row['title']}"
            message["From"] = smtp_user
            message["To"] = email_to
            message.set_content(f"Hi, this is a reminder that '{row['title']}' is due on {row['due_date']}.")
            with smtplib.SMTP(smtp_host, smtp_port) as smtp:
                smtp.starttls()
                smtp.login(smtp_user, smtp_pass)
                smtp.send_message(message)
            send_status = "email-sent"
        except Exception:
            send_status = "mock-sent"

    connection.execute(
        "UPDATE deadlines SET reminder_sent = 1 WHERE id = ? AND user_id = ?",
        (deadline_id, user["id"]),
    )
    connection.commit()
    connection.close()

    return jsonify({
        "message": "Reminder processed successfully.",
        "status": send_status,
        "recipient": email_to,
    })


init_db()


if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=5000)
