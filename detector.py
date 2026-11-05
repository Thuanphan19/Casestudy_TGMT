from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import numpy as np
from numpy.typing import NDArray
from ultralytics import YOLO
from ultralytics.engine.results import Boxes

if TYPE_CHECKING:
    from counter import ROICounter


class Detection(TypedDict):
    id: int
    bbox: list[int]
    confidence: float


class CounterStats(TypedDict):
    count_in: int
    count_out: int
    entered_ids: list[int]


class CapturedPerson(TypedDict):
    id: int
    time: str
    image_url: str


class PeopleDetector:
    PERSON_CLASS = 0
    CONFIDENCE_THRESHOLD = 0.2
    INFERENCE_SIZE = 320

    def __init__(self, model_path: str | Path):
        self.model = YOLO(str(model_path))

    def warmup(self) -> None:
        frame = np.zeros((self.INFERENCE_SIZE, self.INFERENCE_SIZE, 3), dtype=np.uint8)
        self.model.predict(
            frame,
            classes=[self.PERSON_CLASS],
            conf=self.CONFIDENCE_THRESHOLD,
            verbose=False,
            imgsz=self.INFERENCE_SIZE,
        )

    def detect(self, frame: NDArray[np.uint8]) -> list[Detection]:
        results = self.model.track(
            frame,
            persist=True,
            classes=[self.PERSON_CLASS],
            conf=self.CONFIDENCE_THRESHOLD,
            verbose=False,
            imgsz=self.INFERENCE_SIZE,
        )
        if not results:
            return []
        return self._parse_boxes(results[0].boxes)

    @staticmethod
    def _parse_boxes(boxes: Boxes | None) -> list[Detection]:
        detections = []
        if boxes is None:
            return detections

        for box in boxes:
            detection = PeopleDetector._parse_box(box)
            if detection is not None:
                detections.append(detection)
        return detections

    @staticmethod
    def _parse_box(box: Boxes) -> Detection | None:
        if box.id is None:
            return None

        x1, y1, x2, y2 = box.xyxy[0].tolist()
        return {
            "id": int(box.id[0]),
            "bbox": [int(x1), int(y1), int(x2), int(y2)],
            "confidence": float(box.conf[0]),
        }

    def process_frame(
        self,
        frame: NDArray[np.uint8],
        counter: "ROICounter",
        capture_root: Path,
        analysis_id: str,
    ) -> tuple[
        NDArray[np.uint8],
        list[Detection],
        CounterStats,
        list[CapturedPerson],
    ]:
        detections = self.detect(frame)
        stats = counter.update(detections)
        captured_people = counter.capture_entries(
            frame,
            detections,
            stats["entered_ids"],
            capture_root,
            analysis_id,
        )
        rendered_frame = counter.render_frame(frame, detections)
        return rendered_frame, detections, stats, captured_people
