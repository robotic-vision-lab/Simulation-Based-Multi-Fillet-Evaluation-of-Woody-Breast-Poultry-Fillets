"""
Synchronizes ZMQ streams and aggregates top-down and side-view metrics.
"""
import zmq
import cv2
import numpy as np
import time
import csv
import os
import argparse
from fillet_utils import drain_sock
from sideview_eval import SideViewAnalyzer
from topdownview_eval import TopDownAnalyzer

class Args:
    cmd_port = "5557"
    sv_port = "5555"
    tdv_port = "5556"
    scene_port = "5558"
    num_fillets = 1000
    stiff_lvls = [0, 10, 100]
    spd_lvls = [100]
    mass_lvls = [100]
    img_w = 960
    img_h = 696
    img_c = 3
    dir = ""

def main():
    parser = argparse.ArgumentParser(description="Both TDV and SV Evaluation")
    parser.add_argument('--dir', type=str, required=True, help="Directory to save combined CSV output")
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
    
    tdv_sock = ctx.socket(zmq.SUB)
    tdv_sock.connect(f"tcp://localhost:{Args.tdv_port}")
    tdv_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    tdv_sock.setsockopt(zmq.RCVHWM, 1)
    
    scene_sock = ctx.socket(zmq.SUB)
    scene_sock.connect(f"tcp://localhost:{Args.scene_port}")
    scene_sock.setsockopt_string(zmq.SUBSCRIBE, "")
    scene_sock.setsockopt(zmq.RCVHWM, 1)

    sv_analyzer = SideViewAnalyzer()
    tdv_analyzer = TopDownAnalyzer()

    csv_path = os.path.join(Args.dir, "combined_eval.csv")
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

    print("START")
    
    with open(csv_path, mode, newline="") as f:
        writer = csv.writer(f)
        if write_hdr:
            writer.writerow(["MeshID", "Speed", "Stiff", "Mass", "L", "W", "H", "Avg_ShapeScore", "Min_NMDM", "Max_BE"])

        for mesh_id in range(start_id, Args.num_fillets):
            for spd in Args.spd_lvls:
                for stiff in Args.stiff_lvls:
                    for mass in Args.mass_lvls:
                        print(f"Mesh {mesh_id} | Spd {spd} | Stiff {stiff} | Mass {mass}...", end="", flush=True)
                        
                        sv_analyzer.reset()
                        tdv_analyzer.reset_run()
                        
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
                            # side view
                            sv_parts = drain_sock(sv_sock)
                            if sv_parts and len(sv_parts) >= 2:
                                sv_arr = np.frombuffer(sv_parts[1], dtype=np.uint8).reshape((Args.img_h, Args.img_w, Args.img_c))
                                sv_frame = cv2.flip(cv2.cvtColor(sv_arr, cv2.COLOR_RGB2BGR), 0)
                                sv_out = sv_analyzer.analyze_img(sv_frame)
                                cv2.imshow("Side View", sv_out)

                            # top down view
                            tdv_parts = drain_sock(tdv_sock)
                            if tdv_parts and len(tdv_parts) >= 4:
                                w, h = map(int, tdv_parts[1].decode('utf-8').split(','))
                                tdv_rgb = np.frombuffer(tdv_parts[2], dtype=np.uint8).reshape((h, w, 3))
                                tdv_depth = np.frombuffer(tdv_parts[3], dtype=np.float32).reshape((h, w))
                                
                                tdv_rgb = cv2.cvtColor(cv2.flip(tdv_rgb, 0), cv2.COLOR_RGB2BGR)
                                tdv_depth = cv2.flip(tdv_depth, 0)
                                
                                tdv_out = tdv_analyzer.analyze_img(tdv_rgb, tdv_depth)
                                cv2.imshow("Top Down View", tdv_out)

                            # scene view
                            sc_parts = drain_sock(scene_sock)
                            if sc_parts and len(sc_parts) >= 2:
                                sc_arr = np.frombuffer(sc_parts[1], dtype=np.uint8).reshape((Args.img_h, Args.img_w, Args.img_c))
                                sc_frame = cv2.flip(cv2.cvtColor(sc_arr, cv2.COLOR_RGB2BGR), 0)
                                cv2.imshow("Scene View", sc_frame)

                            cv2.waitKey(1)

                            # sync exit condition based on td camera
                            active_cnt = len(tdv_analyzer.track_map)
                            if active_cnt > 0: 
                                tracking_started = True
                                cool_start = None 
                            if tracking_started and active_cnt == 0:
                                if cool_start is None: cool_start = time.time()
                                elif time.time() - cool_start > 0.5: break 

                        # sv metrics
                        fin_nmdm = sv_analyzer.min_nmdm if sv_analyzer.min_nmdm != float('inf') else -1.0
                        fin_be = sv_analyzer.max_be if sv_analyzer.max_be != -1.0 else 0.0
                        
                        # td metrics across all lanes
                        all_f = tdv_analyzer.completed_data + list(tdv_analyzer.track_map.values())
                        valid_f = [d for d in all_f if d['max_shape'] > 0]
                        
                        avg_shape = -1.0
                        if len(valid_f) > 0:
                            avg_shape = np.mean([d['max_shape'] for d in valid_f])

                        writer.writerow([
                            mesh_id, spd, stiff, mass, dim_l, dim_w, dim_h, 
                            f"{avg_shape:.4f}", f"{fin_nmdm:.4f}", f"{fin_be:.4f}"
                        ])
                        f.flush()
                        
                        print(f" NMDM: {fin_nmdm:.3f} | Avg Shape: {avg_shape:.2f}")

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()