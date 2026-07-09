# GIẢI THÍCH TỪ DỮ LIỆU CẢM BIẾN ĐẾN GIÁ TRỊ TRỤC TUNG ECG – PPG

Tài liệu này phân tích trực tiếp phép đo:

```text
data_csv/SYNC/raw/bao-12h45_BOTH_sync_2026-07-09_12-56-23_raw.csv
```

Kết quả sau lọc được đối chiếu với:

```text
data_csv/SYNC/filtered/bao-12h45_BOTH_sync_2026-07-09_12-56-23_wavelet.csv
```

Mục tiêu là giải thích rõ:

- Giá trị thực tế được đọc từ AD8232 và MAX30102.
- Chu kỳ và timer lấy mẫu.
- Cách đồng bộ ECG với PPG.
- Cách tính baseline.
- Các bộ lọc được sử dụng.
- Cách tính giá trị đưa lên trục tung của từng đường trên đồ thị.

> Lưu ý quan trọng: giá trị trục tung hiện tại là số đếm tương đối sau xử lý. ECG chưa được đổi sang mV và PPG chưa được đổi sang đơn vị quang học tuyệt đối.

---

## 1. CẤU TRÚC DỮ LIỆU CSV

Mỗi dòng dữ liệu có dạng:

```text
person_name,time_ms,ecg_raw,ppg_red_raw,ppg_ir_raw
```

Ý nghĩa:

| Cột | Ý nghĩa |
|---|---|
| `person_name` | Tên người thực hiện phép đo. |
| `time_ms` | Thời gian tính từ lúc bắt đầu đo, đơn vị mili-giây. |
| `ecg_raw` | Giá trị ADC 12 bit đọc từ AD8232. |
| `ppg_red_raw` | Số đếm quang học của kênh LED đỏ MAX30102. |
| `ppg_ir_raw` | Số đếm quang học của kênh hồng ngoại MAX30102. |

ECG và PPG có tần số lấy mẫu khác nhau. Vì vậy:

- Hầu hết các dòng chỉ có ECG.
- Khoảng mỗi 40 ms mới có một mẫu PPG.
- Khi timestamp ECG và PPG trùng nhau, chúng được ghi chung một dòng.
- Ô không có dữ liệu được để trống.

---

## 2. SỐ LIỆU THỰC TẾ CỦA PHÉP ĐO

| Thông số | ECG | PPG |
|---|---:|---:|
| Khoảng thời gian | 0–9.999 ms | 26–9.966 ms |
| Số mẫu thực tế | 9.998 | 249 |
| Số mẫu lý thuyết trong 10 giây | 10.000 | 250 |
| Chu kỳ chủ yếu | 1 ms | 40 ms |
| Tần số hiệu dụng | Xấp xỉ 1.000 Hz | 25 Hz |
| Miền raw | 1.649–2.496 | RED: 24.090–24.541 |
|  |  | IR: 25.097–26.065 |

Phân bố khoảng thời gian giữa hai mẫu liên tiếp:

### ECG

```text
9.995 khoảng có độ dài 1 ms
2 khoảng có độ dài 2 ms
```

### PPG

```text
246 khoảng có độ dài 40 ms
2 khoảng có độ dài 50 ms
```

Nhận xét:

- ECG thiếu 2 mẫu so với 10.000 mẫu lý thuyết.
- PPG thiếu 1 mẫu so với 250 mẫu lý thuyết.
- Phần lớn timestamp vẫn đúng chu kỳ thiết kế.
- Các khoảng 2 ms hoặc 50 ms là jitter nhỏ trong quá trình đọc và lập lịch tác vụ.

---

## 3. CÁCH LẤY MẪU ECG

### 3.1. Cấu hình ADC

AD8232 đưa tín hiệu analog vào:

```text
GPIO34
ADC1_CHANNEL_6
Độ phân giải ADC: 12 bit
```

Miền ADC lý thuyết:

```text
0 đến 4.095 count
```

Giá trị ECG thực tế của phép đo:

```text
Nhỏ nhất: 1.649
Lớn nhất: 2.496
```

Tín hiệu không chạm ngưỡng 0 hoặc 4.095, vì vậy không có hiện tượng bão hòa ADC trong phép đo này.

### 3.2. Timer ECG

