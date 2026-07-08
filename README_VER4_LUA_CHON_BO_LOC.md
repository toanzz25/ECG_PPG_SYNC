# README VER4 - Giai thich lua chon bo loc trong du an

Tai lieu nay giai thich bo loc dang duoc chon trong du an ECG + PPG Sync, ly do chon cac bo loc do, va vai tro cua tung buoc trong chuoi xu ly tin hieu.

> Tom tat ngan: Du an chon pipeline loc ket hop `baseline removal + FFT bandpass/notch + wavelet denoise`. Ly do la tin hieu duoc xu ly tren PC sau khi thu, can loc de hieu, de dieu chinh, it phu thuoc thu vien phuc tap, phu hop voi ECG 1 kHz va PPG lay mau thap hon.

## 1. Muc tieu loc tin hieu

Tin hieu ECG va PPG do truc tiep tu cam bien thuong bi anh huong boi:

- Nhieu nen cham do troi baseline, chuyen dong, tiep xuc dien cuc.
- Nhieu tan so cao do mach ADC, day dan, rung dong nho.
- Nhieu dien luoi 50 Hz.
- PPG co thanh phan DC rat lon, trong khi thanh phan mach AC can quan sat lai nho.
- Bien do va huong dinh PPG co the thay doi theo cach dat cam bien.

Viec loc tin hieu trong du an phuc vu 3 muc dich:

1. Ve do thi ECG/PPG de quan sat ro hon.
2. Phat hien dinh R ECG va dinh PPG on dinh hon.
3. Tinh cac chi so BPM, HRV, PTT, SpO2 va PI tu tin hieu da xu ly.

## 2. Bo loc dang dung cho ECG

Trong `monitor.py`, ECG duoc xu ly theo chuoi:

```text
ECG raw
-> tru baseline bang median
-> FFT bandpass 0.5-45 Hz
-> notch 50 Hz
-> wavelet denoise db4 level 3
-> tru median lan cuoi
-> ECG filtered
```

### 2.1. Tru baseline bang median

Cong thuc:

```text
ecg_centered[n] = ecg_raw[n] - median(ecg_raw)
```

Ly do chon:

- Median ben vung hon mean khi co dinh R lon hoac spike.
- Dua tin hieu ve quanh 0 de ve do thi va loc FFT de hon.
- Don gian, khong can tham so phuc tap.

### 2.2. FFT bandpass 0.5-45 Hz

Day tan so duoc giu lai:

```text
0.5 Hz <= f <= 45 Hz
```

Ly do chon can duoi 0.5 Hz:

- Thanh phan duoi 0.5 Hz chu yeu la troi baseline, thay doi tiep xuc dien cuc, ho hap, chuyen dong cham.
- Loai bo vung nay giup duong ECG it bi troi len/xuong.

Ly do chon can tren 45 Hz:

- QRS va thong tin hinh dang ECG co ich trong bai nay nam chu yeu duoi khoang 40-45 Hz.
- Nhieu tan so cao thuong den tu ADC, day dan va moi truong.
- Giu den 45 Hz giup dinh R van ro, nhung bot nhieu cao tan.

Ly do dung FFT bandpass:

- Du lieu trong project duoc thu xong roi moi xu ly tren PC, nen loc theo block bang FFT rat phu hop.
- De cai dat bang `numpy`, khong can them `scipy`.
- De giai thich: bien doi sang mien tan so, giu dai tan co ich, dat cac tan so khac ve 0, roi bien doi nguoc.
- Khong can thiet ke he so IIR/FIR phuc tap.

### 2.3. Notch 50 Hz

Vung tan so bi loai:

```text
49 Hz <= f <= 51 Hz
```

Ly do chon:

- O Viet Nam, dien luoi co tan so 50 Hz.
- Tin hieu ECG bien do nho nen rat de bi nhieu dien luoi chen vao.
- Du an da gioi han lowpass 45 Hz, nhung van giu notch 50 Hz de tang tinh an toan khi co ro ri tan so gan 50 Hz hoac khi thay doi tham so sau nay.

### 2.4. Wavelet denoise db4 level 3

Thong so:

```text
wavelet = db4
level = 3
threshold = sigma * sqrt(2 * ln(N))
sigma = median(abs(detail_last)) / 0.6745
```

Ly do chon wavelet:

