# README VER 2 - Cau hoi bao ve project ECG + PPG Sync

File nay dung de on bao ve. Cac cau tra loi ben duoi bam theo dung project hien tai:

- ESP32 doc ECG tu AD8232 bang ADC GPIO34.
- ESP32 doc PPG tu MAX30102/MAX30105 bang I2C FIFO, gom RED va IR.
- ECG lay mau bang `esp_timer` 1 kHz.
- PPG co toc do hieu dung 25 Hz do `sampleRate = 100` va `sampleAverage = 4`.
- Firmware do theo phien, luu mau vao RAM, het thoi gian moi dump CSV ve PC.
- `monitor.py` luu raw CSV, loc FFT + wavelet, ve ECG/PPG.

## 1. Tom tat project trong 30 giay

**Cau hoi:** Em hay gioi thieu ngan gon project cua minh?

**Tra loi:**  
Project cua em thu dong thoi hai tin hieu sinh hoc la ECG va PPG. ECG duoc lay tu module AD8232 qua ADC cua ESP32, tan so lay mau 1000 Hz. PPG duoc lay tu MAX30102 qua I2C FIFO, gom hai kenh RED va IR, tan so hieu dung hien tai la 25 Hz. Hai tin hieu dung chung moc thoi gian `measurement_start_us`, sau do firmware gan timestamp `time_ms` cho tung mau va dump ra CSV. Tren PC, `monitor.py` luu du lieu raw, loc tin hieu bang FFT band-pass/notch va wavelet `db4 level 3`, roi ve do thi ECG/PPG.

## 2. Cau hoi ve muc tieu va y nghia

### 2.1 Project nay giai quyet bai toan gi?

Project giai quyet bai toan thu dong thoi ECG va PPG tren cung mot he ESP32, co timestamp chung de phuc vu so sanh thoi gian giua tin hieu dien tim va tin hieu mach ngoai vi. Day la nen tang de tinh heart rate tu ECG, pulse rate tu PPG, va ve sau co the tinh PTT hoac cac chi so lien quan.

### 2.2 ECG va PPG khac nhau nhu the nao?

ECG la tin hieu dien cua tim, do bang dien cuc va module AD8232. PPG la tin hieu quang hoc, do su thay doi hap thu anh sang theo mach mau bang MAX30102. ECG the hien hoat dong dien cua tim gan nhu truc tiep, con PPG the hien song mach den vi tri dat cam bien sau mot do tre sinh ly.

### 2.3 Vi sao can do ca ECG va PPG?

Do ca hai tin hieu giup quan sat hai hien tuong khac nhau cua he tim mach: ECG cho thoi diem tim co tin hieu dien, PPG cho thoi diem song mach den ngoai vi. Khi dong bo timestamp, co the tinh do tre giua R peak ECG va dinh/chan song PPG, phuc vu phan tich PTT.

## 3. Cau hoi ve phan cung

### 3.1 AD8232 co vai tro gi?

AD8232 la analog front-end cho ECG. No khuech dai va loc so bo tin hieu ECG tu dien cuc, sau do dua ra dien ap analog o chan OUT. ESP32 doc dien ap nay bang ADC1 channel 6, tuong ung GPIO34.

### 3.2 MAX30102 co vai tro gi?

MAX30102 la cam bien PPG quang hoc, co LED do, LED hong ngoai, photodiode va ADC noi bo. ESP32 khong doc analog tu MAX30102, ma doc du lieu so RED va IR tu FIFO cua cam bien qua I2C.

### 3.3 Chan ket noi chinh la gi?

- AD8232 OUT -> ESP32 GPIO34.
- MAX30102 SDA -> ESP32 GPIO21.
- MAX30102 SCL -> ESP32 GPIO22.
- UART giao tiep PC o baud 115200.

### 3.4 I2C trong project dung de lam gi?

I2C dung de ESP32 cau hinh va doc FIFO cua MAX30102. ESP32 la master, MAX30102 la slave co dia chi `0x57`. Toc do I2C hien tai la 400 kHz.

