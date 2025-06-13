from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash
from cs50 import SQL
from datetime import datetime, date
import os

app = Flask(__name__)

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SECRET_KEY"] = "your-secret-key-change-this"
app.config['TRAP_HTTP_EXCEPTIONS'] = True
Session(app)
# Custom error page for development
if app.debug:
    app.config['TRAP_BAD_REQUEST_ERRORS'] = True


# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///institute.db")

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_role") != 'admin':
            flash("Access denied. Admin privileges required.")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_or_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_role") not in ['admin', 'teacher']:
            flash("Access denied. Teacher or Admin privileges required.")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def can_send_messages(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_role") not in ['admin', 'teacher', 'student']:
            flash("Access denied. Please login to send messages.")
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def is_notification_read(notification, user_id, user_role):
    """Check if user has read the notification using simple string matching"""
    user_key = f"{user_role}_{user_id}"
    read_by = notification.get('read_by', '')
    return user_key in read_by.split(',') if read_by else False

def get_user_notifications(user_id, user_role, user_course=None):
    """Get notifications for a specific user based on their role and course"""
    notifications = []
    
    if user_role == 'admin':
        notifications = db.execute("""
            SELECT n.*, 
                   CASE 
                       WHEN n.created_by_role = 'admin' THEN a.name
                       WHEN n.created_by_role = 'teacher' THEN t.name
                   END as creator_name
            FROM notifications n
            LEFT JOIN admin a ON n.created_by = a.admin_id AND n.created_by_role = 'admin'
            LEFT JOIN teachers t ON n.created_by = t.teacher_id AND n.created_by_role = 'teacher'
            WHERE n.status = 'active'
            ORDER BY n.created_at DESC
        """)
        
    elif user_role == 'teacher':
        notifications = db.execute("""
            SELECT n.*, a.name as creator_name
            FROM notifications n
            JOIN admin a ON n.created_by = a.admin_id
            WHERE n.created_by_role = 'admin' 
                AND (n.target_audience = 'all' OR n.target_audience = 'all_teachers')
                AND n.status = 'active'
            ORDER BY n.created_at DESC
        """)
        
    elif user_role == 'student':
        notifications = db.execute("""
            SELECT n.*, 
                   CASE 
                       WHEN n.created_by_role = 'admin' THEN a.name
                       WHEN n.created_by_role = 'teacher' THEN t.name
                   END as creator_name
            FROM notifications n
            LEFT JOIN admin a ON n.created_by = a.admin_id AND n.created_by_role = 'admin'
            LEFT JOIN teachers t ON n.created_by = t.teacher_id AND n.created_by_role = 'teacher'
            WHERE n.status = 'active'
                AND (
                    (n.created_by_role = 'admin' AND (n.target_audience = 'all' OR n.target_audience = 'all_students'))
                    OR 
                    (n.created_by_role = 'teacher' AND n.target_audience = 'all_students')
                    OR 
                    (n.created_by_role = 'teacher' AND n.target_audience = 'specific_course' AND n.specific_course = ?)
                )
            ORDER BY n.created_at DESC
        """, user_course)
    
    for notification in notifications:
        notification['is_read'] = is_notification_read(notification, user_id, user_role)
    
    return notifications

def get_pending_accounts_count(user_role):
    """Get count of pending accounts based on user role"""
    count = 0
    try:
        if user_role == 'admin':
            student_count = db.execute("SELECT COUNT(*) as count FROM students WHERE status = 0")[0]['count']
            teacher_count = db.execute("SELECT COUNT(*) as count FROM teachers WHERE status = 0")[0]['count']
            admin_count = db.execute("SELECT COUNT(*) as count FROM admin WHERE status = 0")[0]['count']
            count = student_count + teacher_count + admin_count
        elif user_role == 'teacher':
            count = db.execute("SELECT COUNT(*) as count FROM students WHERE status = 0")[0]['count']
    except:
        count = 0
    
    return count

def get_unread_messages_count(user_id, user_role):
    """Get count of unread messages for user"""
    try:
        count = db.execute("""
            SELECT COUNT(*) as count 
            FROM messages 
            WHERE recipient_id = ? AND recipient_role = ? AND is_read = 0
        """, user_id, user_role)[0]['count']
        return count
    except:
        return 0

def calculate_grade(percentage):
    """Calculate grade based on percentage"""
    if percentage >= 90: return 'A+'
    elif percentage >= 85: return 'A'
    elif percentage >= 80: return 'A-'
    elif percentage >= 75: return 'B+'
    elif percentage >= 70: return 'B'
    elif percentage >= 65: return 'B-'
    elif percentage >= 60: return 'C+'
    elif percentage >= 55: return 'C'
    elif percentage >= 50: return 'C-'
    elif percentage >= 45: return 'D'
    else: return 'F'

def update_course_result(student_id, course_name):
    """Calculate and update final course result based on all assessments"""
    try:
        # Get all graded assessments for this student in this course
        assessments_data = db.execute("""
            SELECT a.weightage, g.percentage, a.assessment_type
            FROM assessments a
            JOIN grades g ON a.assessment_id = g.assessment_id
            WHERE g.student_id = ? AND a.course_name = ? AND a.status = 'active'
        """, student_id, course_name)
        
        if not assessments_data:
            return
        
        # Calculate weighted average
        total_weightage = sum(item['weightage'] for item in assessments_data)
        if total_weightage == 0:
            return
        
        weighted_score = sum(item['percentage'] * item['weightage'] for item in assessments_data)
        final_percentage = weighted_score / total_weightage
        final_grade = calculate_grade(final_percentage)
        status = 'Pass' if final_percentage >= 50 else 'Fail'
        
        # Update or insert course result
        db.execute("""
            INSERT OR REPLACE INTO course_results 
            (student_id, course_name, total_weightage, obtained_weightage, 
             final_percentage, final_grade, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, student_id, course_name, total_weightage, weighted_score, 
             final_percentage, final_grade, status)
        
    except Exception as e:
        print(f"Error updating course result: {str(e)}")

@app.context_processor
def inject_global_vars():
    """Inject variables that should be available in all templates"""
    if session.get("user_id") and session.get("user_role"):
        user_role = session.get("user_role")
        user_id = session.get("user_id")
        pending_count = get_pending_accounts_count(user_role)
        unread_messages_count = get_unread_messages_count(user_id, user_role)
        return {
            'pending_accounts_count': pending_count,
            'unread_messages_count': unread_messages_count,
            'user_role': user_role,
            'user_name': session.get("user_name"),
            'user_id': session.get("user_id"),
            'current_date': date.today().strftime('%Y-%m-%d')
        }
    return {
        'pending_accounts_count': 0,
        'unread_messages_count': 0,
        'current_date': date.today().strftime('%Y-%m-%d')
    }

@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

@app.route('/')
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("start"))

@app.route('/start')
def start():
    return render_template('start.html')

@app.route('/login')
def login():
    role = request.args.get('role', '')
    return render_template('login.html', role=role)

@app.route('/login', methods=['POST'])
def login_post():
    try:
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role')

        if not email or not password or not role:
            flash("All fields are required")
            return redirect(url_for('login', role=role))

        user = None
        if role == 'student':
            users = db.execute("SELECT * FROM students WHERE email = ?", email)
            if users and check_password_hash(users[0]['password'], password):
                if users[0]['status'] == 0:
                    flash("Account pending approval. Please contact admin or teacher.")
                    return redirect(url_for('login', role=role))
                user = users[0]
                user['role'] = 'student'
                user['id'] = user['student_id']

        elif role == 'teacher':
            users = db.execute("SELECT * FROM teachers WHERE email = ?", email)
            if users and check_password_hash(users[0]['password'], password):
                if users[0]['status'] == 0:
                    flash("Account pending approval. Please contact admin.")
                    return redirect(url_for('login', role=role))
                user = users[0]
                user['role'] = 'teacher'
                user['id'] = user['teacher_id']

        elif role == 'admin':
            users = db.execute("SELECT * FROM admin WHERE email = ?", email)
            if users and check_password_hash(users[0]['password'], password):
                if users[0]['status'] == 0:
                    flash("Account pending approval. Please contact another admin.")
                    return redirect(url_for('login', role=role))
                user = users[0]
                user['role'] = 'admin'
                user['id'] = user['admin_id']

        if user:
            session["user_id"] = user['id']
            session["user_role"] = user['role']
            session["user_name"] = user['name']
            if user['role'] == 'student':
                session["user_course"] = user.get('course', '')
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid email or password")
            return redirect(url_for('login', role=role))

    except Exception as e:
        print(f"Login error: {str(e)}")
        flash("An error occurred during login. Please try again.")
        return redirect(url_for('login', role=role))

@app.route('/register')
def register():
    role = request.args.get('role', '')
    courses = []
    if role == 'student':
        try:
            courses = db.execute("SELECT * FROM courses")
        except:
            courses = []
    return render_template('register.html', role=role, courses=courses)

@app.route('/register', methods=['POST'])
def register_post():
    try:
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '').strip()
        role = request.form.get('role', '')

        if not all([first_name, last_name, email, password, confirm_password, phone, role]):
            flash("All fields are required")
            return redirect(url_for('register', role=role))

        if password != confirm_password:
            flash("Passwords do not match")
            return redirect(url_for('register', role=role))

        if len(password) < 6:
            flash("Password must be at least 6 characters long")
            return redirect(url_for('register', role=role))

        existing_users = []
        try:
            existing_users.extend(db.execute("SELECT email FROM students WHERE email = ?", email))
            existing_users.extend(db.execute("SELECT email FROM teachers WHERE email = ?", email))
            existing_users.extend(db.execute("SELECT email FROM admin WHERE email = ?", email))
        except Exception as e:
            print(f"Error checking existing users: {str(e)}")

        if existing_users:
            flash("Email already registered")
            return redirect(url_for('register', role=role))

        hashed_password = generate_password_hash(password)
        full_name = f"{first_name} {last_name}"
        
        if role == 'student':
            course = request.form.get('course', '').strip()
            dob = request.form.get('dob', '').strip()
            gender = request.form.get('gender', '').strip()
            
            # Get parent details
            parent_name = request.form.get('parent_name', '').strip()
            parent_phone = request.form.get('parent_phone', '').strip()
            parent_email = request.form.get('parent_email', '').strip()
            parent_occupation = request.form.get('parent_occupation', '').strip()
            emergency_contact = request.form.get('emergency_contact', '').strip()
            
            # Validate required fields
            if not all([course, dob, gender, parent_name, parent_phone]):
                flash("Please fill all required fields including parent/guardian information.")
                return redirect(url_for('register', role=role))

            # Insert student with parent details
            db.execute("""
                INSERT INTO students (name, email, password, phone, course, dob, gender, 
                                    parent_name, parent_phone, parent_email, parent_occupation, 
                                    emergency_contact, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """, full_name, email, hashed_password, phone, course, dob, gender,
                 parent_name, parent_phone, parent_email, parent_occupation, emergency_contact)
            
            flash("Student registration successful! Please wait for approval from admin or teacher.")
            
        elif role == 'teacher':
            subject = request.form.get('subject', '').strip()
            
            db.execute("""
                INSERT INTO teachers (name, email, password, phone, subject, status)
                VALUES (?, ?, ?, ?, ?, 0)
            """, full_name, email, hashed_password, phone, subject)
            
            flash("Teacher registration successful! Please wait for admin approval.")

        elif role == 'admin':
            db.execute("""
                INSERT INTO admin (name, email, password, phone, status)
                VALUES (?, ?, ?, ?, 0)
            """, full_name, email, hashed_password, phone)
            
            flash("Admin registration successful! Please wait for approval from another admin.")

        return redirect(url_for('login', role=role))

    except Exception as e:
        print(f"Registration error: {str(e)}")
        flash(f"Registration failed: {str(e)}")
        return redirect(url_for('register', role=role or ''))

@app.route('/dashboard')
@login_required
def dashboard():
    user_role = session.get("user_role")
    user_name = session.get("user_name")
    user_id = session.get("user_id")
    user_course = session.get("user_course", None)
    
    notifications = get_user_notifications(user_id, user_role, user_course)
    unread_count = len([n for n in notifications if not n['is_read']])
    
    # Get recent messages
    recent_messages = db.execute("""
        SELECT m.*, 
               CASE 
                   WHEN m.sender_role = 'admin' THEN a.name
                   WHEN m.sender_role = 'teacher' THEN t.name
               END as sender_name
        FROM messages m
        LEFT JOIN admin a ON m.sender_id = a.admin_id AND m.sender_role = 'admin'
        LEFT JOIN teachers t ON m.sender_id = t.teacher_id AND m.sender_role = 'teacher'
        WHERE m.recipient_id = ? AND m.recipient_role = ?
        ORDER BY m.sent_at DESC
        LIMIT 5
    """, user_id, user_role)
    
    # Get dashboard statistics
    stats = {}
    try:
        if user_role == 'admin':
            stats['total_students'] = db.execute("SELECT COUNT(*) as count FROM students WHERE status = 1")[0]['count']
            stats['total_teachers'] = db.execute("SELECT COUNT(*) as count FROM teachers WHERE status = 1")[0]['count']
            stats['total_courses'] = db.execute("SELECT COUNT(*) as count FROM courses")[0]['count']
            stats['pending_approvals'] = get_pending_accounts_count(user_role)
        elif user_role == 'teacher':
            stats['my_students'] = db.execute("SELECT COUNT(*) as count FROM students WHERE status = 1")[0]['count']
            stats['my_courses'] = db.execute("SELECT COUNT(*) as count FROM courses WHERE teacher_id = ?", user_id)[0]['count']
            stats['assessments'] = db.execute("SELECT COUNT(*) as count FROM assessments WHERE teacher_id = ?", user_id)[0]['count']
            stats['pending_approvals'] = get_pending_accounts_count(user_role)
        elif user_role == 'student':
            # Get student's attendance percentage
            attendance_data = db.execute("""
                SELECT COUNT(*) as total, 
                       SUM(CASE WHEN status = 'present' THEN 1 ELSE 0 END) as present
                FROM attendance WHERE student_id = ?
            """, user_id)
            if attendance_data[0]['total'] > 0:
                stats['attendance'] = round((attendance_data[0]['present'] / attendance_data[0]['total']) * 100, 1)
            else:
                stats['attendance'] = 0
            
            # Get average grade
            avg_result = db.execute("""
                SELECT AVG(final_percentage) as avg_percentage
                FROM course_results WHERE student_id = ?
            """, user_id)
            if avg_result[0]['avg_percentage']:
                stats['avg_percentage'] = round(avg_result[0]['avg_percentage'], 1)
                stats['avg_grade'] = calculate_grade(stats['avg_percentage'])
            else:
                stats['avg_percentage'] = 0
                stats['avg_grade'] = 'N/A'
    except Exception as e:
        print(f"Error loading dashboard stats: {str(e)}")
        stats = {}
    
    return render_template('dashboard.html', 
                         role=user_role, 
                         name=user_name,
                         notifications=notifications,
                         unread_count=unread_count,
                         recent_messages=recent_messages,
                         stats=stats)

# MESSAGING ROUTES
@app.route('/messages')
@login_required
def messages():
    """View all messages for the current user"""
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    try:
        # Get received messages
        received_messages = db.execute("""
            SELECT m.*, 
                   CASE 
                       WHEN m.sender_role = 'admin' THEN a.name
                       WHEN m.sender_role = 'teacher' THEN t.name
                   END as sender_name
            FROM messages m
            LEFT JOIN admin a ON m.sender_id = a.admin_id AND m.sender_role = 'admin'
            LEFT JOIN teachers t ON m.sender_id = t.teacher_id AND m.sender_role = 'teacher'
            WHERE m.recipient_id = ? AND m.recipient_role = ?
            ORDER BY m.sent_at DESC
        """, user_id, user_role)
        
        # Get sent messages (only for teachers and admins)
        sent_messages = []
        if user_role in ['admin', 'teacher']:
            sent_messages = db.execute("""
                SELECT m.*, 
                       CASE 
                           WHEN m.recipient_role = 'admin' THEN a.name
                           WHEN m.recipient_role = 'teacher' THEN t.name
                           WHEN m.recipient_role = 'student' THEN s.name
                       END as recipient_name
                FROM messages m
                LEFT JOIN admin a ON m.recipient_id = a.admin_id AND m.recipient_role = 'admin'
                LEFT JOIN teachers t ON m.recipient_id = t.teacher_id AND m.recipient_role = 'teacher'
                LEFT JOIN students s ON m.recipient_id = s.student_id AND m.recipient_role = 'student'
                WHERE m.sender_id = ? AND m.sender_role = ?
                ORDER BY m.sent_at DESC
            """, user_id, user_role)
        
    except Exception as e:
        print(f"Error loading messages: {str(e)}")
        received_messages = []
        sent_messages = []
    
    return render_template('messages.html',
                         received_messages=received_messages,
                         sent_messages=sent_messages,
                         user_role=user_role)

@app.route('/compose_message')
@can_send_messages
def compose_message():
    """Compose a new message (Teachers, Admins, and Students)"""
    user_role = session.get("user_role")
    
    try:
        # Get potential recipients based on user role
        recipients = []
        
        if user_role == 'admin':
            # Admins can message teachers and students
            teachers = db.execute("SELECT teacher_id as id, name, 'teacher' as role FROM teachers WHERE status = 1")
            students = db.execute("SELECT student_id as id, name, 'student' as role FROM students WHERE status = 1")
            recipients = teachers + students
            
        elif user_role == 'teacher':
            # Teachers can message admins, other teachers, and students
            admins = db.execute("SELECT admin_id as id, name, 'admin' as role FROM admin WHERE status = 1")
            teachers = db.execute("SELECT teacher_id as id, name, 'teacher' as role FROM teachers WHERE status = 1 AND teacher_id != ?", session.get("user_id"))
            students = db.execute("SELECT student_id as id, name, 'student' as role FROM students WHERE status = 1")
            recipients = admins + teachers + students
            
        elif user_role == 'student':
            # Students can only message admins and teachers
            admins = db.execute("SELECT admin_id as id, name, 'admin' as role FROM admin WHERE status = 1")
            teachers = db.execute("SELECT teacher_id as id, name, 'teacher' as role FROM teachers WHERE status = 1")
            recipients = admins + teachers
            
    except Exception as e:
        print(f"Error loading recipients: {str(e)}")
        recipients = []
    
    return render_template('compose_message.html', recipients=recipients)

@app.route('/send_message', methods=['POST'])
@can_send_messages
def send_message():
    """Send a message"""
    try:
        sender_id = session.get("user_id")
        sender_role = session.get("user_role")
        recipient_info = request.form.get('recipient', '').split('|')
        
        if len(recipient_info) != 2:
            flash("Please select a valid recipient.")
            return redirect(url_for('compose_message'))
        
        recipient_id = int(recipient_info[0])
        recipient_role = recipient_info[1]
        subject = request.form.get('subject', '').strip()
        message_body = request.form.get('message_body', '').strip()
        
        if not subject or not message_body:
            flash("Subject and message are required.")
            return redirect(url_for('compose_message'))
        
        # Updated messaging rules validation
        if sender_role == 'teacher' and recipient_role not in ['admin', 'teacher', 'student']:
            flash("Teachers can only message admins, other teachers, or students.")
            return redirect(url_for('compose_message'))
        
        if sender_role == 'admin' and recipient_role not in ['teacher', 'student']:
            flash("Admins can only message teachers or students.")
            return redirect(url_for('compose_message'))
        
        if sender_role == 'student' and recipient_role not in ['admin', 'teacher']:
            flash("Students can only message admins or teachers.")
            return redirect(url_for('compose_message'))
        
        # Prevent students from messaging other students
        if sender_role == 'student' and recipient_role == 'student':
            flash("Students cannot message other students.")
            return redirect(url_for('compose_message'))
        
        # Insert message
        db.execute("""
            INSERT INTO messages (sender_id, sender_role, recipient_id, recipient_role, subject, message_body)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sender_id, sender_role, recipient_id, recipient_role, subject, message_body)
        
        flash("Message sent successfully!")
        return redirect(url_for('messages'))
        
    except Exception as e:
        print(f"Error sending message: {str(e)}")
        flash("Error sending message. Please try again.")
        return redirect(url_for('compose_message'))

@app.route('/read_message/<int:message_id>')
@login_required
def read_message(message_id):
    """Mark message as read and view details"""
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    try:
        # Get message details
        message = db.execute("""
            SELECT m.*, 
                   CASE 
                       WHEN m.sender_role = 'admin' THEN a.name
                       WHEN m.sender_role = 'teacher' THEN t.name
                   END as sender_name
            FROM messages m
            LEFT JOIN admin a ON m.sender_id = a.admin_id AND m.sender_role = 'admin'
            LEFT JOIN teachers t ON m.sender_id = t.teacher_id AND m.sender_role = 'teacher'
            WHERE m.message_id = ? AND m.recipient_id = ? AND m.recipient_role = ?
        """, message_id, user_id, user_role)
        
        if not message:
            flash("Message not found.")
            return redirect(url_for('messages'))
        
        message = message[0]
        
        # Mark as read if not already read
        if not message['is_read']:
            db.execute("""
                UPDATE messages 
                SET is_read = 1, read_at = CURRENT_TIMESTAMP 
                WHERE message_id = ?
            """, message_id)
        
    except Exception as e:
        print(f"Error reading message: {str(e)}")
        flash("Error loading message.")
        return redirect(url_for('messages'))
    
    return render_template('read_message.html', message=message)

@app.route('/reply_message/<int:message_id>')
@can_send_messages
def reply_message(message_id):
    """Reply to a message"""
    user_id = session.get("user_id")
    user_role = session.get("user_role")
    
    try:
        # Get original message
        original_message = db.execute("""
            SELECT m.*, 
                   CASE 
                       WHEN m.sender_role = 'admin' THEN a.name
                       WHEN m.sender_role = 'teacher' THEN t.name
                   END as sender_name
            FROM messages m
            LEFT JOIN admin a ON m.sender_id = a.admin_id AND m.sender_role = 'admin'
            LEFT JOIN teachers t ON m.sender_id = t.teacher_id AND m.sender_role = 'teacher'
            WHERE m.message_id = ? AND m.recipient_id = ? AND m.recipient_role = ?
        """, message_id, user_id, user_role)
        
        if not original_message:
            flash("Message not found.")
            return redirect(url_for('messages'))
        
        original_message = original_message[0]
        
    except Exception as e:
        print(f"Error loading message for reply: {str(e)}")
        flash("Error loading message.")
        return redirect(url_for('messages'))
    
    return render_template('reply_message.html', original_message=original_message)

@app.route('/send_reply', methods=['POST'])
@can_send_messages
def send_reply():
    """Send a reply message"""
    try:
        sender_id = session.get("user_id")
        sender_role = session.get("user_role")
        original_message_id = int(request.form.get('original_message_id'))
        recipient_id = int(request.form.get('recipient_id'))
        recipient_role = request.form.get('recipient_role')
        subject = request.form.get('subject', '').strip()
        message_body = request.form.get('message_body', '').strip()
        
        if not subject or not message_body:
            flash("Subject and message are required.")
            return redirect(url_for('reply_message', message_id=original_message_id))
        
        # Insert reply message
        db.execute("""
            INSERT INTO messages (sender_id, sender_role, recipient_id, recipient_role, subject, message_body)
            VALUES (?, ?, ?, ?, ?, ?)
        """, sender_id, sender_role, recipient_id, recipient_role, subject, message_body)
        
        flash("Reply sent successfully!")
        return redirect(url_for('messages'))
        
    except Exception as e:
        print(f"Error sending reply: {str(e)}")
        flash("Error sending reply. Please try again.")
        return redirect(url_for('messages'))

# ATTENDANCE ROUTES
@app.route('/attendance')
@login_required
def attendance():
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    user_course = session.get("user_course", '')
    
    selected_date = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    selected_course = request.args.get('course', '')
    
    courses = []
    students = []
    attendance_records = []
    
    try:
        # Get available courses
        courses = db.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name")
        
        if user_role == 'teacher':
            # Teachers can mark attendance for any course
            if selected_course:
                students = db.execute("""
                    SELECT student_id, name, course, email 
                    FROM students 
                    WHERE course = ? AND status = 1 
                    ORDER BY name
                """, selected_course)
        elif user_role == 'admin':
            # Admins can mark attendance for any course
            if selected_course:
                students = db.execute("""
                    SELECT student_id, name, course, email 
                    FROM students 
                    WHERE course = ? AND status = 1 
                    ORDER BY name
                """, selected_course)
        elif user_role == 'student':
            # Students can only VIEW their attendance, not mark it
            selected_course = user_course
            # No students list for marking - students cannot mark attendance
        
        # Get existing attendance records for the selected date and course
        if selected_course:
            if user_role == 'student':
                # Students can only see their own attendance
                attendance_records = db.execute("""
                    SELECT a.*, s.name as student_name,
                           CASE 
                               WHEN a.marked_by_role = 'teacher' THEN t.name
                               WHEN a.marked_by_role = 'admin' THEN ad.name
                           END as marked_by_name
                    FROM attendance a
                    JOIN students s ON a.student_id = s.student_id
                    LEFT JOIN teachers t ON a.marked_by = t.teacher_id AND a.marked_by_role = 'teacher'
                    LEFT JOIN admin ad ON a.marked_by = ad.admin_id AND a.marked_by_role = 'admin'
                    WHERE a.date = ? AND a.course_name = ? AND a.student_id = ?
                    ORDER BY s.name
                """, selected_date, selected_course, user_id)
            else:
                # Teachers and admins can see all attendance for the course
                attendance_records = db.execute("""
                    SELECT a.*, s.name as student_name,
                           CASE 
                               WHEN a.marked_by_role = 'teacher' THEN t.name
                               WHEN a.marked_by_role = 'admin' THEN ad.name
                           END as marked_by_name
                    FROM attendance a
                    JOIN students s ON a.student_id = s.student_id
                    LEFT JOIN teachers t ON a.marked_by = t.teacher_id AND a.marked_by_role = 'teacher'
                    LEFT JOIN admin ad ON a.marked_by = ad.admin_id AND a.marked_by_role = 'admin'
                    WHERE a.date = ? AND a.course_name = ?
                    ORDER BY s.name
                """, selected_date, selected_course)
    
    except Exception as e:
        print(f"Error loading attendance data: {str(e)}")
        flash("Error loading attendance data.")
    
    return render_template('attendance.html',
                         courses=courses,
                         students=students,
                         attendance_records=attendance_records,
                         selected_date=selected_date,
                         selected_course=selected_course,
                         user_role=user_role)

@app.route('/mark_attendance', methods=['POST'])
@teacher_or_admin_required  # This decorator already prevents students
def mark_attendance():
    try:
        user_id = session.get("user_id")
        user_role = session.get("user_role")
        
        # Additional check to ensure students cannot mark attendance
        if user_role == 'student':
            flash("Students are not authorized to mark attendance.")
            return redirect(url_for('attendance'))
        
        attendance_date = request.form.get('date')
        course_name = request.form.get('course')
        student_id = request.form.get('student_id')
        status = request.form.get('status')
        
        if not all([attendance_date, course_name, student_id, status]):
            flash("All fields are required for marking attendance.")
            return redirect(url_for('attendance', date=attendance_date, course=course_name))
        
        # Check if attendance already exists
        existing = db.execute("""
            SELECT * FROM attendance 
            WHERE student_id = ? AND course_name = ? AND date = ?
        """, student_id, course_name, attendance_date)
        
        if existing:
            # Update existing attendance
            db.execute("""
                UPDATE attendance 
                SET status = ?, marked_by = ?, marked_by_role = ?, marked_at = CURRENT_TIMESTAMP
                WHERE student_id = ? AND course_name = ? AND date = ?
            """, status, user_id, user_role, student_id, course_name, attendance_date)
            flash("Attendance updated successfully!")
        else:
            # Insert new attendance record
            db.execute("""
                INSERT INTO attendance (student_id, course_name, date, status, marked_by, marked_by_role)
                VALUES (?, ?, ?, ?, ?, ?)
            """, student_id, course_name, attendance_date, status, user_id, user_role)
            flash("Attendance marked successfully!")
        
        return redirect(url_for('attendance', date=attendance_date, course=course_name))
        
    except Exception as e:
        print(f"Mark attendance error: {str(e)}")
        flash("Error marking attendance. Please try again.")
        return redirect(url_for('attendance'))

@app.route('/attendance_report')
@login_required
def attendance_report():
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    user_course = session.get("user_course", '')
    
    # Get filter parameters
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    course_filter = request.args.get('course', '')
    student_filter = request.args.get('student', '')
    
    courses = []
    students = []
    attendance_data = []
    
    try:
        # Get available courses based on user role
        if user_role in ['admin', 'teacher']:
            courses = db.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name")
            if course_filter:
                students = db.execute("""
                    SELECT student_id, name FROM students 
                    WHERE course = ? AND status = 1 ORDER BY name
                """, course_filter)
        else:  # student
            courses = [{'course_name': user_course}]
            course_filter = user_course
            students = [{'student_id': user_id, 'name': session.get('user_name')}]
        
        # Build attendance report query
        query = """
            SELECT a.*, s.name as student_name, s.course,
                   CASE 
                       WHEN a.marked_by_role = 'teacher' THEN t.name
                       WHEN a.marked_by_role = 'admin' THEN ad.name
                   END as marked_by_name
            FROM attendance a
            JOIN students s ON a.student_id = s.student_id
            LEFT JOIN teachers t ON a.marked_by = t.teacher_id AND a.marked_by_role = 'teacher'
            LEFT JOIN admin ad ON a.marked_by = ad.admin_id AND a.marked_by_role = 'admin'
            WHERE 1=1
        """
        
        params = []
        
        if start_date:
            query += " AND a.date >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND a.date <= ?"
            params.append(end_date)
        
        if course_filter:
            query += " AND a.course_name = ?"
            params.append(course_filter)
        
        if student_filter:
            query += " AND a.student_id = ?"
            params.append(student_filter)
        
        if user_role == 'student':
            query += " AND a.student_id = ?"
            params.append(user_id)
        
        query += " ORDER BY a.date DESC, s.name"
        
        attendance_data = db.execute(query, *params)
        
    except Exception as e:
        print(f"Error generating attendance report: {str(e)}")
        flash("Error generating attendance report.")
    
    return render_template('attendance_report.html',
                         courses=courses,
                         students=students,
                         attendance_data=attendance_data,
                         start_date=start_date,
                         end_date=end_date,
                         course_filter=course_filter,
                         student_filter=student_filter,
                         user_role=user_role)

# MODERN GRADING SYSTEM ROUTES
@app.route('/assessments')
@teacher_or_admin_required
def assessments():
    """Modern assessment management dashboard"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    try:
        # Get courses based on user role
        if user_role == 'teacher':
            courses = db.execute("SELECT DISTINCT course_name FROM courses WHERE teacher_id = ?", user_id)
        else:  # admin
            courses = db.execute("SELECT DISTINCT course_name FROM courses")
        
        # Get recent assessments
        if user_role == 'teacher':
            recent_assessments = db.execute("""
                SELECT a.*, t.name as teacher_name,
                       COUNT(g.grade_id) as graded_count,
                       (SELECT COUNT(*) FROM students s WHERE s.course = a.course_name AND s.status = 1) as total_students
                FROM assessments a
                LEFT JOIN teachers t ON a.teacher_id = t.teacher_id
                LEFT JOIN grades g ON a.assessment_id = g.assessment_id
                WHERE a.status = 'active' AND a.teacher_id = ?
                GROUP BY a.assessment_id
                ORDER BY a.created_at DESC
                LIMIT 10
            """, user_id)
        else:
            recent_assessments = db.execute("""
                SELECT a.*, t.name as teacher_name,
                       COUNT(g.grade_id) as graded_count,
                       (SELECT COUNT(*) FROM students s WHERE s.course = a.course_name AND s.status = 1) as total_students
                FROM assessments a
                LEFT JOIN teachers t ON a.teacher_id = t.teacher_id
                LEFT JOIN grades g ON a.assessment_id = g.assessment_id
                WHERE a.status = 'active'
                GROUP BY a.assessment_id
                ORDER BY a.created_at DESC
                LIMIT 10
            """)
        
    except Exception as e:
        print(f"Error loading assessments: {str(e)}")
        courses = []
        recent_assessments = []
    
    return render_template('assessments.html',
                         courses=courses,
                         recent_assessments=recent_assessments,
                         user_role=user_role)

@app.route('/create_assessment')
@teacher_or_admin_required
def create_assessment():
    """Create new assessment"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    try:
        if user_role == 'teacher':
            courses = db.execute("SELECT DISTINCT course_name FROM courses WHERE teacher_id = ?", user_id)
        else:
            courses = db.execute("SELECT DISTINCT course_name FROM courses")
    except:
        courses = []
    
    assessment_types = ['Quiz', 'Assignment', 'Midterm', 'Final Exam', 'Project', 'Presentation', 'Lab Work']
    
    return render_template('create_assessment.html',
                         courses=courses,
                         assessment_types=assessment_types)

@app.route('/create_assessment', methods=['POST'])
@teacher_or_admin_required
def create_assessment_post():
    """Handle assessment creation"""
    try:
        course_name = request.form.get('course_name')
        assessment_name = request.form.get('assessment_name')
        assessment_type = request.form.get('assessment_type')
        total_marks = int(request.form.get('total_marks'))
        weightage = float(request.form.get('weightage'))
        assessment_date = request.form.get('assessment_date')
        description = request.form.get('description', '')
        teacher_id = session.get("user_id")
        
        if not all([course_name, assessment_name, assessment_type, total_marks, weightage, assessment_date]):
            flash("All required fields must be filled")
            return redirect(url_for('create_assessment'))
        
        if total_marks <= 0 or weightage <= 0:
            flash("Total marks and weightage must be positive")
            return redirect(url_for('create_assessment'))
        
        # Create assessment
        db.execute("""
            INSERT INTO assessments (course_name, teacher_id, assessment_name, assessment_type, 
                                   total_marks, weightage, assessment_date, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, course_name, teacher_id, assessment_name, assessment_type, 
             total_marks, weightage, assessment_date, description)
        
        flash("Assessment created successfully!")
        return redirect(url_for('assessments'))
        
    except Exception as e:
        print(f"Error creating assessment: {str(e)}")
        flash("Error creating assessment")
        return redirect(url_for('create_assessment'))

@app.route('/grade_assessment/<int:assessment_id>')
@teacher_or_admin_required
def grade_assessment(assessment_id):
    """Grade students for a specific assessment"""
    try:
        # Get assessment details
        assessment = db.execute("SELECT * FROM assessments WHERE assessment_id = ?", assessment_id)[0]
        
        # Get students enrolled in the course
        students = db.execute("""
            SELECT s.student_id, s.name, s.email
            FROM students s
            WHERE s.course = ? AND s.status = 1
            ORDER BY s.name
        """, assessment['course_name'])
        
        # Get existing grades for this assessment
        existing_grades = db.execute("""
            SELECT * FROM grades WHERE assessment_id = ?
        """, assessment_id)
        
        # Create a mapping for easy lookup
        grade_map = {grade['student_id']: grade for grade in existing_grades}
        
    except Exception as e:
        print(f"Error loading assessment: {str(e)}")
        flash("Error loading assessment")
        return redirect(url_for('assessments'))
    
    return render_template('grade_assessment.html',
                         assessment=assessment,
                         students=students,
                         grade_map=grade_map)

@app.route('/submit_grades', methods=['POST'])
@teacher_or_admin_required
def submit_grades():
    """Submit grades for multiple students"""
    try:
        assessment_id = int(request.form.get('assessment_id'))
        
        # Get assessment details
        assessment = db.execute("SELECT * FROM assessments WHERE assessment_id = ?", assessment_id)[0]
        total_marks = assessment['total_marks']
        
        # Process each student's grade
        for key, value in request.form.items():
            if key.startswith('marks_'):
                student_id = int(key.split('_')[1])
                obtained_marks = float(value) if value else 0
                
                if obtained_marks > total_marks:
                    flash(f"Marks cannot exceed {total_marks} for student ID {student_id}")
                    continue
                
                percentage = (obtained_marks / total_marks) * 100
                remarks = request.form.get(f'remarks_{student_id}', '')
                
                # Insert or update grade
                db.execute("""
                    INSERT OR REPLACE INTO grades 
                    (assessment_id, student_id, obtained_marks, percentage, remarks)
                    VALUES (?, ?, ?, ?, ?)
                """, assessment_id, student_id, obtained_marks, percentage, remarks)
                
                # Update course result
                update_course_result(student_id, assessment['course_name'])
        
        flash("Grades submitted successfully!")
        return redirect(url_for('assessments'))
        
    except Exception as e:
        print(f"Error submitting grades: {str(e)}")
        flash("Error submitting grades")
        return redirect(url_for('assessments'))

@app.route('/results')
@login_required
def results():
    """View results based on user role"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    if user_role == 'student':
        return redirect(url_for('student_results'))
    else:
        return redirect(url_for('all_student_results'))

@app.route('/student_results')
@login_required
def student_results():
    """View results for a specific student"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    # Get student ID based on role
    if user_role == 'student':
        student_id = user_id
        student_info = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)[0]
    else:
        student_id = request.args.get('student_id')
        if not student_id:
            flash("Please select a student to view results")
            return redirect(url_for('all_student_results'))
        student_info = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)[0]
    
    try:
        # Get course results
        course_results = db.execute("""
            SELECT * FROM course_results WHERE student_id = ?
        """, student_id)
        
        # Get detailed assessment breakdown
        assessment_breakdown = db.execute("""
            SELECT a.assessment_name, a.assessment_type, a.total_marks, a.weightage,
                   g.obtained_marks, g.percentage, a.course_name, a.assessment_date
            FROM assessments a
            JOIN grades g ON a.assessment_id = g.assessment_id
            WHERE g.student_id = ?
            ORDER BY a.course_name, a.assessment_date
        """, student_id)
        
        # Organize data for display
        course_data = {}
        for result in course_results:
            course_name = result['course_name']
            course_data[course_name] = {
                'result': result,
                'assessments': []
            }
        
        for assessment in assessment_breakdown:
            course_name = assessment['course_name']
            if course_name in course_data:
                course_data[course_name]['assessments'].append(assessment)
        
    except Exception as e:
        print(f"Error loading student results: {str(e)}")
        course_results = []
        course_data = {}
    
    return render_template('student_results.html',
                         student_info=student_info,
                         course_results=course_results,
                         course_data=course_data,
                         user_role=user_role)

@app.route('/all_student_results')
@teacher_or_admin_required
def all_student_results():
    """View all students' results summary"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    # Filter parameters
    course_filter = request.args.get('course', '')
    grade_filter = request.args.get('grade', '')
    
    try:
        # Base query for students
        query = """
            SELECT DISTINCT s.student_id, s.name, s.course, s.email
            FROM students s
            WHERE s.status = 1
        """
        params = []
        
        # Filter by course if specified
        if course_filter:
            query += " AND s.course = ?"
            params.append(course_filter)
        
        students = db.execute(query + " ORDER BY s.name", *params)
        
        # Get performance summary for each student
        student_performance = []
        for student in students:
            # Get overall performance from course results
            course_results = db.execute("""
                SELECT AVG(final_percentage) as avg_percentage, COUNT(*) as total_courses
                FROM course_results WHERE student_id = ?
            """, student['student_id'])
            
            if course_results[0]['avg_percentage']:
                avg_percentage = round(course_results[0]['avg_percentage'], 2)
                final_grade = calculate_grade(avg_percentage)
                status = 'Pass' if avg_percentage >= 50 else 'Fail'
            else:
                avg_percentage = 0
                final_grade = 'N/A'
                status = 'No Grades'
            
            performance = {
                'student_info': student,
                'avg_percentage': avg_percentage,
                'final_grade': final_grade,
                'total_courses': course_results[0]['total_courses'],
                'status': status
            }
            
            # Apply grade filter
            if grade_filter and performance['final_grade'] != grade_filter:
                continue
                
            student_performance.append(performance)
        
        # Get available courses and grades for filtering
        courses = db.execute("SELECT DISTINCT course_name FROM courses")
        grades = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D', 'F']
        
    except Exception as e:
        print(f"Error loading student results: {str(e)}")
        flash("Error loading student results")
        student_performance = []
        courses = []
        grades = []
    
    return render_template('all_student_results.html',
                         student_performance=student_performance,
                         courses=courses,
                         grades=grades,
                         course_filter=course_filter,
                         grade_filter=grade_filter,
                         user_role=user_role)

# Continue with existing routes (pending_accounts, create_notification, etc.)
@app.route('/pending_accounts')
@teacher_or_admin_required
def pending_accounts():
    user_role = session.get("user_role")
    
    pending_students = []
    pending_teachers = []
    pending_admins = []
    
    try:
        if user_role == 'admin':
            pending_students = db.execute("SELECT * FROM students WHERE status = 0 ORDER BY student_id DESC")
            pending_teachers = db.execute("SELECT * FROM teachers WHERE status = 0 ORDER BY teacher_id DESC")
            pending_admins = db.execute("SELECT * FROM admin WHERE status = 0 ORDER BY admin_id DESC")
        elif user_role == 'teacher':
            pending_students = db.execute("SELECT * FROM students WHERE status = 0 ORDER BY student_id DESC")
    except Exception as e:
        print(f"Error loading pending accounts: {str(e)}")
        flash("Error loading pending accounts.")
    
    return render_template('pending_accounts.html',
                         pending_students=pending_students,
                         pending_teachers=pending_teachers,
                         pending_admins=pending_admins,
                         user_role=user_role)

@app.route('/approve_account/<role>/<int:account_id>', methods=['POST'])
@teacher_or_admin_required
def approve_account(role, account_id):
    try:
        user_role = session.get("user_role")
        
        if role in ['teacher', 'admin'] and user_role != 'admin':
            flash("Only admins can approve teacher and admin accounts.")
            return redirect(url_for('pending_accounts'))
        
        if role == 'student':
            db.execute("UPDATE students SET status = 1 WHERE student_id = ?", account_id)
            flash("Student account approved successfully!")
        elif role == 'teacher':
            db.execute("UPDATE teachers SET status = 1 WHERE teacher_id = ?", account_id)
            flash("Teacher account approved successfully!")
        elif role == 'admin':
            db.execute("UPDATE admin SET status = 1 WHERE admin_id = ?", account_id)
            flash("Admin account approved successfully!")
        
        return redirect(url_for('pending_accounts'))
        
    except Exception as e:
        print(f"Approve account error: {str(e)}")
        flash("Error approving account. Please try again.")
        return redirect(url_for('pending_accounts'))

@app.route('/reject_account/<role>/<int:account_id>', methods=['POST'])
@teacher_or_admin_required
def reject_account(role, account_id):
    try:
        user_role = session.get("user_role")
        
        if role in ['teacher', 'admin'] and user_role != 'admin':
            flash("Only admins can reject teacher and admin accounts.")
            return redirect(url_for('pending_accounts'))
        
        if role == 'student':
            db.execute("DELETE FROM students WHERE student_id = ?", account_id)
            flash("Student account rejected and removed.")
        elif role == 'teacher':
            db.execute("DELETE FROM teachers WHERE teacher_id = ?", account_id)
            flash("Teacher account rejected and removed.")
        elif role == 'admin':
            db.execute("DELETE FROM admin WHERE admin_id = ?", account_id)
            flash("Admin account rejected and removed.")
        
        return redirect(url_for('pending_accounts'))
        
    except Exception as e:
        print(f"Reject account error: {str(e)}")
        flash("Error rejecting account. Please try again.")
        return redirect(url_for('pending_accounts'))

@app.route('/create_notification')
@login_required
def create_notification():
    user_role = session.get("user_role")
    if user_role not in ['admin', 'teacher']:
        flash("Access denied. Only admins and teachers can create notifications.")
        return redirect(url_for('dashboard'))
    
    courses = []
    try:
        if user_role == 'teacher':
            courses = db.execute("SELECT DISTINCT course_name FROM courses")
    except Exception as e:
        print(f"Error loading courses: {str(e)}")
        courses = []
    
    return render_template('create_notification.html', courses=courses)

@app.route('/create_notification', methods=['POST'])
@login_required
def create_notification_post():
    try:
        user_role = session.get("user_role")
        user_id = session.get("user_id")
        
        if user_role not in ['admin', 'teacher']:
            flash("Access denied.")
            return redirect(url_for('dashboard'))
        
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        target_audience = request.form.get('target_audience', '')
        specific_course = request.form.get('specific_course', '')
        
        if not title or not message or not target_audience:
            flash("Title, message, and target audience are required.")
            return redirect(url_for('create_notification'))
        
        if user_role == 'teacher' and target_audience in ['all_teachers', 'all']:
            flash("Teachers can only send notifications to students.")
            return redirect(url_for('create_notification'))
        
        if target_audience == 'specific_course' and not specific_course:
            flash("Please select a course for course-specific notifications.")
            return redirect(url_for('create_notification'))
        
        db.execute("""
            INSERT INTO notifications (title, message, created_by, created_by_role, 
                                     target_audience, specific_course, read_by)
            VALUES (?, ?, ?, ?, ?, ?, '')
        """, title, message, user_id, user_role, target_audience, 
             specific_course if target_audience == 'specific_course' else None)
        
        flash("Notification created successfully!")
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Create notification error: {str(e)}")
        flash("Error creating notification. Please try again.")
        return redirect(url_for('create_notification'))

@app.route('/mark_notification_read/<int:notification_id>', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    try:
        user_id = session.get("user_id")
        user_role = session.get("user_role")
        user_key = f"{user_role}_{user_id}"
        
        notification = db.execute("SELECT read_by FROM notifications WHERE notification_id = ?", notification_id)
        
        if notification:
            current_read_by = notification[0]['read_by']
            
            if user_key not in current_read_by:
                if current_read_by:
                    new_read_by = f"{current_read_by},{user_key}"
                else:
                    new_read_by = user_key
                
                db.execute("""
                    UPDATE notifications 
                    SET read_by = ? 
                    WHERE notification_id = ?
                """, new_read_by, notification_id)
                
                flash("Notification marked as read.")
        
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Mark read error: {str(e)}")
        flash("Error updating notification.")
        return redirect(url_for('dashboard'))

@app.route('/mark_all_read', methods=['POST'])
@login_required
def mark_all_read():
    try:
        user_id = session.get("user_id")
        user_role = session.get("user_role")
        user_course = session.get("user_course", None)
        user_key = f"{user_role}_{user_id}"
        
        notifications = get_user_notifications(user_id, user_role, user_course)
        unread_notifications = [n for n in notifications if not n['is_read']]
        
        for notification in unread_notifications:
            current_read_by = notification['read_by']
            if user_key not in current_read_by:
                if current_read_by:
                    new_read_by = f"{current_read_by},{user_key}"
                else:
                    new_read_by = user_key
                
                db.execute("""
                    UPDATE notifications 
                    SET read_by = ? 
                    WHERE notification_id = ?
                """, new_read_by, notification['notification_id'])
        
        flash("All notifications marked as read.")
        return redirect(url_for('dashboard'))
    except Exception as e:
        print(f"Mark all read error: {str(e)}")
        flash("Error updating notifications.")
        return redirect(url_for('dashboard'))

# STUDENT AND TEACHER MANAGEMENT ROUTES
@app.route('/manage_students')
@teacher_or_admin_required
def manage_students():
    """Manage all students with detailed view"""
    user_role = session.get("user_role")
    user_id = session.get("user_id")
    
    # Filter parameters
    course_filter = request.args.get('course', '')
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '')
    
    try:
        # Base query for students
        query = """
            SELECT s.*, 
                   COUNT(DISTINCT a.attendance_id) as total_attendance,
                   COUNT(DISTINCT CASE WHEN a.status = 'present' THEN a.attendance_id END) as present_count,
                   AVG(cr.final_percentage) as avg_percentage
            FROM students s
            LEFT JOIN attendance a ON s.student_id = a.student_id
            LEFT JOIN course_results cr ON s.student_id = cr.student_id
            WHERE 1=1
        """
        params = []
        
        # Apply filters
        if course_filter:
            query += " AND s.course = ?"
            params.append(course_filter)
        
        if status_filter:
            if status_filter == 'active':
                query += " AND s.status = 1"
            elif status_filter == 'pending':
                query += " AND s.status = 0"
        
        if search_query:
            query += " AND (s.name LIKE ? OR s.email LIKE ?)"
            params.extend([f"%{search_query}%", f"%{search_query}%"])
        
        query += " GROUP BY s.student_id ORDER BY s.name"
        
        students = db.execute(query, *params)
        
        # Calculate attendance percentage for each student
        for student in students:
            if student['total_attendance'] > 0:
                student['attendance_percentage'] = round((student['present_count'] / student['total_attendance']) * 100, 1)
            else:
                student['attendance_percentage'] = 0
            
            student['avg_percentage'] = round(student['avg_percentage'], 1) if student['avg_percentage'] else 0
        
        # Get available courses for filter
        courses = db.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name")
        
    except Exception as e:
        print(f"Error loading students: {str(e)}")
        flash("Error loading student data.")
        students = []
        courses = []
    
    return render_template('manage_students.html',
                         students=students,
                         courses=courses,
                         course_filter=course_filter,
                         status_filter=status_filter,
                         search_query=search_query,
                         user_role=user_role)

@app.route('/manage_teachers')
@admin_required
def manage_teachers():
    """Manage all teachers with detailed view (Admin only)"""
    # Filter parameters
    subject_filter = request.args.get('subject', '')
    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '')
    
    try:
        # Base query for teachers
        query = """
            SELECT t.*, 
                   COUNT(DISTINCT c.course_id) as assigned_courses,
                   COUNT(DISTINCT a.assessment_id) as total_assessments
            FROM teachers t
            LEFT JOIN courses c ON t.teacher_id = c.teacher_id
            LEFT JOIN assessments a ON t.teacher_id = a.teacher_id
            WHERE 1=1
        """
        params = []
        
        # Apply filters
        if subject_filter:
            query += " AND t.subject LIKE ?"
            params.append(f"%{subject_filter}%")
        
        if status_filter:
            if status_filter == 'active':
                query += " AND t.status = 1"
            elif status_filter == 'pending':
                query += " AND t.status = 0"
        
        if search_query:
            query += " AND (t.name LIKE ? OR t.email LIKE ? OR t.subject LIKE ?)"
            params.extend([f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"])
        
        query += " GROUP BY t.teacher_id ORDER BY t.name"
        
        teachers = db.execute(query, *params)
        
        # Get unique subjects for filter
        subjects = db.execute("SELECT DISTINCT subject FROM teachers WHERE subject IS NOT NULL ORDER BY subject")
        
    except Exception as e:
        print(f"Error loading teachers: {str(e)}")
        flash("Error loading teacher data.")
        teachers = []
        subjects = []
    
    return render_template('manage_teachers.html',
                         teachers=teachers,
                         subjects=subjects,
                         subject_filter=subject_filter,
                         status_filter=status_filter,
                         search_query=search_query)

@app.route('/student_details/<int:student_id>')
@teacher_or_admin_required
def student_details(student_id):
    """View detailed information about a specific student"""
    user_role = session.get('user_role')
    
    try:
        # Get student basic info
        student = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)
        if not student:
            flash("Student not found.")
            return redirect(url_for('manage_students'))
        
        student = student[0]
        
        # Get attendance data
        attendance_data = db.execute("""
            SELECT a.*, 
                   CASE 
                       WHEN a.marked_by_role = 'teacher' THEN t.name
                       WHEN a.marked_by_role = 'admin' THEN ad.name
                   END as marked_by_name
            FROM attendance a
            LEFT JOIN teachers t ON a.marked_by = t.teacher_id AND a.marked_by_role = 'teacher'
            LEFT JOIN admin ad ON a.marked_by = ad.admin_id AND a.marked_by_role = 'admin'
            WHERE a.student_id = ?
            ORDER BY a.date DESC
            LIMIT 20
        """, student_id)
        
        # Calculate attendance statistics
        total_attendance = len(attendance_data)
        present_count = len([a for a in attendance_data if a['status'] == 'present'])
        attendance_percentage = round((present_count / total_attendance) * 100, 1) if total_attendance > 0 else 0
        
        # Get course results
        course_results = db.execute("""
            SELECT * FROM course_results WHERE student_id = ?
        """, student_id)
        
        # Get assessment details
        assessment_details = db.execute("""
            SELECT a.assessment_name, a.assessment_type, a.total_marks, a.weightage,
                   g.obtained_marks, g.percentage, a.course_name, a.assessment_date,
                   g.remarks
            FROM assessments a
            JOIN grades g ON a.assessment_id = g.assessment_id
            WHERE g.student_id = ?
            ORDER BY a.assessment_date DESC
        """, student_id)
        
        # Calculate overall statistics
        overall_avg = 0
        if course_results:
            total_percentage = sum([cr['final_percentage'] for cr in course_results if cr['final_percentage']])
            overall_avg = round(total_percentage / len(course_results), 1) if course_results else 0
        
        stats = {
            'total_attendance': total_attendance,
            'present_count': present_count,
            'attendance_percentage': attendance_percentage,
            'total_courses': len(course_results),
            'overall_avg': overall_avg,
            'total_assessments': len(assessment_details)
        }
        
    except Exception as e:
        print(f"Error loading student details: {str(e)}")
        flash("Error loading student details.")
        return redirect(url_for('manage_students'))
    
    return render_template('student_details.html',
                         student=student,
                         attendance_data=attendance_data,
                         course_results=course_results,
                         assessment_details=assessment_details,
                         stats=stats,
                         user_role=user_role)

@app.route('/toggle_student_status/<int:student_id>', methods=['POST'])
@teacher_or_admin_required
def toggle_student_status(student_id):
    """Toggle student status between active (1) and inactive (0)"""
    try:
        # Get current student status
        student = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)
        
        if not student:
            flash("Student not found.")
            return redirect(url_for('manage_students'))
        
        current_status = student[0]['status']
        student_name = student[0]['name']
        
        # Toggle status: 1 -> 0 (deactivate), 0 -> 1 (activate)
        new_status = 0 if current_status == 1 else 1
        
        # Update student status in database
        db.execute("UPDATE students SET status = ? WHERE student_id = ?", new_status, student_id)
        
        # Show appropriate success message
        if new_status == 1:
            flash(f"Student {student_name} has been activated successfully!")
        else:
            flash(f"Student {student_name} has been deactivated successfully!")
        
    except Exception as e:
        print(f"Error toggling student status: {str(e)}")
        flash("Error updating student status. Please try again.")
    
    return redirect(url_for('manage_students'))

@app.route('/toggle_teacher_status/<int:teacher_id>', methods=['POST'])
@admin_required
def toggle_teacher_status(teacher_id):
    """Toggle teacher status between active (1) and inactive (0)"""
    try:
        # Get current teacher status
        teacher = db.execute("SELECT * FROM teachers WHERE teacher_id = ?", teacher_id)
        
        if not teacher:
            flash("Teacher not found.")
            return redirect(url_for('manage_teachers'))
        
        current_status = teacher[0]['status']
        teacher_name = teacher[0]['name']
        
        # Toggle status: 1 -> 0 (deactivate), 0 -> 1 (activate)
        new_status = 0 if current_status == 1 else 1
        
        # Update teacher status in database
        db.execute("UPDATE teachers SET status = ? WHERE teacher_id = ?", new_status, teacher_id)
        
        # Show appropriate success message
        if new_status == 1:
            flash(f"Teacher {teacher_name} has been activated successfully!")
        else:
            flash(f"Teacher {teacher_name} has been deactivated successfully!")
        
    except Exception as e:
        print(f"Error toggling teacher status: {str(e)}")
        flash("Error updating teacher status. Please try again.")
    
    return redirect(url_for('manage_teachers'))

@app.route('/delete_student/<int:student_id>', methods=['POST'])
@admin_required
def delete_student(student_id):
    """Delete a student (Admin only)"""
    try:
        # Check if student exists
        student = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)
        if not student:
            flash("Student not found.")
            return redirect(url_for('manage_students'))
        
        student_name = student[0]['name']
        
        # Check if student has attendance records
        attendance_records = db.execute("SELECT COUNT(*) as count FROM attendance WHERE student_id = ?", student_id)
        if attendance_records[0]['count'] > 0:
            flash("Cannot delete student with attendance records. Please deactivate instead.")
            return redirect(url_for('manage_students'))
        
        # Check if student has grades
        grade_records = db.execute("SELECT COUNT(*) as count FROM grades WHERE student_id = ?", student_id)
        if grade_records[0]['count'] > 0:
            flash("Cannot delete student with assessment results. Please deactivate instead.")
            return redirect(url_for('manage_students'))
        
        # Delete the student
        db.execute("DELETE FROM students WHERE student_id = ?", student_id)
        
        flash(f"Student {student_name} deleted successfully!")
        
    except Exception as e:
        print(f"Error deleting student: {str(e)}")
        flash("Error deleting student.")
    
    return redirect(url_for('manage_students'))

@app.route('/delete_teacher/<int:teacher_id>', methods=['POST'])
@admin_required
def delete_teacher(teacher_id):
    """Delete a teacher (Admin only)"""
    try:
        # Check if teacher exists
        teacher = db.execute("SELECT * FROM teachers WHERE teacher_id = ?", teacher_id)
        if not teacher:
            flash("Teacher not found.")
            return redirect(url_for('manage_teachers'))
        
        teacher_name = teacher[0]['name']
        
        # Check if teacher has assigned courses
        assigned_courses = db.execute("SELECT COUNT(*) as count FROM courses WHERE teacher_id = ?", teacher_id)
        if assigned_courses[0]['count'] > 0:
            flash("Cannot delete teacher with assigned courses. Please reassign courses first.")
            return redirect(url_for('manage_teachers'))
        
        # Check if teacher has created assessments
        created_assessments = db.execute("SELECT COUNT(*) as count FROM assessments WHERE teacher_id = ?", teacher_id)
        if created_assessments[0]['count'] > 0:
            flash("Cannot delete teacher with created assessments. Please reassign assessments first.")
            return redirect(url_for('manage_teachers'))
        
        # Delete the teacher
        db.execute("DELETE FROM teachers WHERE teacher_id = ?", teacher_id)
        
        flash(f"Teacher {teacher_name} deleted successfully!")
        
    except Exception as e:
        print(f"Error deleting teacher: {str(e)}")
        flash("Error deleting teacher.")
    
    return redirect(url_for('manage_teachers'))

@app.route('/edit_student/<int:student_id>')
@teacher_or_admin_required
def edit_student(student_id):
    """Edit student information form"""
    try:
        student = db.execute("SELECT * FROM students WHERE student_id = ?", student_id)
        if not student:
            flash("Student not found.")
            return redirect(url_for('manage_students'))
        
        student = student[0]
        courses = db.execute("SELECT DISTINCT course_name FROM courses ORDER BY course_name")
        
    except Exception as e:
        print(f"Error loading student: {str(e)}")
        flash("Error loading student.")
        return redirect(url_for('manage_students'))
    
    return render_template('edit_student.html', student=student, courses=courses)

@app.route('/update_student/<int:student_id>', methods=['POST'])
@teacher_or_admin_required
def update_student(student_id):
    """Update student information"""
    try:
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        course = request.form.get('course', '').strip()
        dob = request.form.get('dob', '')
        gender = request.form.get('gender', '')
        parent_name = request.form.get('parent_name', '').strip()
        parent_phone = request.form.get('parent_phone', '').strip()
        parent_email = request.form.get('parent_email', '').strip()
        parent_occupation = request.form.get('parent_occupation', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        
        # Validate required fields
        if not all([name, email, phone, course]):
            flash("Name, email, phone, and course are required.")
            return redirect(url_for('edit_student', student_id=student_id))
        
        # Check if email exists for other students
        existing = db.execute("SELECT * FROM students WHERE email = ? AND student_id != ?", email, student_id)
        if existing:
            flash("Email already exists for another student.")
            return redirect(url_for('edit_student', student_id=student_id))
        
        # Update student
        db.execute("""
            UPDATE students 
            SET name = ?, email = ?, phone = ?, course = ?, dob = ?, gender = ?,
                parent_name = ?, parent_phone = ?, parent_email = ?, 
                parent_occupation = ?, emergency_contact = ?
            WHERE student_id = ?
        """, name, email, phone, course, dob, gender, parent_name, parent_phone, 
             parent_email, parent_occupation, emergency_contact, student_id)
        
        flash("Student information updated successfully!")
        return redirect(url_for('student_details', student_id=student_id))
        
    except Exception as e:
        print(f"Error updating student: {str(e)}")
        flash("Error updating student.")
        return redirect(url_for('edit_student', student_id=student_id))

@app.route('/teacher_details/<int:teacher_id>')
@admin_required
def teacher_details(teacher_id):
    """View detailed information about a specific teacher (Admin only)"""
    try:
        # Get teacher basic info
        teacher = db.execute("SELECT * FROM teachers WHERE teacher_id = ?", teacher_id)
        if not teacher:
            flash("Teacher not found.")
            return redirect(url_for('manage_teachers'))
        
        teacher = teacher[0]
        
        # Get assigned courses
        assigned_courses = db.execute("""
            SELECT * FROM courses WHERE teacher_id = ?
        """, teacher_id)
        
        # Get created assessments
        assessments = db.execute("""
            SELECT a.*, COUNT(g.grade_id) as graded_count,
                   (SELECT COUNT(*) FROM students s WHERE s.course = a.course_name AND s.status = 1) as total_students
            FROM assessments a
            LEFT JOIN grades g ON a.assessment_id = g.assessment_id
            WHERE a.teacher_id = ?
            GROUP BY a.assessment_id
            ORDER BY a.created_at DESC
        """, teacher_id)
        
        # Get students under this teacher (based on course assignment)
        students_taught = []
        if assigned_courses:
            course_names = [course['course_name'] for course in assigned_courses]
            placeholders = ','.join(['?' for _ in course_names])
            students_taught = db.execute(f"""
                SELECT DISTINCT s.student_id, s.name, s.email, s.course
                FROM students s
                WHERE s.course IN ({placeholders}) AND s.status = 1
                ORDER BY s.name
            """, *course_names)
        
        # Calculate statistics
        total_students = len(students_taught)
        total_assessments = len(assessments)
        total_courses = len(assigned_courses)
        
        # Calculate grading progress
        total_possible_grades = sum([a['total_students'] for a in assessments])
        total_graded = sum([a['graded_count'] for a in assessments])
        grading_percentage = round((total_graded / total_possible_grades) * 100, 1) if total_possible_grades > 0 else 0
        
        stats = {
            'total_students': total_students,
            'total_assessments': total_assessments,
            'total_courses': total_courses,
            'grading_percentage': grading_percentage,
            'total_graded': total_graded,
            'total_possible_grades': total_possible_grades
        }
        
    except Exception as e:
        print(f"Error loading teacher details: {str(e)}")
        flash("Error loading teacher details.")
        return redirect(url_for('manage_teachers'))
    
    return render_template('teacher_details.html',
                         teacher=teacher,
                         assigned_courses=assigned_courses,
                         assessments=assessments,
                         students_taught=students_taught,
                         stats=stats)

@app.route('/manage_courses')
@admin_required
def manage_courses():
    """Manage all courses (Admin only)"""
    try:
        # Get courses with teacher and student information
        courses = db.execute("""
            SELECT c.*, 
                   t.name as teacher_name,
                   t.subject as teacher_subject,
                   COUNT(DISTINCT s.student_id) as enrolled_students
            FROM courses c
            LEFT JOIN teachers t ON c.teacher_id = t.teacher_id
            LEFT JOIN students s ON c.course_name = s.course AND s.status = 1
            GROUP BY c.course_id
            ORDER BY c.course_name
        """)
        
        # Get all active teachers for assignment
        teachers = db.execute("SELECT teacher_id, name, subject FROM teachers WHERE status = 1 ORDER BY name")
        
        # Calculate statistics
        total_students = sum([course['enrolled_students'] for course in courses])
        courses_with_teachers = len([course for course in courses if course['teacher_id']])
        
    except Exception as e:
        print(f"Error loading courses: {str(e)}")
        courses = []
        teachers = []
        total_students = 0
        courses_with_teachers = 0
    
    return render_template('manage_courses.html',
                         courses=courses,
                         teachers=teachers,
                         total_students=total_students,
                         courses_with_teachers=courses_with_teachers,
                         user_role=session.get('user_role'))

@app.route('/add_course', methods=['POST'])
@admin_required
def add_course():
    """Add a new course"""
    try:
        course_name = request.form.get('course_name', '').strip()
        teacher_id = request.form.get('teacher_id', '')
        fee = request.form.get('fee', '')
        duration = request.form.get('duration', '').strip()
        description = request.form.get('description', '').strip()
        
        if not course_name:
            flash("Course name is required.")
            return redirect(url_for('manage_courses'))
        
        # Check if course already exists
        existing = db.execute("SELECT * FROM courses WHERE course_name = ?", course_name)
        if existing:
            flash("Course with this name already exists.")
            return redirect(url_for('manage_courses'))
        
        # Convert fee to float if provided
        fee_value = float(fee) if fee else None
        teacher_id_value = int(teacher_id) if teacher_id else None
        
        # Insert new course
        db.execute("""
            INSERT INTO courses (course_name, teacher_id, fee, duration, description)
            VALUES (?, ?, ?, ?, ?)
        """, course_name, teacher_id_value, fee_value, duration, description)
        
        flash("Course added successfully!")
        
    except Exception as e:
        print(f"Error adding course: {str(e)}")
        flash("Error adding course. Please check your input.")
    
    return redirect(url_for('manage_courses'))

@app.route('/assign_teacher/<int:course_id>', methods=['POST'])
@admin_required
def assign_teacher(course_id):
    """Assign or unassign teacher to/from a course"""
    try:
        teacher_id = request.form.get('teacher_id', '')
        
        if teacher_id:
            # Assign teacher
            db.execute("UPDATE courses SET teacher_id = ? WHERE course_id = ?", int(teacher_id), course_id)
            flash("Teacher assigned successfully!")
        else:
            # Unassign teacher
            db.execute("UPDATE courses SET teacher_id = NULL WHERE course_id = ?", course_id)
            flash("Teacher unassigned successfully!")
        
    except Exception as e:
        print(f"Error assigning teacher: {str(e)}")
        flash("Error assigning teacher.")
    
    return redirect(url_for('manage_courses'))

@app.route('/delete_course/<int:course_id>', methods=['POST'])
@admin_required
def delete_course(course_id):
    """Delete a course (Admin only)"""
    try:
        # Check if course exists
        course = db.execute("SELECT * FROM courses WHERE course_id = ?", course_id)
        if not course:
            flash("Course not found.")
            return redirect(url_for('manage_courses'))
        
        course_name = course[0]['course_name']
        
        # Check if there are students enrolled
        enrolled_students = db.execute("SELECT COUNT(*) as count FROM students WHERE course = ?", course_name)
        if enrolled_students[0]['count'] > 0:
            flash("Cannot delete course with enrolled students. Please transfer students first.")
            return redirect(url_for('manage_courses'))
        
        # Check if there are assessments
        assessments = db.execute("SELECT COUNT(*) as count FROM assessments WHERE course_name = ?", course_name)
        if assessments[0]['count'] > 0:
            flash("Cannot delete course with existing assessments. Please remove assessments first.")
            return redirect(url_for('manage_courses'))
        
        # Delete the course
        db.execute("DELETE FROM courses WHERE course_id = ?", course_id)
        
        flash("Course deleted successfully!")
        
    except Exception as e:
        print(f"Error deleting course: {str(e)}")
        flash("Error deleting course.")
    
    return redirect(url_for('manage_courses'))

@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out successfully.")
    return redirect(url_for('start'))

# ERROR HANDLERS
@app.errorhandler(403)
def forbidden(error):
    """Handle 403 Forbidden errors"""
    return render_template('error.html',
                         error_code=403,
                         error_title="Access Forbidden",
                         error_message="You don't have permission to access this resource. Please check your user role and permissions.",
                         error_details=str(error) if app.debug else None), 403

@app.errorhandler(404)
def page_not_found(error):
    """Handle 404 Not Found errors"""
    return render_template('error.html',
                         error_code=404,
                         error_title="Page Not Found",
                         error_message="The page you're looking for doesn't exist. It may have been moved, deleted, or you entered the wrong URL.",
                         error_details=str(error) if app.debug else None), 404

@app.errorhandler(401)
def unauthorized(error):
    """Handle 401 Unauthorized errors"""
    return render_template('error.html',
                         error_code=401,
                         error_title="Authentication Required",
                         error_message="You need to log in to access this resource. Please log in with your credentials.",
                         error_details=str(error) if app.debug else None), 401

@app.errorhandler(500)
def internal_server_error(error):
    """Handle 500 Internal Server errors"""
    # Log the error for debugging
    print(f"Internal Server Error: {str(error)}")
    
    # Rollback any database transactions
    try:
        db.execute("ROLLBACK")
    except:
        pass
    
    return render_template('error.html',
                         error_code=500,
                         error_title="Internal Server Error",
                         error_message="Something went wrong on our server. Our team has been notified and is working to fix the issue.",
                         error_details=str(error) if app.debug else None), 500

@app.errorhandler(400)
def bad_request(error):
    """Handle 400 Bad Request errors"""
    return render_template('error.html',
                         error_code=400,
                         error_title="Bad Request",
                         error_message="The request could not be understood by the server. Please check your input and try again.",
                         error_details=str(error) if app.debug else None), 400

@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 Method Not Allowed errors"""
    return render_template('error.html',
                         error_code=405,
                         error_title="Method Not Allowed",
                         error_message="The method is not allowed for the requested URL. Please check the request method.",
                         error_details=str(error) if app.debug else None), 405

@app.errorhandler(Exception)
def handle_exception(error):
    """Handle any uncaught exceptions"""
    # Log the error
    print(f"Uncaught Exception: {str(error)}")
    
    # Check if it's an HTTP error
    if hasattr(error, 'code'):
        return render_template('error.html',
                             error_code=error.code,
                             error_title=error.name,
                             error_message=error.description,
                             error_details=str(error) if app.debug else None), error.code
    
    # For any other exception, return 500
    return render_template('error.html',
                         error_code=500,
                         error_title="Unexpected Error",
                         error_message="An unexpected error occurred. Please try again later or contact support if the problem persists.",
                         error_details=str(error) if app.debug else None), 500

# Enhanced login_required decorator with better error handling
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            # Store the URL they were trying to access
            session['next_url'] = request.url
            # Return 401 instead of redirect for better error handling
            return render_template('error.html',
                                 error_code=401,
                                 error_title="Login Required",
                                 error_message="Please log in to access this page.",
                                 error_details=None), 401
        return f(*args, **kwargs)
    return decorated_function

# Enhanced admin_required decorator
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return render_template('error.html',
                                 error_code=401,
                                 error_title="Login Required",
                                 error_message="Please log in to access this page.",
                                 error_details=None), 401
        
        if session.get("user_role") != 'admin':
            return render_template('error.html',
                                 error_code=403,
                                 error_title="Admin Access Required",
                                 error_message="You need administrator privileges to access this resource.",
                                 error_details=None), 403
        return f(*args, **kwargs)
    return decorated_function

# Enhanced teacher_or_admin_required decorator
def teacher_or_admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return render_template('error.html',
                                 error_code=401,
                                 error_title="Login Required",
                                 error_message="Please log in to access this page.",
                                 error_details=None), 401
        
        if session.get("user_role") not in ['admin', 'teacher']:
            return render_template('error.html',
                                 error_code=403,
                                 error_title="Teacher/Admin Access Required",
                                 error_message="You need teacher or administrator privileges to access this resource.",
                                 error_details=None), 403
        return f(*args, **kwargs)
    return decorated_function

# Enhanced can_send_messages decorator
def can_send_messages(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return render_template('error.html',
                                 error_code=401,
                                 error_title="Login Required",
                                 error_message="Please log in to send messages.",
                                 error_details=None), 401
        
        if session.get("user_role") not in ['admin', 'teacher', 'student']:
            return render_template('error.html',
                                 error_code=403,
                                 error_title="Access Denied",
                                 error_message="You don't have permission to send messages.",
                                 error_details=None), 403
        return f(*args, **kwargs)
    return decorated_function


if __name__ == '__main__':
    app.run(debug=True)
