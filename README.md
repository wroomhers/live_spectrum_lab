# Live Spectrum Lab

PipeWire kullanan Linux sistemler için geliştirilmiş, gerçek zamanlı ses analiz ve test sinyali üretim araçları seti. Proje, kaynak ayırma (stem separation) yapmaz; doğrudan seçilen PipeWire çıkışının (sink) monitör akışını okur veya bu akışa sinyal gönderir.

İki temel araçtan oluşur:
1. **`visualizer.py`**: Sistemde çalan sesi okuyan, interaktif spektrum ve dalga formu analizörü.
2. **`tone_lab.py`**: Test tonları ve matematiksel formüllerle özel sinyaller üreten interaktif jeneratör.

---

## 1. Live Spectrum Lab (`visualizer.py`)

Aktif PipeWire çıkışını (output sink) bulur ve GStreamer (`pipewiresrc`) yardımıyla PCM verisini okuyarak Tkinter arayüzünde görselleştirir. Tarayıcılar, medya oynatıcılar veya sistem sesleri dahil olmak üzere o an hoparlörden çıkan tüm sesi analiz eder.

### Temel Özellikler
* **Gerçek Zamanlı Analiz:** Full mix dalga formu (waveform) ve FFT bazlı spektrum önizlemesi.
* **Frekans Bantları & Enerji Takibi:** Sesi SUB, KICK, LOW BASS, TREBLE gibi spesifik bantlara ayırarak zaman içindeki RMS enerjisini (timeline) ve tepe noktalarını (peak) gösterir.
* **İnteraktif Arayüz Etkileşimleri:**
    * **Sol Tık (Bant üzerinde):** Seçilen frekans bandını daha dar alt bantlara bölerek detaylı analiz (zoom) görünümüne geçer.
    * **Sağ Tık (Timeline üzerinde):** İlgili zaman/enerji noktasına referans işaretçisi (marker) bırakır.
    * **Orta Tık (Fare Tekerleği):** Bırakılan işaretçiyi siler.
    * **Geri Butonu / ESC:** Üst banda geri döner veya uygulamayı kapatır.
    * **Hover Tooltip:** Fare ile grafiğin üzerinde gezinirken frekans, zaman ve genlik değerlerini okur.
* **Çoklu Cihaz Desteği:** GUI üzerinden aktif çıkış cihazını anlık olarak değiştirebilme.

### CLI Kullanımı ve Argümanlar
```bash
# Standart başlatma (varsayılan sink cihazını bulur)
python3 visualizer.py

# Kullanılabilir cihazları (sink) listeleme
python3 visualizer.py --list-targets

# GUI açmadan hızlı bağlantı ve veri akışı testi (örneğin 2 saniye)
python3 visualizer.py --probe-seconds 2

# Belirli bir cihaza doğrudan bağlanma (ID: 51)
python3 visualizer.py --target 51
# veya
PIPEWIRE_TARGET=51 python3 visualizer.py
