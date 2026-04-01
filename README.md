# Live Spectrum Lab

Bu proje, bilgisayarda calan sesi PipeWire uzerinden canli okuyup frekans dagilimini ve waveform gorunumu olarak cizer.

AI stem ayirma yapmaz. Yani kick, vokal, snare gibi kaynaklari ayri kanallara bolmez. Bunun yerine FL Studio'daki analiz ekranlari gibi frekans ve enerji dagilimini gosterir.

## Calistirma

```bash
cd ~/Desktop/live_spectrum_lab
./run_visualizer.sh
```

## Faydalı komutlar

Mevcut monitor hedeflerini listele:

```bash
python3 visualizer.py --list-targets
```

GUI acmadan ses gelip gelmedigini test et:

```bash
python3 visualizer.py --probe-seconds 2
```

Belirli bir cikisi hedefle:

```bash
python3 visualizer.py --target alsa_output.pci-0000_00_1f.3.analog-stereo
```

## Notlar

- Varsayilan olarak aktif ses cikisini `wpctl` ile bulur.
- PipeWire kullanan Linux oturumlari icin tasarlandi.
- Cikis olarak hoparlor monituru dinlendigi icin tarayicida, oynaticida veya sistemde calan sesi gorebilirsin.
