from pathlib import Path
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory, Response
from werkzeug.utils import secure_filename
import cv2
import hashlib
import numpy as np
import uuid
import threading
import time

from detector import PeopleDetector
from counter import ROICounter
from database import init_db, save_history, get_history, count_history

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

def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.digest()

@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.get("/api/default-video")
def default_video():
    return jsonify({"filename": DEFAULT_VIDEO, "url": f"/videos/{DEFAULT_VIDEO}"})

@app.get("/api/videos")
def list_videos():
    videos = [
        {"filename": path.name, "url": f"/videos/{path.name}"}
        for path in sorted(VIDEO_DIR.iterdir(), key=lambda item: item.name.lower())
        if path.is_file() and allowed_video(path.name)
    ]
    return jsonify({"videos": videos})

@app.post("/api/upload")
def upload_video():
    file = request.files.get("video")
    if not file or not file.filename:
        return jsonify({"error": "Bạn chưa chọn video."}), 400
    if not allowed_video(file.filename):
        return jsonify({"error": "Định dạng video không được hỗ trợ."}), 400
    safe_name = secure_filename(file.filename)
    temporary_path = VIDEO_DIR / f".upload-{uuid.uuid4().hex}.tmp"
    try:
        file.save(temporary_path)
        uploaded_size = temporary_path.stat().st_size
        uploaded_hash = file_sha256(temporary_path)
        for existing_path in VIDEO_DIR.iterdir():
            if not existing_path.is_file() or not allowed_video(existing_path.name):
                continue
            if existing_path.stat().st_size != uploaded_size:
                continue
            if file_sha256(existing_path) == uploaded_hash:
                return jsonify({
                    "filename": existing_path.name,
                    "url": f"/videos/{existing_path.name}",
                    "duplicate": True,
                })

        unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
        final_path = VIDEO_DIR / unique_name
        temporary_path.replace(final_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return jsonify({"filename": unique_name, "url": f"/videos/{unique_name}", "duplicate": False})

def generate_frames(filename):
    global cap, detector_instance, counter_instance, current_polygon, video_stats, is_running, is_paused

    source_path = VIDEO_DIR / filename
    capture = cv2.VideoCapture(str(source_path))
    if not capture.isOpened():
        app.logger.error("Could not open video for analysis: %s", filename)
        return

    fps = capture.get(cv2.CAP_PROP_FPS)
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    duration_seconds = frame_count / fps if fps > 0 and frame_count > 0 else 0

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
            "position_seconds": 0,
            "duration_seconds": duration_seconds,
            "entered_people": [],
            "running": True,
            "paused": False,
            "completed": False,
            "finalized": False,
            "save_error": None,
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
    stream_started_at = time.monotonic()
    paused_started_at = None
    paused_duration = 0.0
    try:
        while capture.isOpened():
            with lock:
                running = is_running
                paused = is_paused
            if not running:
                break
            if paused:
                if paused_started_at is None:
                    paused_started_at = time.monotonic()
                time.sleep(0.1)
                continue
            if paused_started_at is not None:
                paused_duration += time.monotonic() - paused_started_at
                paused_started_at = None

            ok, frame = capture.read()
            if not ok:
                completed = True
                break

            detections = detector_instance.detect(frame)
            stats = counter_instance.update(detections)
            position_seconds = capture.get(cv2.CAP_PROP_POS_FRAMES) / fps if fps > 0 else 0
            if duration_seconds:
                position_seconds = min(position_seconds, duration_seconds)
            captured_people = counter_instance.capture_entries(
                frame,
                detections,
                stats["entered_ids"],
                CAPTURES_DIR,
                current_analysis["id"],
            )
            current_analysis["captured_people"].extend(captured_people)

            with lock:
                video_stats.update({
                    "count_in": stats["count_in"],
                    "count_out": stats["count_out"],
                    "total_people": len(counter_instance.detected_ids),
                    "position_seconds": position_seconds,
                    "duration_seconds": duration_seconds,
                    "entered_people": list(current_analysis["captured_people"]),
                    "running": True,
                    "paused": is_paused,
                })

            frame = counter_instance.render_frame(frame, detections)
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                if fps > 0:
                    frame_deadline = stream_started_at + paused_duration + position_seconds
                    remaining_time = frame_deadline - time.monotonic()
                    if remaining_time > 0:
                        time.sleep(remaining_time)
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
    finally:
        capture.release()
        if current_analysis and (completed or current_analysis.get("save_on_stop")) and not current_analysis["saved"]:
            stats = {
                "count_in": counter_instance.count_in,
                "count_out": counter_instance.count_out,
                "total_people": len(counter_instance.detected_ids),
                "entered_people": current_analysis["captured_people"],
            }
            try:
                save_history(
                    filename,
                    current_analysis["id"],
                    stats,
                    time.monotonic() - current_analysis["started_at"],
                )
                current_analysis["saved"] = True
            except Exception as error:
                current_analysis["save_error"] = str(error)
                app.logger.exception("Could not save analysis history for %s", filename)
        with lock:
            is_running = False
            is_paused = False
            video_stats.update({
                "running": False,
                "paused": False,
                "completed": completed,
                "finalized": bool(current_analysis and current_analysis["saved"]),
                "save_error": current_analysis.get("save_error") if current_analysis else None,
                "position_seconds": duration_seconds if completed and duration_seconds else video_stats.get("position_seconds", 0),
                "duration_seconds": duration_seconds,
            })
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
    data = request.get_json(silent=True) or {}
    save_result = data.get("save", False)
    with lock:
        if save_result and analysis:
            analysis["save_on_stop"] = True
        is_running = False
        is_paused = False
        video_stats.update({"running": False, "paused": False})
    if not stream_done.wait(timeout=30):
        return jsonify({"status": "stopping", "saved": False}), 202
    with lock:
        saved = bool(analysis and analysis["saved"])
        save_error = analysis.get("save_error") if analysis else None
        result_stats = {
            "count_in": video_stats.get("count_in", 0),
            "count_out": video_stats.get("count_out", 0),
            "total_people": video_stats.get("total_people", 0),
            "position_seconds": video_stats.get("position_seconds", 0),
            "duration_seconds": video_stats.get("duration_seconds", 0),
        }
    if save_error:
        return jsonify({"error": f"Không lưu được lịch sử phân tích: {save_error}", "stats": result_stats}), 500
    return jsonify({"status": "stopped", "saved": saved, "stats": result_stats})

@app.get("/api/history")
def history():
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    page = request.args.get("page", 1, type=int)
    try:
        if start_date:
            datetime.strptime(start_date, "%Y-%m-%d")
        if end_date:
            datetime.strptime(end_date, "%Y-%m-%d")
        if start_date and end_date and start_date > end_date:
            return jsonify({"error": "Ngày bắt đầu phải trước hoặc bằng ngày kết thúc."}), 400
    except ValueError:
        return jsonify({"error": "Ngày lọc không hợp lệ."}), 400
    if page < 1:
        return jsonify({"error": "Trang phải lớn hơn hoặc bằng 1."}), 400
    page_size = 8
    total = count_history(start_date or None, end_date or None)
    entries = get_history(
        start_date or None,
        end_date or None,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return jsonify({
        "history": entries,
        "total": total,
        "page": page,
        "per_page": page_size,
    })

@app.get("/captures/<path:filename>")
def serve_capture(filename):
    return send_from_directory(CAPTURES_DIR, filename)

@app.get("/videos/<path:filename>")
def serve_video(filename): return send_from_directory(VIDEO_DIR, filename)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, threaded=True)