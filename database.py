from cs50 import SQL
import sqlite3
from werkzeug.security import generate_password_hash
import os

def setup_database():
    # Delete existing database to start fresh
    if os.path.exists('institute.db'):
        os.remove('institute.db')
    if not os.path.exists('institute.db'):
        conn = sqlite3.connect("institute.db")
        conn.close()
    db = SQL("sqlite:///institute.db")

    # Create tables with proper schema - Each table in separate db.execute call
    db.execute('''CREATE TABLE IF NOT EXISTS admin (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        status INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS teachers (
        teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        subject TEXT,
        status INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS students (
        student_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        phone TEXT,
        course TEXT,
        dob DATE,
        gender TEXT,
        parent_name TEXT,
        parent_phone TEXT,
        parent_email TEXT,
        parent_occupation TEXT,
        emergency_contact TEXT,
        status INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS courses (
        course_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT UNIQUE NOT NULL,
        teacher_id INTEGER,
        fee REAL,
        duration TEXT,
        description TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS attendance (
        attendance_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        course_name TEXT NOT NULL,
        date DATE NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('present', 'absent', 'late')),
        marked_by INTEGER NOT NULL,
        marked_by_role TEXT NOT NULL CHECK (marked_by_role IN ('admin', 'teacher')),
        marked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students(student_id)
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS assessments (
        assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        course_name TEXT NOT NULL,
        teacher_id INTEGER NOT NULL,
        assessment_name TEXT NOT NULL,
        assessment_type TEXT NOT NULL,
        total_marks INTEGER NOT NULL,
        weightage REAL NOT NULL,
        assessment_date DATE NOT NULL,
        description TEXT,
        status TEXT DEFAULT 'active',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS grades (
        grade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        assessment_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        obtained_marks REAL NOT NULL,
        percentage REAL NOT NULL,
        remarks TEXT,
        graded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id),
        FOREIGN KEY (student_id) REFERENCES students(student_id)
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS course_results (
        result_id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER NOT NULL,
        course_name TEXT NOT NULL,
        total_weightage REAL NOT NULL,
        obtained_weightage REAL NOT NULL,
        final_percentage REAL NOT NULL,
        final_grade TEXT NOT NULL,
        status TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (student_id) REFERENCES students(student_id)
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        created_by INTEGER NOT NULL,
        created_by_role TEXT NOT NULL CHECK (created_by_role IN ('admin', 'teacher')),
        target_audience TEXT NOT NULL,
        specific_course TEXT,
        read_by TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );''')

    db.execute('''CREATE TABLE IF NOT EXISTS messages (
    message_id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL,
    sender_role TEXT NOT NULL CHECK (sender_role IN ('admin', 'teacher', 'student')),
    recipient_id INTEGER NOT NULL,
    recipient_role TEXT NOT NULL CHECK (recipient_role IN ('admin', 'teacher', 'student')),
    subject TEXT NOT NULL,
    message_body TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    read_at DATETIME NULL
    );''')


    # Insert default admin account (password: admin123)
    from werkzeug.security import generate_password_hash
    default_password = generate_password_hash('admin123')
    
    db.execute('''INSERT OR IGNORE INTO admin (name, email, password, phone, status) 
                  VALUES (?, ?, ?, ?, ?)''', 
               'System Admin', 'admin@institute.com', default_password, '+1234567890', 1)

    print("Database setup completed successfully!")

if __name__ == "__main__":
    setup_database()
