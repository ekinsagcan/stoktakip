import asyncio
import logging
import os
import sqlite3
from datetime import datetime
from typing import Dict, List

from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, JobQueue # JobQueue buraya eklendi


# import aiohttp # Artık doğrudan aiohttp kullanmayacağımız için yorum satırı yapıldı veya kaldırılabilir.
from bs4 import BeautifulSoup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# Selenium importları (RemoteWebDriver için gerekli olanlar)
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver # ÖNEMLİ DEĞİŞİKLİK
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException, SessionNotCreatedException

# Ortam değişkenlerinden bot tokenını al
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set.")

# Railway'deki Browserless V1 hizmetinizin URL'si
# Bu URL'yi Railway dashboard'unuzdaki Browserless servisinden alacaksınız.
# Genellikle Browserless template'i ile oluşturduğunuz servisin "Variables" kısmında HOST veya BROWSERLESS_URL olarak bulunur.
# Uygulamanızı Railway'e dağıtırken bu ortam değişkenini ayarlamanız GEREKİR.
BROWSERLESS_URL = os.getenv("BROWSERLESS_URL")
if not BROWSERLESS_URL:
    raise ValueError("BROWSERLESS_URL environment variable not set. Please get it from your Railway Browserless service.")


# Logging yapılandırması
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    ''')
    conn.commit()
    conn.close()

# Stok durumu kontrolü (Selenium RemoteWebDriver ile güncellendi)
class StockChecker:
    def __init__(self):
        self.chrome_options = Options()
        # Browserless zaten headless çalıştığı için burada tekrar '--headless' eklemeye gerek yok.
        # Ancak güvenlik ve performans için diğer argümanları tutmak iyi bir fikir.
        self.chrome_options.add_argument('--no-sandbox') # Güvenlik kısıtlamalarını kaldır (Linux konteynerler için gerekli)
        self.chrome_options.add_argument('--disable-dev-shm-usage') # /dev/shm kullanımını devre dışı bırak (Linux tabanlı sistemler için)
        self.chrome_options.add_argument('--disable-gpu') # GPU hızlandırmayı kapat (bazı ortamlar için gerekli)
        self.chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
        self.chrome_options.add_argument('--window-size=1920,1080') # Pencere boyutu (headless için önemli)
        self.chrome_options.add_argument('--ignore-certificate-errors') # Sertifika hatalarını yok say
        self.chrome_options.add_argument('--allow-running-insecure-content') # Güvenli olmayan içeriklere izin ver

    async def check_stock(self, url: str, selector: str = None, 
                         in_stock_keywords: List[str] = None, 
                         out_of_stock_keywords: List[str] = None) -> Dict:
        driver = None
        try:
            # ÖNEMLİ DEĞİŞİKLİK: Local Selenium yerine Browserless üzerinden bağlan
            # Browserless v1 template'i genellikle /webdriver uç noktasını sunar.
            driver = RemoteWebDriver(
                command_executor=f"{BROWSERLESS_URL}/webdriver",
                options=self.chrome_options
            )
            
            driver.get(url)

            # Sayfanın tamamen yüklenmesini beklemek için daha akıllı stratejiler
            try:
                # Body elementinin veya belirli bir anahtar elementin görünmesini bekleyin.
                # Zara için fiyat elementini beklemek iyi bir başlangıç olabilir.
                WebDriverWait(driver, 25).until( # Bekleme süresini biraz artırdık
                    EC.presence_of_element_located((By.TAG_NAME, 'body')) or
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'span.money-amount__main')) # Zara fiyat seçicisi
                )
                await asyncio.sleep(3) # Ek bir bekleme: JavaScript'in bitmesi için kısa bir süre bekleme
            except TimeoutException:
                logger.warning(f"Initial page load timeout for {url}, trying to proceed with current DOM.")

            # Sayfanın tüm HTML'ini al (JavaScript ile oluşturulmuş haliyle)
            html = driver.page_source
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
        except TimeoutException:
            logger.error(f"Selenium Timeout waiting for page elements for {url}")
            return {'success': False, 'error': 'Timeout waiting for page elements or content.'}
        except SessionNotCreatedException as e:
            logger.error(f"Failed to create Selenium session with Browserless for {url}: {e}. Check BROWSERLESS_URL and Browserless logs.")
            return {'success': False, 'error': f'Browserless bağlantı hatası: {e}'}
        except WebDriverException as e:
            logger.error(f"Selenium WebDriver error accessing {url} via Browserless: {e}")
            return {'success': False, 'error': f'WebDriver hatası: {e}'}
        except Exception as e:
            logger.error(f"General error checking stock with Selenium/Browserless for {url}: {e}", exc_info=True)
            return {'success': False, 'error': str(e)}
        finally:
            if driver:
                driver.quit() # Tarayıcı oturumunu kapatmayı unutma

    def _analyze_stock_status(self, soup, selector=None, 
                            in_stock_keywords=None, out_of_stock_keywords=None):
        default_in_stock = ['sepete ekle', 'add to cart', 'in stock', 'stokta', 'satın al', 'hemen al', 'ürün sepetinizde']
        default_out_of_stock = ['stokta yok', 'tükendi', 'mevcut değil', 'out of stock', 'sold out', 'unavailable', 'tükenmek üzere', 'coming soon', 'notify me', 'beden tükenmiş']
        
        in_stock_keywords = [k.lower() for k in (in_stock_keywords or default_in_stock)]
        out_of_stock_keywords = [k.lower() for k in (out_of_stock_keywords or default_out_of_stock)]
        
        in_stock_elements_selectors = [
            'button[data-qa-action="add-to-cart"]', # Zara'nın sepet butonu
            'button.add-to-cart-button', 
            'button[aria-label*="Add to cart"]',
            'button[title*="Sepete Ekle"]',
            '.product-actions__add-to-cart-button' # Zara'da gördüğüm bir başka potansiyel
        ]

        out_of_stock_elements_selectors = [
            '.product-availability__message--out-of-stock', # Zara'nın "stokta yok" mesajı
            '.availability-status--out-of-stock', 
            '.stock-error-message',
            '.size-selector__size--out-of-stock', # Beden seçici içinde stokta yok bilgisi
            '.stock-info-text',
            '[data-qa-action="unavailable-product"]', # Zara'da stokta olmayan ürün için
            'div.product-actions__disabled-message' # Zara'da "tükendi" mesajı için
        ]

        # Element bazlı kontrol (daha güvenilir)
        for sel in out_of_stock_elements_selectors:
            if soup.select_one(sel): # Sadece elementin varlığına bakıyoruz
                text = soup.select_one(sel).get_text().lower()
                if any(k in text for k in out_of_stock_keywords):
                    price = self._extract_price(soup)
                    return {'in_stock': False, 'status_text': f'Stokta yok (Element: {sel}, Metin: {text[:30]}...)', 'price': price}

        for sel in in_stock_elements_selectors:
            if soup.select_one(sel):
                text = soup.select_one(sel).get_text().lower()
                if any(k in text for k in in_stock_keywords):
                    price = self._extract_price(soup)
                    return {'in_stock': True, 'status_text': f'Stokta mevcut (Element: {sel}, Metin: {text[:30]}...)', 'price': price}


        # Genel sayfa metni kontrolü (daha az güvenilir)
        page_text = soup.get_text().lower()
        target_text = page_text
        if selector:
            target_elements = soup.select(selector)
            if target_elements:
                target_text = ' '.join([elem.get_text().lower() for elem in target_elements])
            
        out_of_stock_found = any(keyword in target_text for keyword in out_of_stock_keywords)
        if out_of_stock_found:
            price = self._extract_price(soup)
            return {'in_stock': False, 'status_text': 'Stokta yok (Genel sayfa metninde bulundu)', 'price': price}

        in_stock_found = any(keyword in target_text for keyword in in_stock_keywords)
        if in_stock_found:
            price = self._extract_price(soup)
            return {'in_stock': True, 'status_text': 'Stokta mevcut (Genel sayfa metninde bulundu)', 'price': price}
        
        # Son çare: Fiyat varsa muhtemelen stokta varsay
        price = self._extract_price(soup)
        if price != 'N/A':
            return {'in_stock': True, 'status_text': 'Muhtemelen stokta (Fiyat bulundu ama kesin değil)', 'price': price}
        
        return {'in_stock': False, 'status_text': 'Stok durumu belirsiz (Hiçbir gösterge bulunamadı)', 'price': 'N/A'}

    def _extract_price(self, soup):
        price_selectors = [
            'span.money-amount__main', # Zara için temel fiyat seçici
            '[data-qa-action="product-price"]',
            '.price', '.fiyat', '[class*="price"]', '[class*="fiyat"]',
            '.amount', '.cost', '[data-testid*="price"]',
            'div.product-price span',
            'span[itemprop="price"]', # Schema.org markup
            'meta[itemprop="price"]' # Schema.org markup in meta tag
        ]
        
        for selector in price_selectors:
            elements = soup.select(selector)
            for element in elements:
                text = element.get_text().strip()
                if any(currency in text for currency in ['₺', '$', '€', 'TL', 'USD', 'EUR']) or any(char.isdigit() for char in text):
                    return text
        
        # JSON-LD (Schema.org) verisinden fiyat çekme
        try:
            import json
            for script in soup.find_all('script', type='application/ld+json'):
                data = json.loads(script.string)
                if isinstance(data, list): # Bazen JSON-LD bir liste olabilir
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
            logger.debug(f"Error parsing JSON-LD for price: {e}")

        return 'N/A'

# ... (Veritabanı işlemleri, bot komutları ve main fonksiyonu aynı kalacak)
# Veritabanı işlemleri (değişmedi)
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
        logger.error(f"Database error: {e}")
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

# Bot komutları (küçük iyileştirmelerle)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_message = """
    🎉 **Stok Takip Botu'na Hoş Geldiniz!**

    Bu bot, girdiğiniz ürünlerin stok durumunu takip eder ve stok değiştiğinde size bildirim gönderir.

    **Komutlar:**
    • `/ekle <ürün_adı> <url>`: Yeni ürün ekle
    • `/liste`: Takip edilen ürünleri listele
    • `/sil`: Takip edilen bir ürünü sil
    • `/durum`: Tüm takip edilen ürünlerin anlık stok kontrolünü yap
    • `/help`: Yardım mesajını göster

    **Nasıl kullanılır:**
    1. `/ekle` komutu ile ürün ekleyin. Örnek: `/ekle Zara Kazak https://www.zara.com/tr/tr/dugmeli-duz-triko-kazak-p08851180.html`
    2. Bot stok durumunu otomatik olarak düzenli aralıklarla kontrol eder.
    3. Stok durumu değiştiğinde (özellikle "stokta yok"tan "stokta var"a döndüğünde) size bildirim alırsınız!
    """
    await update.message.reply_text(welcome_message, parse_mode='Markdown')

async def add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "Kullanım: `/ekle <ürün_adı> <url> [css_selector] [stok_kelimeleri_virgülle_ayrılmış] [stokta_olmayan_kelimeleri_virgülle_ayrılmış]`\n"
            "Örnek: `/ekle Zara Kazak https://www.zara.com/tr/tr/dugmeli-duz-triko-kazak-p08851180.html`\n"
            "Örnek (gelişmiş): `/ekle iPhone https://example.com .product-stock \"stokta,var\" \"tükendi,yok\"`\n\n"
            "CSS Seçicisi ve kelimeler opsiyoneldir. Bot varsayılan olarak en yaygın durumları kontrol etmeye çalışır."
            "Ancak, belirli bir site için daha doğru sonuçlar almak isterseniz bu parametreleri kullanabilirsiniz.",
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
        await update.message.reply_text(f"✅ **{product_name}** takibe eklendi!\nURL: `{product_url}`", parse_mode='Markdown')
        
        checker = StockChecker()
        await update.message.reply_text("🔍 Anlık durum kontrol ediliyor...", parse_mode='Markdown')
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
            await update.message.reply_text(f"⛔ Kontrol başarısız: {result['error']}", parse_mode='Markdown')
    else:
        await update.message.reply_text("⚠ Ürün eklenirken hata oluştu veya bu URL zaten takip ediliyor.", parse_mode='Markdown')

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
        message += f"{status_emoji} **{name}**\n"
        message += f"ID: `{product_id}`\n"
        message += f"Son kontrol: {last_checked_str}\n"
        message += f"URL: {url[:60]}...\n\n" # URL'yi biraz daha uzun gösterebiliriz

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

    await update.message.reply_text("🔍 Tüm ürünlerin stok durumları kontrol ediliyor...", parse_mode='Markdown')
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
            await update.message.reply_text(f"⛔ **{name}** - Kontrol başarısız: {result['error']}", parse_mode='Markdown')
        
        await asyncio.sleep(1) # Her kontrol arasında kısa bekleme

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    📚 **Yardım Menüsü**

    Bu bot, belirlediğiniz web sitelerindeki ürünlerin stok durumunu sizin için takip eder.

    **Komut Listesi:**
    • `/start`: Botu başlatır ve hoş geldin mesajını gösterir.
    • `/ekle <ürün_adı> <url>`: Yeni bir ürün eklemenizi sağlar. Örneğin: `/ekle Telefon https://www.samsung.com/telefon`
       * *Gelişmiş Kullanım*: `/ekle <ürün_adı> <url> [css_selector] [stok_kelimeleri_virgülle_ayrılmış] [stokta_olmayan_kelimeleri_virgülle_ayrılmış]`
         * `css_selector`: Ürünün stok durumunu veya fiyatını içeren belirli bir HTML elementi. Örneğin: `.stock-status` veya `div#product-info`
         * `stok_kelimeleri`: Stokta olduğunu gösteren virgülle ayrılmış kelimeler. Örneğin: `"stokta,mevcut,sepete ekle"`
         * `stokta_olmayan_kelimeler`: Stokta olmadığını gösteren virgülle ayrılmış kelimeler. Örneğin: `"tükendi,stokta yok,gelince haber ver"`
         * *Bu opsiyonel parametreler, botun sitenin yapısına göre daha doğru sonuçlar vermesini sağlar.*
    • `/liste`: Takip ettiğiniz tüm ürünleri listeler, ID'leri ve son kontrol durumları ile birlikte.
    • `/sil`: Takip listenizden bir ürünü ID'sine göre silmenizi sağlar. `/liste` komutundan ID'yi alabilirsiniz.
    • `/durum`: Botun anlık olarak tüm takip ettiğiniz ürünlerin stok durumunu kontrol etmesini sağlar.
    • `/help`: Bu yardım mesajını gösterir.

    **Otomatik Takip:**
    Bot, eklediğiniz ürünleri arka planda düzenli aralıklarla otomatik olarak kontrol eder. Bir ürünün "stokta yok" durumundan "stokta var" durumuna geçtiğini tespit ettiğinde size anında bildirim gönderir.

    Herhangi bir sorun yaşarsanız veya yeni bir özellik öneriniz olursa lütfen bana bildirin!
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Query'yi cevapla, yoksa kullanıcıda "yükleniyor" kalır
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
            if not products:
                logger.info("No products to track. Sleeping for 5 minutes.")
                await asyncio.sleep(300)
                continue

            for product in products:
                product_id, user_id, name, url, selector, in_stock_kw, out_of_stock_kw, last_status, _, _ = product
                logger.info(f"Checking stock for product ID: {product_id}, Name: {name}, URL: {url}")
                result = await checker.check_stock(
                    url, 
                    selector,
                    in_stock_kw.split(',') if in_stock_kw else None,
                    out_of_stock_kw.split(',') if out_of_stock_kw else None
                )
                
                if result['success']:
                    current_status = 'in_stock' if result['in_stock'] else 'out_of_stock'
                    
                    # Sadece durum değiştiyse ve "stokta yok"tan "stokta var"a geçişse bildirim gönder
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
                            logger.info(f"Sent stock notification for product ID: {product_id} to user {user_id}")
                        except Exception as e:
                            logger.error(f"Failed to send notification for product ID: {product_id} to user {user_id}: {e}")
                    
                    update_product_status(product_id, current_status)
                    logger.info(f"Updated status for product ID: {product_id} to {current_status}. Last status was {last_status}.")
                else:
                    logger.error(f"Stock check failed for product ID: {product_id} ({name}): {result['error']}")
                
                await asyncio.sleep(5)  # Her ürün kontrolü arasında 5 saniye bekle
            
            logger.info("Finished one full product check loop. Sleeping for 5 minutes before next loop.")
            await asyncio.sleep(300)  # Tüm ürünler kontrol edildikten sonra 5 dakika bekle
        except Exception as e:
            logger.critical(f"Critical error in stock monitoring loop: {e}", exc_info=True)
            await asyncio.sleep(60)  # Ciddi bir hata durumunda 1 dakika bekle

# ... (Diğer tüm kodlar aynı kalacak)

def main():
    init_database()
    # ÖNEMLİ DÜZELTME: JobQueue nesnesi oluşturularak job_queue metoduna verildi.
    # JobQueue'yi etkinleştirmek için JobQueue() nesnesi parametre olarak verilmeli
    application = Application.builder().token(BOT_TOKEN).job_queue(JobQueue()).build() 

    # Komut handler'ları
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ekle", add_product))
    application.add_handler(CommandHandler("liste", list_products))
    application.add_handler(CommandHandler("durum", check_status))
    application.add_handler(CommandHandler("help", help_command))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(button_callback))

    # Stok kontrol döngüsünü başlat
    # Arka plan görevi olarak çalıştırılmalı
    application.job_queue.run_once(lambda context: asyncio.create_task(stock_monitoring_loop(application)), 1) # Bot başlatıldıktan hemen sonra başlat

    logger.info("🎉 Stok Takip Botu başlatılıyor...")
    application.run_polling(poll_interval=1.0) # Daha hızlı polling için interval düşürülebilir

if __name__ == "__main__":
    main()

