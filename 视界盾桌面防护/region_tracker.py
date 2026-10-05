"""窗口身份 + 控件结构 + 视觉特征；失败时不复用屏幕固定坐标。"""
import time
import hashlib
from region_features import locate_features


def client_signature(image, client):
    """Exact client-relative pixel digest; no pixels leave the caller's memory."""
    import numpy as np
    if (not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3
            or image.dtype!=np.uint8 or len(client)!=4):return None
    if any(type(value) is not int for value in client):return None
    x,y,width,height=client
    if x<0 or y<0 or width<=0 or height<=0 or x+width>image.shape[1] or y+height>image.shape[0]:return None
    pixels=np.ascontiguousarray(image[y:y+height,x:x+width])
    return hashlib.sha256(pixels.data).hexdigest()


class RegionTracker:
    def __init__(self):
        self.worker=None;self.results={};self.sequence=0;self.last_submit=0
        self.visual_cache={};self.binding={};self.profile_tokens={}
        self.last_image=None;self.image_sequence=0

    def close(self):
        if self.worker:self.worker.close();self.worker=None
        self.results.clear();self.visual_cache.clear();self.binding.clear()
        self.last_image=None

    def resolve(self,profiles,windows,image,origin=(0,0),now=None):
        now=time.monotonic() if now is None else now
        if image is not self.last_image:
            self.image_sequence+=1;self.last_image=image
        active={key for key,profile in profiles.items() if profile['mode']=='tracked'}
        for cache in (self.results,self.visual_cache,self.binding,self.profile_tokens):
            for key in list(cache):
                if key not in active:cache.pop(key,None)
        resolved={};tasks={};clients={};signatures={}
        if self.worker:
            for item in self.worker.poll():
                if 'error' in item:self.results.clear()
                if 'regions' in item:
                    for key,rect in item['regions'].items():
                        if key in active and key in item.get('signatures',{}):
                            self.results[key]=(rect,item['clients'][key],item['requested_at'],item['signatures'][key])
            if (not self.worker.process.is_alive() or
                (self.worker.requested_at is not None and now-self.worker.requested_at>1.2) or
                (not self.worker.ready and now-self.worker.created_at>8)):
                self.worker.close();self.worker=None;self.results.clear();self.last_submit=now+2
        for key,profile in profiles.items():
            if profile['mode']!='tracked':continue
            token=repr(profile)
            if self.profile_tokens.get(key)!=token:
                self.profile_tokens[key]=token;self.binding.pop(key,None)
                self.visual_cache.pop(key,None);self.results.pop(key,None)
            candidates=[w for w in windows if w['key']==key and w['mode']!='ignore']
            bound=profile.get('binding') or self.binding.get(key)
            if bound:
                window=next((w for w in candidates if w['handle']==bound['handle'] and w['pid']==bound['pid']),None)
                if window is None:
                    # 最小化只暂时不可见，保留身份；不转移到同应用另一窗口。
                    continue
            elif len(candidates)==1 and profile['anchor']['type']!='visual':
                window=candidates[0];self.binding[key]={'handle':window['handle'],'pid':window['pid']}
            else:continue
            anchor=profile['anchor'];rect=None;method='pending'
            if anchor['type']=='native':
                from region_anchor import locate_anchor
                try:rect=locate_anchor(window['handle'],anchor,origin)
                except Exception:rect=None
                if rect:method='native'
            elif anchor['type']=='uia':
                digest=client_signature(image,window['client'])
                signature={'layout':digest,'size':tuple(window['client'][2:]),
                           'handle':window['handle'],'pid':window['pid'],
                           'profile':hashlib.blake2b(token.encode('utf-8'),digest_size=16).hexdigest()}
                if digest is not None:
                    tasks[key]={'handle':window['handle'],'anchor':anchor};clients[key]=window['client']
                    signatures[key]=signature
                cached=self.results.get(key)
                if (digest is not None and cached and cached[0] and 0<=now-cached[2]<=.8
                        and cached[3]==signature):
                    # Only equal client-relative pixels can bridge window
                    # translation. Internal changes invalidate the old box now.
                    rect=(cached[0][0]+window['client'][0]-cached[1][0],cached[0][1]+window['client'][1]-cached[1][1],*cached[0][2:]);method='uia'
                elif cached:self.results.pop(key,None)
            if rect is None and profile.get('features') is not None:
                cached=self.visual_cache.get(key)
                signature=(self.image_sequence,window['client'])
                if cached is None or cached[0]!=signature:
                    rect=locate_features(image,window['client'],profile['features'])
                    self.visual_cache[key]=(signature,rect)
                else:rect=cached[1]
                if rect:method='visual'
            if rect is not None:
                from app_scope import intersect
                rect=intersect(rect,window['rect'])
            resolved[key]={'handle':window['handle'],'rect':rect,'method':method}
        if tasks:
            if self.worker is None and now>=self.last_submit:
                from region_worker import RegionWorker
                self.worker=RegionWorker()
            if self.worker and self.worker.ready and self.worker.requested_at is None and now-self.last_submit>=.15:
                self.sequence+=1;self.last_submit=now
                self.worker.submit({'command':'locate','tasks':tasks,'origin':origin,'clients':clients,
                                    'signatures':signatures,'sequence':self.sequence,'requested_at':now})
        return resolved
