import logging
import random
import string
import time
import re
import json
import os
import asyncio
import pytz
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAFAgBRvDOmw1KrZZ0Ku0hW5h8nbA0otcKw"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

ADMINS = [OWNER_ID]

# ============ TIME CONFIGURATION ============
MAINTENANCE_START_HOUR = 22
MAINTENANCE_END_HOUR = 8
MAINTENANCE_MANUAL = False

# ============ LIMITS ============
MAX_EMAIL_UPLOAD = 1000
MAX_QR_UPLOAD = 100
MAX_REVIEW_UPLOAD = 500

# ============ TIMEOUT CONFIGURATION ============
HTTPX_TIMEOUT = 120.0
TASK_TIMEOUT_MINUTES = 15
QR_EXPIRE_MINUTES = 5
REVIEW_EXPIRE_MINUTES = 10
COOLDOWN_MINUTES = 2

# ============ IST TIMEZONE ============
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    return datetime.now(IST)

def is_maintenance_mode():
    global MAINTENANCE_MANUAL
    if MAINTENANCE_MANUAL:
        return True
    now = get_ist_now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START_HOUR or current_hour < MAINTENANCE_END_HOUR:
        return True
    return False

def get_next_start_time():
    now = get_ist_now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START_HOUR:
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0) + timedelta(days=1)
    elif current_hour < MAINTENANCE_END_HOUR:
        next_start = now.replace(hour=MAINTENANCE_END_HOUR, minute=0, second=0, microsecond=0)
    else:
        next_start = None
    return next_start

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                default_keys = {
                    "users": {}, "pending": {}, "email_stock": [], "used_emails": [],
                    "withdraw_requests": [], "cooldowns": {}, "admins": [OWNER_ID],
                    "upload_counter": 0, "upload_history": [],
                    "qr_stock": [], "qr_used": [], "qr_upload_counter": 0, "qr_history": [],
                    "review_stock": [], "review_used": [], "review_upload_counter": 0, "review_history": [],
                    "pending_qr": {}, "pending_review": {}, "pending_approvals": {}
                }
                for key, default_val in default_keys.items():
                    if key not in data:
                        data[key] = default_val
                return data
        except Exception as e:
            logging.error(f"Error loading data: {e}")
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {}, "pending": {}, "email_stock": [], "used_emails": [],
        "withdraw_requests": [], "cooldowns": {}, "admins": [OWNER_ID],
        "upload_counter": 0, "upload_history": [],
        "qr_stock": [], "qr_used": [], "qr_upload_counter": 0, "qr_history": [],
        "review_stock": [], "review_used": [], "review_upload_counter": 0, "review_history": [],
        "pending_qr": {}, "pending_review": {}, "pending_approvals": {}
    }

def save_data(data):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, default=str, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Error saving data: {e}")
        return False

data = load_data()
ADMINS = data.get("admins", [OWNER_ID])

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def is_admin(user_id):
    return user_id in ADMINS or user_id == OWNER_ID

def get_admin_name(user_id):
    for admin in ADMINS:
        if admin == user_id:
            return "Owner" if user_id == OWNER_ID else f"Admin_{user_id}"
    return f"Admin_{user_id}"

# ============ SELF PING ============
PING_COUNT = 0

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    global PING_COUNT, data
    PING_COUNT += 1
    data = load_data()
    now = get_ist_now()
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔄 **BOT ALIVE** #{PING_COUNT}\n\n"
                 f"⏰ IST: {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Email: {len(data['email_stock'])}\n"
                 f"📱 QR: {len(data['qr_stock'])}\n"
                 f"📝 Review: {len(data['review_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending Approvals: {len(data.get('pending_approvals', {}))}"
        )
        logger.info(f"Self ping #{PING_COUNT} sent")
    except Exception as e:
        logger.error(f"Self ping failed: {e}")

# ============ CHECK TIMEOUT ============
def check_pending_timeout():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data["pending"].items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > TASK_TIMEOUT_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        if pending.get("type") == "email":
            email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
            data["email_stock"].append(email_data)
        elif pending.get("type") == "qr":
            data["qr_stock"].append(pending.get("qr_data"))
        elif pending.get("type") == "review":
            data["review_stock"].append(pending.get("review_data"))
        data["cooldowns"][user_id] = (now + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        del data["pending"][user_id]
        save_data(data)

async def check_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data["pending"]:
        check_pending_timeout()

# ============ CHECK QR EXPIRE ============
def check_qr_expire():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data.get("pending_qr", {}).items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > QR_EXPIRE_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending_qr"][user_id]
        data["qr_stock"].append(pending.get("qr_data"))
        del data["pending_qr"][user_id]
        save_data(data)

async def check_qr_expire_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data.get("pending_qr"):
        check_qr_expire()

# ============ CHECK REVIEW EXPIRE ============
def check_review_expire():
    global data
    now = get_ist_now()
    to_remove = []
    for user_id, pending in data.get("pending_review", {}).items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if start_time.tzinfo is None:
                    start_time = IST.localize(start_time)
                if (now - start_time).total_seconds() > REVIEW_EXPIRE_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending_review"][user_id]
        data["review_stock"].append(pending.get("review_data"))
        del data["pending_review"][user_id]
        save_data(data)

async def check_review_expire_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data.get("pending_review"):
        check_review_expire()

# ============ BROADCAST ============
async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text(
            "📢 **BROADCAST**\n\nUsage: `/broadcast [message]`",
            parse_mode='Markdown'
        )
        return
    message = " ".join(context.args)
    data = load_data()
    users = data.get("users", {})
    if not users:
        await update.message.reply_text("❌ No users found!", parse_mode='Markdown')
        return
    sent = 0
    failed = 0
    for uid in users.keys():
        try:
            await context.bot.send_message(
                int(uid),
                f"📢 **ANNOUNCEMENT**\n\n{message}\n\n👑 Admin: {ESCROW_USER}",
                parse_mode='Markdown'
            )
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(
        f"✅ **BROADCAST SENT!**\n\n📤 Sent: {sent}\n❌ Failed: {failed}\n👥 Total Users: {len(users)}",
        parse_mode='Markdown'
    )

# ============ MAINTENANCE ON/OFF ============
async def mainon_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MANUAL
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner!", parse_mode='Markdown')
        return
    MAINTENANCE_MANUAL = True
    await update.message.reply_text("🛠️ **MAINTENANCE MODE ON**", parse_mode='Markdown')

async def mainoff_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MAINTENANCE_MANUAL
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner!", parse_mode='Markdown')
        return
    MAINTENANCE_MANUAL = False
    await update.message.reply_text("✅ **MAINTENANCE MODE OFF**", parse_mode='Markdown')

# ============ NEW ADMIN ============
async def newadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data, ADMINS
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner!", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/newadmin [user_id]`", parse_mode='Markdown')
        return
    try:
        new_admin_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid ID!", parse_mode='Markdown')
        return
    if new_admin_id in ADMINS:
        await update.message.reply_text(f"⚠️ Already admin!", parse_mode='Markdown')
        return
    ADMINS.append(new_admin_id)
    data["admins"] = ADMINS
    save_data(data)
    await update.message.reply_text(f"✅ New admin added: `{new_admin_id}`", parse_mode='Markdown')

