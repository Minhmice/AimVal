# ============================
# MODULE GUI - GIAO DIỆN NGƯỜI DÙNG
# ============================
# File này chứa giao diện người dùng chính của ứng dụng aimbot
# Sử dụng CustomTkinter để tạo giao diện hiện đại và đẹp mắt
# Quản lý tất cả các tab cài đặt: General, Aimbot, Triggerbot, Anti-Recoil, Config
# Tích hợp với các module khác: aim, anti_recoil, viewer, esp

import customtkinter as ctk  # Thư viện giao diện hiện đại (CustomTkinter)
import tkinter as tk  # Thư viện giao diện cơ bản (Tkinter)
import os  # Hệ thống file và thư mục
import json  # Xử lý file cấu hình JSON
import subprocess  # Chạy các lệnh hệ thống
import sys  # Hệ thống và tham số dòng lệnh
from config import config  # Module cấu hình toàn cục
from viewer import (  # Module hiển thị video và UDP
    _LatestBytesStore,  # Lưu trữ dữ liệu UDP mới nhất
    _Decoder,  # Giải mã JPEG từ UDP
    _Receiver,  # Nhận dữ liệu UDP
    SimpleFrameStore,  # Lưu trữ frame đơn giản
    DisplayThread,  # Luồng hiển thị video
)
from aim import AimTracker  # Module aimbot chính
from anti_recoil import AntiRecoil  # Module chống giật súng
from esp import DetectionEngine  # Detection Engine chính

# ========== MAPPING CÁC NÚT CHUỘT ==========
# Từ điển chuyển đổi mã nút chuột thành tên hiển thị
# Sử dụng trong các dropdown chọn phím aim và triggerbot
BUTTONS = {
    0: "Left Mouse Button",  # Nút chuột trái
    1: "Right Mouse Button",  # Nút chuột phải
    2: "Middle Mouse Button",  # Nút chuột giữa (scroll)
    3: "Side Mouse 4 Button",  # Nút phụ chuột 4 (bên trái dưới)
    4: "Side Mouse 5 Button",  # Nút phụ chuột 5 (bên phải trên)
}