Tần số lấy mẫu được cấu hình:

```text
Fs_ECG = 1.000 Hz
```

Chu kỳ timer:

```text
T_ECG = 1 / Fs_ECG
      = 1 / 1.000
      = 0,001 giây
      = 1.000 micro-giây
```

ESP32 dùng `esp_timer` gọi hàm lấy mẫu định kỳ mỗi 1.000 micro-giây.

### 3.3. Trung bình 4 lần đọc ADC

Trong mỗi lần timer gọi, chương trình đọc ADC 4 lần liên tiếp:

```text
ADC_1, ADC_2, ADC_3, ADC_4
```

Một mẫu ECG được tính:

```text
ECG_raw[n] = làm_tròn((ADC_1 + ADC_2 + ADC_3 + ADC_4) / 4)
```

Mục đích:

- Giảm nhiễu ngẫu nhiên của ADC.
- Làm giá trị từng mẫu ổn định hơn.
- Không làm thay đổi tần số đầu ra 1.000 Hz.

---

## 4. CÁCH LẤY MẪU PPG

### 4.1. Cấu hình MAX30102

Các thông số chính:

```text
sampleRate = 100 mẫu/giây
sampleAverage = 4
```

Tần số hiệu dụng:

```text
Fs_PPG = sampleRate / sampleAverage
       = 100 / 4
       = 25 Hz
```

Chu kỳ PPG:

```text
T_PPG = 1 / 25
      = 0,04 giây
      = 40 ms
```

Kết quả CSV phù hợp với cấu hình này: 246 trong tổng số 248 khoảng PPG có độ dài đúng 40 ms.

### 4.2. Đọc FIFO

MAX30102 tự lấy mẫu và đưa kết quả vào FIFO.

Task ESP32 kiểm tra FIFO mỗi:

```text
5 ms
```

Một lần đọc FIFO có thể lấy nhiều mẫu. Vì vậy thời điểm ESP32 đọc FIFO không phải thời điểm sinh ra từng mẫu.

Chương trình tính tuổi của mẫu:

```text
age_ms = số_mẫu_đứng_sau × 40
```

Timestamp của mẫu:

```text
time_PPG_ms = batch_time_ms - age_ms
```

Ví dụ nếu FIFO có 3 mẫu:

```text
Mẫu mới nhất: age = 0 ms
Mẫu trước đó: age = 40 ms
Mẫu cũ nhất: age = 80 ms
```

Nhờ đó các mẫu PPG không bị gán cùng một timestamp.

---

## 5. MỐC THỜI GIAN VÀ ĐỒNG BỘ ECG – PPG

Khi bắt đầu phép đo, ESP32 lưu:

```text
measurement_start_us = esp_timer_get_time()
```

Thời gian của một mẫu được tính tương đối so với mốc này:

```text
elapsed_us = esp_timer_get_time() - measurement_start_us
time_ms = elapsed_us / 1.000
```

ECG và PPG dùng chung `measurement_start_us`.

Do đó:

- Hai tín hiệu có chung mốc thời gian 0.
- Có thể vẽ ECG và PPG trên cùng trục thời gian.
- Có thể tính độ trễ từ R-peak ECG đến đỉnh PPG.

Đối với ECG, nếu hai timestamp sau khi đổi sang ms bị trùng:

```text
time_ms_mới = time_ms_trước + 1
```

Mục đích là bảo đảm timestamp luôn tăng.

---

## 6. TRỤC HOÀNH CỦA ĐỒ THỊ

CSV lưu thời gian theo mili-giây, còn đồ thị hiển thị giây:

```text
t_giây[n] = time_ms[n] / 1.000
```

Ví dụ:

```text
time_ms = 4.236 ms
t = 4.236 / 1.000 = 4,236 giây
```

Hai đồ thị ECG và PPG dùng chung trục thời gian này.

---

## 7. BASELINE ECG VÀ ĐƯỜNG XÁM ECG

### 7.1. Baseline thực tế

Trung vị của 9.998 mẫu ECG trong file là:

```text
baseline_ECG = median(ECG_raw)
             = 1.830 count
```

Chương trình dùng trung vị thay cho trung bình vì:

- Đỉnh R có biên độ lớn.
- Nhiễu đột biến có thể kéo trung bình lệch đi.
- Trung vị ít bị ảnh hưởng bởi các giá trị quá lớn hoặc quá nhỏ.

