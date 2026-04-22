from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
app.secret_key = "demo-secret-key"

USERS = {"admin": "password123", "user": "qwerty"}

ITEMS = [
    {"id": 1, "name": "Ноутбук", "price": 75000},
    {"id": 2, "name": "Мышь", "price": 1500},
    {"id": 3, "name": "Клавиатура", "price": 3000},
]


def _get_cart():
    return session.setdefault("cart", {})


def _cart_count():
    return sum(session.get("cart", {}).values())


@app.context_processor
def inject_cart_count():
    return {"cart_count": _cart_count()}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username in USERS and USERS[username] == password:
            session["user"] = username
            return redirect(url_for("dashboard"))
        error = "Неверный логин или пароль"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html", username=session["user"])


@app.route("/items")
def items():
    return render_template("items.html", items=ITEMS)


@app.route("/items/<int:item_id>")
def item_detail(item_id):
    item = next((i for i in ITEMS if i["id"] == item_id), None)
    if item is None:
        return render_template("404.html"), 404
    return render_template("item_detail.html", item=item)


@app.route("/cart/add/<int:item_id>", methods=["POST"])
def cart_add(item_id):
    item = next((i for i in ITEMS if i["id"] == item_id), None)
    if item:
        cart = _get_cart()
        cart[str(item_id)] = cart.get(str(item_id), 0) + 1
        session.modified = True
    return redirect(request.referrer or url_for("items"))


@app.route("/cart/remove/<int:item_id>", methods=["POST"])
def cart_remove(item_id):
    cart = _get_cart()
    cart.pop(str(item_id), None)
    session.modified = True
    return redirect(url_for("cart"))


@app.route("/cart/clear", methods=["POST"])
def cart_clear():
    session["cart"] = {}
    return redirect(url_for("cart"))


@app.route("/cart")
def cart():
    cart = _get_cart()
    cart_items = []
    total = 0
    for item in ITEMS:
        qty = cart.get(str(item["id"]), 0)
        if qty > 0:
            subtotal = item["price"] * qty
            total += subtotal
            cart_items.append({**item, "qty": qty, "subtotal": subtotal})
    return render_template("cart.html", cart_items=cart_items, total=total)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


if __name__ == "__main__":
    app.run(debug=True, port=8080)