## 4. Cau hoi ve lay mau

### 4.1 ECG duoc lay mau nhu the nao?

ECG duoc lay mau bang `esp_timer` periodic. Trong code:

```c
#define ADC_SAMPLE_RATE 1000
#define ECG_TIMER_PERIOD_US (1000000 / ADC_SAMPLE_RATE)
```

Vay chu ky lay mau ECG la:

```text
T = 1 / 1000 = 0.001 s = 1 ms
```

Moi callback timer doc ADC AD8232, gan timestamp theo thoi gian troi qua tu luc bat dau do, roi luu vao `ecg_buffer`.

### 4.2 PPG duoc lay mau nhu the nao?

PPG duoc MAX30102 lay mau noi bo va dua vao FIFO. ESP32 polling FIFO moi 5 ms. Khi FIFO co mau, firmware doc RED va IR, sau do gan timestamp nguoc theo so mau dang co trong FIFO.

Trong code:

```c
#define sampleRate 100
#define sampleAverage 4
#define PPG_EFFECTIVE_SAMPLE_RATE (sampleRate / sampleAverage)
```

Vay:

```text
Fs_ppg = 100 / 4 = 25 Hz
T_ppg = 40 ms
```

### 4.3 Tai sao ECG 1000 Hz con PPG chi 25 Hz?

ECG co cac thanh phan nhanh, dac biet QRS/R peak, nen can tan so lay mau cao de bat dinh chinh xac. PPG bien thien cham hon theo mach dap, nen 25 Hz van co the quan sat dang song va pulse rate co ban. Trong project, PPG bi giam toc do hieu dung do `sampleAverage = 4`, tuc cam bien trung binh 4 mau de giam nhieu.

### 4.4 Lay mau ECG co phai doc 1 lan ADC moi mau khong?

Khong. Moi mau ECG trong project duoc oversampling 4 lan:

```c
#define ECG_ADC_OVERSAMPLE_COUNT 4
```

Firmware doc ADC 4 lan roi lay trung binh. Muc dich la giam nhieu ADC ngau nhien, doi lai moi mau ton thoi gian doc ADC lon hon.

### 4.5 Gia tri `ecg_raw` co don vi gi?

`ecg_raw` la ADC count 12 bit, nam trong khoang 0 den 4095. Project hien tai chua calibration sang volt hoac mV, nen khong nen noi day la mV sinh hoc. Neu muon doi sang dien ap can biet Vref/attenuation/calibration cua ESP32 va gain cua AD8232.

### 4.6 Gia tri PPG RED/IR co don vi gi?

`ppg_red_raw` va `ppg_ir_raw` la count 18 bit tu ADC noi bo cua MAX30102, nam trong khoang 0 den 262143. Day la gia tri quang hoc raw, gom thanh phan DC lon va thanh phan AC do mach dap.

## 5. Cau hoi ve timer va ngat

### 5.1 Timer ngat trong project la gi?

Project dung `esp_timer` cua ESP-IDF de tao timer periodic 1 kHz cho ECG. Ham callback la:

```c
static void ecg_timer_callback(void *arg)
```

Moi 1 ms callback duoc goi de doc ADC va luu mau ECG.

### 5.2 `esp_timer` co phai interrupt phan cung tuyet doi khong?

Khong nen tra loi qua muc tuyet doi. Trong project, `esp_timer` duoc cau hinh `dispatch_method = ESP_TIMER_TASK`, nghia la callback chay trong task cua esp_timer, khong phai ISR phan cung truc tiep. No giup lap lich lay mau 1 kHz kha on dinh, nhung van co the jitter neu CPU ban.

### 5.3 Jitter la gi va project co kiem tra khong?

Jitter la sai lech chu ky lay mau so voi ly thuyet. ECG ly thuyet moi 1000 us co mot mau. Project co luu `ecg_min_period_us` va `ecg_max_period_us`, sau do dump ra CSV trong dong STATS. Neu hai gia tri nay lech nhieu khoi 1000 us thi he thong bi jitter.

