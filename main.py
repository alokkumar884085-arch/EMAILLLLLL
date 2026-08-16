import logging
import random
import string
import time
import re
import json
import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.request import HTTPXRequest

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAHLqV5K0T35xBovV9aInnWqvmYwaivZ7rY"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

# ============ ADMIN LIST ============
ADMINS = [OWNER_ID]

# ============ TIME CONFIGURATION ============
MAINTENANCE_START = 22
MAINTENANCE_END = 10
TASK_TIMEOUT_MINUTES = 15
COOLDOWN_MINUTES = 2

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for key in ["email_stock", "used_emails", "users", "pending", "withdraw_requests", "cooldowns", "admins", "upload_counter", "upload_history"]:
                    if key not in data:
                        if key in ["users", "pending", "cooldowns"]:
                            data[key] = {}
                        elif key == "upload_counter":
                            data[key] = 0
                        else:
                            data[key] = []
                return data
        except Exception as e:
            logging.error(f"Error loading data: {e}")
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {},
        "pending": {},
        "email_stock": [],
        "used_emails": [],
        "withdraw_requests": [],
        "cooldowns": {},
        "admins": [OWNER_ID],
        "upload_counter": 0,
        "upload_history": []  # [{id: 1, email: "...", status: "pending/approved/cancelled"}]
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
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def is_maintenance_mode():
    now = datetime.now()
    return now.hour >= MAINTENANCE_START or now.hour < MAINTENANCE_END

def is_admin(user_id):
    return user_id in ADMINS or user_id == OWNER_ID

# ============ SELF PING ============
PING_COUNT = 0

async def self_ping(context: ContextTypes.DEFAULT_TYPE):
    global PING_COUNT, data
    PING_COUNT += 1
    data = load_data()
    
    try:
        await context.bot.send_message(
            chat_id=OWNER_ID,
            text=f"🔄 **BOT IS ALIVE!**\n\n"
                 f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                 f"📦 Stock: {len(data['email_stock'])}\n"
                 f"👥 Users: {len(data['users'])}\n"
                 f"⏳ Pending: {len(data['pending'])}\n"
                 f"📊 Uploads: {data.get('upload_counter', 0)}\n"
                 f"📋 History: {len(data.get('upload_history', []))}"
        )
        logger.info(f"Self ping #{PING_COUNT} sent")
    except Exception as e:
        logger.error(f"Self ping failed: {e}")

# ============ CHECK TIMEOUT ============
def check_pending_timeout():
    global data
    now = datetime.now()
    to_remove = []
    for user_id, pending in data["pending"].items():
        if "timestamp" in pending:
            try:
                start_time = datetime.fromisoformat(pending["timestamp"])
                if (now - start_time).total_seconds() > TASK_TIMEOUT_MINUTES * 60:
                    to_remove.append(user_id)
            except:
                continue
    for user_id in to_remove:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        email_data = f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}"
        data["email_stock"].append(email_data)
        data["cooldowns"][user_id] = (datetime.now() + timedelta(minutes=COOLDOWN_MINUTES)).isoformat()
        del data["pending"][user_id]
        save_data(data)

async def check_timeout_job(context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    if data["pending"]:
        check_pending_timeout()

# ============ UPLOAD TRACKING FUNCTIONS ============
def add_upload_to_history(email_data, status="pending"):
    """Add upload to history with unique ID"""
    global data
    data["upload_counter"] = data.get("upload_counter", 0) + 1
    upload_id = data["upload_counter"]
    
    # Parse email data
    parts = email_data.split("|")
    if len(parts) == 4:
        name, email, password, recovery = parts
    else:
        email, password, recovery = parts[0], parts[1], parts[2]
        name = "Unknown"
    
    data["upload_history"].append({
        "id": upload_id,
        "name": name,
        "email": email,
        "password": password,
        "recovery": recovery,
        "raw": email_data,
        "status": status,
        "timestamp": datetime.now().isoformat(),
        "assigned_to": None,
        "approved_by": None
    })
    save_data(data)
    return upload_id

def get_upload_by_id(upload_id):
    """Get upload by ID"""
    global data
    for upload in data.get("upload_history", []):
        if upload["id"] == upload_id:
            return upload
    return None

def update_upload_status(upload_id, status, extra=None):
    """Update upload status"""
    global data
    for upload in data.get("upload_history", []):
        if upload["id"] == upload_id:
            upload["status"] = status
            if extra:
                upload.update(extra)
            save_data(data)
            return True
    return False

# ============ NEW ADMIN COMMAND ============
async def newadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data, ADMINS
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ **Only Owner can add admins!**", parse_mode='Markdown')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "👑 **ADD NEW ADMIN**\n\n"
            "Usage: `/newadmin [user_id]`\n\n"
            "Example: `/newadmin 123456789`",
            parse_mode='Markdown'
        )
        return
    
    try:
        new_admin_id = int(context.args[0])
    except:
        await update.message.reply_text("❌ Invalid User ID!", parse_mode='Markdown')
        return
    
    if new_admin_id in ADMINS:
        await update.message.reply_text(f"⚠️ User `{new_admin_id}` is already an admin.", parse_mode='Markdown')
        return
    
    ADMINS.append(new_admin_id)
    data["admins"] = ADMINS
    save_data(data)
    
    await update.message.reply_text(f"✅ **NEW ADMIN ADDED!**\n\n👑 User ID: `{new_admin_id}`", parse_mode='Markdown')
    
    try:
        await context.bot.send_message(
            chat_id=new_admin_id,
            text=f"👑 **You are now an Admin!**\n\nYou can use admin commands:\n/upload - Add stock\n/stock - Check stock\n/approve - Approve withdrawals\n/cancel #id - Cancel upload",
            parse_mode='Markdown'
        )
    except:
        pass

