import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_NAME = "bot_stats.db"

def init_db():
    """Initialize the database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            language_code TEXT,
            joined_at TIMESTAMP,
            last_seen TIMESTAMP,
            message_count INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()

def get_user(user_id):
    """Retrieve user details."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_user(user_id, username, first_name, language_code):
    """
    Update user stats or insert new user.
    Returns: (is_new_user, user_data)
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    now = datetime.now()
    
    # Check if user exists
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    existing_user = cursor.fetchone()
    
    is_new = False
    
    if existing_user is None:
        is_new = True
        cursor.execute('''
            INSERT INTO users (user_id, username, first_name, language_code, joined_at, last_seen, message_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, username, first_name, language_code, now, now))
    else:
        cursor.execute('''
            UPDATE users 
            SET username = ?, first_name = ?, language_code = ?, last_seen = ?, message_count = message_count + 1
            WHERE user_id = ?
        ''', (username, first_name, language_code, now, user_id))
        
    conn.commit()
    conn.close()
    
    return is_new

def get_statistics():
    """
    Get bot statistics.
    Returns a dictionary with stats.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Total users
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    
    # Active users in last 24 hours
    # SQLite datetime comparison
    cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen > datetime('now', '-1 day')")
    active_24h = cursor.fetchone()[0]
    
    # Top 5 users by message count
    cursor.execute('SELECT username, first_name, message_count FROM users ORDER BY message_count DESC LIMIT 5')
    top_users = cursor.fetchall()
    
    conn.close()
    
    return {
        "total_users": total_users,
        "active_24h": active_24h,
        "top_users": top_users
    }
