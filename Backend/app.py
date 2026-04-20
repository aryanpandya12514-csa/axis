from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime, timedelta
from twilio.rest import Client
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, decode_token
import random
import os
from dotenv import load_dotenv
import requests
import math
import uuid
import cloudinary
import cloudinary.uploader
from werkzeug.utils import secure_filename
from pipeline import UnifiedPipeline

citysync_pipeline = UnifiedPipeline()

# ✅ FIX: load_dotenv() MUST come before any os.getenv() calls
load_dotenv()

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

app = Flask(__name__)
CORS(app)

app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)

jwt = JWTManager(app)


# =========================
# HELPERS
# =========================

def upload_image(file):
    result = cloudinary.uploader.upload(file)
    return result["secure_url"]

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def verify_token(req):
    """Extract and decode token from request headers. Returns (phone, error_response)."""
    token_header = req.headers.get('token')
    if not token_header:
        auth_header = req.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token_header = auth_header.split(' ')[1]
    if not token_header:
        return None, (jsonify({"message": "Access Denied. No token provided"}), 401)
    try:
        decoded = decode_token(token_header)
        return decoded.get("sub"), None
    except Exception:
        return None, (jsonify({"message": "Invalid or expired token"}), 401)

def verify_admin_token(req):
    """Verify token is an admin token. Returns (is_admin, error_response)."""
    identity, err = verify_token(req)
    if err:
        return False, err
    if identity != "admin":
        return False, (jsonify({"message": "Unauthorized. Admin access only"}), 403)
    return True, None


# =========================
# JWT ERROR HANDLERS
# =========================

@jwt.unauthorized_loader
def unauthorized_callback(callback):
    return jsonify({"message": "Token missing"}), 401

@jwt.invalid_token_loader
def invalid_token_callback(callback):
    return jsonify({"message": "Invalid token"}), 401

@jwt.expired_token_loader
def expired_token_callback(jwt_header, jwt_payload):
    return jsonify({"message": "Token expired"}), 401


# =========================
# MONGODB CONNECTION
# =========================
mongo_client = MongoClient(os.getenv("MONGO_URI"))
db = mongo_client["otp_auth_db"]
users = db["users"]
complaints = db["complaints"]


def send_sms(phone, otp):
    try:
        twilio_client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN")
        )
        message = twilio_client.messages.create(
            body=f"Your CitySync OTP is {otp}. Valid for 5 minutes.",
            from_=os.getenv("TWILIO_PHONE_NUMBER"),
            to="+91" + phone
        )
        print("SMS SENT:", message.sid)
        return True
    except Exception as e:
        print("TWILIO ERROR:", e)
        return False


# =========================
# AUTH ROUTES
# =========================

@app.route('/send-otp', methods=['POST'])
def send_otp():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    phone = str(data.get('phone', ''))
    if not phone or not phone.isdigit() or len(phone) != 10:
        return jsonify({"message": "Invalid phone"}), 400

    otp = str(random.randint(100000, 999999))
    print("OTP:", otp)

    db["otps"].update_one(
        {"phone": phone},
        {"$set": {"otp": otp, "created_at": datetime.utcnow()}},
        upsert=True
    )

    success = send_sms(phone, otp)
    if not success:
        return jsonify({"message": "SMS failed"}), 500

    return jsonify({"message": "OTP sent"}), 200


@app.route('/verify-otp-signup', methods=['POST'])
def verify_otp_signup():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    name = data.get('name')
    phone = str(data.get('phone', ''))
    entered_otp = str(data.get('otp', ''))

    if not name or not phone or not entered_otp:
        return jsonify({"message": "Name, phone, and OTP required"}), 400

    otp_record = db["otps"].find_one({"phone": phone})
    if not otp_record:
        return jsonify({"message": "OTP not found or already verified"}), 400

    if datetime.utcnow() > otp_record["created_at"] + timedelta(minutes=5):
        return jsonify({"message": "OTP expired"}), 400

    if otp_record["otp"] != entered_otp:
        return jsonify({"message": "Invalid OTP"}), 401

    existing_user = users.find_one({"phone": phone})
    if existing_user:
        return jsonify({"message": "User already registered"}), 400

    users.insert_one({
        "name": name,
        "phone": phone,
        "is_verified": True,
        "created_at": datetime.utcnow()
    })

    db["otps"].delete_one({"phone": phone})
    access_token = create_access_token(identity=phone)

    return jsonify({
        "message": "Signup successful",
        "token": access_token,
        "user": {"name": name, "phone": phone}
    }), 200


