import os
import time
import threading
import importlib.util
from pathlib import Path
from typing import Dict

from flask import Flask
import telebot
from telebot import types

# ============================================================
# ВСТАВЬ СВОИ ДАННЫЕ СЮДА
# ============================================================
HOST_BOT_TOKEN = "8867884169:AAG-UkjVW4SThLxFcL7pzt6NweKrz_1RQFI"
# ============================================================

BOTS_DIR = Path("hosted_bots")
BOTS_DIR.mkdir(exist_ok=True)

running_bots: Dict[int, dict] = {}

# Временное хранилище токенов (ждём файл)
pending_tokens: Dict[int, str] = {}

bot = telebot.TeleBot(HOST_BOT_TOKEN, threaded=False)

# ============================================================
# ПРОВЕРКА ТОКЕНА
# ============================================================

def check_token(token: str) -> dict:
    result = {
        "valid": False,
        "bot_name": None,
        "bot_username": None,
        "bot_id": None,
        "error": None
    }

    if not token or ":" not in token:
        result["error"] = "Неверный формат токена"
        return result

    try:
        test_bot = telebot.TeleBot(token)
        bot_info = test_bot.get_me()
        
        result["valid"] = True
        result["bot_name"] = bot_info.first_name
        result["bot_username"] = bot_info.username
        result["bot_id"] = bot_info.id
        
    except Exception as e:
        error_str = str(e)
        if "Unauthorized" in error_str or "401" in error_str:
            result["error"] = "Токен недействителен или бот удалён"
        else:
            result["error"] = f"Ошибка проверки: {error_str[:100]}"

    return result

# ============================================================
# ЗАПУСК БОТА
# ============================================================

def run_user_bot(user_id: int, token: str, code: str) -> dict:
    stop_user_bot(user_id)

    bot_file = BOTS_DIR / f"bot_{user_id}.py"
    bot_file.write_text(code, encoding="utf-8")

    running_bots[user_id] = {
        "token": token,
        "bot_file": str(bot_file),
        "started_at": time.time(),
        "status": "starting",
        "thread": None
    }

    def bot_worker():
        user_bot = telebot.TeleBot(token)
        
        try:
            spec = importlib.util.spec_from_file_location(
                f"user_bot_{user_id}", bot_file
            )
            module = importlib.util.module_from_spec(spec)
            
            module.bot = user_bot
            module.types = types
            
            spec.loader.exec_module(module)

            bot_info = user_bot.get_me()
            running_bots[user_id]["status"] = "running"
            running_bots[user_id]["bot_name"] = bot_info.first_name
            running_bots[user_id]["bot_username"] = bot_info.username

            print(f"Бот @{bot_info.username} запущен")

            user_bot.infinity_polling(timeout=10, long_polling_timeout=5)

        except Exception as e:
            running_bots[user_id]["status"] = "crashed"
            running_bots[user_id]["error"] = str(e)[:200]
            print(f"Бот упал: {e}")

    thread = threading.Thread(target=bot_worker, daemon=True)
    thread.start()
    running_bots[user_id]["thread"] = thread

    return {"success": True, "message": "Бот запущен"}

def stop_user_bot(user_id: int) -> bool:
    if user_id not in running_bots:
        return False

    bot_data = running_bots[user_id]
    bot_data["status"] = "stopped"

    try:
        temp_bot = telebot.TeleBot(bot_data["token"])
        temp_bot.stop_polling()
    except:
        pass

    del running_bots[user_id]

    session = BOTS_DIR / f"bot_{user_id}.session"
    if session.exists():
        session.unlink()

    return True

# ============================================================
# КОМАНДЫ
# ============================================================

@bot.message_handler(commands=["start"])
def start_command(msg: types.Message):
    bot.reply_to(msg,
        "🤖 **Бот-хостер**\n\n"
        "📋 **Команды:**\n"
        "/new — загрузить нового бота\n"
        "/stop — остановить бота\n"
        "/status — статус бота\n\n"
        "📤 **Как загрузить:**\n"
        "1. /new + токен\n"
        "2. Отправить .py файл с кодом",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["new"])
