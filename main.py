import asyncio
import os
import sys
import time
import threading
from pathlib import Path
from typing import Dict, Optional

from flask import Flask
from pyrogram import Client, filters
from pyrogram.errors import AccessTokenInvalid, ApiIdInvalid, Unauthorized
from pyrogram.types import Message

# ============================================================
# ⚠️ ВСТАВЬ СВОИ ДАННЫЕ СЮДА ⚠️
# ============================================================
HOST_BOT_TOKEN = "8867884169:AAG-UkjVW4SThLxFcL7pzt6NweKrz_1RQFI"
API_ID = 34944645
API_HASH = "33ff1004a149671057f2e0fa8e6b4aaf"
# ============================================================

BOTS_DIR = Path("hosted_bots")
BOTS_DIR.mkdir(exist_ok=True)

running_bots: Dict[int, Dict] = {}

async def check_token(token: str) -> dict:
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
        test_client = Client(
            "token_check",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=token,
            in_memory=True
        )

        await test_client.start()
        bot_info = await test_client.get_me()

        result["valid"] = True
        result["bot_name"] = bot_info.first_name
        result["bot_username"] = bot_info.username
        result["bot_id"] = bot_info.id

        await test_client.stop()

    except (AccessTokenInvalid, Unauthorized):
        result["error"] = "Токен недействителен или бот удалён"
    except ApiIdInvalid:
        result["error"] = "Неверный API_ID/API_HASH"
    except Exception as e:
        result["error"] = f"Ошибка проверки: {str(e)[:100]}"

    session_file = Path("token_check.session")
    if session_file.exists():
        session_file.unlink()

    return result

def load_bot_code(user_id: int, code: str) -> Path:
    bot_file = BOTS_DIR / f"bot_{user_id}.py"
    bot_file.write_text(code, encoding="utf-8")
    return bot_file

async def run_user_bot(user_id: int, token: str, code: str) -> dict:
    await stop_user_bot(user_id)

    bot_file = load_bot_code(user_id, code)

    client = Client(
        f"bot_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=token,
        workdir=str(BOTS_DIR)
    )

    running_bots[user_id] = {
        "client": client,
        "token": token,
        "bot_file": str(bot_file),
        "started_at": time.time(),
        "status": "starting"
    }

    async def bot_worker():
        try:
            await client.start()
            bot_info = await client.get_me()
            running_bots[user_id]["status"] = "running"
            running_bots[user_id]["bot_name"] = bot_info.first_name
            running_bots[user_id]["bot_username"] = bot_info.username

            print(f"Бот @{bot_info.username} запущен")

            while user_id in running_bots:
                await asyncio.sleep(1)

        except Exception as e:
            running_bots[user_id]["status"] = "crashed"
            running_bots[user_id]["error"] = str(e)[:200]
            print(f"Бот упал: {e}")

        finally:
            try:
                await client.stop()
            except:
                pass
            if user_id in running_bots:
                running_bots[user_id]["status"] = "stopped"

    task = asyncio.create_task(bot_worker())
    running_bots[user_id]["task"] = task

    return {"success": True, "message": "Бот запущен"}

async def stop_user_bot(user_id: int) -> bool:
    if user_id not in running_bots:
        return False

    bot_data = running_bots[user_id]
    bot_data["status"] = "stopping"

    if "task" in bot_data:
        bot_data["task"].cancel()
        try:
            await bot_data["task"]
        except asyncio.CancelledError:
            pass

    try:
        await bot_data["client"].stop()
    except:
        pass

    del running_bots[user_id]

    session = BOTS_DIR / f"bot_{user_id}.session"
    if session.exists():
        session.unlink()

    return True

host_app = Client(
    "host_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=HOST_BOT_TOKEN
)

@host_app.on_message(filters.command("start"))
async def start_command(_, msg: Message):
    await msg.reply(
        "🤖 Бот-хостер\n\n"
        "/check токен — проверить токен\n"
        "/host — загрузить код бота\n"
        "/stop — остановить бота\n"
        "/status — статус бота"
    )

@host_app.on_message(filters.command("check"))
async def check_command(_, msg: Message):
    token = msg.text.replace("/check", "").strip()
    if not token:
        await msg.reply("Укажи токен: /check 123456:ABC-DEF")
        return

    status_msg = await msg.reply("Проверяю...")
    result = await check_token(token)

    if result["valid"]:
        text = f"Токен валиден! Бот: @{result['bot_username']}"
    else:
        text = f"Ошибка: {result['error']}"

    await status_msg.edit(text)

@host_app.on_message(filters.command("host"))
async def host_command(_, msg: Message):
    await msg.reply(
        "Отправь:\n\n"
        "/upload\nТОКЕН\n```python\nКОД\n```"
    )

@host_app.on_message(filters.command("upload"))
async def upload_bot(_, msg: Message):
    user_id = msg.from_user.id

    text = msg.text.replace("/upload", "", 1).strip()
    lines = text.split("\n")

    if len(lines) < 3:
        await msg.reply("Неверный формат")
        return

    token = lines[0].strip()

    try:
        code_start = text.find("```python") + len("```python")
        code_end = text.find("```", code_start)
        if code_start < 10 or code_end < 0:
            raise ValueError("Код не найден")
        code = text[code_start:code_end].strip()
    except:
        await msg.reply("Код должен быть в ```python ... ```")
        return

    status_msg = await msg.reply("Проверяю...")
    check = await check_token(token)

    if not check["valid"]:
        await status_msg.edit(f"Ошибка: {check['error']}")
        return

    if "from pyrogram" not in code:
        code = "from pyrogram import Client, filters\nimport asyncio\n\n" + code

    if "app.run()" not in code:
        code += "\n\napp.run()"

    await status_msg.edit(f"Запускаю @{check['bot_username']}...")
    result = await run_user_bot(user_id, token, code)

    if result["success"]:
        await status_msg.edit(f"Бот запущен! /stop /status")

@host_app.on_message(filters.command("stop"))
async def stop_bot(_, msg: Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        await msg.reply("Нет запущенных ботов")
        return

    await stop_user_bot(user_id)
    await msg.reply("Бот остановлен")

@host_app.on_message(filters.command("status"))
async def status_bot(_, msg: Message):
    user_id = msg.from_user.id

    if user_id not in running_bots:
        await msg.reply("Нет запущенных ботов")
        return

    bot = running_bots[user_id]
    uptime = time.time() - bot.get("started_at", 0)
    hours, rem = divmod(int(uptime), 3600)
    minutes, seconds = divmod(rem, 60)

    await msg.reply(
        f"Статус\n"
        f"Бот: @{bot.get('bot_username', '?')}\n"
        f"Статус: {bot['status']}\n"
        f"Аптайм: {hours}ч {minutes}м {seconds}с"
    )

async def main():
    BOTS_DIR.mkdir(exist_ok=True)

    print("Запуск...")
    await host_app.start()
    me = await host_app.get_me()
    print(f"Бот @{me.username} запущен")

    await asyncio.Event().wait()

# Flask для Render
flask_app = Flask(__name__)

@flask_app.route("/")
def health():
    return "OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Остановка...")
