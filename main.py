from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory, Response
from werkzeug.utils import secure_filename
import cv2
import numpy as np
import uuid
import threading
import time

from detector import PeopleDetector
from counter import ROICounter
from database import init_db, save_history, get_history

BASE_DIR = Path(__file__).resolve().parent
VIDEO_DIR = BASE_DIR / "videos"
MODEL_PATH = BASE_DIR / "yolo26s.pt"
DEFAULT_VIDEO = "videoplayback.mp4"
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
VIDEO_DIR.mkdir(exist_ok=True)
init_db()

# Các biến toàn cục quản lý luồng streaming
detector_instance = None
counter_instance = None
cap = None
current_polygon = []
video_stats = {"count_in": 0, "count_out": 0, "total_people": 0}
is_running = False
lock = threading.Lock()

def allowed_video(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS

@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.get("/api/default-video")
def default_video():
    return jsonify({"filename": DEFAULT_VIDEO, "url": f"/videos/{DEFAULT_VIDEO}"})

@app.post("/api/upload")
def upload_video():
    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"error": "Bạn chưa chọn video."}), 400
    safe_name = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    file.save(VIDEO_DIR / unique_name)
    return jsonify({"filename": unique_name, "url": f"/videos/{unique_name}"})

def generate_frames(filename):
    global cap, detector_instance, counter_instance, current_polygon, video_stats, is_running
    
    source_path = VIDEO_DIR / filename
    cap = cv2.VideoCapture(str(source_path))
    
    if not detector_instance:
        detector_instance = PeopleDetector(str(MODEL_PATH))
    
    counter_instance = ROICounter(current_polygon)
    
    with lock:
        video_stats = {"count_in": 0, "count_out": 0, "total_people": 0}
        is_running = True

    while cap.isOpened() and is_running:
        ok, frame = cap.read()
        if not ok: break

        detections = detector_instance.detect(frame)
        stats = counter_instance.update(detections)
        
        with lock:
            video_stats["count_in"] = stats["count_in"]
            video_stats["count_out"] = stats["count_out"]
            video_stats["total_people"] = len(counter_instance.detected_ids)

        # Vẽ ROI
        cv2.polylines(frame, [counter_instance.polygon], True, (0, 200, 90), 3)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [counter_instance.polygon], (0, 200, 90))
        frame = cv2.addWeighted(overlay, 0.13, frame, 0.87, 0)

        # Vẽ người
        for person in detections:
            x1, y1, x2, y2 = person["bbox"]
            color = (0, 190, 90) if counter_instance.is_inside(person["bbox"]) else (255, 130, 30)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            cv2.putText(frame, f"ID {person['id']}", (x1, max(17, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

        cv2.putText(frame, f"IN: {stats['count_in']} | OUT: {stats['count_out']}", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 230, 130), 2)
        
        ret, buffer = cv2.imencode('.jpg', frame)
        if ret:
            yield (b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n")
            
    if cap: cap.release()
    with lock: is_running = False

@app.post("/api/process")
def process_video():
    global current_polygon, is_running
    data = request.get_json(silent=True) or {}
    filename = secure_filename(data.get("filename", ""))
    roi_points = data.get("roi") or data.get("points")
    
    if not filename or not roi_points or len(roi_points) < 3:
        return jsonify({"error": "Dữ liệu không hợp lệ."}), 400
        
    # Chuẩn hóa tọa độ dựa trên kích thước video tạm (ví dụ 1280x720)
    # Lấy kích thước thực:
    temp_cap = cv2.VideoCapture(str(VIDEO_DIR / filename))
    width = int(temp_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(temp_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    temp_cap.release()
    
    current_polygon = np.array([[int(x * width), int(y * height)] for x, y in roi_points], dtype=np.int32)
    
    # Reset luồng cũ nếu đang chạy
    with lock:
        is_running = False
    time.sleep(0.2) # Chờ luồng cũ thoát
    
    return jsonify({"status": "ok", "message": "Bắt đầu stream", "filename": filename})

@app.get("/video_feed/<filename>")
def video_feed(filename):
    return Response(generate_frames(secure_filename(filename)), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.get("/api/stats")
def get_stats():
    with lock:
        return jsonify(video_stats)

@app.get("/api/history")
def history():
    return jsonify({"history": get_history()})

@app.get("/videos/<path:filename>")
def serve_video(filename): return send_from_directory(VIDEO_DIR, filename)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)