### 7.2. Công thức đường xám ECG

Giá trị đưa lên trục tung:

```text
y_ECG_xám[n] = ECG_raw[n] - baseline_ECG
```

Với phép đo này:

```text
y_ECG_xám[n] = ECG_raw[n] - 1.830
```

### 7.3. Ví dụ bằng số liệu CSV

| `time_ms` | ECG raw | Baseline | Giá trị trục tung đường xám |
|---:|---:|---:|---:|
| 0 | 1.919 | 1.830 | 89 |
| 1.000 | 1.877 | 1.830 | 47 |
| 5.000 | 1.850 | 1.830 | 20 |
| 9.999 | 1.930 | 1.830 | 100 |

Ví dụ tại `time_ms = 0`:

```text
y = 1.919 - 1.830
  = 89 count
```

Miền giá trị thực tế của đường xám ECG:

```text
Nhỏ nhất: -181
Lớn nhất: +666
```

Đây vẫn là ADC count tương đối, chưa phải mV.

---

## 8. ĐƯỜNG HỒNG ECG SAU LỌC

Chuỗi xử lý:

```text
ECG raw
→ trừ trung vị
→ FFT band-pass 0,5–45 Hz
→ wavelet db4 level 3
→ trừ trung vị lần cuối
```

### 8.1. Đưa tín hiệu về quanh 0

```text
x[n] = ECG_raw[n] - median(ECG_raw)
```

### 8.2. Biến đổi FFT

```text
X[k] = FFT{x[n]}
```

Chỉ giữ thành phần:

```text
0,5 Hz <= f[k] <= 45 Hz
```

Các thành phần ngoài dải được đặt bằng 0:

```text
X_lọc[k] = X[k]     nếu 0,5 <= f[k] <= 45
X_lọc[k] = 0        nếu nằm ngoài dải
```

Tái tạo tín hiệu:

```text
x_bandpass[n] = IFFT{X_lọc[k]}
```

Ý nghĩa:

- Cận dưới 0,5 Hz giảm trôi đường nền chậm.
- Cận trên 45 Hz giảm nhiễu cơ và nhiễu cao tần.
- Phức bộ QRS vẫn được giữ lại.

Mã có thêm điều kiện loại vùng:

```text
49–51 Hz
```

Tuy nhiên vùng 49–51 Hz đã nằm ngoài low-pass 45 Hz, nên trong cấu hình hiện tại điều kiện notch 50 Hz gần như không làm thay đổi thêm tín hiệu.

### 8.3. Wavelet DB4 level 3

Chương trình phân rã wavelet:

```text
wavelet = db4
level = 3
```

Ước lượng nhiễu:

```text
sigma = median(|detail_cuối|) / 0,6745
```

Ngưỡng:

```text
threshold = sigma × sqrt(2 × ln(N))
```

Các hệ số detail được soft-threshold:

```text
Nếu |c| nhỏ: c bị giảm về gần 0
Nếu |c| lớn: c được giữ nhưng giảm một phần biên độ
```

Mục đích:

- Giảm nhiễu cục bộ.
- Giữ các biến đổi nhanh như phức bộ QRS tốt hơn một bộ làm mượt mạnh.

### 8.4. Giá trị cuối cùng

```text
y_ECG_hồng[n] =
ECG_wavelet[n] - median(ECG_wavelet)
```

Ví dụ thực tế:

| `time_ms` | Đường xám | Đường hồng |
|---:|---:|---:|
| 0 | 89 | 16,442 |
| 1.000 | 47 | -2,779 |
| 5.000 | 20 | 28,296 |
| 9.999 | 100 | 10,487 |

Miền đường hồng:

```text
Nhỏ nhất: -174,169
Lớn nhất: +556,017
```

> Giá trị sau FFT và wavelet không thể tính chỉ từ một mẫu raw riêng lẻ. Hai phép xử lý sử dụng quan hệ giữa nhiều mẫu trong toàn chuỗi.

---

## 9. BASELINE PPG VÀ ĐƯỜNG XÁM PPG

PPG có thành phần nền DC lớn, khoảng 25.000 count, trong khi dao động theo nhịp chỉ vài trăm count.

