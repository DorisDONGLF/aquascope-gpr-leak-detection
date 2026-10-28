"""Recover historical merge members and render fixed-XY comparison PNGs.

Presence scores and original candidate records are never changed. Old jobs did
not keep merge members, so their saved scores are replayed through the original
peak/localizer/merge procedure and checked against EVERY existing candidate.
"""
from pathlib import Path
import collections
import json
import math

VERSION = 1
GALLERY_VERSION = 4


def signature(candidates):
    return [[r['candidate_id'],r['file_id'],r['window_center_trace_1based'],
             r['trace_1based'],r['x'],r['y'],r['supporting_observations']]
            for r in candidates]


def write_members(out, sites, fingerprint):
    payload = dict(version=VERSION,checkpoint_sha256=fingerprint,
                   signature=signature(sites),
                   members={s['candidate_id']:s['members'] for s in sites})
    path=Path(out)/'observation_members.json'
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    temp.replace(path)
    return payload['members']


def group_peaks(peaks, merge):
    """Original greedy merge: highest response anchors each fixed centre."""
    sites=[];buckets=collections.defaultdict(list)
    for r in sorted(peaks,key=lambda r:r['logit'],reverse=True):
        matches=[]
        if r['x'] is not None:
            cell=(math.floor(r['x']/merge),math.floor(r['y']/merge))
            for ax in [-1,0,1]:
                for ay in [-1,0,1]:
                    matches.extend(i for i in buckets[(cell[0]+ax,cell[1]+ay)]
                                   if math.hypot(r['x']-sites[i]['x'],r['y']-sites[i]['y'])<merge)
        else:
            matches=[i for i,s in enumerate(sites) if s['file_id']==r['file_id']
                     and abs(s['trace_1based']-r['trace_1based'])*r['spacing_m']<merge]
        if matches:
            i=min(matches,key=lambda i:math.hypot(r['x']-sites[i]['x'],r['y']-sites[i]['y'])
                  if r['x'] is not None else abs(sites[i]['trace_1based']-r['trace_1based']))
            sites[i]['members'].append(r)
        else:
            if r['x'] is not None:buckets[cell].append(len(sites))
            sites.append(dict(**r,members=[r]))
    return sites


def reconcile_members(candidates, reconstructed):
    """Reject partial or changed associations instead of presenting guessed views."""
    def key(r):
        return r['file_id'],r['window_center_trace_1based'],r['trace_1based']
    groups={key(s):s for s in reconstructed}
    if len(groups)!=len(reconstructed) or len(candidates)!=len(reconstructed):
        raise ValueError('Historical merged-result counts do not match the existing candidates. Existing results are preserved. Run detection again to generate complete observations.')
    result=[]
    for candidate in candidates:
        group=groups.get(key(candidate))
        if group is None or len(group['members'])!=candidate['supporting_observations']:
            raise ValueError(f'{candidate["candidate_id"]} has inconsistent historical observation counts or centers; no unreliable association was generated.')
        if any(group[k]!=candidate[k] for k in ('x','y','logit')):
            raise ValueError(f'{candidate["candidate_id"]} has a historical primary observation that differs from the existing result.')
        if len({r['profile'] for r in group['members']})!=candidate['supporting_swaths']:
            raise ValueError(f'{candidate["candidate_id"]} has inconsistent swath associations.')
        result.append(dict(candidate,members=group['members']))
    return result