@app.route('/verify-otp-login', methods=['POST'])
def verify_otp_login():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    phone = str(data.get('phone', ''))
    entered_otp = str(data.get('otp', ''))

    if not phone or not entered_otp:
        return jsonify({"message": "Phone and OTP required"}), 400

    otp_record = db["otps"].find_one({"phone": phone})
    if not otp_record:
        return jsonify({"message": "OTP not found or already verified"}), 400

    if datetime.utcnow() > otp_record["created_at"] + timedelta(minutes=5):
        return jsonify({"message": "OTP expired"}), 400

    if otp_record["otp"] != entered_otp:
        return jsonify({"message": "Invalid OTP"}), 401

    user = users.find_one({"phone": phone})
    if not user:
        return jsonify({"message": "User not registered"}), 404

    db["otps"].delete_one({"phone": phone})
    access_token = create_access_token(identity=phone)

    return jsonify({
        "message": "Login successful",
        "token": access_token,
        "user": {"name": user.get("name"), "phone": phone}
    }), 200


@app.route('/get-user', methods=['GET'])
def getuser():
    phone, err = verify_token(request)
    if err:
        return err

    user = users.find_one({"phone": phone})
    if not user:
        return jsonify({"message": "User not found"}), 404

    return jsonify({
        "message": "User successfully retrieved",
        "name": user.get("name"),
        "phone": phone
    }), 200


# =========================
# COMPLAINT ROUTES
# =========================

@app.route('/register-complaint', methods=['POST'])
def create_complaint():
    phone, err = verify_token(request)
    if err:
        return err

    text = request.form.get("text")
    ward_id_str = request.form.get("ward_id", "0")
    try:
        ward_id = int(ward_id_str)
        lat = float(request.form.get("lat", 0.0))
        lng = float(request.form.get("lng", 0.0))
    except (TypeError, ValueError):
        return jsonify({"message": "Invalid latitude, longitude, or ward_id"}), 400

    if not text:
        return jsonify({"message": "Required fields missing"}), 400

    image_file = request.files.get('image')
    image_url = None
    local_image_path = None

    if image_file:
        try:
            # Temporarily save for the AI Pipeline evaluation bound natively locally
            local_image_path = secure_filename(image_file.filename or "temp_image.jpg")
            image_file.save(local_image_path)
            # Push explicitly bounds cleanly mapping into Cloudinary remotely
            image_url = upload_image(local_image_path)
        except Exception as e:
            return jsonify({"message": f"Image processing failed: {str(e)}"}), 500

    try:
        # Pre-fetch array variables bounded dynamically for pure Python Logic AI execution
        active_masters = list(complaints.find({
            "master": None,
            "status": {"$ne": "resolved"}
        }))

        # Run AI Architecture Core Pipeline completely mapped via native Python parameters
        payload = citysync_pipeline.process_incident(
            text=text,
            image_path=local_image_path,
            lat=lat,
            lng=lng,
            ward_id=ward_id,
            active_masters=active_masters
        )
        
        c_status = payload["grouping"]
        is_clone = c_status["is_duplicate"]
        parent_group = c_status["group_id"]
        
        ctoken = payload["complaint_id"]
        
        # Serialize constraints natively inserting completely populated mapping bounds
        document = {
            "phone": phone,
            "ctoken": ctoken,
            "text": text,
            "location": {"lat": lat, "lng": lng},
            "image": image_url,
            "department": payload["classification"].get("final_result", {}).get("department", "General"),
            "status": "pending",
            "priority_label": payload["priority"].get("priority_label"),
            "priority_score": payload["priority"].get("priority_score"),
            "master": parent_group if is_clone else None,
            "report_count": 1 if not is_clone else None, # Clones don't hold the master report count
            "embedding": payload["grouping"].get("embedding", []),
            "created_at": datetime.utcnow(),
            "ai_analysis": payload
        }

        if is_clone:
            # Safely log as child, updating the native parent node securely mapping
            complaints.update_one(
                {"ctoken": parent_group},
                {"$inc": {"report_count": 1}, "$addToSet": {"supporters": phone, "children": ctoken}}
            )
            
        complaints.insert_one(document)

        return jsonify({
            "message": "Complaint successfully evaluated and registered.",
            "ctoken": ctoken,
            "is_duplicate": is_clone,
            "master_group_node": parent_group
        }), 201
        
    finally:
        # Guarantee local cleanup dynamically avoiding bloated filesystem caching
        if local_image_path and os.path.exists(local_image_path):
            os.remove(local_image_path)


