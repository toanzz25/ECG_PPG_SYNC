# README VER3 - Cong thuc tinh cac chi so tu ECG va PPG

Tai lieu nay tong hop cach tinh cac gia tri hien thi trong panel `Derived metrics` cua giao dien `monitor.py`.

> Luu y: Cac thong so BPM, HRV, PTT, SpO2 va PI trong chuong trinh la gia tri uoc luong phuc vu hoc tap/thi nghiem. Khong dung thay the thiet bi y te da hieu chuan.

## 1. Du lieu dau vao

Moi mau du lieu dong bo co dang:

```text
time_ms, ecg_raw, ppg_red_raw, ppg_ir_raw
```

Trong do:

- `time_ms`: moc thoi gian tinh bang mili-giay.
- `ecg_raw`: tin hieu ECG doc tu AD8232.
- `ppg_red_raw`: tin hieu PPG kenh LED do cua MAX30102.
- `ppg_ir_raw`: tin hieu PPG kenh hong ngoai IR cua MAX30102.

## 2. Tien xu ly tin hieu

### 2.1. ECG da loc

Tin hieu ECG duoc xu ly theo cac buoc:

1. Lay trung vi lam baseline va dua tin hieu ve quanh 0:

```text
ecg_centered[n] = ecg_raw[n] - median(ecg_raw)
```

2. Loc mien tan so bang FFT:

```text
0.5 Hz <= f <= 45 Hz
```

3. Loai nhieu dien luoi 50 Hz bang notch:

```text
49 Hz <= f <= 51 Hz
```

4. Khu nhieu bang wavelet:

```text
wavelet = db4
level = 3
threshold = sigma * sqrt(2 * ln(N))
sigma = median(abs(detail_last)) / 0.6745
```

5. Dua tin hieu sau loc ve quanh 0:

```text
ecg_filtered[n] = ecg_wavelet[n] - median(ecg_wavelet)
```

### 2.2. PPG da loc

Tin hieu PPG IR duoc xu ly theo cac buoc:

1. Uoc luong tan so lay mau PPG tu timestamp:

```text
Fs = 1000 / median(diff(time_ms))
```

2. Tinh thanh phan AC bang cach tru xu huong cham:

```text
trend[n] = moving_average(ppg_ir_raw, window = 1.2 s)
ppg_ac[n] = ppg_ir_raw[n] - trend[n]
```

3. Loc mien tan so bang FFT:

```text
0.5 Hz <= f <= min(8 Hz, 0.45 * Fs)
```

4. Khu nhieu bang wavelet `db4 level 3`.

5. Dua tin hieu sau loc ve quanh 0:

```text
ppg_filtered[n] = ppg_wavelet[n] - median(ppg_wavelet)
```

## 3. Phat hien dinh ECG va PPG

### 3.1. Dinh R ECG

Chuong trinh phat hien dinh tren bien do tuyet doi cua ECG da loc:

```text
ecg_score[n] = abs(ecg_filtered[n])
```

Nguong thich nghi:

```text
MAD = 1.4826 * median(abs(x - median(x)))
threshold = max(median(x) + 2.8 * MAD, percentile_70(x))
```

Mot mau duoc xem la ung vien dinh neu:

```text
x[n] >= x[n-1]
x[n] >  x[n+1]
x[n] >  threshold
```

Khoang cach toi thieu giua hai dinh ECG:

```text
min_distance = 0.28 s
```

### 3.2. Dinh PPG

PPG co the dao pha tuy cach dat cam bien, vi vay chuong trinh thu ca hai huong:

```text
positive peaks:  ppg_filtered
negative peaks: -ppg_filtered
```

Neu co ECG, chuong trinh chon tap dinh PPG co so luong gan voi so dinh ECG hon. Neu khong co ECG, chon huong co nhieu dinh hop le hon.

Khoang cach toi thieu giua hai dinh PPG:

```text
min_distance = 0.35 s
```

## 4. BPM - Nhip tim tuc thoi

Sau khi co cac dinh R cua ECG, tinh khoang RR:

```text
RR_i = t_R_i - t_R_(i-1)
```

Don vi cua `RR_i` la mili-giay.

Chi nhan RR hop le trong khoang:

```text
300 ms <= RR_i <= 2000 ms
```

BPM tuc thoi duoc tinh tu khoang RR cuoi cung:

```text
BPM = 60000 / RR_last
```

Neu khong co du dinh ECG, chuong trinh fallback sang dinh PPG:

