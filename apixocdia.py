from flask import Flask, jsonify
import threading
import websocket
import json
import time
from typing import List, Tuple, Dict, Any, Callable
import math
from collections import deque
import logging

# Thiết lập logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ================= Cấu hình WebSocket =================
# LƯU Ý QUAN TRỌNG: URL đã được cập nhật nhưng có thể hết hạn.
# Vui lòng cập nhật "connectionToken" và "access_token" nếu cần thiết!
WS_URL = "wss://taixiumd5.system32-cloudfare-356783752985678522.monster/signalr/reconnect?transport=webSockets&connectionToken=SgIYXqnbkJRw6FvkcaXYVrAcj9Rkcx758qlxIanF3odMFBbrqY%2BJJ%2FVvZUnOX0Z2pNFJwckC2pCxXefKhAclClEefIExyEGKc9Z6zfoZsoa9oUAzcs1LNw2G3jxr7w9j&connectionData=%5B%7B%22name%22%3A%22md5luckydiceHub%22%7D%5D&tid=6&access_token=05%2F7JlwSPGzg4ARi0d7%2FLOcNQQ%2BecAvgB3UwDAmuWFJiZj%2Blw1TcJ0PZt5VeUAHKLVCmODRrV5CHPNbit3mc868w8zYBuyQ5Xlu1AZVsEElr9od2qJ8S9N2GLAdQnd0VL8fj8IAGPMsP45pdIIXZysKmhapPBCREit0So1HOC6jOiz5IyKVNadwp8EfsxKzBOKE0z0zdavvY6wXrSZhIJeIqKqVAt3SEuoG82a%2BjwxNo%3D.5a1d88795043d5c4ef6538c9edfb5ff93e65b852d89b71344bdd5ec80eb63e24"
PING_INTERVAL = 15
MAX_HISTORY = 300 # Tăng giới hạn lịch sử lên 300 phiên

# ================= Biến toàn cục & Lock =================
lock = threading.Lock()
# Sử dụng deque để quản lý lịch sử hiệu quả
results_history: deque[str] = deque(maxlen=MAX_HISTORY)
dice_points_history: deque[Dict[str, int]] = deque(maxlen=MAX_HISTORY)

latest_result: Dict[str, Any] = {
    "Phien": None,
    "Xuc_xac_1": -1,
    "Xuc_xac_2": -1,
    "Xuc_xac_3": -1,
    "Tong_diem": -1,
    "Ket_qua": None,
    "Du_doan_tiep": "Đang chờ dữ liệu...",
    "Do_tin_cay": 0.0,
    "id": "thuất ttoán vip " # ID mới cho bản 30 thuật toán
}

# ================= HÀM HỖ TRỢ CHUNG =================
def xac_dinh_tai_xiu(tong: int) -> str:
    """Xác định kết quả Tài/Xỉu dựa trên tổng điểm (3-10 Xỉu, 11-18 Tài)."""
    if tong >= 11:
        return "Tài"
    else:
        return "Xỉu"

def calculate_confidence(base_conf: float) -> float:
    """Tính toán độ tin cậy xác định (Deterministic Confidence). Không có nhiễu ngẫu nhiên."""
    conf = max(base_conf, 50.1)
    conf = min(conf, 99.9)
    return round(conf, 1)

def get_algorithm_result(func: Callable, *args) -> Dict[str, Any]:
    """Hàm wrapper để đảm bảo thuật toán không bị lỗi khi chạy."""
    try:
        return func(*args)
    except Exception as e:
        # logging.error(f"Lỗi khi chạy thuật toán {func.__name__}: {e}")
        return {"du_doan": "Tài", "do_tin_cay": 50.0}

# ==============================================================================
# 30 LỚP THUẬT TOÁN PHÂN TÍCH CHUYÊN SÂU (SUPER ENSEMBLE V3.0)
# ==============================================================================

# ----------------- NHÓM 1: PHÂN TÍCH CHUỖI T/X (10 LỚP) -----------------