- ECG la tin hieu khong dung yen theo thoi gian, co dinh QRS ngan va sac.
- Wavelet phu hop hon loc tan so co dinh khi muon giam nhieu ma van giu bien doi cuc bo nhu QRS.
- Wavelet threshold co the lam mem nhieu cao tan ma khong lam phang dinh R qua nhieu.

Ly do chon `db4`:

- Daubechies 4 hay duoc dung trong xu ly ECG vi hinh dang wavelet co kha nang mo ta QRS tuong doi tot.
- Can bang giua do muot va kha nang giu bien doi nhanh.
- Nhe, de tinh, phu hop voi du lieu thu dai ngan khac nhau.

Ly do chon `level = 3`:

- Muc 3 du de tach nhieu cao tan o ECG 1 kHz.
- Khong qua sau de tranh lam mat chi tiet QRS.
- Phu hop voi muc tieu cua du an la hien thi va phat hien dinh, khong phai chan doan hinh thai ECG chi tiet.

## 3. Bo loc dang dung cho PPG

Trong `monitor.py`, PPG IR duoc xu ly theo chuoi:

```text
PPG IR raw
-> uoc luong Fs tu timestamp
-> tru trend bang moving average 1.2 s
-> FFT bandpass 0.5-8 Hz
-> wavelet denoise db4 level 3
-> tru median lan cuoi
-> PPG filtered
```

### 3.1. Uoc luong tan so lay mau PPG

Cong thuc:

```text
Fs = 1000 / median(diff(time_ms))
```

Ly do chon:

- PPG tu MAX30102 khong cung tan so voi ECG 1 kHz.
- Timestamp thuc te co the co jitter nho.
- Dung median cua khoang cach timestamp giup uoc luong Fs on dinh hon mean.

### 3.2. Tru trend bang moving average 1.2 s

Cong thuc:

```text
trend[n] = moving_average(ppg_ir_raw, window = 1.2 s)
ppg_ac[n] = ppg_ir_raw[n] - trend[n]
```

Ly do chon:

- PPG co thanh phan DC rat lon do anh sang nen, mo, da, luc ep ngon tay.
- Thanh phan can quan sat de tinh nhip mach la AC nho nam tren DC.
- Moving average 1.2 s bat duoc xu huong cham, sau khi tru di se lam song mach ro hon.
- Cua so 1.2 s du dai de khong bam sat tung nhip tim, nhung du ngan de theo thay doi cham cua baseline.

### 3.3. FFT bandpass 0.5-8 Hz

Day tan so duoc giu lai:

```text
0.5 Hz <= f <= min(8 Hz, 0.45 * Fs)
```

Ly do chon can duoi 0.5 Hz:

- Duoi 0.5 Hz chu yeu la troi nen, thay doi luc dat tay, chuyen dong cham.
- Loai bo vung nay giup song mach PPG ro hon.

Ly do chon can tren 8 Hz:

- Nhip tim nguoi binh thuong va ca khi nhanh van nam chu yeu trong vung thap.
- 8 Hz tuong duong 480 bpm, cao hon nhieu so voi nhip sinh ly can do, nen van du rong.
- Cac thanh phan tren 8 Hz cua PPG thuong la nhieu hoac dao dong khong can cho BPM/PTT.

Ly do dung `min(8 Hz, 0.45 * Fs)`:

- PPG co tan so lay mau thap hon ECG.
- Theo Nyquist, khong nen loc qua gan `Fs/2`.
- Chon 0.45 * Fs giup tranh sat bien Nyquist, giam loi khi Fs PPG thay doi.

### 3.4. Wavelet denoise cho PPG

Sau bandpass, PPG van co the con nhieu nho. Wavelet `db4 level 3` duoc dung them de:

- Lam muot song PPG.
- Giam spike nho.
- Giu dang song mach de phat hien dinh PPG phuc vu tinh PTT va BPM fallback.

## 4. Vi sao khong chi dung mot bo loc duy nhat?

Mot bo loc duy nhat kho giai quyet tot tat ca van de:

- Median/baseline removal xu ly do lech nen.
- FFT bandpass xu ly nhieu nam ngoai dai tan mong muon.
- Notch xu ly rieng nhieu dien luoi 50 Hz.
- Wavelet xu ly nhieu cuc bo va giu dinh tin hieu tot hon.

