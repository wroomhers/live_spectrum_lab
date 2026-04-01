# Live Spectrum Lab

PipeWire kullanan Linux sistemlerde iki kucuk ses araci:

- `visualizer.py`: Sistemde calan sesi canli okuyup spektrum, bant enerjileri ve waveform gosterir.
- `tone_lab.py`: Secilen output sink'e test tonu/generator sinyali yollar.

Proje stem ayirma yapmaz. Kick, vokal veya snare gibi kaynaklari ayri kanallara bolmez; mix'in tamamini analiz eder veya test sinyali uretir.

## Icerik

### 1. Live Spectrum Lab

Canli analiz araci. Varsayilan PipeWire output sink'i bulur, GStreamer ile monitor akisini okur ve Tkinter arayuzunde gosterir.

Ozellikler:

- Canli FFT ozeti
- Frekans bantlarina ayrilmis enerji timeline'i
- Full mix waveform gorunumu
- Cihaz/sink secimi
- Fare ile banda zoom benzeri detay gorunumu
- GUI acmadan hizli baglanti testi

Calistirma:

```bash
cd ~/Desktop/live_spectrum_lab
./run_visualizer.sh
```

Dogrudan Python ile:

```bash
python3 visualizer.py
```

Faydali komutlar:

```bash
python3 visualizer.py --list-targets
python3 visualizer.py --probe-seconds 2
python3 visualizer.py --target 51
PIPEWIRE_TARGET=51 python3 visualizer.py
```

### 2. Tone Lab

Interaktif test tonu ureticisi. `pw-play` uzerinden secilen sink'e ses yollar ve ayni anda waveform/FFT preview gosterir.

Ozellikler:

- `sine`, `square`, `saw`, `triangle` waveform secimi
- Iki osilator (`freq_a`, `freq_b`) ve mix kontrolu
- Gain kontrolu
- Formula modu
- Farkli output sink secimi

Calistirma:

```bash
cd ~/Desktop/live_spectrum_lab
./run_tone_lab.sh
```

Dogrudan Python ile:

```bash
python3 tone_lab.py
```

Formula modu ornekleri:

```text
200
200,400
0.6*sine(200)+0.4*sine(400)
0.7*square(220)
0.4*sine(f1)+0.4*saw(f2)
```

## Gereksinimler

Python tarafinda harici paket yok; standart kutuphaneler ve sistem araclari kullaniliyor.

Gerekli ortam:

- Linux
- PipeWire
- `wpctl`
- `pw-play`
- `gst-launch-1.0`
- Tkinter (`python3-tk`)

Ubuntu/Debian benzeri sistemlerde gereken paketler tipik olarak sunlardir:

```bash
sudo apt install python3 python3-tk pipewire-bin gstreamer1.0-tools gstreamer1.0-pipewire
```

Dagitima gore paket adlari degisebilir.

## Nasil Calisir

- `visualizer.py`, aktif output sink'i `wpctl status` ile bulur.
- Secilen sink'in monitor akisindan PCM veri okumak icin `gst-launch-1.0 pipewiresrc` kullanir.
- `tone_lab.py`, olusturdugu PCM veriyi `pw-play --target <sink_id>` ile secilen cihaza yollar.
- Her iki uygulama da arayuz icin Tkinter kullanir.

## Notlar

- Varsayilan davranis aktif ses cikisini secmektir.
- Analizor, hoparlor/cihaz monitor akisina baglandigi icin tarayici, muzik oynatici veya sistem sesi uzerinde calisir.
- `Tone Lab` sesi dogrudan secilen output sink'e yollar; hoparlor aciksa duyarsin.
- Wayland/X11 fark etmeksizin PipeWire oturumu oldugu surece calismasi hedeflenir.