### 5.4 Vi sao khong stream realtime tung mau qua UART?

Vi ECG 1000 Hz, neu vua lay mau vua in UART tung mau realtime co the lam cham he thong va gay jitter. Project chon cach luu mau vao RAM trong luc do, het thoi gian moi dump ca block CSV ve PC. Cach nay uu tien do on dinh cua viec lay mau.

### 5.5 Task `readAD8232_task` co doc ECG khong?

Trong project hien tai, `readAD8232_task` khong doc ECG. No chi log thong bao. ECG that su duoc doc trong `ecg_timer_callback` bang `esp_timer`.

## 6. Cau hoi ve dong bo tin hieu

### 6.1 ECG va PPG dang do tuan tu hay dong thoi?

Khong phai tuan tu. O mode `BOTH`, ECG va PPG duoc do dong thoi theo cung mot moc bat dau. ECG duoc lay mau bang timer 1 kHz, PPG duoc doc FIFO trong task rieng.

### 6.2 Co phai dong bo mau 1-1 khong?

Khong. Project hien tai la dong bo theo timestamp, khong phai dong bo mau 1-1. ECG co 1000 mau/s, PPG co 25 mau/s, nen trung binh 40 mau ECG moi co 1 mau PPG.

### 6.3 Dong bo trong project duoc thuc hien nhu the nao?

Khi bat dau do, firmware dat:

```c
measurement_start_us = esp_timer_get_time();
```

Sau do:

- ECG lay `elapsed_us = esp_timer_get_time() - measurement_start_us`.
- PPG lay `batch_time_ms` luc doc FIFO, roi uoc luong timestamp tung mau trong batch dua vao `PPG_SAMPLE_PERIOD_US`.
- Khi dump CSV, firmware merge `ecg_buffer` va `ppg_buffer` theo `time_ms`.

### 6.4 Vi sao PPG timestamp chi la uoc luong?

MAX30102 luu mau vao FIFO, nhung project khong dung chan interrupt va khong timestamp tung mau ngay tai thoi diem cam bien tao mau. ESP32 doc FIFO theo batch moi 5 ms, sau do gan timestamp nguoc dua vao chu ky PPG 40 ms. Vi vay timestamp PPG la uoc luong theo batch FIFO.

### 6.5 Neu muon dong bo mau that su thi phai lam gi?

Co ba huong:

1. Ha ECG xuong cung tan so voi PPG, vi du 25 Hz, moi dong co ca ECG va PPG. Cach nay khong tot cho ECG vi mat R peak chi tiet.
2. Giu ECG 1000 Hz, PPG 25 Hz, khi co PPG thi ghep voi mau ECG gan nhat theo timestamp. Day la hop ly hon cho project nay.
3. Noi suy PPG len truc 1000 Hz de moi dong ECG co gia tri PPG uoc luong. Nhung PPG noi suy khong phai mau do that.

### 6.6 Dong CSV co ca ECG va PPG cung mot `time_ms` co nghia la gi?

Nghia la theo timestamp ms, mau ECG va mau PPG duoc gan vao cung thoi diem. Tuy nhien do ECG va PPG co co che lay mau khac nhau, do chinh xac phu thuoc jitter timer ECG va cach uoc luong timestamp FIFO cua PPG.

## 7. Cau hoi ve thoi gian do va buffer

### 7.1 Thoi gian do duoc dieu khien nhu the nao?

PC gui lenh:

```text
START <duration_s>
```

Firmware chuan hoa thoi gian do. Neu bang 0 thi lay mac dinh 10 s. Neu lon hon 120 s thi gioi han ve 120 s.

### 7.2 Vi sao gioi han toi da 120 s?

