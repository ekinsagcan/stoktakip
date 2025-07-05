import asyncio
import logging
from datetime import datetime
from typing import Dict, List
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import sqlite3

# Bot tokenınızı buraya ekleyin
BOT_TOKEN = "7602002058:AAFLWeRECvcJ8gQl_c5cvJ9drXZCutJPEFQ"

# Veritabanı kurulumu
def init_database():
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tracked_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        product_name TEXT,
        product_url TEXT,
        selector TEXT,
        in_stock_keywords TEXT,
        out_of_stock_keywords TEXT,
        last_status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, product_url)
    )
    ''')
    conn.commit()
    conn.close()

# Stok durumu kontrolü
class StockChecker:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def check_stock(self, url: str, selector: str = None, 
                         in_stock_keywords: List[str] = None, 
                         out_of_stock_keywords: List[str] = None) -> Dict:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, timeout=30) as response:
                    if response.status == 200:
                        html = await response.text()
                        soup = BeautifulSoup(html, 'html.parser')
                        stock_status = self._analyze_stock_status(soup, selector, 
                                                                in_stock_keywords, 
                                                                out_of_stock_keywords)
                        return {
                            'success': True,
                            'in_stock': stock_status['in_stock'],
                            'status_text': stock_status['status_text'],
                            'price': stock_status.get('price', 'N/A')
                        }
                    return {'success': False, 'error': f'HTTP {response.status}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _analyze_stock_status(self, soup, selector=None, 
                            in_stock_keywords=None, out_of_stock_keywords=None):
        default_in_stock = ['stokta', 'mevcut', 'satın al', 'sepete ekle', 
                          'add to cart', 'buy now', 'in stock']
        default_out_of_stock = ['stokta yok', 'tükendi', 'mevcut değil', 
                              'out of stock', 'sold out', 'unavailable']
        
        in_stock_keywords = in_stock_keywords or default_in_stock
        out_of_stock_keywords = out_of_stock_keywords or default_out_of_stock
        
        page_text = soup.get_text().lower()
        
        if selector:
            target_elements = soup.select(selector)
            target_text = ' '.join([elem.get_text().lower() for elem in target_elements]) if target_elements else page_text
        else:
            target_text = page_text
        
        in_stock_found = any(keyword.lower() in target_text for keyword in in_stock_keywords)
        out_of_stock_found = any(keyword.lower() in target_text for keyword in out_of_stock_keywords)
        
        price = self._extract_price(soup)
        
        if in_stock_found and not out_of_stock_found:
            return {'in_stock': True, 'status_text': 'Stokta mevcut', 'price': price}
        elif out_of_stock_found:
            return {'in_stock': False, 'status_text': 'Stokta yok', 'price': price}
        else:
            if any(word in target_text for word in ['price', 'fiyat', '₺', '$', '€']):
                return {'in_stock': True, 'status_text': 'Muhtemelen stokta', 'price': price}
            return {'in_stock': False, 'status_text': 'Stok durumu belirsiz', 'price': price}

    def _extract_price(self, soup):
        price_selectors = [
            '.price', '.fiyat', '[class*="price"]', '[class*="fiyat"]',
            '.amount', '.cost', '[data-testid*="price"]'
        ]
        
        for selector in price_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().strip()
                if any(currency in text for currency in ['₺', '$', '€', 'TL']):
                    return text
        return 'N/A'

# Veritabanı işlemleri
def save_tracked_product(user_id: int, product_name: str, product_url: str, 
                        selector: str = None, in_stock_keywords: str = None, 
                        out_of_stock_keywords: str = None):
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    try:
        cursor.execute('''
        INSERT OR REPLACE INTO tracked_products
        (user_id, product_name, product_url, selector, in_stock_keywords, out_of_stock_keywords, last_status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (user_id, product_name, product_url, selector, 
             in_stock_keywords, out_of_stock_keywords, 'unknown'))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Database error: {e}")
        return False
    finally:
        conn.close()

def get_tracked_products(user_id: int = None):
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    if user_id:
        cursor.execute('SELECT * FROM tracked_products WHERE user_id = ?', (user_id,))
    else:
        cursor.execute('SELECT * FROM tracked_products')
    products = cursor.fetchall()
    conn.close()
    return products

def update_product_status(product_id: int, status: str):
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('UPDATE tracked_products SET last_status = ? WHERE id = ?', (status, product_id))
    conn.commit()
    conn.close()

def delete_tracked_product(user_id: int, product_id: int):
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tracked_products WHERE id = ? AND user_id = ?', (product_id, user_id))
    conn.commit()
    conn.close()

