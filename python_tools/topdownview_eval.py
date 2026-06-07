"""
Evaluates multi-fillet 2D shape deformation using top-down RGBD data.
"""
import cv2
import zmq
import numpy as np
import time
import csv
import os
import argparse
from scipy.spatial import distance as dist
from collections import OrderedDict
from fillet_utils import det_tip_exp, get_amp_body, seg_watershed, drain_sock

class Args:
    cmd_port = "5557"
    tdv_port = "5556"
    num_fillets = 1000
    stiff_lvls = [0, 20, 40, 60, 80, 100]
    spd_lvls = [100, 130]
    mass_lvls = [100]
    h_thresh = 0.0000001
    edge_x = 568
    thick_cutoff_x = edge_x - 100
    tip_ratio = 0.3 
    ms_wt = 100
    sd_wt = 100
    max_disap_frames = 15
    dir = ""

class TopDownAnalyzer:
    def __init__(self):
        self.bg_depth = None
        self.reset_run()

    def reset_run(self):
        """Clears tracking maps for a new simulation run."""
        self.track_map = OrderedDict()
        self.next_id = 0
        self.completed_data = [] 

    def register_fillet(self, obj):
        self.track_map[self.next_id] = {
            'cent': obj['cent'], 'cnt': obj['cnt'], 
            'disap': 0, 'max_shape': 0.0, 'max_sd': 0.0, 'max_ms': 0.0
        }
        self.next_id += 1

    def disap_fillet(self, f_id):
        self.track_map[f_id]['disap'] += 1
        if self.track_map[f_id]['disap'] > Args.max_disap_frames:
            self.completed_data.append(self.track_map[f_id])
            del self.track_map[f_id]

    def update_fillet(self, f_id, obj):
        self.track_map[f_id].update({'cent': obj['cent'], 'cnt': obj['cnt'], 'disap': 0})

    def analyze_img(self, rgb_frame, depth_arr):
        """Processes synced RGB and Depth arrays and updates multi-fillet trajectories."""
        if self.bg_depth is None:
            self.bg_depth = depth_arr.copy()
            return rgb_frame 
        
        h_map = np.clip(self.bg_depth - depth_arr, 0, None)
        _, init_mask = cv2.threshold(h_map, Args.h_thresh, 255, cv2.THRESH_BINARY)
        final_mask = seg_watershed(init_mask.astype(np.uint8))
        contours, _ = cv2.findContours(final_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        curr_objs = []
        for c in contours:
            if cv2.contourArea(c) > 500:
                M = cv2.moments(c)
                if M["m00"] != 0:
                    curr_objs.append({'cent': (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])), 'cnt': c})

        if len(self.track_map) == 0:
            for obj in curr_objs: 
                self.register_fillet(obj)
        else:
            f_ids = list(self.track_map.keys())
            prev_cents = [f['cent'] for f in self.track_map.values()]
            curr_cents = [obj['cent'] for obj in curr_objs]

            if len(curr_cents) == 0:
                for f_id in f_ids: self.disap_fillet(f_id)
            else:
                D = dist.cdist(np.array(prev_cents), np.array(curr_cents))
                rows = D.min(axis=1).argsort()
                cols = D.argmin(axis=1)[rows]
                used_r, used_c = set(), set()
                
                for (r, c) in zip(rows, cols):
                    if r in used_r or c in used_c: continue
                    self.update_fillet(f_ids[r], curr_objs[c])
                    used_r.add(r)
                    used_c.add(c)
                    
                unused_r = set(range(len(prev_cents))).difference(used_r)
                unused_c = set(range(len(curr_cents))).difference(used_c)
                for r in unused_r: self.disap_fillet(f_ids[r])
                for c in unused_c: self.register_fillet(curr_objs[c])

        for (f_id, data) in self.track_map.items():
            if data['disap'] == 0:
                self._score_fillet(data, final_mask, rgb_frame)
                
        return rgb_frame

    def _score_fillet(self, data, mask, frame):
        raw_cnt = data['cnt']
        M = cv2.moments(raw_cnt)
        if M["m00"] == 0: return

        raw_tip_x = raw_cnt[:, :, 0].max()

        # init
        if 'ref_body' not in data and Args.thick_cutoff_x < raw_tip_x < Args.edge_x:
            tip_len = det_tip_exp(mask, raw_cnt, Args.tip_ratio)
            data['tip_len'] = tip_len
            tail_x = raw_cnt[:, :, 0].min()
            data['body_len'] = (raw_cnt[:, :, 0].max() - tail_x) - tip_len
            
            body_cnt, body_cent = get_amp_body(raw_cnt, tail_x + data['body_len'])
            data['ref_body'] = body_cnt
            
            rect = cv2.minAreaRect(body_cnt)
            s_side, l_side = min(rect[1]), max(rect[1])
            data['body_ar'] = (l_side / s_side) if s_side > 0 else 1.0
            data['tail_offset'] = body_cent[0] - tail_x
            
            hull = cv2.convexHull(body_cnt)
            data['ref_sol'] = cv2.contourArea(body_cnt) / cv2.contourArea(hull) if cv2.contourArea(hull) > 0 else 1.0

        # scoring
        vis_cnt = raw_cnt
        is_rec = False 

        if 'ref_body' in data:
            curr_tail_x = raw_cnt[:, :, 0].min()
            curr_tip_x = raw_cnt[:, :, 0].max()
            rigid_cut_x = curr_tail_x + data['body_len']
            safe_cut_x = curr_tip_x - (data.get('tip_len', 0) * 0.5)
            
            virt_cx = curr_tail_x + data['tail_offset']
            curr_body, _ = get_amp_body(raw_cnt, min(rigid_cut_x, safe_cut_x))
            vis_cnt = curr_body

            if rigid_cut_x >= Args.edge_x and virt_cx < Args.edge_x:
                is_rec = True 
                
                raw_score = cv2.matchShapes(data['ref_body'], curr_body, cv2.CONTOURS_MATCH_I1, 0.0)
                norm_score = raw_score / data['body_ar']
                
                hull = cv2.convexHull(curr_body)
                curr_sol = cv2.contourArea(curr_body) / cv2.contourArea(hull) if cv2.contourArea(hull) > 0 else 1.0
                sol_diff = abs(curr_sol - data['ref_sol'])
                
                smart_score = (norm_score * Args.ms_wt) + (sol_diff * Args.sd_wt)
                
                data['max_shape'] = max(data.get('max_shape', 0.0), smart_score)
                data['max_ms'] = max(data.get('max_ms', 0), norm_score)
                data['max_sd'] = max(data.get('max_sd', 0), sol_diff)
                
                cv2.putText(frame, f"S:{smart_score:.1f}", (int(virt_cx), int(data['cent'][1])), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            else:
                cv2.putText(frame, f"LOCKED", (int(virt_cx), int(data['cent'][1])), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        cv2.drawContours(frame, [vis_cnt], -1, (0, 255, 0) if is_rec else (0, 0, 255), 2)

def main():
    parser = argparse.ArgumentParser(description="Top Down Evaluation")
    parser.add_argument('--dir', type=str, required=True, help="Directory to save CSV output")
    parsed = parser.parse_args()
    Args.dir = parsed.dir

    if not os.path.exists(Args.dir): 
        os.makedirs(Args.dir)

    ctx = zmq.Context()
    cmd_sock = ctx.socket(zmq.REQ)
    cmd_sock.connect(f"tcp://localhost:{Args.cmd_port}")
    cmd_sock.setsockopt(zmq.LINGER, 0)
    
    tdv_sock = ctx.socket(zmq.SUB)
    tdv_sock.connect(f"tcp://localhost:{Args.tdv_port}")
    tdv_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    tdv_sock.setsockopt(zmq.RCVHWM, 1)

    analyzer = TopDownAnalyzer()
    csv_path = os.path.join(Args.dir, "topdown_eval.csv")

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
            writer.writerow(["MeshID", "Speed", "Stiff", "Mass", "RowID", "CentY", "MaxScore", "MaxMS", "MaxSD", "L", "W", "H"])
        
        for mesh_id in range(start_id, Args.num_fillets):
            for spd in Args.spd_lvls:
                for stiff in Args.stiff_lvls:
                    for mass in Args.mass_lvls:
                        print(f"Mesh {mesh_id} | Spd {spd} | Stiff {stiff} | Mass {mass}...", end="", flush=True)
                        analyzer.reset_run()
                        
                        cmd_sock.send_string(f"SPAWN:{mesh_id}:{float(stiff)}:{float(spd)}:{float(mass)}")
                        
                        dim_l, dim_w, dim_h = 0, 0, 0
                        if cmd_sock.poll(2000):
                            resp = cmd_sock.recv_string()
                            try:
                                parts = resp.split(':')
                                if len(parts) >= 4 and parts[0] == "OK":
                                    dim_l, dim_w, dim_h = float(parts[1]), float(parts[2]), float(parts[3])
                                elif len(parts) == 3:
                                    dim_l, dim_w, dim_h = float(parts[0]), float(parts[1]), float(parts[2])
                            except ValueError: pass 
                        else:
                            print(" TIMEOUT")
                            cmd_sock.close()
                            cmd_sock = ctx.socket(zmq.REQ)
                            cmd_sock.connect(f"tcp://localhost:{Args.cmd_port}")
                            continue

                        start_t = time.time()
                        max_wait = 25.0 
                        tracking_started = False
                        cool_start = None
                        
                        while time.time() - start_t < max_wait:
                            parts = drain_sock(tdv_sock)
                            if parts and len(parts) >= 4:
                                w, h = map(int, parts[1].decode('utf-8').split(','))
                                rgb = np.frombuffer(parts[2], dtype=np.uint8).reshape((h, w, 3))
                                depth = np.frombuffer(parts[3], dtype=np.float32).reshape((h, w))
                                
                                rgb = cv2.cvtColor(cv2.flip(rgb, 0), cv2.COLOR_RGB2BGR)
                                depth = cv2.flip(depth, 0)

                                out_frame = analyzer.analyze_img(rgb, depth)
                                cv2.imshow("TopDown Analysis", out_frame)
                                cv2.waitKey(1)
                            
                            active_cnt = len(analyzer.track_map)
                            if active_cnt > 0: 
                                tracking_started = True
                                cool_start = None 
                            if tracking_started and active_cnt == 0:
                                if cool_start is None: cool_start = time.time()
                                elif time.time() - cool_start > 0.5: break 
                        
                        all_f = analyzer.completed_data + list(analyzer.track_map.values())
                        valid_f = sorted([d for d in all_f if d['max_shape'] > 0], key=lambda x: x['cent'][1])
                        
                        valid_cnt = 0
                        for i, data in enumerate(valid_f):
                            writer.writerow([
                                mesh_id, spd, stiff, mass, i, data['cent'][1], 
                                f"{data['max_shape']:.4f}", f"{data['max_ms']:.4f}", f"{data['max_sd']:.4f}",
                                dim_l, dim_w, dim_h 
                            ])
                            valid_cnt += 1
                        
                        if valid_cnt > 0:
                            avg_score = np.mean([d['max_shape'] for d in valid_f])
                            print(f" Count: {valid_cnt} | AvgScore: {avg_score:.2f}")
                        else:
                            print("No Data")
                            writer.writerow([mesh_id, spd, stiff, mass, -1, 0, 0, 0, 0, dim_l, dim_w, dim_h])
                        
                        f.flush()

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()