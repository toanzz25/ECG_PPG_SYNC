# LÝ DO CHỌN BỘ LỌC CHO TÍN HIỆU ECG VÀ PPG

## 1. Bộ lọc cho ECG

Chuỗi xử lý:

```text
ECG raw
→ trừ trung vị
→ band-pass 0,5–45 Hz
→ wavelet db4 level 3
```

### Trừ trung vị

```text
ECG_centered = ECG_raw - median(ECG_raw)
```

Mục đích:

- Đưa tín hiệu về quanh mức 0.
- Giảm thành phần DC ban đầu.
- Trung vị ít bị các đỉnh R lớn làm sai lệch hơn trung bình.

### High-pass 0,5 Hz

Mục đích:

- Giảm trôi đường nền do hô hấp.
- Giảm ảnh hưởng của chuyển động chậm và thay đổi tiếp xúc điện cực.

### Low-pass 45 Hz

Mục đích:

- Giảm nhiễu cơ và nhiễu cao tần từ ADC.
- Vẫn giữ được phức bộ QRS và đỉnh R cần thiết để tính nhịp tim.

Chương trình có điều kiện loại vùng 49–51 Hz. Tuy nhiên, do low-pass đã giới hạn ở 45 Hz nên nhiễu điện lưới 50 Hz đã nằm ngoài dải được giữ.

### Wavelet DB4 level 3

Mục đích:

- Giảm nhiễu cục bộ và các dao động nhỏ.
- Giữ các biến đổi nhanh như phức bộ QRS tốt hơn bộ lọc làm mượt mạnh.
- DB4 có dạng sóng ngắn, phù hợp để làm rõ các đặc trưng nhanh của ECG.

---

## 2. Bộ lọc cho PPG

Chuỗi xử lý:

```text
PPG IR raw
→ trừ moving average 1,2 giây
→ band-pass 0,5–8 Hz
→ wavelet db4 level 3
```

### Moving average 1,2 giây

```text
PPG_AC = PPG_raw - moving_average(PPG_raw)
```

Mục đích:

- Loại thành phần nền DC rất lớn của PPG.
- Giảm ảnh hưởng của mô, ánh sáng môi trường và tiếp xúc cảm biến.
- Giữ lại thành phần AC thay đổi theo nhịp mạch.

Với tần số PPG 25 Hz, chương trình sử dụng cửa sổ 31 mẫu, tương đương khoảng 1,24 giây.

### High-pass 0,5 Hz

Mục đích:

- Giảm trôi nền còn lại.
- Giảm chuyển động chậm của ngón tay.
- Loại các biến đổi quá chậm không thuộc nhịp mạch cần quan sát.

### Low-pass 8 Hz

Mục đích:

- Giảm nhiễu quang học và nhiễu điện tử cao tần.
- Giữ được tần số nhịp tim và hình dạng cơ bản của xung PPG.
- Phù hợp với tần số lấy mẫu hiệu dụng 25 Hz của MAX30102.

### Wavelet DB4 level 3

Mục đích:

- Giảm nhiễu cục bộ sau band-pass.
- Làm đường PPG ổn định hơn để phát hiện đỉnh.
- Hạn chế làm mất hoàn toàn hình dạng xung mạch.

---

## 3. Vì sao ECG và PPG dùng dải lọc khác nhau?

| Tín hiệu | Dải lọc | Lý do |
|---|---|---|
| ECG | 0,5–45 Hz | ECG có phức bộ QRS biến đổi nhanh nên cần giữ dải tần rộng hơn. |
| PPG | 0,5–8 Hz | PPG biến đổi chậm hơn; phần lớn thành phần cao tần là nhiễu. |

ECG được lấy mẫu ở 1.000 Hz nên có thể xử lý dải tần rộng. PPG chỉ có tần số hiệu dụng 25 Hz nên cần giới hạn dải thấp hơn.

## 4. Kết luận

- ECG cần giữ đỉnh R sắc nên dùng band-pass rộng `0,5–45 Hz` kết hợp wavelet.
- PPG có nền DC lớn nên phải trừ moving average trước khi lọc.
- PPG chỉ cần dải `0,5–8 Hz` để giữ nhịp mạch và giảm nhiễu.
- Wavelet được dùng sau band-pass để giảm thêm nhiễu cục bộ cho cả hai tín hiệu.

Các thông số này phù hợp cho mục tiêu học tập, hiển thị tín hiệu và phát hiện đỉnh. Nếu dùng cho thiết bị y tế, cần đánh giá và hiệu chuẩn trên nhiều dữ liệu thực tế.