# Bot komutları
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
    🎉 **Stok Takip Botu'na Hoş Geldiniz!**

    **Komutlar:**
    • /ekle - Yeni ürün ekle
    • /liste - Takip edilen ürünler
    • /sil - Ürün sil
    • /durum - Anlık stok kontrolü
    • /help - Yardım

    Nasıl kullanılır:
    1. /ekle komutu ile ürün ekleyin
    2. Bot stok durumunu otomatik kontrol eder
    3. Stok geldiğinde bildirim alırsınız!
    """
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Kullanım: /ekle <ürün_adı> <url>\nÖrnek: /ekle iPhone https://example.com/iphone",
            parse_mode='Markdown'
        )
        return

    product_name = context.args[0]
    product_url = context.args[1]
    selector = context.args[2] if len(context.args) > 2 else None
    in_stock_keywords = context.args[3] if len(context.args) > 3 else None
    out_of_stock_keywords = context.args[4] if len(context.args) > 4 else None

    if not product_url.startswith(('http://', 'https://')):
        await update.message.reply_text("⚠ Geçerli bir URL girin (http:// veya https:// ile başlamalı)")
        return

    if save_tracked_product(update.effective_user.id, product_name, product_url, 
                           selector, in_stock_keywords, out_of_stock_keywords):
        await update.message.reply_text(f"✅ {product_name} takibe eklendi!\n\nURL: {product_url}")
        
        checker = StockChecker()
        result = await checker.check_stock(
            product_url, 
            selector,
            in_stock_keywords.split(',') if in_stock_keywords else None,
            out_of_stock_keywords.split(',') if out_of_stock_keywords else None
        )
        
        if result['success']:
            status = "✅ Stokta" if result['in_stock'] else "⚠ Stokta yok"
            await update.message.reply_text(
                f"{status}\nDurum: {result['status_text']}\nFiyat: {result['price']}"
            )
        else:
            await update.message.reply_text(f"⛔ Kontrol başarısız: {result['error']}")
    else:
        await update.message.reply_text("⚠ Ürün eklenirken hata oluştu.")

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_tracked_products(update.effective_user.id)
    if not products:
        await update.message.reply_text("📋 Henüz takip edilen ürün yok.")
        return

    message = "📋 **Takip Edilen Ürünler:**\n\n"
    for product in products:
        product_id, _, name, url, _, _, _, last_status, _ = product
        status = "✅" if last_status == 'in_stock' else "⚠" if last_status == 'out_of_stock' else "❓"
        message += f"{status} {name}\nID: {product_id}\nURL: {url[:50]}...\n\n"

    keyboard = [[InlineKeyboardButton("🗑 Ürün Sil", callback_data="delete_menu")]]
    await update.message.reply_text(message, 
                                  reply_markup=InlineKeyboardMarkup(keyboard),
                                  parse_mode='Markdown')

async def delete_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    products = get_tracked_products(query.from_user.id)

    if not products:
        await query.edit_message_text("📋 Silinecek ürün yok.")
        return

    keyboard = [
        [InlineKeyboardButton(f"🗑 {name}", callback_data=f"delete_{product_id}")]
        for product_id, _, name, *_ in products
    ]
    keyboard.append([InlineKeyboardButton("« Geri", callback_data="back_to_list")])
    await query.edit_message_text("🗑 Silinecek ürünü seçin:", 
                                reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    product_id = int(query.data.split('_')[1])
    delete_tracked_product(query.from_user.id, product_id)
    await query.edit_message_text("✅ Ürün takipten çıkarıldı.")

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    products = get_tracked_products(update.effective_user.id)
    if not products:
        await update.message.reply_text("📋 Kontrol edilecek ürün yok.")
        return

    await update.message.reply_text("🔍 Stok durumları kontrol ediliyor...")
    checker = StockChecker()
    
    for product in products:
        product_id, _, name, url, selector, in_stock_kw, out_of_stock_kw, _, _ = product
        result = await checker.check_stock(
            url, 
            selector,
            in_stock_kw.split(',') if in_stock_kw else None,
            out_of_stock_kw.split(',') if out_of_stock_kw else None
        )
        
        if result['success']:
            status = "✅" if result['in_stock'] else "⚠"
            await update.message.reply_text(
                f"{status} {name}\nDurum: {result['status_text']}\nFiyat: {result['price']}"
            )
        else:
            await update.message.reply_text(f"⚠ {name} - Kontrol başarısız: {result['error']}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    📚 **Yardım**

    **Temel Komutlar:**
    • /start - Botu başlat
    • /ekle <ürün_adı> <url> - Ürün ekle
    • /liste - Takip edilen ürünler
    • /sil - Ürün sil
    • /durum - Anlık stok kontrolü

    **Örnek:**
    /ekle iPhone https://example.com/iphone
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "delete_menu":
        await delete_product_menu(update, context)
    elif query.data.startswith("delete_"):
        await handle_delete(update, context)
    elif query.data == "back_to_list":
        await list_products(update, context)

async def stock_monitoring_loop(application):
    checker = StockChecker()
    while True:
        try:
            products = get_tracked_products()
            for product in products:
                product_id, user_id, name, url, selector, in_stock_kw, out_of_stock_kw, last_status, _ = product
                result = await checker.check_stock(
                    url, 
                    selector,
                    in_stock_kw.split(',') if in_stock_kw else None,
                    out_of_stock_kw.split(',') if out_of_stock_kw else None
                )
                
                if result['success']:
                    current_status = 'in_stock' if result['in_stock'] else 'out_of_stock'
                    if current_status != last_status and current_status == 'in_stock':
                        message = f"🚀 **STOK GELDİ!**\n\n🏷 {name}\n💰 {result['price']}\n🔗 {url}"
                        try:
                            await application.bot.send_message(user_id, message, parse_mode='Markdown')
                        except Exception as e:
                            logging.error(f"Bildirim hatası: {e}")
                    update_product_status(product_id, current_status)
                await asyncio.sleep(2)
            await asyncio.sleep(300)
        except Exception as e:
            logging.error(f"Stok kontrol hatası: {e}")
            await asyncio.sleep(60)

def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    init_database()
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ekle", add_product))
    application.add_handler(CommandHandler("liste", list_products))
    application.add_handler(CommandHandler("durum", check_status))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback))

    loop = asyncio.get_event_loop()
    loop.create_task(stock_monitoring_loop(application))

    print("🎉 Stok Takip Botu başlatılıyor...")
    application.run_polling()

if __name__ == "__main__":
    main()
