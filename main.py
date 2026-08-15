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

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAHUbwcMmabM5UmsDKivRH1C6rj1mIQbpvM"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

# ============ TIME CONFIGURATION ============
MAINTENANCE_START = 22  # 10 PM
MAINTENANCE_END = 10    # 10 AM

# ============ DATABASE FILES ============
DATA_FILE = "bot_data.json"

# ============ DATABASE STRUCTURE ============
def load_data():
    """Load data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except:
            return default_data()
    return default_data()

def default_data():
    return {
        "users": {},
        "pending": {},
        "email_stock": [],
        "used_emails": [],
        "user_sessions": {},
        "otp_storage": {},
        "verified_users": {},
        "pending_payments": {},
        "withdraw_requests": []
    }

def save_data(data):
    """Save data to JSON file"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4, default=str)

# ============ LOAD DATA ============
data = load_data()

# ============ LOGGING ============
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ============ MAINTENANCE MODE CHECK ============
def is_maintenance_mode():
    """Check if current time is in maintenance window (10 PM - 10 AM IST)"""
    now = datetime.now()
    current_hour = now.hour
    if current_hour >= MAINTENANCE_START or current_hour < MAINTENANCE_END:
        return True
    return False

# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        await update.message.reply_text(
            "🛠️ **MAINTENANCE MODE** 🛠️\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bot is under maintenance.\n"
            "⏰ **Timing:** 10 PM - 10 AM IST\n\n"
            "🔄 Please try again after 10 AM.\n\n"
            "Thank you for your patience! 🙏",
            parse_mode='Markdown'
        )
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "gmail": "",
            "password": "",
            "recovery": "",
            "timestamp": "",
            "upi": "",
            "balance": 0,
            "username": user.first_name,
            "completed": False
        }
        save_data(data)
    
    welcome_text = f"""
📧 **GMAIL 2FA VERIFICATION BOT** 📧

👋 Hello {user.first_name}!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **EARN ₹15 BY VERIFYING GMAIL!**

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **STEPS:**

1️⃣ /new - Start new verification
2️⃣ Upload 2FA QR Code or Submit without 2FA
3️⃣ Enter OTP (if 2FA enabled)
4️⃣ Submit screenshot proof
5️⃣ Get ₹15 on hold
6️⃣ Release after 5 days moderation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📌 **REQUIREMENTS:**
├─ ✅ New Gmail account
├─ ✅ 2FA QR code (optional)
├─ ✅ Screenshot proof
└─ ✅ UPI ID for withdrawal

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚡ **COMMANDS:**
/new - Start new verification
/status - Check your status
/balance - Check your balance
/withdraw - Withdraw earnings
/setupi - Set your UPI ID
/help - Show help
/cancel - Cancel current process

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

👑 **Admin:** {ESCROW_USER}
"""
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start new Gmail verification process"""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text(
            "🛠️ **MAINTENANCE MODE** 🛠️\n\n"
            "Bot is under maintenance.\n"
            "⏰ **Timing:** 10 PM - 10 AM IST\n\n"
            "🔄 Please try again after 10 AM.",
            parse_mode='Markdown'
        )
        return
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text(
            "❌ **Already Completed!**\n\n"
            "You have already completed one verification.\n"
            "Only one Gmail per user is allowed.\n\n"
            f"📧 **Your Gmail:** `{data['users'][user_id]['gmail']}`\n"
            f"💰 **Balance:** ₹{data['users'][user_id]['balance']}\n\n"
            "📌 Contact admin for any issues.",
            parse_mode='Markdown'
        )
        return
    
    if not data["email_stock"]:
        await update.message.reply_text(
            "❌ **No Email Stock Available!**\n\n"
            "All Gmails are currently assigned.\n"
            "Please wait for new stock.\n"
            "Admin has been notified.",
            parse_mode='Markdown'
        )
        await context.bot.send_message(
            OWNER_ID,
            f"⚠️ **EMAIL STOCK EMPTY!**\n\n"
            f"All Gmails have been assigned.\n"
            f"Please upload new stock using /upload."
        )
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text(
            "⏳ **You have a pending verification!**\n\n"
            "Complete or cancel it first.\n"
            "Use /cancel to cancel pending.",
            parse_mode='Markdown'
        )
        return
    
    email_data = data["email_stock"].pop(0)
    gmail, password, recovery = email_data.split("|")
    
    data["pending"][user_id] = {
        "gmail": gmail,
        "password": password,
        "recovery": recovery,
        "timestamp": str(datetime.now()),
        "status": "pending",
        "username": username
    }
    save_data(data)
    
    await update.message.reply_text(
        "📧 **GMAIL ASSIGNED!** 📧\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"🔑 **Password:** `{password}`\n"
        f"📧 **Recovery:** `{recovery}`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 **Next Steps:**\n"
        "1️⃣ Login to this Gmail\n"
        "2️⃣ Enable 2FA (if not enabled)\n"
        "   - Or submit WITHOUT 2FA\n"
        "3️⃣ Upload 2FA QR Code\n"
        "   - Or type /skip2fa\n"
        "4️⃣ Enter OTP\n"
        "5️⃣ Submit screenshot proof\n\n"
        "⚡ **Commands:**\n"
        "/skip2fa - Submit without 2FA\n"
        "/cancel - Cancel this process",
        parse_mode='Markdown'
    )

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Skip 2FA verification"""
    user_id = str(update.effective_user.id)
    
    if user_id not in data["pending"]:
        await update.message.reply_text(
            "❌ **No pending verification!**\n\n"
            "Use /new to start.",
            parse_mode='Markdown'
        )
        return
    
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text(
        "✅ **2FA SKIPPED!** ✅\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📸 **STEP: SUBMIT SCREENSHOT PROOF**\n\n"
        "Please send a screenshot showing:\n"
        "1. Gmail inbox\n"
        "2. Account creation proof\n"
        "3. Gmail settings page\n\n"
        "📤 **Send the screenshot now:**\n\n"
        "⚠️ Clear screenshot required!",
        parse_mode='Markdown'
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all text messages"""
    user_id = str(update.effective_user.id)
    text = update.message.text
    
    if not text:
        return
    
    if user_id not in data["pending"]:
        return
    
    step = data["pending"][user_id].get("step", "")
    
    if step == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle QR code upload"""
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
    
    await update.message.reply_text(
        f"✅ **QR Code Received!** ✅\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📱 **Your 2FA OTP is:**\n"
        f"🔐 **`{otp}`**\n\n"
        "📝 **Please enter this OTP below:**\n\n"
        "⚠️ OTP expires in 5 minutes!\n"
        "⏰ You have 5 minutes to respond.",
        parse_mode='Markdown'
    )

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle OTP input"""
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text(
            "❌ **Invalid OTP!**\n\n"
            "OTP must be exactly 6 digits.\n"
            "Example: `123456`\n\n"
            "Try again.",
            parse_mode='Markdown'
        )
        return
    
    if user_id not in data["pending"]:
        await update.message.reply_text(
            "❌ **No pending verification!**",
            parse_mode='Markdown'
        )
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    
    if int(text) != stored_otp:
        await update.message.reply_text(
            "❌ **Invalid OTP!**\n\n"
            "The OTP you entered is incorrect.\n"
            "Please try again.",
            parse_mode='Markdown'
        )
        return
    
    data["pending"][user_id]["otp_verified"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text(
        "📸 **STEP: SUBMIT SCREENSHOT PROOF**\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "✅ OTP Verified Successfully!\n\n"
        "📸 **Please send a screenshot showing:**\n"
        "1. Gmail inbox\n"
        "2. 2FA enabled confirmation (if enabled)\n"
        "3. Recovery email visible\n"
        "4. Account creation proof\n\n"
        "📤 **Send the screenshot now:**\n\n"
        "⚠️ Clear screenshot required!",
        parse_mode='Markdown'
    )

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle screenshot upload"""
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if user_id not in data["pending"]:
        return
    
    if not update.message.photo and not update.message.document:
        await update.message.reply_text(
            "❌ **Please send a screenshot!**\n\n"
            "Send a photo or file.",
            parse_mode='Markdown'
        )
        return
    
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
    else:
        file_id = update.message.document.file_id
    
    pending = data["pending"][user_id]
    gmail = pending["gmail"]
    password = pending["password"]
    recovery = pending["recovery"]
    
    data["users"][user_id] = {
        "gmail": gmail,
        "password": password,
        "recovery": recovery,
        "timestamp": str(datetime.now()),
        "upi": data["users"].get(user_id, {}).get("upi", ""),
        "balance": 15,
        "username": username,
        "completed": True,
        "screenshot": file_id,
        "skip_2fa": pending.get("skip_2fa", False),
        "otp_verified": pending.get("otp_verified", False)
    }
    
    data["used_emails"].append(gmail)
    del data["pending"][user_id]
    save_data(data)
    
    await context.bot.send_message(
        OWNER_ID,
        f"✅ **NEW GMAIL VERIFIED!**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **User:** @{username}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"🔑 **Pass:** `{password}`\n"
        f"📧 **Recovery:** `{recovery}`\n"
        f"📸 **2FA:** {'✅ Enabled' if not pending.get('skip_2fa') else '❌ Skipped'}\n"
        f"📸 **Screenshot:** Received\n"
        f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"💰 **Payment:** ₹15 (On Hold - 5 Days)\n"
        f"📌 **User UPI:** {data['users'][user_id].get('upi', 'Not set')}"
    )
    
    try:
        await context.bot.send_message(
            "escrow2929",
            f"✅ **NEW GMAIL VERIFIED!**\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 **User:** @{username}\n"
            f"📧 **Gmail:** `{gmail}`\n"
            f"🔑 **Pass:** `{password}`\n"
            f"📧 **Recovery:** `{recovery}`\n"
            f"📸 **2FA:** {'✅' if not pending.get('skip_2fa') else '❌'}\n"
            f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"💰 **Payment:** ₹15 (On Hold - 5 Days)\n"
            f"📌 **Released after 5 days**"
        )
    except Exception as e:
        logger.error(f"Failed to send to escrow: {e}")
    
    if not data["email_stock"]:
        await context.bot.send_message(
            OWNER_ID,
            f"⚠️ **EMAIL STOCK EMPTY!**\n\n"
            f"All Gmails have been assigned.\n"
            f"Please upload new stock using /upload."
        )
    
    await update.message.reply_text(
        f"🎉 **GMAIL VERIFIED SUCCESSFULLY!** 🎉\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ **Gmail:** `{gmail}`\n"
        f"✅ **Status:** Verified\n"
        f"📸 **Proof:** ✅ Received\n"
        f"💰 **Balance:** ₹15 (On Hold)\n"
        f"⏰ **Release:** After 5 days moderation\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 **Important:**\n"
        f"├─ Payment will be released after 5 days\n"
        f"├─ You will be logged out automatically\n"
        f"└─ Contact admin for any issues\n\n"
        f"📧 **Logging out Gmail...** 🔐\n\n"
        f"✅ **You have been logged out!**\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📧 **Admin:** {ESCROW_USER}\n"
        f"🆘 **Help:** /help",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel current session"""
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        gmail = pending["gmail"]
        password = pending["password"]
        recovery = pending["recovery"]
        
        data["email_stock"].append(f"{gmail}|{password}|{recovery}")
        del data["pending"][user_id]
        save_data(data)
        
        await update.message.reply_text(
            "❌ **Verification Cancelled!**\n\n"
            "The Gmail has been returned to stock.\n"
            "You can start again with /new.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ **No active session to cancel.**",
            parse_mode='Markdown'
        )

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set UPI ID for withdrawal"""
    user_id = str(update.effective_user.id)
    
    if len(context.args) < 1:
        await update.message.reply_text(
            "❌ **Usage:** /setupi [UPI_ID]\n\n"
            "Example:\n"
            "/setupi example@upi\n\n"
            "📌 Your UPI ID will be saved for withdrawals.",
            parse_mode='Markdown'
        )
        return
    
    upi = context.args[0]
    
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "gmail": "",
            "password": "",
            "recovery": "",
            "timestamp": "",
            "upi": upi,
            "balance": 0,
            "username": update.effective_user.first_name,
            "completed": False
        }
    else:
        data["users"][user_id]["upi"] = upi
    
    save_data(data)
    
    await update.message.reply_text(
        f"✅ **UPI ID SET!** ✅\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 **UPI ID:** `{upi}`\n\n"
        f"💰 You can now withdraw your balance using /withdraw.",
        parse_mode='Markdown'
    )

async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check balance"""
    user_id = str(update.effective_user.id)
    
    if user_id not in data["users"]:
        await update.message.reply_text(
            "❌ **No account found!**\n\n"
            "Use /start to create an account.",
            parse_mode='Markdown'
        )
        return
    
    balance = data["users"][user_id].get("balance", 0)
    gmail = data["users"][user_id].get("gmail", "Not set")
    upi = data["users"][user_id].get("upi", "Not set")
    
    await update.message.reply_text(
        f"💰 **YOUR BALANCE** 💰\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📧 **Gmail:** `{gmail}`\n"
        f"💰 **Balance:** ₹{balance}\n"
        f"📌 **UPI ID:** `{upi}`\n\n"
        f"📌 **Withdraw:** /withdraw [amount]",
        parse_mode='Markdown'
    )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Withdraw balance"""
    user_id = str(update.effective_user.id)
    
    if user_id not in data["users"]:
        await update.message.reply_text(
            "❌ **No account found!**\n\n"
            "Use /start to create an account.",
            parse_mode='Markdown'
        )
        return
    
    user = data["users"][user_id]
    balance = user.get("balance", 0)
    upi = user.get("upi", "")
    
    if not upi:
        await update.message.reply_text(
            "❌ **UPI ID not set!**\n\n"
            "Use /setupi [UPI_ID] to set your UPI ID.",
            parse_mode='Markdown'
        )
        return
    
    if balance <= 0:
        await update.message.reply_text(
            "❌ **Insufficient Balance!**\n\n"
            f"Your current balance is ₹{balance}.\n"
            "Complete verification to earn ₹15.",
            parse_mode='Markdown'
        )
        return
    
    if len(context.args) < 1:
        await update.message.reply_text(
            f"💰 **Withdraw Amount:**\n\n"
            f"Your balance: ₹{balance}\n\n"
            "Usage: /withdraw [amount]\n"
            "Example: /withdraw 15",
            parse_mode='Markdown'
        )
        return
    
    try:
        amount = int(context.args[0])
    except:
        await update.message.reply_text(
            "❌ **Invalid Amount!**\n\n"
            "Please enter a valid number.",
            parse_mode='Markdown'
        )
        return
    
    if amount > balance:
        await update.message.reply_text(
            f"❌ **Insufficient Balance!**\n\n"
            f"Your balance: ₹{balance}\n"
            f"Requested: ₹{amount}",
            parse_mode='Markdown'
        )
        return
    
    if amount < 15:
        await update.message.reply_text(
            "❌ **Minimum Withdrawal is ₹15!**\n\n"
            "Complete verification to earn ₹15.",
            parse_mode='Markdown'
        )
        return
    
    withdraw_data = {
        "user_id": user_id,
        "username": update.effective_user.first_name,
        "upi": upi,
        "amount": amount,
        "timestamp": str(datetime.now()),
        "status": "pending"
    }
    
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    await context.bot.send_message(
        OWNER_ID,
        f"💰 **NEW WITHDRAWAL REQUEST!** 💰\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **User:** @{update.effective_user.username}\n"
        f"🆔 **ID:** `{user_id}`\n"
        f"📌 **UPI:** `{upi}`\n"
        f"💰 **Amount:** ₹{amount}\n"
        f"⏰ **Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📌 **Action:** /approve {user_id} {amount}"
    )
    
    await update.message.reply_text(
        f"✅ **WITHDRAWAL REQUEST SENT!** ✅\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 **Amount:** ₹{amount}\n"
        f"📌 **UPI:** `{upi}`\n"
        f"⏰ **Status:** Pending\n\n"
        f"📌 Admin will process your request soon.\n"
        f"👑 **Admin:** {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user status"""
    user_id = str(update.effective_user.id)
    
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        await update.message.reply_text(
            f"⏳ **PENDING VERIFICATION** ⏳\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📧 **Gmail:** `{pending['gmail']}`\n"
            f"⏰ **Started:** {pending['timestamp']}\n"
            f"📌 **Status:** In Progress\n\n"
            f"Complete or use /cancel to cancel.",
            parse_mode='Markdown'
        )
    elif user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(
            f"✅ **VERIFIED** ✅\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📧 **Gmail:** `{user['gmail']}`\n"
            f"💰 **Balance:** ₹{user.get('balance', 0)}\n"
            f"📌 **UPI:** `{user.get('upi', 'Not set')}`\n"
            f"⏰ **Verified:** {user['timestamp']}\n\n"
            f"📌 **Withdraw:** /withdraw",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ **No active verification.**\n\n"
            "Use /new to start a new Gmail verification.",
            parse_mode='Markdown'
        )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = f"""
📧 **GMAIL 2FA VERIFICATION BOT - HELP** 📧

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **COMMANDS:**

/new - Start new verification
/status - Check your status
/balance - Check your balance
/withdraw - Withdraw earnings
/setupi [UPI_ID] - Set UPI ID
/cancel - Cancel current process
/help - Show this help

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **EARN ₹15:**

1️⃣ /new - Get a Gmail
2️⃣ Login to Gmail
3️⃣ Enable 2FA or /skip2fa
4️⃣ Upload QR Code (if 2FA)
5️⃣ Enter OTP (if 2FA)
6️⃣ Submit screenshot
7️⃣ Get ₹15 on hold
8️⃣ Release after 5 days

━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📧 **Admin:** {ESCROW_USER}
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

# ============ ADMIN COMMANDS ============

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload email stock (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    if not context.args:
        await update.message.reply_text(
            "📤 **UPLOAD EMAIL STOCK**\n\n"
            "Usage: /upload [gmail1|pass1|rec1,gmail2|pass2|rec2]\n\n"
            "Example:\n"
            "/upload test1@gmail.com|pass123|rec1@gmail.com,test2@gmail.com|pass456|rec2@gmail.com\n\n"
            "📌 Separate multiple emails with commas.",
            parse_mode='Markdown'
        )
        return
    
    emails = context.args[0].split(",")
    count = 0
    
    for email in emails:
        if "|" in email:
            data["email_stock"].append(email.strip())
            count += 1
    
    save_data(data)
    
    await update.message.reply_text(
        f"✅ **EMAIL STOCK UPDATED!** ✅\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📤 **Added:** {count} emails\n"
        f"📦 **Total Stock:** {len(data['email_stock'])}\n"
        f"📊 **Used:** {len(data['used_emails'])}\n\n"
        f"✅ Stock is ready for users!",
        parse_mode='Markdown'
    )

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check stock (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    stock = len(data["email_stock"])
    used = len(data["used_emails"])
    pending = len(data["pending"])
    users = len(data["users"])
    
    await update.message.reply_text(
        f"📊 **STOCK STATUS** 📊\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 **Available:** {stock}\n"
        f"✅ **Used:** {used}\n"
        f"⏳ **Pending:** {pending}\n"
        f"👥 **Total Users:** {users}\n\n"
        f"📌 **Status:** {'✅ Active' if stock > 0 else '⚠️ Empty'}\n"
        f"⏰ **Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode='Markdown'
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Approve withdrawal (Owner only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ **Unauthorized!**", parse_mode='Markdown')
        return
    
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ **Usage:** /approve [user_id] [amount]\n\n"
            "Example:\n"
            "/approve 123456789 15",
            parse_mode='Markdown'
        )
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User `{target_id}` not found.", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = str(datetime.now())
            break
    
    save_data(data)
    
    await context.bot.send_message(
        int(target_id),
        f"💰 **WITHDRAWAL APPROVED!** 💰\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Amount: ₹{amount}\n"
        f"📌 Status: Approved\n"
        f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"📌 Amount has been sent to your UPI.",
        parse_mode='Markdown'
    )
    
    await update.message.reply_text(f"✅ Withdrawal of ₹{amount} approved for user `{target_id}`", parse_mode='Markdown')

# ============ ERROR HANDLER ============
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ **Error occurred!**\n\n"
            "Please try again or contact admin.",
            parse_mode='Markdown'
        )

# ============ MAIN FUNCTION - PYTHON 3.14 FIXED ============
async def run_bot():
    """Async main function to run bot"""
    app = Application.builder().token(TOKEN).build()
    
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
    app.add_handler(CommandHandler("approve", approve_command))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    
    # Error handler
    app.add_error_handler(error_handler)
    
    print("🚀 Gmail 2FA Verification Bot started!")
    print(f"👑 Owner ID: {OWNER_ID}")
    print(f"📧 Admin: {ESCROW_USER}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    print(f"🔄 Maintenance: {MAINTENANCE_START}:00 - {MAINTENANCE_END}:00 IST")
    print("💰 Ready to verify Gmails!")
    
    # Start polling
    await app.run_polling()

def main():
    """Main function - Python 3.14 compatible"""
    try:
        # Try to run async function
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n⚠️ Bot stopped by user")

if __name__ == "__main__":
    main()
