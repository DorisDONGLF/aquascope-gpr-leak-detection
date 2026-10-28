"""Loopback-only local SGY review service. No cloud service or package install required."""
from pathlib import Path
import argparse, csv, io, json, os, secrets, threading, time, traceback, uuid, zipfile, html
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs,unquote
from concurrent.futures import ThreadPoolExecutor
from point_exports import make_export
from review_records import updated_review, cleared_reviews
from observation_gallery import GALLERY_VERSION
BASE=Path(__file__).resolve().parent;DATA=BASE.parent;RUNTIME=Path(os.environ.get('APP_DATA_DIR',str(BASE)));STORE=RUNTIME/'runs';UPLOADS=RUNTIME/'uploads'
STORE.mkdir(parents=True,exist_ok=True);UPLOADS.mkdir(parents=True,exist_ok=True)
LOCK=threading.RLock();POOL=ThreadPoolExecutor(max_workers=1);JOBS={};OBS_TASKS={};ENGINE=None;TOKEN=secrets.token_hex(24)
LABELS={'unreviewed':'Pending review','similar':'Suspected leak','different':'No leak signal','manhole':'Possible manhole / verify','uncertain':'Uncertain'}
def write_job(job):
 folder=STORE/job['id'];folder.mkdir(exist_ok=True);tmp=folder/'job.tmp';tmp.write_text(json.dumps(job,ensure_ascii=False,allow_nan=False),encoding='utf-8');tmp.replace(folder/'job.json')
for path in STORE.glob('*/job.json'):
 try:
  job=json.loads(path.read_text(encoding='utf-8'))
  if job['status'] in ['queued','running']:job.update(status='error',message='The service stopped before the previous detection finished. Please run detection again.');write_job(job)
  JOBS[job['id']]=job
 except (OSError,ValueError,KeyError):pass

def start_job(files,options,title=None):
 if not 0<float(options.get('threshold',.98557657))<1:raise ValueError('The threshold must be between 0 and 1.')
 for key,default,lo,hi in [('step_m',.5,.1,2),('merge_m',4,.5,20),('spacing_m',.04,.001,2)]:
  value=float(options.get(key,default))
  if not lo<=value<=hi:raise ValueError(f'{key} is outside the supported range {lo}–{hi}.')
  options[key]=value
 id=uuid.uuid4().hex;job=dict(id=id,title=title or files[0]['name'],created=time.strftime('%Y-%m-%d %H:%M:%S'),status='queued',progress=0,message='Waiting for detection',input_files=files,options=options,candidates=[],files=[],summary={},warnings=[])
 with LOCK:JOBS[id]=job;write_job(job)
 POOL.submit(run_job,id);return job

def run_job(id):
 global ENGINE
 try:
  with LOCK:job=JOBS[id];job.update(status='running',message='Loading model');write_job(job)
  if ENGINE is None:
   from engine import Engine
   ENGINE=Engine()
  last_save=[0]
  def progress(value,message,stats):
   with LOCK:
    base=.08 if job.get('source_archive') else 0
    job.update(progress=base+(1-base)*value,message=message,live_stats=stats)
    if time.monotonic()-last_save[0]>2:write_job(job);last_save[0]=time.monotonic()
  result=ENGINE.scan(job['input_files'],job['options'],STORE/id,progress)
  with LOCK:job.update(result);job.update(status='done',progress=1,message='Detection complete; awaiting expert review');write_job(job)
 except Exception as e:
  traceback.print_exc()
  with LOCK:JOBS[id].update(status='error',message=str(e));write_job(JOBS[id])

def run_test_archive(id,path):
 """Import the user-selected local test archive without a multi-GB browser copy."""
 try:
  with LOCK:job=JOBS[id];job.update(status='running',message='Importing local test archive');write_job(job)
  target=UPLOADS/('archive_'+id);target.mkdir(exist_ok=True);files=[]
  with zipfile.ZipFile(path) as z:
   members=[m for m in z.infolist() if not m.is_dir() and Path(m.filename).suffix.lower() in ['.sgy','.segy']]
   if not members or len(members)>5000:raise ValueError('The test archive must contain 1–5,000 SGY files.')
   if sum(m.file_size for m in members)>50*1024**3:raise ValueError('The uncompressed test archive exceeds 50 GB.')
   import shutil
   for i,m in enumerate(sorted(members,key=lambda m:m.filename)):
    if m.file_size>2*1024**3:raise ValueError('An SGY file in the test archive exceeds 2 GB.')
    fid=uuid.uuid4().hex;dest=target/f'{fid}.sgy'
    with z.open(m) as source,dest.open('wb') as output:shutil.copyfileobj(source,output,1024*1024)
    # Preserve original relative names so distinct swaths in archive subfolders stay distinct.
    files.append(dict(id=fid,name=m.filename,path=str(dest),size=m.file_size,archive_member=m.filename))
    if i%10==0 or i+1==len(members):
     with LOCK:job.update(progress=.08*(i+1)/len(members),message=f'Importing test archive: {i+1}/{len(members)} SGY files',live_stats=dict(files_imported=i+1,files_total=len(members)));write_job(job)
  with LOCK:job['input_files']=files;write_job(job)
  run_job(id)
 except Exception as e:
  traceback.print_exc()
  with LOCK:JOBS[id].update(status='error',message=str(e));write_job(JOBS[id])

