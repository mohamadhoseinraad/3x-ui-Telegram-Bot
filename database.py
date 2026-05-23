"""
Database operations for the VPN bot
"""
import sqlite3
import logging
from datetime import datetime, timedelta
from config import DB_FILE

logger = logging.getLogger(__name__)

def init_db():
    """Initialize database tables if they don't exist"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS web_accounts (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        contact_info TEXT,
        linked_user_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_login_at TIMESTAMP,
        FOREIGN KEY (linked_user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS invite_codes (
        code TEXT PRIMARY KEY,
        created_by_admin_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        used_by_username TEXT,
        used_by_user_id INTEGER,
        used_at TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        FOREIGN KEY (used_by_username) REFERENCES web_accounts (username),
        FOREIGN KEY (used_by_user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS configs (
        config_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        email TEXT UNIQUE,
        client_id TEXT,
        total_gb REAL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active BOOLEAN DEFAULT TRUE,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        setting_key TEXT PRIMARY KEY,
        setting_value TEXT NOT NULL
    )
    ''')

    default_expiry_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    cursor.execute(
        'INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)',
        ('max_config_gb', '0')
    )
    cursor.execute(
        'INSERT OR IGNORE INTO app_settings (setting_key, setting_value) VALUES (?, ?)',
        ('global_expiry_date', default_expiry_date)
    )

    # Check if last_notified column exists in configs table
    cursor.execute("PRAGMA table_info(configs)")
    columns = [column_info[1] for column_info in cursor.fetchall()]

    # Add last_notified column if it doesn't exist
    if 'last_notified' not in columns:
        logger.info("Adding last_notified column to configs table")
        cursor.execute('''
        ALTER TABLE configs
        ADD COLUMN last_notified TIMESTAMP
        ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS status_logs (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_id INTEGER,
        remaining_gb REAL,
        remaining_days REAL,
        checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (config_id) REFERENCES configs (config_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        plan TEXT,
        receipt_file_id TEXT,
        status TEXT DEFAULT 'pending',
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        approved_at TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        subject TEXT,
        status TEXT DEFAULT 'open',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS ticket_messages (
        message_id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER,
        sender_id INTEGER,
        message TEXT,
        is_admin BOOLEAN,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (ticket_id) REFERENCES tickets (ticket_id),
        FOREIGN KEY (sender_id) REFERENCES users (user_id)
    )''')

    conn.commit()
    conn.close()

def get_or_create_user(user_id, username, first_name, last_name):
    """Get or create a user record"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO users (user_id, username, first_name, last_name)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(user_id) DO UPDATE SET
        username = COALESCE(excluded.username, users.username),
        first_name = COALESCE(excluded.first_name, users.first_name),
        last_name = COALESCE(excluded.last_name, users.last_name)
    ''', (user_id, username, first_name, last_name))

    conn.commit()
    conn.close()
    return user_id


def get_web_account(username):
    """Get a web login account by username"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        'SELECT username, password_hash, contact_info, linked_user_id, created_at, last_login_at FROM web_accounts WHERE username = ?',
        (username,)
    )
    account = cursor.fetchone()
    conn.close()
    return account


def get_app_settings():
    """Get application-wide service policy settings."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('SELECT setting_key, setting_value FROM app_settings')
    settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
    conn.close()

    default_expiry_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    return {
        'max_config_gb': settings.get('max_config_gb', '0') or '0',
        'global_expiry_date': settings.get('global_expiry_date', default_expiry_date) or default_expiry_date,
    }


def update_app_settings(max_config_gb=None, global_expiry_date=None):
    """Update application-wide service policy settings."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if max_config_gb is not None:
        cursor.execute(
            '''
            INSERT INTO app_settings (setting_key, setting_value)
            VALUES ('max_config_gb', ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            ''',
            (str(max_config_gb),)
        )

    if global_expiry_date is not None:
        cursor.execute(
            '''
            INSERT INTO app_settings (setting_key, setting_value)
            VALUES ('global_expiry_date', ?)
            ON CONFLICT(setting_key) DO UPDATE SET setting_value = excluded.setting_value
            ''',
            (global_expiry_date,)
        )

    conn.commit()
    conn.close()


def get_service_policy():
    """Return parsed service policy values used by web and bot flows."""
    settings = get_app_settings()
    max_config_gb = float(settings['max_config_gb'] or 0)
    try:
        expiry_date = datetime.strptime(settings['global_expiry_date'], '%Y-%m-%d')
    except ValueError:
        expiry_date = datetime.now() + timedelta(days=30)

    expiry_time_ms = int(datetime(expiry_date.year, expiry_date.month, expiry_date.day, 23, 59, 59).timestamp() * 1000)
    return {
        'max_config_gb': max_config_gb,
        'global_expiry_date': expiry_date.strftime('%Y-%m-%d'),
        'global_expiry_time_ms': expiry_time_ms,
    }


def has_web_accounts():
    """Return True when at least one web account exists."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT 1 FROM web_accounts LIMIT 1')
    exists = cursor.fetchone() is not None

    conn.close()
    return exists


def save_web_account(username, password_hash, contact_info=None, linked_user_id=None):
    """Create or update a web login account"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO web_accounts (username, password_hash, contact_info, linked_user_id, last_login_at)
    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
    ON CONFLICT(username) DO UPDATE SET
        password_hash = excluded.password_hash,
        contact_info = COALESCE(excluded.contact_info, web_accounts.contact_info),
        linked_user_id = COALESCE(excluded.linked_user_id, web_accounts.linked_user_id),
        last_login_at = CURRENT_TIMESTAMP
    ''', (username, password_hash, contact_info, linked_user_id))

    conn.commit()
    conn.close()


