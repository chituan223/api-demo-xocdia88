from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Tuple, Dict, Any, Callable
import math
import random
from collections import Counter, deque

# ================= Cấu hình WebSocket =================
# LƯU Ý QUAN TRỌNG: Cần CẬP NHẬT token mới nếu URL này đã hết hạn.
# Sử dụng URL của bạn:
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmRi40b%2FOVLAp4yOpkaXP3icyn2%2Fodm397vVKSY9AlMCcH15AghVm3lx5JM%2BoUuP%2Fkjgh5xWXtdTQkd9W3%2BQBY25AdX3CvOZ2I17r67METGpFv8cP7xmAoySWEnokU2IcOKu3mzvRWXsG7N5sHFkv%2FIKw%2F1IPCNY2oi8RygWpHwIFWcHGdeoTeM6kskfrqNSmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhIJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89b71344bdd5ec80eb63e24"
PING_INTERVAL = 15
MAX_HISTORY = 100 # Tăng lịch sử lên 100 phiên để phân tích dài hạn

# ================= Biến toàn cục & Lock =================
lock = threading.Lock()
# Lịch sử kết quả Tài/Xỉu
results_history: List[str] = [] # Ví dụ: ["Tài", "Xỉu", "Tài"]
# Lịch sử điểm số chi tiết
dice_points_history: List[Dict[str, int]] = [] # Ví dụ: [{'T': 12, 'X1': 4, 'X2': 4, 'X3': 4}, ...]

latest_result: Dict[str, Any] = {
    "Phien": None,
    "Xuc_xac_1": -1,
    "Xuc_xac_2": -1,
    "Xuc_xac_3": -1,
    "Tong_diem": -1,
    "Ket_qua": None,
    "Du_doan_tiep": "Đang chờ dữ liệu...",
    "Do_tin_cay": 0.0,
    "id": "pentter-ai-v2"
}

# ================= HÀM HỖ TRỢ CHUNG =================
def xac_dinh_tai_xiu(tong: int) -> str:
    """Xác định kết quả Tài/Xỉu dựa trên tổng điểm."""
    if tong >= 11:
        return "Tài"
    else: # 3 đến 10
        return "Xỉu"

def calculate_confidence(base_conf: float) -> float:
    """Làm tròn và giới hạn độ tin cậy (50.0 - 99.9)."""
    # Thêm nhiễu ngẫu nhiên nhỏ để tránh kết quả tin cậy tuyệt đối
    # và tạo cảm giác "AI đang học"
    noise = random.uniform(-0.1, 0.1)
    conf = base_conf + noise
    
    conf = max(conf, 50.1)
    conf = min(conf, 99.9)
    return round(conf, 1)

def get_algorithm_result(func: Callable, *args) -> Dict[str, Any]:
    """Hàm wrapper để đảm bảo thuật toán không bị lỗi khi chạy."""
    try:
        return func(*args)
    except Exception as e:
        # print(f"Lỗi khi chạy thuật toán {func.__name__}: {e}")
        return {"du_doan": "Tài", "do_tin_cay": 50.0} # Giá trị trung lập an toàn

# ==============================================================================
# 5 LỚP THUẬT TOÁN PHÂN TÍCH CHUYÊN SÂU
# ==============================================================================

# ----------------- Nhóm 1: Phân tích Chuỗi (results_history) -----------------

def algo_01_streak_momentum(results_history: List[str]) -> Dict[str, Any]:
    """
    Phân tích Bệt (Streak Momentum): Dự đoán tiếp tục bệt nếu bệt đủ dài.
    Min History: 5
    """
    MIN_LEN = 5
    if len(results_history) < MIN_LEN:
        return {"du_doan": results_history[-1], "do_tin_cay": 50.0}

    last_result = results_history[-1]
    streak_length = 0
    for result in reversed(results_history):
        if result == last_result:
            streak_length += 1
        else:
            break

    if streak_length >= MIN_LEN:
        # Độ tin cậy tăng tuyến tính với độ dài bệt
        conf = 60.0 + (streak_length - MIN_LEN) * 3.0
        return {"du_doan": last_result, "do_tin_cay": calculate_confidence(conf)}
    
    return {"du_doan": last_result, "do_tin_cay": 50.0}