def observation_state(job,candidate):
 rows=candidate.get('observation_gallery')
 if rows and candidate.get('observation_gallery_version')==GALLERY_VERSION and candidate.get('channel_gallery'):
  return dict(status='done',progress=1,rows=rows,main_rows=candidate['channel_gallery'],
              groups=candidate.get('swath_gallery_groups',[]),warnings=candidate.get('channel_gallery_warnings',[]),
              alignment_audit=candidate.get('alignment_audit'),
              message='Channels are aligned to the fixed primary candidate XY; browse by channel number')
 return OBS_TASKS.get((job['id'],candidate['candidate_id']),dict(status='idle',progress=0,message='Waiting to recover associated observations'))

def run_observations(id,candidate_id):
 global ENGINE
 key=(id,candidate_id)
 try:
  with LOCK:
   snapshot=json.loads(json.dumps(JOBS[id]));OBS_TASKS[key]=dict(status='running',progress=0,message='Preparing associated observation images')
  if ENGINE is None:
   from engine import Engine
   ENGINE=Engine()
  from observation_gallery import build_channel_comparison
  def progress(value,message):
   with LOCK:OBS_TASKS[key]=dict(status='running',progress=value,message=message)
  gallery=build_channel_comparison(ENGINE,snapshot,candidate_id,STORE/id,progress)
  with LOCK:
   candidate=next(r for r in JOBS[id]['candidates'] if r['candidate_id']==candidate_id)
   candidate.update(observation_gallery=gallery['rows'],channel_gallery=gallery['main_rows'],
                    swath_gallery_groups=gallery['groups'],channel_gallery_warnings=gallery['warnings'],
                    observation_gallery_version=GALLERY_VERSION,alignment_audit=gallery['alignment_audit'])
   write_job(JOBS[id]);OBS_TASKS.pop(key,None)
 except Exception as e:
  traceback.print_exc()
  with LOCK:OBS_TASKS[key]=dict(status='error',progress=0,message=str(e))

def export_csv(job):
 out=io.StringIO(newline='');fields=['candidate_id','review_label','reviewer','notes','name','profile','channel','trace_1based','window_center_trace_1based','x','y','distance_to_known_m','near_known','logit','signal_score','samples_per_trace','supporting_observations','supporting_channels','supporting_swaths','spacing_m','localizer_shift_m']
 w=csv.DictWriter(out,fieldnames=fields);w.writeheader()
 for r in job['candidates']:
  vals={k:r.get(k) for k in fields};vals['supporting_channels']=','.join(map(str,r['supporting_channels']));w.writerow(vals)
 return ('\ufeff'+out.getvalue()).encode('utf-8')