```text
BPM = 60000 / PP_interval_last
```

## 5. HRV - Bien thien nhip tim

HRV trong chuong trinh gom hai chi so co ban: `SDNN` va `RMSSD`.

### 5.1. SDNN

SDNN la do lech chuan cua cac khoang RR hop le:

```text
mean_RR = sum(RR_i) / N
SDNN = sqrt( sum((RR_i - mean_RR)^2) / (N - 1) )
```

Don vi:

```text
ms
```

Y nghia:

- SDNN lon hon thuong cho thay bien thien nhip tim cao hon.
- SDNN qua thap co the cho thay tin hieu it bien thien hoac qua trinh phat hien dinh chua tot.

### 5.2. RMSSD

RMSSD dua tren sai khac lien tiep giua cac khoang RR:

```text
diff_i = RR_i - RR_(i-1)
RMSSD = sqrt( sum(diff_i^2) / (N - 1) )
```

Don vi:

```text
ms
```

Y nghia:

- RMSSD phan anh bien thien ngan han cua nhip tim.
- RMSSD can it nhat 3 dinh R de co toi thieu 2 khoang RR.

## 6. PTT - Pulse Transit Time

PTT la thoi gian truyen mach tu hoat dong dien tim ECG den song mach PPG.

Voi moi dinh R ECG, tim dinh PPG dau tien xuat hien sau no:

```text
PTT_i = t_PPG_peak_i - t_ECG_R_i
```

Chi chap nhan cap ECG-PPG neu:

```text
80 ms <= PTT_i <= 600 ms
```

Gia tri hien thi la trung vi cua cac cap hop le:

```text
PTT = median(PTT_i)
```

Don vi:

```text
ms
```

## 7. SpO2 - Do bao hoa oxy mau uoc luong

SpO2 duoc uoc luong tu ti so giua thanh phan AC/DC cua kenh do va kenh IR.

Thanh phan DC:

```text
DC_red = mean(ppg_red_raw)
DC_ir  = mean(ppg_ir_raw)
```

Thanh phan AC tinh bang RMS sau khi tru xu huong:

```text
AC_red = RMS(ppg_red_raw - trend_red)
AC_ir  = RMS(ppg_ir_raw  - trend_ir)
```

Trong do:

```text
RMS(x) = sqrt(mean(x^2))
```

Ti so ratio-of-ratios:

```text
R = (AC_red / DC_red) / (AC_ir / DC_ir)
```

Cong thuc uoc luong SpO2 dang dung:

```text
SpO2 = 110 - 25 * R
```

Sau do gioi han gia tri hien thi:

```text
70% <= SpO2 <= 100%
```

Luu y: Cong thuc nay can hieu chuan thuc nghiem neu muon dung nhu mot may do SpO2 thuc te.

## 8. PI - Perfusion Index

PI la chi so tuoi mau, tinh tu ti le giua bien do AC va thanh phan DC cua PPG IR:

```text
PI = 100 * AC_ir / DC_ir
```

Don vi:

```text
%
```

Y nghia:

- PI cao hon thuong cho thay tin hieu PPG co bien do mach ro hon.
- PI qua thap co the do ngon tay dat chua chat, cam bien lech, anh sang ngoai nhieu, hoac tuan hoan ngoai vi yeu.

## 9. Dieu kien du lieu de hien thi

Bang tom tat:

| Chi so | Can du lieu | Cong thuc chinh | Don vi |
| --- | --- | --- | --- |
| BPM | ECG hoac PPG peaks | `60000 / interval_last` | bpm |
| SDNN | ECG RR intervals | `std(RR)` | ms |
| RMSSD | ECG RR intervals | `sqrt(mean(diff(RR)^2))` | ms |
| PTT | ECG peaks + PPG peaks | `median(t_PPG - t_ECG)` | ms |
| SpO2 | PPG RED + PPG IR | `110 - 25 * R` | % |
| PI | PPG IR | `100 * AC_ir / DC_ir` | % |

Neu khong du du lieu, giao dien hien:

```text
--
```

## 10. Vi tri code lien quan

Cac ham chinh trong `monitor.py`:

- `compute_filtered(...)`: tinh ECG/PPG da loc.
- `detect_peaks(...)`: phat hien dinh tren tin hieu da loc.
- `compute_derived_metrics(...)`: tinh BPM, SDNN, RMSSD, PTT, SpO2 va PI.
- `update_metrics_panel(...)`: cap nhat cac gia tri len UI.

