import cv2
import numpy as np
from typing import List, Dict, Any, Tuple
from .base import Box, Detector


def _iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = max(1, area_a + area_b - inter)
    return inter / union


def _merge_by_iou(boxes: List[Box], thr: float) -> List[Box]:
    if not boxes:
        return []
    merged: List[Box] = []
    used = [False] * len(boxes)
    xyxy = [b.as_xyxy() for b in boxes]
    for i, bi in enumerate(boxes):
        if used[i]:
            continue
        group = [i]
        for j in range(i + 1, len(boxes)):
            if used[j]:
                continue
            if _iou(xyxy[i], xyxy[j]) >= thr:
                group.append(j)
        # merge group by min/max
        x1 = min(xyxy[k][0] for k in group)
        y1 = min(xyxy[k][1] for k in group)
        x2 = max(xyxy[k][2] for k in group)
        y2 = max(xyxy[k][3] for k in group)
        w = max(1, x2 - x1)
        h = max(1, y2 - y1)
        score = float(np.mean([boxes[k].score for k in group]))
        merged.append(Box(x1, y1, w, h, label="hsv", score=score, source="hsv"))
        for k in group:
            used[k] = True
    return merged


class HSVColorDetector(Detector):
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.enabled = bool(config.get("enabled", True))
        self.lower = np.array(config.get("lower", [20, 100, 100]), dtype=np.uint8)
        self.upper = np.array(config.get("upper", [35, 255, 255]), dtype=np.uint8)
        
        # Basic morphology (v5 style)
        self.kernel_size = int(config.get("morph_kernel", 3))
        self.min_area = float(config.get("min_area", 150.0))
        self.merge_iou = float(config.get("merge_iou", 0.2))
        self.profiles = config.get("profiles", {})
        
        # Advanced morphology từ v2 - sử dụng float cho precision
        self.dilate_iterations = float(config.get("dilate_iterations", 2.0))
        self.dilate_kernel_width = float(config.get("dilate_kernel_width", 3.0))
        self.dilate_kernel_height = float(config.get("dilate_kernel_height", 3.0))
        self.erode_iterations = float(config.get("erode_iterations", 1.0))
        self.erode_kernel_width = float(config.get("erode_kernel_width", 2.0))
        self.erode_kernel_height = float(config.get("erode_kernel_height", 2.0))
        
        # Target verification từ v2
        self.sandwich_check_height = float(config.get("sandwich_check_height", 15.0))
        self.sandwich_check_scan_width = float(config.get("sandwich_check_scan_width", 5.0))
        self.enable_sandwich_check = bool(config.get("enable_sandwich_check", True))
        
        # Advanced filtering từ v2
        self.contour_approximation = float(config.get("contour_approximation", 0.02))
        self.aspect_ratio_min = float(config.get("aspect_ratio_min", 0.3))
        self.aspect_ratio_max = float(config.get("aspect_ratio_max", 3.0))
        self.solidity_min = float(config.get("solidity_min", 0.3))
        self.extent_min = float(config.get("extent_min", 0.3))
        
        # Noise reduction từ v2/v3
        self.gaussian_blur_kernel = int(config.get("gaussian_blur_kernel", 0))  # 0 = disabled
        self.median_blur_kernel = int(config.get("median_blur_kernel", 0))  # 0 = disabled
        self.bilateral_filter_d = int(config.get("bilateral_filter_d", 0))  # 0 = disabled
        self.bilateral_sigma_color = float(config.get("bilateral_sigma_color", 75.0))
        self.bilateral_sigma_space = float(config.get("bilateral_sigma_space", 75.0))
        
        # Color space enhancements
        self.hsv_saturation_boost = float(config.get("hsv_saturation_boost", 1.0))
        self.hsv_value_boost = float(config.get("hsv_value_boost", 1.0))
        self.adaptive_threshold_enabled = bool(config.get("adaptive_threshold_enabled", False))
        self.adaptive_threshold_block_size = int(config.get("adaptive_threshold_block_size", 11))
        self.adaptive_threshold_c = float(config.get("adaptive_threshold_c", 2.0))

    def set_profile(self, name: str):
        rng = self.profiles.get(name)
        if rng:
            self.lower = np.array(rng[0], dtype=np.uint8)
            self.upper = np.array(rng[1], dtype=np.uint8)

    def infer(self, bgr) -> Tuple[List[Box], Dict[str, Any]]:
        if not self.enabled or bgr is None:
            return [], {}
            
        # Pre-processing filters từ v2/v3
        processed_bgr = bgr.copy()
        
        # Noise reduction filters
        if self.gaussian_blur_kernel > 0:
            kernel_size = int(self.gaussian_blur_kernel)
            if kernel_size % 2 == 0:
                kernel_size += 1  # Must be odd
            processed_bgr = cv2.GaussianBlur(processed_bgr, (kernel_size, kernel_size), 0)
            
        if self.median_blur_kernel > 0:
            kernel_size = int(self.median_blur_kernel)
            if kernel_size % 2 == 0:
                kernel_size += 1  # Must be odd
            processed_bgr = cv2.medianBlur(processed_bgr, kernel_size)
            
        if self.bilateral_filter_d > 0:
            processed_bgr = cv2.bilateralFilter(
                processed_bgr, 
                int(self.bilateral_filter_d),
                self.bilateral_sigma_color,
                self.bilateral_sigma_space
            )
        
        # Convert to HSV
        hsv = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2HSV)
        
        # HSV enhancement từ v2
        if self.hsv_saturation_boost != 1.0 or self.hsv_value_boost != 1.0:
            h, s, v = cv2.split(hsv)
            if self.hsv_saturation_boost != 1.0:
                s = np.clip(s * self.hsv_saturation_boost, 0, 255).astype(np.uint8)
            if self.hsv_value_boost != 1.0:
                v = np.clip(v * self.hsv_value_boost, 0, 255).astype(np.uint8)
            hsv = cv2.merge([h, s, v])
        
        # Color thresholding
        mask = cv2.inRange(hsv, self.lower, self.upper)
        
        # Adaptive thresholding option
        if self.adaptive_threshold_enabled:
            gray = cv2.cvtColor(processed_bgr, cv2.COLOR_BGR2GRAY)
            adaptive_mask = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY,
                self.adaptive_threshold_block_size, self.adaptive_threshold_c
            )
            mask = cv2.bitwise_and(mask, adaptive_mask)
        
        # Advanced morphology từ v2 - sử dụng float precision
        dilate_w = max(1, int(self.dilate_kernel_width))
        dilate_h = max(1, int(self.dilate_kernel_height))
        dilate_iter = max(0, int(self.dilate_iterations))
        if dilate_iter > 0:
            dilate_kernel = np.ones((dilate_h, dilate_w), np.uint8)
            mask = cv2.dilate(mask, dilate_kernel, iterations=dilate_iter)
        
        erode_w = max(1, int(self.erode_kernel_width))
        erode_h = max(1, int(self.erode_kernel_height))
        erode_iter = max(0, int(self.erode_iterations))
        if erode_iter > 0:
            erode_kernel = np.ones((erode_h, erode_w), np.uint8)
            mask = cv2.erode(mask, erode_kernel, iterations=erode_iter)
        
        # Find contours
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        boxes: List[Box] = []
        for c in contours:
            area = cv2.contourArea(c)
            if area < self.min_area:
                continue
                
            # Advanced contour filtering từ v2
            if self._should_filter_contour(c):
                continue
                
            x, y, w, h = cv2.boundingRect(c)
            
            # Sandwich check từ v2 (target verification)
            if self.enable_sandwich_check:
                if not self._verify_target_sandwich(mask, x + w//2, y + h//2):
                    continue
            
            # Calculate confidence based on contour properties
            confidence = self._calculate_confidence(c, area)
            boxes.append(Box(x, y, w, h, label="hsv", score=confidence, source="hsv"))
        
        boxes = _merge_by_iou(boxes, self.merge_iou)
        
        debug_info = {
            "mask": mask,
            "original_contours": len(contours),
            "filtered_contours": len(boxes),
            "hsv_enhanced": self.hsv_saturation_boost != 1.0 or self.hsv_value_boost != 1.0,
            "noise_reduction": any([self.gaussian_blur_kernel > 0, self.median_blur_kernel > 0, self.bilateral_filter_d > 0])
        }
        
        return boxes, debug_info
    
    def _should_filter_contour(self, contour) -> bool:
        """Advanced contour filtering từ v2"""
        try:
            # Approximate contour to polygon
            epsilon = self.contour_approximation * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)
            
            # Get bounding rectangle
            x, y, w, h = cv2.boundingRect(contour)
            
            # Aspect ratio check
            aspect_ratio = float(w) / h if h > 0 else 0
            if aspect_ratio < self.aspect_ratio_min or aspect_ratio > self.aspect_ratio_max:
                return True
            
            # Solidity check (contour area / convex hull area)
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            if hull_area > 0:
                solidity = cv2.contourArea(contour) / hull_area
                if solidity < self.solidity_min:
                    return True
            
            # Extent check (contour area / bounding rectangle area)
            rect_area = w * h
            if rect_area > 0:
                extent = cv2.contourArea(contour) / rect_area
                if extent < self.extent_min:
                    return True
                    
            return False
        except Exception:
            return True  # Filter out problematic contours
    
    def _verify_target_sandwich(self, mask, cx: int, cy: int) -> bool:
        """Sandwich check từ v2 - verify target has pixels above and below center"""
        try:
            h, w = mask.shape
            scan_h = int(self.sandwich_check_height)
            scan_w = int(self.sandwich_check_scan_width)
            
            # Check bounds
            if cy - scan_h < 0 or cy + scan_h >= h:
                return False
            if cx - scan_w < 0 or cx + scan_w >= w:
                return False
            
            # Check for white pixels above center
            above_region = mask[cy - scan_h:cy, cx - scan_w:cx + scan_w + 1]
            has_above = np.any(above_region > 0)
            
            # Check for white pixels below center  
            below_region = mask[cy:cy + scan_h, cx - scan_w:cx + scan_w + 1]
            has_below = np.any(below_region > 0)
            
            return has_above and has_below
        except Exception:
            return True  # Default to accept if check fails
    
    def _calculate_confidence(self, contour, area: float) -> float:
        """Calculate confidence score based on contour properties"""
        try:
            # Base confidence from area (normalized)
            area_confidence = min(1.0, area / (self.min_area * 5))
            
            # Solidity bonus
            hull = cv2.convexHull(contour)
            hull_area = cv2.contourArea(hull)
            solidity = cv2.contourArea(contour) / hull_area if hull_area > 0 else 0
            solidity_bonus = solidity * 0.2
            
            # Aspect ratio bonus (closer to 1.0 is better for typical targets)
            x, y, w, h = cv2.boundingRect(contour)
            aspect_ratio = float(w) / h if h > 0 else 0
            aspect_bonus = 0.1 if 0.7 <= aspect_ratio <= 1.3 else 0
            
            confidence = min(1.0, 0.7 + area_confidence * 0.3 + solidity_bonus + aspect_bonus)
            return confidence
        except Exception:
            return 0.5  # Default confidence
    
    def update_config(self, config: Dict[str, Any]):
        """Update configuration parameters dynamically"""
        for key, value in config.items():
            if hasattr(self, key):
                # Convert to appropriate type
                attr = getattr(self, key)
                if isinstance(attr, bool):
                    setattr(self, key, bool(value))
                elif isinstance(attr, int):
                    setattr(self, key, int(value))
                elif isinstance(attr, float):
                    setattr(self, key, float(value))
                elif isinstance(attr, np.ndarray):
                    setattr(self, key, np.array(value, dtype=attr.dtype))
