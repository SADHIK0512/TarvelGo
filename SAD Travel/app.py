from flask import Flask, render_template, request, redirect, session, flash, url_for
import uuid
import boto3
from boto3.dynamodb.conditions import Attr, Key
from decimal import Decimal
import os

# ==========================================
# APP SETUP
# ==========================================
app = Flask(__name__)
app.secret_key = "travelgo_secret"

# ==========================================
# AWS SETUP
# ==========================================
AWS_REGION = "ap-south-1" # Ensure this matches your AWS Console Region

# DynamoDB Table Names (Ensure these match your AWS Console EXACTLY)
TABLE_USERS = "travel-Users"
TABLE_BOOKINGS = "Bookings"        
TABLE_SERVICES = "TravelServices"

try:
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    users_table = dynamodb.Table(TABLE_USERS)
    bookings_table = dynamodb.Table(TABLE_BOOKINGS)
    services_table = dynamodb.Table(TABLE_SERVICES)
except Exception as e:
    print(f"AWS Configuration Error: {e}")

# ==========================================
# ADMIN CREDENTIALS
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

        # Admin Login Check
        if email == ADMIN_EMAIL and password == ADMIN_PASSWORD:
            session["user"] = email
            return redirect(url_for('admin_portal'))

        # User Login Check
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
                return redirect(url_for('dashboard'))
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
            # Check if user exists
            if "Item" in users_table.get_item(Key={"email": email}):
                return render_template("login.html", error="User already exists. Please Login.")

            users_table.put_item(Item={
                "email": email,
                "name": name,
                "password": password,
                "logins": Decimal(0)
            })
            return redirect(url_for('login'))
        except Exception as e:
            return render_template("register.html", message=f"Error: {e}")

    return render_template("index.html") # Redirecting to home/login context if GET

# --- DASHBOARD ---
@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect(url_for('login'))
    if is_admin(): return redirect(url_for('admin_portal'))

    email = session["user"]
    
    try:
        # Fetch User's Bookings - Using FilterExpression (Scan)
        response = bookings_table.scan(FilterExpression=Attr("email").eq(email))
        bookings = response.get("Items", [])
        
        # Fetch User's Name
        user_resp = users_table.get_item(Key={"email": email})
        user_name = user_resp.get("Item", {}).get("name", "Traveler")

        return render_template("dashboard.html", name=user_name, bookings=bookings)
    except Exception as e:
        print(f"Dashboard Error: {e}")
        return f"Error loading dashboard: {e}"

# --- PRINT TICKET (Fixed Missing Route) ---
@app.route("/print_ticket/<booking_id>")
def print_ticket(booking_id):
    if "user" not in session: return redirect(url_for('login'))
    
    try:
        # Try to get item directly if booking_id is Primary Key
        response = bookings_table.get_item(Key={'booking_id': booking_id})
        booking = response.get('Item')

        # Fallback: Scan if booking_id is not the primary key in your table
        if not booking:
            response = bookings_table.scan(FilterExpression=Attr('booking_id').eq(booking_id))
            items = response.get('Items', [])
            if items:
                booking = items[0]

        if booking:
            return render_template("ticket.html", booking=booking)
        else:
            return "Ticket not found.", 404
            
    except Exception as e:
        print(f"Ticket Fetch Error: {e}")
        return f"Error fetching ticket: {e}"

# ==========================================
# ADMIN BACKEND
# ==========================================

@app.route("/admin")
def admin_portal():
    if not is_admin(): return redirect(url_for('login'))
    return render_template("admin_dashboard.html")

@app.route("/admin/add_transport", methods=["POST"])
def add_transport():
    if not is_admin(): return redirect(url_for('home'))

    try:
        service_id = str(uuid.uuid4())[:8]
        # Normalize inputs: Source/Dest -> Title Case, Category -> lowercase
        category = request.form["category"].lower() 
        name = request.form["name"]
        source = request.form["source"].strip().title()
        destination = request.form["destination"].strip().title()
        price = Decimal(str(request.form["price"]))
        details = request.form["details"]

        item = {
            "service_id": service_id,
            "category": category,
            "name": name,
            "source": source,
            "destination": destination,
            "price": price,
            "details": details
        }
        services_table.put_item(Item=item)
        flash(f"{category.title()} added successfully!")
    except Exception as e:
        print(f"Admin Add Error: {e}") # Print to console for debugging
        flash(f"Error adding transport: {e}")
    
    return redirect(url_for('admin_portal'))

