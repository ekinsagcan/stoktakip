import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List
import aiohttp
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue

# Ortam değişkenlerini al

BOT_TOKEN = os.getenv(“BOT_TOKEN”)
if not BOT_TOKEN:
raise ValueError(“BOT_TOKEN environment variable not set.”)

# Browserless URL ve API anahtarını al

BROWSERLESS_URL = os.getenv(“BROWSERLESS_URL”, “https://chrome.browserless.io”)
BROWSERLESS_API_KEY = os.getenv(“BROWSERLESS_API_KEY”)

# Logging yapılandırması

logging.basicConfig(
format=’%(asctime)s - %(name)s - %(levelname)s - %(message)s’,
level=logging.INFO
)
logger = logging.getLogger(**name**)

# Veritabanı kurulumu

def init_database():
conn = sqlite3.connect(‘stock_tracker.db’, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(’’’
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
‘’’)
conn.commit()
conn.close()

class StockChecker:
def **init**(self):
self.session = None
self.headers = {
‘User-Agent’: ‘Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36’,
‘Accept’: ‘text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8’,
‘Accept-Language’: ‘en-US,en;q=0.5’,
‘Accept-Encoding’: ‘gzip, deflate’,
‘Connection’: ‘keep-alive’,
‘Upgrade-Insecure-Requests’: ‘1’
}

```
async def get_session(self):
    if self.session is None:
        timeout = aiohttp.ClientTimeout(total=30)
        self.session = aiohttp.ClientSession(
            timeout=timeout,
            headers=self.headers,
            connector=aiohttp.TCPConnector(ssl=False)
        )
    return self.session

async def check_stock_with_browserless(self, url: str) -> Dict:
    """Browserless API kullanarak stok kontrolü"""
    if not BROWSERLESS_API_KEY:
        return {'success': False, 'error': 'Browserless API key not configured'}
    
    try:
        session = await self.get_session()
        
        # Browserless API endpoint
        api_url = f"{BROWSERLESS_URL}/content"
        
        params = {
            'token': BROWSERLESS_API_KEY
        }
        
        payload = {
            'url': url,
            'waitFor': 3000,  # 3 saniye bekle
            'rejectResourceTypes': ['image', 'media', 'font']
        }
        
        async with session.post(api_url, params=params, json=payload) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                stock_status = self._analyze_stock_status(soup)
                return {
                    'success': True,
                    'in_stock': stock_status['in_stock'],
                    'status_text': stock_status['status_text'],
                    'price': stock_status.get('price', 'N/A')
                }
            else:
                return {
                    'success': False,
                    'error': f'Browserless API error: {response.status} - {await response.text()}'
                }
                
    except Exception as e:
        logger.error(f"Browserless API error: {e}")
        return {'success': False, 'error': f'Browserless API error: {str(e)}'}

async def check_stock_with_requests(self, url: str) -> Dict:
    """Doğrudan HTTP istekleri ile stok kontrolü"""
    try:
        session = await self.get_session()
        
        async with session.get(url) as response:
            if response.status == 200:
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')
                
                stock_status = self._analyze_stock_status(soup)
                return {
                    'success': True,
                    'in_stock': stock_status['in_stock'],
                    'status_text': stock_status['status_text'],
                    'price': stock_status.get('price', 'N/A')
                }
            else:
                return {
                    'success': False,
                    'error': f'HTTP error: {response.status}'
                }
                
    except Exception as e:
        logger.error(f"HTTP request error: {e}")
        return {'success': False, 'error': f'HTTP request error: {str(e)}'}

async def check_stock(self, url: str, selector: str = None,
                     in_stock_keywords: List[str] = None,
                     out_of_stock_keywords: List[str] = None) -> Dict:
    """Ana stok kontrol fonksiyonu - önce Browserless, sonra direct HTTP"""
    
    # Önce Browserless ile dene
    if BROWSERLESS_API_KEY:
        logger.info(f"Trying Browserless API for {url}")
        result = await self.check_stock_with_browserless(url)
        if result['success']:
            return result
        else:
            logger.warning(f"Browserless failed: {result['error']}")
    
    # Browserless başarısız olursa direct HTTP ile dene
    logger.info(f"Trying direct HTTP request for {url}")
    result = await self.check_stock_with_requests(url)
    
    return result

def _analyze_stock_status(self, soup, selector=None,
                        in_stock_keywords=None, out_of_stock_keywords=None):
    default_in_stock = ['sepete ekle', 'add to cart', 'in stock', 'stokta', 'satın al', 'hemen al', 'ürün sepetinizde', 'buy now', 'purchase']
    default_out_of_stock = ['stokta yok', 'tükendi', 'mevcut değil', 'out of stock', 'sold out', 'unavailable', 'tükenmek üzere', 'coming soon', 'notify me', 'beden tükenmiş', 'temporarily unavailable']

    in_stock_keywords = [k.lower() for k in (in_stock_keywords or default_in_stock)]
    out_of_stock_keywords = [k.lower() for k in (out_of_stock_keywords or default_out_of_stock)]

    # Önce out-of-stock selektörlerini kontrol et
    out_of_stock_selectors = [
        '.product-availability__message--out-of-stock',
        '.availability-status--out-of-stock',
        '.stock-error-message',
        '.size-selector__size--out-of-stock',
        '.stock-info-text',
        '[data-qa-action="unavailable-product"]',
        'div.product-actions__disabled-message',
        '.out-of-stock',
        '.sold-out',
        '.unavailable'
    ]

    for sel in out_of_stock_selectors:
        elements = soup.select(sel)
        for element in elements:
            text = element.get_text().lower()
            if any(k in text for k in out_of_stock_keywords):
                price = self._extract_price(soup)
                return {
                    'in_stock': False, 
                    'status_text': f'Stokta yok (Element: {sel})', 
                    'price': price
                }

    # In-stock selektörlerini kontrol et
    in_stock_selectors = [
        'button[data-qa-action="add-to-cart"]',
        'button.add-to-cart-button',
        'button[aria-label*="Add to cart"]',
        'button[title*="Sepete Ekle"]',
        '.product-actions__add-to-cart-button',
        '.add-to-cart',
        '.buy-now',
        'button[type="submit"]'
    ]

    for sel in in_stock_selectors:
        elements = soup.select(sel)
        for element in elements:
            text = element.get_text().lower()
            if any(k in text for k in in_stock_keywords):
                price = self._extract_price(soup)
                return {
                    'in_stock': True, 
                    'status_text': f'Stokta mevcut (Element: {sel})', 
                    'price': price
                }

    # Genel sayfa metni analizi
    page_text = soup.get_text().lower()
    target_text = page_text
    
    if selector:
        target_elements = soup.select(selector)
        if target_elements:
            target_text = ' '.join([elem.get_text().lower() for elem in target_elements])

    # Önce out-of-stock kelimelerini kontrol et
    out_of_stock_found = any(keyword in target_text for keyword in out_of_stock_keywords)
    if out_of_stock_found:
        price = self._extract_price(soup)
        return {
            'in_stock': False, 
            'status_text': 'Stokta yok (Sayfa metninde bulundu)', 
            'price': price
        }

    # Sonra in-stock kelimelerini kontrol et
    in_stock_found = any(keyword in target_text for keyword in in_stock_keywords)
    if in_stock_found:
        price = self._extract_price(soup)
        return {
            'in_stock': True, 
            'status_text': 'Stokta mevcut (Sayfa metninde bulundu)', 
            'price': price
        }

    # Fiyat varsa muhtemelen stokta var
    price = self._extract_price(soup)
    if price != 'N/A':
        return {
            'in_stock': True, 
            'status_text': 'Muhtemelen stokta (Fiyat bulundu)', 
            'price': price
        }

    return {
        'in_stock': False, 
        'status_text': 'Stok durumu belirsiz', 
        'price': 'N/A'
    }

def _extract_price(self, soup):
    price_selectors = [
        'span.money-amount__main',
        '[data-qa-action="product-price"]',
        '.price', '.fiyat', '[class*="price"]', '[class*="fiyat"]',
        '.amount', '.cost', '[data-testid*="price"]',
        'div.product-price span',
        'span[itemprop="price"]',
        'meta[itemprop="price"]',
        '.price-current',
        '.price-now',
        '.sale-price'
    ]

    for selector in price_selectors:
        elements = soup.select(selector)
        for element in elements:
            if element.name == 'meta':
                text = element.get('content', '')
            else:
                text = element.get_text().strip()
            
            if text and (any(currency in text for currency in ['₺', '$', '€', 'TL', 'USD', 'EUR']) or any(char.isdigit() for char in text)):
                return text

    # JSON-LD structured data kontrolü
    try:
        import json
        for script in soup.find_all('script', type='application/ld+json'):
            if script.string:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get('@type') == 'Product' and item.get('offers'):
                            offers = item['offers']
                            if isinstance(offers, list) and len(offers) > 0:
                                offer = offers[0]
                            elif isinstance(offers, dict):
                                offer = offers
                            else:
                                continue
                            
                            if offer.get('price'):
                                price = offer['price']
                                currency = offer.get('priceCurrency', '')
                                return f"{price} {currency}".strip()
                elif data.get('@type') == 'Product' and data.get('offers'):
                    offers = data['offers']
                    if isinstance(offers, list) and len(offers) > 0:
                        offer = offers[0]
                    elif isinstance(offers, dict):
                        offer = offers
                    else:
                        continue
                    
                    if offer.get('price'):
                        price = offer['price']
                        currency = offer.get('priceCurrency', '')
                        return f"{price} {currency}".strip()
    except Exception as e:
        logger.debug(f"Error parsing JSON-LD for price: {e}")

    return 'N/A'

async def close(self):
    if self.session:
        await self.session.close()
```

def save_tracked_product(user_id: int, product_name: str, product_url: str,
selector: str = None, in_stock_keywords: str = None,
out_of_stock_keywords: str = None):
conn = sqlite3.connect(‘stock_tracker.db’, check_same_thread=False)
cursor = conn.cursor()
try:
cursor.execute(’’’
INSERT OR REPLACE INTO tracked_products
(user_id, product_name, product_url, selector, in_stock_keywords, out_of_stock_keywords, last_status)
VALUES (?, ?, ?, ?, ?, ?, ?)
‘’’, (user_id, product_name, product_url, selector,
in_stock_keywords, out_of_stock_keywords, ‘unknown’))
conn.commit()
return True
except Exception as e:
logger.error(f”Database error: {e}”)
return False
finally:
conn.close()

def get_tracked_products(user_id: int = None):
conn = sqlite3.connect(‘stock_tracker.db’, check_same_thread=False)
cursor = conn.cursor()
if user_id:
cursor.execute(‘SELECT * FROM tracked_products WHERE user_id = ?’, (user_id,))
else:
cursor.execute(‘SELECT * FROM tracked_products’)
products = cursor.fetchall()
conn.close()
return products

def update_product_status(product_id: int, status: str):
conn = sqlite3.connect(‘stock_tracker.db’, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(‘UPDATE tracked_products SET last_status = ?, last_checked = CURRENT_TIMESTAMP WHERE id = ?’,
(status, product_id))
conn.commit()
conn.close()

def delete_tracked_product(user_id: int, product_id: int):
conn = sqlite3.connect(‘stock_tracker.db’, check_same_thread=False)
cursor = conn.cursor()
cursor.execute(‘DELETE FROM tracked_products WHERE id = ? AND user_id = ?’, (product_id, user_id))
conn.commit()
conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
welcome_message = “””
🎉 **Stok Takip Botu’na Hoş Geldiniz!**

Bu bot, girdiğiniz ürünlerin stok durumunu takip eder ve stok değiştiğinde size bildirim gönderir.

**Komutlar:**
• `/ekle <ürün_adı> <url>`: Yeni ürün ekle
• `/liste`: Takip edilen ürünleri listele
• `/sil`: Takip edilen bir ürünü sil
• `/durum`: Tüm takip edilen ürünlerin anlık stok kontrolünü yap
• `/help`: Yardım mesajını göster

**Nasıl kullanılır:**

1. `/ekle` komutu ile ürün ekleyin. Örnek: `/ekle Zara Kazak https://www.zara.com/tr/tr/dugmeli-duz-triko-kazak-p08851180.html`
1. Bot stok durumunu otomatik olarak düzenli aralıklarla kontrol eder.
1. Stok durumu değiştiğinde size bildirim alırsınız!
   “””
   await update.message.reply_text(welcome_message, parse_mode=‘Markdown’)

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
args = context.args
if len(args) < 2:
await update.message.reply_text(
“Kullanım: `/ekle <ürün_adı> <url> [css_selector] [stok_kelimeleri_virgülle_ayrılmış] [stokta_olmayan_kelimeleri_virgülle_ayrılmış]`\n”
“Örnek: `/ekle Zara Kazak https://www.zara.com/tr/tr/dugmeli-duz-triko-kazak-p08851180.html`\n”
“Örnek (gelişmiş): `/ekle iPhone https://example.com .product-stock \"stokta,var\" \"tükendi,yok\"`”,
parse_mode=‘Markdown’
)
return

```
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
    await update.message.reply_text(f"✅ **{product_name}** takibe eklendi!\nURL: `{product_url}`", parse_mode='Markdown')

    checker = StockChecker()
    await update.message.reply_text("🔍 Anlık durum kontrol ediliyor...", parse_mode='Markdown')
    
    try:
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
                f"{status_emoji} Durum: {result['status_text']}\n"
                f"💰 Fiyat: {result['price']}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(f"❌ Kontrol başarısız: {result['error']}", parse_mode='Markdown')
    finally:
        await checker.close()
else:
    await update.message.reply_text("⚠ Ürün eklenirken hata oluştu veya bu URL zaten takip ediliyor.", parse_mode='Markdown')
```

async def list_products(update: Update, context: ContextTypes.DEFAULT_TYPE):
products = get_tracked_products(update.effective_user.id)
if not products:
await update.message.reply_text(“📋 Henüz takip edilen ürün yok.”)
return

```
message = "📋 **Takip Edilen Ürünler:**\n\n"
for product in products:
    product_id, _, name, url, _, _, _, last_status, last_checked, _ = product
    status_emoji = "✅" if last_status == 'in_stock' else "⚠" if last_status == 'out_of_stock' else "❓"
    last_checked_str = datetime.strptime(last_checked, '%Y-%m-%d %H:%M:%S').strftime('%d.%m.%Y %H:%M') if last_checked else "Bilinmiyor"
    message += f"{status_emoji} **{name}**\n"
    message += f"ID: `{product_id}`\n"
    message += f"Son kontrol: {last_checked_str}\n"
    message += f"URL: {url[:60]}...\n\n"

keyboard = [[InlineKeyboardButton("🗑 Ürün Sil", callback_data="delete_menu")]]
await update.message.reply_text(
    message,
    reply_markup=InlineKeyboardMarkup(keyboard),
    parse_mode='Markdown'
)
```

async def delete_product_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
products = get_tracked_products(query.from_user.id)

```
if not products:
    await query.edit_message_text("📋 Silinecek ürün yok.")
    return

keyboard = [
    [InlineKeyboardButton(f"🗑 {name} (ID: {product_id})", callback_data=f"delete_{product_id}")]
    for product_id, _, name, *_ in products
]
keyboard.append([InlineKeyboardButton("« Geri", callback_data="back_to_list")])
await query.edit_message_text(
    "🗑 Silinecek ürünü seçin:",
    reply_markup=InlineKeyboardMarkup(keyboard)
)
```

async def handle_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
product_id = int(query.data.split(’_’)[1])
delete_tracked_product(query.from_user.id, product_id)
await query.edit_message_text(“✅ Ürün takipten çıkarıldı.”)

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
products = get_tracked_products(update.effective_user.id)
if not products:
await update.message.reply_text(“📋 Kontrol edilecek ürün yok.”)
return

```
await update.message.reply_text("🔍 Tüm ürünlerin stok durumları kontrol ediliyor...", parse_mode='Markdown')
checker = StockChecker()

try:
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
            await update.message.reply_text(f"❌ **{name}** - Kontrol başarısız: {result['error']}", parse_mode='Markdown')

        await asyncio.sleep(1)
finally:
    await checker.close()
```

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
help_text = “””
📚 **Yardım Menüsü**

Bu bot, belirlediğiniz web sitelerindeki ürünlerin stok durumunu sizin için takip eder.

**Komut Listesi:**
• `/start`: Botu başlatır
• `/ekle <ürün_adı> <url>`: Yeni ürün ekler
• `/liste`: Takip edilen ürünleri listeler
• `/durum`: Anlık stok kontrol yapar
• `/help`: Bu yardım mesajını gösterir

**Sistem Bilgisi:**
• Bot önce Browserless API’yi dener
• Başarısız olursa direkt HTTP istekleri kullanır
• Stok değişikliklerinde bildirim gönderir
“””
await update.message.reply_text(help_text, parse_mode=‘Markdown’)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
query = update.callback_query
await query.answer()
if query.data == “delete_menu”:
await delete_product_menu(update, context)
elif query.data.startswith(“delete_”):
await handle_delete(update, context)
elif query.data == “back_to_list”:
await list_products(update, context)

async def stock_monitoring_loop(application):
checker = StockChecker()

```
try:
    while True:
        try:
            products = get_tracked_products()
            if not products:
                logger.info("No products to track. Sleeping for 5 minutes.")
                await asyncio.sleep(300)
                continue

            for product in products:
                product_id, user_id, name, url, selector, in_stock_kw, out_of_stock_kw, last_status, _, _ = product
                logger.info(f"Checking stock for product ID: {product_id}, Name: {name}")
                
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
                            logger.info(f"Sent stock notification for product ID: {product_id}")
                        except Exception as e:
                            logger.error(f"Failed to send notification: {e}")

                    update_product_status(product_id, current_status)
                    logger.info(f"Updated status for product ID: {product_id} to {current_status}")
                else:
                    logger.error(f"Stock check failed for product ID: {product_id}: {result['error']}")

                await asyncio.sleep(5)

            logger.info("Finished product check loop. Sleeping for 5 minutes.")
            await asyncio.sleep(300)
            
        except Exception as e:
            logger.error(f"Error in stock monitoring loop: {e}", exc_info=True)
            await asyncio.sleep(60)
finally:
    await checker.close()
```

def main():
init_database()
application = Application.builder().token(BOT_TOKEN).job_queue(JobQueue()).build()

```
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("ekle", add_product))
application.add_handler(CommandHandler("liste", list_products))
application.add_handler(CommandHandler("durum", check_status))
application.add_handler(CommandHandler("help", help_command))
application.add_handler(CallbackQueryHandler(button_callback))

application.job_queue.run_once(lambda context: asyncio.create_task(stock_monitoring_loop(application)), 1)

logger.info("🎉 Stok Takip Botu başlatılıyor...")
application.run_polling(poll_interval=1.0)
```

if **name** == “**main**”:
main()
