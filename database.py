import sqlite3
from werkzeug.security import generate_password_hash
import os

def setup_database():
    """Setup database with native SQLite3"""
    # Delete existing database to start fresh
    if os.path.exists('institute.db'):
        os.remove('institute.db')

    # Create new database connection
    conn = sqlite3.connect("institute.db")
    cursor = conn.cursor()

    try:
        # Create tables with proper schema
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin (
            admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            status INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS teachers (
            teacher_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT,
            subject TEXT,
            status INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS students (
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
            fee_status TEXT DEFAULT 'unpaid' CHECK (fee_status IN ('paid', 'unpaid', 'partial')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT UNIQUE NOT NULL,
            teacher_id INTEGER,
            fee DECIMAL(10,2) DEFAULT 0,
            duration TEXT,
            description TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
        );''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS attendance (
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

        cursor.execute('''CREATE TABLE IF NOT EXISTS assessments (
            assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_name TEXT NOT NULL,
            teacher_id INTEGER NOT NULL,
            assessment_name TEXT NOT NULL,
            assessment_type TEXT NOT NULL,
            total_marks INTEGER NOT NULL,
            weightage REAL NOT NULL,
            assessment_date DATE NOT NULL,
            description TEXT,
            status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (teacher_id) REFERENCES teachers(teacher_id)
        );''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS grades (
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

        cursor.execute('''CREATE TABLE IF NOT EXISTS course_results (
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

        cursor.execute('''CREATE TABLE IF NOT EXISTS notifications (
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

        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (
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

        cursor.execute('''CREATE TABLE IF NOT EXISTS finance_ledger (
            ledger_id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            transaction_type TEXT NOT NULL CHECK (transaction_type IN ('income', 'expenditure')),
            amount DECIMAL(10,2) NOT NULL CHECK (amount > 0),
            description TEXT NOT NULL,
            created_by INTEGER NOT NULL,
            created_by_role TEXT NOT NULL CHECK (created_by_role IN ('admin', 'teacher')),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );''')

        print("Creating default admin account...")
        default_password = generate_password_hash('admin123')
        cursor.execute('''INSERT OR IGNORE INTO admin (name, email, password, phone, status)
                         VALUES (?, ?, ?, ?, ?)''',
                      ('System Admin', 'admin@institute.com', default_password, '+1234567890', 1))

        conn.commit()
        print("✅ Database setup completed successfully!")
        print("📧 Email: admin@institute.com")
        print("🔒 Password: admin123")

    except Exception as e:
        print(f"Error setting up database: {str(e)}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    setup_database()
