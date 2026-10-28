"""Local, numerical SGY inference using the unchanged v3 detector and v1 localizer."""
from pathlib import Path
import sys, struct, csv, json, math, hashlib, re, collections, time
BASE=Path(__file__).resolve().parent
DATA=BASE.parent
from model_runtime import PresenceCNN, PooledLinear, Localizer, preprocess, torch, np, F, DEVICE
from PIL import Image,ImageDraw

REVIEW_LABELS={'unreviewed':'Pending review','similar':'Suspected leak','different':'No leak signal','manhole':'Possible manhole / verify','uncertain':'Uncertain'}

def read_sgy(path, fallback_spacing=.04):
 raw=Path(path).read_bytes()
 if len(raw)<3840:raise ValueError('File is too short to read the SEG-Y header.')
 ns=struct.unpack_from('>H',raw,3220)[0];fmt=struct.unpack_from('>H',raw,3224)[0]
 if fmt!=2:raise ValueError(f'This reader supports the verified big-endian int32 SEG-Y format 2. This file declares format {fmt}, which is not supported.')
 if not 1<=ns<=20000:raise ValueError('Invalid vertical sample-count field.')
 ext=struct.unpack_from('>h',raw,3504)[0]
 if ext<0 or ext>100:raise ValueError('This extended text-header layout is not supported.')
 offset=3600+ext*3200;stride=240+4*ns;n,rem=divmod(len(raw)-offset,stride)
 if rem or n<2:raise ValueError('Record length does not match the fixed trace length. Variable-length traces and this file layout are not supported.')
 h=np.ndarray((n,240),dtype='u1',buffer=raw,offset=offset,strides=(stride,1))
 def field(off,dt):return np.ascontiguousarray(h[:,off:off+np.dtype(dt).itemsize]).view(dt).ravel()
 trace_ns=field(114,'>u2')
 if ((trace_ns!=ns)&(trace_ns!=0)).any():raise ValueError('Trace-header sample counts are inconsistent; fixed-length parsing is unsafe.')
 samples=np.ndarray((n,ns),dtype='>i4',buffer=raw,offset=offset+240,strides=(stride,4))
 scalar=field(70,'>i2').astype(float);scalar=np.where(scalar>0,scalar,1/np.maximum(abs(scalar),1))
 x=field(72,'>i4')*scalar;y=field(76,'>i4')*scalar;units=field(88,'>u2');measurement=struct.unpack_from('>H',raw,3254)[0]
 delta=np.hypot(np.diff(x),np.diff(y));valid=delta[(delta>.001)&(delta<10)]
 # This project uses source XY in metres. Angular coordinates cannot be used as metres.
 xy_ok=bool(np.isfinite(x).all() and np.isfinite(y).all() and np.any((x!=0)|(y!=0)) and np.all(units<=1) and measurement!=2 and len(valid)>0)
 dx=float(np.median(valid)) if xy_ok else float(fallback_spacing)
 if dx<=0 or not np.isfinite(dx):raise ValueError('Cannot determine trace spacing. Supply a positive value in meters per trace.')
 return samples,x,y,dx,dict(traces=n,samples_per_trace=ns,format_code=fmt,byte_order='big endian',sample_interval_raw=struct.unpack_from('>H',raw,3216)[0],sample_interval_units_verified=False,vertical_extent='Full SGY record; all vertical samples retained',coordinate_available=xy_ok,coordinate_units_raw=sorted(set(map(int,units))),spacing_m=dx,spacing_source='Median spacing from source XY' if xy_ok else 'User-supplied fallback spacing',measurement_system_raw=measurement)

def known_points():
 rows=[]
 for path in [DATA/'updated_data_audit'/'corrected_point_mapping.csv',DATA/'review_step1_2'/'point_mapping.csv']:
  if path.exists():
   with path.open(encoding='utf-8-sig') as f:
    rows.extend((float(r['X']),float(r['Y'])) for r in csv.DictReader(f))
 return np.unique(np.asarray(rows),axis=0) if rows else np.empty((0,2))