def update_web_account_login(username, contact_info=None, linked_user_id=None):
    """Update last login metadata for a web account"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    UPDATE web_accounts
    SET contact_info = COALESCE(?, contact_info),
        linked_user_id = COALESCE(?, linked_user_id),
        last_login_at = CURRENT_TIMESTAMP
    WHERE username = ?
    ''', (contact_info, linked_user_id, username))

    conn.commit()
    conn.close()


def link_web_account_to_telegram_id(username, telegram_user_id, first_name=None, last_name=None):
    """Link a web account to a Telegram user id and migrate any existing user-owned rows."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        'SELECT linked_user_id FROM web_accounts WHERE username = ?',
        (username,)
    )
    account = cursor.fetchone()
    if not account:
        conn.close()
        return False, 'Web account not found'

    current_user_id = account['linked_user_id']
    if current_user_id is not None and current_user_id > 0 and current_user_id != telegram_user_id:
        conn.close()
        return False, 'This web account is already linked to another Telegram user id.'

    def update_foreign_keys(source_user_id, target_user_id):
        cursor.execute('UPDATE configs SET user_id = ? WHERE user_id = ?', (target_user_id, source_user_id))
        cursor.execute('UPDATE payments SET user_id = ? WHERE user_id = ?', (target_user_id, source_user_id))
        cursor.execute('UPDATE tickets SET user_id = ? WHERE user_id = ?', (target_user_id, source_user_id))
        cursor.execute('UPDATE ticket_messages SET sender_id = ? WHERE sender_id = ?', (target_user_id, source_user_id))
        cursor.execute('UPDATE invite_codes SET used_by_user_id = ? WHERE used_by_user_id = ?', (target_user_id, source_user_id))

    try:
        conn.execute('BEGIN')

        cursor.execute('SELECT user_id, username, first_name, last_name FROM users WHERE user_id = ?', (telegram_user_id,))
        target_user = cursor.fetchone()
        cursor.execute('SELECT user_id, username, first_name, last_name FROM users WHERE user_id = ?', (current_user_id,))
        source_user = cursor.fetchone() if current_user_id is not None else None

        fallback_username = username
        fallback_first_name = first_name or username

        if current_user_id == telegram_user_id:
            if target_user is None:
                cursor.execute(
                    'INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                    (telegram_user_id, fallback_username, fallback_first_name, last_name)
                )
        elif current_user_id is None:
            if target_user is None:
                cursor.execute(
                    'INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                    (telegram_user_id, fallback_username, fallback_first_name, last_name)
                )
            else:
                cursor.execute(
                    '''
                    UPDATE users
                    SET username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name)
                    WHERE user_id = ?
                    ''',
                    (fallback_username, fallback_first_name, last_name, telegram_user_id),
                )
        else:
            if target_user is None:
                if source_user is not None:
                    update_foreign_keys(current_user_id, telegram_user_id)
                    cursor.execute(
                        'UPDATE users SET user_id = ?, username = COALESCE(?, username), first_name = COALESCE(?, first_name), last_name = COALESCE(?, last_name) WHERE user_id = ?',
                        (telegram_user_id, fallback_username, fallback_first_name, last_name, current_user_id)
                    )
                else:
                    cursor.execute(
                        'INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)',
                        (telegram_user_id, fallback_username, fallback_first_name, last_name)
                    )
            else:
                if source_user is not None:
                    update_foreign_keys(current_user_id, telegram_user_id)
                    cursor.execute('DELETE FROM users WHERE user_id = ?', (current_user_id,))
                cursor.execute(
                    '''
                    UPDATE users
                    SET username = COALESCE(?, username),
                        first_name = COALESCE(?, first_name),
                        last_name = COALESCE(?, last_name)
                    WHERE user_id = ?
                    ''',
                    (fallback_username, fallback_first_name, last_name, telegram_user_id),
                )

        cursor.execute(
            'UPDATE web_accounts SET linked_user_id = ?, contact_info = COALESCE(contact_info, ?) WHERE username = ?',
            (telegram_user_id, str(telegram_user_id), username)
        )

        conn.commit()
        return True, telegram_user_id
    except Exception:
        conn.rollback()
        logger.exception('Failed to link web account %s to Telegram id %s', username, telegram_user_id)
        return False, 'Unable to link Telegram user id'
    finally:
        conn.close()