Vi firmware luu du lieu vao RAM trong luc do. ECG 1000 Hz tao nhieu mau, nen thoi gian qua dai se ton RAM. Project dat `MEASUREMENT_MAX_SECONDS = 120` de tranh tran bo nho.

### 7.3 Neu do 10 giay thi co bao nhieu mau?

Voi cau hinh hien tai:

```text
ECG: 10 * 1000 = 10000 mau
PPG: 10 * 25 = 250 mau
```

So mau thuc te co the lech nho do timer, FIFO, start/stop va jitter.

### 7.4 Buffer duoc cap phat the nao?

Khi start:

```c
ecg_capacity = duration_s * ADC_SAMPLE_RATE + ADC_SAMPLE_RATE;
ppg_capacity = duration_s * PPG_EFFECTIVE_SAMPLE_RATE + MAX30105_STORAGE_SIZE * 2;
```

Project cap phat them mot phan du de tranh thieu buffer do sai lech nho.

### 7.5 Overflow trong STATS co y nghia gi?

`ECG_OVERFLOW = 1` hoac `PPG_OVERFLOW = 1` nghia la buffer khong du cho so mau trong thoi gian do. Khi do du lieu co the bi mat va ket qua phan tich khong con day du.

## 8. Cau hoi ve CSV va UART

### 8.1 Firmware gui du lieu ve PC theo format nao?

Firmware gui block CSV:

```csv
BEGIN_SYNC_CSV,<ecg_count>,<ppg_count>
time_ms,ecg_raw,ppg_red_raw,ppg_ir_raw
...
STATS,...
END_SYNC_CSV,<ecg_count>,<ppg_count>,<ecg_overflow>,<ppg_overflow>
```

`monitor.py` doc block nay, luu raw CSV va filtered CSV.

### 8.2 Vi sao co dong bi trong cot ECG hoac PPG?

Vi ECG va PPG khong cung tan so. ECG 1000 Hz, PPG 25 Hz. Khi merge theo `time_ms`, nhieu dong chi co ECG, va thinh thoang moi co PPG. Day la dung voi co che dong bo timestamp hien tai.

### 8.3 File raw va filtered khac nhau the nao?

Raw CSV luu gia tri doc truc tiep tu firmware. Filtered CSV luu them tin hieu da xu ly tren PC:

- ECG: tru baseline, loc FFT band/notch, wavelet.
- PPG IR: khu DC/trend, loc band-pass, wavelet.

## 9. Cau hoi ve xu ly tin hieu ECG

### 9.1 Pipeline xu ly ECG la gi?

Trong `monitor.py`, ECG duoc xu ly:

```text
ECG raw -> subtract median -> FFT band-pass/notch -> wavelet denoise -> subtract median
```

Muc tieu la bo DC baseline, giam nhieu ngoai dai tan, giam nhieu dien luoi va lam min tin hieu.

### 9.2 Vi sao phai tru median ECG?

AD8232 dua ECG ve quanh mot muc DC bias, khong quanh 0. Tru median giup dua tin hieu ve quanh 0 va de ve/loc hon. Dung median thay mean vi median it bi anh huong boi cac peak lon va outlier.

### 9.3 Bo loc FFT ECG giu dai tan nao?

Project giu:

```text
0.5 Hz den 45 Hz
```

Va loai nhieu dien luoi quanh:

```text
50 Hz +/- 1 Hz
```

### 9.4 Tai sao chon 0.5 den 45 Hz cho ECG?

Thanh phan ECG quan trong, dac biet QRS, nam chu yeu trong dai thap den trung binh. High-pass 0.5 Hz giup bo drift baseline rat cham. Low-pass 45 Hz giup giam nhieu cao tan. Notch 50 Hz giup giam nhieu dien luoi.

### 9.5 FFT band clean co nhược diem gi?

FFT xu ly tren toan bo doan tin hieu, nen khong phai loc realtime. No co the gay anh huong bien o dau/cuoi doan va phu thuoc do dai cua block. Trong project nay chap nhan duoc vi du lieu duoc xu ly sau khi do xong, khong phai realtime.

