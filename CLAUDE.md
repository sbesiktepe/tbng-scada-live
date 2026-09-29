# CLAUDE.md — TBNG SCADA Live

Acil durum canlı görüntüleyici. Ana proje: github.com/sbesiktepe/tbng-scada-next (mimari,
kurallar orada). Kullanıcıyla Türkçe konuşulur; ürün (kod, arayüz, log) tamamen İngilizce.

- Veritabanı YOK, geçmiş YOK: yalnızca `config/devices.yaml`'daki cihazları okuyup son
  değerleri bellekte tutar ve gösterir. Yeni özellik eklerken bu sadeliği koru.
- Sahadaki cihazlara asla yazma; yalnızca Function 03. Modbus kodu tbng-scada-next
  `services/collector/collector/{modbus,decoding,planning}.py` ile aynı tutulur.
- Mobil veri: okuma aralığı en az 30 sn (MIN_POLL_SECONDS); bağlantı kalıcıdır.
- Kimlik doğrulama Caddy'de (tek ortak kullanıcı, basic auth + TLS). Gizli bilgi repoya girmez.
- `config/devices.yaml` ana sistemden dışa aktarılır (Services → Export devices for live viewer).