Vi vay, pipeline ket hop giup tin hieu vua sach ve dai tan, vua muot hon khi phat hien peak.

## 5. Vi sao khong chon bo loc IIR/FIR truc tiep?

IIR/FIR la lua chon tot neu can loc thoi gian thuc tren vi dieu khien. Tuy nhien trong du an nay, viec loc dang nam o UI Python sau khi thu du lieu, nen FFT + wavelet co nhieu loi the:

- De cai dat bang `numpy` va `PyWavelets`.
- De thay doi tan so cat khi bao cao/thi nghiem.
- De giai thich truc quan theo mien tan so.
- Khong can quan tam nhieu den on dinh he so loc IIR.
- Khong can them `scipy.signal`.

Neu sau nay can hien thi realtime lien tuc tren ESP32 hoac tinh BPM ngay tren firmware, khi do co the can chuyen sang IIR/FIR nhe hon.

## 6. Diem manh cua lua chon hien tai

- Phu hop xu ly offline/gan realtime tren may tinh.
- Giu code ngan, de doc, de bao tri.
- Loc duoc ca troi nen, nhieu cao tan va nhieu dien luoi.
- Wavelet giup giu dinh R ECG tot hon so voi lam muot manh bang moving average.
- PPG duoc xu ly rieng theo timestamp rieng, khong ep cung tan so voi ECG.
- Khong phu thuoc nhieu thu vien ngoai.

## 7. Gioi han cua lua chon hien tai

- FFT loc theo block nen co the co artifact o dau/cuoi doan tin hieu.
- Khong phai bo loc causal, nen khong phu hop neu can tinh realtime tung mau tren firmware.
- Tham so 0.5-45 Hz cho ECG va 0.5-8 Hz cho PPG la lua chon thuc nghiem, co the can tinh chinh theo cam bien va cach dat tay.
- Wavelet threshold neu qua manh co the lam giam bien do dinh.
- SpO2 va PI phu thuoc chat luong PPG RED/IR, nen loc tot chua du, van can dat cam bien dung.

## 8. Bang tom tat bo loc

| Tin hieu | Buoc loc | Tham so | Ly do |
| --- | --- | --- | --- |
| ECG | Tru baseline | `median` | Dua ECG ve quanh 0, giam troi nen |
| ECG | FFT bandpass | `0.5-45 Hz` | Giu dai tan ECG huu ich, bo troi nen va nhieu cao tan |
| ECG | Notch | `50 Hz +/- 1 Hz` | Giam nhieu dien luoi |
| ECG | Wavelet | `db4 level 3` | Giam nhieu, giu dinh R |
| PPG | Moving average detrend | `1.2 s` | Tach AC khoi DC |
| PPG | FFT bandpass | `0.5-8 Hz` | Giu song mach, bo troi nen va nhieu cao tan |
| PPG | Wavelet | `db4 level 3` | Lam muot PPG, ho tro phat hien dinh |

## 9. Cau tra loi ngan khi bao ve

Co the trinh bay ngan gon nhu sau:

```text
Du an chon bo loc ket hop FFT bandpass va wavelet. Voi ECG, em giu dai 0.5-45 Hz de loai troi baseline va nhieu cao tan, them notch 50 Hz de giam nhieu dien luoi, sau do dung wavelet db4 level 3 de khu nhieu nhung van giu dinh R. Voi PPG, em tru thanh phan DC bang moving average 1.2 s, loc dai 0.5-8 Hz vi song mach nam o dai tan thap, roi dung wavelet de lam muot. Cach chon nay phu hop vi du lieu duoc xu ly tren PC sau khi thu, de cai dat bang Python, de giai thich va du tot cho viec tinh BPM, HRV, PTT, SpO2 va PI.
```

## 10. Vi tri code lien quan

Cac ham trong `monitor.py`:

- `fft_ecg_band_clean(...)`: loc FFT bandpass ECG va notch 50 Hz.
- `ecg_denoise(...)`: ket hop FFT ECG va wavelet.
- `ppg_ac_component(...)`: tach thanh phan AC cua PPG bang moving average.
- `fft_ppg_band_clean(...)`: loc FFT bandpass PPG.
- `ppg_denoise(...)`: ket hop detrend, FFT PPG va wavelet.
- `compute_derived_metrics(...)`: dung tin hieu da loc de tinh cac chi so.

