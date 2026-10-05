"""本地ONNX OCR适配器；保留原始坐标，不上传屏幕内容。"""
import onnxruntime as ort
import cv2
import numpy as np
import time
from runtime_paths import desktop_root
from gpu_adapter import preferred_adapter
from rapidocr_onnxruntime import RapidOCR


class FastOCR:
    def __init__(self, gpu=True, det_long=1536):
        # OpenCV并行与ORT线程竞争会放大延迟；图像预处理固定单线程。
        cv2.setNumThreads(1)
        use_dml=gpu and 'DmlExecutionProvider' in ort.get_available_providers()
        models=desktop_root()/'models/rapid_onnx'
        if not (models/'ch_PP-OCRv4_det_infer.onnx').exists():
            raise RuntimeError('缺少ONNX模型，请先运行prepare_fast_models.py')
        # GPU检测与固定形状批量识别；无DirectML时回退CPU。
        self.engine=RapidOCR(det_use_dml=False,rec_use_dml=False,
                             intra_op_num_threads=4,inter_op_num_threads=1,
                             det_limit_type='max',text_score=0.0,use_cls=False,
                             det_model_path=str(models/'ch_PP-OCRv4_det_infer.onnx'),
                             rec_model_path=str(models/'ch_PP-OCRv4_rec_infer.onnx'),
                             cls_model_path=str(models/'ch_ppocr_mobile_v2.0_cls_infer.onnx'),
                             max_side_len=4096)
        self.adapter=preferred_adapter() if use_dml else None
        if use_dml:
            options=ort.SessionOptions()
            options.enable_mem_pattern=False
            options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            options.intra_op_num_threads=4
            options.inter_op_num_threads=1
            options.graph_optimization_level=ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self.engine.text_det.infer.session=ort.InferenceSession(
                str(models/'ch_PP-OCRv4_det_infer.onnx'),sess_options=options,
                providers=[('DmlExecutionProvider',{'device_id':self.adapter['device_id'] if self.adapter else 0}),
                           'CPUExecutionProvider'])
            self.engine.text_rec.session.session=ort.InferenceSession(
                str(models/'ch_PP-OCRv4_rec_infer.onnx'),sess_options=options,
                providers=[('DmlExecutionProvider',{'device_id':self.adapter['device_id'] if self.adapter else 0}),
                           'CPUExecutionProvider'])
        self.use_dml=use_dml
        self.providers={'text_det':self.engine.text_det.infer.session.get_providers(),
                        'text_rec':self.engine.text_rec.session.session.get_providers()}
        self.buckets=((512,384),(1024,640),(det_long,round(det_long*.625/32)*32))
        # 在“就绪”之前预热固定检测尺寸；运行中不为每个裁剪框编译新尺寸。
        for width,height in self.buckets:
            self.engine.text_det(np.full((height,width,3),255,dtype=np.uint8))
        for width in (320,640,1280,2560):
            self.recognize_crops([np.full((48,width,3),255,dtype=np.uint8)])

    def recognize_crops(self,crops):
        if not self.use_dml:
            return self.engine.text_rec(crops)[0]
        recognizer=self.engine.text_rec
        # 按宽高比分组；固定批量和宽度，避免每条新长度触发GPU冷编译。
        order=sorted(range(len(crops)),key=lambda i:crops[i].shape[1]/crops[i].shape[0])
        results=[('',0.0)]*len(crops)
        for start in range(0,len(order),4):
            indices=order[start:start+4]
            width=max(320,max(int(np.ceil(48*crops[i].shape[1]/crops[i].shape[0])) for i in indices))
            bucket=next((w for w in (320,640,1280,2560) if w>=width),int(np.ceil(width/320))*320)
            batch=[recognizer.resize_norm_img(crops[i],bucket/48) for i in indices]
            batch.extend([batch[-1]]*(4-len(batch)))
            predictions=recognizer.session(np.stack(batch).astype(np.float32))[0]
            decoded=recognizer.postprocess_op(predictions)
            for i,value in zip(indices,decoded):
                results[i]=value
        return results

    def recognize(self,image,preserve_scale=False):
        started=time.perf_counter()
        self.last_timing = {'preprocess_ms': 0.0, 'detection_ms': 0.0, 'crop_ms': 0.0,
                            'recognition_ms': 0.0}
        height,width=image.shape[:2]
        bucket=next(((w,h) for w,h in self.buckets if width<=w and height<=h),self.buckets[-1])
        bw,bh=bucket
        scale=min(1.0,bw/width,bh/height)
        rw,rh=max(1,round(width*scale)),max(1,round(height*scale))
        canvas=np.empty((bh,bw,3),dtype=np.uint8)
        canvas[:]=image[0,0]
        canvas[:rh,:rw]=cv2.resize(image,(rw,rh)) if scale<1 else image
        preprocessed=time.perf_counter()
        boxes,_=self.engine.text_det(canvas)
        detected=time.perf_counter()
        self.last_timing['preprocess_ms']=(preprocessed-started)*1000
        self.last_timing['detection_ms']=(detected-preprocessed)*1000
        if boxes is None:
            return []
        mapped=[]
        for box in boxes:
            if float(box[:,0].mean())>=rw or float(box[:,1].mean())>=rh:
                continue
            box=box.astype(np.float32).copy()
            box[:,0]=np.clip(box[:,0]*width/rw,0,width-1)
            box[:,1]=np.clip(box[:,1]*height/rh,0,height-1)
            if np.ptp(box[:,0])>=4 and np.ptp(box[:,1])>=4:
                mapped.append(box)
        if not mapped:
            return []
        mapped=self.engine.sorted_boxes(np.asarray(mapped))
        # 识别裁剪取原始分辨率，检测缩放不降低识别输入文字的清晰度。
        crops=self.engine.get_crop_img_list(image,mapped)
        cropped=time.perf_counter()
        results=self.recognize_crops(crops)
        self.last_timing['crop_ms']=(cropped-detected)*1000
        self.last_timing['recognition_ms']=(time.perf_counter()-cropped)*1000
        return [{'text':str(text),'confidence':float(score),'polygon':box.tolist(),'source':'onnx_ocr'}
                for box,(text,score) in zip(mapped,results)]
