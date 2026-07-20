# ============================================
# TELEGRAM TEMP MAIL BOT (VERSIÓN INLINE & LINKS)
# ============================================

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import requests
import sqlite3
import hashlib
import logging
import random
import string
import time
import threading
import re

# ============================================
# TOKEN Y CONFIGURACIÓN
# ============================================

TOKEN = "8944900785:AAF81FVJmzKnjSMHhsHZapPbxMFKZ1zaMuY"
ADMIN_ID = 8768008680  # Tu ID de administrador

bot = telebot.TeleBot(TOKEN)

DATABASE = "bot.db"
PROVIDERS = ["https://api.mail.tm", "https://api.mail.gw"]

MAX_EMAILS_PER_HOUR = 3
SESSION_TIMEOUT = 3600
TEMP_DATA_TIMEOUT = 600

# ============================================
# LOGS
# ============================================

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ============================================
# BASE DE DATOS
# ============================================

conn = sqlite3.connect(DATABASE, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users(
    telegram_id INTEGER PRIMARY KEY,
    username TEXT UNIQUE,
    password_hash TEXT,
    created_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS emails(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER,
    email TEXT,
    password TEXT,
    token TEXT,
    provider TEXT,
    created_at INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS rate_limits(telegram_id INTEGER, timestamp INTEGER)
""")
cursor.execute("""
CREATE TABLE IF NOT EXISTS login_attempts(telegram_id INTEGER, timestamp INTEGER)
""")
conn.commit()

# ============================================
# MEMORIA Y GLOBALES
# ============================================

user_data = {}
sessions = {}

# ============================================
# FUNCIONES AUXILIARES Y ESTÉTICA
# ============================================

BANNER = "╭━━━━━━━━━━━━━━━╮\n   🤖 <b>TEMP MAIL PRO</b>\n╰━━━━━━━━━━━━━━━╯\n\n"

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def sanitize_username(username):
    return re.match(r"^[a-zA-Z0-9_-]{3,20}$", username)

def sanitize_password(password):
    return len(password) >= 6

def create_random_string(length=10):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))

def is_logged(user_id):
    if user_id not in sessions: return False
    if time.time() - sessions[user_id] > SESSION_TIMEOUT:
        del sessions[user_id]
        return False
    return True

def extract_links(text):
    """Extrae enlaces de un texto para convertirlos en botones"""
    if not text: return []
    urls = re.findall(r'https?://[^\s<>\"\'()]+', text)
    return list(dict.fromkeys(urls))

# ============================================
# LÍMITES
# ============================================

def can_create_email(user_id):
    one_hour = int(time.time()) - 3600
    cursor.execute("DELETE FROM rate_limits WHERE timestamp < ?", (one_hour,))
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM rate_limits WHERE telegram_id = ?", (user_id,))
    return cursor.fetchone()[0] < MAX_EMAILS_PER_HOUR

def add_rate_limit(user_id):
    cursor.execute("INSERT INTO rate_limits VALUES (?,?)", (user_id, int(time.time())))
    conn.commit()

# ============================================
# API PROVEEDORES
# ============================================

def get_domain(provider):
    try:
        r = requests.get(f"{provider}/domains", timeout=10).json()
        return r['hydra:member'][0]['domain']
    except: return None

def create_account(provider, address, password):
    try:
        return requests.post(f"{provider}/accounts", json={"address": address, "password": password}, timeout=15).json()
    except: return None

def get_token(provider, address, password):
    try:
        return requests.post(f"{provider}/token", json={"address": address, "password": password}, timeout=15).json()
    except: return None

def get_messages(provider, token):
    try:
        return requests.get(f"{provider}/messages", headers={"Authorization": f"Bearer {token}"}, timeout=15).json()
    except: return None

def get_message_detail(provider, token, msg_id):
    try:
        return requests.get(f"{provider}/messages/{msg_id}", headers={"Authorization": f"Bearer {token}"}, timeout=15).json()
    except: return None

# ============================================
# MENÚ PRINCIPAL INTERACTIVO
# ============================================

def send_main_menu(chat_id, user_id, message_id=None):
    markup = InlineKeyboardMarkup(row_width=2)
    
    if is_logged(user_id):
        text = BANNER + "✅ <b>Sesión Iniciada</b>\n\nSelecciona una opción para gestionar tus correos:"
        markup.add(
            InlineKeyboardButton("➕ Crear Correo", callback_data="menu_email"),
            InlineKeyboardButton("📬 Mi Bandeja", callback_data="menu_emails")
        )
        markup.add(InlineKeyboardButton("🚪 Cerrar Sesión", callback_data="menu_logout"))
    else:
        text = BANNER + "🔒 <b>No has iniciado sesión</b>\n\nRegístrate o inicia sesión para generar correos temporales."
        markup.add(
            InlineKeyboardButton("📝 Registrarse", callback_data="menu_register"),
            InlineKeyboardButton("🔑 Iniciar Sesión", callback_data="menu_login")
        )
    
    # Botones que siempre aparecen (Canal de Soporte actualizado)
    extra_btns = [InlineKeyboardButton("🌐 Canal de Soporte", url="https://t.me/bienperu")]
    if user_id == ADMIN_ID:
        extra_btns.append(InlineKeyboardButton("📊 Estadísticas", callback_data="menu_stats"))
    markup.add(*extra_btns)

    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
    else:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(commands=['start', 'menu'])
def start(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    send_main_menu(message.chat.id, message.from_user.id)

# ============================================
# ENRUTADOR DE BOTONES DEL MENÚ
# ============================================

@bot.callback_query_handler(func=lambda c: c.data.startswith("menu_"))
def menu_callbacks(call):
    bot.clear_step_handler_by_chat_id(call.message.chat.id)
    cmd = call.data.split("_")[1]
    cid = call.message.chat.id
    uid = call.from_user.id
    mid = call.message.message_id

    if cmd == "main":
        send_main_menu(cid, uid, mid)
    elif cmd == "logout":
        if uid in sessions: del sessions[uid]
        send_main_menu(cid, uid, mid)
    elif cmd == "register":
        msg = bot.edit_message_text("👤 <b>Ingresa un nombre de usuario nuevo:</b>", cid, mid, parse_mode="HTML")
        bot.register_next_step_handler(msg, process_reg_user)
    elif cmd == "login":
        msg = bot.edit_message_text("👤 <b>Ingresa tu nombre de usuario:</b>", cid, mid, parse_mode="HTML")
        bot.register_next_step_handler(msg, process_log_user)
    elif cmd == "email":
        show_email_creation_menu(cid, mid)
    elif cmd == "emails":
        show_emails_list(cid, uid, mid)
    elif cmd == "stats":
        show_stats(cid, uid, mid)

# ============================================
# FLUJO DE REGISTRO
# ============================================

def process_reg_user(message):
    username = message.text.strip()
    if not sanitize_username(username):
        bot.send_message(message.chat.id, "❌ <b>Inválido.</b> Usa 3-20 caracteres (letras, números). /start", parse_mode="HTML")
        return
    user_data[message.from_user.id] = {"username": username}
    msg = bot.send_message(message.chat.id, "🔑 <b>Ingresa tu contraseña:</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_reg_pass)

def process_reg_pass(message):
    password = message.text.strip()
    if not sanitize_password(password):
        bot.send_message(message.chat.id, "❌ <b>Débil.</b> Mínimo 6 caracteres. /start", parse_mode="HTML")
        return
    user_data[message.from_user.id]["password"] = password
    msg = bot.send_message(message.chat.id, "🔁 <b>Confirma tu contraseña:</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_reg_confirm)

def process_reg_confirm(message):
    uid = message.from_user.id
    if message.text.strip() != user_data.get(uid, {}).get("password", ""):
        bot.send_message(message.chat.id, "❌ <b>No coinciden.</b> /start para reintentar.", parse_mode="HTML")
        return

    try:
        cursor.execute("INSERT INTO users VALUES (?,?,?,?)", (uid, user_data[uid]["username"], hash_password(message.text.strip()), int(time.time())))
        conn.commit()
        bot.send_message(message.chat.id, "✅ <b>Cuenta creada.</b> Presiona /start para iniciar sesión.", parse_mode="HTML")
    except:
        bot.send_message(message.chat.id, "❌ <b>Usuario ya existente.</b> /start", parse_mode="HTML")

# ============================================
# FLUJO DE LOGIN
# ============================================

def process_log_user(message):
    user_data[message.from_user.id] = {"username": message.text.strip()}
    msg = bot.send_message(message.chat.id, "🔑 <b>Ingresa tu contraseña:</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_log_pass)

def process_log_pass(message):
    uid = message.from_user.id
    user = user_data.get(uid, {}).get("username", "")
    cursor.execute("SELECT * FROM users WHERE telegram_id=? AND username=? AND password_hash=?", (uid, user, hash_password(message.text.strip())))
    if cursor.fetchone():
        sessions[uid] = time.time()
        bot.send_message(message.chat.id, "✅ <b>¡Login Exitoso!</b> Toca /start para abrir el menú.", parse_mode="HTML")
    else:
        bot.send_message(message.chat.id, "❌ <b>Credenciales incorrectas.</b> /start", parse_mode="HTML")

# ============================================
# CREACIÓN DE CORREO
# ============================================

def show_email_creation_menu(cid, mid):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⏳ Temporal", callback_data="create_temp"),
        InlineKeyboardButton("💎 Permanente", callback_data="create_perm")
    )
    markup.add(InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_main"))
    
    text = "⚙️ <b>CREAR CORREO</b>\n\nSelecciona el tipo de cuenta a generar:"
    bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data.startswith("create_"))
def process_creation_choice(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    if not can_create_email(uid):
        bot.answer_callback_query(call.id, "⏳ Límite alcanzado. Espera un rato.", show_alert=True)
        return

    if call.data == "create_temp":
        execute_email_creation(cid, uid, is_custom=False)
    elif call.data == "create_perm":
        msg = bot.edit_message_text("✍️ <b>Escribe el nombre del correo</b> (sin @):", cid, call.message.message_id, parse_mode="HTML")
        bot.register_next_step_handler(msg, lambda m: execute_email_creation(cid, uid, True, m.text.strip().lower()))

def execute_email_creation(cid, uid, is_custom, custom_name=None):
    if is_custom and not custom_name.isalnum():
        bot.send_message(cid, "❌ <b>Nombre inválido.</b> /start", parse_mode="HTML")
        return
        
    bot.send_chat_action(cid, "typing")
    provider = random.choice(PROVIDERS)
    domain = get_domain(provider)
    if not domain:
        bot.send_message(cid, "⚠️ <b>Error en los servidores.</b> /start", parse_mode="HTML")
        return

    username = custom_name if is_custom else create_random_string(10)
    address = f"{username}@{domain}"
    password = create_random_string(12)
    
    acc = create_account(provider, address, password)
    if not acc or 'id' not in acc:
        bot.send_message(cid, "❌ <b>Error. (Nombre en uso o servidor caído)</b> /start", parse_mode="HTML")
        return

    token = get_token(provider, address, password).get("token", "")
    cursor.execute("INSERT INTO emails(telegram_id, email, password, token, provider, created_at) VALUES (?,?,?,?,?,?)", 
                   (uid, address, password, token, provider, int(time.time())))
    conn.commit()
    add_rate_limit(uid)

    text = f"✅ <b>CORREO CREADO</b>\n\n📧 <code>{address}</code>\n🔑 <code>{password}</code>"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📬 Ir a mi Bandeja", callback_data="menu_emails"))
    bot.send_message(cid, text, reply_markup=markup, parse_mode="HTML")

# ============================================
# BANDEJA DE ENTRADA Y LECTURA
# ============================================

def show_emails_list(cid, uid, mid):
    cursor.execute("SELECT id, email FROM emails WHERE telegram_id = ? ORDER BY id DESC LIMIT 10", (uid,))
    rows = cursor.fetchall()

    markup = InlineKeyboardMarkup(row_width=1)
    if not rows:
        text = "📭 <b>No tienes correos creados.</b>"
    else:
        text = "📬 <b>TUS CORREOS:</b>\n<i>Selecciona uno para abrirlo</i>"
        for row in rows:
            markup.add(InlineKeyboardButton(f"📧 {row[1]}", callback_data=f"inbox_{row[0]}"))
            
    markup.add(InlineKeyboardButton("🔙 Volver al Menú", callback_data="menu_main"))
    bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data.startswith("inbox_"))
def view_inbox(call):
    email_id = call.data.split("_")[1]
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    cursor.execute("SELECT email, token, provider FROM emails WHERE id=? AND telegram_id=?", (email_id, uid))
    row = cursor.fetchone()
    if not row: return

    email, token, provider = row
    data = get_messages(provider, token)
    
    markup = InlineKeyboardMarkup(row_width=1)
    
    if not data or not data.get("hydra:member"):
        text = f"📭 <b>BANDEJA VACÍA</b>\n\n<code>{email}</code>\n<i>Aún no recibes mensajes aquí.</i>"
    else:
        text = f"📨 <b>BANDEJA:</b>\n<code>{email}</code>\n\n<i>Mensajes recibidos:</i>"
        for m in data["hydra:member"][:5]:
            subject = m.get("subject", "Sin Asunto")
            msg_id = m.get("id")
            markup.add(InlineKeyboardButton(f"📩 {subject[:30]}", callback_data=f"read_{email_id}_{msg_id}"))

    markup.add(
        InlineKeyboardButton("🔄 Actualizar", callback_data=f"inbox_{email_id}"),
        InlineKeyboardButton("🔙 Lista de Correos", callback_data="menu_emails")
    )
    bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="HTML")

@bot.callback_query_handler(func=lambda c: c.data.startswith("read_"))
def read_message(call):
    _, email_id, msg_id = call.data.split("_", 2)
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id

    cursor.execute("SELECT token, provider FROM emails WHERE id=? AND telegram_id=?", (email_id, uid))
    row = cursor.fetchone()
    if not row: return
    token, provider = row

    msg_data = get_message_detail(provider, token, msg_id)
    if not msg_data:
        bot.answer_callback_query(call.id, "⚠️ Error al abrir el mensaje.", show_alert=True)
        return

    subject = msg_data.get("subject", "Sin Asunto")
    sender = msg_data.get("from", {}).get("address", "Desconocido")
    content = msg_data.get("text", "El mensaje no tiene formato de texto plano.")
    
    # 🔥 Extracción e Inyección limpia de Enlaces 🔥
    links = extract_links(content)
    
    # Limpiamos los links del texto plano para que el contenido se vea estético
    clean_content = content
    for link in links:
        clean_content = clean_content.replace(link, "[Enlace Ocultado]")

    safe_content = clean_content[:800] + ("\n...[Cortado]" if len(clean_content) > 800 else "")
    
    text = (
        f"📖 <b>MENSAJE ABIERTO</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>De:</b> {sender}\n"
        f"📝 <b>Asunto:</b> {subject}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<code>{safe_content}</code>"
    )

    markup = InlineKeyboardMarkup(row_width=1)
    
    # 🌟 Un único botón con texto predeterminado para el primer enlace encontrado 🌟
    if links:
        markup.add(InlineKeyboardButton("🔗 Abrir Enlace de Verificación", url=links[0]))
        
    markup.row(
        InlineKeyboardButton("🔙 Volver a Bandeja", callback_data=f"inbox_{email_id}"),
        InlineKeyboardButton("🏠 Inicio", callback_data="menu_main")
    )
    
    bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)

# ============================================
# ESTADÍSTICAS
# ============================================

def show_stats(cid, uid, mid):
    if uid != ADMIN_ID: return
    cursor.execute("SELECT COUNT(*) FROM users")
    users = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM emails")
    emails = cursor.fetchone()[0]

    text = f"📊 <b>ESTADÍSTICAS</b>\n\n👤 <b>Usuarios:</b> {users}\n📧 <b>Correos:</b> {emails}\n🟢 <b>API Activas:</b> {len(PROVIDERS)}"
    markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Volver", callback_data="menu_main"))
    bot.edit_message_text(text, cid, mid, reply_markup=markup, parse_mode="HTML")

# ============================================
# INICIO Y EJECUCIÓN
# ============================================

if __name__ == "__main__":
    print("🤖 BOT INICIADO Y FUNCIONANDO CON BOTONES INLINE")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logging.error(f"Caída del Bot: {e}")
            time.sleep(5)
