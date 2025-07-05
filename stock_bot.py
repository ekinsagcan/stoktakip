import os
import threading
import time
import requests
from bs4 import BeautifulSoup
from telegram import Update, Bot
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

updater = Updater(token=TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Her kullanıcı için birden çok ürün takibi
user_tracking = {}  # {chat_id: [ {url: ..., notified: False}, ... ]}

def check_stock(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers)
        soup = BeautifulSoup(r.text, 'html.parser')
        if "Tükendi" in soup.text or "Stokta yok" in soup.text:
            return False
        return True
    except Exception as e:
        print(f"[HATA] {url}: {e}")
        return False

def background_stock_checker():
    while True:
        for chat_id, items in user_tracking.items():
            for item in items:
                url = item["url"]
                in_stock = check_stock(url)
                if in_stock and not item["notified"]:
                    updater.bot.send_message(chat_id=chat_id, text=f"🎉 Stoğa girdi!\n{url}")
                    item["notified"] = True
                elif not in_stock:
                    item["notified"] = False
        time.sleep(300)  # 5 dakika

def start(update: Update, context: CallbackContext):
    update.message.reply_text("👋 Hoş geldin! Zara ürün linkini gönder. İstediğin kadar link gönderebilirsin.")

def handle_message(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    text = update.message.text.strip()

    if "zara.com" in text:
        if chat_id not in user_tracking:
            user_tracking[chat_id] = []
        if any(item["url"] == text for item in user_tracking[chat_id]):
            update.message.reply_text("🔁 Bu ürünü zaten takip ediyorsun.")
        else:
            user_tracking[chat_id].append({"url": text, "notified": False})
            update.message.reply_text("✅ Ürün takip listene eklendi!")
    else:
        update.message.reply_text("⛔ Lütfen geçerli bir Zara ürün linki gönder.")

dispatcher.add_handler(CommandHandler("start", start))
dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

if __name__ == '__main__':
    threading.Thread(target=background_stock_checker, daemon=True).start()
    updater.start_polling()
    updater.idle()
