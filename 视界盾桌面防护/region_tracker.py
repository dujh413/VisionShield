"""窗口身份 + 控件结构 + 视觉特征；失败时不复用屏幕固定坐标。"""
import time
from region_features import locate_features


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
        resolved={};tasks={};clients={}
        if self.worker:
            for item in self.worker.poll():
                if 'regions' in item:
                    for key,rect in item['regions'].items():
                        self.results[key]=(rect,item['clients'][key],item['requested_at'])
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
                tasks[key]={'handle':window['handle'],'anchor':anchor};clients[key]=window['client']
                cached=self.results.get(key)
                if cached and cached[0] and now-cached[2]<=.8 and cached[1][2:]==window['client'][2:]:
                    # 仅窗口平移时以实时窗口位置换算，控件内部布局仍不断重读。
                    rect=(cached[0][0]+window['client'][0]-cached[1][0],cached[0][1]+window['client'][1]-cached[1][1],*cached[0][2:]);method='uia'
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
                self.worker.submit({'command':'locate','tasks':tasks,'origin':origin,'clients':clients,'sequence':self.sequence,'requested_at':now})
        return resolved
