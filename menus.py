"""
Menu structures and keyboard layouts for the Telegram bot
"""
import math
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from database import DEFAULT_VPN_PLANS, get_vpn_plans
from config import USE_ONE_MONTH_MODE 

VPN_PLANS = {plan['plan_key']: plan for plan in DEFAULT_VPN_PLANS}


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

    catalog = get_vpn_plans()
    if not catalog:
        catalog = DEFAULT_VPN_PLANS

    for plan in catalog:
        plan_key = plan["plan_key"]
        plan_name = plan["name"]
        if days_until_expiry is not None:
            plan_name = f"{int(days_until_expiry)} روزه"
        if USE_ONE_MONTH_MODE:
            plan_name = "یک ماهه"

        plans[plan_key] = {**plan, "name": plan_name}

    return plans


def _format_price_toman(amount):
    try:
        n = float(amount)
    except Exception:
        return str(amount) + " تومن"

    if n.is_integer():
        s = f"{int(n):,}"
    else:
        s = f"{n:,.2f}".rstrip('0').rstrip('.')
    return f"{s} تومن"

# Free trial plans
def get_free_trial_keyboard():
    # return [
    #     [InlineKeyboardButton("درحال حاضر فعال نمیباشد", callback_data="back_to_main")],
    # ]
    return [
        [InlineKeyboardButton("🎁 دریافت 1GB رایگان تست یک روزه(تنها یکبار)", callback_data="free_1gb")],
        [InlineKeyboardButton("🎁 دریافت 5GB رایگان تست یک هفته ای (تنها یکبار)", callback_data="free_5gb")]
    ]

# Regular VPN plans keyboard
def get_vpn_plans_keyboard(policy=None):
    plans = build_vpn_plans(policy)
    keyboard = []
    for plan_key, plan in plans.items():
        label = f"{plan['name']} | {plan['gb']:g} گیگ | {_format_price_toman(plan['price'])}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"plan_{plan_key}")])

    if not keyboard:
        keyboard.append([InlineKeyboardButton("پلنی ثبت نشده است", callback_data="back_to_main")])

    return keyboard


def get_vpn_extend_plans_keyboard(email, policy=None):
    plans = build_vpn_plans(policy)
    keyboard = []
    for plan_key, plan in plans.items():
        label = f"➕ {plan['gb']:g} گیگ | {_format_price_toman(plan['price'])}"
        keyboard.append([InlineKeyboardButton(label, callback_data=f"extend_plan_{plan_key}")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=f"status_{email}")])
    return keyboard

# Main menu keyboard
def get_main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("خرید سرویس", callback_data="buy_service")],
        [InlineKeyboardButton("دعوت از دوستان", callback_data="referral_info")],
        [InlineKeyboardButton("💰 کیف پول", callback_data="wallet_menu")],
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


def get_wallet_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ شارژ کیف پول", callback_data="wallet_topup")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")]
    ])


def get_payment_method_keyboard(back_callback="back_to_main"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 پرداخت با کیف پول", callback_data="pay_wallet")],
        [InlineKeyboardButton("💳 پرداخت مستقیم", callback_data="pay_direct")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)]
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
        [InlineKeyboardButton("💰 شارژ کیف پول کاربر", callback_data="admin_charge_wallet"),
         InlineKeyboardButton("➕ ایجاد کانفیگ کاربر", callback_data="admin_assign_config")],
        [InlineKeyboardButton("💳 مدیریت شماره کارت‌ها", callback_data="admin_cards")],
        [InlineKeyboardButton("🎫 تیکت‌های پشتیبانی", callback_data="admin_tickets")],
        [InlineKeyboardButton("✉️ پیام به یک کاربر", callback_data="admin_msg_user")],
        [InlineKeyboardButton("👨‍💻 مدیریت کلاینت ها", callback_data="admin_manage_clients")],
        [InlineKeyboardButton("📢 ارسال پیام به همه", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🖥️ مدیریت سرورها", callback_data="admin_servers")],
        [InlineKeyboardButton("📜 Service Policy", callback_data="admin_service_policy")],
            [InlineKeyboardButton("🛠️ مدیریت پلن‌ها", callback_data="admin_plans")],
        [InlineKeyboardButton("⏱️ تنظیم تاریخ انقضای همه کلاینت‌ها", callback_data="admin_extend_all")],
        [InlineKeyboardButton("فعال/غیر فعال سازی فروش", callback_data="admin_buy_allow")]
    ])