def create_invite_code(code, created_by_admin_id):
    """Create a one-time invite code"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        '''
        INSERT INTO invite_codes (code, created_by_admin_id)
        VALUES (?, ?)
        ''',
        (code, created_by_admin_id),
    )

    conn.commit()
    conn.close()


def get_invite_code(code):
    """Fetch a single invite code record"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT code, created_by_admin_id, created_at, used_by_username, used_by_user_id, used_at, is_active
        FROM invite_codes
        WHERE code = ?
        ''',
        (code,),
    )
    invite_code = cursor.fetchone()
    conn.close()
    return invite_code


def list_invite_codes(limit=50):
    """List recent invite codes for the admin panel"""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        '''
        SELECT code, created_by_admin_id, created_at, used_by_username, used_by_user_id, used_at, is_active
        FROM invite_codes
        ORDER BY created_at DESC
        LIMIT ?
        ''',
        (limit,),
    )
    invite_codes = cursor.fetchall()
    conn.close()
    return invite_codes


def consume_invite_code(code, username, linked_user_id):
    """Mark an invite code as used exactly once"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        '''
        UPDATE invite_codes
        SET used_by_username = ?,
            used_by_user_id = ?,
            used_at = CURRENT_TIMESTAMP,
            is_active = FALSE
        WHERE code = ? AND used_at IS NULL AND is_active = TRUE
        ''',
        (username, linked_user_id, code),
    )

    updated = cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0

def save_new_config(user_id, email, client_id, total_gb):
    """Save a new VPN configuration"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO configs (user_id, email, client_id, total_gb)
    VALUES (?, ?, ?, ?)
    ''', (user_id, email, client_id, total_gb))

    config_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return config_id

def get_user_configs(user_id):
    """Get all VPN configurations for a user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT config_id, email, client_id, total_gb, is_active
    FROM configs
    WHERE user_id = ?
    ORDER BY created_at DESC
    ''', (user_id,))

    configs = cursor.fetchall()
    conn.close()
    return configs

def log_status_check(config_id, remaining_gb, remaining_days):
    """Log a status check for a VPN configuration"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO status_logs (config_id, remaining_gb, remaining_days)
    VALUES (?, ?, ?)
    ''', (config_id, remaining_gb, remaining_days))

    conn.commit()
    conn.close()

def save_payment_request(user_id, plan_name, file_id):
    """Save a payment request"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    INSERT INTO payments (user_id, plan, receipt_file_id)
    VALUES (?, ?, ?)
    ''', (user_id, plan_name, file_id))

    payment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return payment_id

def update_payment_status(payment_id, status, approved_at=None):
    """Update the status of a payment"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if status == 'approved' and approved_at is None:
        approved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    cursor.execute('''
    UPDATE payments SET status = ?, approved_at = ?
    WHERE payment_id = ?
    ''', (status, approved_at, payment_id))

    conn.commit()
    conn.close()

def get_payment_info(payment_id):
    """Get payment information"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT p.user_id, p.plan, u.username 
    FROM payments p
    JOIN users u ON p.user_id = u.user_id
    WHERE p.payment_id = ? AND p.status = 'pending'
    ''', (payment_id,))

    payment = cursor.fetchone()
    conn.close()
    return payment

def update_config_active_status(email, user_id, is_active):
    """Update the active status of a configuration"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    UPDATE configs 
    SET is_active = ?
    WHERE email = ? AND user_id = ?
    ''', (is_active, email, user_id))

    conn.commit()
    conn.close()

