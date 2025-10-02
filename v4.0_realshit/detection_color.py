import cv2
import numpy as np
from config import config

# ------------------ Config GPU ------------------

# ------------------ Modèle HSV ------------------
_model = None
_class_names = {}
HSV_MIN = None
HSV_MAX = None


def test():
    print("HSV Detection test initialized")
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    hsv_img = cv2.cvtColor(dummy_img, cv2.COLOR_BGR2HSV)
    print("HSV conversion done")


def load_model(model_path=None):
    global _model, _class_names, HSV_MIN, HSV_MAX
    config.model_load_error = ""

    try:
        print("Loading HSV parameters (purple only)...")
        purple = [144, 106, 172, 160, 255, 255]
        HSV_MIN = np.array([purple[0], purple[1], purple[2]], dtype=np.uint8)
        HSV_MAX = np.array([purple[3], purple[4], purple[5]], dtype=np.uint8)
        print("Loaded HSV for purple")

        _model = (HSV_MIN, HSV_MAX)
        _class_names = {"color": "Target Color"}
        config.model_classes = list(_class_names.values())
        config.model_file_size = 0
        return _model, _class_names

    except Exception as e:
        config.model_load_error = f"Failed to load HSV params: {e}"
        _model, _class_names = None, {}
        return None, {}


def reload_model(model_path=None):
    return load_model(model_path)


# ------------------ Vérification ligne verticale ------------------
def has_color_vertical_line(mask, x, y1, y2):
    """
    Vérifie si une colonne verticale à la position x contient des pixels non nuls.
    """
    line = mask[y1:y2, x]
    return np.any(line > 0)


# ------------------ Fusion de rectangles ------------------
def merge_close_rects(rects, centers, dist_threshold=250):
    merged, merged_centers = [], []
    used = [False] * len(rects)

    for i, (r1, c1) in enumerate(zip(rects, centers)):
        if used[i]:
            continue
        x1, y1, w1, h1 = r1
        cx1, cy1 = c1
        nx, ny, nw, nh = x1, y1, w1, h1
        cxs, cys = [cx1], [cy1]

        for j, (r2, c2) in enumerate(zip(rects, centers)):
            if i == j or used[j]:
                continue
            x2, y2, w2, h2 = r2
            cx2, cy2 = c2

            # --- Condition 1 : chevauchement ---
            if (x1 < x2 + w2 and x1 + w1 > x2) and (y1 < y2 + h2 and y1 + h1 > y2):
                nx, ny = min(nx, x2), min(ny, y2)
                nw = max(nx + nw, x2 + w2) - nx
                nh = max(ny + nh, y2 + h2) - ny
                cxs.append(cx2)
                cys.append(cy2)
                used[j] = True

        used[i] = True
        merged.append((nx, ny, nw, nh))
        merged_centers.append((int(np.mean(cxs)), int(np.mean(cys))))

    return merged, merged_centers


def triggerbot_detect(model, roi):
    """
    Détecte si la couleur est présente dans le ROI.
    Renvoie True si au moins un pixel détecté, False sinon.

    Params:
        model : tuple (HSV_MIN, HSV_MAX)
        roi : image BGR de la zone à analyser
    """
    if model is None or roi is None:
        return False

    # Conversion HSV et masque
    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_roi, model[0], model[1])

    # Nettoyage morphologique léger
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Retourne True si au moins un pixel détecté
    return np.any(mask > 0)


# ------------------ Détection couleur ------------------
def perform_detection(model, image):
    """
    Détecte les zones colorées dans l'image et fusionne les rectangles proches.
    """
    if model is None:
        return None

    hsv_img = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv_img, model[0], model[1])

    # Nettoyage morphologique
    kernel = np.ones((30, 15), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)

    # Contours et rectangles
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects, centers = [], []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        cx, cy = x + w // 2, y + h // 2

        # --- Condition 2 : skip si pas de ligne verticale colorée ---
        if not has_color_vertical_line(mask, cx, y, y + h):
            continue

        rects.append((x, y, w, h))
        centers.append((cx, cy))

    merged_rects, merged_centers = merge_close_rects(rects, centers)

    return [
        {"class": "player", "bbox": r, "confidence": 1.0} for r in merged_rects
    ], mask


# ------------------ Helpers ------------------
def get_class_names():
    return _class_names


def get_model_size(model_path=None):
    return 0


# ------------------ Head ROI detection helper ------------------
def detect_heads_in_roi(img, x1, y1, x2, y2, offsetX=0, offsetY=0):
    """
    Detect head positions within a body bbox using color-based detection.

    Returns a list of tuples: (head_cx, head_cy, bbox) where bbox is (x,y,w,h) in image coords.

    Applies a small crop at the top and sides to focus search, then runs perform_detection
    on a narrow ROI around the estimated head baseline using offsets.
    """
    width = x2 - x1
    height = y2 - y1

    # Light crop to focus on upper-body/head area
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

    results = []
    try:
        detections, mask = perform_detection(_model, roi)
    except Exception:
        detections, mask = [], None

    if not detections:
        # No detection → keep baseline with offsets
        results.append(
            (headx_base, heady_base, (x1_roi, y1_roi, x2_roi - x1_roi, y2_roi - y1_roi))
        )
    else:
        for det in detections:
            x, y, w, h = det["bbox"]
            # Raw detection center
            headx_det = x1_roi + x + w / 2
            heady_det = y1_roi + y + h / 2
            # Apply offsets
            headx_det += effective_width * (offsetX / 100)
            heady_det += effective_height * (offsetY / 100)
            results.append((headx_det, heady_det, (x1_roi + x, y1_roi + y, w, h)))

    return results