def new_bot_command(msg: types.Message):
    """Принимает токен и ждёт файл"""
    user_id = msg.from_user.id
    
    # Извлекаем токен
    token = msg.text.replace("/new", "").strip()
    
    if not token:
        bot.reply_to(msg, "❌ Отправь: /new ТВОЙ_ТОКЕН")
        return

    # Проверяем токен
    status_msg = bot.reply_to(msg, "🔍 Проверяю токен...")
    check = check_token(token)

    if not check["valid"]:
        bot.edit_message_text(f"❌ {check['error']}", msg.chat.id, status_msg.message_id)
        return

    # Сохраняем токен и ждём файл
    pending_tokens[user_id] = token
    
    bot.edit_message_text(
        f"✅ Токен @{check['bot_username']} принят!\n\n"
        f"📤 Теперь **отправь .py файл** с кодом бота.\n\n"
        f"Пример кода:\n"
        f"```python\n"
        f"import telebot\n"
        f"from telebot import types\n\n"
        f"@bot.message_handler(commands=['start'])\n"
        f"def start(msg):\n"
        f"    bot.reply_to(msg, 'Привет!')\n\n"
        f"bot.infinity_polling()\n"
        f"```\n\n"
        f"⚠️ Отправь именно файл .py, не текст!",
        msg.chat.id,
        status_msg.message_id,
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=["document"])
def handle_file(msg: types.Message):
    """Принимает .py файл и запускает бота"""
    user_id = msg.from_user.id

    # Проверяем, ждали ли файл
    if user_id not in pending_tokens:
        bot.reply_to(msg, "❌ Сначала отправь /new ТВОЙ_ТОКЕН")
        return

    # Проверяем что это .py файл
    file_name = msg.document.file_name
    if not file_name.endswith(".py"):
        bot.reply_to(msg, "❌ Отправь файл с расширением .py")
        return

    token = pending_tokens.pop(user_id)
    status_msg = bot.reply_to(msg, "📥 Скачиваю файл...")

    try:
        # Скачиваем файл
        file_info = bot.get_file(msg.document.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        code = downloaded_file.decode("utf-8")

        # Проверка на пустой код
        if not code.strip():
            bot.edit_message_text("❌ Файл пустой!", msg.chat.id, status_msg.message_id)
            return

        # Проверка на опасный код
        dangerous = ["os.system", "subprocess", "eval(", "exec(", "__import__", 
                     "rm -rf", "shutil.rmtree", "os.remove"]
        for danger in dangerous:
            if danger in code:
                bot.edit_message_text(
                    f"❌ Обнаружен опасный код: `{danger}`",
                    msg.chat.id,
                    status_msg.message_id,
                    parse_mode="Markdown"
                )
                return

        # Добавляем импорты если нужны
        if "import telebot" not in code and "from telebot" not in code:
            code = "import telebot\nfrom telebot import types\n\n" + code

        if "bot.infinity_polling" not in code and "bot.polling" not in code:
            code += "\n\nbot.infinity_polling()"

        # Запускаем
        bot.edit_message_text("🚀 Запускаю бота...", msg.chat.id, status_msg.message_id)

        # Получаем инфо о боте
        check = check_token(token)
        bot_name = check.get("bot_username", "?")

        result = run_user_bot(user_id, token, code)

        if result["success"]:
            bot.edit_message_text(
                f"✅ **Бот запущен!**\n\n"
                f"👤 @{bot_name}\n"
                f"📄 Файл: `{file_name}`\n\n"
                f"Команды:\n"
                f"/stop — остановить\n"
                f"/status — статус",
                msg.chat.id,
                status_msg.message_id,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text(
                f"❌ Ошибка запуска: {result.get('error', 'Неизвестно')}",
                msg.chat.id,
                status_msg.message_id
            )

    except Exception as e:
        bot.edit_message_text(
            f"❌ Ошибка: {str(e)[:200]}",
            msg.chat.id,
            status_msg.message_id
        )

@bot.message_handler(commands=["stop"])
def stop_command(msg: types.Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        bot.reply_to(msg, "❌ Нет запущенных ботов")
        return

    stop_user_bot(user_id)
    bot.reply_to(msg, "✅ Бот остановлен")

@bot.message_handler(commands=["status"])
def status_command(msg: types.Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        bot.reply_to(msg, "❌ Нет запущенных ботов")
        return

    bot_data = running_bots[user_id]
    uptime = time.time() - bot_data.get("started_at", 0)
    hours, rem = divmod(int(uptime), 3600)
    minutes, seconds = divmod(rem, 60)

    bot.reply_to(msg,
        f"📊 **Статус**\n\n"
        f"👤 Бот: @{bot_data.get('bot_username', '?')}\n"
        f"📌 Статус: `{bot_data['status']}`\n"
        f"⏱ Аптайм: {hours}ч {minutes}м {seconds}с\n"
        f"📄 Файл: `{Path(bot_data.get('bot_file', '?')).name}`",
        parse_mode="Markdown"
    )

# ============================================================
# FLASK ДЛЯ RENDER
# ============================================================

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 40)
    print("Бот-Хостер v4.0 (файлы)")
    print("=" * 40)

    threading.Thread(target=run_flask, daemon=True).start()

    print("Запуск...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)        "bot_id": None,
        "error": None
    }

    if not token or ":" not in token:
        result["error"] = "Неверный формат токена"
        return result

    try:
        test_bot = telebot.TeleBot(token)
        bot_info = test_bot.get_me()
        
        result["valid"] = True
        result["bot_name"] = bot_info.first_name
        result["bot_username"] = bot_info.username
        result["bot_id"] = bot_info.id
        
    except Exception as e:
        error_str = str(e)
        if "Unauthorized" in error_str or "401" in error_str:
            result["error"] = "Токен недействителен или бот удалён"
        else:
            result["error"] = f"Ошибка проверки: {error_str[:100]}"

    return result

# ============================================================
# ЗАПУСК ПОЛЬЗОВАТЕЛЬСКОГО БОТА
# ============================================================

def load_bot_code(user_id: int, code: str) -> Path:
    bot_file = BOTS_DIR / f"bot_{user_id}.py"
    bot_file.write_text(code, encoding="utf-8")
    return bot_file

def run_user_bot(user_id: int, token: str, code: str) -> dict:
    """Запускает пользовательского бота"""
    stop_user_bot(user_id)

    bot_file = load_bot_code(user_id, code)

    running_bots[user_id] = {
        "token": token,
        "bot_file": str(bot_file),
        "started_at": time.time(),
        "status": "starting",
        "thread": None
    }

    def bot_worker():
        user_bot = telebot.TeleBot(token)
        
        try:
            # Загружаем пользовательский код
            spec = importlib.util.spec_from_file_location(
                f"user_bot_{user_id}", bot_file
            )
            module = importlib.util.module_from_spec(spec)
            
            # Передаём bot в модуль пользователя
            module.bot = user_bot
            module.types = types
            
            spec.loader.exec_module(module)

            bot_info = user_bot.get_me()
            running_bots[user_id]["status"] = "running"
            running_bots[user_id]["bot_name"] = bot_info.first_name
            running_bots[user_id]["bot_username"] = bot_info.username

            print(f"Бот @{bot_info.username} запущен")

            # Запускаем polling
            user_bot.infinity_polling(timeout=10, long_polling_timeout=5)

        except Exception as e:
            running_bots[user_id]["status"] = "crashed"
            running_bots[user_id]["error"] = str(e)[:200]
            print(f"Бот упал: {e}")

    thread = threading.Thread(target=bot_worker, daemon=True)
    thread.start()
    running_bots[user_id]["thread"] = thread

    return {"success": True, "message": "Бот запущен"}

def stop_user_bot(user_id: int) -> bool:
    if user_id not in running_bots:
        return False

    bot_data = running_bots[user_id]
    bot_data["status"] = "stopped"

    # Останавливаем поток
    if bot_data.get("thread"):
        # Принудительно останавливаем через stop_polling
        try:
            temp_bot = telebot.TeleBot(bot_data["token"])
            temp_bot.stop_polling()
        except:
            pass

    del running_bots[user_id]

    # Удаляем файлы
    session = BOTS_DIR / f"bot_{user_id}.session"
    if session.exists():
        session.unlink()

    return True

# ============================================================
# КОМАНДЫ ХОСТ-БОТА
# ============================================================

@bot.message_handler(commands=["start"])
def start_command(msg: types.Message):
    bot.reply_to(msg, 
        "🤖 **Бот-хостер**\n\n"
        "/check токен — проверить токен\n"
        "/host — загрузить код бота\n"
        "/stop — остановить бота\n"
        "/status — статус бота",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["check"])
def check_command(msg: types.Message):
    token = msg.text.replace("/check", "").strip()
    
    if not token:
        bot.reply_to(msg, "Укажи токен: /check 123456:ABC-DEF")
        return

    status_msg = bot.reply_to(msg, "Проверяю...")
    result = check_token(token)

    if result["valid"]:
        text = f"✅ Токен валиден!\nБот: @{result['bot_username']}"
    else:
        text = f"❌ {result['error']}"

    bot.edit_message_text(text, msg.chat.id, status_msg.message_id)

@bot.message_handler(commands=["host"])
def host_command(msg: types.Message):
    bot.reply_to(msg,
        "📤 Отправь:\n\n"
        "/upload\nТОКЕН\n```python\nКОД\n```",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["upload"])
def upload_command(msg: types.Message):
    user_id = msg.from_user.id

    text = msg.text.replace("/upload", "", 1).strip()
    lines = text.split("\n")

    if len(lines) < 3:
        bot.reply_to(msg, "Неверный формат")
        return

    token = lines[0].strip()

    try:
        code_start = text.find("```python") + len("```python")
        code_end = text.find("```", code_start)
        if code_start < 10 or code_end < 0:
            raise ValueError("Код не найден")
        code = text[code_start:code_end].strip()
    except:
        bot.reply_to(msg, "Код должен быть в ```python ... ```")
        return

    status_msg = bot.reply_to(msg, "Проверяю...")
    check = check_token(token)

    if not check["valid"]:
        bot.edit_message_text(f"❌ {check['error']}", msg.chat.id, status_msg.message_id)
        return

    # Проверка на опасный код
    dangerous = ["os.system", "subprocess", "eval(", "exec(", "__import__"]
    for danger in dangerous:
        if danger in code:
            bot.edit_message_text(f"❌ Опасный код: {danger}", msg.chat.id, status_msg.message_id)
            return

    # Добавляем базовый код если нужен
    if "import telebot" not in code and "from telebot" not in code:
        code = "import telebot\nfrom telebot import types\n\n" + code

    if "bot.infinity_polling" not in code and "bot.polling" not in code:
        code += "\n\nbot.infinity_polling()"

    bot.edit_message_text(f"Запускаю @{check['bot_username']}...", msg.chat.id, status_msg.message_id)
    result = run_user_bot(user_id, token, code)

    if result["success"]:
        bot.edit_message_text(
            f"✅ Бот запущен!\n\n@{check['bot_username']}\n/stop /status",
            msg.chat.id, status_msg.message_id
        )

@bot.message_handler(commands=["stop"])
def stop_command(msg: types.Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        bot.reply_to(msg, "Нет запущенных ботов")
        return

    stop_user_bot(user_id)
    bot.reply_to(msg, "✅ Бот остановлен")

@bot.message_handler(commands=["status"])
def status_command(msg: types.Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        bot.reply_to(msg, "Нет запущенных ботов")
        return

    bot_data = running_bots[user_id]
    uptime = time.time() - bot_data.get("started_at", 0)
    hours, rem = divmod(int(uptime), 3600)
    minutes, seconds = divmod(rem, 60)

    bot.reply_to(msg,
        f"📊 Статус\n"
        f"Бот: @{bot_data.get('bot_username', '?')}\n"
        f"Статус: {bot_data['status']}\n"
        f"Аптайм: {hours}ч {minutes}м {seconds}с"
    )

# ============================================================
# FLASK ДЛЯ RENDER
# ============================================================

flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":
    print("=" * 40)
    print("Бот-Хостер v4.0 (файлы)")
    print("=" * 40)

    threading.Thread(target=run_flask, daemon=True).start()

    print("Запуск...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
