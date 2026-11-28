import os
import logging
import sqlite3
import asyncio
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")

import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)

ADMIN_ID = 6684007846
AUTO_DELETE_SECONDS = 600

logging.basicConfig(level=logging.INFO)

import os

DB_PATH = os.getenv("DB_PATH", "files.db")
db = sqlite3.connect(DB_PATH, check_same_thread=False)

db.execute("""
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    file_id TEXT,
    file_type TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    description TEXT,
    poster_id TEXT,
    category TEXT,
    rating TEXT
)
""")

db.execute("""
CREATE TABLE IF NOT EXISTS video_qualities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER,
    quality TEXT,
    file_id TEXT,
    file_type TEXT
)
""")

db.commit()


def admin(uid):
    return uid == ADMIN_ID


def get_channels():
    return db.execute(
        "SELECT id, username FROM channels ORDER BY id"
    ).fetchall()


async def check_subscriptions(uid, context):
    missing = []

    for channel_id, username in get_channels():
        try:
            member = await context.bot.get_chat_member(
                chat_id=username,
                user_id=uid
            )

            if member.status not in ("creator", "administrator", "member"):
                if not (
                    member.status == "restricted"
                    and getattr(member, "is_member", False)
                ):
                    missing.append(username)

        except Exception as e:
            logging.error("Channel check failed: %s", e)
            missing.append(username)

    return missing


def join_keyboard(missing):
    kb = []

    for username in missing:
        kb.append([
            InlineKeyboardButton(
                "Join " + username,
                url=f"https://t.me/{username.lstrip('@')}"
            )
        ])

    kb.append([
        InlineKeyboardButton(
            "✅ Check Join",
            callback_data="check_join"
        )
    ])

    return InlineKeyboardMarkup(kb)


async def delete_after(bot, chat_id, message_id):
    await asyncio.sleep(AUTO_DELETE_SECONDS)

    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
    except Exception as e:
        logging.warning("Auto delete failed: %s", e)


