"""
Analyzes the bending profile of poultry fillets from a side-view perspective.
"""
import zmq
import numpy as np
import cv2
import time
import csv
import os
import argparse
from fillet_utils import calc_be, drain_sock

class Args:
    cmd_port = "5557"
    sv_port = "5555"
    num_fillets = 1000
    stiff_lvls = [0, 0.1, 0.5, 1, 10, 100, 200, 400]
    spd_lvls = [100, 130]
    mass_lvls = [0.46, 10, 100, 150, 200]
    roller_cx = 480
    roller_cy = 348
    roller_r = 48
    trigger_x = roller_cx + roller_r
    img_w = 960
    img_h = 696
    img_c = 3
    dir = ""

class SideViewAnalyzer:
    def __init__(self):
        self.bg = None
        self.reset()

    def reset(self):
        """Resets the tracking state for the next fillet."""
        self.tracking = False
        self.min_nmdm = float('inf')
        self.min_mdm = float('inf')
        self.max_be = -1.0 
        self.init_h = None
        self.finished = False

    def get_mask(self, frame, bg):
        thresh_sens = 30 
        blur_frame = cv2.GaussianBlur(frame, (5, 5), 0)
        blur_bg = cv2.GaussianBlur(bg, (5, 5), 0)
        diff = cv2.absdiff(blur_bg, blur_frame)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, thresh_sens, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5,5), np.uint8), iterations=2)
        
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        final_mask = np.zeros_like(mask)
        for cnt in contours:
            if cv2.contourArea(cnt) > 500:
                cv2.drawContours(final_mask, [cnt], -1, 255, -1)
        return final_mask

    def analyze_img(self, frame):
        """Processes a single BGR image array and updates bending metrics."""
        if self.bg is None:
            self.bg = frame.copy()
            return frame

        mask = self.get_mask(frame, self.bg)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        largest_cnt = None
        max_area = 0
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area > max_area:
                max_area = area
                largest_cnt = cnt

        if largest_cnt is not None and max_area > 1000:
            cv2.drawContours(frame, [largest_cnt], -1, (0, 255, 0), 2)
            x, y, w, h = cv2.boundingRect(largest_cnt)
            tip_x = x
            
            M = cv2.moments(largest_cnt)
            if M["m00"] > 0:
                cX = int(M["m10"] / M["m00"])
                cY = int(M["m01"] / M["m00"])
                
                cv2.circle(frame, (cX, cY), 5, (0, 0, 255), -1)
                cv2.line(frame, (cX, cY), (Args.roller_cx, Args.roller_cy), (0, 255, 255), 2)
                cv2.line(frame, (Args.trigger_x, 0), (Args.trigger_x, Args.img_h), (0, 0, 255), 2)
                cv2.circle(frame, (Args.roller_cx, Args.roller_cy), 5, (255, 0, 0), -1)

                if not self.tracking and tip_x <= Args.trigger_x:
                    if tip_x > Args.roller_cx - 100: 
                        self.tracking = True
                        y_inds, _ = np.nonzero(mask)
                        if len(y_inds) > 0:
                            self.init_h = abs(cY - np.min(y_inds))

                if self.tracking and self.init_h:
                    d_i = np.sqrt((cX - Args.roller_cx)**2 + (cY - Args.roller_cy)**2)
                    self.min_mdm = min(self.min_mdm, d_i)

                    H = self.init_h + Args.roller_r
                    nmdm = d_i / H
                    self.min_nmdm = min(self.min_nmdm, nmdm)
                    
                    be = calc_be(mask, largest_cnt, draw_frame=frame)
                    self.max_be = max(self.max_be, be)
                    
                    cv2.putText(frame, f"NMDM: {nmdm:.3f}", (30, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(frame, f"MDM: {d_i:.1f}", (30, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(frame, f"Max BE: {self.max_be:.2e}", (30, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        elif self.tracking:
            self.finished = True
            self.tracking = False

        return frame

def main():
    parser = argparse.ArgumentParser(description="Side View Evaluation")
    parser.add_argument('--dir', type=str, required=True, help="Directory to save CSV output")
    parsed = parser.parse_args()
    Args.dir = parsed.dir

    if not os.path.exists(Args.dir): 
        os.makedirs(Args.dir)

    ctx = zmq.Context()
    cmd_sock = ctx.socket(zmq.REQ)
    cmd_sock.connect(f"tcp://localhost:{Args.cmd_port}")
    cmd_sock.setsockopt(zmq.LINGER, 0)

    sv_sock = ctx.socket(zmq.SUB)
    sv_sock.connect(f"tcp://localhost:{Args.sv_port}")
    sv_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    sv_sock.setsockopt(zmq.RCVHWM, 1)
    
    analyzer = SideViewAnalyzer()
    csv_path = os.path.join(Args.dir, "sideview_eval.csv")
    
    start_id = 0
    mode = "w"
    write_hdr = True

    if os.path.exists(csv_path):
        if input(f"Found existing data at {csv_path}. Resume? (y/n): ").strip().lower() == 'y':
            mode = "a"
            write_hdr = False
            try:
                with open(csv_path, "r") as f:
                    lines = f.readlines()
                    if len(lines) > 1 and lines[-1].strip():
                        start_id = int(lines[-1].strip().split(",")[0]) + 1
            except Exception: pass
    
    with open(csv_path, mode, newline="") as f:
        writer = csv.writer(f)
        if write_hdr:
            writer.writerow(["MeshID", "Speed", "Stiff", "Mass", "L", "W", "H", "MDM", "NMDM", "BE"])
        
        for mesh_id in range(start_id, Args.num_fillets):
            for spd in Args.spd_lvls:
                for stiff in Args.stiff_lvls:
                    for mass in Args.mass_lvls:
                        print(f"Mesh {mesh_id} | Spd {spd} | Stiff {stiff} | Mass {mass}...", end="", flush=True)
                        analyzer.reset()
                        
                        cmd_sock.send_string(f"SPAWN:{mesh_id}:{float(stiff)}:{float(spd)}:{float(mass)}")
                        if cmd_sock.poll(2000): 
                            resp = cmd_sock.recv_string()
                            parts = resp.split(":")
                            try:
                                if len(parts) >= 4 and parts[0] == "OK":
                                    L, W, H = float(parts[1]), float(parts[2]), float(parts[3])
                                elif len(parts) == 3:
                                    L, W, H = float(parts[0]), float(parts[1]), float(parts[2])
                                else: 
                                    L, W, H = 0.0, 0.0, 0.0
                            except ValueError: 
                                L, W, H = 0.0, 0.0, 0.0
                        else:
                            print(" TIMEOUT")
                            cmd_sock.close()
                            cmd_sock = ctx.socket(zmq.REQ)
                            cmd_sock.connect(f"tcp://localhost:{Args.cmd_port}")
                            continue

                        timeout = 6.0 if spd > 20 else 14.0 
                        start_t = time.time()
                        
                        while time.time() - start_t < timeout:
                            parts = drain_sock(sv_sock)
                            if parts and len(parts) >= 2:
                                img_data = parts[1]
                                if len(img_data) == Args.img_w * Args.img_h * Args.img_c:
                                    frame = np.frombuffer(img_data, dtype=np.uint8).reshape((Args.img_h, Args.img_w, Args.img_c))
                                    frame = cv2.flip(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), 0)
                                    
                                    out_frame = analyzer.analyze_img(frame)
                                    cv2.imshow("SideView Data Collector", out_frame)
                                    cv2.waitKey(1) 
                            
                            if analyzer.finished: 
                                break
                        
                        fin_nmdm = analyzer.min_nmdm if analyzer.min_nmdm != float('inf') else -1.0
                        fin_mdm = analyzer.min_mdm if analyzer.min_mdm != float('inf') else -1.0
                        fin_be = analyzer.max_be if analyzer.max_be != -1.0 else 0.0
                        
                        writer.writerow([mesh_id, spd, stiff, mass, L, W, H, fin_mdm, fin_nmdm, fin_be])
                        f.flush()
                        print(f" NMDM: {fin_nmdm:.3f}")

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()