def get_extend_all_client_day(server_id):
    """Keyboard for selecting days to extend configs on a specific server."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1 روز افزایش تاریخ انقضا", callback_data=f"admin_ext_days_{server_id}_1")],
        [InlineKeyboardButton("3 روز افزایش تاریخ انقضا", callback_data=f"admin_ext_days_{server_id}_3")],
        [InlineKeyboardButton("10 روز افزایش تاریخ انقضا", callback_data=f"admin_ext_days_{server_id}_10")],
        [InlineKeyboardButton("برگشت", callback_data="admin_menu")]
    ])

def get_admin_server_fields_keyboard(server_id):
    """Keyboard for selecting which specific server field to edit."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("نام سرور (Name)", callback_data=f"admin_server_setfield_{server_id}_name")],
        [InlineKeyboardButton("آدرس پنل (URL)", callback_data=f"admin_server_setfield_{server_id}_url")],
        [InlineKeyboardButton("نام کاربری (Username)", callback_data=f"admin_server_setfield_{server_id}_username"),
         InlineKeyboardButton("رمز عبور (Password)", callback_data=f"admin_server_setfield_{server_id}_password")],
        [InlineKeyboardButton("شناسه Inbound", callback_data=f"admin_server_setfield_{server_id}_inbound_id")],
        [InlineKeyboardButton("Host/IP", callback_data=f"admin_server_setfield_{server_id}_host"),
         InlineKeyboardButton("پورت (Port)", callback_data=f"admin_server_setfield_{server_id}_port")],
        [InlineKeyboardButton("SNI", callback_data=f"admin_server_setfield_{server_id}_sni"),
         InlineKeyboardButton("متن VLESS", callback_data=f"admin_server_setfield_{server_id}_vless_text")],
        [InlineKeyboardButton("پورت ساب (Sub Port)", callback_data=f"admin_server_setfield_{server_id}_sub_port"),
         InlineKeyboardButton("مسیر ساب (Sub Path)", callback_data=f"admin_server_setfield_{server_id}_sub_path")],
        [InlineKeyboardButton("🔙 بازگشت به جزئیات سرور", callback_data=f"admin_server_edit_{server_id}")]
    ])

def get_admin_extend_server_keyboard(servers):
    """Keyboard to select which server's clients should be extended."""
    keyboard = []
    for srv in servers:
        keyboard.append([
            InlineKeyboardButton(f"🌍 {srv['name']} ({srv['server_id']})", callback_data=f"admin_ext_srv_{srv['server_id']}")
        ])
    keyboard.append([InlineKeyboardButton("🌐 اعمال روی همه سرورها", callback_data="admin_ext_srv_all")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_buy_allow_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("بله", callback_data="admin_buy_allow_yes")],
        [InlineKeyboardButton("خیر", callback_data="admin_buy_allow_no")],
        [InlineKeyboardButton("برگشت", callback_data="admin_menu")],

    ])
# ============================================================
# MULTI-SERVER MENUS
# ============================================================

def get_server_selection_keyboard(servers, back_callback="back_to_main"):
    """
    Build a keyboard for choosing a server.
    servers: list of dicts with 'server_id' and 'name'
    """
    keyboard = []
    for srv in servers:
        keyboard.append([
            InlineKeyboardButton(
                f"🌍 {srv['name']}",
                callback_data=f"select_server_{srv['server_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data=back_callback)])
    return InlineKeyboardMarkup(keyboard)


def get_admin_servers_keyboard(servers):
    """Admin server management keyboard."""
    keyboard = []
    for srv in servers:
        status_icon = "✅" if srv.get('is_active') else "❌"
        keyboard.append([
            InlineKeyboardButton(
                f"{status_icon} {srv['name']} ({srv['server_id']})",
                callback_data=f"admin_server_edit_{srv['server_id']}"
            )
        ])
    keyboard.append([InlineKeyboardButton("➕ افزودن سرور جدید", callback_data="admin_server_add")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_server_actions_keyboard(server_id):
    """Actions for a single server in admin view."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ ویرایش", callback_data=f"admin_server_edit_fields_{server_id}")],
        [InlineKeyboardButton("🔄 فعال/غیرفعال", callback_data=f"admin_server_toggle_{server_id}")],
        [InlineKeyboardButton("🗑️ حذف", callback_data=f"admin_server_delete_{server_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_servers")],
    ])

def get_admin_cards_keyboard(cards):
    keyboard = []
    for card in cards:
        status = "✅" if card['is_active'] else "❌"
        keyboard.append([InlineKeyboardButton(f"{status} {card['card_number']} ({card['owner_name']})", callback_data=f"admin_card_edit_{card['card_id']}")])
    keyboard.append([InlineKeyboardButton("➕ افزودن شماره کارت", callback_data="admin_card_add")])
    keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="admin_menu")])
    return InlineKeyboardMarkup(keyboard)

def get_admin_card_actions_keyboard(card_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 فعال/غیرفعال کردن", callback_data=f"admin_card_toggle_{card_id}")],
        [InlineKeyboardButton("🗑️ حذف کارت", callback_data=f"admin_card_delete_{card_id}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="admin_cards")]
    ])