def recover_members(engine, job, out, progress):
    from engine import read_sgy,batch_input,nearest,torch,np,DEVICE
    out=Path(out);cache=out/'observation_members.json'
    if cache.is_file():
        saved=json.loads(cache.read_text(encoding='utf-8'))
        if (saved.get('version')==VERSION and saved.get('signature')==signature(job['candidates'])
                and saved.get('checkpoint_sha256')==job['summary'].get('checkpoint_sha256')):
            return saved['members']
    if job['summary'].get('checkpoint_sha256')!=engine.fingerprint:
        raise ValueError('The historical run used different model weights. The current localizer cannot reconstruct its observation associations reliably.')
    opts=job['options'];merge=float(opts.get('merge_m',4));fallback=float(opts.get('spacing_m',.04))
    threshold=float(opts.get('threshold',engine.threshold));threshold_logit=math.log(threshold/(1-threshold))
    known=engine.known if opts.get('use_known',True) else np.empty((0,2))
    exclude=bool(opts.get('exclude_known',False));sources={f['id']:f for f in job['input_files']}
    peaks=[]
    for fi,meta in enumerate(job['files']):
        progress(.65*fi/max(1,len(job['files'])),f'Recovering historical observations {fi+1}/{len(job["files"])} · {meta["name"]}')
        source=sources[meta['file_id']];path=Path(source['path'])
        if not path.is_file():raise ValueError(f'Source SGY not found: {meta["name"]}. The existing primary image remains available.')
        if source.get('size') and path.stat().st_size!=source['size']:
            raise ValueError(f'Source SGY size has changed: {meta["name"]}. Changed data was not used to recover historical observations.')
        smp,x,y,dx,current=read_sgy(path,fallback);n,ns=smp.shape;half=max(1,round(4/dx))
        if n!=meta['traces'] or ns!=meta['samples_per_trace']:
            raise ValueError(f'Source SGY sample layout has changed: {meta["name"]}.')
        with np.load(out/'scores'/f'file_{fi:03d}.npz',allow_pickle=False) as scores:
            centers=scores['trace_1based'].astype(int)-1;logs=scores['logit'].copy()
        if len(centers)!=len(logs) or ((centers<0)|(centers>=n)).any():
            raise ValueError('Invalid historical scored trace numbers or array lengths.')
        xy_ok=current['coordinate_available'];above=np.flatnonzero(logs>=threshold_logit);chosen=[]
        for ix in above[np.argsort(-logs[above],kind='stable')]:
            if all(abs(int(centers[ix])-int(centers[j]))*dx>=merge and
                   (not xy_ok or np.hypot(x[centers[ix]]-x[centers[j]],y[centers[ix]]-y[centers[j]])>=merge)
                   for j in chosen):chosen.append(int(ix))
        if not chosen:
            del smp
            continue
        full=torch.from_numpy(smp.astype(np.float32).T.copy()).to(DEVICE)
        for off in range(0,len(chosen),128):
            inds=chosen[off:off+128];jj=centers[inds]
            with torch.no_grad():cols=engine.localizer(batch_input(full,jj,half)).argmax(1).cpu().tolist()
            for ix,j,col in zip(inds,jj,cols):
                est=int(np.clip(j-half+round((col+.5)*(2*half+1)/193-.5),0,n-1))
                dist=float(nearest(x[est:est+1],y[est:est+1],known)[0]) if xy_ok and len(known) else None
                if exclude and dist is not None and dist<8:continue
                peaks.append(dict(file_id=meta['file_id'],name=meta['name'],profile=meta['profile'],
                    channel=meta['channel'],trace_1based=est+1,window_center_trace_1based=int(j+1),
                    x=float(x[est]) if xy_ok else None,y=float(y[est]) if xy_ok else None,
                    logit=float(logs[ix]),spacing_m=dx,samples_per_trace=ns))
        del full,smp
    progress(.66,'Checking historical candidates and merged observations')
    sites=reconcile_members(job['candidates'],group_peaks(peaks,merge))
    return write_members(out,sites,engine.fingerprint)


def distance_order(candidate, members):
    rows=[]
    for index,member in enumerate(members):
        r=dict(member)
        primary=(r['file_id']==candidate['file_id'] and
                 r['window_center_trace_1based']==candidate['window_center_trace_1based'] and
                 r['trace_1based']==candidate['trace_1based'])
        valid=all(isinstance(v,(int,float)) and math.isfinite(v)
                  for v in (r.get('x'),r.get('y'),candidate.get('x'),candidate.get('y')))
        if valid:
            distance=math.hypot(r['x']-candidate['x'],r['y']-candidate['y']);kind='xy'
        elif r['file_id']==candidate['file_id']:
            distance=abs(r['trace_1based']-candidate['trace_1based'])*r['spacing_m'];kind='along_track_estimate'
        else:distance=None;kind='unknown'
        r.update(primary=primary,distance_to_primary_m=distance,distance_kind=kind,source_index=index)
        rows.append(r)
    rows.sort(key=lambda r:(r['distance_to_primary_m'] is None,
                           r['distance_to_primary_m'] if r['distance_to_primary_m'] is not None else math.inf,
                           not r['primary'],r['profile'],r['channel'] if r['channel'] is not None else -1,
                           r['trace_1based'],r['source_index']))
    for index,row in enumerate(rows):row['observation_id']=f'O{index+1:04d}'
    return rows