## 10. Cau hoi ve xu ly tin hieu PPG

### 10.1 Pipeline xu ly PPG la gi?

PPG IR duoc xu ly:

```text
PPG IR raw -> moving average trend -> subtract trend -> FFT band-pass -> wavelet denoise
```

RED raw hien duoc luu lai, chua ve tren plot chinh.

### 10.2 Vi sao PPG raw nhin khong giong song PPG ly thuyet?

PPG raw gom thanh phan DC rat lon do anh sang nen, mo, ngon tay va vi tri dat cam bien. Thanh phan mach dap chi la AC nho nam tren nen DC do. Muon thay song PPG ro, phai khu DC/trend:

```text
ppg_ac = ppg_ir_raw - moving_average(ppg_ir_raw)
```

### 10.3 Tai sao dung moving average 1.2 s cho PPG?

Moving average 1.2 s uoc luong baseline/trend cham cua PPG. Khi tru trend nay, ta giu lai thanh phan AC do mach dap. Cua so 1.2 s du dai de bat drift cham, nhung van giu duoc dao dong mach.

### 10.4 Bo loc PPG giu dai tan nao?

Project giu dai:

```text
0.5 Hz den 8 Hz
```

Voi PPG 25 Hz, low-pass thuc te con bi gioi han boi Nyquist. Trong code:

```python
lowpass_hz = min(PPG_LOWPASS_HZ, sample_rate_hz * 0.45)
```

### 10.5 Vi sao khong dung PPG RED de ve plot chinh?

Project hien tai uu tien ve IR vi kenh IR thuong on dinh hon cho PPG. RED van duoc luu de ve sau co the tinh SpO2 bang ti le RED/IR.

## 11. Cau hoi ve wavelet

### 11.1 Wavelet la gi?

Wavelet la phuong phap phan tich tin hieu theo ca thoi gian va tan so. Khac voi FFT chi cho biet thanh phan tan so tren toan bo doan, wavelet phu hop voi tin hieu sinh hoc vi ECG/PPG co dac trung thay doi theo thoi gian.

### 11.2 Project dung wavelet nao?

Project dung:

```python
WAVELET_NAME = "db4"
WAVELET_LEVEL = 3
```

Tuc la Daubechies 4, phan ra 3 muc.

### 11.3 Vi sao dung db4?

`db4` hay duoc dung cho ECG vi dang song cua no phu hop voi cac bien doi nhanh nhu QRS, trong khi van co kha nang lam min nhieu. Voi project nay, `db4 level 3` la lua chon can bang giua giu peak va giam nhieu.

### 11.4 Cac buoc wavelet denoise trong project?

Trong `monitor.py`:

1. Phan ra he so wavelet:

```python
coeffs = pywt.wavedec(values, "db4", mode="symmetric", level=3)
```

2. Uoc luong nhieu bang MAD tu detail cao nhat:

```text
sigma = median(abs(detail_high)) / 0.6745
```

3. Tinh universal threshold:

```text
lambda = sigma * sqrt(2 * ln(N))
```

4. Soft-threshold cac detail coefficient.

5. Tai tao tin hieu bang inverse wavelet.

### 11.5 Soft threshold la gi?

Soft threshold lam nho cac he so detail:

```text
soft(d, lambda) = sign(d) * max(|d| - lambda, 0)
```

Neu he so nho hon nguong, no bi dua ve 0. Neu lon hon nguong, no bi giam bien do. Muc dich la loai nhieu nhung van giu dac trung chinh.

### 11.6 Tai sao khong chi dung FFT ma con dung wavelet?

FFT tot de loai dai tan khong mong muon, nhung ECG/PPG la tin hieu phi dung yen theo thoi gian. Wavelet giup giam nhieu ma van giu dac trung cuc bo nhu R peak ECG hoac dinh PPG. Trong project, FFT lam sach theo dai tan truoc, wavelet lam min/denoise sau.

