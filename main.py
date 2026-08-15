import logging
import random
import string
import time
import re
import json
import os
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# ============ CONFIGURATION ============
TOKEN = "8875994072:AAGjHaMn526uaKXqBEswh53lIPZIm81qOCs"
OWNER_ID = 8785590284
ESCROW_USER = "@escrow2929"

# ============ TIME CONFIGURATION ============
MAINTENANCE_START = 22  # 10 PM
MAINTENANCE_END = 10    # 10 AM

# ============ DATABASE ============
DATA_FILE = "bot_data.json"

def load_data():
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
        "withdraw_requests": []
    }

def save_data(data):
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4, default=str)

data = load_data()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_maintenance_mode():
    now = datetime.now()
    return now.hour >= MAINTENANCE_START or now.hour < MAINTENANCE_END

# ============ COMMAND HANDLERS ============

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = str(user.id)
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode (10 PM - 10 AM IST). Try after 10 AM.", parse_mode='Markdown')
        return
    
    if user_id not in data["users"]:
        data["users"][user_id] = {"gmail": "", "password": "", "recovery": "", "timestamp": "", "upi": "", "balance": 0, "username": user.first_name, "completed": False}
        save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL VERIFICATION BOT**\n\n👋 Hello {user.first_name}!\n💰 **Earn ₹15 per Gmail!**\n\n"
        "📋 **Commands:**\n/new - Start\n/status - Check status\n/balance - Check balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - Help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def new_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    
    if is_maintenance_mode():
        await update.message.reply_text("🛠️ Maintenance Mode. Try after 10 AM.", parse_mode='Markdown')
        return
    
    if user_id in data["users"] and data["users"][user_id].get("completed", False):
        await update.message.reply_text(f"❌ Already completed! Gmail: `{data['users'][user_id]['gmail']}`", parse_mode='Markdown')
        return
    
    if not data["email_stock"]:
        await update.message.reply_text("❌ No stock! Admin notified.", parse_mode='Markdown')
        await context.bot.send_message(OWNER_ID, "⚠️ STOCK EMPTY! Use /upload")
        return
    
    if user_id in data["pending"]:
        await update.message.reply_text("⏳ Pending verification! Use /cancel", parse_mode='Markdown')
        return
    
    email_data = data["email_stock"].pop(0)
    gmail, password, recovery = email_data.split("|")
    
    data["pending"][user_id] = {"gmail": gmail, "password": password, "recovery": recovery, "timestamp": str(datetime.now()), "username": username}
    save_data(data)
    
    await update.message.reply_text(
        f"📧 **GMAIL ASSIGNED!**\n\n📧 `{gmail}`\n🔑 `{password}`\n📧 Recovery: `{recovery}`\n\n"
        "📌 Login → Enable 2FA or /skip2fa → Upload QR → Enter OTP → Screenshot\n\n"
        "⚡ /skip2fa - Skip 2FA\n/cancel - Cancel",
        parse_mode='Markdown'
    )