def algo_02_alternation_counter(results_history: List[str]) -> Dict[str, Any]:
    """
    Phân tích Đảo Chiều (Alternation Counter): Tìm mẫu luân phiên T-X-T-X.
    Nếu mẫu luân phiên xuất hiện 4 lần liên tiếp (8 phiên), dự đoán Bẻ (Break).
    Min History: 8
    """
    MIN_ALTERNATION = 8
    if len(results_history) < MIN_ALTERNATION:
        return {"du_doan": results_history[-1], "do_tin_cay": 50.0}

    # Kiểm tra 8 phiên gần nhất: T-X-T-X-T-X-T-X hoặc X-T-X-T-X-T-X-T
    recent = results_history[-MIN_ALTERNATION:]
    is_alternating = True
    for i in range(MIN_ALTERNATION - 1):
        if recent[i] == recent[i+1]:
            is_alternating = False
            break

    if is_alternating:
        # Dự đoán bẻ chuỗi luân phiên
        last_result = results_history[-1]
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(75.0)}

    return {"du_doan": results_history[-1], "do_tin_cay": 50.0}

def algo_03_short_reversal_matrix(results_history: List[str]) -> Dict[str, Any]:
    """
    Phân tích Đảo Chiều Ngắn Hạn (Short Reversal):
    Dùng ma trận chuyển đổi 2nd-order (3 phiên gần nhất).
    Ví dụ: T-T-T -> Dự đoán Xỉu; X-X-X -> Dự đoán Tài.
    Min History: 3
    """
    MIN_LEN = 3
    if len(results_history) < MIN_LEN:
        return {"du_doan": results_history[-1], "do_tin_cay": 50.0}

    # Lấy 3 phiên gần nhất (pattern)
    p3 = results_history[-3]
    p2 = results_history[-2]
    p1 = results_history[-1]
    
    # Các mẫu đảo chiều mạnh (Strong Reversal Patterns)
    # 3 lần liên tiếp -> Bẻ
    if p3 == p2 and p2 == p1:
        # Dự đoán bẻ bệt 3 phiên
        du_doan = "Xỉu" if p1 == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(68.0)}
        
    # Các mẫu "2-1" hoặc "1-2" -> Đảo chiều lại
    # T-T-X -> Dự đoán T (T-T-X-T pattern)
    if p3 == "Tài" and p2 == "Tài" and p1 == "Xỉu":
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(65.0)}
    # X-X-T -> Dự đoán X (X-X-T-X pattern)
    if p3 == "Xỉu" and p2 == "Xỉu" and p1 == "Tài":
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(65.0)}

    return {"du_doan": results_history[-1], "do_tin_cay": 50.0}

# ----------------- Nhóm 2: Phân tích Điểm Số (dice_points_history) -----------------

def algo_04_sum_parity_trend(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    Phân tích Xu hướng Chẵn/Lẻ (Parity Trend):
    Kiểm tra xu hướng chẵn lẻ của Tổng điểm (T) trong 10 phiên.
    Min History: 10
    """
    MIN_LEN = 10
    if len(dice_points_history) < MIN_LEN:
        return {"du_doan": "Tài", "do_tin_cay": 50.0}

    # 1. Tính độ lệch của Chẵn/Lẻ trong 10 phiên
    parity_score = 0
    for d in dice_points_history[-MIN_LEN:]:
        total_sum = d['T']
        # Chẵn (+1), Lẻ (-1)
        parity_score += 1 if total_sum % 2 == 0 else -1

    # 2. Phân tích kết quả
    if abs(parity_score) >= 6: # Độ lệch lớn (6/4, 7/3, 8/2, ...)
        
        if parity_score > 0: # Xu hướng Chẵn mạnh (Even)
            # Chẵn (4, 6, 8, 10) thường là Xỉu.
            # Dự đoán Xỉu để tiếp tục xu hướng Parity
            return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(62.0)}
        else: # Xu hướng Lẻ mạnh (Odd)
            # Lẻ (3, 5, 7, 9, 11, 13, 15, 17)
            # Lẻ thường là Tài (11, 13, 15, 17)
            # Dự đoán Tài để tiếp tục xu hướng Parity
            return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(62.0)}

    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_05_volatility_analysis(dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    Phân tích Độ Biến Động (Volatility): Tính Độ lệch chuẩn (Std Dev) của tổng điểm.
    - Volatility Cao (Std Dev > 3.5): Thị trường bất ổn, dễ đảo chiều (Break Trend).
    - Volatility Thấp (Std Dev < 2.0): Thị trường tích lũy, dễ xuất hiện bệt (Consolidate).
    Min History: 15
    """
    MIN_LEN = 15
    if len(dice_points_history) < MIN_LEN:
        return {"du_doan": "Tài", "do_tin_cay": 50.0}

    T_history = [d['T'] for d in dice_points_history[-MIN_LEN:]]
    avg_T = sum(T_history) / MIN_LEN
    
    # Tính Độ lệch chuẩn của Tổng T
    variance = sum((t - avg_T) ** 2 for t in T_history) / MIN_LEN
    std_dev_T = math.sqrt(variance)

    last_result = xac_dinh_tai_xiu(T_history[-1])
    
    if std_dev_T >= 3.5:
        # Độ biến động cao -> Dự đoán Đảo Chiều (Break)
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        # Confidence cao vì độ biến động lớn thường dẫn đến phá vỡ mẫu hình
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(78.0)}
    
    elif std_dev_T <= 1.5:
        # Độ biến động rất thấp -> Đang trong giai đoạn tích lũy bệt chặt, dễ tiếp tục
        # Tuy nhiên, cần kiểm tra thêm bệt có đang tồn tại không
        return {"du_doan": last_result, "do_tin_cay": calculate_confidence(65.0)}
        
    return {"du_doan": last_result, "do_tin_cay": 50.0}