# ============ UPLOAD COMMAND WITH TRACKING ============
async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Unauthorized!** Only admins can upload.", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD FORMAT**\n\n"
            "/upload Name|Email|Pass|Recovery\n\n"
            "Multiple:\n"
            "/upload Name1|Email1|Pass1|Rec1,Name2|Email2|Pass2|Rec2\n\n"
            f"📦 Current Stock: {len(data['email_stock'])}\n"
            f"📊 Total Uploads: {data.get('upload_counter', 0)}",
            parse_mode='Markdown'
        )
        return
    
    emails = context.args[0].split(",")
    count = 0
    uploaded_ids = []
    
    for email in emails:
        email = email.strip()
        if "|" in email:
            parts = email.split("|")
            if len(parts) >= 3:
                # Add to stock
                data["email_stock"].append(email)
                
                # Add to history with ID
                upload_id = add_upload_to_history(email, "pending")
                uploaded_ids.append(upload_id)
                count += 1
    
    save_data(data)
    data = load_data()
    
    # Build response message
    response = f"✅ **UPLOAD COMPLETE!**\n\n"
    response += f"📤 Added: {count} emails\n"
    response += f"📦 Total Stock: {len(data['email_stock'])}\n"
    response += f"📊 Upload #: {data.get('upload_counter', 0)}\n\n"
    
    for uid in uploaded_ids:
        upload = get_upload_by_id(uid)
        if upload:
            response += f"#️⃣ `#{upload['id']}` - {upload['email']} - ✅ Done\n"
    
    response += f"\n📌 To cancel: `/cancel #{uploaded_ids[0]}` (if single)"
    
    await update.message.reply_text(response, parse_mode='Markdown')

# ============ CANCEL UPLOAD COMMAND ============
async def cancel_upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a specific upload by ID"""
    global data
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ **Usage:** `/cancel #upload_id`\n\n"
            "Example: `/cancel #1`\n\n"
            "To see all uploads: `/uploads`",
            parse_mode='Markdown'
        )
        return
    
    # Extract ID from #1 or 1
    upload_arg = context.args[0].replace("#", "").strip()
    try:
        upload_id = int(upload_arg)
    except:
        await update.message.reply_text("❌ Invalid ID! Use: `/cancel #1`", parse_mode='Markdown')
        return
    
    # Find upload
    upload = get_upload_by_id(upload_id)
    if not upload:
        await update.message.reply_text(f"❌ Upload `#{upload_id}` not found!", parse_mode='Markdown')
        return
    
    if upload["status"] == "approved":
        await update.message.reply_text(f"❌ Upload `#{upload_id}` already approved and removed!", parse_mode='Markdown')
        return
    
    # Remove from stock
    raw = upload["raw"]
    if raw in data["email_stock"]:
        data["email_stock"].remove(raw)
    
    # Update status
    update_upload_status(upload_id, "cancelled", {"cancelled_by": user_id, "cancelled_at": datetime.now().isoformat()})
    
    await update.message.reply_text(
        f"✅ **UPLOAD CANCELLED!**\n\n"
        f"#️⃣ `#{upload_id}` - {upload['email']}\n"
        f"📌 Status: Cancelled\n"
        f"📦 Stock Left: {len(data['email_stock'])}",
        parse_mode='Markdown'
    )

# ============ RESET ALL UPLOADS ============
async def reset_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset all uploads (Owner only)"""
    global data
    
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ **Only Owner can reset all uploads!**", parse_mode='Markdown')
        return
    
    # Confirmation
    if len(context.args) < 1 or context.args[0].lower() != "confirm":
        await update.message.reply_text(
            "⚠️ **RESET ALL UPLOADS?**\n\n"
            f"This will delete:\n"
            f"📦 {len(data['email_stock'])} stock items\n"
            f"📊 {data.get('upload_counter', 0)} upload records\n"
            f"📋 {len(data.get('upload_history', []))} history entries\n\n"
            f"Type: `/reset all confirm` to confirm.",
            parse_mode='Markdown'
        )
        return
    
    # Reset
    data["email_stock"] = []
    data["upload_counter"] = 0
    data["upload_history"] = []
    save_data(data)
    
    await update.message.reply_text(
        "✅ **ALL UPLOADS RESET!**\n\n"
        f"📦 Stock: 0\n"
        f"📊 Uploads: 0\n"
        f"📋 History: 0",
        parse_mode='Markdown'
    )