async def skip2fa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id not in data["pending"]:
        await update.message.reply_text("❌ No pending!", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["skip_2fa"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text("✅ 2FA Skipped!\n\n📸 Send screenshot of Gmail inbox & settings.", parse_mode='Markdown')

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    await update.message.reply_text(f"✅ QR Received!\n\n📱 OTP: `{otp}`\n\nEnter the OTP:", parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text
    if not text or user_id not in data["pending"]:
        return
    
    if data["pending"][user_id].get("step") == "waiting_otp":
        await handle_otp_input(update, context)

async def handle_otp_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    text = update.message.text.strip()
    
    if not text.isdigit() or len(text) != 6:
        await update.message.reply_text("❌ Enter 6-digit OTP!", parse_mode='Markdown')
        return
    
    stored_otp = data["pending"][user_id].get("otp")
    if int(text) != stored_otp:
        await update.message.reply_text("❌ Wrong OTP! Try again.", parse_mode='Markdown')
        return
    
    data["pending"][user_id]["otp_verified"] = True
    data["pending"][user_id]["step"] = "waiting_screenshot"
    save_data(data)
    
    await update.message.reply_text("✅ OTP Verified!\n\n📸 Send screenshot of Gmail inbox & settings.", parse_mode='Markdown')

async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    data["users"][user_id] = {
        "gmail": gmail, "password": password, "recovery": recovery,
        "timestamp": str(datetime.now()),
        "upi": data["users"].get(user_id, {}).get("upi", ""),
        "balance": 15, "username": username, "completed": True,
        "screenshot": file_id,
        "skip_2fa": pending.get("skip_2fa", False)
    }
    
    data["used_emails"].append(gmail)
    del data["pending"][user_id]
    save_data(data)
    
    # Send to owner
    await context.bot.send_message(
        OWNER_ID,
        f"✅ NEW VERIFIED!\n👤 @{username}\n📧 `{gmail}`\n🔑 `{password}`\n📧 Recovery: `{recovery}`\n"
        f"📸 2FA: {'✅' if not pending.get('skip_2fa') else '❌ Skipped'}\n💰 ₹15 (Hold 5 Days)"
    )
    
    # Send to escrow
    try:
        await context.bot.send_message(
            "escrow2929",
            f"✅ NEW GMAIL!\n👤 @{username}\n📧 `{gmail}`\n🔑 `{password}`\n💰 ₹15 (5 Days Hold)"
        )
    except:
        pass
    
    if not data["email_stock"]:
        await context.bot.send_message(OWNER_ID, "⚠️ STOCK EMPTY! Upload new.")
    
    await update.message.reply_text(
        f"🎉 **VERIFIED!** 🎉\n\n✅ Gmail: `{gmail}`\n💰 ₹15 (5 Days Hold)\n\n"
        f"📧 Logged out!\n👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        pending = data["pending"][user_id]
        data["email_stock"].append(f"{pending['gmail']}|{pending['password']}|{pending['recovery']}")
        del data["pending"][user_id]
        save_data(data)
        await update.message.reply_text("❌ Cancelled! Gmail returned.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active session.", parse_mode='Markdown')

async def setupi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    user_id = str(update.effective_user.id)
    if user_id not in data["users"]:
        await update.message.reply_text("❌ No account!", parse_mode='Markdown')
        return
    user = data["users"][user_id]
    await update.message.reply_text(f"💰 Balance: ₹{user.get('balance', 0)}\n📧 Gmail: `{user.get('gmail', 'Not set')}`\n📌 UPI: `{user.get('upi', 'Not set')}`", parse_mode='Markdown')

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
    withdraw_data = {"user_id": user_id, "username": update.effective_user.first_name, "upi": upi, "amount": amount, "timestamp": str(datetime.now()), "status": "pending"}
    if "withdraw_requests" not in data:
        data["withdraw_requests"] = []
    data["withdraw_requests"].append(withdraw_data)
    save_data(data)
    
    await context.bot.send_message(OWNER_ID, f"💰 WITHDRAWAL!\n👤 @{update.effective_user.username}\n📌 `{upi}`\n💰 ₹{amount}\n/approve {user_id} {amount}")
    await update.message.reply_text(f"✅ Request Sent!\n💰 ₹{amount}\n📌 Pending\n👑 Admin: {ESCROW_USER}", parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id in data["pending"]:
        await update.message.reply_text(f"⏳ Pending: `{data['pending'][user_id]['gmail']}`", parse_mode='Markdown')
    elif user_id in data["users"] and data["users"][user_id].get("completed", False):
        user = data["users"][user_id]
        await update.message.reply_text(f"✅ Verified: `{user['gmail']}`\n💰 ₹{user.get('balance', 0)}", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active verification. Use /new", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📧 **HELP**\n\n"
        "/new - Start\n/status - Status\n/balance - Balance\n/withdraw - Withdraw\n/setupi [UPI] - Set UPI\n/cancel - Cancel\n/help - Help\n\n"
        f"👑 Admin: {ESCROW_USER}",
        parse_mode='Markdown'
    )

# ============ ADMIN COMMANDS ============

async def upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text("Usage: /upload [gmail|pass|rec,gmail2|pass2|rec2]", parse_mode='Markdown')
        return
    
    emails = context.args[0].split(",")
    count = 0
    for email in emails:
        if "|" in email:
            data["email_stock"].append(email.strip())
            count += 1
    save_data(data)
    await update.message.reply_text(f"✅ Added {count} emails. Total: {len(data['email_stock'])}", parse_mode='Markdown')

async def stock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    await update.message.reply_text(
        f"📊 **STOCK**\n\n📦 Available: {len(data['email_stock'])}\n✅ Used: {len(data['used_emails'])}\n⏳ Pending: {len(data['pending'])}\n👥 Users: {len(data['users'])}",
        parse_mode='Markdown'
    )

async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve [user_id] [amount]", parse_mode='Markdown')
        return
    
    target_id = context.args[0]
    amount = int(context.args[1])
    if target_id not in data["users"]:
        await update.message.reply_text(f"❌ User not found.", parse_mode='Markdown')
        return
    
    data["users"][target_id]["balance"] -= amount
    for req in data.get("withdraw_requests", []):
        if req["user_id"] == target_id and req["amount"] == amount and req["status"] == "pending":
            req["status"] = "approved"
            req["approved_at"] = str(datetime.now())
            break
    save_data(data)
    
    await context.bot.send_message(int(target_id), f"💰 ₹{amount} Approved!", parse_mode='Markdown')
    await update.message.reply_text(f"✅ Approved ₹{amount} for `{target_id}`", parse_mode='Markdown')

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ============ MAIN ============
def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("new", new_command))
    app.add_handler(CommandHandler("skip2fa", skip2fa_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("balance", balance_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("setupi", setupi_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("help", help_command))
    
    app.add_handler(CommandHandler("upload", upload_command))
    app.add_handler(CommandHandler("stock", stock_command))
    app.add_handler(CommandHandler("approve", approve_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    app.add_error_handler(error_handler)
    
    print("🚀 Bot started!")
    print(f"👑 Owner: {OWNER_ID}")
    print(f"📦 Stock: {len(data['email_stock'])}")
    
    app.run_polling()

if __name__ == "__main__":
    main()