def get_client_id_by_email(email, user_id):
    """Get client ID for an email and user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT client_id FROM configs WHERE email = ? AND user_id = ?
    ''', (email, user_id))

    result = cursor.fetchone()
    conn.close()

    return result[0] if result else None

def check_trial_usage(user_id, gb_amount):
    """Check if user has already used a trial of the specified GB amount"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT COUNT(*) FROM configs 
    WHERE user_id = ? AND total_gb = ? AND 
          created_at >= datetime('now', '-1 year')
    ''', (user_id, gb_amount))

    already_used = cursor.fetchone()[0]
    conn.close()

    return already_used > 0

def get_all_users():
    """Get all users"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT user_id FROM users')
    users = [user[0] for user in cursor.fetchall()]
    conn.close()

    return users

def create_ticket(user_id, subject):
    """Create a new support ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO tickets (user_id, subject) VALUES (?, ?)",
        (user_id, subject)
    )
    ticket_id = cursor.lastrowid

    conn.commit()
    conn.close()
    return ticket_id

def add_ticket_message(ticket_id, sender_id, message, is_admin):
    """Add a message to a ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "INSERT INTO ticket_messages (ticket_id, sender_id, message, is_admin) VALUES (?, ?, ?, ?)",
        (ticket_id, sender_id, message, is_admin)
    )

    conn.commit()
    conn.close()

def get_user_tickets(user_id):
    """Get all tickets for a user"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT ticket_id, subject, status, created_at 
    FROM tickets 
    WHERE user_id = ?
    ORDER BY created_at DESC
    ''', (user_id,))

    tickets = cursor.fetchall()
    conn.close()
    return tickets

def get_ticket_info(ticket_id):
    """Get information about a ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT t.subject, t.status, t.user_id, u.first_name, u.username 
    FROM tickets t
    JOIN users u ON t.user_id = u.user_id
    WHERE t.ticket_id = ?
    ''', (ticket_id,))

    ticket_info = cursor.fetchone()
    conn.close()
    return ticket_info

def get_ticket_messages(ticket_id):
    """Get all messages for a ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT message, is_admin, created_at 
    FROM ticket_messages 
    WHERE ticket_id = ?
    ORDER BY created_at
    ''', (ticket_id,))

    messages = cursor.fetchall()
    conn.close()
    return messages

def close_ticket(ticket_id):
    """Close a ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE tickets SET status = 'closed' WHERE ticket_id = ?",
        (ticket_id,)
    )

    conn.commit()
    conn.close()

def update_ticket_status(ticket_id, status):
    """Update the status of a ticket"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE tickets SET status = ? WHERE ticket_id = ?",
        (status, ticket_id)
    )

    conn.commit()
    conn.close()

def get_all_tickets():
    """Get all tickets"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT t.ticket_id, t.subject, t.status, u.first_name, u.username 
    FROM tickets t
    JOIN users u ON t.user_id = u.user_id
    ORDER BY t.created_at DESC
    LIMIT 50
    ''')

    tickets = cursor.fetchall()
    conn.close()
    return tickets