### 11.7 Neu PyWavelets chua cai thi sao?

Trong code, neu khong co `pywt`, bien `HAS_PYWT = False`. ECG/PPG wavelet co the khong duoc ap dung dung nghia. De dung day du can cai:

```bash
pip install PyWavelets
```

## 12. Cau hoi ve BPM, peak va chi so sinh hoc

### 12.1 Project hien tai da tinh BPM chua?

Chua. Project hien tai chu yeu thu, dong bo, luu CSV, loc va ve tin hieu. BPM, HRV, PTT, SpO2 moi nam o huong phat trien hoac cong thuc trong README, chua phai chuc nang chinh da hoan thien trong firmware.

### 12.2 BPM duoc tinh tu dau?

BPM khong phai bien do truc Y. BPM duoc tinh tu khoang thoi gian giua cac dinh lien tiep:

```text
BPM = 60 / T_beat_s
```

Voi ECG, dung khoang RR giua cac R peak. Voi PPG, dung khoang giua cac peak/foot PPG.

### 12.3 PTT la gi?

PTT la Pulse Transit Time, do tre tu R peak ECG den dac trung PPG lien sau, thuong la foot hoac peak cua PPG:

```text
PTT_ms = t_ppg_feature_ms - t_r_peak_ms
```

Project co nen tang timestamp de tinh PTT, nhung chua co module detect peak/foot hoan chinh.

### 12.4 SpO2 co tinh duoc tu project khong?

Co the phat trien vi project co RED va IR raw. Cong thuc demo:

```text
R = (RED_AC / RED_DC) / (IR_AC / IR_DC)
SpO2 ~= 110 - 25 * R
```

Nhung day chi la uoc luong demo, khong phai thiet bi y te. Muon chinh xac can calibration.

## 13. Cau hoi ve chat luong tin hieu

### 13.1 Lam sao biet ECG bi clip?

Firmware dem so mau gan bien ADC:

```c
#define ECG_CLIP_LOW_THRESHOLD 20
#define ECG_CLIP_HIGH_THRESHOLD 4075
```

Neu nhieu mau <= 20 hoac >= 4075 thi co the ADC bi clip, dien cuc loi, tiep xuc kem hoac tin hieu bi bao hoa.

### 13.2 Lam sao biet PPG yeu?

PPG yeu khi thanh phan AC qua nho so voi DC, RED/IR gan phang, hoac waveform sau khi khu DC khong co chu ky ro. Trong `monitor.py`, co tinh tom tat IR_AC/DC de danh gia so bo.

### 13.3 Nguyen nhan ECG nhieu la gi?

Cac nguyen nhan thuong gap:

- Dien cuc tiep xuc kem.
- Day tin hieu dai, bat nhieu dien luoi 50 Hz.
- Nguoi do cu dong.
- ADC ESP32 co nhieu.
- Module AD8232 hoac nguon khong on dinh.

### 13.4 Nguyen nhan PPG nhieu la gi?

- Dat ngon tay long hoac an qua manh.
- Anh sang moi truong lot vao cam bien.
- Nguoi do cu dong.
- LED power khong phu hop.
- RED/IR gan bao hoa hoac qua yeu.

## 14. Cau hoi ve han che cua project

### 14.1 Han che lon nhat cua dong bo la gi?

PPG timestamp la uoc luong theo FIFO batch, khong phai timestamp phan cung tung mau. ECG dung timer 1 kHz nhung callback co the jitter vi chay trong esp_timer task. Vi vay project dong bo theo timestamp la hop ly, nhung chua phai dong bo mau phan cung tuyet doi.

### 14.2 Han che cua ECG la gi?

- Chua doc chan LO+/LO- cua AD8232 de phat hien roi dien cuc.
- Chua calibration ADC sang volt/mV.
- `adc_oneshot_read` trong timer task co the bi jitter neu CPU ban.
- Chua co detect R peak realtime.

### 14.3 Han che cua PPG la gi?