# ============ VIEW UPLOADS COMMAND ============
async def uploads_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all uploads"""
    global data
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    data = load_data()
    history = data.get("upload_history", [])
    
    if not history:
        await update.message.reply_text("📋 No uploads found.", parse_mode='Markdown')
        return
    
    # Show recent 20 uploads
    recent = history[-20:] if len(history) > 20 else history
    response = "📋 **UPLOAD HISTORY**\n\n"
    
    for upload in reversed(recent):
        status_emoji = "✅" if upload["status"] == "approved" else "⏳" if upload["status"] == "pending" else "❌"
        response += f"#{upload['id']} {status_emoji} {upload['email']} - {upload['status']}\n"
    
    response += f"\n📊 Total: {len(history)} | Stock: {len(data['email_stock'])}"
    response += f"\n📌 `/cancel #id` to cancel | `/reset all` to reset all"
    
    await update.message.reply_text(response, parse_mode='Markdown')

# ============ APPROVE COMMAND WITH AUTO-REMOVE ============
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve withdrawal and auto-remove"""
    global data
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/approve [user_id] [amount]`\n\n"
            "Example: `/approve 123456789 15`\n\n"
            "⚠️ This will auto-remove the upload from stock.",
            parse_mode='Markdown'
        )
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    
    data = load_data()
    
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User `{target_id}` not found.", parse_mode='Markdown')
        return
    
    # Find user's email and mark as approved
    user_email = data["users"][target_id].get("gmail")
    
    # Update upload status to approved
    for upload in data.get("upload_history", []):
        if upload["email"] == user_email and upload["status"] == "pending":
            update_upload_status(upload["id"], "approved", {"approved_by": user_id, "approved_at": datetime.now().isoformat()})
            await update.message.reply_text(f"✅ Upload `#{upload['id']}` approved and removed from stock!", parse_mode='Markdown')
            break
    
    # Deduct balance
    data["users"][target_id]["balance"] -= amount
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = datetime.now().isoformat()
            break
    save_data(data)
    
    await context.bot.send_message(
        int(target_id), 
        f"💰 **WITHDRAWAL APPROVED!**\n\n✅ ₹{amount} sent to your UPI.", 
        parse_mode='Markdown'
    )
    await update.message.reply_text(f"✅ Approved ₹{amount} for `{target_id}`", parse_mode='Markdown')