def verify_ticket_access(ticket_id, user_id, admin_ids):
    """Check if user has access to this ticket (as owner or admin)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('SELECT user_id FROM tickets WHERE ticket_id = ?', (ticket_id,))
    result = cursor.fetchone()
    conn.close()

    if not result:
        return False, None

    ticket_owner_id = result[0]
    has_access = (ticket_owner_id == user_id) or (user_id in admin_ids)

    return has_access, ticket_owner_id

def get_ticket_details(ticket_id):
    """Get complete details about a ticket including subject and status"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT t.subject, t.status, t.user_id, u.first_name, u.username 
    FROM tickets t
    JOIN users u ON t.user_id = u.user_id
    WHERE t.ticket_id = ?
    ''', (ticket_id,))

    ticket_info = cursor.fetchone()

    if not ticket_info:
        conn.close()
        return None

    # Get messages
    cursor.execute('''
    SELECT message, is_admin, created_at, sender_id 
    FROM ticket_messages 
    WHERE ticket_id = ?
    ORDER BY created_at
    ''', (ticket_id,))

    messages = cursor.fetchall()
    conn.close()

    return {
        'info': ticket_info,
        'messages': messages
    }

def get_formatted_ticket_messages(ticket_id, for_admin=False):
    """Get formatted ticket messages ready for display"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Get ticket info
    if for_admin:
        cursor.execute('''
        SELECT t.subject, t.status, t.user_id, u.first_name, u.username
        FROM tickets t
        JOIN users u ON t.user_id = u.user_id
        WHERE t.ticket_id = ?
        ''', (ticket_id,))
    else:
        cursor.execute('''
        SELECT subject, status
        FROM tickets
        WHERE ticket_id = ?
        ''', (ticket_id,))

    ticket_info = cursor.fetchone()

    if not ticket_info:
        conn.close()
        return None

    # Get messages
    cursor.execute('''
    SELECT message, is_admin, created_at
    FROM ticket_messages 
    WHERE ticket_id = ?
    ORDER BY created_at
    ''', (ticket_id,))

    messages = cursor.fetchall()
    conn.close()

    if for_admin:
        subject, status, owner_id, first_name, username = ticket_info
        message_text = f"📋 تیکت #{ticket_id}\n\n"
        message_text += f"📝 موضوع: {subject}\n"
        message_text += f"👤 کاربر: {first_name}" + (f" (@{username})" if username else "") + f"\n"
        message_text += f"📊 وضعیت: {status}\n\n"
    else:
        subject, status = ticket_info
        message_text = f"📋 تیکت #{ticket_id}\n\n"
        message_text += f"موضوع: {subject}\n"
        message_text += f"وضعیت: {status}\n\n"

    message_text += "📬 پیام ها:\n\n"

    for msg in messages:
        text, is_admin, timestamp = msg
        sender = "👤 پشتیبانی" if is_admin else "👤 شما"
        message_text += f"{sender} ({timestamp}):\n{text}\n\n"

    result = {
        'text': message_text,
        'status': status,
        'info': ticket_info
    }

    if for_admin:
        result['owner_id'] = owner_id

    return result

def get_user_tickets_list(user_id):
    """Get a formatted list of user tickets"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT ticket_id, subject, status, created_at 
    FROM tickets 
    WHERE user_id = ?
    ORDER BY created_at DESC
    ''', (user_id,))

    tickets = cursor.fetchall()
    conn.close()

    return tickets

