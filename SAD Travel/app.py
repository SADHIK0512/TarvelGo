from flask import Flask, render_template, request, redirect, session, flash
import uuid
import boto3
from boto3.dynamodb.conditions import Attr
from decimal import Decimal

# ==========================================
# APP SETUP
# ==========================================
app = Flask(__name__)
app.secret_key = "travelgo_secret"

# ==========================================
# AWS SETUP (IAM ROLE BASED)
# ==========================================
# We do not use .env or keys here. Boto3 will automatically find 
# the IAM Role attached to your EC2 instance.
AWS_REGION = "ap-south-1"

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
# sns = boto3.client("sns", region_name=AWS_REGION) # Uncomment if you need SNS

# DynamoDB Tables (Matching your specific AWS spelling)
users_table = dynamodb.Table("travel-Users")
bookings_table = dynamodb.Table("Bookinngs")  # NOTE: double 'n' as per your table
services_table = dynamodb.Table("TravelServices")

# ==========================================
# ADMIN CONFIG
# ==========================================
ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "admin123"

def is_admin():
    return session.get("user") == ADMIN_EMAIL

# ==========================================
# MAIN ROUTES
# ==========================================

@app.route("/")
def home():
    return render_template("index.html", logged_in="user" in session)

# --- LOGIN ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        # 1. Admin Login Check
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect("/admin")

        # 2. User Login Check
        try:
            response = users_table.get_item(Key={"email": email})
            user = response.get("Item")
            
            if user and user["password"] == password:
                session["user"] = email
                # Update login count
                users_table.update_item(
                    Key={"email": email},
                    UpdateExpression="ADD logins :inc",
                    ExpressionAttributeValues={":inc": Decimal(1)}
                )
                return redirect("/dashboard")
            else:
                return render_template("login.html", error="Invalid Credentials")
        except Exception as e:
            print(f"Login Error: {e}")
            return render_template("login.html", error="System Error")

    return render_template("login.html")

# --- REGISTER ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]
        try:
            # Check if user already exists
            if "Item" in users_table.get_item(Key={"email": email}):
                return render_template("register.html", message="User already exists")

            # Create new user
            users_table.put_item(Item={
                "email": email,
                "name": request.form["name"],
                "password": request.form["password"],
                "logins": 0
            })
            return redirect("/login")
        except Exception as e:
            return render_template("register.html", message=f"Error: {e}")

    return render_template("register.html")

# --- DASHBOARD ---
@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect("/login")
    if is_admin(): return redirect("/admin")

    email = session["user"]
    
    # Fetch User's Bookings
    response = bookings_table.scan(FilterExpression=Attr("email").eq(email))
    bookings = response.get("Items", [])
    
    # Fetch User's Name
    user_resp = users_table.get_item(Key={"email": email})
    user_name = user_resp.get("Item", {}).get("name", "User")

    return render_template("dashboard.html", name=user_name, bookings=bookings)

# ==========================================
# ADMIN BACKEND (Add Data to DynamoDB)
# ==========================================

@app.route("/admin")
def admin_portal():
    if not is_admin(): return redirect("/login")
    return render_template("admin_dashboard.html")

@app.route("/admin/add_transport", methods=["POST"])
def add_transport():
    if not is_admin(): return redirect("/")

    service_id = str(uuid.uuid4())[:8]
    category = request.form["category"] # bus, train, flight

    # Create Item for TravelServices Table
    item = {
        "service_id": service_id,
        "category": category,
        "name": request.form["name"],
        "source": request.form["source"].strip(),
        "destination": request.form["destination"].strip(),
        "price": Decimal(request.form["price"]),
        "details": request.form["details"]
    }

    services_table.put_item(Item=item)
    flash(f"{category.title()} added successfully!")
    return redirect("/admin")