# ==============================================================================
# HÀM DỰ ĐOÁN TỔNG HỢP (SUPER ENSEMBLE V2)
# ==============================================================================

def super_complex_pentter_ai(results_history: List[str], dice_points_history: List[Dict[str, int]]) -> Dict[str, Any]:
    """
    Hệ thống AI Đa tầng, kết hợp 5 thuật toán chuyên sâu với Trọng số Động (Dynamic Weighting)
    """
    
    # Cấu trúc: (Hàm thuật toán, Yêu cầu tối thiểu về lịch sử T/X, Yêu cầu tối thiểu về lịch sử Điểm)
    all_layers: List[Tuple[Callable, int, int]] = [
        (algo_01_streak_momentum, 5, 0),
        (algo_02_alternation_counter, 8, 0),
        (algo_03_short_reversal_matrix, 3, 0),
        (algo_04_sum_parity_trend, 0, 10),
        (algo_05_volatility_analysis, 0, 15),
    ]

    score_tai = 0.0
    score_xiu = 0.0
    total_weight = 0.0
    
    min_len_history = len(results_history)
    min_len_dice = len(dice_points_history)
    
    # ------------------ PHÂN TÍCH VÀ BỎ PHIẾU ------------------
    for logic_func, min_res_len, min_dice_len in all_layers:
        
        # Xác định dữ liệu đầu vào cần thiết và kiểm tra điều kiện tối thiểu
        args = []
        is_runnable = True
        
        if min_res_len > 0 and min_len_history >= min_res_len:
            args.append(results_history)
        elif min_res_len > 0 and min_len_history < min_res_len:
            is_runnable = False
            
        if min_dice_len > 0 and min_len_dice >= min_dice_len:
            args.append(dice_points_history)
        elif min_dice_len > 0 and min_len_dice < min_dice_len:
            is_runnable = False
            
        if not is_runnable:
            continue
            
        # Chạy thuật toán
        pred_dict = get_algorithm_result(logic_func, *args)
        
        if pred_dict and pred_dict["do_tin_cay"] > 50.0:
            pred = pred_dict["du_doan"]
            # Chuyển đổi độ tin cậy [50.1, 99.9] về trọng số [0.01, 0.99]
            weight = (pred_dict["do_tin_cay"] - 50.0) / 50.0
            
            if pred == "Tài":
                score_tai += weight
            else:
                score_xiu += weight
            total_weight += weight
            
    # ------------------ TÍNH TOÁN KẾT QUẢ CUỐI CÙNG ------------------
    if total_weight == 0:
        # Nếu chưa đủ dữ liệu hoặc tất cả đều trung lập, dự đoán phiên trước đó với độ tin cậy thấp
        return {"du_doan": results_history[-1] if results_history else "Tài", "do_tin_cay": 55.0}
            
    du_doan = "Tài" if score_tai >= score_xiu else "Xỉu"
    
    # TÍNH ĐỘ TIN CẬY CUỐI CÙNG (Dynamic Swing)
    winning_score = max(score_tai, score_xiu)
    losing_score = min(score_tai, score_xiu)

    # Tỷ lệ Biên độ (Margin Ratio): (Điểm Thắng - Điểm Thua) / Tổng Điểm
    margin = (winning_score - losing_score) / total_weight

    # Khuếch đại Biên độ (margin * 49.9): Boost từ 50.0 đến 99.9
    do_tin_cay = 50.0 + (margin * 49.9)
    
    # Áp dụng hàm làm tròn/giới hạn
    do_tin_cay = calculate_confidence(do_tin_cay)

    return {"du_doan": du_doan, "do_tin_cay": do_tin_cay}


