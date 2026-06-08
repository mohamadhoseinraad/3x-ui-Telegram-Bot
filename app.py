"""
Web application for managing VPN services with the same core flows as the Telegram bot.
"""

import logging
import random
import sqlite3
import string
import time
import uuid
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, session, url_for
from flask import make_response
from werkzeug.security import check_password_hash, generate_password_hash

import config
from config import ADMIN_IDS, BOT_ID, DB_FILE, HOST, IPDOMAIN, PORT, SNI, get_payment_msg
from database import (
    add_ticket_message,
    consume_invite_code,
    check_trial_usage,
    close_ticket,
    create_invite_code,
    create_ticket,
    get_all_configs_with_users,
    get_or_create_user,
    get_invite_code,
    get_web_account,
    get_payment_info,
    get_payment_record,
    get_pending_payments,
    get_ticket_conversation,
    get_vpn_plans,
    save_vpn_plan,
    delete_vpn_plan,
    get_user_configs,
    get_user_tickets,
    has_web_accounts,
    get_service_policy,
    update_app_settings,
    list_invite_codes,
    init_db,
    save_new_config,
    save_web_account,
    save_payment_request,
    link_web_account_to_telegram_id,
    update_config_active_status,
    update_config_total_gb,
    adjust_wallet_balance,
    update_payment_status,
    update_ticket_status,
    update_web_account_login,
    verify_ticket_access,
    get_wallet_balance,
    credit_referral_bonus_if_first_service_purchase,
)
from db_utils import delete_config_by_client_id, get_all_db_configs
from menus import VPN_PLANS, build_vpn_plans
from xui_api import create_client, delete_client, extend_client, get_all_clients, get_client_status
from translations import translate
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = "replace-this-with-a-secure-secret"


@app.context_processor
def inject_globals():
    lang = session.get("lang", "fa")
    dir = "rtl" if lang == "fa" else "ltr"

    def t(key, **kwargs):
        return translate(key, lang, **kwargs)

    return {"ADMIN_IDS": ADMIN_IDS, "BOT_ID": BOT_ID, "t": t, "lang": lang, "dir": dir}


@app.route('/set-lang/<lang>')
def set_lang(lang):
    if lang not in ('en', 'fa'):
        return redirect(request.referrer or url_for('dashboard'))
    session['lang'] = lang
    return redirect(request.referrer or url_for('dashboard'))


def random_suffix(length=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_vless_link(client_id, email):
    return (
        f"vless://{client_id}@{IPDOMAIN}:{PORT}"
        f"?{VLESS_TEXT}"
        f"#{email}"
    )


def current_user_id():
    return session.get("user_id")


def is_admin():
    uid = current_user_id()
    return uid in ADMIN_IDS if uid is not None else False


def login_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user_id() is None:
            return redirect(url_for("login"))
        return func(*args, **kwargs)

    return wrapper


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not is_admin():
            flash("You do not have access to admin features.", "error")
            return redirect(url_for("dashboard"))
        return func(*args, **kwargs)

    return wrapper


def _parse_plan_gb(plan_name):
    import re

    if not plan_name:
        return 0

    # Normalize Persian/Arabic digits to ASCII
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    trans = {}
    for i, d in enumerate(persian_digits):
        trans[ord(d)] = ord(str(i))
    for i, d in enumerate(arabic_digits):
        trans[ord(d)] = ord(str(i))
    normalized = plan_name.translate(trans)

    # Look for an explicit GB marker near a number (e.g. '10 گیگ', '10GB')
    m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:گیگابایت|گیگاب|گیگ|GB|G)\b', normalized, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(',', '.'))

    # Fallback: take the first standalone number token found
    m = re.search(r'(\d+(?:[.,]\d+)?)', normalized)
    if m:
        return float(m.group(1).replace(',', '.'))

    return 0