@app.route('/fetch-complaints', methods=['GET'])
def get_complaints():
    """Fetch complaints for the logged-in user. Optional ?status= filter."""
    phone, err = verify_token(request)
    if err:
        return err

    query = {"phone": phone}
    status_filter = request.args.get('status')
    if status_filter in ["pending", "inprogress", "resolved"]:
        query["status"] = status_filter

    cursor = complaints.find(query).sort("created_at", -1)
    result = [{**comp, "_id": str(comp["_id"])} for comp in cursor]

    return jsonify(result), 200


@app.route('/search-complaint', methods=['POST'])
def search_complaint():
    """Search a complaint by ctoken."""
    phone, err = verify_token(request)
    if err:
        return err

    data = request.get_json()
    if not data or "ctoken" not in data:
        return jsonify({"message": "ctoken is required"}), 400

    comp = complaints.find_one({"ctoken": data.get("ctoken")})
    if not comp:
        return jsonify({"message": "Complaint not found"}), 404

    comp["_id"] = str(comp["_id"])
    return jsonify({"message": "Complaint fetched successfully", "complaint": comp}), 200


# =========================
# NEW: Fetch complaints by department (Admin)
# GET /admin/complaints?department=PWD - Public Works Department
# Optional: &status=pending|inprogress|resolved
# =========================

@app.route('/admin/complaints', methods=['GET'])
def get_complaints_by_department():
    """Admin endpoint — fetch complaints filtered by department name."""
    is_admin, err = verify_admin_token(request)
    if err:
        return err

    department = request.args.get('department')
    if not department:
        return jsonify({"message": "department query parameter is required"}), 400

    query = {"department": department}

    # Optional status filter
    status_filter = request.args.get('status')
    if status_filter in ["pending", "inprogress", "resolved"]:
        query["status"] = status_filter

    # Optional priority filter (for urgent tab)
    priority_filter = request.args.get('priority')
    if priority_filter in ["low", "medium", "high", "urgent"]:
        query["priority"] = priority_filter

    cursor = complaints.find(query).sort("created_at", -1)
    result = [{**comp, "_id": str(comp["_id"])} for comp in cursor]

    return jsonify({
        "department": department,
        "count": len(result),
        "complaints": result
    }), 200


# =========================
# NEW: Update complaint status (Admin)
# PATCH /admin/update-status
# Headers: token
# Body: { "ctoken": "CMP-xxxx", "status": "inprogress" }
# =========================

@app.route('/admin/update-status', methods=['PATCH'])
def update_complaint_status():
    """Admin endpoint — securely update cluster bounds statuses simultaneously."""
    is_admin, err = verify_admin_token(request)
    if err:
        return err

    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    group_id = data.get("group_id")
    new_status = data.get("status")

    if not group_id or not new_status:
        return jsonify({"message": "group_id and status are required"}), 400

    valid_statuses = ["pending", "inprogress", "resolved"]
    if new_status not in valid_statuses:
        return jsonify({"message": f"Invalid status. Must be one of: {valid_statuses}"}), 400

    # Syncs atomic operations across the exact master node plus every mapped clone node simultaneously.
    result = complaints.update_many(
        {"$or": [{"ctoken": group_id}, {"master": group_id}]},
        {
            "$set": {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
        }
    )

    if result.matched_count == 0:
        return jsonify({"message": "Target Group ID mapped bounds could not be found."}), 404

    return jsonify({
        "message": "Cluster status synchronized globally.",
        "group_id": group_id,
        "status": new_status,
        "records_modified": result.modified_count
    }), 200


# =========================
# ADMIN AUTH
# =========================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "citysync@2026"

@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"message": "Invalid JSON"}), 400

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400

    if username != ADMIN_USERNAME or password != ADMIN_PASSWORD:
        return jsonify({"message": "Invalid credentials"}), 401

    access_token = create_access_token(identity="admin")
    return jsonify({
        "message": "Admin login successful",
        "token": access_token
    }), 200


@app.route('/admin/verify', methods=['GET'])
def admin_verify():
    is_admin, err = verify_admin_token(request)
    if err:
        return err
    return jsonify({"message": "Admin verified"}), 200


# =========================
# RUN SERVER
# =========================
if __name__ == '__main__':
    app.run(debug=True)