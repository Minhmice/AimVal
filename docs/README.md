# UDP MJPEG Viewer cho Raspberry Pi 5 (OBS)

Dự án nhỏ giúp nhận luồng MJPEG qua UDP từ OBS (PC) và hiển thị trên Raspberry Pi 5. Nếu có GUI (màn hình/desktop), chương trình mở cửa sổ hiển thị. Nếu chạy headless (SSH không có X11), chương trình sẽ liên tục ghi khung hình mới nhất ra file `latest_frame.jpg`.

---

## Tính năng

- Lắng nghe `udp://0.0.0.0:8080` cho MJPEG.
- Ghép lại khung JPEG từ các gói UDP (tìm marker `FFD8` → `FFD9`).
- Giải mã bằng OpenCV.
  - Có GUI → hiển thị cửa sổ "UDP Stream".
  - Headless → ghi liên tục ảnh `latest_frame.jpg`.
- Tùy chọn ghi stream ra file video (`--record out.mp4` hoặc `.avi`).

---

## Yêu cầu

- Raspberry Pi 5 (Raspberry Pi OS Bookworm trở lên)
- Python 3.11+ (được cài bởi `setup.sh`)
- `ffmpeg` (tùy chọn, dùng để test/preview)

---

## Cài đặt & chạy nhanh

### Cách A: Dùng script tự động trên Pi

```bash
# Trên Raspberry Pi 5
git clone <your-repo-url> pi-udp-mjpeg-viewer
cd pi-udp-mjpeg-viewer
bash setup.sh
```

Script sẽ:

- Cập nhật hệ thống, cài `python3-full python3-venv python3-pip ffmpeg`.
- Tạo `venv/` và cài `numpy`, `imutils`, `opencv-python`.
- Tạo `udp_viewer.py` nếu chưa có.
- Chạy `python udp_viewer.py`.

### Cách B: Thực hiện thủ công

```bash
# Trên Raspberry Pi 5
git clone <your-repo-url> pi-udp-mjpeg-viewer
cd pi-udp-mjpeg-viewer
python3 -m venv venv
source venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python udp_viewer.py
```

---

## Gửi MJPEG từ OBS

Có nhiều cách, dưới đây là 2 cách phổ biến:

- OBS (Custom Output - FFmpeg):

  - Settings → Output → Output Mode: Advanced.
  - Recording → Type: Custom Output (FFmpeg).
  - FFmpeg Output Type: Output to URL.
  - Filepath or URL: `udp://<pi-ip>:8080?pkt_size=1316&overrun_nonfatal=1&fifo_size=50000000`
  - Encoder: `mjpeg` (M-JPEG).
  - Start Recording.

- Test nhanh bằng `ffmpeg` trên PC (không cần OBS):

```bash
ffmpeg -f avfoundation -framerate 30 -i 0 \
  -f mjpeg -q:v 5 -bsf:v mjpegadump -fflags +genpts \
  -flags +global_header -muxdelay 0 -muxpreload 0 \
  -f mpegts udp://<pi-ip>:8080?pkt_size=1316&overrun_nonfatal=1&fifo_size=50000000
```

Tùy hệ điều hành, bạn cần đổi input (`-i`). Mấu chốt là gửi MJPEG tới UDP port `8080` của Pi.

---

## Chạy chương trình xem

```bash
python udp_viewer.py
```

- Terminal sẽ in: `Listening on udp://0.0.0.0:8080`.
- Có GUI → hiện cửa sổ "UDP Stream".
- SSH/headless → ảnh sẽ được lưu liên tục vào `latest_frame.jpg`.

### Ghi video ra file (tùy chọn)

```bash
# Ghi MP4 (mặc định dùng fourcc mp4v)
python udp_viewer.py --record out.mp4

# Ghi AVI (khuyến nghị fourcc XVID)
python udp_viewer.py --record out.avi --fourcc XVID

# Điều chỉnh FPS cho file đầu ra (mặc định 30)
python udp_viewer.py --record out.mp4 --fps 25

# Chạy headless cưỡng bức (không mở cửa sổ)
python udp_viewer.py --no-gui --record out.mp4
```

