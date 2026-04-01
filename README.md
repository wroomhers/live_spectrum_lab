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
2. Tone Lab (tone_lab.py)

pw-play alt yapısını kullanarak doğrudan seçilen cihaza test sinyalleri gönderen interaktif osilatör aracıdır. Üretilen sinyali çıkışa gönderirken aynı anda arayüzde dalga formu ve FFT önizlemesini çizer.
Temel Özellikler

    Standart Dalga Formları: Sine, Square, Saw, Triangle.

    Knob Modu: Çift osilatör (freq_a ve freq_b), osilatörler arası miks oranı ve ana kazanç (gain) kontrollerini arayüzdeki slider'lar ile anlık olarak yönetme.

    Formula Modu: Sinyali doğrudan Python ifadeleriyle matematiksel olarak sentezleme. Formül kutusuna girilen ifadeler anında işlenerek sese dönüştürülür.

    Canlı Cihaz Değişimi: Çalışma esnasında sesi farklı bir çıkışa (örneğin kulaklıktan hoparlöre) aktarabilme.

Formula Modu Örnekleri

Metin giriş kutusuna yazılabilecek geçerli ifadeler:

    200 : 200 Hz'lik basit bir sinüs dalgası.

    200, 400 : 200 Hz ve 400 Hz'lik iki sinüs dalgasının eşit miksi.

    0.6*sine(200) + 0.4*sine(400) : Özel oranlanmış sinüs karışımı.

    0.7*square(220) : 220 Hz'lik kare dalga.

    0.4*sine(f1) + 0.4*saw(f2) : Arayüzdeki A ve B slider frekanslarını (f1 ve f2 değişkenleri) referans alan kompozit dalga.

Çalıştırma
Bash

python3 tone_lab.py

Gereksinimler ve Kurulum

Python tarafında harici bir bağımlılık (pip paketi) bulunmamaktadır. Tüm işlemler standart kütüphaneler (math, threading, subprocess vb.) ve sistem araçlarıyla yürütülür.
Sistem Gereksinimleri

    Linux İşletim Sistemi (Wayland veya X11 fark etmeksizin PipeWire oturumu açık olmalı)

    PipeWire (wpctl, pw-play)

    GStreamer (gst-launch-1.0 ve pipewire eklentileri)

    Tkinter (Arayüz için python3-tk)

Ubuntu / Debian / Mint Kurulumu

Gerekli sistem paketlerini aşağıdaki komutla kurabilirsiniz:
Bash

sudo apt update
sudo apt install python3 python3-tk pipewire-bin gstreamer1.0-tools gstreamer1.0-pipewire

(Diğer dağıtımlarda paket isimleri Arch için pipewire, gst-plugin-pipewire, tk; Fedora için pipewire-utils, gstreamer1-plugin-pipewire, python3-tkinter şeklinde farklılık gösterebilir.)
