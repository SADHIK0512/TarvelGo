from flask import Flask, render_template, request, redirect, session
import uuid
import boto3
import os
from decimal import Decimal
from boto3.dynamodb.conditions import Attr
#from dotenv import load_dotenv

# ================= CONFIG =================
USE_STATIC_DATA = True  # 🔴 CHANGE TO False when admin DB is ready
AWS_REGION = "ap-south-1"

# ==========================================
# STATIC DATA (TEMP)
# ==========================================
if USE_STATIC_DATA:
    from utils.data import buses, trains, flights, hotels

# ==========================================
# APP SETUP
# ==========================================
app = Flask(__name__)
app.secret_key = "travelgo_secret"

# ==========================================
# AWS SETUP (IAM ROLE BASED)
# ==========================================
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
sns = boto3.client("sns", region_name=AWS_REGION)

users_table = dynamodb.Table("travel-Users")
bookings_table = dynamodb.Table("Bookings")
services_table = dynamodb.Table("TravelServices")

# ==========================================
# ADMIN CONFIG
# ==========================================
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "admin123"

def is_admin():
    return session.get("user") == ADMIN_EMAIL

# ==========================================
# HOME
# ==========================================
@app.route("/")
def home():
    return render_template("index.html")

# ==========================================
# LOGIN
# ==========================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect("/admin")

        user = users_table.get_item(Key={"email": email}).get("Item")
        if user and user["password"] == password:
            session["user"] = email
            return redirect("/dashboard")

        return render_template("login.html", error="Invalid credentials")

    return render_template("login.html")

# ==========================================
# REGISTER (REAL DB WRITE)
# ==========================================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        users_table.put_item(Item={
            "email": request.form["email"],
            "name": request.form["name"],
            "password": request.form["password"],
            "logins": 0
        })
        return redirect("/login")

    return render_template("register.html")

# ==========================================
# DASHBOARD
# ==========================================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/login")

    if is_admin():
        return redirect("/admin")

    response = bookings_table.scan(
        FilterExpression=Attr("email").eq(session["user"])
    )

    return render_template(
        "dashboard.html",
        bookings=response.get("Items", []),
        name=session["user"]
    )

# ==========================================
# ADMIN
# ==========================================
@app.route("/admin")
def admin():
    if not is_admin():
        return redirect("/login")
    return render_template("admin_dashboard.html")

# ==========================================
# DATA FETCH HELPERS
# ==========================================
def get_services(category, source=None, destination=None):
    if USE_STATIC_DATA:
        return {
            "bus": buses,
            "train": trains,
            "flight": flights,
            "hotel": hotels
        }.get(category, [])

    response = services_table.scan(
        FilterExpression=Attr("category").eq(category) & Attr("status").eq("Active")
    )
    return response.get("Items", [])

# ==========================================
# SEARCH ROUTES
# ==========================================
@app.route("/bus", methods=["GET", "POST"])
def bus():
    if request.method == "POST":
        return render_template("bus.html", buses=get_services("bus"), **request.form)
    return render_template("bus.html", buses=None)

@app.route("/train", methods=["GET", "POST"])
def train():
    if request.method == "POST":
        return render_template("train.html", trains=get_services("train"), **request.form)
    return render_template("train.html", trains=None)

@app.route("/flight", methods=["GET", "POST"])
def flight():
    if request.method == "POST":
        return render_template("flight.html", flights=get_services("flight"), **request.form)
    return render_template("flight.html", flights=None)

@app.route("/hotels", methods=["GET", "POST"])
def hotels_page():
    if request.method == "POST":
        return render_template("hotels.html", hotels=get_services("hotel"))
    return render_template("hotels.html", hotels=None)

# ==========================================
# BOOKING
# ==========================================
@app.route("/book", methods=["POST"])
def book():
    session["pending_booking"] = {
        "booking_id": str(uuid.uuid4())[:8],
        "email": session["user"],
        "type": request.form["type"],
        "source": request.form.get("source", "N/A"),
        "destination": request.form.get("destination", "N/A"),
        "date": request.form.get("date", "N/A"),
        "details": request.form["details"],
        "price": Decimal(request.form["price"])
    }

    return redirect("/payment")

# ==========================================
# PAYMENT
# ==========================================
@app.route("/payment", methods=["GET", "POST"])
def payment():
    booking = session.get("pending_booking")

    if request.method == "POST":
        booking["payment_reference"] = request.form["reference"]
        bookings_table.put_item(Item=booking)
        session.pop("pending_booking")
        return redirect("/dashboard")

    return render_template("payment.html", booking=booking)

# ==========================================
# LOGOUT
# ==========================================
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ==========================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

