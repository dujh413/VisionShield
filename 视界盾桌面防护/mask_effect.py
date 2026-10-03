"""Start-button settings and a separable box mean filter, without GUI dependencies."""
from dataclasses import dataclass
import unicodedata
import numpy as np


@dataclass(frozen=True)
class MaskEffect:
    mode: str
    radius: int = 0

    @property
    def description(self):
        return {'off': '不处理敏感内容', 'block': '深色矩形遮挡',
                'blur': f'盒式模糊，半径 {self.radius} 物理像素'}[self.mode]


def parse_effect(text):
    text = unicodedata.normalize('NFKC', text).strip()
    if not text:
        return MaskEffect('off')
    if text.isdecimal():
        return MaskEffect('blur', int(text))
    return MaskEffect('block')


def _mean_axis(image, radius, axis):
    data = np.moveaxis(image, axis, 0).astype(np.float64)
    size = len(data)
    prefix = np.concatenate((np.zeros_like(data[:1]), np.cumsum(data, axis=0)), axis=0)
    positions = np.arange(size)
    bounded_radius = min(radius, size)
    lo = np.maximum(0, positions - bounded_radius)
    hi = np.minimum(size, positions + bounded_radius + 1)
    denominator = 2 * radius + 1
    # Python integer division also supports radii larger than NumPy integer types.
    inverse = 1 / denominator
    left = np.array([max(0, radius - int(i)) / denominator for i in positions])
    right = np.array([max(0, int(i) + radius - size + 1) / denominator for i in positions])
    shape = (size,) + (1,) * (data.ndim - 1)
    averaged = ((prefix[hi] - prefix[lo]) * inverse
                + left.reshape(shape) * data[0] + right.reshape(shape) * data[-1])
    return np.moveaxis(averaged, 0, axis)


def box_blur(image, radius):
    """Uniform (2r+1)^2 filter with replicated edges; input stays unchanged."""
    if type(radius) is not int or radius < 0:
        raise ValueError('Box radius must be a non-negative integer')
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
        raise ValueError('Expected a uint8 BGR image')
    if not image.size or radius == 0:
        return image.copy()
    averaged = _mean_axis(_mean_axis(image, radius, 1), radius, 0)
    return np.clip(np.rint(averaged), 0, 255).astype(np.uint8)