def _db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def _resolve_linked_user_id(username, reference_value=None):
    candidates = []
    if reference_value:
        candidates.append(reference_value)
    candidates.append(username)

    conn = _db_connection()
    try:
        cursor = conn.cursor()
        for candidate in candidates:
            if isinstance(candidate, int):
                cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (candidate,))
            else:
                cleaned_value = candidate.lstrip("@")
                if cleaned_value.isdigit():
                    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (int(cleaned_value),))
                else:
                    cursor.execute(
                        "SELECT user_id FROM users WHERE username = ? ORDER BY join_date DESC LIMIT 1",
                        (cleaned_value,),
                    )
            row = cursor.fetchone()
            if row:
                return row["user_id"]
    finally:
        conn.close()

    return None


def _create_web_only_user(username):
    conn = _db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT MIN(user_id) AS min_user_id FROM users WHERE user_id < 0")
        row = cursor.fetchone()
        next_user_id = -1 if row is None or row["min_user_id"] is None else row["min_user_id"] - 1

        cursor.execute(
            "INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
            (next_user_id, username, username, None),
        )
        conn.commit()
        return next_user_id
    finally:
        conn.close()


def _config_limit_allows(total_gb):
    policy = get_service_policy()
    max_config_gb = policy['max_config_gb']
    return max_config_gb <= 0 or total_gb <= max_config_gb