def export_report(job):
 esc=lambda s:html.escape(str(s))
 def observation_html(p):
  dist='Distance unavailable' if p.get('distance_to_primary_m') is None else f'Distance from primary center: {p["distance_to_primary_m"]:.3f} m'
  label='Blue: alignment reference; not a merged hit' if p.get('view_kind')=='reference' else f'Green: AI center · Response {p["logit"]:.2f}'
  if p.get('alignment_version')==GALLERY_VERSION:
   dist=f'Track distance from fixed primary point: {p["alignment_distance_m"]:.3f} m · Nearest recorded trace {p["alignment_trace_1based"]}'
   label='Blue: fixed primary point projected onto the track; dashed green: AI center. '+('Reference image; no additional detection. ' if p.get('view_kind')=='reference' else f'Scan-window model value {p["logit"]:.2f}.')
   if p.get('alignment_ambiguous'):label+='Multiple track matches are possible; check alignment.'
  return f'<p>{esc(p["profile"])} · CH {p["channel"]} · Trace {p["trace_1based"]} · {dist} · {label}</p><img src="{esc(p["file"])}">'
 cards=[]
 for r in job['candidates']:
  primary=next(p for p in r['panels'] if p['primary']);xy='Coordinates unavailable' if r['x'] is None else f'X {r["x"]:.3f} · Y {r["y"]:.3f}'
  observations=r.get('observation_gallery',[])
  if r.get('channel_gallery'):
   extra='<h3>Primary swath: ordered by channel number</h3>'+''.join(observation_html(p) for p in r['channel_gallery'] if not p['primary'])
   for group in r.get('swath_gallery_groups',[]):
    extra+='<h3>'+('Primary swath: additional merged observations: ' if group['primary_swath'] else 'Nearby swath: ')+esc(group['profile'])+'</h3>'+''.join(observation_html(p) for p in group['rows'])
  else:extra=''.join(observation_html(p) for p in observations if not p['primary']) if observations else ''.join(f'<p>CH {p["channel"]}</p><img src="{esc(p["file"])}">' for p in r['panels'] if not p['primary'])
  cards.append(f'<article><h2>{r["candidate_id"]} · CH {r["channel"]} · Model response {r["logit"]:.2f} (ranking only)</h2><p>{esc(r["name"])} · Localized trace {r["trace_1based"]}<br>{xy} · Original vertical samples: {r["samples_per_trace"]} samples</p><p>Review: {LABELS[r["review_label"]]} · Reviewer: {esc(r["reviewer"])}<br>Notes: {esc(r["notes"])}</p><img src="{esc(primary["file"])}"><details><summary>16 m context / other hit channels</summary><img src="{esc(r["context_image"])}">{extra}</details></article>')
 return ('<!doctype html><meta charset="utf-8"><title>SGY expert review atlas</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;line-height:1.7}article{border-top:1px solid #ccc;padding:22px 0}img{width:100%}</style><h1>'+esc(job['title'])+'</h1><p>v3 signal-similarity candidates. Model scores are not leak probabilities. Green marks the AI center for expert review. The full vertical range is scaled for display; equal image heights across files do not imply equal depths.</p>'+''.join(cards)).encode('utf-8')

