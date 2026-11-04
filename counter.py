import cv2
import numpy as np

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