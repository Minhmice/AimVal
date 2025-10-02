# ============================
# MAIN.PY - FILE CHÍNH CỦA PROJECT V3
# ============================
import customtkinter as ctk
import cv2
from gui import ViewerApp

if __name__ == "__main__":
    """
    ============================
    TỔNG QUAN VỀ CÁCH HOẠT ĐỘNG CỦA PROJECT V3
    ============================
    
    1. KHỞI TẠO:
    - Tạo GUI với CustomTkinter (giao diện hiện đại)
    - Khởi tạo AimTracker (logic aimbot chính)
    - Thiết lập UDP receiver để nhận video stream
    
    2. LUỒNG HOẠT ĐỘNG CHÍNH:
    - UDP Receiver: Nhận video từ game qua UDP, ghép packet thành frame JPEG
    - Decoder: Giải mã JPEG thành ảnh BGR để xử lý
    - AI Detection: Chạy YOLO để phát hiện mục tiêu (người chơi)
    - AimTracker: Tính toán chuyển động chuột để nhắm vào mục tiêu
    - Display: Hiển thị video gốc và mask detection qua OpenGL/CV2
    
    3. CÁC CHỨC NĂNG:
    - Aimbot: Tự động nhắm vào đầu đối thủ khi giữ phím
    - Triggerbot: Tự động bắn khi phát hiện màu sắc trong FOV
    - 2 chế độ: Normal (mượt mà) và Silent (ẩn)
    - Quản lý config: Lưu/tải cài đặt từ file JSON
    
    4. KIẾN TRÚC:
    - Multi-threading: Mỗi chức năng chạy trong luồng riêng
    - Thread-safe: Sử dụng lock để đồng bộ dữ liệu
    - Modular: Tách biệt các module (detection, mouse, config)
    - Real-time: Xử lý video với FPS cao (80+ FPS)
    """
    ctk.set_appearance_mode("Dark")  # Đặt chế độ tối
    app = ViewerApp()  # Tạo ứng dụng chính
    app.protocol("WM_DELETE_WINDOW", app._on_close)  # Xử lý khi đóng cửa sổ
    app.mainloop()  # Chạy vòng lặp GUI
