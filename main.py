import cv2
import mediapipe as mp
import numpy as np
import random
from PIL import ImageFont, ImageDraw, Image


# ==========================================
# 核心動態校正變數初始化
# ==========================================
is_calibrated = False
calib_data = {
    "Left":  {"home_y": 0.0, "home_mcp_x": 0.0, "borders": []},
    "Right": {"home_y": 0.0, "home_mcp_x": 0.0, "borders": []}
}

# 容許彈性數值
INDEX_STRETCH_FACTOR = 1.5   
KEYBOARD_SLANT = 0.25        
FINGER_SLACK = 0.01        
MAX_SHIFT = 0.015           

# 遊戲狀態機變數
game_state = "IDLE"  
MAX_ROUNDS = 20      
current_round = 0
AVAILABLE_CHARS = list("QWERTYUIOPASDFGHJKLZXCVBNM")
target_char = ""
score = 0
feedback_msg = ""
feedback_color = (255, 255, 255)
feedback_timer = 0

# 延遲判定機制
pending_eval = False
eval_frames_left = 0
FRAMES_TO_WAIT = 4   

def put_chinese_text(img, text, pos, color=(255,255,255), size=20):
    img_pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    font = ImageFont.truetype("C:/Windows/Fonts/msjh.ttc", size)
    draw.text(pos, text, font=font, fill=color)
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# 初始化 MediaPipe Hands
mp_hands = mp.solutions.hands
hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=2,
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)
mp_drawing = mp.solutions.drawing_utils

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

print("=" * 50)
print("系統啟動中... 請將雙手置於 ASDF / JKL; 基準列上")
print("維持正確姿勢後，請按下 'F' 鍵進行精準定位校正。")
print("=" * 50)