- Chua dung interrupt pin cua MAX30102.
- Toc do hieu dung chi 25 Hz do sample averaging.
- Timestamp duoc gan nguoc theo FIFO, chi la uoc luong.
- Chua tinh SpO2 hoan chinh.

### 14.4 Han che cua wavelet la gi?

Wavelet denoise phu thuoc wavelet, level va threshold. Neu threshold qua lon co the lam mat peak nho; neu qua nho thi con nhieu. Xu ly hien tai la offline tren PC, chua phai realtime tren ESP32.

## 15. Cau hoi "gai" hay gap va cach tra loi

### 15.1 Em noi dong bo, vay co phai hai cam bien lay mau cung mot thoi diem tuyet doi khong?

Khong. Em dong bo theo moc thoi gian chung va timestamp. ECG va PPG khong co cung tan so va khong chung ngat phan cung. Vi vay day la dong bo thoi gian, khong phai dong bo mau 1-1 tuyet doi.

### 15.2 Tai sao khong lay PPG 100 Hz de gan voi ECG tot hon?

Co the chinh `sampleAverage = 1` de tang toc do hieu dung len gan 100 Hz. Nhung trong cau hinh hien tai em chon `sampleAverage = 4` de giam nhieu PPG, chap nhan toc do 25 Hz. Neu muc tieu la PTT chinh xac hon, em se giam sample averaging va dung interrupt cua MAX30102.

### 15.3 Neu ECG 1000 Hz ma PPG 25 Hz thi so sanh co sai khong?

Khong sai neu so sanh theo timestamp. ECG cho moc R peak rat min theo thoi gian, PPG co mau thua hon. Do chinh xac cua PPG bi gioi han boi chu ky 40 ms va cach timestamp FIFO. Neu can PTT chinh xac cao, can tang Fs PPG va timestamp bang interrupt.

### 15.4 Tai sao khong xu ly wavelet tren ESP32?

Vi project hien tai uu tien thu du lieu on dinh va luu raw day du. Wavelet va FFT tinh toan nang hon, de tren PC se de kiem tra, thay doi tham so va ve plot. ESP32 chi can dam bao lay mau va timestamp on dinh.

### 15.5 Neu UART baud 115200 co du khong?

Du vi project khong stream realtime trong luc do. Du lieu duoc dump sau khi do xong. Neu stream realtime ECG 1000 Hz + PPG thi 115200 co the thanh nut co chai, nhung cach hien tai giam anh huong UART len lay mau.

### 15.6 Vi sao filtered CSV co gia tri NaN/trong o mot so dong?

Vi dong do khong co mau tu cam bien tuong ung. ECG va PPG co tan so khac nhau, khi merge theo `time_ms` thi cac cot khong phai luc nao cung co gia tri.

### 15.7 Neu thay PPG nguoc chieu voi hinh ly thuyet thi co sai khong?

Khong nhat thiet. Huong len/xuong cua PPG phu thuoc quy uoc ve hap thu/quang thong va cach plot. Dieu quan trong la co thanh phan AC co chu ky theo mach. Neu can giong hinh tham khao co the ve `-ppg_ac`.

### 15.8 Du lieu nay co dung chan doan y te khong?

Khong. Project la muc dich hoc tap/nghien cuu ky thuat. Chua co calibration, kiem dinh, cach ly y te, va thuat toan dat chuan. Khong dung de chan doan hay dieu tri.

## 16. Cac cong thuc can nho khi bao ve

### 16.1 Tan so va chu ky lay mau

```text
T = 1 / Fs
Fs_ecg = 1000 Hz -> T_ecg = 1 ms
Fs_ppg = sampleRate / sampleAverage = 100 / 4 = 25 Hz
T_ppg = 40 ms
```

### 16.2 So mau theo thoi gian do

```text
N_ecg ~= duration_s * 1000
N_ppg ~= duration_s * 25
```

### 16.3 Timestamp