async def send_auto_file(context, chat_id, file_id, file_type, caption):
    if file_type == "video":
        msg = await context.bot.send_video(
            chat_id=chat_id,
            video=file_id,
            caption=caption
        )
    else:
        msg = await context.bot.send_document(
            chat_id=chat_id,
            document=file_id,
            caption=caption
        )

    context.application.create_task(
        delete_after(context.bot, chat_id, msg.message_id)
    )

    await context.bot.send_message(
        chat_id=chat_id,
        text="⏳ This file will be deleted after 10 minutes."
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    db.execute(
        "INSERT OR IGNORE INTO users VALUES (?)",
        (uid,)
    )
    db.commit()

    if not admin(uid):
        missing = await check_subscriptions(uid, context)

        if missing:
            await update.message.reply_text(
                "🔒 Join all required channels first:",
                reply_markup=join_keyboard(missing)
            )
            return

    await update.message.reply_text(
        "🎬 Welcome to Firoj Video Library!\n\n"
        "Send a video name to search."
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not admin(update.effective_user.id):
        return

    kb = [
        [InlineKeyboardButton("🎬 Add New Video", callback_data="add_video")],
        [InlineKeyboardButton("📤 Upload Old File", callback_data="upload")],
        [InlineKeyboardButton("🗑 Delete Old File", callback_data="delete")],
        [InlineKeyboardButton("➕ Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("➖ Remove Channel", callback_data="remove_channel")],
        [InlineKeyboardButton("📋 List Channels", callback_data="list_channels")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")]
    ]

    await update.message.reply_text(
        "⚙️ FIROJ ADMIN PANEL",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def add_video_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["video_data"] = {}
    context.user_data["video_step"] = "name"

    await update.callback_query.message.reply_text(
        "🎬 Send the video title:"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = update.effective_user.id
    state = context.user_data.get("video_step")

    # Admin video catalog creation
    if admin(uid) and state:
        data = context.user_data["video_data"]

        if state == "name":
            if not msg.text:
                await msg.reply_text("Please send the video name as text.")
                return

            data["name"] = msg.text.strip()
            context.user_data["video_step"] = "description"
            await msg.reply_text("📝 Send the description:")
            return

        if state == "description":
            if not msg.text:
                await msg.reply_text("Please send the description as text.")
                return

            data["description"] = msg.text.strip()
            context.user_data["video_step"] = "category"
            await msg.reply_text("🎭 Send category (example: Comedy, Action):")
            return

        if state == "category":
            if not msg.text:
                await msg.reply_text("Please send category as text.")
                return

            data["category"] = msg.text.strip()
            context.user_data["video_step"] = "rating"
            await msg.reply_text("⭐ Send rating (example: 8.0/10):")
            return

        if state == "rating":
            if not msg.text:
                await msg.reply_text("Please send rating as text.")
                return

            data["rating"] = msg.text.strip()
            context.user_data["video_step"] = "poster"
            await msg.reply_text("🖼 Now send the poster photo:")
            return

        if state == "poster":
            if not msg.photo:
                await msg.reply_text("Please send a photo as the poster.")
                return

            data["poster_id"] = msg.photo[-1].file_id
            data["qualities"] = {}
            context.user_data["quality_index"] = 0
            context.user_data["video_step"] = "quality"

            await msg.reply_text(
                "📥 Send your 1080p video/document.\n"
                "If unavailable, type SKIP."
            )
            return

        if state == "quality":
            qualities = ["1080p", "720p", "480p"]
            index = context.user_data["quality_index"]
            quality = qualities[index]

            if msg.text and msg.text.strip().upper() == "SKIP":
                pass
            elif msg.video:
                data["qualities"][quality] = (
                    msg.video.file_id, "video"
                )
            elif msg.document:
                data["qualities"][quality] = (
                    msg.document.file_id, "document"
                )
            else:
                await msg.reply_text(
                    "Send a video/document or type SKIP."
                )
                return

            index += 1
            context.user_data["quality_index"] = index

            if index < len(qualities):
                context.user_data["video_step"] = "quality"
                await msg.reply_text(
                    f"📥 Now send {qualities[index]} video/document or type SKIP."
                )
                return

            video_id = db.execute(
                """INSERT INTO videos
                (name, description, poster_id, category, rating)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    data["name"],
                    data["description"],
                    data["poster_id"],
                    data["category"],
                    data["rating"]
                )
            ).lastrowid

            for quality, item in data["qualities"].items():
                file_id, file_type = item

                db.execute(
                    """INSERT INTO video_qualities
                    (video_id, quality, file_id, file_type)
                    VALUES (?, ?, ?, ?)""",
                    (video_id, quality, file_id, file_type)
                )

            db.commit()

            context.user_data.pop("video_step", None)
            context.user_data.pop("quality_index", None)
            context.user_data.pop("video_data", None)

            kb = [[
                InlineKeyboardButton(
                    "📢 Publish Preview",
                    callback_data=f"publish_{video_id}"
                )
            ]]

            await msg.reply_text(
                "✅ Video saved successfully!\n"
                "Press Publish Preview to see its catalog post.",
                reply_markup=InlineKeyboardMarkup(kb)
            )
            return

    # Admin channel adding
    if admin(uid) and context.user_data.get("await_channel"):
        username = msg.text.strip() if msg.text else ""

        if not username.startswith("@"):
            await msg.reply_text("Send a public channel username like @mychannel.")
            return

        try:
            await context.bot.get_chat(username)

            db.execute(
                "INSERT OR IGNORE INTO channels (username) VALUES (?)",
                (username,)
            )
            db.commit()

            context.user_data["await_channel"] = False
            await msg.reply_text(
                f"✅ Channel added: {username}\n"
                "Make sure the bot is an administrator there."
            )
        except Exception as e:
            logging.error("Channel add failed: %s", e)
            await msg.reply_text("❌ Channel not found or bot cannot access it.")
        return

    # Legacy file upload
    if admin(uid) and (msg.video or msg.document):
        if not msg.caption:
            await msg.reply_text("Add a file name in the caption.")
            return

        if msg.video:
            file_id, typ = msg.video.file_id, "video"
        else:
            file_id, typ = msg.document.file_id, "document"

        db.execute(
            "INSERT INTO files (name,file_id,file_type) VALUES (?, ?, ?)",
            (msg.caption, file_id, typ)
        )
        db.commit()

        await msg.reply_text("✅ Old file uploaded.")
        return

    if not msg.text:
        return

    # User search
    if not admin(uid):
        missing = await check_subscriptions(uid, context)

        if missing:
            await msg.reply_text(
                "🔒 Join all required channels first:",
                reply_markup=join_keyboard(missing)
            )
            return

    results = db.execute(
        "SELECT id, name FROM videos WHERE name LIKE ? LIMIT 10",
        (f"%{msg.text.strip()}%",)
    ).fetchall()

    old_results = db.execute(
        "SELECT id, name FROM files WHERE name LIKE ? LIMIT 10",
        (f"%{msg.text.strip()}%",)
    ).fetchall()

    kb = []

    for vid, name in results:
        kb.append([
            InlineKeyboardButton(
                "🎬 " + name[:40],
                callback_data=f"vid_{vid}"
            )
        ])

    for fid, name in old_results:
        kb.append([
            InlineKeyboardButton(
                "📁 " + name[:40],
                callback_data=f"get_{fid}"
            )
        ])

    if not kb:
        await msg.reply_text("❌ No videos found.")
        return

    await msg.reply_text(
        "🔎 Search Results:",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id

    if q.data == "check_join":
        missing = await check_subscriptions(uid, context)

        if missing:
            await q.message.reply_text(
                "❌ Join the remaining channels:",
                reply_markup=join_keyboard(missing)
            )
        else:
            await q.message.reply_text(
                "✅ Subscription verified! Send a video name to search."
            )
        return

    if not admin(uid) and (
        q.data.startswith(("vid_", "get_"))
    ):
        missing = await check_subscriptions(uid, context)

        if missing:
            await q.message.reply_text(
                "🔒 Join all required channels first:",
                reply_markup=join_keyboard(missing)
            )
            return

    if q.data == "add_video":
        if admin(uid):
            await add_video_start(update, context)
        return

    if not admin(uid):
        if q.data.startswith("vid_"):
            video_id = int(q.data.split("_")[1])
            await show_video(q, video_id)
        elif q.data.startswith("get_"):
            await send_old_file(q, context)
        return

    if q.data == "upload":
        await q.message.reply_text(
            "Send a video/document with its name in the caption."
        )

    elif q.data == "add_channel":
        context.user_data["await_channel"] = True
        await q.message.reply_text("Send channel username, example @mychannel")

    elif q.data == "remove_channel":
        rows = get_channels()
        kb = [
            [InlineKeyboardButton(
                "➖ " + username,
                callback_data=f"chdel_{cid}"
            )]
            for cid, username in rows
        ]

        if kb:
            await q.message.reply_text(
                "Select channel:",
                reply_markup=InlineKeyboardMarkup(kb)
            )
        else:
            await q.message.reply_text("No channels available.")

    elif q.data == "list_channels":
        rows = get_channels()
        names = "\n".join(username for cid, username in rows)
        await q.message.reply_text(names or "No channels added.")

    elif q.data == "stats":
        total = db.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        await q.message.reply_text(
            f"📊 Statistics\nVideos: {total}\nUsers: {users}"
        )

    elif q.data == "delete":
        rows = db.execute(
            "SELECT id,name FROM files ORDER BY id DESC LIMIT 20"
        ).fetchall()

        kb = [
            [InlineKeyboardButton(
                "🗑 " + name[:35],
                callback_data=f"del_{fid}"
            )]
            for fid, name in rows
        ]

        await q.message.reply_text(
            "Select old file to delete:",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif q.data.startswith("del_"):
        fid = int(q.data.split("_")[1])
        db.execute("DELETE FROM files WHERE id=?", (fid,))
        db.commit()
        await q.message.reply_text("✅ File deleted.")

    elif q.data.startswith("chdel_"):
        cid = int(q.data.split("_")[1])
        db.execute("DELETE FROM channels WHERE id=?", (cid,))
        db.commit()
        await q.message.reply_text("✅ Channel removed.")

    elif q.data.startswith("publish_"):
        video_id = int(q.data.split("_")[1])
        await show_video(q, video_id)


async def show_video(q, video_id):
    row = db.execute(
        """SELECT name, description, poster_id, category, rating
        FROM videos WHERE id=?""",
        (video_id,)
    ).fetchone()

    if not row:
        await q.message.reply_text("Video not found.")
        return

    name, description, poster, category, rating = row

    qualities = db.execute(
        """SELECT quality FROM video_qualities
        WHERE video_id=? ORDER BY id""",
        (video_id,)
    ).fetchall()

    kb = [
        [InlineKeyboardButton(
            "📥 " + quality,
            callback_data=f"quality_{video_id}_{quality}"
        )]
        for (quality,) in qualities
    ]

    caption = (
        f"🎬 {name}\n\n"
        f"⭐ {rating}\n"
        f"🎭 {category}\n\n"
        f"📝 {description}\n\n"
        f"👇 Select video quality:"
    )

    await q.message.reply_photo(
        photo=poster,
        caption=caption,
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def quality_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    parts = q.data.split("_")
    video_id = int(parts[1])
    quality = parts[2]

    if not admin(q.from_user.id):
        missing = await check_subscriptions(q.from_user.id, context)

        if missing:
            await q.message.reply_text(
                "🔒 Join all required channels first:",
                reply_markup=join_keyboard(missing)
            )
            return

    row = db.execute(
        """SELECT file_id, file_type FROM video_qualities
        WHERE video_id=? AND quality=?""",
        (video_id, quality)
    ).fetchone()

    if not row:
        await q.message.reply_text("This quality is not available.")
        return

    name = db.execute(
        "SELECT name FROM videos WHERE id=?",
        (video_id,)
    ).fetchone()

    if not name:
        await q.message.reply_text("Video not found.")
        return

    await send_auto_file(
        context,
        q.message.chat_id,
        row[0],
        row[1],
        name[0] + " - " + quality
    )


async def send_old_file(q, context):
    fid = int(q.data.split("_")[1])

    row = db.execute(
        "SELECT name,file_id,file_type FROM files WHERE id=?",
        (fid,)
    ).fetchone()

    if not row:
        await q.message.reply_text("File not found.")
        return

    await send_auto_file(
        context,
        q.message.chat_id,
        row[1],
        row[2],
        row[0]
    )


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("admin", admin_panel))

app.add_handler(CallbackQueryHandler(
    quality_button,
    pattern=r"^quality_\d+_(1080p|720p|480p)$"
))

app.add_handler(CallbackQueryHandler(
    buttons
))

app.add_handler(MessageHandler(
    filters.ALL & ~filters.COMMAND,
    handle_message
))

print("Firoj Video Library Bot is running!")
print("Multiple Force Subscribe: Enabled")
print("Auto Delete Timer: 10 Minutes")

app.run_polling()
