from flask import Flask, render_template, request, redirect, session, url_for, make_response, jsonify
import sqlite3, re
import pdfkit
from datetime import datetime
from twilio.rest import Client
import qrcode
import io
import base64
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import request, jsonify
import os
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = "hackathon_secret"

DB = "hackathon.db"

# Load .env file
load_dotenv()

# ---------- Twilio configuration ----------
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER") 

# ---------- DATABASE INITIALIZATION ----------
def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    roll TEXT,
                    dept TEXT,
                    email TEXT,
                    parent_mobile TEXT,
                    password TEXT,
                    role TEXT
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS leaves(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_name TEXT,
                    roll TEXT,
                    dept TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    reason TEXT,
                    tutor TEXT,
                    status TEXT DEFAULT 'Pending',
                    qr_code TEXT
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS notifications(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    dept TEXT,
                    roll TEXT,
                    message TEXT,
                    is_read INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )''')
    conn.commit()
    conn.close()

init_db()

# ---------- DATABASE CONNECTION HELPER ----------
def get_conn():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ---------- Twilio SMS helper ----------
def send_sms(to_number, message):
    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        msg = client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        print(f"SMS sent successfully! SID: {msg.sid}, Status: {msg.status}")
        return msg.status
    except Exception as e:
        print(f"Error sending SMS: {e}")
        return None

# ---------- QR Code helper ----------
def generate_qr_code(student_name, roll, dept, start_date, end_date, reason, tutor):
    qr_text = (
        f"Student Name: {student_name}\n"
        f"Roll Number: {roll}\n"
        f"Department: {dept}\n"
        f"Leave Start: {start_date}\n"
        f"Leave End: {end_date}\n"
        f"Reason: {reason}\n"
        f"Approved by Tutor: {tutor}\n"
    )
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return img_base64

# ---------- Notification helper ----------
def add_notification(role, dept, message, roll=None):
    conn = get_conn(); c = conn.cursor()
    c.execute("INSERT INTO notifications (role, dept, roll, message) VALUES (?, ?, ?, ?)", (role, dept, roll, message))
    conn.commit()
    conn.close()

# ---------- ROUTES ----------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/f_page/<action>")
def f_page(action):
    return render_template("f_page.html", action=action)

# ---------- REGISTER ----------
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role")
        name = request.form.get("name").strip()
        dept = request.form.get("dept").strip()
        email = request.form.get("email").strip()
        password = request.form.get("password")
        roll = request.form.get("roll", "").strip() if role == "student" else None
        parent_mobile = request.form.get("parent_mobile") if role == "student" else None

        if parent_mobile and not parent_mobile.startswith("+91"):
            parent_mobile = "+91" + parent_mobile.strip().replace(" ", "")

        # ---------- VALIDATIONS ----------
        if role == "student":
            if not re.match(r"^7181\d{7}$", roll):
                return "Invalid Roll Number! Must start with 7181 and total 11 digits."
            if not re.match(r"^\+91[6-9]\d{9}$", parent_mobile):
                return "Invalid Parent Mobile Number! Must include +91 and 10-digit mobile starting with 6-9."

        if role in ["tutor","ac"]:
            if not email.endswith("@srec.ac.in"):
                return "Email must end with @srec.ac.in"

        if not re.match(r"^(?=.*[A-Z])(?=.*[a-z])(?=.*\d)(?=.*\W).{8,}$", password):
            return "Weak Password! Must have uppercase, lowercase, digit, special char, min 8 chars."

        # Insert into DB
        conn = get_conn()
        c = conn.cursor()
        c.execute("INSERT INTO users(name, roll, dept, email, parent_mobile, password, role) VALUES(?,?,?,?,?,?,?)",
                  (name, roll, dept, email, parent_mobile, password, role))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

    return render_template("register.html")

# ---------- LOGIN ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        role = request.form.get("role")
        password = request.form.get("password")
        
        if role == "student":
            roll = request.form.get("roll").strip()
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT * FROM users WHERE roll=? AND password=? AND role='student'", (roll,password))
            user = c.fetchone()
            conn.close()
            if user:
                session["user"] = dict(user)
                return redirect(url_for("student_dashboard"))
            return "Invalid Student Login!"

        elif role == "tutor":
            email = request.form.get("email").strip()
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT * FROM users WHERE email=? AND password=? AND role='tutor'", (email,password))
            user = c.fetchone()
            conn.close()
            if user:
                session["user"] = dict(user)
                return redirect(url_for("tutor_dashboard"))
            return "Invalid Tutor Login!"

        elif role == "ac":
            email = request.form.get("email").strip()
            conn = get_conn(); c = conn.cursor()
            c.execute("SELECT * FROM users WHERE email=? AND password=? AND role='ac'", (email,password))
            user = c.fetchone()
            conn.close()
            if user:
                session["user"] = dict(user)
                return redirect(url_for("ac_dashboard"))
            return "Invalid AC Login!"

        elif role == "admin":
            username = request.form.get("email").strip()
            if username=="admin" and password=="admin@123":
                session["admin"] = True
                return redirect(url_for("admin"))
            return "Invalid Admin Login!"

    return render_template("login.html")

# ---------- STUDENT DASHBOARD ----------
@app.route("/student_dashboard")
def student_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    user = session["user"]
    roll = user['roll']
    conn = get_conn(); c = conn.cursor()

    # Leaves
    c.execute("SELECT * FROM leaves WHERE roll=? ORDER BY id DESC", (roll,))
    leaves = c.fetchall()

    # Notifications
    c.execute("SELECT * FROM notifications WHERE role='student' AND roll=? AND is_read=0 ORDER BY created_at DESC LIMIT 10", (roll,))
    notifications = c.fetchall()

    # Mark as read
    c.execute("UPDATE notifications SET is_read=1 WHERE role='student' AND roll=? AND is_read=0", (roll,))
    conn.commit()

    # --- NEW: Pie Chart Data ---
    c.execute("""
        SELECT 
            SUM(CASE WHEN status = 'Approved by AC' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN status = 'Rejected by AC' THEN 1 ELSE 0 END) AS rejected,
            SUM(CASE WHEN status IN ('Pending', 'Tutor Approved') THEN 1 ELSE 0 END) AS pending
        FROM leaves WHERE roll=?
    """, (roll,))
    pie_counts = c.fetchone()
    approved_count = pie_counts['approved'] or 0
    rejected_count = pie_counts['rejected'] or 0
    pending_count = pie_counts['pending'] or 0

    # --- NEW: Monthly Trend Data ---
    monthly_counts = [0] * 12
    c.execute("""
        SELECT strftime('%m', start_date) AS month, COUNT(*) AS count
        FROM leaves WHERE roll=? AND start_date IS NOT NULL
        GROUP BY month ORDER BY month
    """, (roll,))
    monthly_rows = c.fetchall()
    for row in monthly_rows:
        month_num = int(row['month'])
        if 1 <= month_num <= 12:
            monthly_counts[month_num - 1] = row['count']

    jan_leaves, feb_leaves, mar_leaves, apr_leaves, may_leaves, jun_leaves = monthly_counts[0:6]
    jul_leaves, aug_leaves, sep_leaves, oct_leaves, nov_leaves, dec_leaves = monthly_counts[6:12]

    # --- NEW: Day-of-Week Heatmap Data (Sun=0 to Sat=6) ---
    day_counts = [0] * 7  # [Sun, Mon, Tue, Wed, Thu, Fri, Sat]
    c.execute("""
        SELECT strftime('%w', start_date) AS day_of_week, COUNT(*) AS count
        FROM leaves WHERE roll=? AND status != 'Pending'
        GROUP BY day_of_week ORDER BY day_of_week
    """, (roll,))
    day_rows = c.fetchall()
    for row in day_rows:
        day_index = int(row['day_of_week'])  # 0=Sunday, 1=Monday, ..., 6=Saturday
        if 0 <= day_index <= 6:
            day_counts[day_index] = row['count']

    # Generate QR for approved leaves
    leaves_with_qr = []
    for l in leaves:
        leave_dict = dict(l)
        if leave_dict['status'] == "Approved by AC" and not leave_dict.get('qr_code'):
            leave_dict['qr_code'] = generate_qr_code(
                leave_dict['student_name'],
                leave_dict['roll'],
                leave_dict['dept'],
                leave_dict['start_date'],
                leave_dict['end_date'],
                leave_dict['reason'],
                leave_dict['tutor'],
            )
            c.execute("UPDATE leaves SET qr_code=? WHERE id=?", (leave_dict['qr_code'], leave_dict['id']))
            conn.commit()
        leaves_with_qr.append(leave_dict)

    conn.close()

    return render_template("student_dashboard.html", 
        leaves=leaves_with_qr, 
        notifications=notifications,
        approved_count=approved_count,
        rejected_count=rejected_count,
        pending_count=pending_count,
        jan_leaves=jan_leaves,
        feb_leaves=feb_leaves,
        mar_leaves=mar_leaves,
        apr_leaves=apr_leaves,
        may_leaves=may_leaves,
        jun_leaves=jun_leaves,
        jul_leaves=jul_leaves,
        aug_leaves=aug_leaves,
        sep_leaves=sep_leaves,
        oct_leaves=oct_leaves,
        nov_leaves=nov_leaves,
        dec_leaves=dec_leaves,
        day_counts=day_counts  # 👈 Passed to template for heatmap
    )

# ---------- APPLY LEAVE ----------
@app.route("/apply_leave", methods=["GET","POST"])
def apply_leave():
    if "user" not in session:
        return redirect(url_for("login"))
    student = session["user"]

    if request.method == "POST":
        start = request.form.get("start")
        end = request.form.get("end")
        reason = request.form.get("reason").strip()
        tutor = request.form.get("tutor").strip()

        conn = get_conn(); c = conn.cursor()
        c.execute("INSERT INTO leaves(student_name, roll, dept, start_date, end_date, reason, tutor) VALUES(?,?,?,?,?,?,?)",
                  (student['name'], student['roll'], student['dept'], start, end, reason, tutor))
        conn.commit()
        conn.close()

        # SMS to parent
        parent_number = student['parent_mobile']
        sms_message = f"""Dear Parent,
Your child {student['name']} (Roll: {student['roll']}, Dept: {student['dept']}) has applied for leave.
Start Date: {start}
End Date: {end}
Reason: {reason}
Tutor: {tutor}
Status: Pending
- SREC Leave Management System"""
        send_sms(parent_number, sms_message)

        # Notification for tutor
        add_notification("tutor", student['dept'], f"Student {student['name']} applied for leave")

        return redirect(url_for("student_dashboard"))

    # Fetch tutors
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT name FROM users WHERE role=? AND dept=?", ("tutor", student['dept']))
    tutors = c.fetchall()
    conn.close()

    return render_template("apply_leave.html", student=student, tutors=tutors)

# ---------- TUTOR DASHBOARD ----------
@app.route("/tutor_dashboard")
def tutor_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    tutor = session["user"]
    tutor_name = tutor["name"]
    dept = tutor["dept"]

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM leaves WHERE tutor=? ORDER BY id DESC", (tutor_name,))
    leaves = c.fetchall()

    # Notifications
    c.execute("SELECT * FROM notifications WHERE role='tutor' AND dept=? AND is_read=0 ORDER BY created_at DESC LIMIT 10", (dept,))
    notifications = c.fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE role='tutor' AND dept=? AND is_read=0", (dept,))
    conn.commit()

    # --- NEW: Sankey Diagram Data ---
    applied_count = len(leaves)
    tutor_approved_count = sum(1 for l in leaves if l['status'] == 'Tutor Approved')
    ac_approved_count = sum(1 for l in leaves if l['status'] == 'Approved by AC')
    rejected_count = sum(1 for l in leaves if l['status'] == 'Rejected')
    max_flow = max(applied_count, tutor_approved_count, ac_approved_count, rejected_count) or 1

    # ✅ FIXED: Approval Percentage (Protected Against Zero Division)
    if applied_count > 0 and tutor_approved_count > 0:
        approved_percent = round((ac_approved_count / tutor_approved_count) * 100, 1)
    else:
        approved_percent = 0.0

    # --- NEW: Leaderboard — Top 3 Students by Total Applications ---
    from collections import defaultdict
    student_counts = defaultdict(int)
    student_roll_map = {}  # To map name → roll

    for l in leaves:
        student_name = l['student_name']
        student_counts[student_name] += 1
        student_roll_map[student_name] = l['roll']  # Use first occurrence of roll

    # Sort by count descending, take top 3
    top_students_applied = sorted(
        [
            {
                'name': name,
                'roll': student_roll_map[name],
                'count': count
            }
            for name, count in student_counts.items()
        ],
        key=lambda x: x['count'],
        reverse=True
    )[:3]

    conn.close()

    return render_template("tutor_dashboard.html",
        tutor=tutor,
        leaves=leaves,
        notifications=notifications,
        applied_count=applied_count,
        tutor_approved_count=tutor_approved_count,
        ac_approved_count=ac_approved_count,
        rejected_count=rejected_count,
        max_flow=max_flow,
        top_students_applied=top_students_applied,
        approved_percent=approved_percent  # ✅ NEW SAFE PERCENTAGE
    )

# ---------- UPDATE LEAVE BY TUTOR ----------
@app.route("/update_leave/<int:leave_id>/<action>")
def update_leave(leave_id, action):
    if "user" not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Not logged in"), 401
        return redirect(url_for("login"))

    new_status = "Tutor Approved" if action.lower()=="approve" else "Rejected" if action.lower()=="reject" else None
    if not new_status:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Invalid action"), 400
        return "Invalid action!", 400

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM leaves WHERE id=?", (leave_id,))
    leave = c.fetchone()
    if not leave:
        conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Leave not found"), 404
        return "Leave not found!", 404
        
    leave_dict = dict(leave)

    c.execute("UPDATE leaves SET status=? WHERE id=?", (new_status, leave_id))
    conn.commit(); conn.close()

    # Send SMS
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT parent_mobile FROM users WHERE roll=?", (leave_dict['roll'],))
    student_data = c.fetchone(); conn.close()

    if student_data:
        send_sms(student_data['parent_mobile'], f"Your child {leave_dict['student_name']} leave has been {new_status}.")

    # Notifications
    if new_status == "Tutor Approved":
        add_notification("ac", leave_dict['dept'], f"Tutor {leave_dict['tutor']} approved {leave_dict['student_name']}'s leave")
    elif new_status == "Rejected":
        add_notification("student", leave_dict['dept'], f"Tutor {leave_dict['tutor']} rejected your leave", leave_dict['roll'])

    # Return JSON for AJAX requests, redirect for normal browser requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message="Leave updated successfully")
    return redirect(url_for("tutor_dashboard"))

# ---------- AC DASHBOARD ----------
@app.route("/ac_dashboard")
def ac_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    ac = session["user"]
    dept = ac["dept"]

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT name FROM users WHERE role=? AND dept=?", ("tutor", dept))
    tutors = c.fetchall()

    c.execute("SELECT * FROM leaves WHERE dept=? ORDER BY id DESC", (dept,))
    leaves = c.fetchall()

    # --- NEW: Tutor Comparison Data ---
    tutor_names = [t['name'] for t in tutors]
    tutor_approved = []
    tutor_rejected = []
    tutor_pending = []

    for tutor in tutor_names:
        c.execute("""
            SELECT 
                SUM(CASE WHEN status = 'Tutor Approved' THEN 1 ELSE 0 END) AS approved,
                SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) AS rejected,
                SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) AS pending
            FROM leaves WHERE tutor = ?
        """, (tutor,))
        result = c.fetchone()
        tutor_approved.append(result['approved'] or 0)
        tutor_rejected.append(result['rejected'] or 0)
        tutor_pending.append(result['pending'] or 0)

    # --- NEW: Top Students ---
    from collections import defaultdict
    student_counts = defaultdict(int)
    for l in leaves:
        student_counts[l['student_name']] += 1

    top_students = sorted(
        [{'name': name, 'count': count} for name, count in student_counts.items()],
        key=lambda x: x['count'],
        reverse=True
    )[:5]  # Top 5

    student_labels = [s['name'] for s in top_students]
    student_counts_list = [s['count'] for s in top_students]

    # --- NEW: Approval Performance ---
    ac_approved = sum(1 for l in leaves if l['status'] == 'Approved by AC')
    ac_rejected = sum(1 for l in leaves if l['status'] == 'Rejected by AC')
    ac_pending = sum(1 for l in leaves if l['status'] == 'Pending')

    tutor_approved_total = sum(tutor_approved)
    tutor_rejected_total = sum(tutor_rejected)
    tutor_pending_total = sum(tutor_pending)

    # Notifications
    c.execute("SELECT * FROM notifications WHERE role='ac' AND dept=? AND is_read=0 ORDER BY created_at DESC LIMIT 10", (dept,))
    notifications = c.fetchall()
    c.execute("UPDATE notifications SET is_read=1 WHERE role='ac' AND dept=? AND is_read=0", (dept,))
    conn.commit(); conn.close()

    return render_template("ac_dashboard.html",
        ac=ac,
        tutors=tutors,
        leaves=leaves,
        notifications=notifications,

        # Tutor Comparison
        tutor_labels=tutor_names,
        tutor_approved=tutor_approved,
        tutor_rejected=tutor_rejected,
        tutor_pending=tutor_pending,

        # Top Students
        student_labels=student_labels,
        student_counts=student_counts_list,

        # Approval Performance
        ac_approved_count=ac_approved,
        ac_rejected_count=ac_rejected,
        ac_pending_count=ac_pending,
        tutor_approved_count=tutor_approved_total,
        tutor_rejected_count=tutor_rejected_total,
        tutor_pending_count=tutor_pending_total
    )

# ---------- UPDATE LEAVE BY AC ----------
@app.route("/ac_update_leave/<int:leave_id>/<action>")
def ac_update_leave(leave_id, action):
    if "user" not in session:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Not logged in"), 401
        return redirect(url_for("login"))

    new_status = "Approved by AC" if action.lower()=="approve" else "Rejected by AC" if action.lower()=="reject" else None
    if not new_status:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Invalid action"), 400
        return "Invalid action!", 400

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM leaves WHERE id=?", (leave_id,))
    leave = c.fetchone()
    if not leave:
        conn.close()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify(success=False, message="Leave not found"), 404
        return "Leave not found!", 404
    leave_dict = dict(leave)

    c.execute("UPDATE leaves SET status=? WHERE id=?", (new_status, leave_id)); conn.commit()

    # QR for approved
    if new_status == "Approved by AC":
        qr_code = generate_qr_code(
            leave_dict['student_name'],
            leave_dict['roll'],
            leave_dict['dept'],
            leave_dict['start_date'],
            leave_dict['end_date'],
            leave_dict['reason'],
            leave_dict['tutor']
        )
        c.execute("UPDATE leaves SET qr_code=? WHERE id=?", (qr_code, leave_id)); conn.commit()

    # Send SMS
    c.execute("SELECT parent_mobile FROM users WHERE roll=?", (leave_dict['roll'],))
    student_data = c.fetchone(); conn.close()
    if student_data:
        send_sms(student_data['parent_mobile'], f"Your child {leave_dict['student_name']} leave has been {new_status}.")

    # Notifications
    if new_status == "Approved by AC":
        add_notification("student", leave_dict['dept'], "AC approved your leave", leave_dict['roll'])
    elif new_status == "Rejected by AC":
        add_notification("student", leave_dict['dept'], "AC rejected your leave", leave_dict['roll'])

    # Return JSON for AJAX requests, redirect for normal browser requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(success=True, message="Leave updated successfully")
    return redirect(url_for("ac_dashboard"))

# ---------- ADMIN DASHBOARD ----------
@app.route("/admin")
def admin():
    if "admin" not in session:
        return redirect(url_for("login"))
    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM users"); users = c.fetchall()
    c.execute("SELECT * FROM leaves ORDER BY id DESC"); leaves = c.fetchall()

    # --- NEW: User Role Distribution ---
    role_counts = {'student': 0, 'tutor': 0, 'ac': 0}
    dept_role_stats = {}

    for u in users:
        role_counts[u['role']] += 1

        dept = u['dept']
        if dept not in dept_role_stats:
            dept_role_stats[dept] = {'students': 0, 'tutors': 0, 'acs': 0, 'total': 0}
        dept_role_stats[dept][u['role'] + 's'] += 1
        dept_role_stats[dept]['total'] += 1

    # Policy Alert: Detect ratio > 1:50
    policy_alert = None
    for dept, stats in dept_role_stats.items():
        if stats['tutors'] > 0 and stats['students'] / stats['tutors'] > 50:
            policy_alert = f"{dept} Dept: {stats['students']} Students, {stats['tutors']} Tutor → Ratio {stats['students']}/{stats['tutors']} (exceeds 1:50 policy)."

    role_labels = list(role_counts.keys())
    role_counts_list = list(role_counts.values())

    # --- NEW: Department-wise Leave Statistics ---
    dept_leave_counts = {}
    for l in leaves:
        dept = l['dept']
        dept_leave_counts[dept] = dept_leave_counts.get(dept, 0) + 1

    dept_labels = list(dept_leave_counts.keys())
    dept_leave_counts_list = list(dept_leave_counts.values())

    # --- NEW: Institutional Monthly Trend ---
    monthly_trend = [0] * 12
    for l in leaves:
        try:
            month = int(l['start_date'].split('-')[1]) - 1  # Convert "2024-03-15" → 2 → index 2
            if 0 <= month <= 11:
                monthly_trend[month] += 1
        except:
            continue

    conn.close()

    return render_template("admin.html",
        users=users,
        leaves=leaves,
        role_labels=role_labels,
        role_counts=role_counts_list,
        dept_role_stats=dept_role_stats,
        policy_alert=policy_alert,
        dept_labels=dept_labels,
        dept_leave_counts=dept_leave_counts_list,
        monthly_trend=monthly_trend
    )

# ---------- DOWNLOAD LEAVE LETTER PDF ----------
# ---------- DOWNLOAD LEAVE LETTER PDF ----------
@app.route("/download_leave_letter/<int:leave_id>")
def download_leave_letter(leave_id):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_conn(); c = conn.cursor()
    c.execute("SELECT * FROM leaves WHERE id=?", (leave_id,))
    leave = c.fetchone(); conn.close()
    if not leave: return "Leave not found", 404

    leave_dict = dict(leave)
    current_date = datetime.now().strftime("%d-%m-%Y")
    rendered_html = render_template("leave_letter.html", leave=leave_dict, current_date=current_date)

    # ✅ FIXED: Enable local file access to load images
    config = pdfkit.configuration(wkhtmltopdf=r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe")
    options = {
        'enable-local-file-access': None,  # 👈 CRITICAL FIX
        'margin-top': '0.75in',
        'margin-right': '0.75in',
        'margin-bottom': '0.75in',
        'margin-left': '0.75in',
        'encoding': "UTF-8",
        'no-stop-slow-scripts': None
    }

    pdf = pdfkit.from_string(rendered_html, False, configuration=config, options=options)

    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=leave_letter_{leave_dict["roll"]}.pdf'
    return response

# ---------- LOGOUT ----------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# --- EMAIL CONFIGURATION ---
ADMIN_EMAIL = "ruthishkumarg@gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")    # ← Replace with sender email
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")      # ← Replace with App Password (NOT account password)

@app.route("/message", methods=["GET"])
def message():
    return render_template("message.html")

@app.route("/send_message", methods=["POST"])
def send_message():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    message_text = request.form.get("message", "").strip()

    if not email.endswith("@srec.ac.in"):
        return jsonify(success=False, message="Email must end with @srec.ac.in")

    if not name or not message_text:
        return jsonify(success=False, message="All fields are required.")

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = ADMIN_EMAIL
        msg['Subject'] = f"New Query from {name} ({email})"

        body = f"""
New Message from SREC Leave System:

Name: {name}
Email: {email}

Message:
{message_text}
        """
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        text = msg.as_string()
        server.sendmail(EMAIL_USER, ADMIN_EMAIL, text)
        server.quit()

        return jsonify(success=True, message="Thank you! Your message has been sent successfully.")
    
    except Exception as e:
        print(f"Error sending email: {e}")
        return jsonify(success=False, message=f"Failed to send message. Error: {str(e)}")

# ------------------ MAIN ------------------
if __name__ == '__main_ _':
    app.run(host='0.0.0.0', port=5000, debug=True)