# ============ USER COMMANDS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode (10 PM - 10 AM IST).", parse_mode='Markdown')
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": "", "balance": 0, "username": user.first_name, "completed": False}
        save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL VERIFICATION BOT**\n\n👋 Hello {user.first_name}!\n💰 **Earn ₹15 per Gmail!**\n\n"
        "📋 **Commands:**\n/new - Start\n/status - Check\n/balance - Check balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - Help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode.", parse_mode='Markdown')
        return
    
    if user_id in data.get("cooldowns", {}):
        cooldown_end = datetime.fromisoformat(data["cooldowns"][user_id])
        if datetime.now() < cooldown_end:
            remaining = (cooldown_end - datetime.now()).seconds // 60
            await update.message.reply_text(f"⏳ Cooldown: {remaining + 1} minutes", parse_mode='Markdown')
            return
        else:
            del data["cooldowns"][user_id]
            save_data(data)
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text("❌ Already completed!", parse_mode='Markdown')
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No stock! Admin notified.", parse_mode='Markdown')
        for admin in ADMINS:
            try:
                await context.bot.send_message(admin, "⚠️ STOCK EMPTY! Use /upload")
            except:
                pass
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ Pending! Use /cancel", parse_mode='Markdown')
        return
    
    email_data = data["email_stock"].pop(0)
    parts = email_data.split("|")
    
    if len(parts) == 4:
        name, gmail, password, recovery = parts
    else:
        gmail, password, recovery = parts[0], parts[1], parts[2]
        name = username
    
    data["pending"][user_id] = {
        "gmail": gmail, "password": password, "recovery": recovery,
        "name": name, "timestamp": datetime.now().isoformat(), "username": username
    }
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"📧 **GMAIL ASSIGNED!**\n"
                f"👤 @{username} (ID: `{user_id}`)\n"
                f"📧 `{gmail}`\n"
                f"📦 Stock Left: {len(data['email_stock'])}"
            )
        except:
            pass
    
    await update.message.reply_text(
        f"📧 **GMAIL ASSIGNED!**\n\n"
        f"👤 Name: `{name}`\n"
        f"📧 Email: `{gmail}`\n"
        f"🔑 Password: `{password}`\n"
        f"📧 Recovery: `{recovery}`\n\n"
        "📌 Login → /skip2fa or upload QR → OTP → Screenshot\n\n"
        f"⏰ {TASK_TIMEOUT_MINUTES} minutes timeout!\n"
        "/skip2fa - Skip 2FA\n/cancel - Cancel",
        parse_mode='Markdown'
    )

