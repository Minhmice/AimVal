import customtkinter as ctk
import threading
import queue
import time
import math
import numpy as np
import cv2
import tkinter as tk
import os
import json

from udp_source import UdpFrameSource

from config import config
from mouse import Mouse, is_button_pressed
from detection import load_model, perform_detection, reload_model


BUTTONS = {
    0: "Left Mouse Button",
    1: "Right Mouse Button",
    2: "Middle Mouse Button",
    3: "Side Mouse 4 Button",
    4: "Side Mouse 5 Button",
}


def threaded_silent_move(controller, dx, dy):
    """Petit move-restore pour le mode Silent."""
    controller.move(dx, dy)
    time.sleep(0.001)
    controller.click()
    time.sleep(0.001)
    controller.move(-dx, -dy)


class AimTracker:
    def __init__(self, app, target_fps=80):
        self.app = app
        # --- Params (avec valeurs fallback) ---
        self.normal_x_speed = float(getattr(config, "normal_x_speed", 0.5))
        self.normal_y_speed = float(getattr(config, "normal_y_speed", 0.5))
        self.normalsmooth = float(getattr(config, "normalsmooth", 10))
        self.normalsmoothfov = float(getattr(config, "normalsmoothfov", 10))
        self.mouse_dpi = float(getattr(config, "mouse_dpi", 800))
        self.fovsize = float(getattr(config, "fovsize", 300))
        self.tbfovsize = float(getattr(config, "tbfovsize", 70))
        self.tbdelay = float(getattr(config, "tbdelay", 0.08))
        self.last_tb_click_time = 0.0

        self.in_game_sens = float(getattr(config, "in_game_sens", 7))
        self.color = getattr(config, "color", "yellow")
        self.mode = getattr(config, "mode", "Normal")
        self.selected_mouse_button = getattr(config, "selected_mouse_button", 3)
        self.selected_tb_btn = getattr(config, "selected_tb_btn", 3)
        self.max_speed = float(getattr(config, "max_speed", 1000.0))

        self.controller = Mouse()
        self.move_queue = queue.Queue(maxsize=50)
        self._move_thread = threading.Thread(
            target=self._process_move_queue, daemon=True
        )
        self._move_thread.start()

        self.model, self.class_names = load_model()
        print("Classes:", self.class_names)
        self._stop_event = threading.Event()
        self._target_fps = target_fps
        self._track_thread = threading.Thread(target=self._track_loop, daemon=True)
        self._track_thread.start()

    def stop(self):
        self._stop_event.set()
        try:
            self._track_thread.join(timeout=1.0)
        except Exception:
            pass

    def _process_move_queue(self):
        while True:
            try:
                dx, dy, delay = self.move_queue.get(timeout=0.1)
                try:
                    self.controller.move(dx, dy)
                except Exception as e:
                    print("[Mouse.move error]", e)
                if delay and delay > 0:
                    time.sleep(delay)
            except queue.Empty:
                time.sleep(0.001)
                continue
            except Exception as e:
                print(f"[Move Queue Error] {e}")
                time.sleep(0.01)

    def _clip_movement(self, dx, dy):
        clipped_dx = np.clip(dx, -abs(self.max_speed), abs(self.max_speed))
        clipped_dy = np.clip(dy, -abs(self.max_speed), abs(self.max_speed))
        return float(clipped_dx), float(clipped_dy)

    def _track_loop(self):
        period = 1.0 / float(self._target_fps)
        while not self._stop_event.is_set():
            start = time.time()
            try:
                self.track_once()
            except Exception as e:
                print("[Track error]", e)
            elapsed = time.time() - start
            to_sleep = period - elapsed
            if to_sleep > 0:
                time.sleep(to_sleep)

    def _draw_fovs(self, img, frame):
        center_x = int(frame.xres / 2)
        center_y = int(frame.yres / 2)
        if getattr(config, "enableaim", False):
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "fovsize", self.fovsize)),
                (255, 255, 255),
                2,
            )
            # Correct: cercle smoothing = normalsmoothFOV
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "normalsmoothfov", self.normalsmoothfov)),
                (51, 255, 255),
                2,
            )
        if getattr(config, "enabletb", False):
            cv2.circle(
                img,
                (center_x, center_y),
                int(getattr(config, "tbfovsize", self.tbfovsize)),
                (255, 255, 255),
                2,
            )

    def track_once(self):
        if not getattr(self.app, "connected", False):
            return

        # Fetch latest UDP MJPEG frame (already BGR)
        try:
            img = None
            if getattr(self.app, "udp_source", None) is not None:
                img = self.app.udp_source.get_latest_frame()
            if img is None:
                return
            h, w = img.shape[:2]
            # Build a lightweight frame info object with xres/yres attributes
            frame = type("FrameInfo", (), {"xres": w, "yres": h})()
            bgr_img = img.copy()
        except Exception:
            return

        try:
            detection_results, mask = perform_detection(self.model, bgr_img)
            cv2.imshow("MASK", mask)
            cv2.waitKey(1)
        except Exception as e:
            print("[perform_detection error]", e)
            detection_results = []

        targets = []
        if detection_results:
            for det in detection_results:
                try:
                    x, y, w, h = det["bbox"]
                    conf = det.get("confidence", 1.0)
                    x1, y1 = int(x), int(y)
                    x2, y2 = int(x + w), int(y + h)
                    y1 *= 1.03
                    # Draw based on detection type with different colors
                    if det.get("type") == "body" and getattr(config, "show_body_box", True):
                        self._draw_body(bgr_img, x1, y1, x2, y2, conf)
                        # Body center for targeting
                        body_cx = x1 + w // 2
                        body_cy = y1 + h // 2  
                        d = math.hypot(
                            body_cx - frame.xres / 2.0, body_cy - frame.yres / 2.0
                        )
                        targets.append((body_cx, body_cy, d, "body"))
                        
                    elif det.get("type") == "head" and getattr(config, "show_head_box", True):
                        self._draw_head_bbox_new(bgr_img, x1, y1, x2, y2, conf)
                        # Head center for targeting (more precise)
                        head_cx = x1 + w // 2
                        head_cy = y1 + h // 2
                        d = math.hypot(
                            head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0
                        )
                        targets.append((head_cx, head_cy, d, "head"))
                        
                    else:
                        # Legacy support - old detection format
                        self._draw_body(bgr_img, x1, y1, x2, y2, conf)
                        head_positions = self._estimate_head_positions(
                            x1, y1, x2, y2, bgr_img
                        )
                        for head_cx, head_cy, bbox in head_positions:
                            self._draw_head_bbox(bgr_img, head_cx, head_cy)
                            d = math.hypot(
                                head_cx - frame.xres / 2.0, head_cy - frame.yres / 2.0
                            )
                            targets.append((head_cx, head_cy, d, "head"))
                except Exception as e:
                    print("Erreur dans _estimate_head_positions:", e)

        # FOVs une fois par frame
        try:
            self._draw_fovs(bgr_img, frame)
        except Exception:
            pass

        try:
            self._aim_and_move(targets, frame, bgr_img)
        except Exception as e:
            print("[Aim error]", e)

        try:
            cv2.imshow("Detection", bgr_img)
            cv2.waitKey(1)
        except Exception:
            pass

    def _draw_head_bbox(self, img, headx, heady):
        cv2.circle(img, (int(headx), int(heady)), 2, (0, 0, 255), -1)

    def _estimate_head_positions(self, x1, y1, x2, y2, img):
        offsetY = getattr(config, "offsetY", 0)
        offsetX = getattr(config, "offsetX", 0)

        width = x2 - x1
        height = y2 - y1

        # Crop léger
        top_crop_factor = 0.10
        side_crop_factor = 0.10

        effective_y1 = y1 + height * top_crop_factor
        effective_height = height * (1 - top_crop_factor)

        effective_x1 = x1 + width * side_crop_factor
        effective_x2 = x2 - width * side_crop_factor
        effective_width = effective_x2 - effective_x1

        center_x = (effective_x1 + effective_x2) / 2
        headx_base = center_x + effective_width * (offsetX / 100)
        heady_base = effective_y1 + effective_height * (offsetY / 100)

        pixel_marginx = 40
        pixel_marginy = 10

        x1_roi = int(max(headx_base - pixel_marginx, 0))
        y1_roi = int(max(heady_base - pixel_marginy, 0))
        x2_roi = int(min(headx_base + pixel_marginx, img.shape[1]))
        y2_roi = int(min(heady_base + pixel_marginy, img.shape[0]))

        roi = img[y1_roi:y2_roi, x1_roi:x2_roi]
        cv2.rectangle(img, (x1_roi, y1_roi), (x2_roi, y2_roi), (0, 0, 255), 2)

        results = []
        detections = []
        try:
            detections, mask = perform_detection(self.model, roi)
        except Exception as e:
            print("[perform_detection ROI error]", e)

        if not detections:
            # Sans détection → garder le head position avec offset
            results.append((headx_base, heady_base, (x1_roi, y1_roi, x2_roi, y2_roi)))
        else:
            for det in detections:
                x, y, w, h = det["bbox"]
                cv2.rectangle(
                    img,
                    (x1_roi + x, y1_roi + y),
                    (x1_roi + x + w, y1_roi + y + h),
                    (0, 255, 0),
                    2,
                )

                # Position détection brute
                headx_det = x1_roi + x + w / 2
                heady_det = y1_roi + y + h / 2

                # Application de l’offset aussi sur la détection
                headx_det += effective_width * (offsetX / 100)
                heady_det += effective_height * (offsetY / 100)

                results.append((headx_det, heady_det, (x1_roi + x, y1_roi + y, w, h)))

        return results

    def _draw_body(self, img, x1, y1, x2, y2, conf):
        """Draw body bounding box in BLUE"""
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (255, 0, 0), 3)  # Blue for body
        cv2.putText(
            img,
            f"BODY {conf:.2f}",
            (int(x1), int(y1) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 0, 0),  # Blue text
            2,
        )
        # Add corner markers for better visibility
        corner_size = 8
        cv2.line(img, (int(x1), int(y1)), (int(x1 + corner_size), int(y1)), (255, 0, 0), 4)
        cv2.line(img, (int(x1), int(y1)), (int(x1), int(y1 + corner_size)), (255, 0, 0), 4)
        cv2.line(img, (int(x2), int(y2)), (int(x2 - corner_size), int(y2)), (255, 0, 0), 4)
        cv2.line(img, (int(x2), int(y2)), (int(x2), int(y2 - corner_size)), (255, 0, 0), 4)
    
    def _draw_head_bbox_new(self, img, x1, y1, x2, y2, conf):
        """Draw head bounding box in RED with different style"""
        # Main rectangle in RED
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)  # Red for head
        
        # Add cross-hair in center
        center_x = int((x1 + x2) / 2)
        center_y = int((y1 + y2) / 2)
        cross_size = 6
        cv2.line(img, (center_x - cross_size, center_y), (center_x + cross_size, center_y), (0, 0, 255), 2)
        cv2.line(img, (center_x, center_y - cross_size), (center_x, center_y + cross_size), (0, 0, 255), 2)
        
        # Text label
        cv2.putText(
            img,
            f"HEAD {conf:.2f}",
            (int(x1), int(y1) - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 0, 255),  # Red text
            2,
        )
        
        # Corner brackets for head (different from body)
        bracket_size = 6
        thickness = 3
        # Top-left bracket
        cv2.line(img, (int(x1), int(y1 + bracket_size)), (int(x1), int(y1)), (0, 255, 255), thickness)
        cv2.line(img, (int(x1), int(y1)), (int(x1 + bracket_size), int(y1)), (0, 255, 255), thickness)
        # Top-right bracket  
        cv2.line(img, (int(x2 - bracket_size), int(y1)), (int(x2), int(y1)), (0, 255, 255), thickness)
        cv2.line(img, (int(x2), int(y1)), (int(x2), int(y1 + bracket_size)), (0, 255, 255), thickness)
        # Bottom-left bracket
        cv2.line(img, (int(x1), int(y2 - bracket_size)), (int(x1), int(y2)), (0, 255, 255), thickness)
        cv2.line(img, (int(x1), int(y2)), (int(x1 + bracket_size), int(y2)), (0, 255, 255), thickness)
        # Bottom-right bracket
        cv2.line(img, (int(x2 - bracket_size), int(y2)), (int(x2), int(y2)), (0, 255, 255), thickness)
        cv2.line(img, (int(x2), int(y2)), (int(x2), int(y2 - bracket_size)), (0, 255, 255), thickness)

    def _aim_and_move(self, targets, frame, img):
        aim_enabled = getattr(config, "enableaim", False)
        selected_btn = getattr(config, "selected_mouse_button", None)

        center_x = frame.xres / 2.0
        center_y = frame.yres / 2.0
        # --- Target selection with priority (head > body) ---
        if not targets:
            cx, cy, distance_to_center = center_x, center_y, float("inf")
            target_type = "none"
        else:
            # Prioritize head targets over body targets
            head_targets = [t for t in targets if len(t) > 3 and t[3] == "head"]
            body_targets = [t for t in targets if len(t) > 3 and t[3] == "body"]
            
            if head_targets:
                # Prefer closest head
                best_target = min(head_targets, key=lambda t: t[2])
                cx, cy, distance_to_center, target_type = best_target[0], best_target[1], best_target[2], best_target[3]
            elif body_targets:
                # Fallback to closest body
                best_target = min(body_targets, key=lambda t: t[2])
                cx, cy, distance_to_center, target_type = best_target[0], best_target[1], best_target[2], best_target[3]
            else:
                # Legacy format
                best_target = min(targets, key=lambda t: t[2])
                cx, cy, distance_to_center = best_target[0], best_target[1], best_target[2]
                target_type = "legacy"
                
            if distance_to_center > float(getattr(config, "fovsize", self.fovsize)):
                return
                
            # Visual indicator of selected target
            cv2.circle(img, (int(cx), int(cy)), 4, (0, 255, 0), -1)  # Green dot for selected target
            cv2.putText(img, f"TARGET: {target_type.upper()}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        dx = cx - center_x
        dy = cy - center_y

        sens = float(getattr(config, "in_game_sens", self.in_game_sens))
        dpi = float(getattr(config, "mouse_dpi", self.mouse_dpi))

        cm_per_rev_base = 54.54
        cm_per_rev = cm_per_rev_base / max(sens, 0.01)

        count_per_cm = dpi / 2.54
        deg_per_count = 360.0 / (cm_per_rev * count_per_cm)

        ndx = dx * deg_per_count
        ndy = dy * deg_per_count

        mode = getattr(config, "mode", "Normal")
        if mode == "Normal":
            try:
                # --- AIMBOT ---
                if (
                    aim_enabled
                    and selected_btn is not None
                    and is_button_pressed(selected_btn)
                    and targets
                    and target_type != "none"
                ):
                    if distance_to_center < float(
                        getattr(config, "normalsmoothfov", self.normalsmoothfov)
                    ):
                        ndx *= float(
                            getattr(config, "normal_x_speed", self.normal_x_speed)
                        ) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)),
                            0.01,
                        )
                        ndy *= float(
                            getattr(config, "normal_y_speed", self.normal_y_speed)
                        ) / max(
                            float(getattr(config, "normalsmooth", self.normalsmooth)),
                            0.01,
                        )
                    else:
                        ndx *= float(
                            getattr(config, "normal_x_speed", self.normal_x_speed)
                        )
                        ndy *= float(
                            getattr(config, "normal_y_speed", self.normal_y_speed)
                        )
                    ddx, ddy = self._clip_movement(ndx, ndy)
                    self.move_queue.put((ddx, ddy, 0.005))
            except Exception:
                pass

            try:
                # --- Paramètres triggerbot ---
                if (
                    getattr(config, "enabletb", False)
                    and is_button_pressed(getattr(config, "selected_tb_btn", None))
                    or is_button_pressed(getattr(config, "selected_2_tb", None))
                ):
                    # Centre de l'écran
                    cx0, cy0 = int(frame.xres // 2), int(frame.yres // 2)
                    ROI_SIZE = 5  # petit carré autour du centre
                    x1, y1 = max(cx0 - ROI_SIZE, 0), max(cy0 - ROI_SIZE, 0)
                    x2, y2 = (
                        min(cx0 + ROI_SIZE, img.shape[1]),
                        min(cy0 + ROI_SIZE, img.shape[0]),
                    )
                    roi = img[y1:y2, x1:x2]

                    if roi.size == 0:
                        return  # sécurité

                    # Conversion HSV (assure-toi que img est BGR)
                    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

                    # Plage HSV pour le violet (ajuste si nécessaire)

                    HSV_UPPER = self.model[1]
                    HSV_LOWER = self.model[0]

                    mask = cv2.inRange(hsv, HSV_LOWER, HSV_UPPER)

                    detected = cv2.countNonZero(mask) > 0
                    # print(f"ROI shape: {roi.shape}, NonZero pixels: {cv2.countNonZero(mask)}")

                    # Debug affichage
                    cv2.imshow("ROI", roi)
                    cv2.imshow("Mask", mask)
                    cv2.waitKey(1)

                    # Texte sur l'image principale
                    if detected:
                        cv2.putText(
                            img,
                            "PURPLE DETECTED",
                            (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            1,
                            (0, 0, 255),
                            2,
                        )
                        now = time.time()
                        if now - self.last_tb_click_time >= float(
                            getattr(config, "tbdelay", self.tbdelay)
                        ):
                            self.controller.click()
                            self.last_tb_click_time = now

            except Exception as e:
                print("[Triggerbot error]", e)

        elif mode == "Silent":
            if targets:  # évite crash si pas de target
                dx_raw = int(dx)
                dy_raw = int(dy)
                dx_raw *= self.normal_x_speed
                dy_raw *= self.normal_y_speed
                threading.Thread(
                    target=threaded_silent_move,
                    args=(self.controller, dx_raw, dy_raw),
                    daemon=True,
                ).start()


class ViewerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("CUPSY COLORBOT")
        self.geometry("400x700")

        # Dicos pour MAJ UI <-> config
        self._slider_widgets = (
            {}
        )  # key -> {"slider": widget, "label": widget, "min":..., "max":...}
        self._checkbox_vars = {}  # key -> tk.BooleanVar
        self._option_widgets = {}  # key -> CTkOptionMenu

        # UDP source
        self.udp_source = None
        self.connected = False
        # enlève la barre native

        # Detection tab moved after TabView creation

        # barre custom
        self.title_bar = ctk.CTkFrame(self, height=30, corner_radius=0)
        self.title_bar.pack(fill="x", side="top")

        self.title_label = ctk.CTkLabel(self.title_bar, text="CUPSY CB", anchor="w")
        self.title_label.pack(side="left", padx=10)

        # bouton fermer
        self.close_btn = ctk.CTkButton(
            self.title_bar, text="X", width=25, command=self.destroy
        )
        self.close_btn.pack(side="right", padx=2)

        # rendre la barre draggable
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.do_move)

        # Tracker
        self.tracker = AimTracker(app=self, target_fps=80)

        # TabView
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(expand=True, fill="both", padx=20, pady=20)
        self.tab_general = self.tabview.add("⚙️ Général")
        self.tab_aimbot = self.tabview.add("🎯 Aimbot")
        self.tab_tb = self.tabview.add("🔫 Triggerbot")
        self.tab_detection = self.tabview.add("🧪 Detection")
        self.tab_config = self.tabview.add("💾 Config")

        self._build_general_tab()
        self._build_aimbot_tab()
        self._build_tb_tab()
        self._build_detection_tab()
        self._build_config_tab()

        # Status polling
        self.after(500, self._update_connection_status_loop)
        self._load_initial_config()

    # ---------- Helpers de mapping UI ----------
    def _create_detection_scrollable_frame(self, parent):
        """Create a smooth scrollable frame specifically for Detection tab."""
        # Main container
        main_container = ctk.CTkFrame(parent, corner_radius=0)
        main_container.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Canvas for scrolling
        canvas = tk.Canvas(
            main_container,
            highlightthickness=0,
            relief="flat",
            bd=0,
            bg="#212121" if ctk.get_appearance_mode() == "Dark" else "#EBEBEB"
        )
        
        # Scrollbar
        scrollbar = ctk.CTkScrollbar(
            main_container,
            orientation="vertical",
            command=canvas.yview
        )
        
        # Scrollable content frame
        scrollable_frame = ctk.CTkFrame(canvas, corner_radius=0)
        
        # Configure scrolling
        def update_scroll_region(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        scrollable_frame.bind("<Configure>", update_scroll_region)
        
        # Create canvas window
        canvas_frame = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        
        # Configure canvas
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Pack elements
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Smooth scrolling function
        def smooth_scroll(event):
            # Smoother, more responsive scrolling
            if event.delta:
                delta = -int(event.delta / 40)  # Adjust for smoothness
            else:
                delta = -1 if event.num == 4 else 1
            canvas.yview_scroll(delta, "units")
        
        # Bind scroll events
        def bind_scroll_events(widget):
            widget.bind("<MouseWheel>", smooth_scroll)
            widget.bind("<Button-4>", smooth_scroll)
            widget.bind("<Button-5>", smooth_scroll)
        
        # Apply scroll binding to relevant widgets
        bind_scroll_events(canvas)
        bind_scroll_events(scrollable_frame)
        bind_scroll_events(main_container)
        
        # Auto-resize canvas content width
        def configure_canvas_width(event):
            canvas_width = event.width
            canvas.itemconfig(canvas_frame, width=canvas_width)
        
        canvas.bind("<Configure>", configure_canvas_width)
        
        return scrollable_frame

    def _register_slider(self, key, slider, label, vmin, vmax, is_float):
        self._slider_widgets[key] = {
            "slider": slider,
            "label": label,
            "min": vmin,
            "max": vmax,
            "is_float": is_float,
        }

    def _load_initial_config(self):
        try:
            import json, os
            from detection import reload_model

            if os.path.exists("configs/default.json"):
                with open("configs/default.json", "r") as f:
                    data = json.load(f)

                self._apply_settings(data)

            else:
                print("doesn't exist")
        except Exception as e:
            print("Impossible de charger la config initiale:", e)

    def _set_slider_value(self, key, value):
        if key not in self._slider_widgets:
            return
        w = self._slider_widgets[key]
        vmin, vmax = w["min"], w["max"]
        is_float = w["is_float"]
        # Clamp
        try:
            v = float(value) if is_float else int(round(float(value)))
        except Exception:
            return
        v = max(vmin, min(v, vmax))
        w["slider"].set(v)
        # Rafraîchir label
        txt = (
            f"{key.replace('_', ' ').title()}: {v:.2f}"
            if is_float
            else f"{key.replace('_', ' ').title()}: {int(v)}"
        )
        # On garde le libellé humain (X Speed etc.) si déjà présent
        current = w["label"].cget("text")
        prefix = current.split(":")[0] if ":" in current else txt.split(":")[0]
        w["label"].configure(
            text=f"{prefix}: {v:.2f}" if is_float else f"{prefix}: {int(v)}"
        )

    def _set_checkbox_value(self, key, value_bool):
        var = self._checkbox_vars.get(key)
        if var is not None:
            var.set(bool(value_bool))

    def _set_option_value(self, key, value_str):
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))

    def _set_btn_option_value(self, key, value_str):
        menu = self._option_widgets.get(key)
        if menu is not None and value_str is not None:
            menu.set(str(value_str))

    # -------------- Tab Config --------------

    def _build_config_tab(self):
        os.makedirs("configs", exist_ok=True)

        ctk.CTkLabel(self.tab_config, text="Choose a config:").pack(pady=5, anchor="w")

        self.config_option = ctk.CTkOptionMenu(
            self.tab_config, values=[], command=self._on_config_selected
        )
        self.config_option.pack(pady=5, fill="x")

        ctk.CTkButton(self.tab_config, text="💾 Save", command=self._save_config).pack(
            pady=10, fill="x"
        )
        ctk.CTkButton(
            self.tab_config, text="💾 New Config", command=self._save_new_config
        ).pack(pady=5, fill="x")
        ctk.CTkButton(
            self.tab_config, text="📂 Load config", command=self._load_selected_config
        ).pack(pady=5, fill="x")

        self.config_log = ctk.CTkTextbox(self.tab_config, height=120)
        self.config_log.pack(pady=10, fill="both", expand=True)

        self._refresh_config_list()

    # -------------- Tab Detection --------------
    def _build_detection_tab(self):
        # Create smooth scrollable frame specifically for detection parameters
        scrollable_detection = self._create_detection_scrollable_frame(self.tab_detection)
        
        # Add display toggle buttons at the top
        toggle_frame = ctk.CTkFrame(scrollable_detection)
        toggle_frame.pack(pady=10, fill="x", padx=10)
        
        ctk.CTkLabel(toggle_frame, text="Display Options:", font=("Arial", 14, "bold")).pack(pady=5)
        
        # Show Body Box toggle
        self.var_show_body = tk.BooleanVar(value=getattr(config, "show_body_box", True))
        ctk.CTkCheckBox(
            toggle_frame,
            text="Show Body Boxes",
            variable=self.var_show_body,
            command=self._on_show_body_changed,
        ).pack(pady=2, anchor="w")
        self._checkbox_vars["show_body_box"] = self.var_show_body
        
        # Show Head Box toggle  
        self.var_show_head = tk.BooleanVar(value=getattr(config, "show_head_box", True))
        ctk.CTkCheckBox(
            toggle_frame,
            text="Show Head Boxes",
            variable=self.var_show_head,
            command=self._on_show_head_changed,
        ).pack(pady=2, anchor="w")
        self._checkbox_vars["show_head_box"] = self.var_show_head

        def add_slider_row(key, text, vmin, vmax, init, is_float, tooltip=""):
            s, l = self._add_slider_with_label_and_tooltip(
                scrollable_detection,
                text,
                vmin,
                vmax,
                init,
                lambda val, k=key, f=is_float: self._on_detection_slider_changed(
                    k, val, f
                ),
                is_float=is_float,
                tooltip=tooltip
            )
            self._register_slider(key, s, l, vmin, vmax, is_float)

        # === BODY DETECTION PARAMETERS ===
        body_section = ctk.CTkLabel(scrollable_detection, text="🔵 BODY DETECTION", font=("Arial", 16, "bold"))
        body_section.pack(pady=(15, 5), anchor="w")
        
        # Body HSV ranges
        add_slider_row(
            "det_body_h_min", "Body Hue Min", 0.0, 179.0, 
            float(getattr(config, "det_body_h_min", 30.0)), True,
            "Giá trị Hue tối thiểu để detect body (0-179). Hue quyết định màu sắc cơ bản."
        )
        add_slider_row(
            "det_body_h_max", "Body Hue Max", 0.0, 179.0,
            float(getattr(config, "det_body_h_max", 160.0)), True,
            "Giá trị Hue tối đa để detect body. Khoảng Hue càng rộng thì detect càng nhiều màu."
        )
        add_slider_row(
            "det_body_s_min", "Body Sat Min", 0.0, 255.0,
            float(getattr(config, "det_body_s_min", 125.0)), True,
            "Độ bão hòa màu tối thiểu cho body. Giá trị cao = màu sắc rõ nét, thấp = màu nhạt."
        )
        add_slider_row(
            "det_body_s_max", "Body Sat Max", 0.0, 255.0,
            float(getattr(config, "det_body_s_max", 255.0)), True,
            "Độ bão hòa màu tối đa cho body. 255 = chấp nhận tất cả độ bão hòa."
        )
        add_slider_row(
            "det_body_v_min", "Body Val Min", 0.0, 255.0,
            float(getattr(config, "det_body_v_min", 150.0)), True,
            "Độ sáng tối thiểu cho body. Giá trị cao = chỉ detect vùng sáng, thấp = cả vùng tối."
        )
        add_slider_row(
            "det_body_v_max", "Body Val Max", 0.0, 255.0,
            float(getattr(config, "det_body_v_max", 255.0)), True,
            "Độ sáng tối đa cho body. 255 = chấp nhận tất cả độ sáng."
        )
        
        # === HEAD DETECTION PARAMETERS ===
        head_section = ctk.CTkLabel(scrollable_detection, text="🔴 HEAD DETECTION", font=("Arial", 16, "bold"))
        head_section.pack(pady=(15, 5), anchor="w")
        
        # Head HSV ranges  
        add_slider_row(
            "det_head_h_min", "Head Hue Min", 0.0, 179.0,
            float(getattr(config, "det_head_h_min", 25.0)), True,
            "Giá trị Hue tối thiểu để detect head. Thường khác với body để phân biệt."
        )
        add_slider_row(
            "det_head_h_max", "Head Hue Max", 0.0, 179.0,
            float(getattr(config, "det_head_h_max", 170.0)), True,
            "Giá trị Hue tối đa để detect head. Điều chỉnh để tách biệt với body."
        )
        add_slider_row(
            "det_head_s_min", "Head Sat Min", 0.0, 255.0,
            float(getattr(config, "det_head_s_min", 100.0)), True,
            "Độ bão hòa tối thiểu cho head. Head thường có màu khác body nên cần tune riêng."
        )
        add_slider_row(
            "det_head_s_max", "Head Sat Max", 0.0, 255.0,
            float(getattr(config, "det_head_s_max", 255.0)), True,
            "Độ bão hòa tối đa cho head."
        )
        add_slider_row(
            "det_head_v_min", "Head Val Min", 0.0, 255.0,
            float(getattr(config, "det_head_v_min", 120.0)), True,
            "Độ sáng tối thiểu cho head. Head có thể sáng/tối khác body."
        )
        add_slider_row(
            "det_head_v_max", "Head Val Max", 0.0, 255.0,
            float(getattr(config, "det_head_v_max", 255.0)), True,
            "Độ sáng tối đa cho head."
        )

        # === PRE-PROCESSING PARAMETERS ===
        preprocess_section = ctk.CTkLabel(scrollable_detection, text="🔧 PRE-PROCESSING", font=("Arial", 16, "bold"))
        preprocess_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_blur_kernel", "Blur Kernel Size", 1.0, 15.0,
            float(getattr(config, "det_blur_kernel", 3.0)), True,
            "Kích thước kernel làm mờ ảnh. Giá trị lẻ, càng lớn càng mờ, giúp giảm noise."
        )
        add_slider_row(
            "det_blur_sigma", "Blur Sigma", 0.0, 5.0,
            float(getattr(config, "det_blur_sigma", 1.0)), True,
            "Độ mạnh của Gaussian blur. 0 = box blur, > 0 = Gaussian blur mượt hơn."
        )
        add_slider_row(
            "det_gamma", "Gamma Correction", 0.1, 3.0,
            float(getattr(config, "det_gamma", 1.0)), True,
            "Hiệu chỉnh gamma. < 1 = làm sáng vùng tối, > 1 = làm tối vùng sáng."
        )
        add_slider_row(
            "det_brightness", "Brightness", -100.0, 100.0,
            float(getattr(config, "det_brightness", 0.0)), True,
            "Điều chỉnh độ sáng. Âm = tối hơn, dương = sáng hơn."
        )
        add_slider_row(
            "det_contrast", "Contrast", 0.1, 3.0,
            float(getattr(config, "det_contrast", 1.0)), True,
            "Điều chỉnh độ tương phản. < 1 = giảm contrast, > 1 = tăng contrast."
        )
        
        # === BODY MORPHOLOGY ===
        body_morph_section = ctk.CTkLabel(scrollable_detection, text="🔵 BODY MORPHOLOGY", font=("Arial", 16, "bold"))
        body_morph_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_body_close_kw", "Body Close Kernel W", 1.0, 65.0,
            float(getattr(config, "det_body_close_kw", 15.0)), True,
            "Chiều rộng kernel đóng lỗ hổng cho body. Lớn = đóng lỗ lớn hơn."
        )
        add_slider_row(
            "det_body_close_kh", "Body Close Kernel H", 1.0, 65.0,
            float(getattr(config, "det_body_close_kh", 30.0)), True,
            "Chiều cao kernel đóng lỗ hổng cho body."
        )
        add_slider_row(
            "det_body_dilate_k", "Body Dilate Kernel", 1.0, 65.0,
            float(getattr(config, "det_body_dilate_k", 15.0)), True,
            "Kích thước kernel mở rộng body. Lớn = body phình to hơn."
        )
        add_slider_row(
            "det_body_dilate_iter", "Body Dilate Iterations", 0.0, 10.0,
            float(getattr(config, "det_body_dilate_iter", 1.0)), True,
            "Số lần lặp mở rộng body. Nhiều = body càng to."
        )
        add_slider_row(
            "det_body_erode_k", "Body Erode Kernel", 1.0, 65.0,
            float(getattr(config, "det_body_erode_k", 3.0)), True,
            "Kích thước kernel co nhỏ body. Dùng để loại bỏ noise nhỏ."
        )
        add_slider_row(
            "det_body_erode_iter", "Body Erode Iterations", 0.0, 10.0,
            float(getattr(config, "det_body_erode_iter", 1.0)), True,
            "Số lần lặp co nhỏ body."
        )
        
        # === HEAD MORPHOLOGY ===
        head_morph_section = ctk.CTkLabel(scrollable_detection, text="🔴 HEAD MORPHOLOGY", font=("Arial", 16, "bold"))
        head_morph_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_head_close_kw", "Head Close Kernel W", 1.0, 65.0,
            float(getattr(config, "det_head_close_kw", 8.0)), True,
            "Chiều rộng kernel đóng lỗ hổng cho head. Head nhỏ nên kernel nhỏ hơn body."
        )
        add_slider_row(
            "det_head_close_kh", "Head Close Kernel H", 1.0, 65.0,
            float(getattr(config, "det_head_close_kh", 12.0)), True,
            "Chiều cao kernel đóng lỗ hổng cho head."
        )
        add_slider_row(
            "det_head_dilate_k", "Head Dilate Kernel", 1.0, 65.0,
            float(getattr(config, "det_head_dilate_k", 5.0)), True,
            "Kích thước kernel mở rộng head."
        )
        add_slider_row(
            "det_head_dilate_iter", "Head Dilate Iterations", 0.0, 10.0,
            float(getattr(config, "det_head_dilate_iter", 1.0)), True,
            "Số lần lặp mở rộng head."
        )
        add_slider_row(
            "det_head_erode_k", "Head Erode Kernel", 1.0, 65.0,
            float(getattr(config, "det_head_erode_k", 2.0)), True,
            "Kích thước kernel co nhỏ head."
        )
        add_slider_row(
            "det_head_erode_iter", "Head Erode Iterations", 0.0, 10.0,
            float(getattr(config, "det_head_erode_iter", 1.0)), True,
            "Số lần lặp co nhỏ head."
        )

        # Contour filters
        add_slider_row(
            "det_min_area",
            "Min Area (px^2)",
            0,
            300000,
            float(getattr(config, "det_min_area", 80)),
            False,
        )
        add_slider_row(
            "det_max_area",
            "Max Area (px^2)",
            1000,
            1000000,
            float(getattr(config, "det_max_area", 200000)),
            False,
        )
        add_slider_row(
            "det_ar_min",
            "Aspect Ratio Min",
            0.05,
            3.0,
            float(getattr(config, "det_ar_min", 0.2)),
            True,
        )
        add_slider_row(
            "det_ar_max",
            "Aspect Ratio Max",
            0.2,
            10.0,
            float(getattr(config, "det_ar_max", 5.0)),
            True,
        )

        # Merge / Confidence / Vertical line
        add_slider_row(
            "det_merge_dist",
            "Merge Distance",
            10,
            600,
            float(getattr(config, "det_merge_dist", 250)),
            False,
        )
        add_slider_row(
            "det_iou_thr",
            "Merge IoU Threshold",
            0.0,
            1.0,
            float(getattr(config, "det_iou_thr", 0.1)),
            True,
        )
        add_slider_row(
            "det_conf_thr",
            "Confidence Threshold (0-1)",
            0.0,
            1.0,
            float(getattr(config, "det_conf_thr", 0.02)),
            True,
        )
        add_slider_row(
            "det_vline_min_h",
            "Vertical Line Min Height (px)",
            0,
            200,
            float(getattr(config, "det_vline_min_h", 5)),
            False,
        )

        # === ADVANCED FILTERS ===
        advanced_section = ctk.CTkLabel(scrollable_detection, text="⚙️ ADVANCED FILTERS", font=("Arial", 16, "bold"))
        advanced_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_edge_threshold1", "Edge Detection Low", 0.0, 300.0,
            float(getattr(config, "det_edge_threshold1", 50.0)), True,
            "Ngưỡng thấp cho Canny edge detection. Thấp = detect nhiều edge, cao = ít edge."
        )
        add_slider_row(
            "det_edge_threshold2", "Edge Detection High", 0.0, 500.0,
            float(getattr(config, "det_edge_threshold2", 150.0)), True,
            "Ngưỡng cao cho Canny edge detection. Phải > ngưỡng thấp."
        )
        add_slider_row(
            "det_contour_epsilon", "Contour Approximation", 0.001, 0.1,
            float(getattr(config, "det_contour_epsilon", 0.02)), True,
            "Độ chính xác xấp xỉ contour. Thấp = chính xác hơn, cao = đơn giản hóa nhiều."
        )
        add_slider_row(
            "det_min_contour_points", "Min Contour Points", 3.0, 50.0,
            float(getattr(config, "det_min_contour_points", 5.0)), True,
            "Số điểm tối thiểu của contour. Ít = chấp nhận hình đơn giản, nhiều = hình phức tạp."
        )
        
        # === MERGE & VALIDATION ===
        merge_section = ctk.CTkLabel(scrollable_detection, text="🔗 MERGE & VALIDATION", font=("Arial", 16, "bold"))
        merge_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_merge_dist", "Merge Distance", 10.0, 1000.0,
            float(getattr(config, "det_merge_dist", 250.0)), True,
            "Khoảng cách tối đa để gộp 2 detection thành 1. Lớn = gộp xa hơn."
        )
        add_slider_row(
            "det_iou_thr", "IoU Merge Threshold", 0.0, 1.0,
            float(getattr(config, "det_iou_thr", 0.1)), True,
            "Ngưỡng IoU để gộp bbox chồng lấp. Cao = chỉ gộp khi chồng nhiều."
        )
        add_slider_row(
            "det_body_conf_thr", "Body Confidence", 0.0, 1.0,
            float(getattr(config, "det_body_conf_thr", 0.02)), True,
            "Ngưỡng confidence cho body. Cao = chỉ chấp nhận body chắc chắn."
        )
        add_slider_row(
            "det_head_conf_thr", "Head Confidence", 0.0, 1.0,
            float(getattr(config, "det_head_conf_thr", 0.05)), True,
            "Ngưỡng confidence cho head. Thường cao hơn body vì head khó detect hơn."
        )
        add_slider_row(
            "det_vline_min_h", "Vertical Line Min Height", 0.0, 200.0,
            float(getattr(config, "det_vline_min_h", 5.0)), True,
            "Chiều cao tối thiểu của đường thẳng đứng trong detection để xác nhận."
        )
        
        # === HEAD-BODY RELATIONSHIP ===
        relation_section = ctk.CTkLabel(scrollable_detection, text="🤝 HEAD-BODY RELATIONSHIP", font=("Arial", 16, "bold"))
        relation_section.pack(pady=(15, 5), anchor="w")
        
        add_slider_row(
            "det_head_body_ratio", "Head/Body Size Ratio", 0.1, 1.0,
            float(getattr(config, "det_head_body_ratio", 0.3)), True,
            "Tỷ lệ kích thước head/body. 0.3 = head bằng 30% body. Dùng để validate head hợp lý."
        )
        add_slider_row(
            "det_head_position_ratio", "Head Position in Body", 0.1, 0.8,
            float(getattr(config, "det_head_position_ratio", 0.25)), True,
            "Head phải nằm trong % đầu của body. 0.25 = head trong 25% trên của body."
        )
        
        # === CLAHE ENHANCEMENT ===
        clahe_section = ctk.CTkLabel(scrollable_detection, text="✨ CLAHE ENHANCEMENT", font=("Arial", 16, "bold"))
        clahe_section.pack(pady=(15, 5), anchor="w")
        
        # Checkbox Enable CLAHE
        self.var_enable_clahe = tk.BooleanVar(
            value=bool(getattr(config, "use_clahe", True))
        )
        cb = ctk.CTkCheckBox(
            scrollable_detection,
            text="Enable CLAHE (Contrast Limited Adaptive Histogram Equalization)",
            variable=self.var_enable_clahe,
            command=self._on_enable_clahe_changed,
        )
        cb.pack(pady=6, anchor="w")
        self._checkbox_vars["use_clahe"] = self.var_enable_clahe
        
        add_slider_row(
            "det_clahe_clip", "CLAHE Clip Limit", 1.0, 10.0,
            float(getattr(config, "det_clahe_clip", 2.0)), True,
            "Giới hạn clip cho CLAHE. Cao = tăng contrast mạnh, thấp = tăng contrast nhẹ."
        )
        add_slider_row(
            "det_clahe_grid", "CLAHE Grid Size", 2.0, 64.0,
            float(getattr(config, "det_clahe_grid", 8.0)), True,
            "Kích thước lưới CLAHE. Nhỏ = xử lý chi tiết, lớn = xử lý tổng thể."
        )

    # draggable title bar handlers
    def start_move(self, event):
        self._x = event.x
        self._y = event.y

    def do_move(self, event):
        x = self.winfo_pointerx() - self._x
        y = self.winfo_pointery() - self._y
        self.geometry(f"+{x}+{y}")

    def _get_current_settings(self):
        return {
            # Aimbot/General
            "normal_x_speed": getattr(config, "normal_x_speed", 0.5),
            "normal_y_speed": getattr(config, "normal_y_speed", 0.5),
            "normalsmooth": getattr(config, "normalsmooth", 10),
            "normalsmoothfov": getattr(config, "normalsmoothfov", 10),
            "mouse_dpi": getattr(config, "mouse_dpi", 800),
            "fovsize": getattr(config, "fovsize", 300),
            "tbfovsize": getattr(config, "tbfovsize", 70),
            "tbdelay": getattr(config, "tbdelay", 0.08),
            "in_game_sens": getattr(config, "in_game_sens", 7),
            "color": getattr(config, "color", "yellow"),
            "mode": getattr(config, "mode", "Normal"),
            "enableaim": getattr(config, "enableaim", False),
            "enabletb": getattr(config, "enabletb", False),
            "selected_mouse_button": getattr(config, "selected_mouse_button", 3),
            "selected_tb_btn": getattr(config, "selected_tb_btn", 3),
            
            # Display options
            "show_body_box": getattr(config, "show_body_box", True),
            "show_head_box": getattr(config, "show_head_box", True),
            
            # Body Detection HSV
            "det_body_h_min": getattr(config, "det_body_h_min", 30.0),
            "det_body_h_max": getattr(config, "det_body_h_max", 160.0),
            "det_body_s_min": getattr(config, "det_body_s_min", 125.0),
            "det_body_s_max": getattr(config, "det_body_s_max", 255.0),
            "det_body_v_min": getattr(config, "det_body_v_min", 150.0),
            "det_body_v_max": getattr(config, "det_body_v_max", 255.0),
            
            # Head Detection HSV
            "det_head_h_min": getattr(config, "det_head_h_min", 25.0),
            "det_head_h_max": getattr(config, "det_head_h_max", 170.0),
            "det_head_s_min": getattr(config, "det_head_s_min", 100.0),
            "det_head_s_max": getattr(config, "det_head_s_max", 255.0),
            "det_head_v_min": getattr(config, "det_head_v_min", 120.0),
            "det_head_v_max": getattr(config, "det_head_v_max", 255.0),
            
            # Pre-processing
            "det_blur_kernel": getattr(config, "det_blur_kernel", 3.0),
            "det_blur_sigma": getattr(config, "det_blur_sigma", 1.0),
            "det_gamma": getattr(config, "det_gamma", 1.0),
            "det_brightness": getattr(config, "det_brightness", 0.0),
            "det_contrast": getattr(config, "det_contrast", 1.0),
            
            # Body Morphology
            "det_body_close_kw": getattr(config, "det_body_close_kw", 15.0),
            "det_body_close_kh": getattr(config, "det_body_close_kh", 30.0),
            "det_body_dilate_k": getattr(config, "det_body_dilate_k", 15.0),
            "det_body_dilate_iter": getattr(config, "det_body_dilate_iter", 1.0),
            "det_body_erode_k": getattr(config, "det_body_erode_k", 3.0),
            "det_body_erode_iter": getattr(config, "det_body_erode_iter", 1.0),
            
            # Head Morphology
            "det_head_close_kw": getattr(config, "det_head_close_kw", 8.0),
            "det_head_close_kh": getattr(config, "det_head_close_kh", 12.0),
            "det_head_dilate_k": getattr(config, "det_head_dilate_k", 5.0),
            "det_head_dilate_iter": getattr(config, "det_head_dilate_iter", 1.0),
            "det_head_erode_k": getattr(config, "det_head_erode_k", 2.0),
            "det_head_erode_iter": getattr(config, "det_head_erode_iter", 1.0),
            
            # Body Contour Filters
            "det_body_min_area": getattr(config, "det_body_min_area", 500.0),
            "det_body_max_area": getattr(config, "det_body_max_area", 50000.0),
            "det_body_ar_min": getattr(config, "det_body_ar_min", 0.3),
            "det_body_ar_max": getattr(config, "det_body_ar_max", 3.0),
            "det_body_solidity_min": getattr(config, "det_body_solidity_min", 0.5),
            "det_body_extent_min": getattr(config, "det_body_extent_min", 0.3),
            
            # Head Contour Filters
            "det_head_min_area": getattr(config, "det_head_min_area", 50.0),
            "det_head_max_area": getattr(config, "det_head_max_area", 2000.0),
            "det_head_ar_min": getattr(config, "det_head_ar_min", 0.6),
            "det_head_ar_max": getattr(config, "det_head_ar_max", 1.8),
            "det_head_solidity_min": getattr(config, "det_head_solidity_min", 0.7),
            "det_head_extent_min": getattr(config, "det_head_extent_min", 0.5),
            
            # Advanced Filters
            "det_edge_threshold1": getattr(config, "det_edge_threshold1", 50.0),
            "det_edge_threshold2": getattr(config, "det_edge_threshold2", 150.0),
            "det_contour_epsilon": getattr(config, "det_contour_epsilon", 0.02),
            "det_min_contour_points": getattr(config, "det_min_contour_points", 5.0),
            
            # Merge & Validation
            "det_merge_dist": getattr(config, "det_merge_dist", 250.0),
            "det_iou_thr": getattr(config, "det_iou_thr", 0.1),
            "det_body_conf_thr": getattr(config, "det_body_conf_thr", 0.02),
            "det_head_conf_thr": getattr(config, "det_head_conf_thr", 0.05),
            "det_vline_min_h": getattr(config, "det_vline_min_h", 5.0),
            
            # Head-Body Relationship
            "det_head_body_ratio": getattr(config, "det_head_body_ratio", 0.3),
            "det_head_position_ratio": getattr(config, "det_head_position_ratio", 0.25),
            
            # CLAHE
            "det_clahe_clip": getattr(config, "det_clahe_clip", 2.0),
            "det_clahe_grid": getattr(config, "det_clahe_grid", 8.0),
            "use_clahe": getattr(config, "use_clahe", True),
        }

    def _apply_settings(self, data, config_name=None):
        """
        Applique un dictionnaire de settings sur le config global, le tracker et l'UI.
        Recharge le modèle si nécessaire.
        """
        try:
            # --- Appliquer sur config global ---
            for k, v in data.items():
                setattr(config, k, v)

            # --- Appliquer sur le tracker si l'attribut existe ---
            for k, v in data.items():
                if hasattr(self.tracker, k):
                    setattr(self.tracker, k, v)

            # --- Mettre à jour les sliders ---
            for k, v in data.items():
                if k in self._slider_widgets:
                    self._set_slider_value(k, v)

            # --- Mettre à jour les checkbox ---
            for k, v in data.items():
                if k in self._checkbox_vars:
                    self._set_checkbox_value(k, v)

            # --- Mettre à jour les OptionMenu ---
            for k, v in data.items():
                if k in self._option_widgets:
                    self._set_option_value(k, v)

            # --- Mettre à jour les OptionMenu ---
            for k, v in data.items():
                if k == "selected_mouse_button" or k == "selected_tb_btn":
                    if k in self._option_widgets:
                        print(k, v)

                        v = BUTTONS[v]
                        print(v)
                        self._set_btn_option_value(k, v)

            # --- Recharger le modèle si nécessaire ---
            from detection import reload_model

            self.tracker.model, self.tracker.class_names = reload_model()

            if config_name:
                self._log_config(
                    f"Config '{config_name}' applied and model reloaded ✅"
                )
            else:
                self._log_config(f"Config applied and model reloaded ✅")

        except Exception as e:
            self._log_config(f"[Erreur _apply_settings] {e}")

    def _save_new_config(self):
        from tkinter import simpledialog

        name = simpledialog.askstring("Config name", "Enter the config name:")
        if not name:
            self._log_config("Cancelled save (pas de nom fourni).")
            return
        data = self._get_current_settings()
        path = os.path.join("configs", f"{name}.json")
        try:
            os.makedirs("configs", exist_ok=True)
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            self._refresh_config_list()
            self.config_option.set(name)  # Sélectionner automatiquement
            self._log_config(f"New config'{name}' saved ✅")
        except Exception as e:
            self._log_config(f"[Erreur SAVE] {e}")

    def _load_selected_config(self):
        """
        Charge la config sélectionnée dans l'OptionMenu.
        """
        name = self.config_option.get()
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._apply_settings(data, config_name=name)
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Erreur LOAD] {e}")

    def _refresh_config_list(self):
        files = [f[:-5] for f in os.listdir("configs") if f.endswith(".json")]
        if not files:
            files = ["default"]
        current = self.config_option.get()
        self.config_option.configure(values=files)
        if current in files:
            self.config_option.set(current)
        else:
            self.config_option.set(files[0])

    def _on_config_selected(self, val):
        self._log_config(f"Selected config: {val}")

    def _save_config(self):
        name = self.config_option.get() or "default"
        data = self._get_current_settings()
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "w") as f:
                json.dump(data, f, indent=4)
            self._log_config(f"Config '{name}' sauvegardée ✅")
            self._refresh_config_list()
        except Exception as e:
            self._log_config(f"[Erreur SAVE] {e}")

    def _load_config(self):
        name = self.config_option.get() or "default"
        path = os.path.join("configs", f"{name}.json")
        try:
            with open(path, "r") as f:
                data = json.load(f)
            self._apply_settings(data)
            self._log_config(f"Config '{name}' loaded 📂")
        except Exception as e:
            self._log_config(f"[Erreur LOAD] {e}")

    def _log_config(self, msg):
        self.config_log.insert("end", msg + "\n")
        self.config_log.see("end")

    def _on_enable_clahe_changed(self):
        config.use_clahe = self.var_enable_clahe.get()

    # ----------------------- UI BUILDERS -----------------------
    def _build_general_tab(self):
        self.status_label = ctk.CTkLabel(self.tab_general, text="Status: Disconnected")
        self.status_label.pack(pady=5, anchor="w")

        # UDP controls
        port_frame = ctk.CTkFrame(self.tab_general)
        port_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(port_frame, text="UDP Port").pack(side="left", padx=6)
        self.udp_port_entry = ctk.CTkEntry(port_frame)
        self.udp_port_entry.insert(0, "8080")
        self.udp_port_entry.pack(side="left", fill="x", expand=True)

        # UDP Buffer Size
        buffer_frame = ctk.CTkFrame(self.tab_general)
        buffer_frame.pack(pady=5, fill="x")
        ctk.CTkLabel(buffer_frame, text="Buffer Size (MB)").pack(side="left", padx=6)
        self.udp_buffer_entry = ctk.CTkEntry(buffer_frame)
        self.udp_buffer_entry.insert(0, "64")
        self.udp_buffer_entry.pack(side="left", fill="x", expand=True)

        # Auto-reconnect checkbox
        self.var_auto_reconnect = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            self.tab_general,
            text="Auto-reconnect UDP",
            variable=self.var_auto_reconnect,
        ).pack(pady=6, anchor="w")
        btn_frame = ctk.CTkFrame(self.tab_general)
        btn_frame.pack(pady=5, fill="x")
        ctk.CTkButton(btn_frame, text="Start UDP", command=self._start_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )
        ctk.CTkButton(btn_frame, text="Stop UDP", command=self._stop_udp).pack(
            side="left", expand=True, fill="x", padx=4
        )
        # ctk.CTkButton(self.tab_general, text="Toggle Rage Mode", command=self._toggle_rage).pack(pady=5, fill="x")

        ctk.CTkLabel(self.tab_general, text="Apparence").pack(pady=5)
        ctk.CTkOptionMenu(
            self.tab_general,
            values=["Dark", "Light"],
            command=self._on_appearance_selected,
        ).pack(pady=5, fill="x")

        ctk.CTkLabel(self.tab_general, text="Mode").pack(pady=5)
        self.mode_option = ctk.CTkOptionMenu(
            self.tab_general, values=["Normal"], command=self._on_mode_selected
        )
        self.mode_option.pack(pady=5, fill="x")
        self._option_widgets["mode"] = self.mode_option

        ctk.CTkLabel(self.tab_general, text="Couleur").pack(pady=5)
        self.color_option = ctk.CTkOptionMenu(
            self.tab_general,
            values=["yellow", "purple"],
            command=self._on_color_selected,
        )
        self.color_option.pack(pady=5, fill="x")
        self._option_widgets["color"] = self.color_option

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

        ctk.CTkLabel(self.tab_aimbot, text="Aimbot Button").pack(pady=5, anchor="w")
        self.aimbot_button_option = ctk.CTkOptionMenu(
            self.tab_aimbot,
            values=list(BUTTONS.values()),
            command=self._on_aimbot_button_selected,
        )
        self.aimbot_button_option.pack(pady=5, fill="x")
        self._option_widgets["selected_mouse_button"] = self.aimbot_button_option

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
        self.tb_button_option = ctk.CTkOptionMenu(
            self.tab_tb,
            values=list(BUTTONS.values()),
            command=self._on_tb_button_selected,
        )
        self.tb_button_option.pack(pady=5, fill="x")
        self._option_widgets["selected_tb_btn"] = self.tb_button_option

    # Enhanced slider helper with tooltip support
    def _add_slider_with_label_and_tooltip(
        self, parent, text, min_val, max_val, init_val, command, is_float=False, tooltip=""
    ):
        frame = ctk.CTkFrame(parent)
        frame.pack(padx=12, pady=6, fill="x")

        # Label with tooltip support
        label = ctk.CTkLabel(
            frame, text=f"{text}: {init_val:.2f}" if is_float else f"{text}: {init_val}"
        )
        label.pack(side="left")
        
        # Add tooltip if provided
        if tooltip:
            self._add_tooltip(label, tooltip)

        steps = 1000 if is_float else max(1, int(max_val - min_val))
        slider = ctk.CTkSlider(
            frame,
            from_=min_val,
            to=max_val,
            number_of_steps=steps,
            command=lambda v: self._slider_callback(v, label, text, command, is_float),
        )
        slider.set(init_val)
        slider.pack(side="right", fill="x", expand=True)
        
        if tooltip:
            self._add_tooltip(slider, tooltip)
            
        return slider, label
    
    # Legacy method for backward compatibility
    def _add_slider_with_label(
        self, parent, text, min_val, max_val, init_val, command, is_float=False
    ):
        return self._add_slider_with_label_and_tooltip(
            parent, text, min_val, max_val, init_val, command, is_float, ""
        )
    
    def _add_tooltip(self, widget, text):
        """Add tooltip to widget"""
        def on_enter(event):
            try:
                tooltip_window = tk.Toplevel(self)
                tooltip_window.wm_overrideredirect(True)
                tooltip_window.configure(bg="#2b2b2b")
                
                # Position tooltip near mouse
                x = widget.winfo_rootx() + 25
                y = widget.winfo_rooty() + 25
                tooltip_window.geometry(f"+{x}+{y}")
                
                # Create tooltip label with text wrapping
                tooltip_label = tk.Label(
                    tooltip_window, 
                    text=text,
                    bg="#2b2b2b",
                    fg="white",
                    font=("Arial", 9),
                    wraplength=300,
                    justify="left",
                    padx=8,
                    pady=4
                )
                tooltip_label.pack()
                
                # Store tooltip reference
                widget.tooltip_window = tooltip_window
            except Exception:
                pass  # Ignore tooltip errors
            
        def on_leave(event):
            try:
                if hasattr(widget, 'tooltip_window'):
                    widget.tooltip_window.destroy()
                    del widget.tooltip_window
            except Exception:
                pass  # Ignore tooltip errors
                
        try:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
        except Exception:
            pass  # Ignore binding errors

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

    def _on_aimbot_button_selected(self, val):
        for key, name in BUTTONS.items():
            if name == val:
                config.selected_mouse_button = key
                break
        self._log_config(f"Aimbot button set to {val} ({key})")

    def _on_tb_button_selected(self, val):
        for key, name in BUTTONS.items():
            if name == val:
                config.selected_tb_btn = key
                # self.tracker.selected_tb_btn = val
                break
        self._log_config(f"Triggerbot button set to {val} ({key})")

    def _on_detection_slider_changed(self, key, val, is_float):
        v = float(val) if is_float else int(round(val))
        setattr(config, key, v)
        # Nếu cần reload model (HSV) khi thay đổi range:
        # Reload model when HSV parameters change
        hsv_keys = {
            "det_body_h_min", "det_body_h_max", "det_body_s_min", "det_body_s_max", "det_body_v_min", "det_body_v_max",
            "det_head_h_min", "det_head_h_max", "det_head_s_min", "det_head_s_max", "det_head_v_min", "det_head_v_max"
        }
        if key in hsv_keys:
            try:
                from detection import reload_model
                self.tracker.model, self.tracker.class_names = reload_model()
            except Exception:
                pass

    def _on_fovsize_changed(self, val):
        config.fovsize = val
        self.tracker.fovsize = val

    def _on_tbdelay_changed(self, val):
        config.tbdelay = val
        self.tracker.tbdelay = val

    def _on_tbfovsize_changed(self, val):
        config.tbfovsize = val
        self.tracker.tbfovsize = val

    def _on_enableaim_changed(self):
        config.enableaim = self.var_enableaim.get()

    def _on_enabletb_changed(self):
        config.enabletb = self.var_enabletb.get()
        
    def _on_show_body_changed(self):
        config.show_body_box = self.var_show_body.get()
        
    def _on_show_head_changed(self):
        config.show_head_box = self.var_show_head.get()

    def _on_source_selected(self, val):
        pass

    def _on_appearance_selected(self, val):
        try:
            ctk.set_appearance_mode(val)
        except Exception:
            pass

    def _on_color_selected(self, val):
        config.color = val
        self.tracker.color = val

    def _on_mode_selected(self, val):
        config.mode = val
        self.tracker.mode = val

    # ----------------------- UDP helpers -----------------------
    def _start_udp(self):
        try:
            port_text = self.udp_port_entry.get().strip()
            port = int(port_text) if port_text else 8080
        except Exception:
            port = 8080

        try:
            buffer_text = self.udp_buffer_entry.get().strip()
            buffer_mb = int(buffer_text) if buffer_text else 64
        except Exception:
            buffer_mb = 64

        try:
            if self.udp_source is not None:
                self._stop_udp()
            self.udp_source = UdpFrameSource(
                host="0.0.0.0",
                port=port,
                rcvbuf_mb=buffer_mb,
                jitter_buffer_size=5,
                auto_reconnect=self.var_auto_reconnect.get(),
                watchdog_timeout=5.0,
            )
            ok = self.udp_source.start()
            self.connected = bool(ok)
            if ok:
                self.status_label.configure(
                    text=f"UDP listening on :{port} (Buffer: {buffer_mb}MB)",
                    text_color="green",
                )
            else:
                self.status_label.configure(
                    text="Failed to start UDP", text_color="red"
                )
        except Exception as e:
            self.connected = False
            self.status_label.configure(text=f"UDP error: {e}", text_color="red")

    def _stop_udp(self):
        try:
            if self.udp_source is not None:
                self.udp_source.stop()
        except Exception:
            pass
        self.udp_source = None
        self.connected = False
        self.status_label.configure(text="Status: Disconnected", text_color="red")

    def _update_connection_status_loop(self):
        try:
            if self.udp_source is not None:
                self.connected = True
                stats = self.udp_source.get_stats()
                fps = stats.get("rt_fps", 0.0)
                loss_rate = stats.get("estimated_loss_rate", 0.0)
                connection_lost = stats.get("connection_lost", False)

                if connection_lost:
                    self.status_label.configure(
                        text=f"UDP Connection Lost — Reconnecting...",
                        text_color="orange",
                    )
                else:
                    status_text = f"UDP Connected — {fps:.1f} fps"
                    if loss_rate > 0.05:  # Show loss rate if > 5%
                        status_text += f" (Loss: {loss_rate*100:.1f}%)"
                    self.status_label.configure(text=status_text, text_color="green")
            else:
                self.connected = False
                self.status_label.configure(text="Disconnected", text_color="red")
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
        self.destroy()
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass


if __name__ == "__main__":
    ctk.set_appearance_mode("Dark")
    try:
        ctk.set_default_color_theme("themes/metal.json")
    except Exception:
        pass
    app = ViewerApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.mainloop()