class Handler(BaseHTTPRequestHandler):
 def log_message(self,fmt,*args):
  if not ('/api/jobs/' in args[0] and 'GET' in args[0]):super().log_message(fmt,*args)
 def headers_ok(self):
  origin=self.headers.get('Origin')
  if origin and origin not in [f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}']:return False
  return True
 def send(self,data,ctype='application/json; charset=utf-8',status=200,attachment=None):
  if isinstance(data,(dict,list)):data=json.dumps(data,ensure_ascii=False,allow_nan=False).encode('utf-8')
  if isinstance(data,str):data=data.encode('utf-8')
  self.send_response(status);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if attachment:self.send_header('Content-Disposition',f'attachment; filename="{attachment}"')
  self.end_headers()
  try:self.wfile.write(data)
  except (BrokenPipeError,ConnectionResetError):pass
 def error(self,error,status=400):self.send(dict(error=str(error)),status=status)
 def do_GET(self):
  try:
   if not self.headers_ok():return self.error('Source not allowed.',403)
   path=unquote(urlparse(self.path).path)
   if path=='/api/state':
    with LOCK:
     history=[{k:j[k] for k in ['id','title','created','status','progress','message']}|{'candidate_count':len(j['candidates'])} for j in sorted(JOBS.values(),key=lambda j:j['created'],reverse=True)]
    return self.send(dict(token=TOKEN,model='Fairview v3',threshold=.9855765700340271,jobs=history,known_reference='Fairview Hong Kong Grid XY',demo='Original CH16 SGY from the example survey line'))
   parts=path.strip('/').split('/')
   if len(parts)>=3 and parts[:2]==['api','jobs']:
    id=parts[2]
    with LOCK:
     if id not in JOBS:return self.error('Detection run not found.',404)
     job=json.loads(json.dumps(JOBS[id]))
    if len(parts)==3:return self.send(job)
    if len(parts)==4 and parts[3]=='observations':
     candidate_id=parse_qs(urlparse(self.path).query).get('candidate_id',[''])[0]
     candidate=next((r for r in job['candidates'] if r['candidate_id']==candidate_id),None)
     if candidate is None:return self.error('Candidate not found.',404)
     with LOCK:state=observation_state(job,candidate)
     return self.send(state)
    if parts[3]=='csv':return self.send(export_csv(job),'text/csv; charset=utf-8',attachment=f'{id}_review.csv')
    if parts[3]=='report':return self.send(export_report(job),'text/html; charset=utf-8',attachment=f'{id}_report.html')
    if parts[3]=='bundle':
     if job['status']!='done':return self.error('The atlas can be exported after detection completes.')
     bundle=io.BytesIO()
     with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
      z.writestr('report.html',export_report(job));z.writestr('candidates.csv',export_csv(job));z.writestr('metadata.json',json.dumps({k:job[k] for k in ['summary','files','options','warnings']},ensure_ascii=False,indent=2))
      assets={f['overview'] for f in job['files']}
      for r in job['candidates']:
       assets.add(r['context_image']);assets.update(p['file'] for p in r['panels'])
       for p in r.get('observation_gallery',[]):assets.add(p['file']);assets.add(p['context_image'])
       for p in r.get('channel_gallery',[]):assets.add(p['file']);assets.add(p['context_image'])
      for asset in sorted(assets):
       p=(STORE/id/asset).resolve()
       if not p.is_relative_to((STORE/id/'images').resolve()) or p.suffix.lower() not in ['.png','.jpg']:raise ValueError('Invalid image export path.')
       z.write(p,asset)
     return self.send(bundle.getvalue(),'application/zip',attachment=f'{id}_review_atlas.zip')
   if path.startswith('/runs/'):
    target=(STORE/path[len('/runs/'):]).resolve()
    if not target.is_relative_to(STORE.resolve()) or target.suffix.lower() not in ['.jpg','.png','.npz']:return self.error('Invalid file path.',403)
   else:
    target=(BASE/'static'/('index.html' if path=='/' else path.lstrip('/'))).resolve()
    if not target.is_relative_to((BASE/'static').resolve()):return self.error('Invalid path.',403)
   if not target.is_file():return self.error('File not found.',404)
   types={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.jpg':'image/jpeg','.png':'image/png'}
   self.send(target.read_bytes(),types.get(target.suffix,'application/octet-stream'))
  except Exception as e:traceback.print_exc();self.error(e,500)
 def do_POST(self):
  try:
   if not self.headers_ok() or self.headers.get('X-App-Token')!=TOKEN:return self.error('Please use the local application page.',403)
   parsed=urlparse(self.path);path=parsed.path;length=int(self.headers.get('Content-Length','0'))
   if path=='/api/uploads':
    name=Path(parse_qs(parsed.query).get('name',['input.SGY'])[0].replace('\\','/')).name
    if Path(name).suffix.lower() not in ['.sgy','.segy']:return self.error('Select an SGY / SEGY file.')
    if not 3840<=length<=2*1024**3:return self.error('File size must be between 3,840 bytes and 2 GB.')
    id=uuid.uuid4().hex;target=UPLOADS/f'{id}.sgy';remaining=length
    try:
     with target.open('wb') as f:
      while remaining:
       block=self.rfile.read(min(1024*1024,remaining))
       if not block:raise ValueError('Upload interrupted. Please retry.')
       f.write(block);remaining-=len(block)
    except Exception:target.unlink(missing_ok=True);raise
    meta=dict(id=id,name=name,path=str(target),size=length);(UPLOADS/f'{id}.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8');return self.send(meta)
   if length>1024*1024:return self.error('Request too large.',413)
   data=json.loads(self.rfile.read(length) or b'{}')
   if path=='/api/local-test':
    archive=Path(data.get('path','')).resolve();allowed=[(DATA/name).resolve() for name in ['model test']+[f'model test {i}' for i in range(2,9)]]
    if not any(archive.is_relative_to(root) for root in allowed) or not archive.is_file() or archive.suffix.lower()!='.zip':raise ValueError('This endpoint accepts ZIP test archives only from the project model test through model test 8 directories.')
    options=dict(step_m=.5,merge_m=4,threshold=.9855765700340271,spacing_m=.04,use_known=False,exclude_known=False)
    id=uuid.uuid4().hex;job=dict(id=id,title=data.get('title') or archive.stem,created=time.strftime('%Y-%m-%d %H:%M:%S'),status='queued',progress=0,message='Waiting to import test archive',input_files=[],source_archive=str(archive),options=options,candidates=[],files=[],summary={},warnings=['Cross-project test: Fairview known-point comparison is disabled. Full vertical records are resampled to the model input. No ground-truth labels are available for this project, so field accuracy cannot be calculated.'])
    with LOCK:JOBS[id]=job;write_job(job)
    POOL.submit(run_test_archive,id,archive);return self.send(job)
   if path=='/api/jobs':
    ids=data.get('uploads',[])
    if not 1<=len(ids)<=128:raise ValueError('Each run supports 1–128 files.')
    files=[]
    for id in ids:
     if not isinstance(id,str) or len(id)!=32 or any(c not in '0123456789abcdef' for c in id):raise ValueError('Invalid upload ID.')
     files.append(json.loads((UPLOADS/f'{id}.json').read_text(encoding='utf-8')))
    return self.send(start_job(files,data.get('options',{}),data.get('title')))
   if path=='/api/demo':
    # Explicit UI demo imports one real SGY, never synthetic scan results.
    name='1_26_2026 21535 PM_CUT_001_014-16.SGY';archive=DATA/'20260126_FairView Park_All_Zones (Last update- 20260316).zip';id='fairview_demo_ch16'
    target=UPLOADS/'demo_ch16.sgy'
    if not target.exists():
     with zipfile.ZipFile(archive) as z,z.open(name) as src,target.open('wb') as dst:
      import shutil
      shutil.copyfileobj(src,dst)
    file=dict(id=id,name=name,path=str(target),size=target.stat().st_size)
    return self.send(start_job([file],data.get('options',{}),'Example · Survey line CH16'))
   parts=path.strip('/').split('/')
   if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='observations':
    with LOCK:
     job=JOBS[parts[2]]
     if job['status']!='done':raise ValueError('Associated observations are available after detection completes.')
     candidate=next(r for r in job['candidates'] if r['candidate_id']==data.get('candidate_id'))
     state=observation_state(job,candidate);key=(job['id'],candidate['candidate_id'])
     if state['status'] in ['idle','error']:
      state=dict(status='queued',progress=0,message='Queued: recovering historical associations on first access; existing candidates and reviews are preserved')
      OBS_TASKS[key]=state;POOL.submit(run_observations,job['id'],candidate['candidate_id'])
    return self.send(state)
   if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='export':
    with LOCK:
     if parts[2] not in JOBS:raise ValueError('Detection run not found.')
     snapshot=json.loads(json.dumps(JOBS[parts[2]]))
    content,ctype,filename=make_export(snapshot,data)
    return self.send(content,ctype,attachment=filename)
   if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='selection':
    with LOCK:
     job=JOBS[parts[2]];mode=data.get('mode','all');ids=data.get('candidate_ids',[])
     if mode not in ['all','manual'] or not isinstance(ids,list) or not all(isinstance(x,str) for x in ids):raise ValueError('Invalid selection scope.')
     valid={r['candidate_id'] for r in job['candidates']}
     if set(ids)-valid:raise ValueError('The selection contains candidates that do not exist.')
     job['export_selection']=dict(mode=mode,candidate_ids=sorted(set(ids)) if mode=='manual' else [])
     write_job(job)
    return self.send(dict(saved=True,selection=job['export_selection']))
   if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='clear-reviews':
    with LOCK:
     job=JOBS[parts[2]]
     if job['status']!='done':raise ValueError('Reviews can be cleared only after detection completes.')
     if data.get('confirm_job_id')!=job['id']:raise ValueError('Confirm the current detection run before clearing reviews.')
     updated,count=cleared_reviews(job['candidates'])
     staged=dict(job,candidates=updated)
     write_job(staged)
     job['candidates']=updated
     reviews=[dict(candidate_id=r['candidate_id'],**{key:r.get(key) for key in ['review_label','reviewer','notes','reviewed_at','review_history']}) for r in updated]
    return self.send(dict(saved=True,cleared_count=count,reviews=reviews))
   if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='review':
    with LOCK:
     job=JOBS[parts[2]];candidate=next(r for r in job['candidates'] if r['candidate_id']==data['candidate_id'])
     updated=updated_review(candidate,data)
     staged=dict(job,candidates=[updated if r is candidate else r for r in job['candidates']])
     write_job(staged)
     candidate.update(updated)
     review={key:candidate.get(key) for key in ['review_label','reviewer','notes','reviewed_at','review_history']}
    return self.send(dict(saved=True,candidate_id=candidate['candidate_id'],review=review))
   self.error('Endpoint not found.',404)
  except (ValueError,KeyError,StopIteration,FileNotFoundError) as e:self.error(str(e) or 'Candidate not found.')
  except Exception as e:traceback.print_exc();self.error(e,500)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);args=parser.parse_args();server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
 (BASE/'running_service.json').write_text(json.dumps(dict(pid=os.getpid(),url=f'http://127.0.0.1:{server.server_port}',started=time.strftime('%Y-%m-%d %H:%M:%S'),script=str(Path(__file__).resolve())),indent=2),encoding='utf-8')
 print(f'Fairview SGY Review ready: http://127.0.0.1:{server.server_port}',flush=True);server.serve_forever()
if __name__=='__main__':main()
