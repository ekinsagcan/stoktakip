from telegram.ext import Updater, CommandHandler, MessageHandler, filters # 'Filters' -> 'filters' olarak değiştirildi
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import logging
import pickle
import telegram
import requests
import os # Ortam değişkeni için

class CZaraStockBot:
    STATE_STOPPED = 0
    STATE_RUNNING = 1
    STATE_PAUSED = 2

    def __init__(self):
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

        # Token'ı ortam değişkeninden al
        bot_token = os.environ.get('BOT_TOKEN')
        if not bot_token:
            raise ValueError("BOT_TOKEN ortam değişkeni ayarlanmamış! Lütfen bot token'ınızı ayarlayın.")

        self.updater = Updater(token=bot_token, use_context=True) # use_context=True eklendi
        self.bot = telegram.Bot(token=bot_token)

        self.datalist = []
        self.dataset = [' ', ' ', 0]
        self.insertmode = 0
        self.interval = 600

        try:
            with open('save.dat', 'rb') as f:
                self.datalist = pickle.load(f)
                f.close()
        except FileNotFoundError:
            pass # save.dat dosyası yoksa sessizce devam et

        self.dispatcher = self.updater.dispatcher
        self.dispatcher.add_handler(CommandHandler('show', self.cmdshow))
        self.dispatcher.add_handler(CommandHandler('del', self.cmddel))
        self.dispatcher.add_handler(CommandHandler('delall', self.cmddelall))
        self.dispatcher.add_handler(CommandHandler('save', self.cmdsave))
        self.dispatcher.add_handler(CommandHandler('help', self.cmdhelp))
        self.dispatcher.add_handler(CommandHandler('start', self.cmdstart))
        self.dispatcher.add_handler(CommandHandler('stop', self.cmdstop))
        self.dispatcher.add_handler(CommandHandler('interval', self.cmdinterval))
        self.updater.start_polling()

        # 'Filters' yerine 'filters' kullanıldı
        echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.echo)
        self.dispatcher.add_handler(echo_handler)

        self.sched = BackgroundScheduler()
        self.sched.start()

    def cmdshow(self, update, context): # context parametresi eklendi
        if not self.datalist: # len(self.datalist) == 0 yerine
            context.bot.send_message(chat_id=update.effective_chat.id, text='Takip edilen ürün bulunmuyor.')
            return
        
        message_text = "Takip Edilen Ürünler:\n\n"
        for i, data in enumerate(self.datalist):
            message_text += f"{i+1}. URL: {data[0]}\n   Beden: {data[1]}\n\n"
        context.bot.send_message(chat_id=update.effective_chat.id, text=message_text)


    def cmddel(self, update, context): # context parametresi eklendi
        context.bot.send_message(chat_id=update.effective_chat.id, text='Silmek istediğiniz ürünün URL\'sini girin:')
        self.insertmode = 1

    def deldata(self, chat_id, url):
        deleted = False
        # Datalist'i tersine döngü ile gezmek, silme işlemi sırasında indeks kaymalarını önler.
        for i in range(len(self.datalist) - 1, -1, -1):
            if self.datalist[i][0] == url and self.datalist[i][2] == chat_id:
                del self.datalist[i]
                deleted = True
        self.insertmode = 0
        return deleted

    def cmddelall(self, update, context): # context parametresi eklendi
        self.datalist.clear()
        context.bot.send_message(chat_id=update.effective_chat.id, text='Tüm takip edilen ürünler silindi.')

    def cmdsave(self, update, context): # context parametresi eklendi
        try:
            with open('save.dat', 'wb') as f:
                pickle.dump(self.datalist, f)
            context.bot.send_message(chat_id=update.effective_chat.id, text='Takip listesi başarıyla kaydedildi.')
        except Exception as e:
            context.bot.send_message(chat_id=update.effective_chat.id, text=f'Kaydetme sırasında bir hata oluştu: {e}')

    def cmdhelp(self, update, context): # context parametresi eklendi
        msg = (
            '**Nasıl Kullanılır:**\n'
            '1. Zara web sitesinden takip etmek istediğiniz ürünün sayfasına gidin.\n'
            '2. Ürünün **URL\'sini** kopyalayıp sohbete yapıştırın ve gönderin.\n'
            '3. Bot "Bedeni girin:" mesajını gönderdiğinde, web sayfasından takip etmek istediğiniz **bedeni** (örneğin "KR 270") kopyalayıp sohbete yapıştırın ve gönderin.\n'
            '4. Bot mevcut stok durumunu kontrol ettikten sonra ürünü takip listenize ekleyecektir.\n\n'
            '**Komutlar:**\n'
            '**/show**: Takip ettiğiniz tüm ürünleri listeler.\n'
            '**/del**: Belirli bir ürünü URL ve bedenle siler.\n'
            '**/delall**: Tüm takip edilen ürünleri siler.\n'
            '**/save**: Mevcut takip listesini dosyaya kaydeder (bot yeniden başlatıldığında kaybolmaması için).\n'
            '**/help**: Bu yardım mesajını gösterir.\n'
            '**/start**: Stok kontrolünü başlatır.\n'
            '**/stop**: Stok kontrolünü durdurur.\n'
            '**/interval**: Stok kontrol aralığını ayarlar (saniye cinsinden).'
        )
        context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=telegram.ParseMode.MARKDOWN)

    def cmdstart(self, update, context): # context parametresi eklendi
        if self.datalist:
            msg = f'{self.interval} saniye aralıklarla stok kontrolü başlatılıyor.'
            self.sched.remove_all_jobs() # Önceki tüm işleri temizle
            self.sched.add_job(self.job_crawling, 'interval', seconds=self.interval)
            # Zamanlayıcı zaten çalışıyorsa durdurup yeniden başlatmak yerine, sadece işi ekleyip emin olmak için resume diyebiliriz.
            if not self.sched.running:
                self.sched.start()
            context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        else:
            msg = 'Takip listeniz boş. Stok kontrolü başlatılamadı.'
            context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

    def cmdstop(self, update, context): # context parametresi eklendi
        if self.sched.running: # self.sched.state == self.STATE_RUNNING yerine
            msg = 'Stok kontrolü durduruluyor.'
            context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
            self.remove()
        else:
            msg = 'Stok kontrolü zaten çalışmıyor.'
            context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

    def remove(self):
        if self.sched.running:
            self.sched.remove_all_jobs()
            # Eğer başka bir iş yoksa zamanlayıcıyı tamamen durdurmak daha mantıklı olabilir
            # self.sched.shutdown(wait=False) # Eğer tüm işler kaldırıldıktan sonra tamamen durdurmak isterseniz

    def cmdinterval(self, update, context): # context parametresi eklendi
        self.remove()
        self.insertmode = 2
        context.bot.send_message(chat_id=update.effective_chat.id, text='Stok kontrol aralığını (saniye cinsinden) girin:')

    def echo(self, update, context): # context parametresi eklendi
        chat_id = update.effective_chat.id
        user_message = update.message.text.strip()

        if self.insertmode == 2: # Aralık ayarı modu
            try:
                new_interval = int(user_message)
                if new_interval > 0:
                    self.interval = new_interval
                    context.bot.send_message(chat_id=chat_id, text=f'Stok kontrol aralığı {self.interval} saniyeye ayarlandı. Başlatmak için /start yazın.')
                    self.insertmode = 0 # Modu sıfırla
                else:
                    context.bot.send_message(chat_id=chat_id, text='Geçerli bir saniye değeri girin (pozitif bir tam sayı).')
            except ValueError:
                context.bot.send_message(chat_id=chat_id, text='Geçersiz giriş. Lütfen sadece sayı girin.')
            return # İşlemi tamamla

        elif user_message.startswith('http'): # URL girişi
            self.remove() # URL girişi yapıldığında mevcut job'ları durdur

            if self.insertmode == 0: # Yeni ürün ekleme modu
                self.dataset = [' ', ' ', 0] # Her zaman yeni bir dataset başlat
                self.dataset[0] = user_message
                context.bot.send_message(chat_id=chat_id, text='Bedeni girin (örn: KR 270):')
                self.insertmode = 0 # Modu hala URL/Beden girişi için sıfırda tut
            elif self.insertmode == 1: # Silme modu
                if self.deldata(chat_id, user_message):
                    context.bot.send_message(chat_id=chat_id, text='Ürün başarıyla silindi.')
                else:
                    context.bot.send_message(chat_id=chat_id, text='Silinecek ürün bulunamadı. URL\'yi kontrol edin.')
                self.insertmode = 0 # Modu sıfırla
            else: # Beklenmedik durum
                context.bot.send_message(chat_id=chat_id, text='Geçersiz giriş. Lütfen yardım için /help yazın.')

        elif user_message.upper().startswith('KR') or user_message.upper().startswith('EU'): # Beden girişi (KR veya EU ile başlayan)
            if self.dataset[0] == ' ': # URL girilmeden beden girilmişse
                context.bot.send_message(chat_id=chat_id, text='Önce ürünün URL\'sini girmeniz gerekiyor.')
                return

            self.dataset[1] = user_message
            self.dataset[2] = chat_id
            context.bot.send_message(chat_id=chat_id, text=f'{user_message} için mevcut stok kontrol ediliyor...')
            
            product_name = self.check_stock(self.dataset, mode=0) # Yeni eklerken sadece kontrol et, bildirim gönderme

            if product_name: # Ürün adı döndüyse, yani URL geçerliyse
                # Duplicate check: Aynı URL ve bedene sahip ürün zaten var mı?
                is_duplicate = False
                for item in self.datalist:
                    if item[0] == self.dataset[0] and item[1] == self.dataset[1] and item[2] == self.dataset[2]:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    self.datalist.append(self.dataset[:]) # dataset'in bir kopyasını ekle
                    msg = f'**{product_name}** ({self.dataset[1]}) takip listenize eklendi. Stok kontrolünü başlatmak için /start yazın.'
                else:
                    msg = f'**{product_name}** ({self.dataset[1]}) zaten takip listenizde mevcut.'
            else:
                msg = 'Ürün eklenemedi. URL veya beden hatalı olabilir. Lütfen tekrar deneyin ya da yardım için /help yazın.'
            
            context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=telegram.ParseMode.MARKDOWN)
            self.insertmode = 0 # Modu sıfırla

        else: # Tanınmayan diğer metin girişleri
            context.bot.send_message(chat_id=chat_id, text='Anlamadım. Yardım için /help yazın.')
            self.insertmode = 0 # Modu sıfırla

    def job_crawling(self):
        # Bu metod zamanlayıcı tarafından çağrıldığında, bot ve context nesnelerine doğrudan erişimi olmaz.
        # Bu yüzden self.bot'u kullanmalıyız.
        for data in self.datalist:
            self.check_stock(data, mode=1) # Periyodik kontrol modu

    def check_stock(self, data, mode=1):
        url = data[0]
        size = data[1]
        user_chat_id = data[2]
        product_name = ''

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'
            }
            html = requests.get(url, headers=headers, timeout=10) # Timeout eklendi
            html.raise_for_status() # HTTP hataları için istisna fırlatır

            soup = BeautifulSoup(html.text, 'html.parser')
            
            # Ürün adını bulmaya çalış
            name_tag = soup.find('h1', class_='product-detail-info__name') # Zara için yaygın bir etiket
            if not name_tag:
                name_tag = soup.find('h1') # Genel h1 etiketi
            
            if name_tag:
                product_name = name_tag.get_text(strip=True)
            
            # Beden etiketini bulmaya çalış
            # Zara'nın HTML yapısı sık değişebilir. Genellikle <select> içindeki <option> etiketleri kullanılır.
            # Örneğin: <option value="BEDEN_DEĞERİ" data-is-available="true/false">Beden Adı</option>
            # Veya düğmeler: <button data-size-value="BEDEN_DEĞERİ" data-stock-status="in-stock/out-of-stock">Beden Adı</button>
            # Bu örnekte 'value' özniteliğine bakılıyor, bu Zara için hala geçerli olabilir.
            tag = soup.find(value=size) 
            
            # Alternatif beden bulma yöntemleri (Zara değişirse denenebilir):
            # tag = soup.find('span', text=size) # Bedeni metin olarak arama
            # tag = soup.find('button', {'data-size-name': size}) # Eğer beden bilgisi data özniteliğinde ise

            if tag:
                is_disabled = False
                # `disabled` özniteliği var mı kontrol et
                if 'disabled' in tag.attrs:
                    is_disabled = True
                # Veya 'data-is-available', 'data-stock-status' gibi öznitelikleri kontrol et
                # Örneğin: if tag.get('data-is-available') == 'false':
                # Örneğin: if tag.get('data-stock-status') == 'out-of-stock':

                if is_disabled:
                    if mode == 0: # Yeni ekleme anında stokta yoksa
                        self.bot.send_message(chat_id=user_chat_id, text=f'**{product_name}** ({size}) şu anda stokta yok.', parse_mode=telegram.ParseMode.MARKDOWN)
                else: # Stokta varsa
                    self.bot.send_message(chat_id=user_chat_id, text=f'**{product_name}** ({size}) için stok bulundu!\nÜrün linki: {url}', parse_mode=telegram.ParseMode.MARKDOWN)
            else:
                self.bot.send_message(chat_id=user_chat_id, text=f'Belirtilen beden ({size}) bulunamadı veya ürün yapısı değişmiş olabilir. URL: {url}', parse_mode=telegram.ParseMode.MARKDOWN)

        except requests.exceptions.RequestException as e:
            logging.error(f"URL'ye erişim hatası {url}: {e}")
            if mode == 1: # Periyodik kontrolde hata olursa bildir
                 self.bot.send_message(chat_id=user_chat_id, text=f'URL\'ye erişim hatası: {url}. Lütfen URL\'yi kontrol edin. Hata: {e}')
        except Exception as e:
            logging.error(f"Stok kontrolü sırasında beklenmeyen hata: {e}")
            if mode == 1: # Periyodik kontrolde hata olursa bildir
                self.bot.send_message(chat_id=user_chat_id, text=f'Stok kontrolü sırasında bir hata oluştu: {e}. Lütfen yardım için /help yazın.')

        return product_name

jarabot = CZaraStockBot()
