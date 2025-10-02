# ============================
# MODULE PHÁT HIỆN MÀU SẮC CHO TRIGGERBOT
# ============================
import cv2  # OpenCV - thư viện xử lý ảnh
import numpy as np  # NumPy - xử lý mảng số học
from config import config  # Module cấu hình chung

# ------------------ CẤU HÌNH GPU ------------------
# (Để trống - không sử dụng GPU trong phiên bản này)

# ------------------ MÔ HÌNH HSV ------------------
# Các biến toàn cục cho mô hình phát hiện màu sắc
_model = None  # Mô hình HSV (tuple chứa HSV_MIN, HSV_MAX)
_class_names = {}  # Tên các class có thể phát hiện
HSV_MIN = None  # Giá trị HSV tối thiểu để phát hiện màu
HSV_MAX = None  # Giá trị HSV tối đa để phát hiện màu


def test():
    """
    HÀM TEST - KIỂM TRA CHỨC NĂNG HSV
    - Tạo ảnh test và chuyển đổi sang HSV
    - Đảm bảo OpenCV hoạt động bình thường
    """
    print("HSV Detection test initialized")  # Thông báo khởi tạo test
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)  # Tạo ảnh đen 100x100x3
    hsv_img = cv2.cvtColor(dummy_img, cv2.COLOR_BGR2HSV)  # Chuyển BGR sang HSV
    print("HSV conversion done")  # Thông báo hoàn thành chuyển đổi


def load_model(model_path=None):
    """
    TẢI MÔ HÌNH HSV CHO PHÁT HIỆN MÀU SẮC
    - Thiết lập tham số HSV để phát hiện màu tím (purple)
    - Màu tím được sử dụng để phát hiện mục tiêu trong game
    - Trả về mô hình và tên class để sử dụng trong detection
    """
    global _model, _class_names, HSV_MIN, HSV_MAX
    config.model_load_error = ""  # Reset lỗi load model

    try:
        print("Loading HSV parameters (purple only)...")  # Thông báo đang tải tham số HSV
        # Tham số HSV cho màu tím: [H_min, S_min, V_min, H_max, S_max, V_max]
        purple = [144, 106, 172, 160, 255, 255]
        HSV_MIN = np.array([purple[0], purple[1], purple[2]], dtype=np.uint8)  # HSV tối thiểu
        HSV_MAX = np.array([purple[3], purple[4], purple[5]], dtype=np.uint8)  # HSV tối đa
        print("Loaded HSV for purple")  # Thông báo đã tải xong

        _model = (HSV_MIN, HSV_MAX)  # Lưu mô hình dưới dạng tuple
        _class_names = {"color": "Target Color"}  # Định nghĩa tên class
        config.model_classes = list(_class_names.values())  # Cập nhật config
        config.model_file_size = 0  # Không có file model (chỉ là tham số)
        return _model, _class_names  # Trả về mô hình và tên class

    except Exception as e:
        config.model_load_error = f"Failed to load HSV params: {e}"  # Lưu lỗi vào config
        _model, _class_names = None, {}  # Reset về None
        return None, {}  # Trả về None nếu lỗi


def reload_model(model_path=None):
    """
    TẢI LẠI MÔ HÌNH HSV
    - Gọi lại load_model() để tải lại tham số HSV
    - Sử dụng khi cần cập nhật cấu hình màu sắc
    """
    return load_model(model_path)


# ------------------ KIỂM TRA ĐƯỜNG THẲNG DỌC ------------------
def has_color_vertical_line(mask, x, y1, y2):
    """
    KIỂM TRA XEM CÓ ĐƯỜNG THẲNG DỌC MÀU SẮC KHÔNG
    - Kiểm tra một cột dọc tại vị trí x có chứa pixel màu sắc không
    - Sử dụng để lọc bỏ các detection giả (không phải mục tiêu thật)
    - mask: ảnh mask (grayscale)
    - x: vị trí cột cần kiểm tra
    - y1, y2: vị trí bắt đầu và kết thúc theo chiều dọc
    """
    line = mask[y1:y2, x]  # Lấy cột dọc từ mask
    return np.any(line > 0)  # Trả về True nếu có ít nhất 1 pixel > 0


