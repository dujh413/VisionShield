"""同权重YuNet的CPU推理适配；输出格式与OpenCV FaceDetectorYN一致。"""
import hashlib

import cv2
import numpy as np

MODEL_NAME = 'face_detection_yunet_2026may.onnx'
MODEL_SHA256 = 'ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0'
MODEL_URL = ('https://media.githubusercontent.com/media/opencv/opencv_zoo/'
             '26cc381e4d2594bb9f47a26eb8fd96c94a13660d/models/face_detection_yunet/' + MODEL_NAME)


class OnnxYuNet:
    backend = 'onnxruntime-cpu'

    def __init__(self, model):
        data = model.read_bytes()
        if hashlib.sha256(data).hexdigest() != MODEL_SHA256:
            raise ValueError('YuNet model checksum mismatch')
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        options.enable_cpu_mem_arena = False
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.add_session_config_entry('session.intra_op.allow_spinning','0')
        self.session = ort.InferenceSession(data, options, providers=['CPUExecutionProvider'])
        self.names = [prefix+'_'+str(stride) for prefix in ('cls','obj','bbox','kps') for stride in (8,16,32)]
        inputs = self.session.get_inputs()
        if len(inputs) != 1 or inputs[0].shape != [1,3,'height','width']:
            raise ValueError('Unexpected YuNet input')
        if {item.name for item in self.session.get_outputs()} != set(self.names):
            raise ValueError('Unexpected YuNet outputs')
        self.input_name = inputs[0].name
        self.size = (640,480)

    def setInputSize(self, size):
        self.size = tuple(size)

    def detect(self, image):
        if image is None or not image.size:
            return 0,None
        height,width = image.shape[:2]
        if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8 or (width,height) != self.size:
            raise ValueError('Invalid YuNet image or size')
        padded = cv2.copyMakeBorder(image,0,(-height)%32,0,(-width)%32,cv2.BORDER_CONSTANT,value=0)
        values = self.session.run(self.names,{self.input_name:cv2.dnn.blobFromImage(padded)})
        if any(not np.isfinite(value).all() for value in values):
            raise ValueError('Invalid YuNet predictions')
        rows = []
        # 与OpenCV 4.10 face_detect.cpp一致：BGR原值、三层stride、
        # sqrt(cls*obj)、五点顺序及整数框NMS；不降低检测或身份门限。
        for index,stride in enumerate((8,16,32)):
            cols = padded.shape[1]//stride
            scores = np.sqrt(np.clip(values[index].reshape(-1),0,1)*np.clip(values[index+3].reshape(-1),0,1))
            selected = np.flatnonzero(scores >= .6)
            if not len(selected):
                continue
            bbox = values[index+6].reshape(-1,4)[selected]
            points = values[index+9].reshape(-1,5,2)[selected]
            grid = np.column_stack((selected%cols,selected//cols)).astype(np.float32)
            center = (grid+bbox[:,:2])*stride
            size = np.exp(bbox[:,2:])*stride
            decoded = np.empty((len(selected),15),np.float32)
            decoded[:,:2] = center-size/2
            decoded[:,2:4] = size
            decoded[:,4:14] = ((points+grid[:,None,:])*stride).reshape(-1,10)
            decoded[:,14] = scores[selected]
            if not np.isfinite(decoded).all():
                raise ValueError('Invalid YuNet predictions')
            rows.append(decoded)
        if not rows:
            return 1,None
        faces = np.concatenate(rows)
        if len(faces)>1:
            indices = cv2.dnn.NMSBoxes(faces[:,:4].astype(np.int32).tolist(),faces[:,14].tolist(),
                                       .6,.45,eta=1.,top_k=5000)
            faces = faces[np.asarray(indices,dtype=int).reshape(-1)]
        return 1,faces if len(faces) else None
