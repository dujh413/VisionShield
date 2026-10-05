"""虚构屏幕的区域校验回归与可重复基准；不代表 OCR 或实机端到端延迟。"""
import statistics
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np
from content_index import ContentIndex


def synthetic_screen():
    image = np.zeros((1600,2560,3),dtype=np.uint8)
    lines = [{'text':'13800138000','confidence':.99,
              'polygon':[[x,y],[x+900,y],[x+900,y+18],[x,y+18]]}
             for x in (50,1300) for y in range(20,1560,22)]
    return image,lines


def benchmark(samples=10,warmups=2):
    image,lines = synthetic_screen()
    animation = image.copy()
    animation[1590,2550] = 255
    result = {}
    for scenario in ('identical','animation','same_object'):
        update_times,accept_times = [],[]
        for iteration in range(samples+warmups):
            index = ContentIndex()
            index.update(image)
            index.accept(image,lines,unknown_regions=[])
            target = image.copy() if scenario=='identical' else image if scenario=='same_object' else animation
            started = time.perf_counter()
            index.update(target)
            update_ms = (time.perf_counter()-started)*1000
            started = time.perf_counter()
            index.accept(image,lines,unknown_regions=[])
            accept_ms = (time.perf_counter()-started)*1000
            if iteration>=warmups:
                update_times.append(update_ms)
                accept_times.append(accept_ms)
        result[scenario] = {
            'lines':len(lines),'samples':samples,
            'update_median_ms':round(statistics.median(update_times),3),
            'update_p95_ms':round(float(np.percentile(update_times,95)),3),
            'accept_median_ms':round(statistics.median(accept_times),3),
            'accept_p95_ms':round(float(np.percentile(accept_times,95)),3),
        }
    return result


class ContentPerformanceTests(unittest.TestCase):
    def test_many_contexts_reuse_one_difference_without_source_roi_comparisons(self):
        image,lines = synthetic_screen()
        index = ContentIndex()
        index.update(image)
        index.accept(image,lines,unknown_regions=[])
        latest = image.copy()
        latest[1590,2550] = 255
        # 区域有效性仍严格精确，且不为每行重复比较 RGB 源图。
        with patch('content_index.np.array_equal',side_effect=AssertionError('repeated source comparison')):
            index.update(latest)
            self.assertTrue(index.accept(image,lines,unknown_regions=[]))
        self.assertEqual(len(index.hits),140)
        self.assertTrue(index.unknown[-1,-1])
        self.assertFalse(index.unknown[0,0])

    def test_changed_character_covers_entire_long_line_with_many_neighbors(self):
        image,lines = synthetic_screen()
        index = ContentIndex()
        index.update(image)
        index.accept(image,lines,unknown_regions=[])
        latest = image.copy()
        latest[25,55] = 255
        index.update(latest)
        index.accept(image,lines,unknown_regions=[])
        self.assertTrue(index.unknown[0,14])
        self.assertFalse(any(hit['polygon']==lines[0]['polygon'] for hit in index.hits))
        self.assertTrue(any(hit['polygon']==lines[-1]['polygon'] for hit in index.hits))


if __name__=='__main__':
    if '--benchmark' in sys.argv:
        import json
        print(json.dumps(benchmark(),ensure_ascii=False,indent=2))
    else:
        unittest.main()