while cap.isOpened():
    success, frame = cap.read()
    if not success: break

    frame = cv2.flip(frame, 1)
    h, w, c = frame.shape
    img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(img_rgb)

    left_hand_status = "未偵測"
    right_hand_status = "未偵測"
    left_fingering_alert = "未偵測" if not is_calibrated else "正常"
    right_fingering_alert = "未偵測" if not is_calibrated else "正常"

    current_frame_hands = {}

    if results.multi_hand_landmarks and results.multi_handedness:
        for hand_landmarks, hand_info in zip(results.multi_hand_landmarks, results.multi_handedness):
            raw_label = hand_info.classification[0].label
            hand_label = "Left" if raw_label == "Right" else "Right"
            
            current_frame_hands[hand_label] = hand_landmarks
            mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            pinky_tip = hand_landmarks.landmark[20]
            ring_tip = hand_landmarks.landmark[16]
            middle_tip = hand_landmarks.landmark[12]
            index_tip = hand_landmarks.landmark[8]
            mcp_9 = hand_landmarks.landmark[9]

            if is_calibrated:
                borders = calib_data[hand_label]["borders"]
                home_y = calib_data[hand_label]["home_y"]
                home_mcp_x = calib_data[hand_label]["home_mcp_x"]
                
                current_shift = mcp_9.x - home_mcp_x
                shift_x = max(-MAX_SHIFT, min(MAX_SHIFT, current_shift))
                
                p_proj_x = pinky_tip.x - (pinky_tip.y - home_y) * KEYBOARD_SLANT
                r_proj_x = ring_tip.x - (ring_tip.y - home_y) * KEYBOARD_SLANT
                m_proj_x = middle_tip.x - (middle_tip.y - home_y) * KEYBOARD_SLANT
                i_proj_x = index_tip.x - (index_tip.y - home_y) * KEYBOARD_SLANT
                
                if hand_label == "Left":
                    left_hand_status = "監控中"
                    if p_proj_x > borders[0] + FINGER_SLACK + shift_x: left_fingering_alert = "小指越界！"
                    elif not (borders[0] - FINGER_SLACK + shift_x <= r_proj_x < borders[1] + FINGER_SLACK + shift_x): left_fingering_alert = "無名指越界！"
                    elif not (borders[1] - FINGER_SLACK + shift_x <= m_proj_x < borders[2] + FINGER_SLACK + shift_x): left_fingering_alert = "中指越界！"
                    elif not (borders[2] - FINGER_SLACK + shift_x <= i_proj_x < borders[3] + FINGER_SLACK + shift_x): left_fingering_alert = "食指越界！"
                    else: left_fingering_alert = "正常"
                
                elif hand_label == "Right":
                    right_hand_status = "監控中"
                    if not (borders[0] - FINGER_SLACK + shift_x <= i_proj_x < borders[1] + FINGER_SLACK + shift_x): right_fingering_alert = "食指越界！"
                    elif not (borders[1] - FINGER_SLACK + shift_x <= m_proj_x < borders[2] + FINGER_SLACK + shift_x): right_fingering_alert = "中指越界！"
                    elif not (borders[2] - FINGER_SLACK + shift_x <= r_proj_x < borders[3] + FINGER_SLACK + shift_x): right_fingering_alert = "無名指越界！"
                    elif p_proj_x < borders[3] - FINGER_SLACK + shift_x: right_fingering_alert = "小指越界！"
                    else: right_fingering_alert = "正常"

    # ==========================================
    # 延遲判定機制 (讓畫面跟上按鍵)
    # ==========================================
    if pending_eval:
        if eval_frames_left > 0:
            eval_frames_left -= 1
            feedback_msg = "判定中..."
            feedback_color = (200, 200, 200)
            feedback_timer = 2
        else:
            pending_eval = False
            
            if left_fingering_alert == "正常" and right_fingering_alert == "正常":
                score += 10
                feedback_msg = "Perfect! +10分"
                feedback_color = (0, 255, 0)
            else:
                score = max(0, score - 5)
                feedback_msg = "指法越界！扣5分"
                feedback_color = (255, 0, 0) 
            
            feedback_timer = 20
            current_round += 1
            
            if current_round > MAX_ROUNDS:
                game_state = "GAMEOVER"
            else:
                target_char = random.choice(AVAILABLE_CHARS)

    # ==========================================
    # 鍵盤監聽事件：狀態機切換與觸發答題
    # ==========================================
    key = cv2.waitKey(5) & 0xFF
    
    if (key == ord('f') or key == ord('F')) and game_state == "IDLE":
        if "Left" in current_frame_hands and "Right" in current_frame_hands:
            for label in ["Left", "Right"]:
                lm = current_frame_hands[label]
                home_anchor_y = lm.landmark[9].y
                calib_data[label]["home_y"] = home_anchor_y
                calib_data[label]["home_mcp_x"] = lm.landmark[9].x 
                
                p_raw = lm.landmark[20]
                r_raw = lm.landmark[16]
                m_raw = lm.landmark[12]
                i_raw = lm.landmark[8]

                p_x = p_raw.x - (p_raw.y - home_anchor_y) * KEYBOARD_SLANT
                r_x = r_raw.x - (r_raw.y - home_anchor_y) * KEYBOARD_SLANT
                m_x = m_raw.x - (m_raw.y - home_anchor_y) * KEYBOARD_SLANT
                i_x = i_raw.x - (i_raw.y - home_anchor_y) * KEYBOARD_SLANT
                
                if label == "Left":
                    gap_m_r = m_x - r_x  
                    if p_x >= r_x or (r_x - p_x) > 1.8 * gap_m_r: p_x = r_x - gap_m_r  
                    b0 = (p_x + r_x) / 2
                    b1 = (r_x + m_x) / 2
                    b2 = (m_x + i_x) / 2
                    b3 = i_x + (i_x - m_x) * INDEX_STRETCH_FACTOR 
                    calib_data[label]["borders"] = [b0, b1, b2, b3]
                else:
                    gap_r_m = r_x - m_x 
                    if p_x <= r_x or (p_x - r_x) > 1.8 * gap_r_m: p_x = r_x + gap_r_m  
                    b0 = i_x - (m_x - i_x) * INDEX_STRETCH_FACTOR 
                    b1 = (i_x + m_x) / 2
                    b2 = (m_x + r_x) / 2
                    b3 = (r_x + p_x) / 2
                    calib_data[label]["borders"] = [b0, b1, b2, b3]
                    
            is_calibrated = True
            print("【系統通知】校正成功！")
            
    elif key == 32: 
        if is_calibrated:
            if game_state == "IDLE" or game_state == "GAMEOVER":
                game_state = "PLAYING"
                current_round = 1
                score = 0
                pending_eval = False
                target_char = random.choice(AVAILABLE_CHARS)
                feedback_msg = "遊戲開始！"
                feedback_color = (0, 255, 0)
                feedback_timer = 30
        else:
            print("請先按 F 完成校正，才能啟動遊戲模式！")
            
    elif game_state == "PLAYING" and key > 0 and key != 27 and key != 32 and not pending_eval:
        try:
            pressed_char = chr(key).upper()
            if pressed_char in AVAILABLE_CHARS:
                if pressed_char == target_char:
                    pending_eval = True
                    eval_frames_left = FRAMES_TO_WAIT
                else:
                    feedback_msg = "按錯鍵囉！"
                    feedback_color = (255, 165, 0) 
                    feedback_timer = 20
        except:
            pass

    # ==========================================
    # UI 繪製看板 (Dashboard)
    # ==========================================
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 160), (15, 15, 15), -1)
    
    if game_state in ["PLAYING", "GAMEOVER"]:
        cv2.rectangle(overlay, (w//2 - 250, h//2 - 180), (w//2 + 250, h//2 + 150), (0, 0, 0), -1)
    
    cv2.addWeighted(overlay, 0.75, frame, 0.25, 0, frame)
    cv2.line(frame, (0, 160), (w, 160), (0, 255, 255), 2)
    cv2.line(frame, (w // 2, 0), (w // 2, 110), (50, 50, 50), 1)

    if game_state == "IDLE":
        if not is_calibrated:
            frame = put_chinese_text(frame, "【請將雙手放於基準列，按下 F 鍵進行精準校正】", (w//2 - 345, 115), color=(0, 255, 255), size=30)
        else:
            frame = put_chinese_text(frame, "【校正完成：按 空白鍵 (Space) 啟動訓練遊戲】", (w//2 - 315, 115), color=(0, 255, 0), size=30)

    frame = put_chinese_text(frame, "左手監測面板 (ASDF)", (20, 15), color=(255, 255, 255), size=24)
    frame = put_chinese_text(frame, f"狀態: {left_hand_status}", (20, 55), color=(200, 200, 200), size=18)
    f_color_l = (0, 255, 0) if left_fingering_alert == "正常" else ((200,200,200) if not is_calibrated else (255, 165, 0))
    frame = put_chinese_text(frame, f"指法區域: {left_fingering_alert}", (20, 80), color=f_color_l, size=18)

    frame = put_chinese_text(frame, "右手監測面板 (JKL;)", (w // 2 + 20, 15), color=(255, 255, 255), size=24)
    frame = put_chinese_text(frame, f"狀態: {right_hand_status}", (w // 2 + 20, 55), color=(200, 200, 200), size=18)
    f_color_r = (0, 255, 0) if right_fingering_alert == "正常" else ((200,200,200) if not is_calibrated else (255, 165, 0))
    frame = put_chinese_text(frame, f"指法區域: {right_fingering_alert}", (w // 2 + 20, 80), color=f_color_r, size=18)

    if game_state == "PLAYING":
        frame = put_chinese_text(frame, f"回合: {current_round}/{MAX_ROUNDS}", (w//2 - 230, h//2 - 160), color=(200, 200, 200), size=20)
        frame = put_chinese_text(frame, f"分數: {score}", (w//2 + 130, h//2 - 160), color=(0, 255, 255), size=20)
        
        if pending_eval:
            frame = put_chinese_text(frame, target_char, (w//2 - 50, h//2 - 100), color=(100, 100, 100), size=120)
        else:
            frame = put_chinese_text(frame, target_char, (w//2 - 50, h//2 - 100), color=(255, 255, 255), size=120)
        
        if feedback_timer > 0:
            frame = put_chinese_text(frame, feedback_msg, (w//2 - 90, h//2 + 80), color=feedback_color, size=24)
            feedback_timer -= 1

    elif game_state == "GAMEOVER":
        frame = put_chinese_text(frame, "訓練結束！", (w//2 - 90, h//2 - 120), color=(0, 255, 255), size=40)
        frame = put_chinese_text(frame, f"最終得分: {score} 分", (w//2 - 110, h//2 - 30), color=(255, 255, 255), size=32)
        
        if score >= 180:
            final_msg = "太神啦！盲打大師就是你！"
            msg_color = (0, 255, 0)
        elif score >= 100:
            final_msg = "表現不錯，指法很穩，繼續保持！"
            msg_color = (255, 255, 0)
        else:
            final_msg = "指法有點亂喔，需要多加練習！"
            msg_color = (255, 100, 100)
            
        frame = put_chinese_text(frame, final_msg, (w//2 - 180, h//2 + 40), color=msg_color, size=24)
        frame = put_chinese_text(frame, "【 按 空 白 鍵 重 新 開 始 】", (w//2 - 150, h//2 + 100), color=(200, 200, 200), size=20)
  
    cv2.imshow('Smart Touch-Typing Trainer', frame)
    
    if key == 27: break

cap.release()
cv2.destroyAllWindows()