@app.route("/")
def home():
    if current_user_id() is None:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip() or None
        password = request.form.get("password", "")
        contact_info = request.form.get("contact_info", "").strip() or None
        invite_code = request.form.get("invite_code", "").strip().upper() or None

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template("login.html")

        account = get_web_account(username)
        linked_user_id = None

        if account:
            if not check_password_hash(account["password_hash"], password):
                flash("Invalid username or password.", "error")
                return render_template("login.html")

            linked_user_id = account["linked_user_id"]
            if linked_user_id is None:
                linked_user_id = _resolve_linked_user_id(username, contact_info)
                if linked_user_id is None:
                    linked_user_id = _create_web_only_user(username)

            update_web_account_login(username, contact_info, linked_user_id)
        else:
            bootstrap_mode = not has_web_accounts()

            if not invite_code and not bootstrap_mode:
                flash("Invite code is required to create a new account.", "error")
                return render_template("login.html")

            if not bootstrap_mode:
                invite_record = get_invite_code(invite_code)
                if not invite_record or not invite_record["is_active"] or invite_record["used_at"]:
                    flash("Invalid or already used invite code.", "error")
                    return render_template("login.html")

            linked_user_id = _resolve_linked_user_id(username, contact_info)
            if linked_user_id is None:
                linked_user_id = _create_web_only_user(username)

            password_hash = generate_password_hash(password)
            save_web_account(username, password_hash, contact_info, linked_user_id)

            if not bootstrap_mode:
                if not consume_invite_code(invite_code, username, linked_user_id):
                    flash("Invite code could not be consumed. Please try again.", "error")
                    return render_template("login.html")

        # If the user provided a numeric Telegram id in contact_info and it is listed
        # in ADMIN_IDS, prefer that id as the linked user so the web session has admin rights.
        if contact_info and contact_info.isdigit():
            try:
                contact_tid = int(contact_info)
            except ValueError:
                contact_tid = None

            if contact_tid and contact_tid in ADMIN_IDS:
                # Ensure the Telegram user exists in users table and link the web account
                try:
                    get_or_create_user(contact_tid, username or str(contact_tid), username, None)
                except Exception:
                    # Non-fatal: continue even if user creation fails
                    logger.exception("Failed to ensure admin user exists for web login")

                try:
                    update_web_account_login(username, contact_info, contact_tid)
                except Exception:
                    logger.exception("Failed to link web account to admin Telegram id")

                linked_user_id = contact_tid

        session["user_id"] = linked_user_id
        session["username"] = username
        session["web_username"] = username
        flash("Signed in successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    web_account = get_web_account(session.get("web_username") or session.get("username") or "")
    return render_template(
        "dashboard.html",
        is_admin_user=is_admin(),
        allow_buy=config.ALLOW_BUY,
        web_account=web_account,
        telegram_user_id=current_user_id(),
    )


@app.route("/account/telegram-id", methods=["POST"])
@login_required
def update_telegram_user_id():
    web_username = session.get("web_username") or session.get("username")
    telegram_user_id_raw = request.form.get("telegram_user_id", "").strip()

    if not web_username:
        flash("Unable to resolve the current web account.", "error")
        return redirect(url_for("dashboard"))

    if not telegram_user_id_raw.isdigit():
        flash("Telegram user id must be a numeric value.", "error")
        return redirect(url_for("dashboard"))

    telegram_user_id = int(telegram_user_id_raw)
    success, result = link_web_account_to_telegram_id(web_username, telegram_user_id)
    if not success:
        flash(result, "error")
        return redirect(url_for("dashboard"))

    session["user_id"] = telegram_user_id
    flash("Telegram user id linked successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/configs")
@login_required
def configs_view():
    user_id = current_user_id()
    configs = get_user_configs(user_id)

    rendered = []
    for conf in configs:
        _config_id, email, client_id, total_gb, _active = conf
        status = get_client_status(email)
        if status:
            update_config_active_status(email, user_id, status["is_active"])
            rendered.append(
                {
                    "email": email,
                    "client_id": client_id,
                    "total_gb": status["total_gb"],
                    "remaining_gb": status["remaining_gb"],
                    "remaining_time_display": status["remaining_time_display"],
                    "expiry_date": status["expiry_date"],
                    "is_active": status["is_active"],
                    "vless_link": generate_vless_link(client_id, email),
                }
            )
        else:
            rendered.append(
                {
                    "email": email,
                    "client_id": client_id,
                    "total_gb": total_gb,
                    "remaining_gb": "-",
                    "remaining_time_display": "Unknown",
                    "expiry_date": "Unknown",
                    "is_active": False,
                    "vless_link": generate_vless_link(client_id, email),
                }
            )

    return render_template("configs.html", configs=rendered)


@app.route("/free-trial", methods=["POST"])
@login_required
def free_trial():
    user_id = current_user_id()
    trial_size = request.form.get("trial_size", "")

    if trial_size not in {"1", "5"}:
        flash("Invalid trial option.", "error")
        return redirect(url_for("dashboard"))

    gb_amount = int(trial_size)
    policy = get_service_policy()
    if policy['max_config_gb'] > 0 and gb_amount > policy['max_config_gb']:
        flash(f"Trial size exceeds the configured limit of {policy['max_config_gb']} GB.", "error")
        return redirect(url_for("dashboard"))

    if check_trial_usage(user_id, gb_amount):
        flash(f"You already used the {gb_amount}GB trial.", "error")
        return redirect(url_for("dashboard"))

    suffix = random_suffix()
    username = session.get("username") or f"u{user_id}"
    email = f"{username}_{suffix}@free"
    if len(email) > 50:
        email = f"u{user_id}_{suffix}@free_{gb_amount}_gb"

    total_bytes = gb_amount * (1024 ** 3)
    expiry_time = policy['global_expiry_time_ms']

    client_id, error = create_client(email, total_bytes, expiry_time)
    if error:
        flash(f"Failed to create trial: {error}", "error")
        return redirect(url_for("dashboard"))

    save_new_config(user_id, email, client_id, gb_amount)
    vless_link = generate_vless_link(client_id, email)
    flash(f"Trial created. Config: {vless_link}", "success")
    return redirect(url_for("configs_view"))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy_service():
    if request.method == "POST":
        if not config.ALLOW_BUY:
            flash("Buying is currently disabled.", "error")
            return redirect(url_for("buy_service"))

        plan_key = request.form.get("plan_key", "")
        receipt_text = request.form.get("receipt", "").strip()

        plans = build_vpn_plans(get_service_policy())
        if plan_key not in plans:
            flash("Invalid plan.", "error")
            return redirect(url_for("buy_service"))

        if not receipt_text:
            flash("Receipt/reference is required.", "error")
            return redirect(url_for("buy_service"))

        plan = plans[plan_key]
        policy = get_service_policy()
        if policy['max_config_gb'] > 0 and float(plan.get("gb", 0)) > policy['max_config_gb']:
            flash(f"Plan exceeds the configured limit of {policy['max_config_gb']} GB.", "error")
            return redirect(url_for("buy_service"))

        payment_id = save_payment_request(
            current_user_id(),
            plan["name"],
            receipt_text,
            "web",
            plan.get("price"),
            None,
            None,
            plan_key=plan_key,
            plan_gb=plan.get("gb"),
        )
        flash(f"Payment request #{payment_id} submitted and waiting for admin approval.", "success")
        return redirect(url_for("dashboard"))

    return render_template(
        "buy.html",
        plans=build_vpn_plans(get_service_policy()),
        allow_buy=config.ALLOW_BUY,
        payment_msg=get_payment_msg(),
    )


@app.route("/extend", methods=["POST"])
@login_required
def extend_config_request():
    if not config.ALLOW_BUY:
        flash("Buying is currently disabled.", "error")
        return redirect(url_for("configs_view"))

    user_id = current_user_id()
    email = request.form.get("email", "").strip()
    gb_amount_raw = request.form.get("gb_amount", "").strip()
    receipt_text = request.form.get("receipt", "").strip()

    if not gb_amount_raw.isdigit() or not receipt_text:
        flash("Invalid extension request.", "error")
        return redirect(url_for("configs_view"))

    gb_amount = int(gb_amount_raw)
    policy = get_service_policy()
    client_id = None
    current_total_gb = None
    for conf in get_user_configs(user_id):
        if conf[1] == email:
            client_id = conf[2]
            current_total_gb = float(conf[3])
            break

    if not client_id:
        flash("Config not found.", "error")
        return redirect(url_for("configs_view"))

    if policy['max_config_gb'] > 0 and current_total_gb is not None and current_total_gb + gb_amount > policy['max_config_gb']:
        flash(f"This extension would exceed the configured limit of {policy['max_config_gb']} GB.", "error")
        return redirect(url_for("configs_view"))

    # Support selecting a named plan for extension (admin-managed plans)
    plan_key = request.form.get("plan_key", "").strip()
    plans = build_vpn_plans(get_service_policy())
    if plan_key:
        if plan_key not in plans:
            flash("Invalid plan selected.", "error")
            return redirect(url_for("configs_view"))
        plan = plans[plan_key]
        plan_gb = int(plan.get("gb", gb_amount))
        amount = plan.get("price")
        plan_name = f"تمدید {plan_gb}GB"
        receipt_payload = f"EXT::{email}::{client_id}::{receipt_text}"
        payment_id = save_payment_request(
            user_id,
            plan_name,
            receipt_payload,
            "web",
            amount,
            None,
            None,
            plan_key=plan_key,
            plan_gb=plan_gb,
        )
    else:
        # Keep extension details encoded in plan+receipt so it survives process restarts.
        plan_name = f"تمدید {gb_amount}GB"
        receipt_payload = f"EXT::{email}::{client_id}::{receipt_text}"
        payment_id = save_payment_request(user_id, plan_name, receipt_payload, "web")
    flash(f"Extension payment request #{payment_id} submitted.", "success")
    return redirect(url_for("configs_view"))


@app.route("/support", methods=["GET", "POST"])
@login_required
def support():
    user_id = current_user_id()

    if request.method == "POST":
        subject = request.form.get("subject", "").strip()
        if not subject:
            flash("Ticket subject is required.", "error")
            return redirect(url_for("support"))

        ticket_id = create_ticket(user_id, subject)
        add_ticket_message(ticket_id, user_id, subject, False)
        flash(f"Ticket #{ticket_id} created.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    tickets = get_user_tickets(user_id)
    return render_template("support.html", tickets=tickets)


@app.route("/support/<int:ticket_id>", methods=["GET", "POST"])
@login_required
def ticket_detail(ticket_id):
    user_id = current_user_id()

    data = get_ticket_conversation(ticket_id, user_id, ADMIN_IDS)
    if not data.get("access"):
        flash("Access denied.", "error")
        return redirect(url_for("support"))

    if request.method == "POST":
        action = request.form.get("action", "reply")

        if action == "close":
            has_access, _owner = verify_ticket_access(ticket_id, user_id, ADMIN_IDS)
            if not has_access:
                flash("Access denied.", "error")
                return redirect(url_for("support"))

            close_ticket(ticket_id)
            flash("Ticket closed.", "success")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))

        reply_text = request.form.get("message", "").strip()
        if not reply_text:
            flash("Reply cannot be empty.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))

        is_admin_sender = user_id in ADMIN_IDS
        add_ticket_message(ticket_id, user_id, reply_text, is_admin_sender)
        update_ticket_status(ticket_id, "answered" if is_admin_sender else "open")
        flash("Reply sent.", "success")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    return render_template(
        "ticket_detail.html",
        ticket_id=ticket_id,
        ticket_data=data,
        is_admin_user=is_admin(),
    )


@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    invite_codes = list_invite_codes()
    policy = get_service_policy()
    vpn_plans = get_vpn_plans(include_inactive=True)
    return render_template("admin_dashboard.html", invite_codes=invite_codes, policy=policy, vpn_plans=vpn_plans)


@app.route("/admin/settings", methods=["POST"])
@login_required
@admin_required
def admin_update_settings():
    max_config_gb_raw = request.form.get("max_config_gb", "").strip()
    global_expiry_date = request.form.get("global_expiry_date", "").strip()

    if max_config_gb_raw:
        try:
            max_config_gb = float(max_config_gb_raw)
            if max_config_gb < 0:
                raise ValueError
        except ValueError:
            flash("Max GB must be a non-negative number.", "error")
            return redirect(url_for("admin_dashboard"))
    else:
        max_config_gb = 0

    if not global_expiry_date:
        flash("Global expiry date is required.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        datetime.strptime(global_expiry_date, "%Y-%m-%d")
    except ValueError:
        flash("Global expiry date must be in YYYY-MM-DD format.", "error")
        return redirect(url_for("admin_dashboard"))

    update_app_settings(max_config_gb=max_config_gb, global_expiry_date=global_expiry_date)
    flash("Service policy updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/invite-codes/create", methods=["POST"])
@login_required
@admin_required
def admin_create_invite_code():
    code_length_raw = request.form.get("code_length", "10").strip()
    if not code_length_raw.isdigit():
        flash("Invalid invite code length.", "error")
        return redirect(url_for("admin_dashboard"))

    code_length = max(6, min(int(code_length_raw), 32))
    alphabet = string.ascii_uppercase + string.digits
    code = "".join(random.choices(alphabet, k=code_length))

    try:
        create_invite_code(code, current_user_id())
        flash(f"Invite code created: {code}", "success")
    except sqlite3.IntegrityError:
        flash("Generated a duplicate invite code. Try again.", "error")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/plans", methods=["POST"])
@login_required
@admin_required
def admin_save_plan():
    name = request.form.get("name", "").strip()
    gb_raw = request.form.get("gb", "").strip()
    price_raw = request.form.get("price", "").strip()
    plan_key = request.form.get("plan_key", "").strip() or None
    is_active = request.form.get("is_active", "on") in ("on", "1", "true", "True")
    sort_order_raw = request.form.get("sort_order", "").strip()

    if not name or not gb_raw or not price_raw:
        flash("Name, GB and price are required for a plan.", "error")
        return redirect(url_for("admin_dashboard"))

    try:
        gb = float(gb_raw)
        price = float(price_raw)
    except ValueError:
        flash("GB and price must be numeric.", "error")
        return redirect(url_for("admin_dashboard"))

    sort_order = int(sort_order_raw) if sort_order_raw.isdigit() else None
    plan_key = save_vpn_plan(name, gb, price, plan_key=plan_key, is_active=is_active, sort_order=sort_order)
    flash(f"Plan {plan_key} saved.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/plans/<plan_key>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_plan(plan_key):
    deleted = delete_vpn_plan(plan_key)
    if deleted:
        flash(f"Plan {plan_key} deleted.", "success")
    else:
        flash(f"Plan {plan_key} not found.", "error")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/pending")
@login_required
@admin_required
def admin_pending():
    pending = get_pending_payments()
    return render_template("admin_pending.html", pending=pending)


@app.route("/admin/pending/<int:payment_id>/approve", methods=["POST"])
@login_required
@admin_required
def approve_payment_web(payment_id):
    payment_record = get_payment_record(payment_id)
    if not payment_record or payment_record["status"] != "pending":
        flash("Payment not found or already processed.", "error")
        return redirect(url_for("admin_pending"))

    user_id = payment_record["user_id"]
    plan_name = payment_record["plan"]
    username = payment_record["username"]
    payment_type = payment_record["payment_type"] or "service"
    payment_amount = float(payment_record["amount"] or 0)
    plan_gb = payment_amount if payment_amount > 0 else _parse_plan_gb(plan_name)
    policy = get_service_policy()

    # Normalize and log values for debugging approval issues
    # try:
    #     plan_gb = float(plan_gb)
    # except Exception:
    #     logger.warning("Could not coerce plan_gb to float: %r", plan_gb)
    #     try:
    #         plan_gb = float(int(plan_gb))
    #     except Exception:
    #         plan_gb = 0.0

    logger.info(
        "approve_payment_web: payment_id=%s plan_name=%r plan_gb=%s policy_max=%s",
        payment_id,
        plan_name,
        plan_gb,
        policy.get("max_config_gb"),
    )

    if payment_type == "wallet_topup":
        success, new_balance = adjust_wallet_balance(user_id, payment_amount)
        if not success:
            flash("Unable to charge wallet.", "error")
            return redirect(url_for("admin_pending"))

        update_payment_status(payment_id, "approved")
        flash(
            f"Wallet top-up approved for user {user_id}. New balance: {new_balance:g}",
            "success",
        )
        return redirect(url_for("admin_pending"))

    is_extension = payment_type == "extension"
    extension_email = payment_record["target_email"]
    extension_client_id = payment_record["target_client_id"]

    try:
        if is_extension and (not extension_email or not extension_client_id):
            raise RuntimeError("Stored extension details are incomplete")

        if is_extension:
            status = get_client_status(extension_email)
            if not status:
                raise RuntimeError("Could not find client information")

            if policy['max_config_gb'] > 0 and status['total_gb'] + plan_gb > policy['max_config_gb']:
                raise RuntimeError(f"Extension exceeds the configured limit of {policy['max_config_gb']} GB")

            success, error_msg = extend_client(extension_email, extension_client_id, plan_gb, policy['global_expiry_time_ms'])
            if not success:
                raise RuntimeError(error_msg or "Failed to extend client")

            update_config_total_gb(extension_email, user_id, plan_gb)
            update_payment_status(payment_id, "approved")
            flash(f"Extension approved for {extension_email}.", "success")
        else:
            if policy['max_config_gb'] > 0 and plan_gb > policy['max_config_gb']:
                raise RuntimeError(f"Plan exceeds the configured limit of {policy['max_config_gb']} GB")

            suffix = random_suffix()
            user_identifier = username if username else str(user_id)
            email = f"{user_identifier}_{suffix}@vpn"
            if len(email) > 50:
                email = f"u{user_id}_{suffix}@vpn"

            total_bytes = int(round(plan_gb * (1024 ** 3)))
            expiry_time = policy['global_expiry_time_ms']

            client_id, error = create_client(email, total_bytes, expiry_time)
            if error:
                raise RuntimeError(error)

            save_new_config(user_id, email, client_id, plan_gb)
            referral_applied, referrer_user_id, commission_amount = credit_referral_bonus_if_first_service_purchase(user_id, payment_amount)
            update_payment_status(payment_id, "approved")
            flash(f"Payment #{payment_id} approved and config created.", "success")

            if referral_applied and referrer_user_id:
                flash(
                    f"Referral bonus {commission_amount:g} credited to user {referrer_user_id}.",
                    "success",
                )

    except Exception as exc:
        logger.exception("Error approving payment")
        flash(f"Error approving payment: {exc}", "error")

    return redirect(url_for("admin_pending"))


@app.route("/admin/pending/<int:payment_id>/reject", methods=["POST"])
@login_required
@admin_required
def reject_payment_web(payment_id):
    payment_record = get_payment_record(payment_id)
    if not payment_record or payment_record["status"] != "pending":
        flash("Payment not found or already processed.", "error")
        return redirect(url_for("admin_pending"))

    update_payment_status(payment_id, "rejected")
    flash(f"Payment #{payment_id} rejected.", "success")
    return redirect(url_for("admin_pending"))


@app.route("/admin/users")
@login_required
@admin_required
def admin_users():
    conn = _db_connection()
    users = conn.execute(
        """
        SELECT u.user_id, u.first_name, u.username, COUNT(c.config_id) AS config_count, MAX(c.created_at) AS last_created
        FROM users u
        LEFT JOIN configs c ON u.user_id = c.user_id
        GROUP BY u.user_id
        ORDER BY last_created DESC
        LIMIT 100
        """
    ).fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)


@app.route("/admin/tickets")
@login_required
@admin_required
def admin_tickets():
    conn = _db_connection()
    tickets = conn.execute(
        """
        SELECT t.ticket_id, t.subject, t.status, u.first_name, u.username
        FROM tickets t
        JOIN users u ON t.user_id = u.user_id
        ORDER BY
            CASE
                WHEN t.status = 'open' THEN 1
                WHEN t.status = 'answered' THEN 2
                ELSE 3
            END,
            t.created_at DESC
        LIMIT 100
        """
    ).fetchall()
    conn.close()
    return render_template("admin_tickets.html", tickets=tickets)


@app.route("/admin/clients")
@login_required
@admin_required
def admin_clients():
    xui_clients = get_all_clients() or []
    db_clients = get_all_db_configs() or []

    merged = {}
    for client in xui_clients:
        cid = client.get("id")
        if not cid:
            continue
        merged[cid] = {
            "client_id": cid,
            "email": client.get("email"),
            "remaining_gb": client.get("remaining_gb", "-"),
            "total_gb": client.get("total_gb", "-"),
            "expiry_date": client.get("expiry_date", "Unknown"),
            "remaining_time_display": client.get("remaining_time_display", "Unknown"),
            "is_active": client.get("is_active", client.get("enable", False)),
            "source": "xui",
        }

    for db_client in db_clients:
        cid = db_client.get("client_id")
        if not cid:
            continue
        if cid in merged:
            merged[cid].update(
                {
                    "user_id": db_client.get("user_id"),
                    "username": db_client.get("username"),
                    "first_name": db_client.get("first_name"),
                    "source": "both",
                }
            )
        else:
            merged[cid] = {
                "client_id": cid,
                "email": db_client.get("email"),
                "remaining_gb": "-",
                "total_gb": db_client.get("total_gb"),
                "expiry_date": "Unknown",
                "remaining_time_display": "Unknown",
                "is_active": bool(db_client.get("is_active")),
                "user_id": db_client.get("user_id"),
                "username": db_client.get("username"),
                "first_name": db_client.get("first_name"),
                "source": "db",
            }

    clients = sorted(list(merged.values()), key=lambda item: item.get("email") or "")
    return render_template("admin_clients.html", clients=clients)


@app.route("/admin/clients/<client_id>/delete", methods=["POST"])
@login_required
@admin_required
def admin_delete_client(client_id):
    xui_ok, xui_error = delete_client(client_id)
    db_ok = delete_config_by_client_id(client_id)

    if xui_ok:
        message = f"Client {client_id[:8]}... deleted from XUI"
        if db_ok:
            message += " and database."
        else:
            message += ", but database cleanup failed."
        flash(message, "success")
    else:
        flash(f"Failed to delete from XUI: {xui_error}", "error")

    return redirect(url_for("admin_clients"))


@app.route("/admin/extend-all", methods=["POST"])
@login_required
@admin_required
def admin_extend_all():
    days_raw = request.form.get("days", "")
    if not days_raw.isdigit():
        flash("Invalid day count.", "error")
        return redirect(url_for("admin_dashboard"))

    days = int(days_raw)
    configs = get_all_configs_with_users()
    updated = 0

    for conf in configs:
        email = conf["email"]
        client_id = conf["client_id"]
        user_id = conf["user_id"]
        success, _error = extend_client(email, client_id, 0, timedelta(days=days))
        db_ok = update_config_total_gb(email, user_id, 0)
        if success and db_ok:
            updated += 1

    flash(f"Extended {updated} clients by {days} days.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/toggle-buy", methods=["POST"])
@login_required
@admin_required
def admin_toggle_buy():
    enabled = request.form.get("enabled", "no") == "yes"
    config.ALLOW_BUY = enabled
    flash(f"Buying is now {'enabled' if enabled else 'disabled' }.", "success")
    return redirect(url_for("admin_dashboard"))


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5500, debug=True)