Nếu vẽ IR raw trực tiếp, dao động mạch sẽ khó quan sát. Vì vậy chương trình loại baseline động.

### 9.1. Ước lượng tần số từ timestamp

```text
Fs = 1.000 / median(diff(time_ms))
```

Trong file:

```text
median(diff(time_ms)) = 40 ms
Fs = 1.000 / 40
   = 25 Hz
```

### 9.2. Cửa sổ baseline 1,2 giây

```text
N_cửa_sổ = round(1,2 × Fs)
          = round(1,2 × 25)
          = 30 mẫu
```

Chương trình cần số mẫu lẻ để cửa sổ đối xứng, nên tăng thành:

```text
N_cửa_sổ = 31 mẫu
```

Cửa sổ gồm:

```text
15 mẫu trước
+ mẫu đang xét
+ 15 mẫu sau
```

### 9.3. Công thức baseline PPG

```text
trend_IR[n] =
(IR[n-15] + ... + IR[n] + ... + IR[n+15]) / 31
```

Viết ngắn:

```text
trend_IR[n] = (1 / 31) × tổng(IR[n+k])
với k từ -15 đến +15
```

Ở đầu và cuối chuỗi, khi chỉ số vượt ra ngoài dữ liệu, chương trình lặp lại mẫu biên gần nhất.

### 9.4. Thành phần AC và đường xám

```text
y_PPG_xám[n] = IR_raw[n] - trend_IR[n]
```

Đường xám có nhãn:

```text
PPG IR AC
```

Nó không phải IR raw nguyên bản.

### 9.5. Ví dụ bằng số liệu thực tế

| `time_ms` | IR raw | Trend 31 mẫu | Đường xám |
|---:|---:|---:|---:|
| 26 | 25.468 | 25.512,194 | -44,194 |
| 4.236 | 26.018 | 25.654,968 | +363,032 |
| 4.996 | 25.502 | 25.622,677 | -120,677 |

Tại `time_ms = 4.236`:

```text
y_PPG_xám = 26.018 - 25.654,968
           = 363,032 count
```

Miền đường xám PPG:

```text
Nhỏ nhất: -353,129
Lớn nhất: +363,032
```

---

## 10. ĐƯỜNG XANH PPG SAU LỌC

Chuỗi xử lý:

```text
PPG IR raw
→ trừ moving average 1,2 giây
→ FFT band-pass 0,5–8 Hz
→ wavelet db4 level 3
→ trừ trung vị
```

### 10.1. Dải tần PPG

Giới hạn trên được tính:

```text
f_trên = min(8 Hz, 0,45 × Fs)
```

Với `Fs = 25 Hz`:

```text
0,45 × 25 = 11,25 Hz
f_trên = min(8; 11,25)
       = 8 Hz
```

Dải được giữ:

```text
0,5 Hz <= f <= 8 Hz
```

Ý nghĩa:

- High-pass 0,5 Hz giảm trôi nền và chuyển động rất chậm.
- Low-pass 8 Hz giảm nhiễu quang học cao tần.
- Dải nhịp tim và hình dạng xung mạch vẫn được giữ.

Sau FFT, chương trình áp dụng wavelet `db4 level 3` giống nguyên tắc của ECG.

### 10.2. Ví dụ thực tế

| `time_ms` | Đường xám PPG AC | Đường xanh sau lọc |
|---:|---:|---:|
| 26 | -44,194 | -19,732 |
| 4.236 | +363,032 | +248,915 |
| 4.996 | -120,677 | -144,837 |

Miền đường xanh:

```text
Nhỏ nhất: -328,433
Lớn nhất: +270,797
```

---

## 11. TẠI SAO ĐƯỜNG XANH KHÔNG PHỦ HOÀN TOÀN ĐƯỜNG XÁM?

Đường xám PPG:

```text
IR raw - moving average
```

Đường xanh:

```text
đường xám
→ band-pass 0,5–8 Hz
→ wavelet soft-threshold
```

Vì vậy hai đường không bắt buộc trùng nhau.

Các nguyên nhân:

1. Band-pass loại thành phần dưới 0,5 Hz.
2. Band-pass loại thành phần trên 8 Hz.
3. Soft-threshold làm giảm các hệ số wavelet nhỏ.
4. Các đỉnh nhọn chứa nhiều thành phần cao tần bị giảm mạnh hơn.
5. DWT không bất biến theo dịch nên cực trị có thể lệch khoảng một mẫu.