# ============ UPLOAD EMAIL ============
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    admin_username = update.effective_user.username or update.effective_user.first_name
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD EMAIL**\n\n"
            "/upload Name|Email|Pass|Recovery\n\n"
            "💡 Use 'skip' for no recovery:\n"
            "/upload Name|Email|Pass|skip\n\n"
            f"📦 Stock: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}",
            parse_mode='Markdown'
        )
        return
    
    if len(data["email_stock"]) >= MAX_EMAIL_UPLOAD:
        await update.message.reply_text(f"❌ Max limit {MAX_EMAIL_UPLOAD} reached!", parse_mode='Markdown')
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        email = email.strip()
        if "|" in email and len(data["email_stock"]) < MAX_EMAIL_UPLOAD:
            parts = email.split("|")
            if len(parts) == 4:
                name = parts[0].strip()
                gmail = parts[1].strip()
                password = parts[2].strip()
                recovery = parts[3].strip().lower()
                
                if recovery == "skip":
                    recovery = "No Recovery"
                
                processed_email = f"{name}|{gmail}|{password}|{recovery}|uploaded_by_{admin_username}"
                data["email_stock"].append(processed_email)
                data["upload_counter"] = data.get("upload_counter", 0) + 1
                data["upload_history"].append({
                    "id": data["upload_counter"], 
                    "raw": processed_email,
                    "uploaded_by": admin_username,
                    "status": "pending", 
                    "timestamp": get_ist_now().isoformat()
                })
                count += 1
            else:
                await update.message.reply_text(
                    f"❌ Invalid format: {email}\n\n"
                    "Use: Name|Email|Pass|Recovery",
                    parse_mode='Markdown'
                )
                return
    save_data(data)
    await update.message.reply_text(
        f"✅ **EMAIL UPLOADED!**\n\n📤 Added: {count}\n📦 Total: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}\n👤 Uploaded by: @{admin_username}",
        parse_mode='Markdown'
    )

# ============ UPLOAD QR ============
async def uploadqr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    admin_username = update.effective_user.username or update.effective_user.first_name
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(data["qr_stock"]) >= MAX_QR_UPLOAD:
        await update.message.reply_text(f"❌ Max {MAX_QR_UPLOAD} QR limit reached!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD QR**\n\n"
            "/uploadqr [qr_name_or_id]\n\n"
            f"📱 Stock: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}",
            parse_mode='Markdown'
        )
        return
    qr_data = " ".join(context.args)
    processed_qr = f"{qr_data}|uploaded_by_{admin_username}"
    data["qr_stock"].append(processed_qr)
    data["qr_upload_counter"] = data.get("qr_upload_counter", 0) + 1
    data["qr_history"].append({
        "id": data["qr_upload_counter"], 
        "data": processed_qr,
        "uploaded_by": admin_username,
        "status": "pending", 
        "timestamp": get_ist_now().isoformat()
    })
    save_data(data)
    await update.message.reply_text(
        f"✅ **QR UPLOADED!**\n\n📱 Added: {qr_data}\n📦 Total: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}\n👤 Uploaded by: @{admin_username}",
        parse_mode='Markdown'
    )

# ============ UPLOAD REVIEW ============
async def uploadr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    admin_username = update.effective_user.username or update.effective_user.first_name
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text(
            "📝 **UPLOAD REVIEW**\n\n"
            "/uploadr [review_message]\n\n"
            f"📝 Stock: {len(data['review_stock'])}",
            parse_mode='Markdown'
        )
        return
    review_data = " ".join(context.args)
    processed_review = f"{review_data}|uploaded_by_{admin_username}"
    data["review_stock"].append(processed_review)
    data["review_upload_counter"] = data.get("review_upload_counter", 0) + 1
    data["review_history"].append({
        "id": data["review_upload_counter"], 
        "data": processed_review,
        "uploaded_by": admin_username,
        "status": "pending", 
        "timestamp": get_ist_now().isoformat()
    })
    save_data(data)
    await update.message.reply_text(
        f"✅ **REVIEW UPLOADED!**\n\n📝 Added: {review_data[:50]}...\n📦 Total: {len(data['review_stock'])}\n👤 Uploaded by: @{admin_username}",
        parse_mode='Markdown'
    )