def nearest(x,y,known):
 if not len(known):return np.full(len(x),np.inf)
 return np.hypot(np.asarray(x)[:,None]-known[:,0],np.asarray(y)[:,None]-known[:,1]).min(1)

@torch.no_grad()
def batch_input(full,centers,half):
 ii=torch.as_tensor(centers,device=DEVICE)[:,None]+torch.arange(-half,half+1,device=DEVICE)[None,:]
 a=F.interpolate(full[:,ii].permute(1,0,2)[:,None],size=(128,193),mode='bilinear',align_corners=False)
 lim=torch.quantile(a.abs().flatten(1),.99,dim=1).clamp_min(1e-12)
 return (a/lim[:,None,None,None]).clamp(-1,1)

def save_panel(a,path,center=None,window_center=None,model_view=False,center_color='#20c785'):
 if model_view:arr=preprocess(a)[0].numpy()
 else:
  lim=float(np.percentile(abs(a),99)) or 1;arr=np.clip(a/lim,-1,1)
 im=Image.fromarray(((arr+1)*127.5).clip(0,255).astype('uint8')).resize((1100,420)).convert('RGB');d=ImageDraw.Draw(im)
 if center is not None:d.line((center*1099,0,center*1099,419),fill=center_color,width=2)
 im.save(path,format='PNG',compress_level=3)