def get_formatted_user_tickets(user_id):
    """Get user tickets with formatted status icons for display"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT ticket_id, subject, status, created_at 
    FROM tickets 
    WHERE user_id = ?
    ORDER BY created_at DESC
    ''', (user_id,))

    tickets = cursor.fetchall()
    conn.close()

    if not tickets:
        return None

    formatted_tickets = []
    for ticket in tickets:
        ticket_id, subject, status, created_at = ticket
        status_icon = "🟢" if status == 'open' else "🟡" if status == 'answered' else "🔴"

        # Truncate subject if needed
        display_subject = subject
        if len(subject) > 20:
            display_subject = subject[:20] + "..."

        formatted_tickets.append({
            'id': ticket_id,
            'subject': subject,
            'display_subject': display_subject,
            'status': status,
            'status_icon': status_icon,
            'created_at': created_at
        })

    return formatted_tickets

def get_ticket_conversation(ticket_id, user_id, admin_ids=None):
    """Get ticket conversation details with permission check

    Returns:
        dict: {'access': bool, 'ticket_info': tuple, 'messages': list, 'formatted_text': str} or None if no access
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Verify ticket belongs to user or user is admin
    cursor.execute('SELECT user_id FROM tickets WHERE ticket_id = ?', (ticket_id,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        return {'access': False, 'error': 'Ticket not found'}

    ticket_owner_id = result[0]
    has_access = (ticket_owner_id == user_id)

    # If admin_ids provided, check if user is admin
    if not has_access and admin_ids and user_id in admin_ids:
        has_access = True

    if not has_access:
        conn.close()
        return {'access': False, 'error': 'Access denied'}

    # Get ticket info
    cursor.execute('SELECT subject, status FROM tickets WHERE ticket_id = ?', (ticket_id,))
    ticket_info = cursor.fetchone()

    # Get messages
    cursor.execute('''
    SELECT message, is_admin, created_at 
    FROM ticket_messages 
    WHERE ticket_id = ?
    ORDER BY created_at
    ''', (ticket_id,))

    messages = cursor.fetchall()
    conn.close()

    if not ticket_info:
        return {'access': True, 'error': 'Ticket data not found'}

    subject, status = ticket_info

    # Format message text
    message_text = f"📋 تیکت #{ticket_id}\n\n"
    message_text += f"موضوع: {subject}\n"
    message_text += f"وضعیت: {status}\n\n"
    message_text += "📬 پیام ها:\n\n"

    for msg in messages:
        text, is_admin, timestamp = msg
        sender = "👤 پشتیبانی" if is_admin else "👤 شما"
        message_text += f"{sender} ({timestamp}):\n{text}\n\n"

    return {
        'access': True,
        'ticket_info': ticket_info,
        'messages': messages,
        'formatted_text': message_text,
        'owner_id': ticket_owner_id,
        'status': status
    }

def get_pending_payments():
    """Get all pending payment requests"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT p.payment_id, p.user_id, p.plan, u.first_name, u.username, p.receipt_file_id
    FROM payments p
    JOIN users u ON p.user_id = u.user_id
    WHERE p.status = 'pending'
    ORDER BY p.submitted_at
    ''')

    pending_payments = cursor.fetchall()
    conn.close()
    return pending_payments

def get_all_configs_with_users():
    """Get all active configs with user information for notification checking"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute('''
    SELECT c.config_id, c.user_id, c.email, c.client_id, c.total_gb, c.is_active, c.last_notified, 
           u.username, u.first_name
    FROM configs c
    JOIN users u ON c.user_id = u.user_id
    WHERE c.is_active = 1
    ''')

    rows = cursor.fetchall()
    conn.close()

    configs = []
    for row in rows:
        configs.append({
            'config_id': row[0],
            'user_id': row[1],
            'email': row[2],
            'client_id': row[3],
            'total_gb': row[4],
            'is_active': row[5],
            'last_notified': row[6],
            'username': row[7],
            'first_name': row[8]
        })

    return configs

def update_notification_sent(config_id):
    """Update the last_notified timestamp for a config"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''
    UPDATE configs 
    SET last_notified = ?
    WHERE config_id = ?
    ''', (current_time, config_id))

    conn.commit()
    conn.close()
    return True


def update_config_total_gb(email, user_id, additional_gb, extend_days=30):
    """Update the total_gb value of a configuration after extension and extend expiry date

    Args:
        email (str): Email identifier for the config
        user_id (int): User ID who owns the config
        additional_gb (int): Additional GB to add to the config
        extend_days (int, optional): Number of days to extend expiry. Defaults to 30.
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # First, get the current total_gb value
    cursor.execute('''
    SELECT total_gb FROM configs WHERE email = ? AND user_id = ?
    ''', (email, user_id))

    result = cursor.fetchone()
    if not result:
        conn.close()
        return False

    current_gb = result[0]
    new_total_gb = current_gb + additional_gb

    # Update the total_gb value and reset last_notified in the database
    # Resetting last_notified ensures users will get fresh notifications about their extended service
    cursor.execute('''
    UPDATE configs 
    SET total_gb = ?, last_notified = NULL
    WHERE email = ? AND user_id = ?
    ''', (new_total_gb, email, user_id))

    conn.commit()
    conn.close()
    return True


def delete_config_by_client_id(client_id):
    """Delete a configuration from the database by client_id

    Args:
        client_id (str): The client ID to delete

    Returns:
        bool: True if successful, False otherwise
    """
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    try:
        # Find the config_id first (needed for cascading deletions)
        cursor.execute('SELECT config_id FROM configs WHERE client_id = ?', (client_id,))
        result = cursor.fetchone()

        if not result:
            logger.warning(f"No config found with client_id: {client_id}")
            return False

        config_id = result[0]

        # Delete related records in status_logs first due to foreign key constraint
        cursor.execute('DELETE FROM status_logs WHERE config_id = ?', (config_id,))

        # Delete the config record
        cursor.execute('DELETE FROM configs WHERE client_id = ?', (client_id,))

        deleted_count = cursor.rowcount
        conn.commit()

        logger.info(f"Deleted config with client_id: {client_id} (affected rows: {deleted_count})")
        return deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting config with client_id {client_id}: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()
