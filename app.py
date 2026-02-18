import os
import time
from flask import Flask, request, jsonify
import MySQLdb

app = Flask(__name__)

MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "root")
MYSQL_DB = os.getenv("MYSQL_DB", "devops")


def get_conn():
    return MySQLdb.connect(
        host=MYSQL_HOST,
        user=MYSQL_USER,
        passwd=MYSQL_PASSWORD,
        db=MYSQL_DB,
        charset="utf8mb4",
        autocommit=True,
    )


def init_db_with_retries(max_retries=30, delay_seconds=2):
    last_err = None
    for _ in range(max_retries):
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    quantity INT NOT NULL DEFAULT 1,
                    purchased BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.close()
            conn.close()
            return
        except Exception as e:
            last_err = e
            time.sleep(delay_seconds)
    raise last_err


@app.get("/health")
def health():
    # App health + DB connectivity
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        return jsonify(status="ok", db="ok"), 200
    except Exception as e:
        return jsonify(status="degraded", db="error", error=str(e)), 503


@app.get("/")
def index():
    return jsonify(
        message="Shopping List API",
        endpoints={
            "GET /items": "List items",
            "POST /items": "Add item {name, quantity?}",
            "PATCH /items/<id>": "Update item {name?, quantity?, purchased?}",
            "DELETE /items/<id>": "Delete item",
            "GET /health": "Healthcheck",
        },
    )


@app.get("/items")
def list_items():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, quantity, purchased, created_at FROM items ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    items = [
        {
            "id": r[0],
            "name": r[1],
            "quantity": r[2],
            "purchased": bool(r[3]),
            "created_at": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]
    return jsonify(items=items), 200


@app.post("/items")
def add_item():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    quantity = data.get("quantity", 1)

    if not name:
        return jsonify(error="name is required"), 400

    try:
        quantity = int(quantity)
        if quantity < 1:
            raise ValueError()
    except Exception:
        return jsonify(error="quantity must be an integer >= 1"), 400

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO items (name, quantity) VALUES (%s, %s)", (name, quantity))
    item_id = cur.lastrowid
    cur.close()
    conn.close()

    return jsonify(id=item_id, name=name, quantity=quantity, purchased=False), 201


@app.patch("/items/<int:item_id>")
def update_item(item_id: int):
    data = request.get_json(silent=True) or {}

    fields = []
    values = []

    if "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify(error="name cannot be empty"), 400
        fields.append("name=%s")
        values.append(name)

    if "quantity" in data:
        try:
            quantity = int(data.get("quantity"))
            if quantity < 1:
                raise ValueError()
        except Exception:
            return jsonify(error="quantity must be an integer >= 1"), 400
        fields.append("quantity=%s")
        values.append(quantity)

    if "purchased" in data:
        purchased = data.get("purchased")
        if not isinstance(purchased, bool):
            return jsonify(error="purchased must be a boolean"), 400
        fields.append("purchased=%s")
        values.append(purchased)

    if not fields:
        return jsonify(error="no valid fields provided"), 400

    values.append(item_id)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE items SET {', '.join(fields)} WHERE id=%s", tuple(values))
    affected = cur.rowcount
    cur.close()
    conn.close()

    if affected == 0:
        return jsonify(error="item not found"), 404

    return jsonify(status="updated"), 200


@app.delete("/items/<int:item_id>")
def delete_item(item_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE id=%s", (item_id,))
    affected = cur.rowcount
    cur.close()
    conn.close()

    if affected == 0:
        return jsonify(error="item not found"), 404

    return jsonify(status="deleted"), 200


if __name__ == "__main__":
    # Ensure DB schema exists when container starts
    init_db_with_retries()
    app.run(host="0.0.0.0", port=5000, debug=False)
