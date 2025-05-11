import re
import sqlite3
import dns.resolver
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from datetime import datetime
now = datetime.now()
if now.hour >= 1 and now.hour < 8:
    print("Bot sleeping... 💤")
    exit()

# === Load fake email domains ===
FAKE_DOMAINS = []
try:
    with open("fake_domains.txt") as f:
        FAKE_DOMAINS = [line.strip().lower() for line in f if line.strip()]
except FileNotFoundError:
    FAKE_DOMAINS = []

# === Helper Functions ===
def is_valid_email_domain(email):
    try:
        domain = email.split('@')[1]
        dns.resolver.resolve(domain, 'MX')
        return True
    except:
        return False

def is_strong_password(password):
    return len(password) >= 6 and any(char.isdigit() for char in password)

def is_disposable(email):
    domain = email.split('@')[1].lower()
    return domain in FAKE_DOMAINS

# === Database Setup ===
conn = sqlite3.connect("bot.db", check_same_thread=False)
cur = conn.cursor()

# Ensure the users table is set up correctly with the `bkash_number` column
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0,
    submissions_today INTEGER DEFAULT 0,
    last_submit_date TEXT,
    bkash_number TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    email TEXT UNIQUE,
    password TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount REAL,
    status TEXT
)""")
# Add table to store the email price and submission limit
cur.execute("""CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY,
    email_price REAL,
    submission_limit INTEGER DEFAULT 10
)""")
conn.commit()

# Set default email price and submission limit if not already set
cur.execute("SELECT email_price, submission_limit FROM settings WHERE id = 1")
if not cur.fetchone():
    cur.execute("INSERT INTO settings (id, email_price, submission_limit) VALUES (1, 0.05, 10)")
    conn.commit()

ADMIN_ID = 5222442956  # Replace with your actual Telegram ID

# === Telegram Handlers ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
    conn.commit()

    # Create a text banner to greet the user
    banner_text = """
    🎉 Welcome to the Email-Reward Bot! 🎉

    🚀 Send your email:password to earn rewards.
    📈 Limit: 10 submissions per day.
    📧 Email Submit Like :Email:password

    📊 Use /balance to check your balance.
    💸 Use /withdraw to request a withdrawal.

    Let's get started!
    """

    # Send the banner message to the user
    await update.message.reply_text(banner_text)


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    bal = result[0] if result else 0
    await update.message.reply_text(f"💰 Your balance: ${bal:.2f}")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    balance = result[0] if result else 0

    if balance < 1.0:
        return await update.message.reply_text(f"🚫 Need $1.00 to withdraw. You have ${balance:.2f}")

    await update.message.reply_text("📱 Please send your Bkash number:")
    context.user_data['awaiting_bkash'] = True

async def handle_submission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if context.user_data.get('awaiting_bkash'):
        bkash_number = text
        if not re.match(r'^01[3-9]\d{8}$', bkash_number):
            return await update.message.reply_text("❌ Invalid Bkash number. Try again.")

        cur.execute("UPDATE users SET balance = balance - 1.0, bkash_number = ? WHERE user_id = ?", (bkash_number, user_id))
        cur.execute("INSERT INTO withdrawals (user_id, amount, status) VALUES (?, ?, 'pending')", (user_id, 1.0))
        conn.commit()
        context.user_data['awaiting_bkash'] = False

        return await update.message.reply_text("✅ Withdrawal requested to Bkash. Admin will review it soon.")

    if ':' not in text or len(text.split(":")) != 2:
        return await update.message.reply_text("❌ Use format: email:password")

    email, password = text.split(":", 1)
    email = email.strip()
    password = password.strip()

    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return await update.message.reply_text("❌ Invalid email format.")

    if not is_valid_email_domain(email):
        return await update.message.reply_text("❌ Email domain not found (maybe fake or disposable).")

    if is_disposable(email):
        return await update.message.reply_text("❌ Disposable email detected. Please use a real email.")

    if not is_strong_password(password):
        return await update.message.reply_text("❌ Password too weak (must be 6+ chars & include numbers).")

    cur.execute("SELECT 1 FROM emails WHERE email = ?", (email,))
    if cur.fetchone():
        return await update.message.reply_text("⚠️ This email was already submitted.")

    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute("SELECT submissions_today, last_submit_date FROM users WHERE user_id = ?", (user_id,))
    user = cur.fetchone()

    if user:
        count, last_date = user
        if last_date != today:
            count = 0
            cur.execute("UPDATE users SET submissions_today = 0, last_submit_date = ? WHERE user_id = ?", (today, user_id))
            conn.commit()

        # Get the current submission limit from the settings table
        cur.execute("SELECT submission_limit FROM settings WHERE id = 1")
        submission_limit = cur.fetchone()[0]

        if count >= submission_limit:
            return await update.message.reply_text(f"🚫 Submission limit of {submission_limit} reached for today.")

    # Get current email price from the database
    cur.execute("SELECT email_price FROM settings WHERE id = 1")
    email_price = cur.fetchone()[0]

    cur.execute("INSERT INTO emails (user_id, email, password) VALUES (?, ?, ?)", (user_id, email, password))
    cur.execute("UPDATE users SET balance = balance + ? , submissions_today = submissions_today + 1, last_submit_date = ? WHERE user_id = ?", (email_price, today, user_id))
    conn.commit()

    await update.message.reply_text(f"✅ {email_price:.2f} credited! Current balance updated.")

async def set_submission_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You're not the admin.")

    try:
        new_limit = int(context.args[0])
        if new_limit < 1:
            raise ValueError("Submission limit must be at least 1.")

        cur.execute("UPDATE settings SET submission_limit = ? WHERE id = 1", (new_limit,))
        conn.commit()
        await update.message.reply_text(f"✅ Submission limit updated to {new_limit} submissions per day.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Please provide a valid submission limit. Usage: /set_submission_limit <limit>")

async def set_email_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You're not the admin.")

    try:
        new_price = float(context.args[0])
        if new_price < 0:
            raise ValueError("Email price must be a positive value.")

        cur.execute("UPDATE settings SET email_price = ? WHERE id = 1", (new_price,))
        conn.commit()
        await update.message.reply_text(f"✅ Email price updated to ${new_price:.2f} per submission.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Please provide a valid price. Usage: /set_email_price <price>")

async def show_all_user_submissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You're not the admin.")

    cur.execute("SELECT user_id, email, password FROM emails")
    rows = cur.fetchall()
    if not rows:
        return await update.message.reply_text("No submissions yet.")

    message = "User Submissions:\n"
    for row in rows:
        user_id, email, password = row
        message += f"User ID: {user_id}\nEmail: {email}\nPassword: {password}\n\n"
    
    await update.message.reply_text(message)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("🚫 You're not the admin.")

    cur.execute("SELECT id, user_id, amount, status FROM withdrawals WHERE status = 'pending'")
    rows = cur.fetchall()
    if not rows:
        return await update.message.reply_text("✅ No pending withdrawals.")

    for row in rows:
        w_id, u_id, amount, status = row
        cur.execute("SELECT bkash_number FROM users WHERE user_id = ?", (u_id,))
        bkash_number = cur.fetchone()
        bkash_number = bkash_number[0] if bkash_number else "N/A"

        keyboard = [
            [InlineKeyboardButton("Approve ✅", callback_data=f"approve:{w_id}"),
             InlineKeyboardButton("Reject ❌", callback_data=f"reject:{w_id}")]
        ]
        markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Request ID: {w_id}\nUser: {u_id}\nAmount: ${amount:.2f}\nBkash Number: {bkash_number}", reply_markup=markup)

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    query = update.callback_query
    await query.answer()
    action, wid = query.data.split(":")
    wid = int(wid)

    if action == "approve":
        cur.execute("UPDATE withdrawals SET status = 'approved' WHERE id = ?", (wid,))
        conn.commit()
        await query.edit_message_text("✅ Approved!")
    elif action == "reject":
        cur.execute("UPDATE withdrawals SET status = 'rejected' WHERE id = ?", (wid,))
        cur.execute("SELECT user_id FROM withdrawals WHERE id = ?", (wid,))
        u_id = cur.fetchone()[0]
        cur.execute("UPDATE users SET balance = balance + 1.0 WHERE user_id = ?", (u_id,))
        conn.commit()
        await query.edit_message_text("❌ Rejected and refunded.")

if __name__ == "__main__":
    app = ApplicationBuilder().token("7593732152:AAE-drV7n_B9R_Jvgip5rpYB-3xyjwCVH2c").build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("set_submission_limit", set_submission_limit))  # New handler to change the submission limit
    app.add_handler(CommandHandler("set_email_price", set_email_price))  # New handler to change email price
    app.add_handler(CommandHandler("show_all_user_submissions", show_all_user_submissions))  # New handler to show all submissions
    app.add_handler(CommandHandler("admin", admin))  # Admin command to handle withdrawals
    app.add_handler(CallbackQueryHandler(handle_callback))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_submission))

    app.run_polling()