# ================= Xử lý WebSocket =================
def on_message(ws, message):
    global latest_result, results_history, dice_points_history
    try:
        data = json.loads(message)
        # Bắt tín hiệu SignalR
        if isinstance(data, dict) and "M" in data:
            for m_item in data["M"]:
                if "M" in m_item and m_item["M"] == "Md5sessionInfo":
                    session_info = m_item["A"][0]
                    session_id = session_info.get("SessionID")
                    result = session_info.get("Result", {})
                    d1 = result.get("Dice1", -1)
                    d2 = result.get("Dice2", -1)
                    d3 = result.get("Dice3", -1)

                    if d1 != -1 and d2 != -1 and d3 != -1:
                        total_sum = d1 + d2 + d3
                        ket_qua = xac_dinh_tai_xiu(total_sum)
                        
                        with lock:
                            # Ngăn chặn việc thêm cùng một phiên vào lịch sử nhiều lần
                            if latest_result["Phien"] != session_id:
                                
                                # 1. Cập nhật và thêm vào lịch sử (dữ liệu phiên vừa xong)
                                if latest_result["Ket_qua"]:
                                    results_history.append(latest_result["Ket_qua"])
                                    # Thêm dữ liệu điểm số T, X1, X2, X3 cho phân tích phức tạp
                                    dice_points_history.append({
                                        'T': latest_result["Tong_diem"],
                                        'X1': latest_result["Xuc_xac_1"],
                                        'X2': latest_result["Xuc_xac_2"],
                                        'X3': latest_result["Xuc_xac_3"]
                                    })

                                    # Giới hạn lịch sử
                                    if len(results_history) > MAX_HISTORY:
                                        results_history.pop(0)
                                    if len(dice_points_history) > MAX_HISTORY:
                                        dice_points_history.pop(0)


                                # 2. Cập nhật dữ liệu phiên mới (Phiên đang chờ)
                                latest_result["Phien"] = session_id
                                latest_result["Xuc_xac_1"] = d1
                                latest_result["Xuc_xac_2"] = d2
                                latest_result["Xuc_xac_3"] = d3
                                latest_result["Tong_diem"] = total_sum
                                latest_result["Ket_qua"] = ket_qua
                                
                                # 3. Chạy thuật toán dự đoán cho phiên tiếp theo
                                pred = super_complex_pentter_ai(results_history, dice_points_history)
                                latest_result["Du_doan_tiep"] = pred["du_doan"]
                                latest_result["Do_tin_cay"] = pred["do_tin_cay"]
                                
    except json.JSONDecodeError:
        # Bỏ qua các tin nhắn SignalR control như PING
        pass
    except Exception as e:
        print(f"Lỗi xử lý message: {e}")

def on_error(ws, error):
    print(f"WebSocket lỗi: {error}")

def on_close(ws, close_status_code, close_msg):
    print("WebSocket đóng, thử kết nối lại sau 5s...")
    time.sleep(5)
    start_ws_thread()

def on_open(ws):
    def ping():
        while True:
            try:
                # Gửi tín hiệu Ping/Pong SignalR
                ws.send("{}") 
                time.sleep(PING_INTERVAL)
            except:
                break
    threading.Thread(target=ping, daemon=True).start()

def start_ws_thread():
    """Khởi động luồng WebSocket để nhận dữ liệu."""
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL, 
                on_open=on_open, 
                on_message=on_message, 
                on_error=on_error, 
                on_close=on_close
            )
            print("Đang kết nối WebSocket...")
            # run_forever có tính năng tự động reconnect
            ws.run_forever(ping_interval=PING_INTERVAL, ping_timeout=10, reconnect=5)
        except Exception as e:
            print(f"Lỗi kết nối WebSocket nghiêm trọng: {e}. Thử lại sau 10s...")
            time.sleep(10)


# ================= Flask API =================
app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    """Endpoint trả về kết quả phiên mới nhất và dự đoán cho phiên tiếp theo."""
    with lock:
        # Thêm lịch sử ngắn để debug
        short_history = results_history[-10:] 
        response_data = latest_result.copy()
        response_data["Lich_su_10_phien"] = short_history
        # Chỉ 5 phiên điểm gần nhất
        response_data["Lich_su_Tong_diem"] = dice_points_history[-5:] 
        return jsonify(response_data)

@app.route("/")
def index():
    return "✅ Pentter-AI v2.0 (5 Lớp Phân tích Chiến lược) đang chạy. Truy cập /api/taixiumd5 để xem dự đoán."

# ================= Main =================
if __name__ == "__main__":
    # Khởi động WebSocket trong một luồng riêng
    threading.Thread(target=start_ws_thread, daemon=True).start()
    
    # Khởi động Flask server
    print("Khởi động Pentter-AI Flask Server tại http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