Một mẫu PPG tương ứng:

```text
40 ms
```

Vì vậy một số đỉnh xanh có thể lệch khoảng 40 ms so với đỉnh xám.

---

## 12. CÁCH MATPLOTLIB CHỌN GIỚI HẠN TRỤC TUNG

Chương trình không đặt cố định:

```text
ylim
```

Matplotlib tự:

1. Tìm giá trị nhỏ nhất và lớn nhất của các đường đang vẽ.
2. Chọn khoảng trục bao phủ các giá trị đó.
3. Thêm một khoảng lề nhỏ.
4. Tạo các vạch chia dễ đọc.

Miền dữ liệu của phép đo:

| Đường | Nhỏ nhất | Lớn nhất | Đơn vị |
|---|---:|---:|---|
| ECG xám | -181 | +666 | ADC count sau trừ baseline |
| ECG hồng | -174,169 | +556,017 | Count sau lọc |
| PPG xám | -353,129 | +363,032 | IR count sau trừ trend |
| PPG xanh | -328,433 | +270,797 | Count sau lọc |

Vạch chia trên trục tung có thể rộng hơn miền trên vì Matplotlib tự thêm lề.

---

## 13. VAI TRÒ CỦA KÊNH RED

Kênh RED không được vẽ trên đồ thị PPG hiện tại.

Đường xám và đường xanh đều được tạo từ kênh IR.

Kênh RED được dùng cùng IR để tính SpO₂:

```text
DC_RED = mean(RED_raw)
DC_IR  = mean(IR_raw)
```

Thành phần AC:

```text
AC_RED = RMS(RED_raw - trend_RED)
AC_IR  = RMS(IR_raw - trend_IR)
```

Tỷ số:

```text
R = (AC_RED / DC_RED) / (AC_IR / DC_IR)
```

SpO₂ ước lượng:

```text
SpO2 = 110 - 25 × R
```

Giá trị được giới hạn:

```text
70% <= SpO2 <= 100%
```

Do đó:

- RED tham gia tính SpO₂.
- RED không trực tiếp tạo đường xám hoặc đường xanh trên plot PPG.

---

## 14. TÓM TẮT TOÀN BỘ QUÁ TRÌNH

### ECG

```text
Điện cực
→ AD8232
→ ADC 12 bit
→ trung bình 4 lần đọc
→ lấy mẫu 1.000 Hz
→ trừ baseline trung vị 1.830
→ FFT 0,5–45 Hz
→ wavelet db4 level 3
→ vẽ đường xám và đường hồng
```

### PPG

```text
LED RED và IR
→ MAX30102
→ 100 mẫu/s, average 4
→ tốc độ hiệu dụng 25 Hz
→ FIFO
→ timestamp lùi theo tuổi mẫu
→ moving average 31 mẫu
→ lấy thành phần AC
→ FFT 0,5–8 Hz
→ wavelet db4 level 3
→ vẽ đường xám và đường xanh
```

---

## 15. CÂU TRÌNH BÀY NGẮN GỌN

> Dữ liệu raw không được đưa thẳng lên đồ thị. ECG được trừ baseline trung vị, còn PPG được trừ baseline động bằng moving average 1,2 giây. Sau đó tín hiệu tiếp tục qua bộ lọc miền tần số và wavelet. Vì vậy trục tung biểu diễn mức biến thiên quanh nền của ECG và PPG, giúp quan sát phức bộ QRS và xung mạch rõ hơn.

---

## 16. LƯU Ý VỀ ĐƠN VỊ VÀ ĐỘ CHÍNH XÁC

- ECG hiện dùng ADC count, chưa phải mV.
- Muốn đổi sang mV cần biết điện áp tham chiếu ADC và hệ số khuếch đại thực tế của AD8232.
- PPG dùng số đếm quang học tương đối.
- SpO₂ đang dùng công thức thực nghiệm đơn giản.
- Muốn đạt độ chính xác y tế cần hiệu chuẩn bằng thiết bị tham chiếu.
- Kết quả của project phù hợp cho học tập và thử nghiệm xử lý tín hiệu.