# ------------------ GHÉP CÁC HÌNH CHỮ NHẬT GẦN NHAU ------------------
def merge_close_rects(rects, centers, dist_threshold=250):
    """
    GHÉP CÁC HÌNH CHỮ NHẬT GẦN NHAU THÀNH MỘT
    - Tránh phát hiện trùng lặp khi cùng một mục tiêu
    - Ghép các rectangle có overlap hoặc gần nhau
    - Tính toán center mới từ trung bình các center cũ
    """
    merged, merged_centers = [], []  # Danh sách kết quả
    used = [False] * len(rects)  # Đánh dấu rectangle đã xử lý

    for i, (r1, c1) in enumerate(zip(rects, centers)):  # Duyệt qua từng rectangle
        if used[i]:
            continue  # Bỏ qua nếu đã xử lý
        x1, y1, w1, h1 = r1  # Tọa độ rectangle hiện tại
        cx1, cy1 = c1  # Center của rectangle hiện tại
        nx, ny, nw, nh = x1, y1, w1, h1  # Rectangle mới (bắt đầu = rectangle hiện tại)
        cxs, cys = [cx1], [cy1]  # Danh sách center để tính trung bình

        for j, (r2, c2) in enumerate(zip(rects, centers)):  # So sánh với các rectangle khác
            if i == j or used[j]:
                continue  # Bỏ qua chính nó hoặc đã xử lý
            x2, y2, w2, h2 = r2  # Tọa độ rectangle so sánh
            cx2, cy2 = c2  # Center của rectangle so sánh

            # --- ĐIỀU KIỆN 1: KIỂM TRA OVERLAP ---
            if (x1 < x2 + w2 and x1 + w1 > x2) and (y1 < y2 + h2 and y1 + h1 > y2):
                # Có overlap - ghép 2 rectangle
                nx, ny = min(nx, x2), min(ny, y2)  # Tọa độ góc trên trái mới
                nw = max(nx + nw, x2 + w2) - nx  # Chiều rộng mới
                nh = max(ny + nh, y2 + h2) - ny  # Chiều cao mới
                cxs.append(cx2)  # Thêm center vào danh sách
                cys.append(cy2)
                used[j] = True  # Đánh dấu đã xử lý

        used[i] = True  # Đánh dấu rectangle hiện tại đã xử lý
        merged.append((nx, ny, nw, nh))  # Thêm rectangle mới vào kết quả
        merged_centers.append((int(np.mean(cxs)), int(np.mean(cys))))  # Center mới = trung bình

    return merged, merged_centers  # Trả về danh sách rectangle và center đã ghép


def triggerbot_detect(model, roi):
    """
    PHÁT HIỆN MÀU SẮC CHO TRIGGERBOT
    - Kiểm tra xem có màu sắc mục tiêu trong vùng ROI không
    - Sử dụng cho triggerbot - tự động bắn khi phát hiện màu
    - Trả về True nếu có ít nhất 1 pixel màu sắc, False nếu không

    Tham số:
        model : tuple (HSV_MIN, HSV_MAX) - mô hình HSV
        roi : ảnh BGR của vùng cần phân tích
    """
    if model is None or roi is None:
        return False  # Không có model hoặc ROI thì trả về False

    # Chuyển đổi sang HSV và tạo mask
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)  # Chuyển BGR sang HSV
    mask = cv2.inRange(hsv_roi, model[0], model[1])  # Tạo mask theo khoảng HSV

    # Làm sạch mask bằng phép toán hình thái học nhẹ
    kernel = np.ones((3, 3), np.uint8)  # Kernel 3x3
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)  # Đóng các lỗ hổng nhỏ

    # Trả về True nếu có ít nhất 1 pixel được phát hiện
    return np.any(mask > 0)


# ------------------ PHÁT HIỆN MÀU SẮC CHÍNH ------------------
def perform_detection(model, image):
    """
    HÀM PHÁT HIỆN MÀU SẮC CHÍNH CHO AIMBOT
    - Phát hiện các vùng màu sắc trong ảnh
    - Ghép các rectangle gần nhau thành một
    - Lọc bỏ các detection giả bằng kiểm tra đường dọc
    - Trả về danh sách mục tiêu và mask để hiển thị
    """
    if model is None:
        return None  # Không có model thì trả về None

    # Chuyển đổi ảnh sang HSV và tạo mask
    hsv_img = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)  # Chuyển BGR sang HSV
    mask = cv2.inRange(hsv_img, model[0], model[1])  # Tạo mask theo khoảng HSV

    # Làm sạch mask bằng phép toán hình thái học
    kernel = np.ones((30, 15), np.uint8)  # Kernel 30x15 (rộng hơn cao)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)  # Đóng các lỗ hổng
    mask = cv2.dilate(mask, kernel, iterations=1)  # Mở rộng vùng phát hiện

    # Tìm contours và tạo bounding rectangle
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects, centers = [], []  # Danh sách rectangle và center
    for c in contours:  # Duyệt qua từng contour
        x, y, w, h = cv2.boundingRect(c)  # Lấy bounding rectangle
        cx, cy = x + w // 2, y + h // 2  # Tính center

        # --- ĐIỀU KIỆN 2: BỎ QUA NẾU KHÔNG CÓ ĐƯỜNG DỌC MÀU SẮC ---
        if not has_color_vertical_line(mask, cx, y, y + h):
            continue  # Bỏ qua nếu không có đường dọc (có thể là detection giả)

        rects.append((x, y, w, h))  # Thêm rectangle vào danh sách
        centers.append((cx, cy))  # Thêm center vào danh sách

    # Ghép các rectangle gần nhau
    merged_rects, merged_centers = merge_close_rects(rects, centers)

    # Trả về danh sách mục tiêu và mask
    return [
        {"class": "player", "bbox": r, "confidence": 1.0} for r in merged_rects
    ], mask


# ------------------ CÁC HÀM HỖ TRỢ ------------------
def get_class_names():
    """
    LẤY TÊN CÁC CLASS CÓ THỂ PHÁT HIỆN
    - Trả về từ điển chứa tên các class
    - Sử dụng để hiển thị thông tin trong UI
    """
    return _class_names


def get_model_size(model_path=None):
    """
    LẤY KÍCH THƯỚC MÔ HÌNH
    - Trả về 0 vì không có file model (chỉ là tham số HSV)
    - Sử dụng để hiển thị thông tin trong UI
    """
    return 0
