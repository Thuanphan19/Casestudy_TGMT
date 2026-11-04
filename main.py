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
CAPTURES_DIR = BASE_DIR / "outputs" / "captures"
MODEL_PATH = BASE_DIR / "yolo26s.pt"
DEFAULT_VIDEO = "videoplayback.mp4"
ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024
VIDEO_DIR.mkdir(exist_ok=True)
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
init_db()

# Các biến toàn cục quản lý luồng streaming
detector_instance = None
counter_instance = None
cap = None
current_polygon = []
video_stats = {"count_in": 0, "count_out": 0, "total_people": 0}
is_running = False
is_paused = False
analysis = None
lock = threading.Lock()
stream_done = threading.Event()
stream_done.set()

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
    if not allowed_video(file.filename):
        return jsonify({"error": "Định dạng video không được hỗ trợ."}), 400
    safe_name = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    file.save(VIDEO_DIR / unique_name)
    return jsonify({"filename": unique_name, "url": f"/videos/{unique_name}"})

def generate_frames(filename):
    global cap, detector_instance, counter_instance, current_polygon, video_stats, is_running, is_paused

    source_path = VIDEO_DIR / filename
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        app.logger.error("Could not open video for analysis: %s", filename)
        return

    if not detector_instance:
        detector_instance = PeopleDetector(str(MODEL_PATH))

    counter_instance = ROICounter(current_polygon)
    with lock:
        cap = capture
        is_running = True
        is_paused = False
        video_stats = {
            "count_in": 0,
            "count_out": 0,
            "total_people": 0,
            "entered_people": [],
            "running": True,
            "paused": False,
            "completed": False,
        }
        current_analysis = analysis
        stream_done.clear()

    if current_analysis is None:
        capture.release()
        with lock:
            is_running = False
            cap = None
        stream_done.set()
        app.logger.error("Video stream requested without an active analysis.")
        return

    completed = False
    try:
        while capture.isOpened():
            with lock:
                running = is_running
                paused = is_paused
            if not running:
                break
            if paused:
                time.sleep(0.1)
                continue

            ok, frame = capture.read()
            if not ok:
                completed = True
                break

            detections = detector_instance.detect(frame)
            stats = counter_instance.update(detections)
            for person_id in stats["entered_ids"]:
                person = next((item for item in detections if item["id"] == person_id), None)
                if person is None:
                    continue
                x1, y1, x2, y2 = person["bbox"]
                height, width = frame.shape[:2]
                x1, x2 = max(0, x1), min(width, x2)
                y1, y2 = max(0, y1), min(height, y2)
                crop = frame[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                image_name = f"person_{uuid.uuid4().hex}.jpg"
                capture_dir = CAPTURES_DIR / current_analysis["id"]
                capture_dir.mkdir(parents=True, exist_ok=True)
                if not cv2.imwrite(str(capture_dir / image_name), crop):
                    raise OSError(f"Could not save captured person image: {capture_dir / image_name}")
                current_analysis["captured_people"].append({
                    "id": person_id,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "image_url": f"/captures/{current_analysis['id']}/{image_name}",
                })

            with lock:
                video_stats.update({
                    "count_in": stats["count_in"],
                    "count_out": stats["count_out"],
                    "total_people": len(counter_instance.detected_ids),
                    "entered_people": list(current_analysis["captured_people"]),
                    "running": True,
                    "paused": is_paused,
                })

            cv2.polylines(frame, [counter_instance.polygon], True, (0, 200, 90), 3)
            overlay = frame.copy()
            cv2.fillPoly(overlay, [counter_instance.polygon], (0, 200, 90))
            frame = cv2.addWeighted(overlay, 0.13, frame, 0.87, 0)

            for person in detections:
                x1, y1, x2, y2 = person["bbox"]
                color = (0, 190, 90) if counter_instance.is_inside(person["bbox"]) else (255, 130, 30)
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                cv2.putText(frame, f"ID {person['id']}", (x1, max(17, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            cv2.putText(frame, f"IN: {stats['count_in']} | OUT: {stats['count_out']}", (24, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (40, 230, 130), 2)
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
    finally:
        capture.release()
        if completed and current_analysis and not current_analysis["saved"]:
            stats = {
                "count_in": counter_instance.count_in,
                "count_out": counter_instance.count_out,
                "total_people": len(counter_instance.detected_ids),
                "entered_people": current_analysis["captured_people"],
            }
            save_history(
                filename,
                current_analysis["id"],
                stats,
                time.monotonic() - current_analysis["started_at"],
            )
            current_analysis["saved"] = True
        with lock:
            is_running = False
            is_paused = False
            video_stats.update({"running": False, "paused": False, "completed": completed})
            if cap is capture:
                cap = None
        stream_done.set()

@app.post("/api/process")
def process_video():
    global current_polygon, is_running, is_paused, analysis
    data = request.get_json(silent=True) or {}
    filename = secure_filename(data.get("filename", ""))
    roi_points = data.get("roi") or data.get("points")
    
    if not filename or not allowed_video(filename) or not roi_points or len(roi_points) < 3:
        return jsonify({"error": "Dữ liệu không hợp lệ."}), 400

    source_path = VIDEO_DIR / filename
    if not source_path.is_file():
        return jsonify({"error": "Không tìm thấy video."}), 404
    temp_cap = cv2.VideoCapture(str(source_path))
    if not temp_cap.isOpened():
        temp_cap.release()
        return jsonify({"error": "Không thể mở video."}), 400
    width = int(temp_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(temp_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    temp_cap.release()
    if width <= 0 or height <= 0:
        return jsonify({"error": "Kích thước video không hợp lệ."}), 400

    current_polygon = np.array([[int(x * width), int(y * height)] for x, y in roi_points], dtype=np.int32)
    with lock:
        is_running = False
        is_paused = False
    if not stream_done.wait(timeout=5):
        return jsonify({"error": "Video trước đó chưa dừng."}), 409
    analysis = {
        "id": uuid.uuid4().hex,
        "filename": filename,
        "started_at": time.monotonic(),
        "captured_people": [],
        "saved": False,
    }

    return jsonify({
        "status": "ok",
        "message": "Bắt đầu stream",
        "filename": filename,
        "analysis_id": analysis["id"],
    })

@app.get("/video_feed/<filename>")
def video_feed(filename):
    with lock:
        if analysis is None:
            return jsonify({"error": "Hãy bắt đầu phân tích trước."}), 409
    return Response(generate_frames(secure_filename(filename)), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.get("/api/stats")
def get_stats():
    with lock:
        return jsonify(video_stats)

@app.post("/api/pause")
def pause_video():
    global is_paused
    with lock:
        if not is_running:
            return jsonify({"error": "Không có video đang chạy."}), 409
        is_paused = True
        video_stats["paused"] = True
    return jsonify({"paused": True})

@app.post("/api/resume")
def resume_video():
    global is_paused
    with lock:
        if not is_running:
            return jsonify({"error": "Không có video đang chạy."}), 409
        is_paused = False
        video_stats["paused"] = False
    return jsonify({"paused": False})

@app.post("/api/stop")
def stop_video():
    global is_running, is_paused
    with lock:
        is_running = False
        is_paused = False
        video_stats.update({"running": False, "paused": False})
    return jsonify({"status": "stopped"})

@app.get("/api/history")
def history():
    return jsonify({"history": get_history()})

@app.get("/captures/<path:filename>")
def serve_capture(filename):
    return send_from_directory(CAPTURES_DIR, filename)

@app.get("/videos/<path:filename>")
def serve_video(filename): return send_from_directory(VIDEO_DIR, filename)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)