# ============ EMAIL COMMAND ============
async def email_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\nBot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n⏰ Timing: 10 PM - 8 AM IST",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("cooldowns", {}):
        cooldown_end = datetime.fromisoformat(data["cooldowns"][user_id])
        if cooldown_end.tzinfo is None:
            cooldown_end = IST.localize(cooldown_end)
        if get_ist_now() < cooldown_end:
            remaining = (cooldown_end - get_ist_now()).seconds // 60
            await update.message.reply_text(f"⏳ Cooldown: {remaining + 1} min", parse_mode='Markdown')
            return
        else:
            del data["cooldowns"][user_id]
            save_data(data)
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ You already have pending work! Use /cancel first.", parse_mode='Markdown')
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No stock! Admin notified.", parse_mode='Markdown')
        for admin in ADMINS:
            try:
                await context.bot.send_message(admin, "⚠️ EMAIL STOCK EMPTY! Use /upload")
            except:
                pass
        return
    
    email_data = data["email_stock"].pop(0)
    parts = email_data.split("|")
    
    uploaded_by = "Unknown Admin"
    if len(parts) >= 5 and parts[4].startswith("uploaded_by_"):
        uploaded_by = parts[4].replace("uploaded_by_", "")
        email_data_clean = "|".join(parts[:4])
    else:
        email_data_clean = email_data
    
    parts_clean = email_data_clean.split("|")
    if len(parts_clean) == 4:
        name = parts_clean[0].strip()
        gmail = parts_clean[1].strip()
        password = parts_clean[2].strip()
        recovery = parts_clean[3].strip()
    else:
        gmail, password, recovery = parts_clean[0].strip(), parts_clean[1].strip(), parts_clean[2].strip()
        name = username
    
    data["pending"][user_id] = {
        "type": "email", 
        "gmail": gmail, 
        "password": password,
        "recovery": recovery,
        "name": name,
        "username": username,
        "uploaded_by": uploaded_by,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"📧 **EMAIL ASSIGNED!**\n"
                f"👤 @{username} (ID: `{user_id}`)\n"
                f"📧 `{gmail}`\n"
                f"👑 Uploaded by: @{uploaded_by}\n"
                f"📦 Left: {len(data['email_stock'])}"
            )
        except:
            pass
    
    await update.message.reply_text(
        f"📧 **EMAIL ASSIGNED!**\n\n"
        f"👤 Name: `{name}`\n"
        f"📧 Email: `{gmail}`\n"
        f"🔑 Pass: `{password}`\n"
        f"📧 Recovery: `{recovery}`\n"
        f"👑 Uploaded by: @{uploaded_by}\n\n"
        "📌 Login → /skip2fa → Upload QR → OTP → Screenshot\n\n"
        f"⏰ {TASK_TIMEOUT_MINUTES} min timeout!\n"
        "/cancel - Cancel",
        parse_mode='Markdown'
    )

