from telegram.ext import Application, CommandHandler, MessageHandler, filters
from apscheduler.schedulers.background import BackgroundScheduler
from bs4 import BeautifulSoup
import logging
import pickle
import telegram
import requests
import os

# Değişiklik: ParseMode'u buradan içe aktarıyoruz
from telegram.constants import ParseMode

class CZaraStockBot:
    STATE_STOPPED = 0
    STATE_RUNNING = 1
    STATE_PAUSED = 2

    def __init__(self):
        logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

        bot_token = os.environ.get('BOT_TOKEN')
        if not bot_token:
            raise ValueError("BOT_TOKEN ortam değişkeni ayarlanmamış! Lütfen bot token'ınızı ayarlayın.")

        self.application = Application.builder().token(bot_token).build()
        self.bot = self.application.bot

        self.datalist = []
        self.dataset = [' ', ' ', 0]
        self.insertmode = 0
        self.interval = 600

        try:
            with open('save.dat', 'rb') as f:
                self.datalist = pickle.load(f)
                f.close()
        except FileNotFoundError:
            pass

        # Handler'lar Application'a ekleniyor
        self.application.add_handler(CommandHandler('show', self.cmdshow))
        self.application.add_handler(CommandHandler('del', self.cmddel))
        self.application.add_handler(CommandHandler('delall', self.cmddelall))
        self.application.add_handler(CommandHandler('save', self.cmdsave))
        self.application.add_handler(CommandHandler('help', self.cmdhelp))
        self.application.add_handler(CommandHandler('start', self.cmdstart))
        self.application.add_handler(CommandHandler('stop', self.cmdstop))
        self.application.add_handler(CommandHandler('interval', self.cmdinterval))
        
        self.application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), self.echo))

        self.sched = BackgroundScheduler()
        self.sched.start()

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdshow(self, update, context):
        if not self.datalist:
            await context.bot.send_message(chat_id=update.effective_chat.id, text='Takip edilen ürün bulunmuyor.')
            return
        
        message_text = "Takip Edilen Ürünler:\n\n"
        for i, data in enumerate(self.datalist):
            message_text += f"{i+1}. URL: {data[0]}\n   Beden: {data[1]}\n\n"
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text)

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmddel(self, update, context):
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Silmek istediğiniz ürünün URL\'sini girin:')
        self.insertmode = 1

    def deldata(self, chat_id, url):
        deleted = False
        for i in range(len(self.datalist) - 1, -1, -1):
            if self.datalist[i][0] == url and self.datalist[i][2] == chat_id:
                del self.datalist[i]
                deleted = True
        self.insertmode = 0
        return deleted

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmddelall(self, update, context):
        self.datalist.clear()
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Tüm takip edilen ürünler silindi.')

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdsave(self, update, context):
        try:
            with open('save.dat', 'wb') as f:
                pickle.dump(self.datalist, f)
            await context.bot.send_message(chat_id=update.effective_chat.id, text='Takip listesi başarıyla kaydedildi.')
        except Exception as e:
            await context.bot.send_message(chat_id=update.effective_chat.id, text=f'Kaydetme sırasında bir hata oluştu: {e}')

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdhelp(self, update, context):
        msg = (
            '**Nasıl Kullanılır:**\n'
            '1. Zara web sitesinden takip etmek istediğiniz ürünün sayfasına gidin.\n'
            '2. Ürünün **URL\'sini** kopyalayıp sohbete yapıştırın ve gönderin.\n'
            '3. Bot "Bedeni girin:" mesajını gönderdiğinde, web sayfasından takip etmek istediğiniz **bedeni** (örneğin "KR 270" veya "EU S") kopyalayıp sohbete yapıştırın ve gönderin.\n'
            '4. Bot mevcut stok durumunu kontrol ettikten sonra ürünü takip listenize ekleyecektir.\n\n'
            '**Komutlar:**\n'
            '**/show**: Takip ettiğiniz tüm ürünleri listeler.\n'
            '**/del**: Belirli bir ürünü URL ile siler.\n'
            '**/delall**: Tüm takip edilen ürünleri siler.\n'
            '**/save**: Mevcut takip listesini dosyaya kaydeder (bot yeniden başlatıldığında kaybolmaması için).\n'
            '**/help**: Bu yardım mesajını gösterir.\n'
            '**/start**: Stok kontrolünü başlatır.\n'
            '**/stop**: Stok kontrolünü durdurur.\n'
            '**/interval**: Stok kontrol aralığını ayarlar (saniye cinsinden).'
        )
        # Değişiklik: ParseMode'u telegram.constants'dan kullanıyoruz
        await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.MARKDOWN)

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdstart(self, update, context):
        if self.datalist:
            msg = f'{self.interval} saniye aralıklarla stok kontrolü başlatılıyor.'
            self.sched.remove_all_jobs()
            self.sched.add_job(self.job_crawling, 'interval', seconds=self.interval)
            
            if not self.sched.running:
                self.sched.start()
            
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
        else:
            msg = 'Takip listeniz boş. Stok kontrolü başlatılamadı.'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdstop(self, update, context):
        if self.sched.running:
            msg = 'Stok kontrolü durduruluyor.'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)
            self.remove()
        else:
            msg = 'Stok kontrolü zaten çalışmıyor.'
            await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

    def remove(self):
        if self.sched.running:
            self.sched.remove_all_jobs()

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def cmdinterval(self, update, context):
        self.remove()
        self.insertmode = 2
        await context.bot.send_message(chat_id=update.effective_chat.id, text='Stok kontrol aralığını (saniye cinsinden) girin:')

    # Değişiklik: Fonksiyonu asenkron yapıyoruz (async def)
    async def echo(self, update, context):
        chat_id = update.effective_chat.id
        user_message = update.message.text.strip()

        if self.insertmode == 2: # Aralık ayarı modu
            try:
                new_interval = int(user_message)
                if new_interval > 0:
                    self.interval = new_interval
                    await context.bot.send_message(chat_id=chat_id, text=f'Stok kontrol aralığı {self.interval} saniyeye ayarlandı. Başlatmak için /start yazın.')
                    self.insertmode = 0 # Modu sıfırla
                else:
                    await context.bot.send_message(chat_id=chat_id, text='Geçerli bir saniye değeri girin (pozitif bir tam sayı).')
            except ValueError:
                await context.bot.send_message(chat_id=chat_id, text='Geçersiz giriş. Lütfen sadece sayı girin.')
            return

        elif user_message.startswith('http'): # URL girişi
            self.remove()

            if self.insertmode == 0: # Yeni ürün ekleme modu
                self.dataset = [' ', ' ', 0]
                self.dataset[0] = user_message
                await context.bot.send_message(chat_id=chat_id, text='Bedeni girin (örn: KR 270 veya EU S):')
            elif self.insertmode == 1: # Silme modu
                if self.deldata(chat_id, user_message):
                    await context.bot.send_message(chat_id=chat_id, text='Ürün başarıyla silindi.')
                else:
                    await context.bot.send_message(chat_id=chat_id, text='Silinecek ürün bulunamadı. URL\'yi kontrol edin.')
                self.insertmode = 0
            else:
                await context.bot.send_message(chat_id=chat_id, text='Geçersiz giriş. Lütfen yardım için /help yazın.')

        elif user_message.upper().startswith('KR') or user_message.upper().startswith('EU') or len(user_message) <= 5: # Beden girişi
            if self.dataset[0] == ' ':
                await context.bot.send_message(chat_id=chat_id, text='Önce ürünün URL\'sini girmeniz gerekiyor.')
                return

            self.dataset[1] = user_message
            self.dataset[2] = chat_id
            await context.bot.send_message(chat_id=chat_id, text=f'"{user_message}" bedeni için mevcut stok kontrol ediliyor...')
            
            # check_stock çağrısı artık await gerektirmiyor çünkü senkron bir metod
            product_name = self.check_stock(self.dataset, mode=0)

            if product_name:
                is_duplicate = False
                for item in self.datalist:
                    if item[0] == self.dataset[0] and item[1] == self.dataset[1] and item[2] == self.dataset[2]:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    self.datalist.append(self.dataset[:])
                    msg = f'**{product_name}** ({self.dataset[1]}) takip listenize eklendi. Stok kontrolünü başlatmak için /start yazın.'
                else:
                    msg = f'**{product_name}** ({self.dataset[1]}) zaten takip listenizde mevcut.'
            else:
                msg = 'Ürün eklenemedi. URL veya beden hatalı olabilir ya da ürün stokta olmayabilir. Lütfen tekrar deneyin ya da yardım için /help yazın.'
            
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN)
            self.insertmode = 0

        else:
            await context.bot.send_message(chat_id=chat_id, text='Anlamadım. Yardım için /help yazın.')
            self.insertmode = 0

    def job_crawling(self):
        # Bu metod hala senkron, içindeki mesaj gönderme işlemleri kendi bot nesnesi üzerinden yapılır.
        for data in self.datalist:
            self.check_stock(data, mode=1)

    def check_stock(self, data, mode=1):
        url = data[0]
        size = data[1]
        user_chat_id = data[2]
        product_name = ''

        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.88 Safari/537.36'
            }
            html = requests.get(url, headers=headers, timeout=10)
            html.raise_for_status()

            soup = BeautifulSoup(html.text, 'html.parser')
            
            name_tag = soup.find('h1', class_='product-detail-info__name') 
            if not name_tag:
                name_tag = soup.find('h1', {'data-qa-action': 'product-detail-title'})
            if not name_tag:
                name_tag = soup.find('h1')
            
            if name_tag:
                product_name = name_tag.get_text(strip=True)
            else:
                logging.warning(f"Ürün adı bulunamadı: {url}")

            tag = soup.find('option', value=size)
            if not tag:
                tag = soup.find('span', string=size)
            if not tag:
                tag = soup.find(lambda tag: tag.name in ['option', 'span', 'div', 'button'] and size in tag.get_text())


            if tag:
                is_disabled = False
                if 'disabled' in tag.attrs:
                    is_disabled = True

                if is_disabled:
                    if mode == 0:
                        # Bu mesaj gönderme işlemi senkron fonksiyonda olduğu için await kullanmıyoruz
                        self.bot.send_message(chat_id=user_chat_id, text=f'**{product_name or "Ürün"}** ({size}) şu anda stokta yok. Stok geldiğinde bildireceğim.', parse_mode=ParseMode.MARKDOWN)
                else:
                    # Bu mesaj gönderme işlemi senkron fonksiyonda olduğu için await kullanmıyoruz
                    self.bot.send_message(chat_id=user_chat_id, text=f'**{product_name or "Ürün"}** ({size}) için **STOK BULUNDU!**\nÜrün linki: {url}', parse_mode=ParseMode.MARKDOWN)
            else:
                self.bot.send_message(chat_id=user_chat_id, text=f'Belirtilen beden (**{size}**) bulunamadı veya ürün yapısı değişmiş olabilir. Lütfen URL\'yi ve bedeni kontrol edin. URL: {url}', parse_mode=ParseMode.MARKDOWN)

        except requests.exceptions.HTTPError as e:
            logging.error(f"HTTP Hatası ({e.response.status_code}) URL: {url} - {e}")
            self.bot.send_message(chat_id=user_chat_id, text=f'Ürüne erişirken HTTP hatası oluştu ({e.response.status_code}). URL\'yi kontrol edin: {url}')
        except requests.exceptions.ConnectionError as e:
            logging.error(f"Bağlantı Hatası URL: {url} - {e}")
            self.bot.send_message(chat_id=user_chat_id, text=f'Ürüne bağlanırken hata oluştu. İnternet bağlantınızı veya URL\'yi kontrol edin: {url}')
        except requests.exceptions.Timeout as e:
            logging.error(f"Zaman Aşımı Hatası URL: {url} - {e}")
            self.bot.send_message(chat_id=user_chat_id, text=f'Ürüne erişim zaman aşımına uğradı. URL\'yi kontrol edin veya daha sonra tekrar deneyin: {url}')
        except requests.exceptions.RequestException as e:
            logging.error(f"Genel İstek Hatası URL: {url} - {e}")
            self.bot.send_message(chat_id=user_chat_id, text=f'Ürüne erişirken beklenmeyen bir hata oluştu: {e}. Lütfen URL\'yi kontrol edin: {url}')
        except Exception as e:
            logging.error(f"Stok kontrolü sırasında beklenmeyen hata: {e} for URL: {url}")
            self.bot.send_message(chat_id=user_chat_id, text=f'Stok kontrolü sırasında bir hata oluştu: {e}. Lütfen yardım için /help yazın.')

        return product_name

# Botun başlatılması
if __name__ == '__main__':
    jarabot = CZaraStockBot()
    # run_polling asenkron bir çağrıdır, bu yüzden doğrudan await gerektiren bir ortamda olmalıyız.
    # python-telegram-bot bunu sizin için yönetir.
    jarabot.application.run_polling()
