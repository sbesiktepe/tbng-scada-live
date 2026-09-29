# TBNG SCADA Live — acil durum canlı görüntüleyici

Ana sistem (scada2.tbngltd.com, yerel sunucu) erişilemediğinde — örneğin fiber koptuğunda —
bir bulut sunucusunda **tek komutla** ayağa kalkan, yalnızca **anlık değerleri** gösteren
yedek arayüz.

- Cihazları (ELGAS sayaçları ve Robustel'e geçmiş üretim cihazları) **doğrudan Modbus ile
  okur** (yalnızca Function 03; sahaya hiçbir şey yazılmaz).
- Veritabanı yok, geçmiş yok, alarm yok. Değerler sadece bellekte tutulur.
- Tek bir ortak kullanıcı (Caddy basic auth, HTTPS). Herkes sadece okur.
- Eski Cinterion modemlerle çalışan kuyular burada **görünmez**: onlar yalnızca ana
  sunucuya rapor gönderir.

## Kurulum (bulut sunucusu)

```bash
git clone https://github.com/sbesiktepe/tbng-scada-live.git && cd tbng-scada-live
cp .env.example .env && chmod 600 .env
docker run --rm caddy:2-alpine caddy hash-password --plaintext 'ORTAK-PAROLA'
#  .env: SITE_ADDRESS (bu sunucuya yönlenen DNS adı), LIVE_USER, LIVE_PASSWORD_HASH='...'
docker compose up -d --build
```

DNS kaydını bu sunucuya yönlendirin; 80 ve 443 portları açık olmalı (Let's Encrypt).
İş bitince `docker compose down` ile kapatın.

## Cihaz listesini güncel tutma

`config/devices.yaml` ana sistemden üretilir: scada2.tbngltd.com → Services →
**"Export devices for live viewer"** (admin). İnen dosyayı bu repodaki
`config/devices.yaml` üzerine koyup commit edin. Böylece acil durumda `git pull` yeterli olur.

İlk sürüm, ana projenin `config/devices.yaml` dosyasındaki 32 ELGAS sayacından üretildi.

## Mobil veri ve çakışma

- Her okuma modemin mobil kotasından yer. Varsayılan okuma aralığı **30 sn**
  (`MIN_POLL_SECONDS`). Görüntüleyiciyi sadece ana sistem çalışmazken açık tutun.
- Ana sistem de aynı cihazları okur. Fiber koptuğunda ana sistem cihazlara zaten
  ulaşamaz, bu yüzden normalde iki okuyucu aynı anda çalışmaz.

## Geliştirme

```bash
cd app && pip install -r requirements.txt
DEVICES_FILE=../config/devices.yaml uvicorn live.server:app --port 8200
```
Modbus kodu (`modbus.py`, `decoding.py`, `planning.py`) tbng-scada-next collector'ından
kopyalandı; orada sahada doğrulanmış kodla aynı tutun.