# ============ QR COMMAND ============
async def qr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(f"🛠️ **MAINTENANCE MODE**\n\nBot will be back at **{time_str}**", parse_mode='Markdown')
        else:
            await update.message.reply_text("🛠️ **MAINTENANCE MODE**\n\n⏰ Timing: 10 PM - 8 AM IST", parse_mode='Markdown')
        return
    
    if user_id in data.get("pending_qr", {}):
        await update.message.reply_text("⏳ You already have a QR!", parse_mode='Markdown')
        return
    
    if not data["qr_stock"]:
        await update.message.reply_text("❌ No QR available!", parse_mode='Markdown')
        return
    
    qr_data = data["qr_stock"].pop(0)
    parts = qr_data.split("|")
    
    uploaded_by = "Unknown Admin"
    if len(parts) >= 2 and parts[-1].startswith("uploaded_by_"):
        uploaded_by = parts[-1].replace("uploaded_by_", "")
        qr_clean = "|".join(parts[:-1])
    else:
        qr_clean = qr_data
    
    data["pending_qr"][user_id] = {
        "qr_data": qr_clean,
        "qr_raw": qr_data,
        "username": username,
        "uploaded_by": uploaded_by,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    await update.message.reply_text(
        f"📱 **YOUR QR CODE**\n\n"
        f"`{qr_clean}`\n\n"
        f"💰 **1 QR = ₹15**\n"
        f"👑 Uploaded by: @{uploaded_by}\n\n"
        f"📸 Send screenshot proof\n"
        f"⏰ Expires in {QR_EXPIRE_MINUTES} minutes!",
        parse_mode='Markdown'
    )

# ============ REVIVE COMMAND ============
async def revive_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(f"🛠️ **MAINTENANCE MODE**\n\nBot will be back at **{time_str}**", parse_mode='Markdown')
        else:
            await update.message.reply_text("🛠️ **MAINTENANCE MODE**\n\n⏰ Timing: 10 PM - 8 AM IST", parse_mode='Markdown')
        return
    
    if user_id in data.get("pending_review", {}):
        await update.message.reply_text("⏳ You already have a review!", parse_mode='Markdown')
        return
    
    if not data["review_stock"]:
        await update.message.reply_text("❌ No review available!", parse_mode='Markdown')
        return
    
    review_data = data["review_stock"].pop(0)
    parts = review_data.split("|")
    
    uploaded_by = "Unknown Admin"
    if len(parts) >= 2 and parts[-1].startswith("uploaded_by_"):
        uploaded_by = parts[-1].replace("uploaded_by_", "")
        review_clean = "|".join(parts[:-1])
    else:
        review_clean = review_data
    
    data["pending_review"][user_id] = {
        "review_data": review_clean,
        "review_raw": review_data,
        "username": username,
        "uploaded_by": uploaded_by,
        "timestamp": get_ist_now().isoformat()
    }
    save_data(data)
    
    await update.message.reply_text(
        f"📝 **REVIEW WORK**\n\n"
        f"`{review_clean}`\n\n"
        f"📸 Send screenshot proof\n"
        f"👑 Uploaded by: @{uploaded_by}\n\n"
        f"⏰ Expires in {REVIEW_EXPIRE_MINUTES} minutes!",
        parse_mode='Markdown'
    )

# ============ GET REVIEW ============
async def getr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await revive_command(update, context)

# ============ SKIP 2FA ============
async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending email!", parse_mode='Markdown')
        return
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    await update.message.reply_text("✅ 2FA Skipped!\n📸 Send screenshot proof.", parse_mode='Markdown')

# ============ HANDLE OTP INPUT ============
async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ Enter 6-digit OTP!", parse_mode='Markdown')
        return
    
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending email work!", parse_mode='Markdown')
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if stored_otp and int(text) == stored_otp:
        data["pending"][user_id]["otp_verified"] = True
        data["pending"][user_id]["step"] = "waiting_screenshot"
        save_data(data)
        await update.message.reply_text(
            "✅ **OTP Verified!**\n\n📸 Send screenshot of Gmail inbox & settings as proof.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Wrong OTP! Try again.", parse_mode='Markdown')

# ============ HANDLE MESSAGE ============
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text
    
    if not text:
        return
    
    if user_id in data.get("pending", {}):
        pending = data["pending"][user_id]
        if pending.get("step") == "waiting_otp":
            await handle_otp_input(update, context)
            return
        
        if pending.get("type") == "email":
            await update.message.reply_text(
                f"📧 **EMAIL WORK**\n\n"
                f"👤 Name: `{pending.get('name', '')}`\n"
                f"📧 Email: `{pending.get('gmail', '')}`\n"
                f"🔑 Pass: `{pending.get('password', '')}`\n"
                f"📧 Recovery: `{pending.get('recovery', '')}`\n"
                f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n\n"
                "📌 /skip2fa - Skip 2FA\n/cancel - Cancel work",
                parse_mode='Markdown'
            )
        return
    
    if user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        await update.message.reply_text(
            f"📱 **QR PENDING**\n\n"
            f"📱 QR: `{pending.get('qr_data', '')}`\n"
            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        await update.message.reply_text(
            f"📝 **REVIEW PENDING**\n\n"
            f"📝 Review: `{pending.get('review_data', '')}`\n"
            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n\n"
            "Send a PHOTO as proof.",
            parse_mode='Markdown'
        )
        return
    
    await update.message.reply_text(
        "❌ **Unknown command**\n\n"
        "📌 Commands:\n"
        "/email - Get email work\n"
        "/qr - Get QR work\n"
        "/revive - Get review work\n"
        "/status - Check status\n"
        "/balance - Check balance\n"
        "/help - Show all commands",
        parse_mode='Markdown'
    )

# ============ HANDLE PHOTO ============
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    # QR pending
    if user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        approval_id = f"qr_{user_id}_{int(get_ist_now().timestamp())}"
        data["pending_approvals"][approval_id] = {
            "type": "qr",
            "user_id": user_id,
            "username": username,
            "data": pending.get("qr_data", ""),
            "uploaded_by": pending.get("uploaded_by", "Unknown"),
            "screenshot": file_id,
            "timestamp": get_ist_now().isoformat(),
            "status": "pending"
        }
        
        for qr in data.get("qr_history", []):
            if qr["data"] == pending.get("qr_raw", "") and qr["status"] == "pending":
                qr["status"] = "pending_approval"
                break
        
        del data["pending_qr"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    chat_id=admin,
                    photo=file_id,
                    caption=f"📱 **QR PENDING APPROVAL!**\n\n"
                            f"👤 User: @{username}\n"
                            f"🆔 ID: `{user_id}`\n"
                            f"📱 QR: `{pending.get('qr_data', '')}`\n"
                            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n"
                            f"⏰ Time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"📌 Approve: `/approve {approval_id}`\n"
                            f"❌ Deny: `/deny {approval_id}`",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send QR approval: {e}")
        
        await update.message.reply_text(
            f"✅ **QR SUBMITTED FOR APPROVAL!**\n\n"
            f"📱 QR: `{pending.get('qr_data', '')}`\n"
            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n"
            f"📸 Screenshot sent to admins\n"
            f"⏳ Waiting for admin approval\n\n"
            f"💰 You will get ₹15 after approval.\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
        return
    
    # Review pending
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        photo = update.message.photo[-1]
        file_id = photo.file_id
        
        approval_id = f"review_{user_id}_{int(get_ist_now().timestamp())}"
        data["pending_approvals"][approval_id] = {
            "type": "review",
            "user_id": user_id,
            "username": username,
            "data": pending.get("review_data", ""),
            "uploaded_by": pending.get("uploaded_by", "Unknown"),
            "screenshot": file_id,
            "timestamp": get_ist_now().isoformat(),
            "status": "pending"
        }
        
        for rev in data.get("review_history", []):
            if rev["data"] == pending.get("review_raw", "") and rev["status"] == "pending":
                rev["status"] = "pending_approval"
                break
        
        del data["pending_review"][user_id]
        save_data(data)
        
        for admin in ADMINS:
            try:
                await context.bot.send_photo(
                    chat_id=admin,
                    photo=file_id,
                    caption=f"📝 **REVIEW PENDING APPROVAL!**\n\n"
                            f"👤 User: @{username}\n"
                            f"🆔 ID: `{user_id}`\n"
                            f"📝 Review: `{pending.get('review_data', '')}`\n"
                            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n"
                            f"⏰ Time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                            f"📌 Approve: `/approve {approval_id}`\n"
                            f"❌ Deny: `/deny {approval_id}`",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Failed to send review approval: {e}")
        
        await update.message.reply_text(
            f"✅ **REVIEW SUBMITTED FOR APPROVAL!**\n\n"
            f"📝 Review: `{pending.get('review_data', '')}`\n"
            f"👑 Uploaded by: @{pending.get('uploaded_by', 'Unknown')}\n"
            f"📸 Screenshot sent to admins\n"
            f"⏳ Waiting for admin approval\n\n"
            f"💰 You will get ₹15 after approval.\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
        return
    
    # Email pending
    if user_id in data.get("pending", {}):
        pending = data["pending"][user_id]
        if pending.get("step") == "waiting_screenshot" or pending.get("step") == "waiting_otp":
            photo = update.message.photo[-1]
            file_id = photo.file_id
            
            gmail = pending.get("gmail")
            password = pending.get("password")
            recovery = pending.get("recovery")
            name = pending.get("name", username)
            skip_2fa = pending.get("skip_2fa", False)
            uploaded_by = pending.get("uploaded_by", "Unknown")
            
            approval_id = f"email_{user_id}_{int(get_ist_now().timestamp())}"
            data["pending_approvals"][approval_id] = {
                "type": "email",
                "user_id": user_id,
                "username": username,
                "gmail": gmail,
                "password": password,
                "recovery": recovery,
                "name": name,
                "uploaded_by": uploaded_by,
                "screenshot": file_id,
                "skip_2fa": skip_2fa,
                "timestamp": get_ist_now().isoformat(),
                "status": "pending"
            }
            
            del data["pending"][user_id]
            save_data(data)
            
            for admin in ADMINS:
                try:
                    await context.bot.send_photo(
                        chat_id=admin,
                        photo=file_id,
                        caption=f"📧 **EMAIL PENDING APPROVAL!**\n\n"
                                f"👤 **Name:** {name}\n"
                                f"👤 **User:** @{username}\n"
                                f"🆔 **ID:** `{user_id}`\n"
                                f"📧 **Email:** `{gmail}`\n"
                                f"🔑 **Pass:** `{password}`\n"
                                f"📧 **Recovery:** `{recovery}`\n"
                                f"👑 **Uploaded by:** @{uploaded_by}\n"
                                f"📸 **2FA:** {'✅ Enabled' if not skip_2fa else '❌ Skipped'}\n"
                                f"⏰ **Time:** {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                                f"📌 Approve: `/approve {approval_id}`\n"
                                f"❌ Deny: `/deny {approval_id}`",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.error(f"Failed to send email approval: {e}")
            
            await update.message.reply_text(
                f"📧 **EMAIL SUBMITTED FOR APPROVAL!**\n\n"
                f"👤 Name: `{name}`\n"
                f"📧 Email: `{gmail}`\n"
                f"🔑 Pass: `{password}`\n"
                f"📧 Recovery: `{recovery}`\n"
                f"👑 Uploaded by: @{uploaded_by}\n"
                f"📸 2FA: {'✅ Enabled' if not skip_2fa else '❌ Skipped'}\n\n"
                f"📸 Screenshot sent to admins\n"
                f"⏳ Waiting for admin approval\n\n"
                f"💰 You will get ₹15 after approval.\n"
                f"👑 Admin: {ESCROW_USER}",
                parse_mode='Markdown'
            )
            return
    
    await update.message.reply_text("❌ No pending work found!", parse_mode='Markdown')

# ============ APPROVE COMMAND ============
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    admin_id = update.effective_user.id
    
    if not is_admin(admin_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "📌 **APPROVE WORK**\n\n"
            "Usage: `/approve [approval_id]`\n\n"
            "Get ID from `/pending` command.\n\n"
            "⚠️ This will add ₹15 to user's balance.",
            parse_mode='Markdown'
        )
        return
    
    approval_id = context.args[0]
    data = load_data()
    
    if approval_id not in data.get("pending_approvals", {}):
        await update.message.reply_text(f"❌ Approval `{approval_id}` not found!", parse_mode='Markdown')
        return
    
    approval = data["pending_approvals"][approval_id]
    if approval["status"] != "pending":
        await update.message.reply_text(f"❌ Approval `{approval_id}` already processed!", parse_mode='Markdown')
        return
    
    target_user_id = approval["user_id"]
    
    if target_user_id not in data["users"]:
        data["users"][target_user_id] = {"balance": 0, "username": approval["username"]}
    
    data["users"][target_user_id]["balance"] = data["users"][target_user_id].get("balance", 0) + 15
    
    if approval["type"] == "email":
        data["users"][target_user_id]["email_done"] = True
        data["users"][target_user_id]["gmail"] = approval.get("gmail")
        data["users"][target_user_id]["password"] = approval.get("password")
        data["users"][target_user_id]["recovery"] = approval.get("recovery")
        data["users"][target_user_id]["name"] = approval.get("name")
        data["used_emails"].append(approval.get("gmail"))
        
        for upload in data.get("upload_history", []):
            if upload["raw"].find(approval.get("gmail", "")) != -1 and upload["status"] == "pending_approval":
                upload["status"] = "approved"
                upload["approved_by"] = admin_id
                upload["approved_at"] = get_ist_now().isoformat()
                break
    elif approval["type"] == "qr":
        data["users"][target_user_id]["qr_done"] = True
        for qr in data.get("qr_history", []):
            if qr["data"] == approval.get("data") and qr["status"] == "pending_approval":
                qr["status"] = "approved"
                qr["approved_by"] = admin_id
                qr["approved_at"] = get_ist_now().isoformat()
                break
    elif approval["type"] == "review":
        data["users"][target_user_id]["review_done"] = True
        for rev in data.get("review_history", []):
            if rev["data"] == approval.get("data") and rev["status"] == "pending_approval":
                rev["status"] = "approved"
                rev["approved_by"] = admin_id
                rev["approved_at"] = get_ist_now().isoformat()
                break
    
    approval["status"] = "approved"
    approval["approved_by"] = admin_id
    approval["approved_at"] = get_ist_now().isoformat()
    save_data(data)
    
    try:
        await context.bot.send_message(
            int(target_user_id),
            f"✅ **WORK APPROVED!**\n\n"
            f"💰 ₹15 has been added to your balance!\n"
            f"📌 Current Balance: ₹{data['users'][target_user_id]['balance']}\n\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
    except:
        pass
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"✅ **WORK APPROVED!**\n\n"
                f"👤 User: @{approval['username']}\n"
                f"🆔 ID: `{target_user_id}`\n"
                f"📌 Type: {approval['type']}\n"
                f"💰 ₹15 added\n"
                f"👑 Approved by: @{update.effective_user.username}",
                parse_mode='Markdown'
            )
        except:
            pass

# ============ DENY COMMAND ============
async def deny_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    admin_id = update.effective_user.id
    
    if not is_admin(admin_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ **DENY WORK**\n\n"
            "Usage: `/deny [approval_id]`\n\n"
            "Get ID from `/pending` command.\n\n"
            "⚠️ This will deny the work and NO balance will be added.",
            parse_mode='Markdown'
        )
        return
    
    approval_id = context.args[0]
    data = load_data()
    
    if approval_id not in data.get("pending_approvals", {}):
        await update.message.reply_text(f"❌ Approval `{approval_id}` not found!", parse_mode='Markdown')
        return
    
    approval = data["pending_approvals"][approval_id]
    if approval["status"] != "pending":
        await update.message.reply_text(f"❌ Approval `{approval_id}` already processed!", parse_mode='Markdown')
        return
    
    approval["status"] = "denied"
    approval["denied_by"] = admin_id
    approval["denied_at"] = get_ist_now().isoformat()
    save_data(data)
    
    target_user_id = approval["user_id"]
    
    try:
        await context.bot.send_message(
            int(target_user_id),
            f"❌ **WORK DENIED!**\n\n"
            f"Your work has been denied by admin.\n"
            f"⚠️ No balance added.\n\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
    except:
        pass
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"❌ **WORK DENIED!**\n\n"
                f"👤 User: @{approval['username']}\n"
                f"🆔 ID: `{target_user_id}`\n"
                f"📌 Type: {approval['type']}\n"
                f"⚠️ No balance added.\n"
                f"👑 Denied by: @{update.effective_user.username}",
                parse_mode='Markdown'
            )
        except:
            pass

# ============ PENDING APPROVALS COMMAND ============
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    data = load_data()
    
    pending_list = data.get("pending_approvals", {})
    if not pending_list:
        await update.message.reply_text("📋 No pending approvals.", parse_mode='Markdown')
        return
    
    text = "⏳ **PENDING APPROVALS**\n\n"
    count = 0
    for aid, approval in pending_list.items():
        if approval["status"] == "pending":
            count += 1
            text += f"🆔 `{aid}`\n"
            text += f"👤 @{approval['username']}\n"
            text += f"📌 Type: {approval['type']}\n"
            if approval["type"] == "email":
                text += f"📧 {approval.get('gmail', '')}\n"
            text += f"👑 Uploaded by: @{approval.get('uploaded_by', 'Unknown')}\n"
            text += f"📌 Approve: `/approve {aid}`\n"
            text += f"❌ Deny: `/deny {aid}`\n\n"
    
    if count == 0:
        await update.message.reply_text("📋 No pending approvals.", parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')

# ============ CANCEL COMMAND ============
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        if pending.get("type") == "email":
            name = pending.get("name", "User")
            uploaded_by = pending.get("uploaded_by", "Unknown")
            email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}|uploaded_by_{uploaded_by}"
            data["email_stock"].append(email_data)
        elif pending.get("type") == "qr":
            uploaded_by = pending.get("uploaded_by", "Unknown")
            data["qr_stock"].append(f"{pending['qr_data']}|uploaded_by_{uploaded_by}")
        elif pending.get("type") == "review":
            uploaded_by = pending.get("uploaded_by", "Unknown")
            data["review_stock"].append(f"{pending['review_data']}|uploaded_by_{uploaded_by}")
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Cancelled! Work returned.", parse_mode='Markdown')
    elif user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        data["qr_stock"].append(pending["qr_raw"])
        del data["pending_qr"][user_id]
        save_data(data)
        await update.message.reply_text("❌ QR cancelled!", parse_mode='Markdown')
    elif user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        data["review_stock"].append(pending["review_raw"])
        del data["pending_review"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Review cancelled!", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session!", parse_mode='Markdown')

# ============ CANCEL UPLOAD (ADMIN) ============
async def cancel_upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/cancel #id`", parse_mode='Markdown')
        return
    
    upload_id = int(context.args[0].replace("#", ""))
    
    for upload in data.get("upload_history", []):
        if upload["id"] == upload_id and upload["status"] == "pending":
            data["email_stock"].remove(upload["raw"])
            upload["status"] = "cancelled"
            save_data(data)
            await update.message.reply_text(f"✅ Upload `#{upload_id}` cancelled!", parse_mode='Markdown')
            return
    
    for qr in data.get("qr_history", []):
        if qr["id"] == upload_id and qr["status"] == "pending":
            data["qr_stock"].remove(qr["data"])
            qr["status"] = "cancelled"
            save_data(data)
            await update.message.reply_text(f"✅ QR `#{upload_id}` cancelled!", parse_mode='Markdown')
            return
    
    await update.message.reply_text(f"❌ Upload `#{upload_id}` not found!", parse_mode='Markdown')

# ============ RESET ALL ============
async def reset_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Only Owner!", parse_mode='Markdown')
        return
    if len(context.args) < 1 or context.args[0].lower() != "confirm":
        await update.message.reply_text("⚠️ Type: `/reset all confirm`", parse_mode='Markdown')
        return
    
    data["email_stock"] = []
    data["qr_stock"] = []
    data["review_stock"] = []
    data["upload_history"] = []
    data["qr_history"] = []
    data["review_history"] = []
    data["upload_counter"] = 0
    data["qr_upload_counter"] = 0
    data["review_upload_counter"] = 0
    data["pending_approvals"] = {}
    data["withdraw_requests"] = []
    save_data(data)
    await update.message.reply_text("✅ **All reset!**", parse_mode='Markdown')

# ============ STOCK COMMAND ============
async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    data = load_data()
    await update.message.reply_text(
        f"📊 **STOCK STATUS**\n\n"
        f"📦 Email: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}\n"
        f"📱 QR: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}\n"
        f"📝 Review: {len(data['review_stock'])}\n"
        f"👥 Users: {len(data['users'])}\n"
        f"⏳ Pending Approvals: {len(data.get('pending_approvals', {}))}\n"
        f"💰 Withdrawals: {len(data.get('withdraw_requests', []))}",
        parse_mode='Markdown'
    )

# ============ BALANCE COMMAND ============
async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(
        f"💰 **BALANCE**\n\n"
        f"💵 Balance: ₹{user.get('balance', 0)}\n"
        f"📧 Email: {'✅' if user.get('email_done') else '❌'}\n"
        f"📱 QR: {'✅' if user.get('qr_done') else '❌'}\n"
        f"📝 Review: {'✅' if user.get('review_done') else '❌'}\n\n"
        f"📌 Withdraw: /withdraw [amount]",
        parse_mode='Markdown'
    )

# ============ WITHDRAW COMMAND ============
async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    balance = user.get("balance", 0)
    upi = user.get("upi", "")
    if not upi:
        await update.message.reply_text("❌ Set UPI: /setupi [UPI]", parse_mode='Markdown')
        return
    if balance <= 0:
        await update.message.reply_text(f"❌ Balance: ₹{balance}", parse_mode='Markdown')
        return
    if len(context.args) < 1:
        await update.message.reply_text(f"💰 Balance: ₹{balance}\nUsage: /withdraw [amount]", parse_mode='Markdown')
        return
    try:
        amount = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid amount!", parse_mode='Markdown')
        return
    if amount > balance:
        await update.message.reply_text(f"❌ Balance: ₹{balance}", parse_mode='Markdown')
        return
    if amount < 15:
        await update.message.reply_text("❌ Minimum ₹15!", parse_mode='Markdown')
        return
    
    withdraw_data = {
        "user_id": user_id, 
        "username": update.effective_user.first_name, 
        "upi": upi, 
        "amount": amount, 
        "timestamp": get_ist_now().isoformat(), 
        "status": "pending"
    }
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"💰 **WITHDRAWAL REQUEST!**\n\n"
                f"👤 User: @{update.effective_user.username}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📌 UPI: `{upi}`\n"
                f"💰 Amount: ₹{amount}\n"
                f"⏰ Time: {get_ist_now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                f"✅ Approve: `/approve_withdraw {user_id} {amount}`\n"
                f"❌ Deny: `/deny_withdraw {user_id} {amount} [reason]`",
                parse_mode='Markdown'
            )
        except:
            pass
    
    await update.message.reply_text(
        f"✅ **WITHDRAWAL REQUEST SENT!**\n\n"
        f"💰 Amount: ₹{amount}\n"
        f"📌 UPI: `{upi}`\n"
        f"⏳ Status: Pending\n\n"
        f"📌 Admin will approve/deny your request.\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ APPROVE WITHDRAWAL ============
async def approve_withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    admin_id = update.effective_user.id
    
    if not is_admin(admin_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "✅ **APPROVE WITHDRAWAL**\n\n"
            "Usage: `/approve_withdraw [user_id] [amount]`\n\n"
            "Example: `/approve_withdraw 123456789 15`",
            parse_mode='Markdown'
        )
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    
    data = load_data()
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User `{target_id}` not found!", parse_mode='Markdown')
        return
    
    found = False
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_by"] = admin_id
            req["approved_at"] = get_ist_now().isoformat()
            found = True
            break
    
    if not found:
        await update.message.reply_text(f"❌ No pending withdrawal of ₹{amount} for user `{target_id}`", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    save_data(data)
    
    try:
        await context.bot.send_message(
            int(target_id),
            f"💰 **WITHDRAWAL APPROVED!**\n\n"
            f"✅ ₹{amount} has been approved\n"
            f"📌 We are paying in 4 days as fastest as possible.\n\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
    except:
        pass
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"✅ **WITHDRAWAL APPROVED!**\n\n"
                f"👤 User: `{target_id}`\n"
                f"💰 Amount: ₹{amount}\n"
                f"👑 Approved by: @{update.effective_user.username}",
                parse_mode='Markdown'
            )
        except:
            pass
    
    await update.message.reply_text(
        f"✅ **WITHDRAWAL APPROVED!**\n\n"
        f"👤 User: `{target_id}`\n"
        f"💰 ₹{amount} approved",
        parse_mode='Markdown'
    )

# ============ DENY WITHDRAWAL WITH REASON ============
async def deny_withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    admin_id = update.effective_user.id
    
    if not is_admin(admin_id):
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **DENY WITHDRAWAL**\n\n"
            "Usage: `/deny_withdraw [user_id] [amount] [reason]`\n\n"
            "Example: `/deny_withdraw 123456789 15 Invalid UPI`",
            parse_mode='Markdown'
        )
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    reason = " ".join(context.args[2:]) if len(context.args) > 2 else "No reason provided"
    
    data = load_data()
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User `{target_id}` not found!", parse_mode='Markdown')
        return
    
    found = False
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "denied"
            req["denied_by"] = admin_id
            req["denied_at"] = get_ist_now().isoformat()
            req["deny_reason"] = reason
            found = True
            break
    
    if not found:
        await update.message.reply_text(f"❌ No pending withdrawal of ₹{amount} for user `{target_id}`", parse_mode='Markdown')
        return
    
    save_data(data)
    
    try:
        await context.bot.send_message(
            int(target_id),
            f"❌ **WITHDRAWAL DENIED!**\n\n"
            f"💰 Amount: ₹{amount}\n"
            f"📌 Reason: `{reason}`\n\n"
            f"⚠️ Your withdrawal request has been denied.\n"
            f"📌 Contact admin for more details.\n\n"
            f"👑 Admin: {ESCROW_USER}",
            parse_mode='Markdown'
        )
    except:
        pass
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"❌ **WITHDRAWAL DENIED!**\n\n"
                f"👤 User: `{target_id}`\n"
                f"💰 Amount: ₹{amount}\n"
                f"📌 Reason: `{reason}`\n"
                f"👑 Denied by: @{update.effective_user.username}",
                parse_mode='Markdown'
            )
        except:
            pass
    
    await update.message.reply_text(
        f"❌ **WITHDRAWAL DENIED!**\n\n"
        f"👤 User: `{target_id}`\n"
        f"💰 ₹{amount} denied\n"
        f"📌 Reason: `{reason}`",
        parse_mode='Markdown'
    )

# ============ SETUPI COMMAND ============
async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /setupi [UPI_ID]", parse_mode='Markdown')
        return
    upi = context.args[0]
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "username": update.effective_user.first_name}
    data["users"][user_id]["upi"] = upi
    save_data(data)
    await update.message.reply_text(f"✅ UPI Set: `{upi}`", parse_mode='Markdown')

# ============ STATUS COMMAND ============
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, TASK_TIMEOUT_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **PENDING**\n📧 `{pending.get('gmail', '')}`\n⏰ Time Left: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_qr", {}):
        pending = data["pending_qr"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, QR_EXPIRE_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **QR PENDING**\n📱 QR assigned\n⏰ Expires in: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data.get("pending_review", {}):
        pending = data["pending_review"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        if start_time.tzinfo is None:
            start_time = IST.localize(start_time)
        elapsed = (get_ist_now() - start_time).seconds // 60
        remaining = max(0, REVIEW_EXPIRE_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **REVIEW PENDING**\n📝 Review assigned\n⏰ Expires in: {remaining} min",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data["users"]:
        user = data["users"][user_id]
        await update.message.reply_text(
            f"✅ **ACCOUNT**\n"
            f"💰 Balance: ₹{user.get('balance', 0)}\n"
            f"📧 Email: {'✅' if user.get('email_done') else '❌'}\n"
            f"📱 QR: {'✅' if user.get('qr_done') else '❌'}\n"
            f"📝 Review: {'✅' if user.get('review_done') else '❌'}\n\n"
            f"📌 /email - Get email work\n"
            f"/qr - Get QR work\n"
            f"/revive - Get review work",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ No account.\n\n"
            "📌 Commands:\n"
            "/email - Get email work\n"
            "/qr - Get QR work\n"
            "/revive - Get review work",
            parse_mode='Markdown'
        )

# ============ HELP COMMAND ============
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin_user = is_admin(update.effective_user.id)
    
    help_text = (
        "📧 **HELP**\n\n"
        "**User Commands:**\n"
        "/email - Get email work (₹15)\n"
        "/qr - Get QR work (₹15)\n"
        "/revive - Get review work (₹15)\n"
        "/status - Check status\n"
        "/balance - Check balance\n"
        "/withdraw [amount] - Withdraw\n"
        "/setupi [UPI] - Set UPI\n"
        "/cancel - Cancel current\n"
        "/help - This help\n\n"
        "⏰ **Bot Timings:**\n"
        "🟢 8 AM - 10 PM IST (Online)\n"
        "🔴 10 PM - 8 AM IST (Maintenance)\n"
    )
    
    if is_admin_user:
        help_text += (
            "\n**Admin Commands:**\n"
            "/upload Name|Email|Pass|Rec - Add email\n"
            "/uploadqr [qr_data] - Add QR\n"
            "/uploadr [review] - Add review\n"
            "/stock - Check all stock\n"
            "/pending - Check pending approvals\n"
            "/approve [id] - Approve work (+₹15)\n"
            "/deny [id] - Deny work (No ₹)\n"
            "/approve_withdraw [id] [amount] - Approve withdrawal\n"
            "/deny_withdraw [id] [amount] [reason] - Deny withdrawal\n"
            "/broadcast [message] - Send to all users\n"
            "/mainon - Maintenance ON\n"
            "/mainoff - Maintenance OFF\n"
            "/cancel #id - Cancel upload\n"
            "/reset all - Reset all (Owner)\n"
            "/newadmin [user_id] - Add admin (Owner)\n"
        )
    
    help_text += f"\n\n👑 Admin: {ESCROW_USER}"
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ============ START COMMAND ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        next_start = get_next_start_time()
        if next_start:
            time_str = next_start.strftime('%I:%M %p')
            await update.message.reply_text(
                f"🛠️ **MAINTENANCE MODE**\n\nBot will be back at **{time_str}**",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🛠️ **MAINTENANCE MODE**\n\n⏰ Timing: 10 PM - 8 AM IST",
                parse_mode='Markdown'
            )
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"balance": 0, "username": user.first_name}
        save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL VERIFICATION BOT**\n\n👋 Hello {user.first_name}!\n💰 **Earn ₹15 per work!**\n\n"
        "📌 **Available Work:**\n"
        "/email - Email verification\n"
        "/qr - QR verification\n"
        "/revive - Review work\n\n"
        f"⏰ **Timings:** 8 AM - 10 PM IST\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ ERROR HANDLER ============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    global data, ADMINS
    data = load_data()
    ADMINS = data.get("admins", [OWNER_ID])
    
    request = HTTPXRequest(
        connect_timeout=HTTPX_TIMEOUT,
        read_timeout=HTTPX_TIMEOUT,
        write_timeout=HTTPX_TIMEOUT,
        pool_timeout=HTTPX_TIMEOUT,
    )
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("email", email_command))
    app.add_handler(CommandHandler("qr", qr_command))
    app.add_handler(CommandHandler("revive", revive_command))
    app.add_handler(CommandHandler("getr", getr_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Admin commands
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("uploadqr", uploadqr_command))
    app.add_handler(CommandHandler("uploadr", uploadr_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("deny", deny_command))
    app.add_handler(CommandHandler("approve_withdraw", approve_withdraw_command))
    app.add_handler(CommandHandler("deny_withdraw", deny_withdraw_command))
    app.add_handler(CommandHandler("broadcast", broadcast_command))
    app.add_handler(CommandHandler("mainon", mainon_command))
    app.add_handler(CommandHandler("mainoff", mainoff_command))
    app.add_handler(CommandHandler("newadmin", newadmin_command))
    app.add_handler(CommandHandler("reset", reset_all_command))
    app.add_handler(CommandHandler("cancel", cancel_upload_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_photo))
    app.add_error_handler(error_handler)
    
    # Job Queue
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(self_ping, interval=180, first=30)
        job_queue.run_repeating(check_timeout_job, interval=60, first=60)
        job_queue.run_repeating(check_qr_expire_job, interval=60, first=30)
        job_queue.run_repeating(check_review_expire_job, interval=60, first=30)
        print("🔄 All jobs scheduled")
    
    print("🚀 Bot started!")
    print(f"📦 Email: {len(data['email_stock'])}/{MAX_EMAIL_UPLOAD}")
    print(f"📱 QR: {len(data['qr_stock'])}/{MAX_QR_UPLOAD}")
    print(f"📝 Review: {len(data['review_stock'])}")
    print(f"⏳ Pending Approvals: {len(data.get('pending_approvals', {}))}")
    print(f"💰 Withdrawals: {len(data.get('withdraw_requests', []))}")
    print(f"👑 Admins: {ADMINS}")
    print(f"⏰ Bot Timings: 8 AM - 10 PM IST")
    
    app.run_polling()

if __name__ == "__main__":
    main()
