import os
import asyncio
import requests
from bs4 import BeautifulSoup
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing!")

# Kullanıcı takip listesi: { user_id: [ { "url": ..., "notified": bool }, ... ] }
user_tracking = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hoş geldin! Zara ürün linkini gönder, ben stoğa girince haber vereyim. Birden fazla ürün gönderebilirsin."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "zara.com" in text:
        if user_id not in user_tracking:
            user_tracking[user_id] = []

        already_added = any(item["url"] == text for item in user_tracking[user_id])
        if already_added:
            await update.message.reply_text("🔁 Bu ürünü zaten takip ediyorsun.")
        else:
            user_tracking[user_id].append({"url": text, "notified": False})
            await update.message.reply_text("✅ Ürün takip listene eklendi!")
    else:
        await update.message.reply_text("⛔ Lütfen geçerli bir Zara ürün linki gönder.")

def check_stock(url: str) -> bool:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        return not ("Tükendi" in soup.text or "Stokta yok" in soup.text)
    except Exception as e:
        print(f"[HATA] {url}: {e}")
        return False

async def background_stock_checker(application):
    while True:
        for user_id, items in user_tracking.items():
            for item in items:
                in_stock = check_stock(item["url"])
                if in_stock and not item["notified"]:
                    await application.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 Stoğa girdi!\n{item['url']}"
                    )
                    item["notified"] = True
                elif not in_stock:
                    item["notified"] = False
        await asyncio.sleep(300)  # 5 dakika

async def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # Arkaplan stoğu kontrol döngüsünü başlat
    app.job_queue.run_repeating(lambda _: asyncio.create_task(background_stock_checker(app)), interval=300, first=0)

    print("Bot başlatıldı...")
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
