"""
Menu structures and keyboard layouts for the Telegram bot
"""
import math
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# VPN plans
VPN_PLANS = {
    "gb_1": {"name": "(1 Gb)", "gb": 1},
    "gb_2": {"name": "(2 Gb)", "gb": 2},
    "gb_5": {"name": "(5 Gb)", "gb": 5},
    "gb_10": {"name": "(10 Gb)", "gb": 10},
}


def get_days_until_expiry(expiry_time_ms):
    if not expiry_time_ms:
        return None

    remaining_ms = int(expiry_time_ms) - int(time.time() * 1000)
    if remaining_ms <= 0:
        return 0

    return max(1, math.ceil(remaining_ms / 86400000))


def build_vpn_plans(policy=None):
    plans = {}
    days_until_expiry = get_days_until_expiry((policy or {}).get("global_expiry_time_ms"))

    for plan_key, plan in VPN_PLANS.items():
        plan_name = plan["name"]
        if days_until_expiry is not None:
            plan_name = f"{plan_name} | {days_until_expiry}  روزه"
            # plan_name = f"{days_until_expiry}  روزه"

        plans[plan_key] = {**plan, "name": plan_name}

    return plans

# Free trial plans
def get_free_trial_keyboard():
    return [
        [InlineKeyboardButton("🎁 دریافت 1GB رایگان تست یک روزه(تنها یکبار)", callback_data="free_1gb")],
        [InlineKeyboardButton("🎁 دریافت 5GB رایگان تست یک هفته ای (تنها یکبار)", callback_data="free_5gb")]
    ]

# Regular VPN plans keyboard
def get_vpn_plans_keyboard(policy=None):
    plans = build_vpn_plans(policy)
    return [
        [InlineKeyboardButton(plans["gb_1"]["name"], callback_data="gb_1")],
        [InlineKeyboardButton(plans["gb_2"]["name"], callback_data="gb_2")],
        [InlineKeyboardButton(plans["gb_5"]["name"], callback_data="gb_5")],
        [InlineKeyboardButton(plans["gb_10"]["name"], callback_data="gb_10")]
    ]
def get_vpn_extend_plans_keyboard(email, policy=None):
    plans = build_vpn_plans(policy)
    keyboard = [
        [InlineKeyboardButton(f"➕{plans['gb_1']['name']} (بدون تمدید زمانی)", callback_data="extend_gb_1")],
        [InlineKeyboardButton(f"➕{plans['gb_2']['name']} (بدون تمدید زمانی)", callback_data="extend_gb_2")],
        [InlineKeyboardButton(f"➕{plans['gb_5']['name']} (بدون تمدید زمانی)", callback_data="extend_gb_5")],
        [InlineKeyboardButton(f"➕{plans['gb_10']['name']} (بدون تمدید زمانی)", callback_data="extend_gb_10")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"status_{email}")]
    ]
    return keyboard

# Main menu keyboard
def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("خرید سرویس", callback_data="buy_service")],
        [InlineKeyboardButton("🎁 سرویس هدیه و تست ", callback_data="buy_service_gift")],
        [InlineKeyboardButton("مشاهده وضعیت سرویس", callback_data="check_status")],
        [InlineKeyboardButton("🔧 پشتیبانی", callback_data="support")]
    ])

# Support menu keyboard
def get_support_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📩 ایجاد تیکت جدید", callback_data="support_new")],
        [InlineKeyboardButton("📨 تیکت های من", callback_data="support_my_tickets")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
    ])

# Back to main menu button
def get_back_to_main_button():
    return [[InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="back_to_main")]]

# Create a keyboard for a list of configs
def get_configs_keyboard(configs):
    keyboard = []

    for config in configs:
        config_id, email, _, total_gb, is_active = config
        status_icon = "✅" if is_active else "❌"
        keyboard.append([InlineKeyboardButton(
            f"{status_icon} {email} ({total_gb}GB)",
            callback_data=f"status_{email}"
        )])

    keyboard.append([InlineKeyboardButton("بازگشت به منوی اصلی", callback_data="back_to_main")])
    return InlineKeyboardMarkup(keyboard)

# Create a keyboard for showing config status
def get_config_status_keyboard():
    """Get keyboard for config status view"""
    keyboard = [
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="refresh_status")],
        [InlineKeyboardButton("⏫ افزایش حجم", callback_data="extend_config")],
        [InlineKeyboardButton("بازگشت به لیست سرویس ها", callback_data="check_status")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="back_to_main")]
    ]
    return InlineKeyboardMarkup(keyboard)

# Admin approval keyboard
def get_admin_approval_keyboard(payment_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("تأیید", callback_data=f"approve_{payment_id}"),
            InlineKeyboardButton("رد", callback_data=f"reject_{payment_id}")
        ]
    ])

# Admin menu keyboard
def get_admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 درخواست‌های در انتظار", callback_data="admin_pending")],
        [InlineKeyboardButton("👥 مشاهده کاربران", callback_data="admin_users")],
        [InlineKeyboardButton("🎫 تیکت‌های پشتیبانی", callback_data="admin_tickets")],
        [InlineKeyboardButton("👨‍💻 مدیریت کلاینت ها", callback_data="admin_manage_clients")],
        [InlineKeyboardButton("📢 ارسال پیام به همه", callback_data="admin_broadcast")],
        [InlineKeyboardButton("⏱️ تنظیم تاریخ انقضای همه کلاینت‌ها", callback_data="admin_extend_all")],
        [InlineKeyboardButton("فعال/غیر فعال سازی فروش", callback_data="admin_buy_allow")]
    ])

def get_extend_all_client_day():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 روز افزایش تاریخ انقضا", callback_data="admin_extend_all_1")],
        [InlineKeyboardButton("3 روز افزایش تاریخ انقضا", callback_data="admin_extend_all_3")],
        [InlineKeyboardButton("10 روز افزایش تاریخ انقضا", callback_data="admin_extend_all_10")],
        [InlineKeyboardButton("برگشت", callback_data="admin_menu")]
    ])
def get_buy_allow_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("بله", callback_data="admin_buy_allow_yes")],
        [InlineKeyboardButton("خیر", callback_data="admin_buy_allow_no")],
        [InlineKeyboardButton("برگشت", callback_data="admin_menu")],

    ])