Lưu ý: nếu MP4 không mở được (thiếu codec), hãy dùng `.avi` với `--fourcc XVID`.

### Ghi chú GUI vs SSH headless

- Chạy trực tiếp trên Pi có màn hình/desktop → dùng `cv2.imshow`.
- Chạy qua SSH không có X11/display:
  - Khuyến nghị dùng `ffplay` để xem nhanh luồng thô:
    ```bash
    ffplay udp://@:8080
    ```
  - Hoặc dùng OpenCV headless để giảm phụ thuộc GUI:
    ```bash
    pip uninstall -y opencv-python
    pip install opencv-python-headless
    ```
- Bật X11 forwarding khi SSH để forward cửa sổ GUI:
  ```bash
  ssh -XC user@<pi-ip>
  ```
  Sau đó chạy `python udp_viewer.py`, cửa sổ sẽ được forward.

---

## Cấu trúc dự án

```
.
├─ udp_viewer.py        # Nhận & hiển thị MJPEG qua UDP; hỗ trợ ghi video
├─ run_tracker.py       # Entry chạy tracker + makcu controller
├─ aimval_tracker/      # Gói module cho pipeline theo component
│  ├─ __init__.py
│  ├─ config.py         # Dataclass cấu hình
│  ├─ frame_source.py   # Nguồn khung hình (UDP MJPEG / video / capture)
│  ├─ tracker.py        # Tracker HSV + contour
│  ├─ mapping.py        # Tuyến tính & homography mapping
│  ├─ smoothing.py      # EMA, deadzone, velocity clamp
│  ├─ controller.py     # Async Makcu controller wrapper
│  └─ utils.py          # Tiện ích chung (timing, overlay, roi)
├─ setup.sh             # Script cài đặt nhanh trên Raspberry Pi 5
├─ requirements.txt     # Dependencies Python
├─ .gitignore           # Bỏ qua venv, cache, media tạm
└─ README.md            # Tài liệu
```

---

## Tracker + Makcu (PC1 nhận stream, điều khiển chuột PC2)

### Cài đặt

```bash
pip install -r requirements.txt
```

Đảm bảo thiết bị Makcu đã cắm điều khiển vào PC2 và PC1 điều khiển qua serial (Option A). Nếu dùng Option B, chạy lib `makcu` trên PC2 và chỉ stream toạ độ từ PC1.

### Chạy nhanh

```bash
python run_tracker.py --udp-host 0.0.0.0 --udp-port 8080 \
  --h-low 0 --s-low 120 --v-low 120 --h-high 10 --s-high 255 --v-high 255 \
  --screen 1920x1080 --overlay --scale 0.8
```

Các tham số chính:
- `--roi x,y,w,h`: bật ROI để hạn chế vùng tìm kiếm.
- `--mapping linear|homography`: ánh xạ tuyến tính hoặc qua homography.
- `--homography x1,y1;...;x4,y4`: nguồn 4 điểm khi dùng homography (đích là bốn góc màn hình).
- `--ema`, `--deadzone`, `--max-step`: làm mượt và giới hạn bước.
- `--tick-hz`: tần số điều khiển makcu (mặc định 240Hz).

Nhấn `q` để thoát cửa sổ hiển thị.

---

## Xử lý sự cố

- Không thấy cửa sổ:
  - Kiểm tra biến display (`echo $DISPLAY`). Nếu rỗng, đang headless.
  - Thử `ssh -XC user@<pi-ip>` để bật X11 forwarding.
- Giật/lỗi frame:
  - Giảm độ phân giải/fps trong OBS.
  - Điều chỉnh `pkt_size`/`fifo_size` trong URL.
- Lỗi quyền thực thi `setup.sh`:
  - `chmod +x setup.sh` rồi chạy `bash setup.sh`.

---

## License

MIT
