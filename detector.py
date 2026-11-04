from ultralytics import YOLO

class PeopleDetector:
    def __init__(self, model_path):
        self.model = YOLO(model_path)

    def detect(self, frame):
        results = self.model.track(frame, persist=True, classes=[0], conf=0.2, verbose=False)
        detections = []
        if results[0].boxes:
            for box in results[0].boxes:
                if box.id is None:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append({
                    "id": int(box.id[0]),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "confidence": float(box.conf[0])
                })
        return detections