@app.route("/admin/add_hotel", methods=["POST"])
def add_hotel():
    if not is_admin(): return redirect(url_for('home'))

    try:
        service_id = str(uuid.uuid4())[:8]
        name = request.form["name"]
        location = request.form["location"].strip().title()
        price = Decimal(str(request.form["price"]))
        details = request.form["details"]

        item = {
            "service_id": service_id,
            "category": "hotel",
            "name": name,
            "location": location,
            "price": price,
            "details": details
        }
        services_table.put_item(Item=item)
        flash("Hotel added successfully!")
    except Exception as e:
        print(f"Admin Hotel Error: {e}")
        flash(f"Error adding hotel: {e}")
    
    return redirect(url_for('admin_portal'))

# ==========================================
# SEARCH LOGIC
# ==========================================

def search_services(category, source=None, destination=None, location=None):
    try:
        if category == "hotel":
            # Search Hotels by City (Location)
            response = services_table.scan(
                FilterExpression=Attr("category").eq("hotel") & Attr("location").eq(location.title())
            )
        else:
            # Search Transport (Bus/Train/Flight)
            # Using .title() to match "Mumbai" even if user types "mumbai"
            response = services_table.scan(
                FilterExpression=Attr("category").eq(category) & 
                                 Attr("source").eq(source.title()) & 
                                 Attr("destination").eq(destination.title())
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
    return render_template("bus.html", buses=results, source=request.form.get("source"), destination=request.form.get("destination"))

@app.route("/train", methods=["GET", "POST"])
def train():
    results = None
    if request.method == "POST":
        s = request.form.get("source", "").strip()
        d = request.form.get("destination", "").strip()
        results = search_services("train", source=s, destination=d)
    return render_template("train.html", trains=results, source=request.form.get("source"), destination=request.form.get("destination"))

@app.route("/flight", methods=["GET", "POST"])
def flight():
    results = None
    if request.method == "POST":
        s = request.form.get("source", "").strip()
        d = request.form.get("destination", "").strip()
        results = search_services("flight", source=s, destination=d)
    return render_template("flight.html", flights=results, source=request.form.get("source"), destination=request.form.get("destination"))

@app.route("/hotels", methods=["GET", "POST"])
def hotels():
    results = None
    city_searched = ""
    if request.method == "POST":
        city_searched = request.form.get("city", "").strip()
        results = search_services("hotel", location=city_searched)
    return render_template("hotels.html", hotels=results, city=city_searched)

# ==========================================
# BOOKING FLOW (FIXED)
# ==========================================

@app.route("/book", methods=["POST"])
def book():
    if "user" not in session: return redirect(url_for('login'))
    
    # Capture form data
    booking_type = request.form.get("type", "Service")
    price_val = request.form.get("price", "0")
    
    session["pending_booking"] = {
        "booking_id": str(uuid.uuid4())[:8],
        "email": session["user"], 
        "type": booking_type,
        "source": request.form.get("source", "N/A"),
        "destination": request.form.get("destination", "N/A"),
        "date": request.form.get("date", "N/A"),
        "details": request.form.get("details", "N/A"),
        "price": price_val 
    }
    session.modified = True # Important: Force session save

    # Redirect to seat selection for Transport
    # Ensure "Bus", "Train", "Flight" match the values in your HTML hidden inputs
    if booking_type in ["Bus", "Train", "Flight"]:
        return redirect(url_for('select_seats'))
        
    # Skip seats for Hotels
    return render_template("payment.html", booking=session["pending_booking"])

@app.route("/select_seats")
def select_seats():
    if "user" not in session: return redirect(url_for('login'))
    if "pending_booking" not in session: return redirect(url_for('home'))
    return render_template("select_seats.html")

@app.route("/confirm_seats", methods=["POST"])
def confirm_seats():
    if "pending_booking" not in session: return redirect(url_for('home'))
    
    seats = request.form.get("selected_seats", "None")
    
    # Append seat info to details
    session["pending_booking"]["details"] += f" | Seats: {seats}"
    session.modified = True # Important: Force session save
    
    return render_template("payment.html", booking=session["pending_booking"])

@app.route("/payment", methods=["POST"])
def payment():
    if "pending_booking" not in session: return redirect(url_for('home'))
    
    # Retrieve booking from session
    booking = session.pop("pending_booking")
    
    # Add payment details
    booking["payment_reference"] = request.form.get("reference", "N/A")
    booking["payment_method"] = request.form.get("method", "Card")
    booking["price"] = Decimal(str(booking["price"])) # Convert to Decimal for DynamoDB
    
    try:
        bookings_table.put_item(Item=booking)
        print("Booking saved successfully")
    except Exception as e:
        print(f"Booking Save Error: {e}")
        return f"Error saving booking to database: {e}"
    
    return redirect(url_for('dashboard'))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