class Engine:
 def __init__(self):
  torch.set_num_threads(4)
  selected=torch.load(DATA/'model_v3'/'selected_model.pt',map_location='cpu',weights_only=False)
  self.model_name=selected['model_name'];self.threshold=float(selected['threshold'])
  path=DATA/'model_v3'/f'{self.model_name}.pt';ck=torch.load(path,map_location=DEVICE,weights_only=False)
  self.model=(PresenceCNN() if self.model_name=='cnn' else PooledLinear()).to(DEVICE);self.model.load_state_dict(ck['state_dict']);self.model.eval()
  self.localizer=Localizer().to(DEVICE);self.localizer.load_state_dict(torch.load(DATA/'model_v1'/'localizer_v1.pt',map_location=DEVICE,weights_only=False)['state_dict']);self.localizer.eval()
  self.known=known_points();self.fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()

 def scan(self,files,options,out,progress):
  t0=time.time();out=Path(out);(out/'images').mkdir(exist_ok=True);(out/'scores').mkdir(exist_ok=True)
  threshold=float(options.get('threshold',self.threshold));step_m=float(options.get('step_m',.5));merge=float(options.get('merge_m',4));exclude=bool(options.get('exclude_known',False));use_known=bool(options.get('use_known',True));fallback=float(options.get('spacing_m',.04));known=self.known if use_known else np.empty((0,2))
  peaks=[];metadata=[];total=hits=0;warnings=[]
  for fi,file in enumerate(files):
   name=file['name'];progress((fi/len(files))*.8,f'Reading {name}',dict(files_done=fi,files_total=len(files),windows_scored=total))
   s,x,y,dx,meta=read_sgy(file['path'],fallback);n,ns=s.shape;half=max(1,round(4/dx));step=max(1,round(step_m/dx));centers=np.arange(half,n-half,step,dtype=int)
   match=re.search(r'-(\d+)\.(?:sgy|segy)$',name,re.I);channel=int(match[1]) if match else None;profile=name[:match.start()] if match else Path(name).stem
   meta.update(name=name,file_id=file['id'],channel=channel,profile=profile,step_m=step*dx,edge_unscanned_est_m=half*dx,overview=f'images/file_{fi:03d}_overview.png')
   xy_ok=meta['coordinate_available']
   if not xy_ok:warnings.append(f'{name}: no reliable metric XY. Scanning uses the configured spacing; cross-file spatial merging and known-point comparison are disabled for this file.')
   d=nearest(x[centers],y[centers],known) if xy_ok else np.full(len(centers),np.inf)
   allowed=d>=8 if exclude and xy_ok else np.ones(len(centers),dtype=bool);excluded=int((~allowed).sum());centers=centers[allowed];d=d[allowed];logs=[]
   full=torch.from_numpy(s.astype(np.float32).T.copy()).to(DEVICE)
   # Full-file overview retains all recorded vertical samples and horizontal extent.
   overview=F.interpolate(full[None,None],size=(ns,min(1800,n)),mode='bilinear',align_corners=False)[0,0].cpu().numpy();save_panel(overview,out/meta['overview'])
   for off in range(0,len(centers),128):
    with torch.no_grad():
     batch=batch_input(full,centers[off:off+128],half);valid=batch.abs().flatten(1).amax(1)>0
     values=torch.full((len(batch),),-float('inf'),device=DEVICE)
     if valid.any():values[valid]=self.model(batch[valid])
     logs.extend(values.cpu().tolist())
    done=off+min(128,len(centers)-off);progress(((fi+done/max(1,len(centers)))/len(files))*.8,f'Scanning {name} · {done:,}/{len(centers):,} windows',dict(files_done=fi,files_total=len(files),windows_scored=total+done))
   logs=np.asarray(logs,dtype=np.float32);valid=np.isfinite(logs);skipped_zero=int((~valid).sum());centers=centers[valid];d=d[valid];logs=logs[valid]
   if skipped_zero:warnings.append(f'{name}: {skipped_zero} windows have no valid amplitude (all zeros) and were not scored; this does not establish a normal background.')
   threshold_logit=math.log(threshold/(1-threshold));above=np.flatnonzero(logs>=threshold_logit);chosen=[]
   for ix in above[np.argsort(-logs[above],kind='stable')]:
    if all(abs(int(centers[ix])-int(centers[j]))*dx>=merge and (not xy_ok or np.hypot(x[centers[ix]]-x[centers[j]],y[centers[ix]]-y[centers[j]])>=merge) for j in chosen):chosen.append(int(ix))
   for off in range(0,len(chosen),128):
    inds=chosen[off:off+128];jj=centers[inds]
    with torch.no_grad():cols=self.localizer(batch_input(full,jj,half)).argmax(1).cpu().tolist()
    for ix,j,col in zip(inds,jj,cols):
     est=int(np.clip(j-half+round((col+.5)*(2*half+1)/193-.5),0,n-1));dist=float(nearest(x[est:est+1],y[est:est+1],known)[0]) if xy_ok and len(known) else None
     if exclude and dist is not None and dist<8:continue
     peaks.append(dict(file_id=file['id'],name=name,profile=profile,channel=channel,trace_1based=est+1,window_center_trace_1based=int(j+1),x=float(x[est]) if xy_ok else None,y=float(y[est]) if xy_ok else None,window_center_x=float(x[j]) if xy_ok else None,window_center_y=float(y[j]) if xy_ok else None,distance_to_known_m=dist,near_known=dist is not None and dist<8,logit=float(logs[ix]),signal_score=float(1/(1+math.exp(-min(float(logs[ix]),80)))),spacing_m=dx,localizer_shift_m=(est-j)*dx,samples_per_trace=ns))
   np.savez_compressed(out/'scores'/f'file_{fi:03d}.npz',trace_1based=centers+1,logit=logs)
   meta.update(scored_windows=len(centers),threshold_hits=len(above),excluded_known_windows=excluded,skipped_zero_windows=skipped_zero);metadata.append(meta);total+=len(centers);hits+=len(above);del full,s
  progress(.82,'Merging duplicate windows and channel candidates',dict(windows_scored=total,files_done=len(files),files_total=len(files)))
  sites=[];buckets=collections.defaultdict(list)
  for r in sorted(peaks,key=lambda r:r['logit'],reverse=True):
   matches=[]
   if r['x'] is not None:
    cell=(math.floor(r['x']/merge),math.floor(r['y']/merge))
    for ax in [-1,0,1]:
     for ay in [-1,0,1]:matches.extend(i for i in buckets[(cell[0]+ax,cell[1]+ay)] if math.hypot(r['x']-sites[i]['x'],r['y']-sites[i]['y'])<merge)
   else:matches=[i for i,s in enumerate(sites) if s['file_id']==r['file_id'] and abs(s['trace_1based']-r['trace_1based'])*r['spacing_m']<merge]
   if matches:
    i=min(matches,key=lambda i:math.hypot(r['x']-sites[i]['x'],r['y']-sites[i]['y']) if r['x'] is not None else abs(sites[i]['trace_1based']-r['trace_1based']));sites[i]['members'].append(r)
   else:
    if r['x'] is not None:buckets[cell].append(len(sites))
    sites.append(dict(**r,members=[r]))
  needed=collections.defaultdict(list)
  for i,s in enumerate(sites,1):
   s.update(candidate_id=f'C{i:04d}',supporting_observations=len(s['members']),supporting_channels=sorted({r['channel'] for r in s['members'] if r['profile']==s['profile'] and r['channel'] is not None}),supporting_swaths=len({r['profile'] for r in s['members']}),review_label='unreviewed',reviewer='',notes='',panels=[])
   needed[s['file_id']].append((s,s,0));others=sorted([r for r in s['members'] if r['profile']==s['profile'] and r['channel']!=s['channel']],key=lambda r:r['logit'],reverse=True);used={s['channel']}
   for r in others:
    if r['channel'] in used:continue
    needed[r['file_id']].append((s,r,len(used)));used.add(r['channel'])
    if len(used)>=3:break
  for k,(fid,items) in enumerate(needed.items()):
   file=next(f for f in files if f['id']==fid);smp,x,y,dx,meta=read_sgy(file['path'],fallback);half=round(4/dx)
   for s,r,index in items:
    j=r['window_center_trace_1based']-1;est=r['trace_1based']-1;ix=np.clip(np.arange(j-half,j+half+1),0,len(smp)-1);fn=f'images/{s["candidate_id"]}_ch{r["channel"]}_{index}.png'
    save_panel(smp[ix].astype(np.float32).T,out/fn,(est-j+half)/(2*half),None,True);s['panels'].append(dict(file=fn,channel=r['channel'],logit=r['logit'],trace_1based=r['trace_1based'],primary=index==0))
    if index==0:
     hc=max(1,round(8/dx));ids=np.clip(np.arange(est-hc,est+hc+1),0,len(smp)-1);s['context_image']=f'images/{s["candidate_id"]}_context.png';save_panel(smp[ids].astype(np.float32).T,out/s['context_image'],.5)
   progress(.84+.15*(k+1)/max(1,len(needed)),f'Rendering candidate images: {k+1}/{len(needed)} files',dict(windows_scored=total,candidate_count=len(sites),files_done=len(files),files_total=len(files)))
  # Retain every merge member for distance-ordered cross-channel/swath review.
  from observation_gallery import write_members
  write_members(out,sites,self.fingerprint)
  for s in sites:
   s['panels'].sort(key=lambda p:not p['primary']);s.pop('members')
  sample_counts=dict(collections.Counter(m['samples_per_trace'] for m in metadata))
  if any(ns not in [113,212] for ns in sample_counts):warnings.insert(0,f'Vertical sampling is {min(sample_counts)}–{max(sample_counts)} points, outside the Fairview training counts of 113 / 212. The full range is retained and resampled to 128 rows. This is an input-distribution-shift test and does not establish detection accuracy.')
  if not use_known:warnings.insert(0,'Fairview known-point comparison is disabled; known-point distances and exclusions do not apply.')
  return dict(candidates=sites,files=metadata,summary=dict(candidate_count=len(sites),scored_windows=total,threshold_hit_windows=hits,channel_peaks=len(peaks),sgy_count=len(files),swath_count=len({m['profile'] for m in metadata}),vertical_sample_counts=sample_counts,threshold=threshold,step_m=step_m,merge_m=merge,known_exclusion_m=8 if exclude else 0,known_reference_enabled=use_known,elapsed_seconds=round(time.time()-t0,1),model='v3 presence CNN + v1 horizontal localizer',checkpoint_sha256=self.fingerprint,device=str(DEVICE),new_confirmed_leaks=0),warnings=warnings)