def build_gallery(engine,job,candidate_id,out,progress):
    from engine import read_sgy,save_panel,np
    candidate=next(r for r in job['candidates'] if r['candidate_id']==candidate_id)
    members=recover_members(engine,job,out,progress)[candidate_id]
    rows=distance_order(candidate,members);out=Path(out)
    folder=out/'images'/'observations'/candidate_id;folder.mkdir(parents=True,exist_ok=True)
    sources={f['id']:f for f in job['input_files']};by_file=collections.defaultdict(list)
    for r in rows:by_file[r['file_id']].append(r)
    completed=0
    for fid,items in by_file.items():
        source=sources[fid]
        smp,x,y,dx,meta=read_sgy(source['path'],float(job['options'].get('spacing_m',.04)))
        half=max(1,round(4/dx));hc=max(1,round(8/dx))
        for r in items:
            if r['primary']:
                r['file']=next(p['file'] for p in candidate['panels'] if p['primary'])
                r['context_image']=candidate['context_image']
            else:
                j=r['window_center_trace_1based']-1;est=r['trace_1based']-1
                ids=np.clip(np.arange(j-half,j+half+1),0,len(smp)-1)
                stem=f'images/observations/{candidate_id}/{r["observation_id"]}'
                r['file']=stem+'.png';r['context_image']=stem+'_context.png'
                save_panel(smp[ids].astype(np.float32).T,out/r['file'],(est-j+half)/(2*half),None,True)
                ids=np.clip(np.arange(est-hc,est+hc+1),0,len(smp)-1)
                save_panel(smp[ids].astype(np.float32).T,out/r['context_image'],.5)
            completed+=1
            progress(.68+.31*completed/max(1,len(rows)),f'Rendering observation images {completed}/{len(rows)}')
        del smp
    return rows


def group_remaining_observations(candidate, rows, main_rows):
    """Keep every merged observation, without duplicating the main channel views.

    Other swaths are ordered by their nearest MERGED observation, then every
    observation inside a swath is ordered by XY distance to the fixed primary.
    Extra observations in the primary swath are kept in a final separate group.
    """
    used={r.get('source_observation_id') for r in main_rows if r.get('source_observation_id')}
    groups=collections.defaultdict(list)
    for r in rows:
        if r['observation_id'] not in used:groups[r['profile']].append(dict(r))
    def distance_key(r):
        d=r.get('distance_to_primary_m')
        return (d is None,d if d is not None else math.inf,
                r['channel'] if r['channel'] is not None else -1,r['trace_1based'])
    result=[]
    for profile,members in groups.items():
        members.sort(key=distance_key)
        result.append(dict(profile=profile,primary_swath=profile==candidate['profile'],
                           nearest_distance_m=members[0].get('distance_to_primary_m'),rows=members))
    result.sort(key=lambda g:(g['primary_swath'],g['nearest_distance_m'] is None,
                             g['nearest_distance_m'] if g['nearest_distance_m'] is not None else math.inf,
                             g['profile']))
    return result


def build_channel_comparison(engine,job,candidate_id,out,progress):
    from spatial_alignment import build_aligned_comparison
    candidate=next(r for r in job['candidates'] if r['candidate_id']==candidate_id)
    out=Path(out)
    existing=candidate.get('observation_gallery',[])
    if len(existing)==candidate['supporting_observations'] and all(
            (out/r['file']).is_file() and (out/r['context_image']).is_file() for r in existing):
        rows=existing
    else:
        rows=build_gallery(engine,job,candidate_id,out,lambda value,msg:progress(value*.3,msg))
    return build_aligned_comparison(job,candidate,rows,out,progress)