```text
elapsed_us = esp_timer_get_time() - measurement_start_us
time_ms = elapsed_us / 1000
```

### 16.4 BPM

```text
BPM = 60 / T_beat_s
```

### 16.5 Wavelet threshold

```text
sigma = median(|detail_high|) / 0.6745
lambda = sigma * sqrt(2 * ln(N))
```

### 16.6 PPG AC

```text
ppg_ac = ppg_ir_raw - moving_average(ppg_ir_raw)
```

### 16.7 SpO2 demo

```text
R = (RED_AC / RED_DC) / (IR_AC / IR_DC)
SpO2 ~= 110 - 25 * R
```

## 17. Cac diem nen nhan manh khi trinh bay

- Project khong chi doc sensor, ma co co che timestamp va dump CSV co cau truc.
- ECG duoc lay mau bang timer 1 kHz, phu hop bat R peak.
- PPG duoc doc FIFO, co RED/IR, phu hop phan tich PPG va SpO2 ve sau.
- Dong bo hien tai la dong bo theo thoi gian, dung chung `measurement_start_us`.
- Xu ly tin hieu tach raw va filtered ro rang, giu du lieu raw de kiem tra lai.
- Wavelet duoc dung sau loc FFT de giam nhieu ma van giu dac trung cuc bo.
- Project co thong ke chat luong nhu expected/actual count, min/max period, clipping va overflow.

## 18. Cau tra loi mau neu thay hoi tong quat cuoi buoi

### 18.1 Neu duoc lam tiep em se cai tien gi?

Em se cai tien theo thu tu:

1. Dung interrupt pin cua MAX30102 de timestamp PPG chinh xac hon.
2. Them doc chan LO+/LO- cua AD8232 de phat hien roi dien cuc.
3. Them detect R peak, PPG peak/foot de tinh BPM va PTT.
4. Tang PPG effective sample rate neu can PTT chinh xac hon.
5. Calibration ADC va them metadata cau hinh vao CSV.
6. Toi uu loc realtime neu muon hien thi truc tiep tren ESP32/PC.

### 18.2 Diem manh nhat cua project la gi?

Diem manh la project co luong thu du lieu kha ro: sensor -> timestamp -> buffer -> CSV -> raw/filtered -> plot. ECG va PPG tuy khac tan so nhung duoc dua ve cung truc thoi gian, nen co the mo rong sang peak detection, heart rate, pulse rate va PTT.

### 18.3 Diem yeu nhat cua project la gi?

Diem yeu la dong bo PPG chua dung interrupt phan cung, nen timestamp PPG chi la uoc luong theo FIFO batch. Ngoai ra project chua co calibration va chua tinh chi so y sinh hoan chinh nhu BPM/PTT/SpO2 trong pipeline chinh.

## 19. Bang tra loi nhanh

| Cau hoi | Tra loi ngan |
|---|---|
| ECG doc bang gi? | ADC ESP32 GPIO34 tu AD8232 |
| PPG doc bang gi? | I2C FIFO tu MAX30102 |
| ECG sample rate? | 1000 Hz |
| ECG period? | 1 ms |
| PPG effective sample rate? | 25 Hz |
| PPG period? | 40 ms |
| Co dong bo 1-1 khong? | Khong, dong bo theo timestamp |
| Co do tuan tu khong? | Khong, mode BOTH do song song |
| Wavelet nao? | db4 level 3 |
| ECG loc dai nao? | 0.5-45 Hz, notch 50 Hz |
| PPG loc dai nao? | 0.5-8 Hz |
| Raw ECG la mV? | Khong, la ADC count 0-4095 |
| Raw PPG la gi? | Count 18 bit 0-262143 |
| Vi sao dump sau khi do? | De UART khong lam jitter lay mau |
| Thoi gian do max? | 120 s |
| Co tinh BPM chua? | Chua hoan chinh, moi co nen tang de tinh |
| Co dung y te khong? | Khong, chi la project hoc tap/nghien cuu |

