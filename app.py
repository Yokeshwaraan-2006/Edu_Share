import os
import smtplib
import random
import mysql.connector
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from email.mime.text import MIMEText
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

otp_store = {}

db_config = {
    'host': 'localhost',
    'user': 'root',         
    'password': '1234', 
    'database': 'edushare'
}

def get_db_connection():
    return mysql.connector.connect(**db_config)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

GMAIL = "edushare.2026@gmail.com"
APP_PASSWORD = "qsqg ytvp zluy fpke"

# --- AUTH ROUTES ---

@app.route("/send-otp", methods=["POST"])
def send_otp():
    email = request.json.get("email")
    otp = str(random.randint(100000, 999999))
    otp_store[email] = otp
    try:
        msg = MIMEText(f"Your EduShare Verification Code is: {otp}")
        msg["Subject"], msg["From"], msg["To"] = "EduShare OTP", GMAIL, email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL, APP_PASSWORD)
            server.send_message(msg)
        return jsonify({"message": "OTP sent successfully!"})
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route("/verify-otp", methods=["POST"])
def verify_otp():
    data = request.json
    if otp_store.get(data.get("email")) == data.get("otp"):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            query = """INSERT INTO users (name, email, password, role, department, semester) 
                       VALUES (%s, %s, %s, %s, %s, %s)"""
            cursor.execute(query, (data['name'], data['email'], data['password'], 
                                   data['role'], data['department'], data['semester']))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"status": "verified"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
    return jsonify({"status": "invalid"})

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT user_id, name, email, role FROM users WHERE email = %s AND password = %s"
        cursor.execute(query, (data['email'], data['password']))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user:
            return jsonify({
                "message": "success", 
                "user_id": user['user_id'], 
                "name": user['name'], 
                "role": user['role']
            })
        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- LEADERBOARD & TRACKING ---

@app.route("/get-leaderboard", methods=["GET"])
def get_leaderboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Fetching from the VIEW. RANK() is handled by MySQL.
        # Added u.role filter to ensure only students appear.
        query = """
            SELECT l.* FROM leader_board l
            JOIN users u ON l.user_id = u.user_id
            WHERE u.role = 'student'
            ORDER BY l.rank_position ASC
            LIMIT 10
        """
        cursor.execute(query)
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/track-download/<int:resource_id>", methods=["POST"])
def track_download(resource_id):
    # This route now inserts into 'downloads' table. 
    # Your leader_board VIEW will update automatically.
    data = request.json
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({"error": "User ID required"}), 400

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO downloads (user_id, resource_id) VALUES (%s, %s)"
        cursor.execute(query, (user_id, resource_id))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- RESOURCE ROUTES ---

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files.get('file')
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(save_path)
        db_path = f"static/uploads/{filename}"
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            query = """INSERT INTO resources (title, description, course_name, semester, file_url, file_type, uploaded_by)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)"""
            cursor.execute(query, (request.form['title'], request.form['description'], 
                                   request.form['course_name'], request.form['semester'], 
                                   db_path, filename.split('.')[-1], request.form['user_id']))
            conn.commit()
            cursor.close()
            conn.close()
            return jsonify({"message": "Uploaded!"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Invalid file"}), 400

@app.route("/get-resources", methods=["GET"])
def get_resources():
    search = request.args.get('search', '')
    semester = request.args.get('semester', '')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """SELECT r.*, u.name as uploader_name, IFNULL(AVG(ra.rating), 0) as average_rating 
                   FROM resources r 
                   JOIN users u ON r.uploaded_by = u.user_id 
                   LEFT JOIN ratings ra ON r.resource_id = ra.resource_id
                   WHERE 1=1"""
        params = []
        if search:
            query += " AND (r.title LIKE %s OR r.course_name LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])
        if semester:
            query += " AND r.semester = %s"
            params.append(semester)
        
        query += " GROUP BY r.resource_id ORDER BY r.uploaded_date DESC"
        cursor.execute(query, params)
        data = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/rate-resource", methods=["POST"])
def rate_resource():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO ratings (user_id, resource_id, rating) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE rating = VALUES(rating)"
        cursor.execute(query, (data['user_id'], data['resource_id'], data['rating']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Rating saved"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- FEEDBACK & VERIFICATION ---

@app.route("/add-comment", methods=["POST"])
def add_comment():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO comments (resource_id, faculty_id, comment_text, comment_type) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (data['resource_id'], data['faculty_id'], data['text'], data['type']))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Comment added"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get-comments/<int:resource_id>", methods=["GET"])
def get_comments(resource_id):
    viewer_id = request.args.get('user_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """SELECT c.*, u.name as faculty_name FROM comments c
                   JOIN users u ON c.faculty_id = u.user_id
                   JOIN resources r ON c.resource_id = r.resource_id
                   WHERE c.resource_id = %s AND (c.comment_type = 'public' OR r.uploaded_by = %s OR u.role = 'faculty')"""
        cursor.execute(query, (resource_id, viewer_id))
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return jsonify(result)
    except Exception as e:
        return jsonify([])

@app.route("/delete-resource/<int:resource_id>", methods=["DELETE"])
def delete_resource(resource_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM resources WHERE resource_id = %s", (resource_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/verify-resource/<int:resource_id>", methods=["POST"])
def verify_resource(resource_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE resources SET is_verified = TRUE WHERE resource_id = %s", (resource_id,))
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"message": "Resource Verified"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/")
def home():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)