def algo_01_long_streak_momentum(results_history: deque) -> Dict[str, Any]:
    """Phân tích Bệt Dài: Dự đoán tiếp tục nếu bệt >= 8."""
    MIN_LEN = 8
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    last_result = results_history[-1]
    streak_length = 0
    for result in reversed(results_history):
        if result == last_result: streak_length += 1
        else: break
    if streak_length >= MIN_LEN:
        conf = 70.0 + min((streak_length - MIN_LEN) * 2.0, 25.0)
        return {"du_doan": last_result, "do_tin_cay": calculate_confidence(conf)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_02_short_reversal_3x(results_history: deque) -> Dict[str, Any]:
    """Phân tích Đảo Chiều Ngắn (3 lần liên tiếp): T-T-T -> Bẻ."""
    MIN_LEN = 3
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    p3, p2, p1 = results_history[-3], results_history[-2], results_history[-1]
    if p3 == p2 and p2 == p1:
        du_doan = "Xỉu" if p1 == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(65.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_03_alternating_reversal(results_history: deque) -> Dict[str, Any]:
    """Phân tích Luân Phiên (T-X-T-X) và dự đoán Bẻ nếu luân phiên >= 6."""
    MIN_ALTERNATION = 6
    if len(results_history) < MIN_ALTERNATION: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    recent = list(results_history)[-MIN_ALTERNATION:]
    is_alternating = all(recent[i] != recent[i+1] for i in range(MIN_ALTERNATION - 1))
    if is_alternating:
        last_result = results_history[-1]
        du_doan = "Xỉu" if last_result == "Tài" else "Tài" # Dự đoán bẻ luân phiên
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(72.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_04_double_break_pattern(results_history: deque) -> Dict[str, Any]:
    """Phân tích Mẫu 2-2 (TTXXT hoặc XXTTX): Dự đoán Hồi về bên 2."""
    MIN_LEN = 5
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    p5, p4, p3, p2, p1 = results_history[-5:]
    if p5 == "Tài" and p4 == "Tài" and p3 == "Xỉu" and p2 == "Xỉu":
        # Mẫu TTXX -> Dự đoán tiếp T
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(60.0)}
    elif p5 == "Xỉu" and p4 == "Xỉu" and p3 == "Tài" and p2 == "Tài":
        # Mẫu XXTT -> Dự đoán tiếp X
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(60.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_05_fibonacci_reversal(results_history: deque) -> Dict[str, Any]:
    """Phân tích Mẫu Fibonacci (2, 3, 5, 8): Bẻ sau chuỗi bệt dài Fibonacci."""
    FIB_BREAK = 8
    if len(results_history) < FIB_BREAK: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    last_result = results_history[-1]
    streak_length = 0
    for result in reversed(results_history):
        if result == last_result: streak_length += 1
        else: break
    if streak_length == FIB_BREAK:
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(75.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_06_minority_correction(results_history: deque) -> Dict[str, Any]:
    """Phân tích Hiệu chỉnh Thiểu số: Nếu 4/5 phiên gần nhất là Tài, dự đoán Xỉu (vì cần cân bằng)."""
    MIN_LEN = 5
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    recent = list(results_history)[-MIN_LEN:]
    tai_count = recent.count("Tài")
    xiu_count = MIN_LEN - tai_count

    if tai_count == 4 and xiu_count == 1:
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(63.0)}
    elif xiu_count == 4 and tai_count == 1:
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(63.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_07_triple_break_pattern(results_history: deque) -> Dict[str, Any]:
    """Phân tích Mẫu 3-1-3 (TTT X TTT): Dự đoán Bẻ sau 3."""
    MIN_LEN = 7
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    p7, p6, p5, p4, p3, p2, p1 = results_history[-7:]
    if p7 == p6 == p5 and p4 != p3 and p3 == p2 == p1:
        # Nếu mẫu là TTT X TTT -> Dự đoán X
        du_doan = "Xỉu" if p1 == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(70.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_08_last_result_continuation(results_history: deque) -> Dict[str, Any]:
    """Chiến lược tiếp diễn đơn giản (Độ tin cậy thấp, dùng làm nền)."""
    if not results_history: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    return {"du_doan": results_history[-1], "do_tin_cay": calculate_confidence(55.0)}

def algo_09_mean_reversion_8(results_history: deque) -> Dict[str, Any]:
    """Phân tích Hồi Quy Trung Bình (8 phiên): Nếu lệch quá 6:2 hoặc 2:6, dự đoán Hồi."""
    MIN_LEN = 8
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    recent = list(results_history)[-MIN_LEN:]
    tai_count = recent.count("Tài")
    xiu_count = MIN_LEN - tai_count

    if tai_count >= 6 and tai_count > xiu_count + 3: # Lệch Tài mạnh (6:2, 7:1, 8:0)
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(68.0)}
    elif xiu_count >= 6 and xiu_count > tai_count + 3: # Lệch Xỉu mạnh
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(68.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_10_two_streak_interruption(results_history: deque) -> Dict[str, Any]:
    """Phân tích Gián đoạn Chuỗi 2 (T-T-X, X-X-T): Dự đoán Hồi về Chuỗi."""
    MIN_LEN = 3
    if len(results_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    p3, p2, p1 = results_history[-3], results_history[-2], results_history[-1]

    if p3 == "Tài" and p2 == "Tài" and p1 == "Xỉu":
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(64.0)}
    elif p3 == "Xỉu" and p2 == "Xỉu" and p1 == "Tài":
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(64.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}


# ----------------- NHÓM 2: PHÂN TÍCH ĐIỂM TỔNG (10 LỚP) -----------------

def algo_11_parity_trend_15x(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Xu hướng Chẵn/Lẻ của Tổng điểm trong 15 phiên."""
    MIN_LEN = 15
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    parity_score = sum(1 if d['T'] % 2 == 0 else -1 for d in list(dice_points_history)[-MIN_LEN:])

    if parity_score >= 6: # Xu hướng Chẵn mạnh -> Xỉu
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(65.0)}
    elif parity_score <= -6: # Xu hướng Lẻ mạnh -> Tài
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(65.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_12_sum_volatility_analysis(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Biến Động (Std Dev > 3.0 -> Đảo Chiều)."""
    MIN_LEN = 15
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    avg_T = sum(T_history) / MIN_LEN
    variance = sum((t - avg_T) ** 2 for t in T_history) / MIN_LEN
    std_dev_T = math.sqrt(variance)

    if std_dev_T >= 3.0: # Biến động cao -> Dự đoán Bẻ
        last_result = xac_dinh_tai_xiu(T_history[-1])
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(70.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_13_extreme_point_reversal(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Điểm Cực: T=3 hoặc T=18 -> Dự đoán Bẻ mạnh."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    last_T = dice_points_history[-1]['T']

    if last_T == 18:
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(80.0)}
    elif last_T == 3:
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(80.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_14_high_low_point_bias_30x(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Lệch Điểm Cao/Thấp (High/Low Bias) trong 30 phiên."""
    MIN_LEN = 30
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    high_count = sum(1 for t in T_history if t >= 14) # Điểm cao (14-18)
    low_count = sum(1 for t in T_history if t <= 7)  # Điểm thấp (3-7)

    if high_count >= 12 and high_count > low_count + 5:
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(68.0)}
    elif low_count >= 12 and low_count > high_count + 5:
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(68.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_15_mean_reversion_to_10_5(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Hồi Quy Trung Bình về 10.5 (20 phiên): Nếu quá lệch, dự đoán Hồi."""
    MIN_LEN = 20
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    avg_T = sum(T_history) / MIN_LEN

    if avg_T >= 11.5: # Quá thiên về Tài
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(72.0)}
    elif avg_T <= 9.5: # Quá thiên về Xỉu
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(72.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_16_consecutive_point_gain(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Tăng điểm liên tiếp (3 phiên): Tăng (> 2 điểm) liên tục -> Tiếp tục xu hướng."""
    MIN_LEN = 3
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    t3, t2, t1 = dice_points_history[-3]['T'], dice_points_history[-2]['T'], dice_points_history[-1]['T']
    
    if t1 > t2 + 2 and t2 > t3 + 2:
        # Tăng mạnh 2 lần liên tiếp
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(67.0)}
    elif t1 < t2 - 2 and t2 < t3 - 2:
        # Giảm mạnh 2 lần liên tiếp
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(67.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_17_sum_near_boundary_reversal(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Điểm Gần Biên (10 hoặc 11): Gần ranh giới -> Dự đoán bẻ sang bên kia."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    last_T = dice_points_history[-1]['T']

    if last_T == 10: # Xỉu lớn -> Dự đoán Tài (Bẻ)
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(66.0)}
    elif last_T == 11: # Tài nhỏ -> Dự đoán Xỉu (Bẻ)
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(66.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_18_low_volatility_continuation(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Biến Động Thấp (Std Dev < 1.5 -> Tiếp tục bệt)."""
    MIN_LEN = 10
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    avg_T = sum(T_history) / MIN_LEN
    variance = sum((t - avg_T) ** 2 for t in T_history) / MIN_LEN
    std_dev_T = math.sqrt(variance)

    if std_dev_T <= 1.5:
        last_result = xac_dinh_tai_xiu(T_history[-1])
        return {"du_doan": last_result, "do_tin_cay": calculate_confidence(68.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_19_sum_prime_trend(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Xu hướng Số Nguyên Tố: Các điểm tổng 3, 5, 7, 11, 13, 17."""
    PRIME_NUMBERS = {3, 5, 7, 11, 13, 17}
    MIN_LEN = 20
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    prime_count = sum(1 for t in T_history if t in PRIME_NUMBERS)
    
    if prime_count >= 13: # Hơn 65% là số nguyên tố
        # Các số nguyên tố có xu hướng phân bố nhiều hơn ở Tài (11, 13, 17)
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(60.0)}
    elif prime_count <= 7: # Dưới 35% là số nguyên tố
        # Các số không phải nguyên tố có xu hướng phân bố nhiều hơn ở Xỉu (4, 6, 8, 10)
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(60.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_20_sum_difference_reversal(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Lệch Tổng (5 phiên): Nếu T1 - T5 > 5 điểm -> Dự đoán Hồi về."""
    MIN_LEN = 5
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    t5, t1 = dice_points_history[-5]['T'], dice_points_history[-1]['T']

    if t1 - t5 >= 6: # Tăng mạnh
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(65.0)} # Dự đoán bẻ
    elif t5 - t1 >= 6: # Giảm mạnh
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(65.0)} # Dự đoán bẻ
    return {"du_doan": "Tài", "do_tin_cay": 50.0}


# ----------------- NHÓM 3: PHÂN TÍCH CẤU TRÚC XÚC XẮC (10 LỚP) -----------------

def algo_21_dice_face_frequency_bias(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Tần suất Mặt xúc xắc (20 phiên): Nếu mặt 6 hoặc 1 quá lệch -> Dự đoán Hồi."""
    MIN_LEN = 20
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    
    face_counts = {i: 0 for i in range(1, 7)}
    for d in list(dice_points_history)[-MIN_LEN:]:
        face_counts[d['X1']] += 1
        face_counts[d['X2']] += 1
        face_counts[d['X3']] += 1
    
    # Số lần xuất hiện kỳ vọng: 20 sessions * 3 dice / 6 faces = 10 lần
    if face_counts[6] >= 16: # Mặt 6 xuất hiện quá nhiều (>1.6 lần kỳ vọng)
        # Quá nhiều 6 -> Tài bị lệch. Dự đoán Xỉu
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(68.0)}
    elif face_counts[1] >= 16: # Mặt 1 xuất hiện quá nhiều
        # Quá nhiều 1 -> Xỉu bị lệch. Dự đoán Tài
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(68.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_22_single_dice_repetition(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Lặp lại Mặt Xúc xắc Đơn (3 phiên): X1 = X2 = X3 (phiên trước) -> Bẻ."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    d = dice_points_history[-1]
    
    if d['X1'] == d['X2'] and d['X2'] == d['X3']: # Bộ Ba (Triple)
        last_result = xac_dinh_tai_xiu(d['T'])
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(75.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_23_center_point_cluster(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Cụm Điểm Trung tâm (9-12): Nếu 5/7 phiên là điểm trung tâm -> Dự đoán Biên."""
    MIN_LEN = 7
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    recent_T = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    center_count = sum(1 for t in recent_T if 9 <= t <= 12)
    
    if center_count >= 5: # Điểm tụ trung tâm mạnh
        # Dự đoán bẻ ra 2 biên (Tài hoặc Xỉu)
        # Vì Tài và Xỉu có xác suất cân bằng hơn, ta dự đoán ngược lại kết quả cuối
        last_result = xac_dinh_tai_xiu(recent_T[-1])
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(63.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_24_dice_sum_parity_trend(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Xu hướng Chẵn/Lẻ của X1+X2 (không tính X3)."""
    MIN_LEN = 10
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    
    parity_score = 0
    for d in list(dice_points_history)[-MIN_LEN:]:
        sum_x12 = d['X1'] + d['X2']
        parity_score += 1 if sum_x12 % 2 == 0 else -1 # Chẵn (+1), Lẻ (-1)

    if parity_score >= 4: # X1+X2 có xu hướng Chẵn mạnh -> X3 có khả năng Lẻ để bù trừ
        # X1+X2=Chẵn. Nếu X3=Lẻ -> Tổng là Lẻ -> Tài (11, 13, 15, 17)
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(62.0)}
    elif parity_score <= -4: # X1+X2 có xu hướng Lẻ mạnh -> X3 có khả năng Chẵn để bù trừ
        # X1+X2=Lẻ. Nếu X3=Chẵn -> Tổng là Lẻ -> Tài
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(62.0)} # Cần phân tích sâu hơn, tạm dự đoán Tài

    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_25_last_dice_bias(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Mặt Xúc xắc cuối (X3): Nếu X3 thường là 1,2,3 -> Dự đoán Tài (vì X3 cần kéo điểm lên)."""
    MIN_LEN = 10
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    low_x3_count = sum(1 for d in list(dice_points_history)[-MIN_LEN:] if d['X3'] <= 3)

    if low_x3_count >= 7: # X3 thường là điểm thấp
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(60.0)}
    elif low_x3_count <= 3: # X3 thường là điểm cao
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(60.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_26_three_dice_difference(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Lệch 3 Xúc xắc: Nếu |X1-X2|+|X2-X3| lớn (>8) -> Dự đoán Biến động cao (Bẻ)."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    d = dice_points_history[-1]
    diff_score = abs(d['X1'] - d['X2']) + abs(d['X2'] - d['X3']) + abs(d['X1'] - d['X3'])
    
    if diff_score >= 9: # Điểm lệch lớn (vd: 1-6-1)
        last_result = xac_dinh_tai_xiu(d['T'])
        du_doan = "Xỉu" if last_result == "Tài" else "Tài"
        return {"du_doan": du_doan, "do_tin_cay": calculate_confidence(69.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_27_same_point_reversion(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Điểm Giống nhau (vd: 4, 4, 6): Nếu có 2 xúc xắc giống nhau -> Dự đoán tiếp diễn."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    d = dice_points_history[-1]
    
    is_double = (d['X1'] == d['X2'] or d['X1'] == d['X3'] or d['X2'] == d['X3'])
    
    if is_double:
        # Nếu có đôi (Double) -> Thường là dấu hiệu của sự ổn định/tiếp diễn
        return {"du_doan": xac_dinh_tai_xiu(d['T']), "do_tin_cay": calculate_confidence(60.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_28_dice_average_bias(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Lệch Trung bình: Trung bình điểm xúc xắc (> 3.8 hoặc < 3.2)."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    d = dice_points_history[-1]
    avg_dice = d['T'] / 3.0
    last_result = xac_dinh_tai_xiu(d['T'])

    if avg_dice >= 4.0: # Trung bình cao -> Tiếp tục Tài
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(65.0)}
    elif avg_dice <= 3.0: # Trung bình thấp -> Tiếp tục Xỉu
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(65.0)}
    return {"du_doan": last_result, "do_tin_cay": 50.0}

def algo_29_sum_modulo_reversal(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Modulo 4: T Mod 4 = 0 hoặc 1 -> Dự đoán Xỉu/Tài ngược lại."""
    MIN_LEN = 1
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}
    last_T = dice_points_history[-1]['T']
    
    if last_T % 4 == 0: # Điểm 4, 8, 12, 16 -> Điểm chẵn -> Dự đoán Tài (Bẻ)
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(62.0)}
    elif last_T % 4 == 1: # Điểm 5, 9, 13, 17 -> Điểm lẻ -> Dự đoán Xỉu (Bẻ)
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(62.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}

def algo_30_distribution_symmetry_300x(dice_points_history: deque) -> Dict[str, Any]:
    """Phân tích Độ Đối Xứng Phân Phối Dài (300 phiên): Nếu lệch mạnh -> Dự đoán Hồi."""
    MIN_LEN = 100
    if len(dice_points_history) < MIN_LEN: return {"du_doan": "Tài", "do_tin_cay": 50.0}

    T_history = [d['T'] for d in list(dice_points_history)[-MIN_LEN:]]
    avg_T = sum(T_history) / MIN_LEN

    bias = avg_T - 10.5 # Độ lệch so với điểm cân bằng
    
    if bias >= 0.5: # Lệch Tài mạnh
        return {"du_doan": "Xỉu", "do_tin_cay": calculate_confidence(75.0)}
    elif bias <= -0.5: # Lệch Xỉu mạnh
        return {"du_doan": "Tài", "do_tin_cay": calculate_confidence(75.0)}
    return {"du_doan": "Tài", "do_tin_cay": 50.0}


# ==============================================================================
# HÀM DỰ ĐOÁN TỔNG HỢP (SUPER ENSEMBLE V3.0 - 30 LAYERS)
# ==============================================================================

def super_complex_pentter_ai(results_history: deque, dice_points_history: deque) -> Dict[str, Any]:
    """
    Hệ thống AI Đa tầng, kết hợp 30 thuật toán chuyên sâu với Trọng số Động (Dynamic Weighted Ensemble)
    """
    
    # Cấu trúc: (Hàm thuật toán, Yêu cầu tối thiểu về lịch sử T/X, Yêu cầu tối thiểu về lịch sử Điểm)
    all_layers: List[Tuple[Callable, int, int]] = [
        # Nhóm 1: Phân tích Chuỗi (Sequence Analysis)
        (algo_01_long_streak_momentum, 8, 0),
        (algo_02_short_reversal_3x, 3, 0),
        (algo_03_alternating_reversal, 6, 0),
        (algo_04_double_break_pattern, 5, 0),
        (algo_05_fibonacci_reversal, 8, 0),
        (algo_06_minority_correction, 5, 0),
        (algo_07_triple_break_pattern, 7, 0),
        (algo_08_last_result_continuation, 1, 0), # Nền tảng
        (algo_09_mean_reversion_8, 8, 0),
        (algo_10_two_streak_interruption, 3, 0),
        
        # Nhóm 2: Phân tích Điểm Tổng (Sum Analysis)
        (algo_11_parity_trend_15x, 0, 15),
        (algo_12_sum_volatility_analysis, 0, 15),
        (algo_13_extreme_point_reversal, 0, 1),
        (algo_14_high_low_point_bias_30x, 0, 30),
        (algo_15_mean_reversion_to_10_5, 0, 20),
        (algo_16_consecutive_point_gain, 0, 3),
        (algo_17_sum_near_boundary_reversal, 0, 1),
        (algo_18_low_volatility_continuation, 0, 10),
        (algo_19_sum_prime_trend, 0, 20),
        (algo_20_sum_difference_reversal, 0, 5),

        # Nhóm 3: Phân tích Cấu trúc Xúc Xắc (Dice Structure Analysis)
        (algo_21_dice_face_frequency_bias, 0, 20),
        (algo_22_single_dice_repetition, 0, 1),
        (algo_23_center_point_cluster, 0, 7),
        (algo_24_dice_sum_parity_trend, 0, 10),
        (algo_25_last_dice_bias, 0, 10),
        (algo_26_three_dice_difference, 0, 1),
        (algo_27_same_point_reversion, 0, 1),
        (algo_28_dice_average_bias, 0, 1),
        (algo_29_sum_modulo_reversal, 0, 1),
        (algo_30_distribution_symmetry_300x, 0, 100),
    ]

    score_tai = 0.0
    score_xiu = 0.0
    total_weight = 0.0
    
    min_len_history = len(results_history)
    min_len_dice = len(dice_points_history)
    
    # ------------------ PHÂN TÍCH VÀ BỎ PHIẾU ------------------
    for logic_func, min_res_len, min_dice_len in all_layers:
        
        args = []
        is_runnable = True
        
        # Thêm lịch sử T/X nếu cần
        if min_res_len > 0:
            if min_len_history >= min_res_len:
                args.append(results_history)
            else:
                is_runnable = False
                
        # Thêm lịch sử Điểm nếu cần
        if min_dice_len > 0:
            if min_len_dice >= min_dice_len:
                args.append(dice_points_history)
            else:
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
        default_pred = results_history[-1] if results_history else "Tài"
        return {"du_doan": default_pred, "do_tin_cay": 55.0}
            
    du_doan = "Tài" if score_tai >= score_xiu else "Xỉu"
    
    # TÍNH ĐỘ TIN CẬY CUỐI CÙNG (Dynamic Swing)
    winning_score = max(score_tai, score_xiu)
    losing_score = min(score_tai, score_xiu)

    margin = (winning_score - losing_score) / total_weight
    do_tin_cay = 50.0 + (margin * 49.9)
    
    do_tin_cay = calculate_confidence(do_tin_cay)

    return {"du_doan": du_doan, "do_tin_cay": do_tin_cay}


# ================= Xử lý WebSocket =================
def on_message(ws, message):
    global latest_result, results_history, dice_points_history
    try:
        data = json.loads(message)
        
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
                            # Chỉ xử lý khi nhận được phiên mới hoàn toàn
                            if latest_result["Phien"] != session_id:
                                
                                # 1. Cập nhật và thêm vào lịch sử (dữ liệu phiên vừa xong)
                                # Đảm bảo không thêm dữ liệu rỗng ở lần chạy đầu tiên
                                if latest_result["Ket_qua"]:
                                    results_history.append(latest_result["Ket_qua"])
                                    dice_points_history.append({
                                        'T': latest_result["Tong_diem"],
                                        'X1': latest_result["Xuc_xac_1"],
                                        'X2': latest_result["Xuc_xac_2"],
                                        'X3': latest_result["Xuc_xac_3"]
                                    })
                                    # Ghi log phiên vừa xong
                                    logging.info(f"Phiên {latest_result['Phien']} - Kết quả: {latest_result['Ket_qua']} ({latest_result['Tong_diem']})")

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
                                
                                # Ghi log dự đoán
                                logging.info(f"Dự đoán cho phiên tiếp theo (Sau {session_id}): {pred['du_doan']} - Độ tin cậy: {pred['do_tin_cay']}%")
                                
    except json.JSONDecodeError:
        pass
    except Exception as e:
        logging.error(f"Lỗi xử lý message: {e}")

def on_error(ws, error):
    logging.error(f"WebSocket lỗi: {error}")

def on_close(ws, close_status_code, close_msg):
    logging.warning("WebSocket đóng, thử kết nối lại sau 5s...")
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
    """Khởi động luồng WebSocket để nhận dữ liệu và tự động kết nối lại."""
    while True:
        try:
            ws = websocket.WebSocketApp(
                WS_URL, 
                on_open=on_open, 
                on_message=on_message, 
                on_error=on_error, 
                on_close=on_close
            )
            logging.info("Đang kết nối WebSocket...")
            # run_forever có tính năng tự động reconnect nhưng ta quản lý reconnect thủ công trong on_close
            ws.run_forever(ping_interval=PING_INTERVAL, ping_timeout=10)
        except Exception as e:
            logging.error(f"Lỗi kết nối WebSocket nghiêm trọng: {e}. Thử lại sau 10s...")
            time.sleep(10)


# ================= Flask API =================
app = Flask(__name__)

@app.route("/api/taixiumd5")
def get_latest():
    """Endpoint trả về kết quả phiên mới nhất và dự đoán cho phiên tiếp theo."""
    with lock:
        # Lấy 15 phiên lịch sử T/X và 5 phiên điểm chi tiết gần nhất để hiển thị
        response_data = latest_result.copy()
        response_data["Lich_su_15_phien"] = list(results_history)[-15:]
        response_data["Lich_su_Tong_diem"] = list(dice_points_history)[-5:]
        
        # Thêm thông tin về độ dài lịch sử hiện tại
        response_data["So_luong_phien_TX_hien_tai"] = len(results_history)
        response_data["So_luong_phien_Diem_hien_tai"] = len(dice_points_history)
        
        return jsonify(response_data)

@app.route("/")
def index():
    return "✅ Pentter-AI v3.0 Super Ensemble (30 Lớp Phân tích Chiến lược) đang chạy. Truy cập /api/taixiumd5 để xem dự đoán."

# ================= Main =================
if __name__ == "__main__":
    # Khởi động WebSocket trong một luồng riêng
    threading.Thread(target=start_ws_thread, daemon=True).start()
    
    # Khởi động Flask server
    logging.info("Khởi động Pentter-AI Flask Server tại http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
