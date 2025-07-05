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
        user_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        product_url TEXT NOT NULL,
        selector TEXT,
        in_stock_keywords TEXT,
        out_of_stock_keywords TEXT,
        last_status TEXT,
        last_checked TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, product_url)
    )
    ''') # Closing parenthesis added for the CREATE TABLE statement
    conn.commit()
    conn.close()

# Stok durumu kontrolü
class StockChecker:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8', # Add Accept-Language for better response
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Connection': 'keep-alive'
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
                    logging.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return {'success': False, 'error': f'HTTP {response.status}'}
        except aiohttp.ClientError as e:
            logging.error(f"Network error accessing {url}: {e}")
            return {'success': False, 'error': f'Network error: {e}'}
        except asyncio.TimeoutError:
            logging.error(f"Timeout accessing {url}")
            return {'success': False, 'error': 'Timeout error'}
        except Exception as e:
            logging.error(f"Error checking stock for {url}: {e}")
            return {'success': False, 'error': str(e)}

    def _analyze_stock_status(self, soup, selector=None, 
                            in_stock_keywords=None, out_of_stock_keywords=None):
        # Default keywords, more comprehensive and specific
        default_in_stock = ['sepete ekle', 'add to cart', 'in stock', 'stokta', 'satın al', 'hemen al']
        default_out_of_stock = ['stokta yok', 'tükendi', 'mevcut değil', 'out of stock', 'sold out', 'unavailable', 'tükenmek üzere', 'coming soon', 'notify me']
        
        # Use provided keywords if any, otherwise use defaults
        in_stock_keywords = [k.lower() for k in (in_stock_keywords or default_in_stock)]
        out_of_stock_keywords = [k.lower() for k in (out_of_stock_keywords or default_out_of_stock)]
        
        # Look for specific elements first
        # For Zara, "Add to Bag" button or similar is a strong indicator
        in_stock_elements = soup.select('button.add-to-cart-button, button.product-actions-add-to-cart-button, button[data-qa-action="add-to-cart"]')
        out_of_stock_elements = soup.select('.product-availability__message--out-of-stock, .availability-status--out-of-stock, .stock-error-message') # Add specific selectors for common out of stock messages

        # Check for in-stock elements
        if any(elem for elem in in_stock_elements if "add to" in elem.get_text().lower() or "sepete ekle" in elem.get_text().lower()):
            price = self._extract_price(soup)
            return {'in_stock': True, 'status_text': 'Stokta mevcut (Sepete Ekle butonu bulundu)', 'price': price}

        # Check for out-of-stock elements
        if any(elem for elem in out_of_stock_elements if "out of stock" in elem.get_text().lower() or "stokta yok" in elem.get_text().lower() or "tükendi" in elem.get_text().lower()):
            price = self._extract_price(soup)
            return {'in_stock': False, 'status_text': 'Stokta yok (Belirli element bulundu)', 'price': price}


        # If specific elements not found, check page text (less reliable)
        page_text = soup.get_text().lower()
        
        target_text = page_text
        if selector:
            target_elements = soup.select(selector)
            if target_elements:
                target_text = ' '.join([elem.get_text().lower() for elem in target_elements])
            
        # Prioritize out-of-stock keywords
        out_of_stock_found = any(keyword in target_text for keyword in out_of_stock_keywords)
        if out_of_stock_found:
            price = self._extract_price(soup)
            return {'in_stock': False, 'status_text': 'Stokta yok (Sayfa metninde bulundu)', 'price': price}

        in_stock_found = any(keyword in target_text for keyword in in_stock_keywords)
        if in_stock_found:
            price = self._extract_price(soup)
            return {'in_stock': True, 'status_text': 'Stokta mevcut (Sayfa metninde bulundu)', 'price': price}
        
        # Fallback if no clear keywords found, assume uncertain or potentially in stock if price is found
        price = self._extract_price(soup)
        if price != 'N/A':
            return {'in_stock': True, 'status_text': 'Muhtemelen stokta (Fiyat bulundu)', 'price': price}
        
        return {'in_stock': False, 'status_text': 'Stok durumu belirsiz (Hiçbir gösterge bulunamadı)', 'price': 'N/A'}


    def _extract_price(self, soup):
        # More specific price selectors. Zara often uses span with data-qa-action="product-price" or similar
        price_selectors = [
            'span.money-amount__main', # Common Zara price selector
            '[data-qa-action="product-price"]', # Another potential Zara price selector
            '.price', '.fiyat', '[class*="price"]', '[class*="fiyat"]',
            '.amount', '.cost', '[data-testid*="price"]',
            'div.product-price span', # Generic price within a div
            'span[itemprop="price"]', # Schema.org price
            'meta[itemprop="price"]' # Schema.org price in meta tag
        ]
        
        for selector in price_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().strip()
                # Check for currency symbols or numbers
                if any(currency in text for currency in ['₺', '$', '€', 'TL', 'USD', 'EUR']) or any(char.isdigit() for char in text):
                    # Clean up the price text
                    price = ''.join(filter(lambda x: x.isdigit() or x in [',', '.'], text))
                    if price:
                        return text # Return original text to keep currency symbol
        
        # Try to find price in script tags (JSON-LD or other embedded data)
        try:
            for script in soup.find_all('script', type='application/ld+json'):
                import json
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product' and item.get('offers') and item['offers'].get('price'):
                            price = item['offers']['price']
                            currency = item['offers'].get('priceCurrency', '')
                            return f"{price} {currency}".strip()
                elif data.get('@type') == 'Product' and data.get('offers') and data['offers'].get('price'):
                    price = data['offers']['price']
                    currency = data['offers'].get('priceCurrency', '')
                    return f"{price} {currency}".strip()
        except Exception as e:
            logging.debug(f"Error parsing JSON-LD for price: {e}")

        return 'N/A'

# Veritabanı işlemleri (unchanged)
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
    cursor.execute('UPDATE tracked_products SET last_status = ?, last_checked = CURRENT_TIMESTAMP WHERE id = ?', 
                  (status, product_id))
    conn.commit()
    conn.close()

def delete_tracked_product(user_id: int, product_id: int):
    conn = sqlite3.connect('stock_tracker.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM tracked_products WHERE id = ? AND user_id = ?', (product_id, user_id))
    conn.commit()
    conn.close()

# Bot komutları (unchanged, except for the fix to the add_product command for better argument handling)
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
    # This part needs to be more flexible for arguments
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Kullanım: /ekle <ürün_adı> <url> [css_selector] [stok_kelimeleri_virgülle_ayrılmış] [stokta_olmayan_kelimeleri_virgülle_ayrılmış]\n"
            "Örnek: /ekle iPhone https://example.com/iphone\n"
            "Örnek (gelişmiş): /ekle iPhone https://example.com .product-stock 'stokta,var' 'tükendi,yok'",
            parse_mode='Markdown'
        )
        return

    product_name = args[0]
    product_url = args[1]
    selector = args[2] if len(args) > 2 else None
    in_stock_keywords = args[3] if len(args) > 3 else None
    out_of_stock_keywords = args[4] if len(args) > 4 else None

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
            status_emoji = "✅" if result['in_stock'] else "⚠"
            await update.message.reply_text(
                f"**Anlık Durum Kontrolü:**\n"
                f"{status_emoji} {result['status_text']}\n"
                f"💰 Fiyat: {result['price']}",
                parse_mode='Markdown'
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
        product_id, _, name, url, _, _, _, last_status, last_checked, _ = product
        status_emoji = "✅" if last_status == 'in_stock' else "⚠" if last_status == 'out_of_stock' else "❓"
        last_checked_str = datetime.strptime(last_checked, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M') if last_checked else "Bilinmiyor"
        message += f"{status_emoji} {name}\n"
        message += f"ID: `{product_id}`\n" # Use backticks for ID to make it monospace
        message += f"Son kontrol: {last_checked_str}\n"
        message += f"URL: {url[:50]}...\n\n"

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
        [InlineKeyboardButton(f"🗑 {name} (ID: {product_id})", callback_data=f"delete_{product_id}")]
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
        product_id, _, name, url, selector, in_stock_kw, out_of_stock_kw, _, _, _ = product
        result = await checker.check_stock(
            url, 
            selector,
            in_stock_kw.split(',') if in_stock_kw else None,
            out_of_stock_kw.split(',') if out_of_stock_kw else None
        )
        
        if result['success']:
            status_emoji = "✅" if result['in_stock'] else "⚠"
            await update.message.reply_text(
                f"{status_emoji} **{name}**\n"
                f"Durum: {result['status_text']}\n"
                f"Fiyat: {result['price']}",
                parse_mode='Markdown'
            )
            update_product_status(product_id, 'in_stock' if result['in_stock'] else 'out_of_stock')
        else:
            await update.message.reply_text(f"⚠ **{name}** - Kontrol başarısız: {result['error']}", parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    📚 **Yardım**

    **Temel Komutlar:**
    • /start - Botu başlat
    • /ekle <ürün_adı> <url> - Ürün ekle
    • /liste - Takip edilen ürünler
    • /sil - Ürün sil
    • /durum - Anlık stok kontrolü

    **Gelişmiş Kullanım:**
    `/ekle <ürün_adı> <url> [css_selector] [stok_kelimeleri_virgülle_ayrılmış] [stokta_olmayan_kelimeleri_virgülle_ayrılmış]`
    Örnek: `/ekle iPhone https://example.com .stock-status "stokta,var" "tükendi,yok"`

    CSS Selector ve Kelimeler opsiyoneldir. Bot varsayılan olarak en yaygın durumları kontrol etmeye çalışır. Ancak, belirli bir site için daha doğru sonuçlar almak isterseniz bu parametreleri kullanabilirsiniz.
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
                product_id, user_id, name, url, selector, in_stock_kw, out_of_stock_kw, last_status, _, _ = product
                result = await checker.check_stock(
                    url, 
                    selector,
                    in_stock_kw.split(',') if in_stock_kw else None,
                    out_of_stock_kw.split(',') if out_of_stock_kw else None
                )
                
                if result['success']:
                    current_status = 'in_stock' if result['in_stock'] else 'out_of_stock'
                    if current_status != last_status and current_status == 'in_stock':
                        message = (
                            f"🚀 **STOK GELDİ!**\n\n"
                            f"🏷 **{name}**\n"
                            f"💰 Fiyat: {result['price']}\n"
                            f"🔗 [Ürüne Git]({url})\n\n"
                            f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"
                        )
                        try:
                            await application.bot.send_message(
                                chat_id=user_id,
                                text=message,
                                parse_mode='Markdown',
                                disable_web_page_preview=True
                            )
                        except Exception as e:
                            logging.error(f"Bildirim gönderilemedi (user_id: {user_id}, product_id: {product_id}): {e}")
                    
                    update_product_status(product_id, current_status)
                
                await asyncio.sleep(2)  # Her ürün arasında bekleme
            
            await asyncio.sleep(300)  # 5 dakika bekleme
        except Exception as e:
            logging.error(f"Stok kontrol döngüsü hatası: {e}")
            await asyncio.sleep(60)  # Hata durumunda 1 dakika bekle

def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )

    init_database()
    application = Application.builder().token(BOT_TOKEN).build()

    # Komut handler'ları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ekle", add_product))
    application.add_handler(CommandHandler("liste", list_products))
    application.add_handler(CommandHandler("durum", check_status))
    application.add_handler(CommandHandler("help", help_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(button_callback))

    # Stok kontrol döngüsünü başlat
    loop = asyncio.get_event_loop()
    loop.create_task(stock_monitoring_loop(application))

    print("🎉 Stok Takip Botu başlatılıyor...")
    application.run_polling()

if __name__ == "__main__":
    main()

