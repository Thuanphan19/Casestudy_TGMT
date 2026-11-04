import cv2
import numpy as np
from datetime import datetime
from pathlib import Path
import uuid

class ROICounter:
    def __init__(self, polygon):
        self.polygon = np.array(polygon, np.int32)
        self.count_in = 0
        self.count_out = 0
        self.detected_ids = set()
        self.objects_in_zone = set()

    def is_inside(self, bbox):
        x1, y1, x2, y2 = bbox
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        return cv2.pointPolygonTest(self.polygon, (cx, cy), False) >= 0

    def update(self, detections):
        entered_ids = []
        for det in detections:
            track_id = det["id"]
            if track_id is None:
                continue
            self.detected_ids.add(track_id)
            inside = self.is_inside(det["bbox"])

            if inside and track_id not in self.objects_in_zone:
                self.count_in += 1
                self.objects_in_zone.add(track_id)
                entered_ids.append(track_id)
            elif not inside and track_id in self.objects_in_zone:
                self.count_out += 1
                self.objects_in_zone.discard(track_id)

        return {
            "count_in": self.count_in,
            "count_out": self.count_out,
            "entered_ids": entered_ids,
        }

    def capture_entries(self, frame, detections, entered_ids, capture_root, analysis_id):
        people_by_id = {
            person["id"]: person
            for person in detections
            if person["id"] is not None
        }
        capture_dir = Path(capture_root) / analysis_id
        captured_people = []

        for person_id in entered_ids:
            person = people_by_id.get(person_id)
            if person is None:
                continue
            x1, y1, x2, y2 = person["bbox"]
            height, width = frame.shape[:2]
            crop = frame[max(0, y1):min(height, y2), max(0, x1):min(width, x2)]
            if crop.size == 0:
                continue

            capture_dir.mkdir(parents=True, exist_ok=True)
            image_name = f"person_{uuid.uuid4().hex}.jpg"
            image_path = capture_dir / image_name
            if not cv2.imwrite(str(image_path), crop):
                raise OSError(f"Could not save captured person image: {image_path}")
            captured_people.append({
                "id": person_id,
                "time": datetime.now().strftime("%H:%M:%S"),
                "image_url": f"/captures/{analysis_id}/{image_name}",
            })

        return captured_people

    def render_frame(self, frame, detections):
        cv2.polylines(frame, [self.polygon], True, (0, 200, 90), 3)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [self.polygon], (0, 200, 90))
        frame = cv2.addWeighted(overlay, 0.13, frame, 0.87, 0)

        for person in detections:
            x1, y1, x2, y2 = person["bbox"]
            color = (0, 190, 90) if self.is_inside(person["bbox"]) else (255, 130, 30)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            if person["id"] is not None:
                cv2.putText(
                    frame,
                    f"ID {person['id']}",
                    (x1, max(17, y1 - 7)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )

        return frame