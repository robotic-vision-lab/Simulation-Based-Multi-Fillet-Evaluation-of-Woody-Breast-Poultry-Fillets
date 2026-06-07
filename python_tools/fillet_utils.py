"""
analysis functions for poultry fillet evaluation.
"""
import cv2
import zmq
import numpy as np
from skimage.morphology import skeletonize

def drain_sock(sock):
    """Uses a ZMQ socket to fetch the most recent frame."""
    latest = None
    while True:
        try:
            latest = sock.recv_multipart(flags=zmq.NOBLOCK)
        except zmq.Again:
            break
    return latest

def calc_be(mask, contour, draw_frame=None):
    """Calculates the normalized Bending Energy (BE) of a fillet contour."""
    try:
        if len(contour) < 5: 
            return 0.0

        M = cv2.moments(contour)
        if M['m00'] == 0: 
            return 0.0
        
        mu20, mu02, mu11 = M['mu20'], M['mu02'], M['mu11']
        angle_rad = 0.5 * np.arctan2(2 * mu11, mu20 - mu02)
        angle_deg = np.degrees(angle_rad)
        
        x, y, w, h = cv2.boundingRect(contour)
        pad = int(max(w, h) * 0.8)
        h_img, w_img = mask.shape
        y1, y2 = max(0, y - pad), min(h_img, y + h + pad)
        x1, x2 = max(0, x - pad), min(w_img, x + w + pad)
        roi = mask[y1:y2, x1:x2]
        
        center_roi = (roi.shape[1] // 2, roi.shape[0] // 2)
        rot_mat = cv2.getRotationMatrix2D(center_roi, angle_deg, 1.0)
        rot_mat_inv = cv2.invertAffineTransform(rot_mat)
        rotated_roi = cv2.warpAffine(roi, rot_mat, (roi.shape[1], roi.shape[0]), flags=cv2.INTER_NEAREST)

        skeleton = skeletonize(rotated_roi // 255)
        y_coords, x_coords = np.nonzero(skeleton)
        if len(x_coords) < 10: 
            return 0.0

        x_range = np.max(x_coords) - np.min(x_coords)
        y_range = np.max(y_coords) - np.min(y_coords)
        
        swapped = y_range > x_range
        x_fit, y_fit = (y_coords, x_coords) if swapped else (x_coords, y_coords)

        a, b, c = np.polyfit(x_fit, y_fit, 2)

        if draw_frame is not None:
            poly_x_vis = np.linspace(min(x_fit), max(x_fit), num=50)
            poly_y_vis = a * poly_x_vis**2 + b * poly_x_vis + c
            curve_pts_rot = np.column_stack((poly_y_vis, poly_x_vis)) if swapped else np.column_stack((poly_x_vis, poly_y_vis))
            curve_pts_rot = curve_pts_rot.astype(np.float32).reshape(-1, 1, 2)
            curve_unrot = cv2.transform(curve_pts_rot, rot_mat_inv).reshape(-1, 2)
            curve_global = (curve_unrot + [x1, y1]).astype(np.int32)
            cv2.polylines(draw_frame, [curve_global], isClosed=False, color=(255, 0, 0), thickness=2)

        y_prime = 2 * a * x_fit + b
        y_double_prime = 2 * a 
        kappa = np.abs(y_double_prime) / np.power(1 + y_prime**2, 1.5)
        sum_kappa_sq = np.sum(kappa**2)

        P = cv2.arcLength(contour, True)
        poly_x_calc = np.linspace(min(x_fit), max(x_fit), num=100)
        poly_y_calc = a * poly_x_calc**2 + b * poly_x_calc + c
        dx = np.diff(poly_x_calc)
        dy = np.diff(poly_y_calc)
        L = np.sum(np.sqrt(dx**2 + dy**2))
        
        if P == 0 or L == 0: 
            return 0.0
        
        return (P ** 2 / L) * sum_kappa_sq

    except Exception:
        return 0.0

def det_tip_exp(mask, contour, tip_wt_ratio):
    """Detects the expansion length of the fillet tail/tip."""
    x, y, w, h = cv2.boundingRect(contour)
    roi = mask[y:y+h, x:x+w]
    if roi.size == 0: 
        return 0
    
    col_heights = np.sum(roi == 255, axis=0) / 255.0
    max_body_width = np.max(col_heights)
    expansion_thresh = max_body_width * tip_wt_ratio
    tip_len = 0
    
    for i in range(w - 1, -1, -1):
        if col_heights[i] > expansion_thresh:
            tip_len = (w - 1) - i
            break
            
    if tip_len > w * 0.5: 
        return 0
    return tip_len

def get_amp_body(contour, cutoff_x):
    """Amputates the non-rigid tail of the fillet contour."""
    points = contour.reshape(-1, 2)
    mask = points[:, 0] <= cutoff_x
    points_left = points[mask]
    
    if len(points_left) > 5:
        body_contour = points_left.reshape(-1, 1, 2)
        M = cv2.moments(body_contour)
        if M["m00"] != 0:
            return body_contour, (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))
            
    return contour, (0,0)

def seg_watershed(mask):
    """Applies watershed segmentation to separate adjacent fillets."""
    kernel = np.ones((3,3), np.uint8)
    sure_bg = cv2.dilate(mask, kernel, iterations=3)
    dist_transform = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    
    if dist_transform.max() <= 0: 
        return mask 
        
    _, sure_fg = cv2.threshold(dist_transform, 0.5 * dist_transform.max(), 255, 0)
    sure_fg = np.uint8(sure_fg)
    unknown = cv2.subtract(sure_bg, sure_fg)
    
    _, markers = cv2.connectedComponents(sure_fg)
    markers = markers + 1
    markers[unknown == 255] = 0
    
    watershed_input = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
    markers = cv2.watershed(watershed_input, markers)
    
    final_mask = np.zeros_like(mask)
    final_mask[markers > 1] = 255 
    return final_mask