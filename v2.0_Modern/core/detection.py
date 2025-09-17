import cv2
import numpy as np


class Detector:
    """Simple HSV color-mask based detector with light morphology.

    Pipeline per frame:
    1) BGR -> HSV conversion
    2) Threshold using lower/upper HSV bounds from config
    3) Dilate then erode (closing) to reduce noise and fill small gaps
    4) Find external contours and filter by area
    Returns a list of targets with contour, center and bounding rect, plus the
    processed binary mask for debugging/trigger checks.
    """

    def __init__(self, config):
        self.config = config

    def run(self, frame):
        # Convert to HSV once; HSV is more robust for color-thresholding
        hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Binary mask of pixels within the selected enemy color profile
        lower_bound = self.config.get_hsv_lower()
        upper_bound = self.config.get_hsv_upper()
        color_mask = cv2.inRange(hsv_frame, lower_bound, upper_bound)

        # Morphological closing: expand bright areas then slightly shrink them
        dilate_kernel = self.config.get_dilate_kernel()
        dilate_iter = int(self.config.get("DILATE_ITERATIONS"))
        dilated_mask = cv2.dilate(color_mask, dilate_kernel, iterations=dilate_iter)

        erode_kernel = self.config.get_erode_kernel()
        erode_iter = int(self.config.get("ERODE_ITERATIONS"))
        processed_mask = cv2.erode(dilated_mask, erode_kernel, iterations=erode_iter)

        # Only consider external contours to avoid nested detections
        contours, _ = cv2.findContours(
            processed_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        valid_targets = []
        if contours:
            for c in contours:
                if cv2.contourArea(c) > self.config.get("MIN_CONTOUR_AREA"):
                    M = cv2.moments(c)
                    if M["m00"] != 0:
                        cx = int(M["m10"] / M["m00"])
                        cy = int(M["m01"] / M["m00"])
                        x, y, w, h = cv2.boundingRect(c)
                        valid_targets.append(
                            {"contour": c, "center": (cx, cy), "rect": (x, y, w, h)}
                        )

        return valid_targets, processed_mask


def verify_on_target(mask, scan_center_x, scan_center_y, scan_height, scan_width):
    """Check for color pixels above and below crosshair to confirm a target.

    The heuristic expects the crosshair to roughly sit at chest/neck area of a
    humanoid. If we see colored pixels in a short bar above and below the
    crosshair, we consider it "on target" for the trigger gate.
    """
    mask_h, mask_w = mask.shape[:2]

    scan_x_start = max(0, scan_center_x - scan_width // 2)
    scan_x_end = min(mask_w, scan_center_x + scan_width // 2 + 1)

    y_above_start = max(0, scan_center_y - scan_height)
    y_above_end = max(0, scan_center_y)

    y_below_start = min(mask_h, scan_center_y + 1)
    y_below_end = min(mask_h, scan_center_y + scan_height + 1)

    is_pixel_above = False
    if y_above_end > y_above_start:
        scan_area_above = mask[y_above_start:y_above_end, scan_x_start:scan_x_end]
        is_pixel_above = np.any(scan_area_above)

    is_pixel_below = False
    if y_below_end > y_below_start:
        scan_area_below = mask[y_below_start:y_below_end, scan_x_start:scan_x_end]
        is_pixel_below = np.any(scan_area_below)

    return is_pixel_above and is_pixel_below


def visualize_detection(debug_img, targets):
    """Draw rectangles and centers for each detected target (debug view)."""
    for target in targets:
        x, y, w, h = target["rect"]
        cv2.rectangle(debug_img, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.circle(debug_img, target["center"], 3, (0, 0, 255), -1)
    return debug_img


def draw_range_circle(frame, center, radius):
    """Vẽ vòng tròn cyan quanh tâm để debug phạm vi aim.

    Args:
        frame: ảnh BGR (numpy array)
        center: tuple (x, y) tâm vòng tròn
        radius: bán kính (pixel)
    """
    try:
        x, y = int(center[0]), int(center[1])
        r = max(1, int(radius))
        # Cyan in BGR: (255, 255, 0)
        cv2.circle(frame, (x, y), r, (255, 255, 0), 1, lineType=cv2.LINE_AA)
    except Exception:
        pass
    return frame