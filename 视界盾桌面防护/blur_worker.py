"""Latest-only box filtering off the Qt thread. Images remain in memory."""
import math
import queue
import threading
import time
from mask_effect import box_blur
from region_geometry import merge_boxes


def crop_boxes(image, rectangles, margin=6):
    height, width = image.shape[:2]
    boxes = []
    for x, y, w, h in rectangles:
        box = (max(0, math.floor(x) - margin), max(0, math.floor(y) - margin),
               min(width, math.ceil(x + w) + margin), min(height, math.ceil(y + h) + margin))
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    return merge_boxes(boxes)


def render_blur(image, boxes, radius):
    return [(box, box_blur(image[box[1]:box[3], box[0]:box[2]], radius)) for box in boxes]


class BlurWorker:
    def __init__(self):
        self.inputs, self.outputs = queue.Queue(1), queue.Queue(1)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='box-blur')
        self.thread.start()

    @staticmethod
    def _latest(channel, item):
        try:
            channel.get_nowait()
        except queue.Empty:
            pass
        try:
            channel.put_nowait(item)
        except queue.Full:
            pass

    def submit(self, image, boxes, radius):
        self._latest(self.inputs, (image, boxes, radius))

    def run(self):
        while not self.stop.is_set():
            try:
                image, boxes, radius = self.inputs.get(timeout=.1)
            except queue.Empty:
                continue
            started = time.monotonic()
            try:
                result = {'image': image, 'boxes': boxes, 'radius': radius,
                          'patches': render_blur(image, boxes, radius)}
                result['blur_ms'] = (time.monotonic() - started) * 1000
            except Exception as error:
                result = {'error': type(error).__name__}
            if not self.stop.is_set():
                self._latest(self.outputs, result)

    def poll(self):
        try:
            return self.outputs.get_nowait()
        except queue.Empty:
            return None

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        for channel in (self.inputs, self.outputs):
            try:
                channel.get_nowait()
            except queue.Empty:
                pass