class ViewerApp(ctk.CTk):
    """
    ỨNG DỤNG GUI CHÍNH - GIAO DIỆN NGƯỜI DÙNG
    Đây là lớp chính chứa toàn bộ giao diện người dùng của ứng dụng aimbot:
    - Sử dụng CustomTkinter cho giao diện hiện đại và đẹp mắt
    - Quản lý cấu hình, kết nối UDP, và hiển thị video
    - Tích hợp aimbot, triggerbot, anti-recoil và các tùy chọn khác
    - Hỗ trợ lưu/tải cấu hình từ file JSON
    - Quản lý các tab cài đặt khác nhau
    """

    def __init__(self):
        """
        CONSTRUCTOR - KHỞI TẠO GIAO DIỆN CHÍNH
        Thiết lập cửa sổ, các widget, và kết nối với các module khác
        """
        super().__init__()
        self.title(
            "AimVal V3.1"
        )  # Tiêu đề cửa sổ ứng dụng        
        self.geometry("600x800")      # Kích thước cửa sổ (rộng x cao)

        # ========== TỪ ĐIỂN ĐỒNG BỘ UI VỚI CONFIG ==========
        # Các từ điển để quản lý đồng bộ giữa giao diện và cấu hình
        self._slider_widgets = (
            {}
        )  # key -> {"slider": widget, "label": widget, "min":..., "max":...}
        self._checkbox_vars = {}  # key -> tk.BooleanVar (cho checkbox)
        self._option_widgets = {}  # key -> CTkOptionMenu (cho dropdown)

        # ========== TRẠNG THÁI UDP VÀ VIDEO ==========
        # Các biến quản lý kết nối UDP và xử lý video
        self.receiver = None  # Đối tượng nhận dữ liệu UDP
        self.rx_store = _LatestBytesStore()  # Lưu trữ dữ liệu UDP mới nhất
        self.decoder = _Decoder()  # Giải mã JPEG từ UDP stream
        self.last_decoded_seq = -1  # Số thứ tự frame cuối cùng đã giải mã
        self.last_bgr = None  # Ảnh BGR cuối cùng (để cache)
        self.connected = False  # Trạng thái kết nối UDP

        # ========== TẠO THANH TIÊU ĐỀ TÙY CHỈNH ==========
        # Loại bỏ thanh tiêu đề mặc định và tạo thanh tiêu đề tùy chỉnh
        self.title_bar = ctk.CTkFrame(
            self,
            height=30,
            corner_radius=0,  # Frame thanh tiêu đề (cao 30px, góc vuông)
        )
        self.title_bar.pack(
            fill="x", side="top"
        )  # Đặt ở trên cùng, kéo dài theo chiều ngang

        self.title_label = ctk.CTkLabel(
            self.title_bar, text="Oustider", anchor="w"  # Label tiêu đề (căn trái)
        )
        self.title_label.pack(side="left", padx=10)  # Đặt bên trái với padding 10px

        # ========== THIẾT LẬP KÉO THẢ CỬA SỔ ==========
        # Làm cho thanh tiêu đề có thể kéo thả để di chuyển cửa sổ
        self.title_bar.bind(
            "<Button-1>", self.start_move
        )  # Bắt đầu kéo (nhấn chuột trái)
        self.title_bar.bind(
            "<B1-Motion>", self.do_move
        )  # Thực hiện kéo (di chuyển chuột)

        # ========== CÁC STORE DÙNG CHUNG CHO HIỂN THỊ ==========
        # Các store để lưu trữ và chia sẻ dữ liệu giữa các luồng
        self.vision_store = SimpleFrameStore()  # Lưu ảnh gốc để hiển thị
        self.mask_store = SimpleFrameStore()  # Lưu mask để hiển thị
        self.display_thread = None  # Luồng hiển thị video
        self.use_gl = False  # Có sử dụng OpenGL không

        # ========== KHỞI TẠO CÁC MODULE CHÍNH ==========
        # Tạo DetectionEngine trước (trung tâm detection)
        self.detection_engine = DetectionEngine()  # Tạo Detection Engine
        
        # Tạo các module chính của ứng dụng
        self.tracker = AimTracker(app=self, detection_engine=self.detection_engine, target_fps=80)  # Tạo aimbot với DetectionEngine
        self.anti_recoil = AntiRecoil(app=self)  # Tạo anti-recoil

        # ========== TẠO GIAO DIỆN TAB ==========
        # Tạo TabView để quản lý các tab cài đặt khác nhau
        self.tabview = ctk.CTkTabview(self)  # Tạo TabView chính
        self.tabview.pack(expand=True, fill="both", padx=20, pady=20)  # Đặt và padding

        # Tạo các tab cài đặt
        self.tab_general = self.tabview.add(
            "General"
        )  # Tab cài đặt chung (UDP, DPI, Sensitivity)
        self.tab_aimbot = self.tabview.add(
            "Aimbot"
        )  # Tab cài đặt aimbot (tốc độ, FOV, smoothing)
        self.tab_tb = self.tabview.add(
            "Triggerbot"
        )  # Tab cài đặt triggerbot (delay, FOV)
        self.tab_ar = self.tabview.add(
            "Anti-Recoil"
        )  # Tab cài đặt anti-recoil (giật súng)
        self.tab_config = self.tabview.add("Config")  # Tab quản lý config (lưu/tải)

        # ========== XÂY DỰNG CÁC TAB GIAO DIỆN ==========
        # Xây dựng nội dung cho từng tab
        self._build_general_tab()  # Xây dựng tab General
        self._build_aimbot_tab()  # Xây dựng tab Aimbot
        self._build_tb_tab()  # Xây dựng tab Triggerbot
        self._build_ar_tab()  # Xây dựng tab Anti-Recoil
        self._build_config_tab()  # Xây dựng tab Config

        # ========== THIẾT LẬP POLLING VÀ CẤU HÌNH ==========
        # Polling trạng thái kết nối mỗi 500ms
        self.after(
            500, self._update_connection_status_loop
        )  # Cập nhật trạng thái mỗi 500ms
        self._load_initial_config()  # Tải cấu hình ban đầu từ file

    # ========== CÁC HÀM HỖ TRỢ ĐỒNG BỘ UI ==========
    def _register_slider(self, key, slider, label, vmin, vmax, is_float):
        """
        HÀM ĐĂNG KÝ SLIDER VÀO TỪ ĐIỂN
        Đăng ký slider vào từ điển để đồng bộ với config
        - key: tên tham số trong config (ví dụ: "normal_x_speed")
        - slider: widget slider (CTkSlider)
        - label: widget label hiển thị giá trị (CTkLabel)
        - vmin, vmax: giá trị min/max của slider
        - is_float: có phải số thực không (True/False)
        """
        self._slider_widgets[key] = {
            "slider": slider,  # Widget slider
            "label": label,  # Widget label hiển thị giá trị
            "min": vmin,  # Giá trị tối thiểu
            "max": vmax,  # Giá trị tối đa
            "is_float": is_float,  # Có phải số thực không
        }

    def _load_initial_config(self):
        """
        HÀM TẢI CẤU HÌNH BAN ĐẦU
        Tải cấu hình từ file configs/default.json khi khởi động ứng dụng:
        - Đọc file configs/default.json nếu có
        - Áp dụng cài đặt vào UI và config toàn cục
        - Reload mô hình AI nếu cần thiết
        - Xử lý lỗi nếu file không tồn tại hoặc bị lỗi
        """
        try:
            import json, os
            from detection import reload_model

            if os.path.exists(
                "v3.0_outsider/configs/default.json"
            ):  # Kiểm tra file config có tồn tại
                with open("configs/default.json", "r") as f:
                    data = json.load(f)  # Đọc dữ liệu JSON từ file

                self._apply_settings(data)  # Áp dụng cài đặt vào UI và config
                print("Default config loaded successfully")
            else:
                print("File configs/default.json not found, using default settings")
        except Exception as e:
            print(f"Error loading initial config: {e}")  # Print error if any

    def _set_slider_value(self, key, value):
        """
        HÀM ĐẶT GIÁ TRỊ CHO SLIDER
        Đặt giá trị cho slider và cập nhật label hiển thị
        - key: tên tham số trong config
        - value: giá trị mới cần đặt
        """
        if key not in self._slider_widgets:
            return  # Slider không tồn tại thì bỏ qua

        w = self._slider_widgets[key]  # Lấy thông tin slider
        vmin, vmax = w["min"], w["max"]  # Lấy giá trị min/max
        is_float = w["is_float"]  # Có phải số thực không

        # Chuyển đổi và giới hạn giá trị
        try:
            v = float(value) if is_float else int(round(float(value)))
        except Exception:
            return  # Lỗi chuyển đổi thì bỏ qua

        v = max(vmin, min(v, vmax))  # Giới hạn giá trị trong khoảng [vmin, vmax]
        w["slider"].set(v)  # Đặt giá trị cho slider

        # Cập nhật label hiển thị
        txt = (
            f"{key.replace('_', ' ').title()}: {v:.2f}"
            if is_float
            else f"{key.replace('_', ' ').title()}: {int(v)}"
        )
        # Giữ nguyên phần đầu của label nếu đã có (ví dụ: "X Speed")
        current = w["label"].cget("text")
        prefix = current.split(":")[0] if ":" in current else txt.split(":")[0]
        w["label"].configure(
            text=f"{prefix}: {v:.2f}" if is_float else f"{prefix}: {int(v)}"
        )

    def _set_checkbox_value(self, key, value_bool):
        """
        HÀM ĐẶT GIÁ TRỊ CHO CHECKBOX
        Đặt giá trị checked/unchecked cho checkbox
        - key: tên tham số trong config
        - value_bool: giá trị boolean (True/False)
        """
        var = self._checkbox_vars.get(key)
        if var is not None:
            var.set(bool(value_bool))  # Đặt giá trị cho BooleanVar

    def _set_option_value(self, key, value_str):
        """
        HÀM ĐẶT GIÁ TRỊ CHO OPTION MENU
        Đặt giá trị được chọn cho dropdown menu
        - key: tên tham số trong config
        - value_str: giá trị string cần đặt
        """
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))  # Đặt giá trị cho OptionMenu

    def _set_btn_option_value(self, key, value_str):
        """
        HÀM ĐẶT GIÁ TRỊ CHO BUTTON OPTION MENU
        Đặt giá trị cho dropdown chọn nút chuột
        - key: tên tham số trong config
        - value_str: tên nút chuột cần đặt
        """
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))  # Đặt giá trị cho OptionMenu

    # ========== TAB CONFIG - QUẢN LÝ CẤU HÌNH ==========
    def _build_config_tab(self):
        """
        HÀM XÂY DỰNG TAB CONFIG
        Tạo giao diện quản lý cấu hình:
        - Dropdown chọn config
        - Các nút lưu/tải config
        - Textbox hiển thị log
        """
        os.makedirs("configs", exist_ok=True)  # Tạo thư mục configs nếu chưa có

        # Label hướng dẫn
        ctk.CTkLabel(self.tab_config, text="Chọn cấu hình:").pack(pady=5, anchor="w")

        # Dropdown chọn config
        self.config_option = ctk.CTkOptionMenu(
            self.tab_config, values=[], command=self._on_config_selected
        )
        self.config_option.pack(pady=5, fill="x")

        # Các nút chức năng
        ctk.CTkButton(self.tab_config, text="Lưu", command=self._save_config).pack(
            pady=10, fill="x"
        )
        ctk.CTkButton(
            self.tab_config, text="Tạo mới", command=self._save_new_config
        ).pack(pady=5, fill="x")
        ctk.CTkButton(
            self.tab_config, text="Tải config", command=self._load_selected_config
        ).pack(pady=5, fill="x")

        # Textbox hiển thị log
        self.config_log = ctk.CTkTextbox(self.tab_config, height=120)
        self.config_log.pack(pady=10, fill="both", expand=True)

        self._refresh_config_list()  # Làm mới danh sách config

    def start_move(self, event):
        """
        HÀM BẮT ĐẦU KÉO CỬA SỔ
        Lưu vị trí chuột khi bắt đầu kéo cửa sổ
        - event: sự kiện chuột
        """
        self._x = event.x  # Lưu vị trí X của chuột
        self._y = event.y  # Lưu vị trí Y của chuột

    def do_move(self, event):
        """
        HÀM THỰC HIỆN KÉO CỬA SỔ
        Di chuyển cửa sổ theo chuột khi đang kéo
        - event: sự kiện di chuyển chuột
        """
        x = self.winfo_pointerx() - self._x  # Tính vị trí X mới
        y = self.winfo_pointery() - self._y  # Tính vị trí Y mới
        self.geometry(f"+{x}+{y}")  # Di chuyển cửa sổ đến vị trí mới

    def _get_current_settings(self):
        """
        HÀM LẤY CẤU HÌNH HIỆN TẠI
        Lấy tất cả cài đặt hiện tại từ config và trả về dạng dictionary
        Bao gồm tất cả tham số: aimbot, triggerbot, anti-recoil, UDP, v.v.
        """
        return {
            # ========== CÀI ĐẶT AIMBOT ==========
            "normal_x_speed": getattr(config, "normal_x_speed", 0.5),        # Tốc độ X aimbot
            "normal_y_speed": getattr(config, "normal_y_speed", 0.5),        # Tốc độ Y aimbot
            "normalsmooth": getattr(config, "normalsmooth", 10),             # Độ mượt mà
            "normalsmoothfov": getattr(config, "normalsmoothfov", 10),       # FOV smoothing
            "fovsize": getattr(config, "fovsize", 300),                      # Kích thước FOV aimbot
            
            # ========== CÀI ĐẶT CHUỘT VÀ ĐỘ NHẠY ==========
            "mouse_dpi": getattr(config, "mouse_dpi", 800),                  # DPI chuột
            "in_game_sens": getattr(config, "in_game_sens", 7),              # Độ nhạy trong game
            
            # ========== CÀI ĐẶT TRIGGERBOT ==========
            "tbfovsize": getattr(config, "tbfovsize", 70),                   # FOV triggerbot
            "tbdelay": getattr(config, "tbdelay", 0.08),                     # Độ trễ triggerbot
            "trigger_fire_rate_ms": getattr(config, "trigger_fire_rate_ms", 100),  # Tốc độ bắn triggerbot
            "color": getattr(config, "color", "yellow"),                     # Màu sắc phát hiện
            
            # ========== CÀI ĐẶT CHUNG ==========
            "mode": getattr(config, "mode", "Normal"),                       # Chế độ aimbot
            "enableaim": getattr(config, "enableaim", False),                # Bật/tắt aimbot
            "enabletb": getattr(config, "enabletb", False),                  # Bật/tắt triggerbot
            
            # ========== CÀI ĐẶT PHÍM ==========
            "aim_button_1": getattr(config, "aim_button_1", 1),              # Phím aim 1
            "aim_button_2": getattr(config, "aim_button_2", 2),              # Phím aim 2
            "trigger_button": getattr(config, "trigger_button", 1),          # Phím triggerbot
            
            # ========== CÀI ĐẶT ANTI-RECOIL ==========
            "anti_recoil_enabled": getattr(config, "anti_recoil_enabled", False),  # Bật/tắt anti-recoil
            "anti_recoil_x": getattr(config, "anti_recoil_x", 0),            # Giật X
            "anti_recoil_y": getattr(config, "anti_recoil_y", 0),            # Giật Y
            "anti_recoil_fire_rate": getattr(config, "anti_recoil_fire_rate", 100),  # Tốc độ bắn
            "anti_recoil_hold_time": getattr(config, "anti_recoil_hold_time", 0),    # Thời gian giữ
            "anti_recoil_only_triggering": getattr(config, "anti_recoil_only_triggering", True),  # Chỉ khi bắn
            "anti_recoil_scale_ads": getattr(config, "anti_recoil_scale_ads", 1.0),  # Tỷ lệ ADS
            "anti_recoil_smooth_segments": getattr(config, "anti_recoil_smooth_segments", 2),  # Đoạn mượt
            "anti_recoil_smooth_scale": getattr(config, "anti_recoil_smooth_scale", 0.25),  # Tỷ lệ mượt
            "anti_recoil_jitter_x": getattr(config, "anti_recoil_jitter_x", 0),  # Jitter X
            "anti_recoil_jitter_y": getattr(config, "anti_recoil_jitter_y", 0),  # Jitter Y
            "anti_recoil_ads_key": getattr(config, "anti_recoil_ads_key", 1),  # Phím ADS
            "anti_recoil_trigger_key": getattr(config, "anti_recoil_trigger_key", 0),  # Phím bắn
        }

    def _apply_settings(self, data, config_name=None):
        """
        HÀM ÁP DỤNG CẤU HÌNH
        Áp dụng một dictionary cài đặt lên config toàn cục, tracker và UI:
        - Cập nhật config toàn cục
        - Cập nhật tracker và anti-recoil
        - Cập nhật tất cả UI widgets (slider, checkbox, dropdown)
        - Reload mô hình AI nếu cần thiết
        """
        try:
            # ========== ÁP DỤNG LÊN CONFIG TOÀN CỤC ==========
            for k, v in data.items():
                setattr(config, k, v)  # Đặt thuộc tính cho config

            # ========== ÁP DỤNG LÊN TRACKER VÀ ANTI-RECOIL ==========
            for k, v in data.items():
                if hasattr(self.tracker, k):
                    setattr(self.tracker, k, v)  # Cập nhật tracker nếu có thuộc tính
                if hasattr(self.anti_recoil, k):
                    setattr(self.anti_recoil, k, v)  # Cập nhật anti-recoil nếu có thuộc tính

            # ========== CẬP NHẬT CÁC SLIDER ==========
            for k, v in data.items():
                if k in self._slider_widgets:
                    self._set_slider_value(k, v)  # Cập nhật slider

            # ========== CẬP NHẬT CÁC CHECKBOX ==========
            for k, v in data.items():
                if k in self._checkbox_vars:
                    self._set_checkbox_value(k, v)  # Cập nhật checkbox

            # ========== CẬP NHẬT CÁC OPTION MENU ==========
            for k, v in data.items():
                if k in self._option_widgets:
                    self._set_option_value(k, v)  # Cập nhật dropdown thường

            # ========== CẬP NHẬT CÁC BUTTON OPTION MENU ==========
            for k, v in data.items():
                if k in [
                    "aim_button_1",           # Phím aim 1
                    "aim_button_2",           # Phím aim 2
                    "trigger_button",         # Phím triggerbot
                    "anti_recoil_ads_key",    # Phím ADS anti-recoil
                    "anti_recoil_trigger_key", # Phím bắn anti-recoil
                ]:
                    if k in self._option_widgets:
                        v = BUTTONS[v]  # Chuyển đổi mã nút thành tên hiển thị
                        self._set_btn_option_value(k, v)

            # ========== CẬP NHẬT CÁC TEXT ENTRY ==========
            if "in_game_sens" in data:
                self.in_game_sens_entry.delete(0, tk.END)  # Xóa nội dung cũ
                self.in_game_sens_entry.insert(0, str(data["in_game_sens"]))  # Chèn giá trị mới
            if "mouse_dpi" in data:
                self.mouse_dpi_entry.delete(0, tk.END)  # Xóa nội dung cũ
                self.mouse_dpi_entry.insert(0, str(data["mouse_dpi"]))  # Chèn giá trị mới

            # ========== CẬP NHẬT ANTI-RECOIL KEY ==========
            if "anti_recoil_key" in data:
                key_name = BUTTONS.get(data["anti_recoil_key"], "Side Mouse 4 Button")
                self.ar_key_option.set(key_name)

            # ========== RELOAD MÔ HÌNH AI ==========
            from detection import reload_model
            self.tracker.model, self.tracker.class_names = reload_model()  # Reload YOLO model

            # ========== LOG KẾT QUẢ ==========
            if config_name:
                self._log_config(f"Config '{config_name}' applied and model reloaded ✅")
            else:
                self._log_config(f"Config applied and model reloaded ✅")

        except Exception as e:
            self._log_config(f"[Error _apply_settings] {e}")  # Log error if any

    def _save_new_config(self):
        """
        HÀM LƯU CẤU HÌNH MỚI
        Tạo và lưu một cấu hình mới với tên do người dùng nhập
        """
        from tkinter import simpledialog

        # Hiển thị dialog để người dùng nhập tên config
        name = simpledialog.askstring("Config Name", "Enter new config name:")
        if not name:
            self._log_config("Save cancelled (no name provided).")
            return
        
        # Lấy cài đặt hiện tại và lưu vào file
        data = self._get_current_settings()
        path = os.path.join("configs", f"{name}.json")
        try:
            os.makedirs("configs", exist_ok=True)  # Tạo thư mục nếu chưa có
            with open(path, "w") as f:
                json.dump(data, f, indent=4)  # Lưu JSON với format đẹp
            self._refresh_config_list()  # Làm mới danh sách config
            self.config_option.set(name)  # Tự động chọn config mới
            self._log_config(f"New config '{name}' saved ✅")
        except Exception as e:
            self._log_config(f"[Error SAVE] {e}")

    def _load_selected_config(self):
        """
        HÀM TẢI CẤU HÌNH ĐÃ CHỌN
        Tải cấu hình được chọn trong OptionMenu
        """
        name = self.config_option.get()  # Lấy tên config được chọn
        path = os.path.join("configs", f"{name}.json")  # Tạo đường dẫn file
        try:
            with open(path, "r") as f:
                data = json.load(f)  # Đọc dữ liệu JSON
            self._apply_settings(data, config_name=name)  # Áp dụng cài đặt
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Error LOAD] {e}")

    def _refresh_config_list(self):
        """
        HÀM LÀM MỚI DANH SÁCH CONFIG
        Cập nhật danh sách các file config có sẵn trong dropdown
        """
        files = [f[:-5] for f in os.listdir("configs") if f.endswith(".json")]  # Lấy tên file .json
        if not files:
            files = ["default"]  # Nếu không có file nào, dùng "default"
        current = self.config_option.get()  # Lấy config hiện tại
        self.config_option.configure(values=files)  # Cập nhật danh sách
        if current in files:
            self.config_option.set(current)  # Giữ nguyên nếu vẫn có
        else:
            self.config_option.set(files[0])  # Chọn file đầu tiên

    def _on_config_selected(self, val):
        """
        HÀM XỬ LÝ KHI CHỌN CONFIG
        Callback khi người dùng chọn config trong dropdown
        """
        self._log_config(f"Selected config: {val}")

    def _save_config(self):
        """
        HÀM LƯU CẤU HÌNH HIỆN TẠI
        Lưu cài đặt hiện tại vào config được chọn
        """
        name = self.config_option.get() or "default"  # Lấy tên config hoặc dùng "default"
        data = self._get_current_settings()  # Lấy cài đặt hiện tại
        path = os.path.join("configs", f"{name}.json")  # Tạo đường dẫn file
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)  # Lưu JSON với format đẹp
            self._log_config(f"Config '{name}' saved ✅")
            self._refresh_config_list()  # Làm mới danh sách
        except Exception as e:
            self._log_config(f"[Error SAVE] {e}")

    def _load_config(self):
        """
        HÀM TẢI CẤU HÌNH
        Tải cấu hình từ file (hàm dự phòng)
        """
        name = self.config_option.get() or "default"  # Lấy tên config hoặc dùng "default"
        path = os.path.join("configs", f"{name}.json")  # Tạo đường dẫn file
        try:
            with open(path, "r") as f:
                data = json.load(f)  # Đọc dữ liệu JSON
            self._apply_settings(data)  # Áp dụng cài đặt
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Error LOAD] {e}")

    def _log_config(self, msg):
        """
        HÀM GHI LOG CONFIG
        Ghi thông báo vào textbox log của tab Config
        """
        self.config_log.insert("end", msg + "\n")  # Thêm thông báo vào cuối
        self.config_log.see("end")  # Cuộn xuống cuối để xem thông báo mới

    # ----------------------- UI BUILDERS -----------------------
    def _build_general_tab(self):
        self.status_label = ctk.CTkLabel(self.tab_general, text="Status: Disconnected")
        self.status_label.pack(pady=5, anchor="w")
        self.metrics_label = ctk.CTkLabel(self.tab_general, text="Avg: -- ms  -- fps")
        self.metrics_label.pack(pady=2, anchor="w")

        # UDP controls
        port_frame = ctk.CTkFrame(self.tab_general)
        port_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(port_frame, text="UDP Port").pack(side="left", padx=6)
        self.udp_port_entry = ctk.CTkEntry(port_frame)
        self.udp_port_entry.insert(0, "8080")
        self.udp_port_entry.pack(side="left", fill="x", expand=True)
        btn_frame = ctk.CTkFrame(self.tab_general)
        btn_frame.pack(pady=5, fill="x")
        ctk.CTkButton(btn_frame, text="Start UDP", command=self._start_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )
        ctk.CTkButton(btn_frame, text="Stop UDP", command=self._stop_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )

        # In-game Sensitivity
        sens_frame = ctk.CTkFrame(self.tab_general)
        sens_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(sens_frame, text="In-game Sensitivity").pack(side="left", padx=6)
        self.in_game_sens_entry = ctk.CTkEntry(sens_frame)
        self.in_game_sens_entry.insert(0, str(getattr(config, "in_game_sens", 0.235)))
        self.in_game_sens_entry.pack(side="left", fill="x", expand=True)
        self.in_game_sens_entry.bind("<Return>", self._on_in_game_sens_enter)
        self.in_game_sens_entry.bind("<FocusOut>", self._on_in_game_sens_enter)

        # Mouse DPI
        dpi_frame = ctk.CTkFrame(self.tab_general)
        dpi_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(dpi_frame, text="Mouse DPI").pack(side="left", padx=6)
        self.mouse_dpi_entry = ctk.CTkEntry(dpi_frame)
        self.mouse_dpi_entry.insert(0, str(getattr(config, "mouse_dpi", 800)))
        self.mouse_dpi_entry.pack(side="left", fill="x", expand=True)
        self.mouse_dpi_entry.bind("<Return>", self._on_mouse_dpi_enter)
        self.mouse_dpi_entry.bind("<FocusOut>", self._on_mouse_dpi_enter)

        # Removed Appearance/Mode/Color controls

    def _build_aimbot_tab(self):
        # X Speed
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "X Speed",
            0.1,
            2000,
            float(getattr(config, "normal_x_speed", 0.5)),
            self._on_normal_x_speed_changed,
            is_float=True,
        )
        self._register_slider("normal_x_speed", s, l, 0.1, 2000, True)
        # Y Speed
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Y Speed",
            0.1,
            2000,
            float(getattr(config, "normal_y_speed", 0.5)),
            self._on_normal_y_speed_changed,
            is_float=True,
        )
        self._register_slider("normal_y_speed", s, l, 0.1, 2000, True)
        # In-game sens
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "In-game sens",
            0.1,
            2000,
            float(getattr(config, "in_game_sens", 7)),
            self._on_config_in_game_sens_changed,
            is_float=True,
        )
        self._register_slider("in_game_sens", s, l, 0.1, 2000, True)
        # Smoothing
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Smoothing",
            1,
            30,
            float(getattr(config, "normalsmooth", 10)),
            self._on_config_normal_smooth_changed,
            is_float=True,
        )
        self._register_slider("normalsmooth", s, l, 1, 30, True)
        # Smoothing FOV
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "Smoothing FOV",
            1,
            30,
            float(getattr(config, "normalsmoothfov", 10)),
            self._on_config_normal_smoothfov_changed,
            is_float=True,
        )
        self._register_slider("normalsmoothfov", s, l, 1, 30, True)
        # FOV Size
        s, l = self._add_slider_with_label(
            self.tab_aimbot,
            "FOV Size",
            1,
            1000,
            float(getattr(config, "fovsize", 300)),
            self._on_fovsize_changed,
            is_float=True,
        )
        self._register_slider("fovsize", s, l, 1, 1000, True)

        # Enable Aim
        self.var_enableaim = tk.BooleanVar(value=getattr(config, "enableaim", False))
        ctk.CTkCheckBox(
            self.tab_aimbot,
            text="Enable Aim",
            variable=self.var_enableaim,
            command=self._on_enableaim_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["enableaim"] = self.var_enableaim

        ctk.CTkLabel(self.tab_aimbot, text="Aim Keys (choose two)").pack(
            pady=5, anchor="w"
        )
        # Two selectors for aim keys
        self.aim_key_1 = ctk.CTkOptionMenu(
            self.tab_aimbot,
            values=list(BUTTONS.values()),
            command=lambda v: self._on_aim_key_1_changed(),
        )
        self.aim_key_1.pack(pady=4, fill="x")
        self._option_widgets["aim_button_1"] = self.aim_key_1

        self.aim_key_2 = ctk.CTkOptionMenu(
            self.tab_aimbot,
            values=list(BUTTONS.values()),
            command=lambda v: self._on_aim_key_2_changed(),
        )
        self.aim_key_2.pack(pady=4, fill="x")
        self._option_widgets["aim_button_2"] = self.aim_key_2

    def _build_tb_tab(self):
        # TB FOV Size
        s, l = self._add_slider_with_label(
            self.tab_tb,
            "TB FOV Size",
            1,
            300,
            float(getattr(config, "tbfovsize", 70)),
            self._on_tbfovsize_changed,
            is_float=True,
        )
        self._register_slider("tbfovsize", s, l, 1, 300, True)
        # TB Delay
        s, l = self._add_slider_with_label(
            self.tab_tb,
            "TB Delay",
            0.0,
            1.0,
            float(getattr(config, "tbdelay", 0.08)),
            self._on_tbdelay_changed,
            is_float=True,
        )
        self._register_slider("tbdelay", s, l, 0.0, 1.0, True)
        # TB Fire Rate
        s, l = self._add_slider_with_label(
            self.tab_tb,
            "TB Fire Rate (ms)",
            10,
            1000,
            float(getattr(config, "trigger_fire_rate_ms", 100)),
            self._on_trigger_fire_rate_changed,
            is_float=True,
        )
        self._register_slider("trigger_fire_rate_ms", s, l, 10, 1000, True)

        # Enable TB
        self.var_enabletb = tk.BooleanVar(value=getattr(config, "enabletb", False))
        ctk.CTkCheckBox(
            self.tab_tb,
            text="Enable TB",
            variable=self.var_enabletb,
            command=self._on_enabletb_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["enabletb"] = self.var_enabletb

        ctk.CTkLabel(self.tab_tb, text="Triggerbot Button").pack(pady=5, anchor="w")
        self.trigger_button_option = ctk.CTkOptionMenu(
            self.tab_tb,
            values=list(BUTTONS.values()),
            command=self._on_trigger_button_selected,
        )
        self.trigger_button_option.pack(pady=5, fill="x")
        self._option_widgets["trigger_button"] = self.trigger_button_option

    def _build_ar_tab(self):
        # Enable Anti-Recoil
        self.var_anti_recoil_enabled = tk.BooleanVar(
            value=getattr(config, "anti_recoil_enabled", False)
        )
        ctk.CTkCheckBox(
            self.tab_ar,
            text="Enable Anti-Recoil",
            variable=self.var_anti_recoil_enabled,
            command=self._on_anti_recoil_enabled_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["anti_recoil_enabled"] = self.var_anti_recoil_enabled

        # Anti-Recoil Key
        ctk.CTkLabel(self.tab_ar, text="Anti-Recoil Key:").pack(pady=5, anchor="w")
        self.ar_key_option = ctk.CTkOptionMenu(
            self.tab_ar,
            values=list(BUTTONS.values()),
            command=self._on_ar_key_changed
        )
        self.ar_key_option.pack(pady=5, fill="x")
        self._option_widgets["anti_recoil_key"] = self.ar_key_option

        # Require Aim Active
        self.var_anti_recoil_require_aim = tk.BooleanVar(
            value=getattr(config, "anti_recoil_require_aim_active", True)
        )
        ctk.CTkCheckBox(
            self.tab_ar,
            text="Require Aim Active to Start",
            variable=self.var_anti_recoil_require_aim,
            command=self._on_ar_require_aim_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["anti_recoil_require_aim_active"] = self.var_anti_recoil_require_aim

        # X Recoil
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "X Recoil",
            -50,
            50,
            float(getattr(config, "anti_recoil_x", 0)),
            self._on_anti_recoil_x_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_x", s, l, -50, 50, True)

        # Y Recoil
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "Y Recoil",
            -50,
            50,
            float(getattr(config, "anti_recoil_y", 0)),
            self._on_anti_recoil_y_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_y", s, l, -50, 50, True)

        # Fire Rate
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "Fire Rate (ms)",
            10,
            1000,
            float(getattr(config, "anti_recoil_fire_rate", 100)),
            self._on_anti_recoil_fire_rate_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_fire_rate", s, l, 10, 1000, True)

        # Hold Time
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "Hold Time (ms)",
            0,
            2000,
            float(getattr(config, "anti_recoil_hold_time", 0)),
            self._on_anti_recoil_hold_time_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_hold_time", s, l, 0, 2000, True)

        # Scale with ADS
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "ADS Scale",
            0.1,
            3.0,
            float(getattr(config, "anti_recoil_scale_ads", 1.0)),
            self._on_anti_recoil_scale_ads_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_scale_ads", s, l, 0.1, 3.0, True)

        # Jitter X
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "Jitter X",
            0,
            20,
            float(getattr(config, "anti_recoil_jitter_x", 0)),
            self._on_anti_recoil_jitter_x_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_jitter_x", s, l, 0, 20, True)

        # Jitter Y
        s, l = self._add_slider_with_label(
            self.tab_ar,
            "Jitter Y",
            0,
            20,
            float(getattr(config, "anti_recoil_jitter_y", 0)),
            self._on_anti_recoil_jitter_y_changed,
            is_float=True,
        )
        self._register_slider("anti_recoil_jitter_y", s, l, 0, 20, True)

        # Only when triggering
        self.var_anti_recoil_only_triggering = tk.BooleanVar(
            value=getattr(config, "anti_recoil_only_triggering", True)
        )
        ctk.CTkCheckBox(
            self.tab_ar,
            text="Only when triggering",
            variable=self.var_anti_recoil_only_triggering,
            command=self._on_anti_recoil_only_triggering_changed,
        ).pack(pady=6, anchor="w")
        self._checkbox_vars["anti_recoil_only_triggering"] = (
            self.var_anti_recoil_only_triggering
        )

        # ADS Key
        ctk.CTkLabel(self.tab_ar, text="ADS Key").pack(pady=5, anchor="w")
        self.ar_ads_key_option = ctk.CTkOptionMenu(
            self.tab_ar,
            values=list(BUTTONS.values()),
            command=self._on_ar_ads_key_selected,
        )
        self.ar_ads_key_option.pack(pady=5, fill="x")
        self._option_widgets["anti_recoil_ads_key"] = self.ar_ads_key_option

        # Trigger Key
        ctk.CTkLabel(self.tab_ar, text="Trigger Key").pack(pady=5, anchor="w")
        self.ar_trigger_key_option = ctk.CTkOptionMenu(
            self.tab_ar,
            values=list(BUTTONS.values()),
            command=self._on_ar_trigger_key_selected,
        )
        self.ar_trigger_key_option.pack(pady=5, fill="x")
        self._option_widgets["anti_recoil_trigger_key"] = self.ar_trigger_key_option

    # Generic slider helper (parent-aware)
    def _add_slider_with_label(
        self, parent, text, min_val, max_val, init_val, command, is_float=False
    ):
        frame = ctk.CTkFrame(parent)
        frame.pack(padx=12, pady=6, fill="x")

        label = ctk.CTkLabel(
            frame, text=f"{text}: {init_val:.2f}" if is_float else f"{text}: {init_val}"
        )
        label.pack(side="left")

        steps = 100 if is_float else max(1, int(max_val - min_val))
        slider = ctk.CTkSlider(
            frame,
            from_=min_val,
            to=max_val,
            number_of_steps=steps,
            command=lambda v: self._slider_callback(v, label, text, command, is_float),
        )
        slider.set(init_val)
        slider.pack(side="right", fill="x", expand=True)
        return slider, label

    def _slider_callback(self, value, label, text, command, is_float):
        val = float(value) if is_float else int(round(value))
        label.configure(text=f"{text}: {val:.2f}" if is_float else f"{text}: {val}")
        command(val)

    # ----------------------- Callbacks -----------------------
    def _on_normal_x_speed_changed(self, val):
        config.normal_x_speed = val
        self.tracker.normal_x_speed = val

    def _on_normal_y_speed_changed(self, val):
        config.normal_y_speed = val
        self.tracker.normal_y_speed = val

    def _on_config_in_game_sens_changed(self, val):
        config.in_game_sens = val
        self.tracker.in_game_sens = val

    def _on_config_normal_smooth_changed(self, val):
        config.normalsmooth = val
        self.tracker.normalsmooth = val

    def _on_config_normal_smoothfov_changed(self, val):
        config.normalsmoothfov = val
        self.tracker.normalsmoothfov = val

    def _on_aim_key_1_changed(self):
        """Callback cho aim button 1"""
        name = self.aim_key_1.get()
        for key, n in BUTTONS.items():
            if n == name:
                config.aim_button_1 = key
                self.tracker.aim_button_1 = key
                break
        self._log_config(f"Aim button 1 set to {name} ({key})")

    def _on_aim_key_2_changed(self):
        """Callback cho aim button 2"""
        name = self.aim_key_2.get()
        for key, n in BUTTONS.items():
            if n == name:
                config.aim_button_2 = key
                self.tracker.aim_button_2 = key
                break
        self._log_config(f"Aim button 2 set to {name} ({key})")

    def _on_trigger_button_selected(self, val):
        """Callback cho trigger button"""
        for key, name in BUTTONS.items():
            if name == val:
                config.trigger_button = key
                self.tracker.trigger_button = key
                break
        self._log_config(f"Triggerbot button set to {val} ({key})")

    def _on_fovsize_changed(self, val):
        config.fovsize = val
        self.tracker.fovsize = val

    def _on_tbdelay_changed(self, val):
        config.tbdelay = val
        self.tracker.tbdelay = val

    def _on_tbfovsize_changed(self, val):
        config.tbfovsize = val
        self.tracker.tbfovsize = val

    def _on_trigger_fire_rate_changed(self, val):
        """Callback cho trigger fire rate"""
        config.trigger_fire_rate_ms = val
        # Cập nhật tracker nếu có thuộc tính này
        if hasattr(self.tracker, 'fire_rate_ms'):
            self.tracker.fire_rate_ms = val

    def _on_enableaim_changed(self):
        config.enableaim = self.var_enableaim.get()

    def _on_enabletb_changed(self):
        config.enabletb = self.var_enabletb.get()

    # Anti-recoil callbacks
    def _on_anti_recoil_enabled_changed(self):
        config.anti_recoil_enabled = self.var_anti_recoil_enabled.get()
        self.anti_recoil.update_config()

    def _on_ar_key_changed(self, choice):
        """Callback khi thay đổi phím anti-recoil"""
        key_code = next((k for k, v in BUTTONS.items() if v == choice), 3)
        config.anti_recoil_key = key_code
        self.anti_recoil.update_config()

    def _on_ar_require_aim_changed(self):
        """Callback khi thay đổi yêu cầu aim active"""
        config.anti_recoil_require_aim_active = self.var_anti_recoil_require_aim.get()
        self.anti_recoil.update_config()

    def _on_anti_recoil_x_changed(self, val):
        config.anti_recoil_x = val
        self.anti_recoil.x_recoil = val

    def _on_anti_recoil_y_changed(self, val):
        config.anti_recoil_y = val
        self.anti_recoil.y_recoil = val

    def _on_anti_recoil_fire_rate_changed(self, val):
        config.anti_recoil_fire_rate = val
        self.anti_recoil.fire_rate_ms = val

    def _on_anti_recoil_hold_time_changed(self, val):
        config.anti_recoil_hold_time = val
        self.anti_recoil.hold_time_ms = val

    def _on_anti_recoil_scale_ads_changed(self, val):
        config.anti_recoil_scale_ads = val
        self.anti_recoil.scale_with_ads = val

    def _on_anti_recoil_jitter_x_changed(self, val):
        config.anti_recoil_jitter_x = val
        self.anti_recoil.random_jitter_x = val

    def _on_anti_recoil_jitter_y_changed(self, val):
        config.anti_recoil_jitter_y = val
        self.anti_recoil.random_jitter_y = val

    def _on_anti_recoil_only_triggering_changed(self):
        config.anti_recoil_only_triggering = self.var_anti_recoil_only_triggering.get()
        self.anti_recoil.only_when_triggering = (
            self.var_anti_recoil_only_triggering.get()
        )

    def _on_ar_ads_key_selected(self, val):
        for key, name in BUTTONS.items():
            if name == val:
                config.anti_recoil_ads_key = key
                self.anti_recoil.ads_key = key
                break
        self._log_config(f"Anti-recoil ADS key set to {val} ({key})")

    def _on_ar_trigger_key_selected(self, val):
        for key, name in BUTTONS.items():
            if name == val:
                config.anti_recoil_trigger_key = key
                self.anti_recoil.trigger_key = key
                break
        self._log_config(f"Anti-recoil trigger key set to {val} ({key})")

    def _on_source_selected(self, val):
        pass

    def _on_in_game_sens_enter(self, event=None):
        """Callback khi người dùng nhập In-game Sensitivity"""
        try:
            value = float(self.in_game_sens_entry.get())
            config.in_game_sens = value
            self.tracker.in_game_sens = value
            self._log_config(f"In-game sensitivity set to {value}")
        except ValueError:
            # Nếu giá trị không hợp lệ, khôi phục giá trị cũ
            self.in_game_sens_entry.delete(0, tk.END)
            self.in_game_sens_entry.insert(
                0, str(getattr(config, "in_game_sens", 0.235))
            )
            self._log_config("Invalid sensitivity value, restored to previous value")

    def _on_mouse_dpi_enter(self, event=None):
        """Callback khi người dùng nhập Mouse DPI"""
        try:
            value = int(self.mouse_dpi_entry.get())
            if value <= 0:
                raise ValueError("DPI must be positive")
            config.mouse_dpi = value
            self.tracker.mouse_dpi = value
            self._log_config(f"Mouse DPI set to {value}")
        except ValueError:
            # Nếu giá trị không hợp lệ, khôi phục giá trị cũ
            self.mouse_dpi_entry.delete(0, tk.END)
            self.mouse_dpi_entry.insert(0, str(getattr(config, "mouse_dpi", 800)))
            self._log_config("Invalid DPI value, restored to previous value")

    # Removed appearance/mode/color handlers

    # ----------------------- UDP helpers -----------------------
    def _start_udp(self):
        try:
            port_text = self.udp_port_entry.get().strip()
            port = int(port_text) if port_text else 8080
        except Exception:
            port = 8080
        try:
            if self.receiver is not None:
                self._stop_udp()
            rcvbuf = getattr(config, "viewer_rcvbuf_mb", 256)
            max_assembly = 256 * 1024 * 1024
            self.rx_store = _LatestBytesStore()
            self.decoder = _Decoder()
            self.last_decoded_seq = -1
            self.last_bgr = None
            self.receiver = _Receiver(
                "0.0.0.0", port, rcvbuf, max_assembly, self.rx_store
            )
            self.receiver.start()
            # Start display thread
            if self.display_thread is None or not self.display_thread.is_alive():
                self.display_thread = DisplayThread(
                    self, self.vision_store, self.mask_store
                )
                self.display_thread.start()
            self.connected = True
            self.status_label.configure(
                text=f"UDP listening on :{port}", text_color="green"
            )
        except Exception as e:
            self.connected = False
            self.status_label.configure(text=f"UDP error: {e}", text_color="red")

    def _stop_udp(self):
        try:
            if self.receiver is not None:
                self.receiver.stop()
                self.receiver.join(timeout=1.0)
        except Exception:
            pass
        try:
            if self.display_thread is not None:
                self.display_thread.stop()
                self.display_thread.join(timeout=1.5)
        except Exception:
            pass
        self.receiver = None
        self.last_bgr = None
        self.connected = False
        self.status_label.configure(text="Status: Disconnected", text_color="red")

    def _update_connection_status_loop(self):
        try:
            if self.receiver is not None:
                self.connected = True
                _, _, avg_ms, avg_fps = self.rx_store.get_latest()
                if avg_ms is not None and avg_fps is not None:
                    self.metrics_label.configure(
                        text=f"Avg: {avg_ms:.1f} ms  {avg_fps:.1f} fps"
                    )
                self.status_label.configure(text="UDP Connected", text_color="green")

                # Chạy anti-recoil tick với DetectionEngine
                try:
                    self.anti_recoil.tick(self.detection_engine)
                except Exception as e:
                    print(f"[Anti-Recoil Tick Error] {e}")
            else:
                self.connected = False
                self.status_label.configure(text="Disconnected", text_color="red")
                self.metrics_label.configure(text="Avg: -- ms  -- fps")
        except Exception:
            pass
        self.after(500, self._update_connection_status_loop)

    def _on_close(self):
        try:
            self.tracker.stop()
        except Exception:
            pass
        try:
            self._stop_udp()
        except Exception:
            pass
        # Stop display thread and UDP
        self.destroy()
        try:
            import cv2

            cv2.destroyAllWindows()
        except Exception:
            pass

    # ----------------------- Frame access -----------------------
    def get_latest_frame(self):
        try:
            buf, seq, _, _ = self.rx_store.get_latest()
            if buf is None:
                return None
            if seq == self.last_decoded_seq and self.last_bgr is not None:
                return self.last_bgr
            frame = self.decoder.decode_bgr(buf)
            if frame is None or frame.size == 0:
                return None
            self.last_decoded_seq = seq
            self.last_bgr = frame
            return frame
        except Exception:
            return None