# ============ OTHER COMMANDS (shortened for space) ============

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending!", parse_mode='Markdown')
        return
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    await update.message.reply_text("✅ 2FA Skipped!\n📸 Send screenshot.", parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        return
    
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    data["pending"][user_id]["qr_file_id"] = photo.file_id
    otp = random.randint(100000, 999999)
    data["pending"][user_id]["otp"] = otp
    data["pending"][user_id]["step"] = "waiting_otp"
    save_data(data)
    await update.message.reply_text(f"✅ QR Received!\n📱 OTP: `{otp}`\n\nEnter OTP:", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text
    if not text or user_id not in data["pending"]:
        return
    if data["pending"][user_id].get("step") == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ 6-digit OTP!", parse_mode='Markdown')
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if int(text) != stored_otp:
        await update.message.reply_text("❌ Wrong OTP! Try again.", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["otp_verified"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    await update.message.reply_text("✅ OTP Verified!\n📸 Send screenshot.", parse_mode='Markdown')

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if user_id not in data["pending"]:
        return
    if not update.message.photo and not update.message.document:
        await update.message.reply_text("❌ Send screenshot!", parse_mode='Markdown')
        return
    
    file_id = update.message.photo[-1].file_id if update.message.photo else update.message.document.file_id
    pending = data["pending"][user_id]
    gmail, password, recovery = pending["gmail"], pending["password"], pending["recovery"]
    name = pending.get("name", username)
    
    data["users"][user_id] = {
        "gmail": gmail, "password": password, "recovery": recovery,
        "name": name, "timestamp": datetime.now().isoformat(),
        "upi": data["users"].get(user_id, {}).get("upi", ""),
        "balance": 15, "username": username, "completed": True,
        "screenshot": file_id, "skip_2fa": pending.get("skip_2fa", False)
    }
    data["used_emails"].append(gmail)
    if user_id in data["cooldowns"]:
        del data["cooldowns"][user_id]
    del data["pending"][user_id]
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"✅ **VERIFIED!**\n👤 @{username}\n📧 `{gmail}`\n💰 ₹15 (Hold 5 Days)"
            )
        except:
            pass
    
    try:
        await context.bot.send_message("escrow2929", f"✅ @{username}\n📧 `{gmail}`\n💰 ₹15")
    except:
        pass
    
    if not data["email_stock"]:
        for admin in ADMINS:
            try:
                await context.bot.send_message(admin, "⚠️ STOCK EMPTY! Use /upload")
            except:
                pass
    
    await update.message.reply_text(
        f"🎉 **VERIFIED!**\n✅ Gmail: `{gmail}`\n💰 ₹15 (5 Days Hold)\n👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        name = pending.get("name", pending.get("username", "User"))
        data["email_stock"].append(f"{name}|{pending['gmail']}|{pending['password']}|{pending['recovery']}")
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Cancelled! Gmail returned.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session.", parse_mode='Markdown')

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if len(context.args) < 1:
        await update.message.reply_text("❌ Usage: /setupi [UPI_ID]", parse_mode='Markdown')
        return
    upi = context.args[0]
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": upi, "balance": 0, "username": update.effective_user.first_name, "completed": False}
    else:
        data["users"][user_id]["upi"] = upi
    save_data(data)
    await update.message.reply_text(f"✅ UPI Set: `{upi}`", parse_mode='Markdown')

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(f"💰 Balance: ₹{user.get('balance', 0)}", parse_mode='Markdown')

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
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": datetime.now().isoformat(), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    for admin in ADMINS:
        try:
            await context.bot.send_message(
                admin,
                f"💰 **WITHDRAWAL!**\n👤 @{update.effective_user.username}\n📌 `{upi}`\n💰 ₹{amount}\n/approve {user_id} {amount}"
            )
        except:
            pass
    
    await update.message.reply_text(f"✅ Request Sent!\n💰 ₹{amount}\n📌 Pending", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    data = load_data()
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        start_time = datetime.fromisoformat(pending["timestamp"])
        elapsed = (datetime.now() - start_time).seconds // 60
        remaining = max(0, TASK_TIMEOUT_MINUTES - elapsed)
        await update.message.reply_text(
            f"⏳ **PENDING**\n📧 `{pending['gmail']}`\n⏰ Time Left: {remaining} min",
            parse_mode='Markdown'
        )
    elif user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(f"✅ **VERIFIED**\n📧 `{user['gmail']}`\n💰 ₹{user.get('balance', 0)}", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active. Use /new", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin_user = is_admin(update.effective_user.id)
    
    help_text = (
        "📧 **HELP**\n\n"
        "**User Commands:**\n"
        "/new - Start verification\n/status - Check status\n/balance - Check balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - Help\n"
    )
    
    if is_admin_user:
        help_text += (
            "\n**Admin Commands:**\n"
            "/upload Name|Email|Pass|Rec - Add stock\n/stock - Check stock\n/uploads - View all uploads\n/cancel #id - Cancel upload\n/reset all - Reset all uploads\n/approve [user_id] [amount] - Approve withdrawal\n/newadmin [user_id] - Add new admin (Owner only)\n"
        )
    
    help_text += f"\n👑 Admin: {ESCROW_USER}"
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global data
    
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    data = load_data()
    
    # Count pending and approved uploads
    pending_uploads = len([u for u in data.get("upload_history", []) if u["status"] == "pending"])
    approved_uploads = len([u for u in data.get("upload_history", []) if u["status"] == "approved"])
    
    await update.message.reply_text(
        f"📊 **STOCK STATUS**\n\n"
        f"📦 Available: {len(data['email_stock'])}\n"
        f"✅ Used: {len(data['used_emails'])}\n"
        f"⏳ Pending: {len(data['pending'])}\n"
        f"👥 Total Users: {len(data['users'])}\n"
        f"📊 Uploads: {data.get('upload_counter', 0)}\n"
        f"⏳ Pending Uploads: {pending_uploads}\n"
        f"✅ Approved Uploads: {approved_uploads}\n"
        f"👑 Admins: {len(ADMINS)}\n"
        f"📌 Status: {'✅ Active' if data['email_stock'] else '⚠️ Empty'}",
        parse_mode='Markdown'
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    global data, ADMINS
    data = load_data()
    ADMINS = data.get("admins", [OWNER_ID])
    
    request = HTTPXRequest(
        connect_timeout=60.0,
        read_timeout=60.0,
        write_timeout=60.0,
        pool_timeout=60.0,
    )
    
    app = Application.builder().token(TOKEN).request(request).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    # Admin commands
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("uploads", uploads_command))
    app.add_handler(CommandHandler("cancel", cancel_upload_command))  # Overload for admin
    app.add_handler(CommandHandler("reset", reset_all_command))
    app.add_handler(CommandHandler("approve", approve_command))
    app.add_handler(CommandHandler("newadmin", newadmin_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    app.add_error_handler(error_handler)
    
    # Job Queue
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_repeating(self_ping, interval=300, first=30)
        job_queue.run_repeating(check_timeout_job, interval=60, first=60)
        print("🔄 Self ping scheduled (every 5 minutes)")
        print("⏰ Timeout check scheduled (every minute)")
    
    print("🚀 Gmail 2FA Verification Bot started!")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"👥 Admins: {ADMINS}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    print(f"📊 Uploads: {data.get('upload_counter', 0)}")
    
    app.run_polling()

if __name__ == "__main__":
    main()
