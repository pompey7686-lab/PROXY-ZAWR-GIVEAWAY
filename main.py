import os
import sqlite3
import secrets
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes
)

TOKEN = os.environ["BOT_TOKEN"]
ADMIN_IDS = {
    int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()
}
DB = "raffle.db"


def connect():
    return sqlite3.connect(DB)


def setup():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS allowed (
                user_id INTEGER PRIMARY KEY
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS participants (
                raffle_id INTEGER,
                user_id INTEGER,
                name TEXT,
                PRIMARY KEY (raffle_id, user_id)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS raffles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                active INTEGER DEFAULT 1
            )
        """)


def is_admin(update):
    return update.effective_user.id in ADMIN_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎁 PROXY ZAWR — бот розыгрышей.\n"
        "/id — узнать свой ID Telegram.\n"
        "/help — список команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Команды администратора:\n"
        "/allow ID ID — допустить донатеров\n"
        "/allowed — показать список допущенных\n"
        "/raffle — опубликовать розыгрыш в группе\n"
        "/draw — выбрать победителя\n"
        "/cancel — отменить розыгрыш\n\n"
        "Участники нажимают кнопку под публикацией."
    )


async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Твой Telegram ID: {update.effective_user.id}"
    )


async def allow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    ids = []
    for arg in context.args:
        try:
            ids.append(int(arg))
        except ValueError:
            continue

    if not ids:
        await update.message.reply_text(
            "Укажи ID пользователей.\nПример: /allow 123456789 987654321"
        )
        return

    with connect() as db:
        for uid in ids:
            db.execute(
                "INSERT OR IGNORE INTO allowed VALUES (?)", (uid,)
            )

    await update.message.reply_text(
        f"✅ Добавлено в список допуска: {len(ids)} пользователей."
    )


async def allowed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    with connect() as db:
        rows = db.execute(
            "SELECT user_id FROM allowed ORDER BY user_id"
        ).fetchall()

    if not rows:
        await update.message.reply_text("Список пока пуст.")
        return

    await update.message.reply_text(
        "Допущенные участники:\n" +
        "\n".join(str(row[0]) for row in rows)
    )


async def raffle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    if update.effective_chat.type == "private":
        await update.message.reply_text(
            "Эту команду нужно отправить в группе PROXY ZAWR."
        )
        return

    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM allowed"
        ).fetchone()[0]

        if count == 0:
            await update.message.reply_text(
                "Сначала добавь донатеров командой /allow ID ID."
            )
            return

        db.execute(
            "UPDATE raffles SET active=0 WHERE active=1"
        )
        cursor = db.execute(
            "INSERT INTO raffles (chat_id, active) VALUES (?, 1)",
            (update.effective_chat.id,)
        )
        raffle_id = cursor.lastrowid

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "🎁 УЧАСТВОВАТЬ (0)",
            callback_data=f"join:{raffle_id}"
        )
    ]])

    await update.message.reply_text(
        "🎁 РОЗЫГРЫШ PROXY ZAWR!\n\n"
        "Приглашаем наших друзей, поддерживавших группу.\n"
        "Нажмите кнопку ниже, чтобы принять участие!\n\n"
        "🏆 Победитель будет выбран случайным образом.",
        reply_markup=keyboard
    )


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    raffle_id = int(query.data.split(":")[1])
    user = query.from_user

    with connect() as db:
        permitted = db.execute(
            "SELECT 1 FROM allowed WHERE user_id=?",
            (user.id,)
        ).fetchone()

        active = db.execute(
            "SELECT 1 FROM raffles WHERE id=? AND active=1",
            (raffle_id,)
        ).fetchone()

        if not active:
            await query.answer("Розыгрыш уже завершён.", show_alert=True)
            return

        if not permitted:
            await query.answer(
                "Этот розыгрыш доступен только приглашённым участникам.",
                show_alert=True
            )
            return

        db.execute(
            "INSERT OR IGNORE INTO participants VALUES (?, ?, ?)",
            (raffle_id, user.id, user.full_name)
        )

        count = db.execute(
            "SELECT COUNT(*) FROM participants WHERE raffle_id=?",
            (raffle_id,)
        ).fetchone()[0]

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🎁 УЧАСТВОВАТЬ ({count})",
            callback_data=f"join:{raffle_id}"
        )
    ]])

    try:
        await query.edit_message_reply_markup(reply_markup=keyboard)
    except Exception:
        pass

    await query.answer("✅ Ты зарегистрирован в розыгрыше!")


async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    with connect() as db:
        raffle_row = db.execute(
            "SELECT id FROM raffles WHERE active=1 ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if not raffle_row:
            await update.message.reply_text("Активного розыгрыша нет.")
            return

        raffle_id = raffle_row[0]

        rows = db.execute(
            "SELECT user_id, name FROM participants WHERE raffle_id=?",
            (raffle_id,)
        ).fetchall()

        if not rows:
            await update.message.reply_text(
                "Пока никто не нажал кнопку участия."
            )
            return

        winner = secrets.choice(rows)
        db.execute(
            "UPDATE raffles SET active=0 WHERE id=?",
            (raffle_id,)
        )

    await update.message.reply_text(
        f"🏆 ПОБЕДИТЕЛЬ PROXY ZAWR!\n\n"
        f"🎉 {winner[1]}\n"
        f"ID: {winner[0]}\n\n"
        f"Поздравляем с победой!"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return

    with connect() as db:
        db.execute("UPDATE raffles SET active=0 WHERE active=1")

    await update.message.reply_text("Розыгрыш отменён.")


def main():
    setup()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("id", get_id))
    app.add_handler(CommandHandler("allow", allow))
    app.add_handler(CommandHandler("allowed", allowed))
    app.add_handler(CommandHandler("raffle", raffle))
    app.add_handler(CommandHandler("draw", draw))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(join, pattern=r"^join:\d+$"))

    print("PROXY ZAWR Giveaway Bot запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
