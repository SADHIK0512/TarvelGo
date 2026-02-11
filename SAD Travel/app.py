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

# Helper to handle DynamoDB Decimals in Flask templates
@app.template_filter('force_float')
def force_float(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

# ==========================================
# AWS SETUP (IAM ROLE BASED)
# ==========================================
AWS_REGION = "ap-south-1"

try:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    # DynamoDB Tables 
    users_table = dynamodb.Table("travel-Users")
    bookings_table = dynamodb.Table("Bookinngs")  # Using your specific spelling
    services_table = dynamodb.Table("TravelServices")
except Exception as e:
    print(f"AWS Configuration Error: {e}")

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
        email = request.form.get("email")
        password = request.form.get("password")

        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect("/admin")

        try:
            response = users_table.get_item(Key={"email": email})
            user = response.get("Item")
            
            if user and user.get("password") == password:
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
            return render_template("login.html", error="System Error or User not found")

    return render_template("login.html")

# --- REGISTER ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        name = request.form.get("name")
        password = request.form.get("password")
        try:
            if "Item" in users_table.get_item(Key={"email": email}):
                return render_template("register.html", message="User already exists")

            users_table.put_item(Item={
                "email": email,
                "name": name,
                "password": password,
                "logins": Decimal(0)
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
    
    try:
        # Fetch User's Bookings
        response = bookings_table.scan(FilterExpression=Attr("email").eq(email))
        bookings = response.get("Items", [])
        
        # Fetch User's Name
        user_resp = users_table.get_item(Key={"email": email})
        user_name = user_resp.get("Item", {}).get("name", "User")

        return render_template("dashboard.html", name=user_name, bookings=bookings)
    except Exception as e:
        print(f"Dashboard Error: {e}")
        return "Internal Server Error", 500

# ==========================================
# ADMIN BACKEND
# ==========================================

@app.route("/admin")
def admin_portal():
    if not is_admin(): return redirect("/login")
    return render_template("admin_dashboard.html")

@app.route("/admin/add_transport", methods=["POST"])
def add_transport():
    if not is_admin(): return redirect("/")

    try:
        service_id = str(uuid.uuid4())[:8]
        category = request.form["category"] 
        item = {
            "service_id": service_id,
            "category": category,
            "name": request.form["name"],
            "source": request.form["source"].strip(),
            "destination": request.form["destination"].strip(),
            "price": Decimal(str(request.form["price"])),
            "details": request.form["details"]
        }
        services_table.put_item(Item=item)
        flash(f"{category.title()} added successfully!")
    except Exception as e:
        flash(f"Error adding transport: {e}")
    return redirect("/admin")

@app.route("/admin/add_hotel", methods=["POST"])
def add_hotel():
    if not is_admin(): return redirect("/")

    try:
        service_id = str(uuid.uuid4())[:8]
        item = {
            "service_id": service_id,
            "category": "hotel",
            "name": request.form["name"],
            "location": request.form["location"].strip(),
            "price": Decimal(str(request.form["price"])),
            "details": request.form["details"]
        }
        services_table.put_item(Item=item)
        flash("Hotel added successfully!")
    except Exception as e:
        flash(f"Error adding hotel: {e}")
    return redirect("/admin")

# ==========================================
# SEARCH LOGIC
# ==========================================

def search_services(category, source=None, destination=None, location=None):
    try:
        if category == "hotel":
            response = services_table.scan(
                FilterExpression=Attr("category").eq("hotel") & Attr("location").eq(location)
            )
        else:
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
        s = request.form.get("source", "").strip()
        d = request.form.get("destination", "").strip()
        results = search_services("bus", source=s, destination=d)
    return render_template("bus.html", buses=results)

@app.route("/train", methods=["GET", "POST"])
def train():
    results = None
    if request.method == "POST":
        s = request.form.get("source", "").strip()
        d = request.form.get("destination", "").strip()
        results = search_services("train", source=s, destination=d)
    return render_template("train.html", trains=results)

@app.route("/flight", methods=["GET", "POST"])
def flight():
    results = None
    if request.method == "POST":
        s = request.form.get("source", "").strip()
        d = request.form.get("destination", "").strip()
        results = search_services("flight", source=s, destination=d)
    return render_template("flight.html", flights=results)

@app.route("/hotels", methods=["GET", "POST"])
def hotels():
    results = None
    if request.method == "POST":
        city = request.form.get("city", "").strip()
        results = search_services("hotel", location=city)
    return render_template("hotels.html", hotels=results)

# ==========================================
# BOOKING FLOW
# ==========================================

@app.route("/book", methods=["POST"])
def book():
    if "user" not in session: return redirect("/login")
    
    # Cast price to string then Decimal to avoid precision float errors
    price_val = request.form.get("price", "0")
    
    session["pending_booking"] = {
        "booking_id": str(uuid.uuid4())[:8],
        "email": session["user"], 
        "type": request.form.get("type", "Service"),
        "source": request.form.get("source", "N/A"),
        "destination": request.form.get("destination", "N/A"),
        "date": request.form.get("date", "N/A"),
        "details": request.form.get("details", "N/A"),
        "price": price_val 
    }

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
    
    seats = request.form.get("selected_seats", "None")
    session["pending_booking"]["details"] += f" | Seats: {seats}"
    # Re-save to session to ensure details update
    session.modified = True
    return render_template("payment.html", booking=session["pending_booking"])

@app.route("/payment", methods=["POST"])
def payment():
    if "pending_booking" not in session: return redirect("/")
    
    booking = session.pop("pending_booking")
    booking["payment_reference"] = request.form.get("reference", "N/A")
    booking["payment_method"] = request.form.get("method", "Card")
    # Convert price back to Decimal for DynamoDB storage
    booking["price"] = Decimal(str(booking["price"]))
    
    try:
        bookings_table.put_item(Item=booking)
    except Exception as e:
        print(f"Booking Save Error: {e}")
        return f"Error saving booking: {e}"
    
    return redirect("/dashboard")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    # Use debug=True locally to see the exact line causing any errors
    app.run(host="0.0.0.0", port=5000, debug=True)
