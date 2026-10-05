"""区域视觉描述子只在内存传递，不保存截图或原文。"""
import base64
import math


def valid_features(value):
    if not isinstance(value,dict):return None
    points=value.get('points');size=value.get('size');data=value.get('descriptors')
    if (not isinstance(points,list) or not 6<=len(points)<=96 or
        not isinstance(size,list) or len(size)!=2 or
        not all(type(v) in (int,float) and math.isfinite(v) and 20<=v<=32768 for v in size) or
        not isinstance(data,str) or len(data)>4096):return None
    if any(not isinstance(p,list) or len(p)!=2 or not all(type(v) in (int,float) and math.isfinite(v) and 0<=v<=1 for v in p) for p in points):return None
    try: decoded=base64.b64decode(data,validate=True)
    except (ValueError,TypeError):return None
    if len(decoded)!=len(points)*32:return None
    return {'points':points,'size':size,'descriptors':data}


def extract_features(image,rect):
    import cv2
    x,y,width,height=map(int,rect)
    if min(width,height)<20 or x<0 or y<0 or x+width>image.shape[1] or y+height>image.shape[0]:return None
    gray=cv2.cvtColor(image[y:y+height,x:x+width],cv2.COLOR_BGR2GRAY)
    scale=min(1,640/max(width,height))
    gray=cv2.resize(gray,None,fx=scale,fy=scale)
    # 小边界阈值允许小控件；描述子仍需多点几何一致性才能通过。
    points,descriptors=cv2.ORB_create(nfeatures=96,edgeThreshold=8,patchSize=21,fastThreshold=12).detectAndCompute(gray,None)
    if descriptors is None or len(points)<6:return None
    # OpenCV在响应分数并列时可能返回多于nfeatures的点。
    points,descriptors=points[:96],descriptors[:96]
    return {'points':[[round(p.pt[0]/gray.shape[1],6),round(p.pt[1]/gray.shape[0],6)] for p in points],
            'size':[width,height],'descriptors':base64.b64encode(descriptors.tobytes()).decode('ascii')}


def locate_features(image,client,features):
    """在所属窗口客户区内重定位，拒绝少匹配、重复图案和非刚性漂移。"""
    import cv2
    import numpy as np
    features=valid_features(features)
    if not features:return None
    x,y,width,height=map(int,client)
    if x<0 or y<0 or x+width>image.shape[1] or y+height>image.shape[0] or min(width,height)<20:return None
    gray=cv2.cvtColor(image[y:y+height,x:x+width],cv2.COLOR_BGR2GRAY)
    scale=min(1,960/max(width,height));gray=cv2.resize(gray,None,fx=scale,fy=scale)
    points,descriptors=cv2.ORB_create(nfeatures=1200,edgeThreshold=8,patchSize=21,fastThreshold=12).detectAndCompute(gray,None)
    if descriptors is None or len(points)<6:return None
    reference=np.frombuffer(base64.b64decode(features['descriptors']),dtype=np.uint8).reshape(-1,32)
    result=_fit(reference,features,points,descriptors,scale)
    if result is None:return None
    left,top,right,bottom=result
    outside=[i for i,p in enumerate(points) if not left<=p.pt[0]/scale<=right or not top<=p.pt[1]/scale<=bottom]
    if len(outside)>=6 and _fit(reference,features,[points[i] for i in outside],descriptors[outside],scale) is not None:
        return None
    if left<-3 or top<-3 or right>width+3 or bottom>height+3:return None
    return (x+max(0,float(left)),y+max(0,float(top)),min(width,float(right))-max(0,float(left)),min(height,float(bottom))-max(0,float(top)))


def _fit(reference,features,points,descriptors,scale):
    import cv2
    import numpy as np
    pairs=cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(reference,descriptors,k=2)
    matches=[p[0] for p in pairs if len(p)==2 and p[0].distance<.70*p[1].distance and p[0].distance<=55]
    if len(matches)<6 or len({m.trainIdx for m in matches})<6:return None
    fw,fh=features['size'];source=np.float32([[features['points'][m.queryIdx][0]*fw,features['points'][m.queryIdx][1]*fh] for m in matches])
    target=np.float32([[points[m.trainIdx].pt[0]/scale,points[m.trainIdx].pt[1]/scale] for m in matches])
    transform,inliers=cv2.estimateAffinePartial2D(source,target,method=cv2.RANSAC,ransacReprojThreshold=3,maxIters=1500)
    if transform is None or inliers is None or inliers.sum()<6 or inliers.mean()<.65:return None
    selected=source[inliers.reshape(-1).astype(bool)]
    spread=selected.max(axis=0)-selected.min(axis=0)
    if spread[0]<fw*.20 or spread[1]<fh*.20:return None
    # 禁止旋转/倾斜；桌面窗口布局缩放和平移才是有效变化。
    zoom=float(math.hypot(transform[0,0],transform[1,0]))
    if not .4<=zoom<=2.5 or abs(transform[1,0])>zoom*.08:return None
    corners=np.float32([[0,0],[fw,0],[fw,fh],[0,fh]])@transform[:,:2].T+transform[:,2]
    left,top=corners.min(axis=0);right,bottom=corners.max(axis=0)
    return (float(left),float(top),float(right),float(bottom))