@app.route("/admin/add_hotel", methods=["POST"])
def add_hotel():
    if not is_admin(): return redirect("/")

    service_id = str(uuid.uuid4())[:8]

    # Create Hotel Item
    item = {
        "service_id": service_id,
        "category": "hotel",
        "name": request.form["name"],
        "location": request.form["location"].strip(),
        "price": Decimal(request.form["price"]),
        "details": request.form["details"]
    }

    services_table.put_item(Item=item)
    flash("Hotel added successfully!")
    return redirect("/admin")

# ==========================================
# DYNAMIC SEARCH LOGIC (From DynamoDB)
# ==========================================

def search_services(category, source=None, destination=None, location=None):
    try:
        if category == "hotel":
            # Search hotels by Location (City)
            response = services_table.scan(
                FilterExpression=Attr("category").eq("hotel") & Attr("location").eq(location)
            )
        else:
            # Search Transport by Source & Destination
            response = services_table.scan(
                FilterExpression=Attr("category").eq(category) & 
                                 Attr("source").eq(source) & 
                                 Attr("destination").eq(destination)
            )
        return response.get("Items", [])
    except Exception as e:
        print(f"Search Error: {e}")
        return []

@app.route("/bus", methods=["GET", "POST"])
def bus():
    results = None
    if request.method == "POST":
        s = request.form["source"].strip()
        d = request.form["destination"].strip()
        results = search_services("bus", source=s, destination=d)
    return render_template("bus.html", buses=results)

@app.route("/train", methods=["GET", "POST"])
def train():
    results = None
    if request.method == "POST":
        s = request.form["source"].strip()
        d = request.form["destination"].strip()
        results = search_services("train", source=s, destination=d)
    return render_template("train.html", trains=results)

@app.route("/flight", methods=["GET", "POST"])
def flight():
    results = None
    if request.method == "POST":
        s = request.form["source"].strip()
        d = request.form["destination"].strip()
        results = search_services("flight", source=s, destination=d)
    return render_template("flight.html", flights=results)

@app.route("/hotels", methods=["GET", "POST"])
def hotels():
    results = None
    if request.method == "POST":
        city = request.form["city"].strip()
        results = search_services("hotel", location=city)
    return render_template("hotels.html", hotels=results)

# ==========================================
# BOOKING & PAYMENT FLOW
# ==========================================

@app.route("/book", methods=["POST"])
def book():
    if "user" not in session: return redirect("/login")
    
    # Create Pending Booking Object
    session["pending_booking"] = {
        "booking_id": str(uuid.uuid4())[:8],
        "email": session["user"], # Partition Key for Bookinngs table
        "type": request.form.get("type", "Service"),
        "source": request.form.get("source", "N/A"),
        "destination": request.form.get("destination", "N/A"),
        "date": request.form.get("date", "N/A"),
        "details": request.form.get("details", "N/A"),
        "price": Decimal(request.form["price"])
    }

    # Redirect: Transport -> Seat Selection | Hotel -> Payment directly
    if session["pending_booking"]["type"] in ["Bus", "Train", "Flight"]:
        return redirect("/select_seats")
        
    return render_template("payment.html", booking=session["pending_booking"])

@app.route("/select_seats")
def select_seats():
    if "user" not in session: return redirect("/login")
    return render_template("select_seats.html")

@app.route("/confirm_seats", methods=["POST"])
def confirm_seats():
    if "pending_booking" not in session: return redirect("/")
    
    seats = request.form.get("selected_seats")
    session["pending_booking"]["details"] += f" | Seats: {seats}"
    return render_template("payment.html", booking=session["pending_booking"])

@app.route("/payment", methods=["POST"])
def payment():
    if "pending_booking" not in session: return redirect("/")
    
    booking = session.pop("pending_booking")
    booking["payment_reference"] = request.form["reference"]
    booking["payment_method"] = request.form["method"]
    
    # Save to DynamoDB
    bookings_table.put_item(Item=booking)
    
    return redirect("/dashboard")

# --- UTILS ---
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/contact", methods=["POST"])
def contact():
    # Placeholder for contact form (optional: save to DB)
    return redirect("/")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
