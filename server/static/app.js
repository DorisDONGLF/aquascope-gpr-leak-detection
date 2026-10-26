'use strict';
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={unreviewed:'Pending review',similar:'Suspected leak',different:'No leak signal',manhole:'Possible manhole',uncertain:'Uncertain'};
// Translate system metadata cached by earlier UI versions, without changing run data.
function metadataText(value){return ({'\u5b8c\u6574 SGY \u8bb0\u5f55\uff0c\u672a\u88c1\u526a\u7eb5\u5411\u8303\u56f4':'Full SGY record; all vertical samples retained','source XY \u4e2d\u4f4d\u9053\u95f4\u8ddd':'Median spacing from source XY','\u7528\u6237\u8bbe\u7f6e\u7684\u5907\u7528\u9053\u95f4\u8ddd':'User-supplied fallback spacing'})[value]||value||'Not recorded'}
const counted=(n,noun)=>n+' '+noun+(n===1?'':'s');
const pageSize=12;
let token='',files=[],active=null,page=0,poll=null,busy=false,focused=null,manual=false,selected=new Set(),dirty=false,draftVersion=0,saving=null,selectionQueue=Promise.resolve(),selectionDirty=false,selectionVersion=0,loadVersion=0;
const hkWkt='PROJCS["Hong Kong 1980 Grid System",GEOGCS["Hong Kong 1980",DATUM["Hong_Kong_1980",SPHEROID["International 1924",6378388,297],TOWGS84[-162.619,-276.959,-161.764,0.067753,-2.243648,-1.158828,-1.094246]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AUTHORITY["EPSG","4611"]],PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",22.3121333333333],PARAMETER["central_meridian",114.178555555556],PARAMETER["scale_factor",1],PARAMETER["false_easting",836694.05],PARAMETER["false_northing",819069.8],UNIT["metre",1,AUTHORITY["EPSG","9001"]],AUTHORITY["EPSG","2326"]]';
function notice(message){$('notice').textContent=message;$('notice').hidden=!message}
function run(action){return Promise.resolve().then(action).catch(e=>notice(e.message))}
async function api(path,body){const res=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':token},body:JSON.stringify(body)});const data=await res.json();if(!res.ok)throw Error(data.error||'Request failed');return data}
function asset(path){return '/runs/'+active.id+'/'+path}
function options(){return {step_m:Number($('step').value),merge_m:Number($('merge').value),threshold:Number($('threshold').value),spacing_m:Number($('spacing').value),use_known:$('useKnown').checked,exclude_known:$('useKnown').checked&&$('excludeKnown').checked}}
function validOptions(){const o=options();if(!(o.threshold>0&&o.threshold<1&&o.step_m>=.1&&o.step_m<=2&&o.merge_m>=.5&&o.merge_m<=20&&o.spacing_m>=.001&&o.spacing_m<=2))throw Error('Check settings: step 0.1–2 m, merge distance 0.5–20 m, fallback spacing 0.001–2 m, and threshold between 0 and 1.');return o}
function showFiles(){$('fileList').innerHTML=files.map((f,i)=>`<div class="file-item"><b>SGY</b><span title="${esc(f.name)}">${esc(f.name)}</span><small>${(f.size/1048576).toFixed(1)} MB</small><button data-remove="${i}" aria-label="Remove ${esc(f.name)}">×</button></div>`).join('');$('startBtn').disabled=!files.length||busy;$('fileList').querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{files.splice(Number(b.dataset.remove),1);showFiles()})}
function addFiles(incoming){const list=[...incoming],good=list.filter(f=>/\.(sgy|segy)$/i.test(f.name)&&f.size>=3840&&f.size<=512*1024**2);let message=good.length!==list.length?'Non-SGY files, undersized files and files over 512 MB were ignored. ':'';const merged=[...files,...good].filter((f,i,a)=>a.findIndex(x=>x.name===f.name&&x.size===f.size&&x.lastModified===f.lastModified)===i);if(merged.length>128)message+='A maximum of 128 files is allowed per run; additional files were not added.';files=merged.slice(0,128);$('importError').textContent=message;showFiles()}
function busyState(value){busy=value;showFiles();$('demoBtn').disabled=value}
async function refresh(){const data=await api('/api/state');token=data.token;$('history').innerHTML=data.jobs.map(j=>`<button data-job="${j.id}" class="${active?.id===j.id?'selected':''}"><strong>${esc(j.title)}</strong><small>${esc(j.created)} · ${j.status==='done'?counted(j.candidate_count,'candidate'):j.status==='error'?'Detection incomplete':'Running / queued'}</small></button>`).join('')||'<p class="muted">No detection history</p>';$('runSelect').innerHTML='<option value="">Select a detection run…</option>'+data.jobs.map(j=>`<option value="${j.id}">${esc(j.title)} · ${j.status==='done'?counted(j.candidate_count,'point'):j.status}</option>`).join('');$('runSelect').value=active?.id||'';$('history').querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>run(async()=>{$('navDialog').close();await loadJob(b.dataset.job)}));return data}
function progress(value,message,title='Running detection'){const pct=Math.round(Math.max(0,Math.min(1,value||0))*100);$('progressPanel').hidden=false;$('progressTitle').textContent=title;$('progressPercent').textContent=pct+'%';$('progressFill').style.width=pct+'%';$('progressMessage').textContent=message;$('empty').hidden=true}
async function start(demo=false){try{const opts=validOptions();if(!demo&&!files.length)return;await saveCurrent();await selectionQueue;notice('');$('importError').textContent='';$('importDialog').close();busyState(true);$('results').hidden=true;$('exportBtn').disabled=true;const ids=[];if(!demo){for(let i=0;i<files.length;i++){const f=files[i];progress(i/files.length,`Uploading ${i+1}/${files.length} · ${f.name}`,'Importing SGY');const res=await fetch('/api/uploads?name='+encodeURIComponent(f.name),{method:'POST',headers:{'X-App-Token':token,'Content-Type':'application/octet-stream'},body:f});const data=await res.json();if(!res.ok)throw Error(data.error||'Upload failed');ids.push(data.id)}}const job=await api(demo?'/api/demo':'/api/jobs',demo?{options:opts}:{uploads:ids,options:opts,title:$('taskTitle').value.trim()||undefined});files=[];$('fileInput').value='';showFiles();await loadJob(job.id)}catch(e){$('importError').textContent=e.message;notice(e.message);$('progressPanel').hidden=true;busyState(false);if(active?.status==='done')renderResults();else $('empty').hidden=false}}
function clearFilterValues(){for(const id of ['sourceFileFilter','labelFilter','channelFilter','priorityLimit'])$(id).value='';$('sort').value='response'}
async function loadJob(id,preferred=null){await saveCurrent();await selectionQueue;clearTimeout(poll);const version=++loadVersion;page=0;focused=preferred;dirty=false;manual=false;selected=new Set();clearFilterValues();notice('');$('exportBtn').disabled=true;window.history.replaceState(null,'','/?job='+encodeURIComponent(id));await updateJob(id,version,true);if(preferred&&active?.status==='done'){page=Math.floor(Math.max(0,filtered().findIndex(r=>r.candidate_id===focused))/pageSize);renderQueue()}}
async function updateJob(id,version,initial=false){try{const job=await api('/api/jobs/'+id);if(version!==loadVersion)return;active=job;if(initial){const saved=job.export_selection;manual=saved?.mode==='manual';selected=new Set(saved?.candidate_ids||[]);selectionDirty=false;$('crs').value='unknown';$('customCrs').hidden=true}if(['queued','running'].includes(job.status)){busyState(true);$('results').hidden=true;progress(job.progress,job.message);poll=setTimeout(()=>updateJob(id,version),1000)}else{busyState(false);$('progressPanel').hidden=true;if(job.status==='done'){renderResults();$('empty').hidden=true}else{notice('Detection incomplete: '+job.message);$('results').hidden=true;$('empty').hidden=false}await refresh()}}catch(e){busyState(false);notice('Could not load detection results: '+e.message)}}
function renderStats(){const s=active.summary,reviewed=active.candidates.filter(r=>r.review_label!=='unreviewed').length;$('stats').innerHTML=[[active.candidates.length,'Merged candidates'],[(s.scored_windows||0).toLocaleString(),'Scored windows'],[s.sgy_count||active.files.length,'SGY channel files'],[reviewed,'Reviewed']].map(([v,l])=>`<div class="stat"><strong>${v}</strong><span>${l}</span></div>`).join('')}
function renderSourceFileOptions(){
 const select=$('sourceFileFilter'),previous=select.value;
 const files=new Map((active.files||[]).map(file=>[file.file_id,file])),counts=new Map(),groups=new Map();
 active.candidates.forEach(row=>{
  counts.set(row.file_id,(counts.get(row.file_id)||0)+1);
  if(!files.has(row.file_id))files.set(row.file_id,row);
 });
 [...files.values()].sort((a,b)=>String(a.profile||'').localeCompare(String(b.profile||''),undefined,{numeric:true})||
   (a.channel??Infinity)-(b.channel??Infinity)||a.name.localeCompare(b.name,undefined,{numeric:true})).forEach(file=>{
  const group=file.profile||'Other files';
  if(!groups.has(group))groups.set(group,[]);
  groups.get(group).push(file);
 });
 select.innerHTML=`<option value="">All SGY files · ${active.candidates.length} candidates</option>`+
  [...groups].map(([profile,items])=>`<optgroup label="${esc(profile)}">${items.map(file=>{
   const count=counts.get(file.file_id)||0;
   return `<option value="${esc(file.file_id)}">${esc(file.name)} · ${count?counted(count,'candidate'):'No primary candidates'}</option>`;
  }).join('')}</optgroup>`).join('');
 select.value=files.has(previous)?previous:'';
}
function renderResults(){const j=active,s=j.summary;$('results').hidden=false;$('empty').hidden=true;$('jobTitle').textContent=j.title;$('jobMeta').textContent=`${j.created} · ${s.swath_count??'—'} swaths · ${s.sgy_count??j.files.length} channel files · ${s.elapsed_seconds??'—'} s · ${(s.device||'local').toUpperCase()}`;$('bundleBtn').href='/api/jobs/'+j.id+'/bundle';$('exportBtn').disabled=!j.candidates.length;renderStats();renderSourceFileOptions();const channel=$('channelFilter').value;$('channelFilter').innerHTML='<option value="">All channels</option>'+[...new Set(j.candidates.map(r=>r.channel).filter(c=>c!==null))].sort((a,b)=>a-b).map(c=>`<option value="${c}">CH ${c}</option>`).join('');$('channelFilter').value=channel;renderWorkspace();}
function hasFilters(){return ['sourceFileFilter','labelFilter','channelFilter','priorityLimit'].some(id=>$(id).value.trim()!=='')}
function filtered(){if(!active)return [];const source=$('sourceFileFilter').value,label=$('labelFilter').value,channel=$('channelFilter').value,min=$('priorityLimit').value;let rows=active.candidates.filter(r=>(!label||r.review_label===label)&&(!channel||String(r.channel)===channel)&&(min===''||candidatePriority(r).rank<=Number(min))&&(!source||r.file_id===source));rows=[...rows];if($('sort').value==='trace')rows.sort((a,b)=>a.name.localeCompare(b.name)||a.trace_1based-b.trace_1based);else if($('sort').value==='review')rows.sort((a,b)=>(a.review_label!=='unreviewed')-(b.review_label!=='unreviewed')||b.logit-a.logit);else rows.sort((a,b)=>b.logit-a.logit);return rows}
function current(){return active?.candidates.find(r=>r.candidate_id===focused)}
function candidatePriority(candidate){
 const rows=active?.candidates||[];
 const rank=1+rows.filter(r=>r.logit>candidate.logit||(r.logit===candidate.logit&&r.candidate_id.localeCompare(candidate.candidate_id)<0)).length;
 return {rank,total:rows.length};
}
function scopeRows(scope=$('exportScope').value){if(scope==='auto')scope=manual?'selected':hasFilters()?'filtered':'all';return {scope,rows:scope==='selected'?active.candidates.filter(r=>selected.has(r.candidate_id)):scope==='filtered'?filtered():active.candidates}}
function selectionSummary(){if(!active)return;const resolved=scopeRows('auto');$('selectionCount').textContent=manual?`${selected.size} selected · Export selected points by default`:hasFilters()?`${resolved.rows.length} filtered · Export filtered points by default`:`No filters · Export all ${active.candidates.length} points by default`;$('clearSelection').disabled=!manual;$('selectFiltered').disabled=!filtered().length;const r=current();$('includePoint').checked=!!r&&manual&&selected.has(r.candidate_id);if($('exportDialog').open)updateExportSummary()}
function renderQueue(){const rows=filtered();page=Math.max(0,Math.min(page,Math.ceil(rows.length/pageSize)-1));const batch=rows.slice(page*pageSize,(page+1)*pageSize);$('queueCount').textContent=rows.length;$('reviewCount').textContent=`Showing ${rows.length} / ${active.candidates.length} · Reviewed ${active.candidates.filter(r=>r.review_label!=='unreviewed').length}`;$('candidateList').innerHTML=batch.map(r=>`<div class="queue-row ${focused===r.candidate_id?'focused':''}"><input type="checkbox" data-select="${r.candidate_id}" aria-label="Select ${r.candidate_id} for export" ${manual&&selected.has(r.candidate_id)?'checked':''}><button class="candidate-open" data-focus="${r.candidate_id}" aria-label="View ${r.candidate_id}"><div class="queue-main"><b>${r.candidate_id}</b><span class="response" title="Review rank in this run: ${candidatePriority(r).rank} / ${active.candidates.length}">#${candidatePriority(r).rank}</span></div><div class="queue-file" title="${esc(r.name)}">${esc(r.name)}</div><div class="queue-meta"><span>CH${r.channel??'—'} · Trace ${r.trace_1based}</span><span class="label-chip ${r.review_label}">${esc(labels[r.review_label]||r.review_label)}</span></div></button></div>`).join('')||'<div class="no-candidates">No matching candidates</div>';$('candidateList').querySelectorAll('[data-focus]').forEach(b=>b.onclick=()=>run(()=>focusCandidate(b.dataset.focus)));$('candidateList').querySelectorAll('[data-select]').forEach(c=>c.onchange=()=>toggleSelection(c.dataset.select,c.checked));const pages=Math.max(1,Math.ceil(rows.length/pageSize));$('pagination').innerHTML=`<button id="prevPage" aria-label="Previous page" ${page===0?'disabled':''}>‹</button><span>${page+1} / ${pages} · ${pageSize} per page</span><button id="nextPage" aria-label="Next page" ${page>=pages-1?'disabled':''}>›</button>`;$('prevPage').onclick=()=>run(()=>turnPage(-1));$('nextPage').onclick=()=>run(()=>turnPage(1));selectionSummary()}
function renderWorkspace(){const rows=filtered();if(!rows.some(r=>r.candidate_id===focused)){focused=rows[0]?.candidate_id||null;page=0}renderQueue();renderDetail()}
function renderDetail(){observationCarousel?.destroy();observationCarousel=null;const r=current();renderCandidateMap(r);$('detailEmpty').hidden=!!r;$('candidateDetail').hidden=!r;for(const id of ['reviewLabel','reviewNotes','saveReview','includePoint','prevCandidate','nextCandidate'])$(id).disabled=!r;if(!r){$('candidateDetail').innerHTML='';$('focusedId').textContent='—';$('reviewNotes').value='';$('reviewLabel').value='unreviewed';renderReviewDecision();renderReviewHistory(null);renderCandidateInfo(null);$('saveStatus').textContent='';return}const p=r.panels.find(p=>p.primary),xy=Number.isFinite(r.x)&&Number.isFinite(r.y);$('focusedId').textContent=r.candidate_id+' · CH'+(r.channel??'—');$('reviewLabel').value=r.review_label;$('reviewNotes').value=r.notes||'';renderReviewDecision();renderReviewHistory(r);$('saveStatus').textContent=r.reviewed_at?'Saved · '+reviewTimeText(r.reviewed_at):'Not yet reviewed';$('saveStatus').classList.remove('error');$('includePoint').checked=manual&&selected.has(r.candidate_id);renderCandidateInfo(r);const rows=filtered(),index=rows.findIndex(x=>x.candidate_id===focused);$('prevCandidate').disabled=index<=0;$('nextCandidate').disabled=index<0||index>=rows.length-1;const extra=r.panels.filter(p=>!p.primary).map(p=>`<h4>CH${p.channel} · AI center trace ${p.trace_1based} · Raw model value ${p.logit.toFixed(2)}</h4><img loading="lazy" src="${asset(p.file)}" alt="${r.candidate_id} CH${p.channel}" data-zoom>`).join('');$('candidateDetail').innerHTML=`<div class="bscan-heading"><div class="bscan-title"><h3>${r.candidate_id}</h3><span class="badge">CH ${r.channel??'—'}</span><span class="response"><small>Review priority</small> ${candidatePriority(r).rank} / ${active.candidates.length}</span></div><p class="bscan-subtitle">Primary candidate · ${esc(r.name)}<br>${xy?`X ${r.x.toFixed(3)} · Y ${r.y.toFixed(3)}`:'XY unavailable'} · Localized trace ${r.trace_1based}</p></div><div class="image-tools"><span>DETECTION WINDOW · ≈ 8 m</span><div><a class="text-button" href="${asset(p.file)}" download="${r.candidate_id}_CH${r.channel}.png">PNG ↓</a><button class="icon-button" id="expandImage" aria-label="Enlarge primary image"><svg><use href="#i-expand"/></svg></button></div></div><div class="candidate-image"><img src="${asset(p.file)}" alt="${r.candidate_id} Primary image; green line: AI center" data-zoom></div><div class="image-caption"><span>All ${r.samples_per_trace} vertical samples · Resampled to 128 rows for the model</span><span class="green">— AI center</span></div><div class="candidate-facts"><span>${r.supporting_observations} merged observations</span><span>Primary swath CH ${(r.supporting_channels||[]).join(', ')||'Unknown'}</span><span>${r.supporting_swaths} swaths</span><span>${r.near_known?'Near a known point':'Awaiting expert review'}</span></div><details class="context-images"><summary>Approx. 16 m context & other hit channels</summary><p>Full vertical record. Equal display heights across files do not imply equal time ranges or depths.</p><img loading="lazy" src="${asset(r.context_image)}" alt="${r.candidate_id} 16 m context" data-zoom>${extra||'<p>No other hit-channel images are available in this input. Channels that were not imported cannot be assessed.</p>'}</details>`;$('candidateDetail').querySelectorAll('[data-zoom]').forEach(img=>img.onclick=()=>zoom(img.src,img.alt));$('expandImage').onclick=()=>zoom(asset(p.file),r.candidate_id+' · CH'+r.channel+' · 8 m PNG');mountObservationCarousel(r);window.history.replaceState(null,'','/?job='+active.id+'&candidate='+encodeURIComponent(r.candidate_id));dirty=false}
let observationCarousel=null;
function renderCandidateInfo(candidate){
 const r=candidate,f=active?.files.find(file=>file.file_id===r?.file_id);
 const number=(value,digits)=>Number.isFinite(value)?(digits===undefined?value.toLocaleString():value.toFixed(digits)):'Not recorded';
 const draw=(id,rows)=>{$(id).innerHTML=rows.map(([key,value])=>{const cls=['SGY file','Primary swath','Vertical extent','Spacing source','Window-center edge exclusion'].includes(key)?' class="source-field"':'';return `<dt${cls}>${esc(key)}</dt><dd${cls}>${esc(value)}</dd>`}).join('')};
 $('candidateFileDetails').hidden=!r;
 $('candidateScoreDetails').hidden=!r;
 if(!r){draw('positionInfo',[]);draw('fileInfo',[]);draw('scoreInfo',[]);return}
 const priority=candidatePriority(r);
 draw('scoreInfo',[['Review rank in this run',`${priority.rank} / ${priority.total}`],['Raw logit',number(r.logit,2)]]);
 draw('positionInfo',[
  ['SGY file',r.name],['Primary channel',r.channel==null?'Unknown':'CH'+r.channel],['Primary swath',r.profile||'Unknown'],
  ['X',number(r.x,3)],['Y',number(r.y,3)],['AI center trace',number(r.trace_1based)],
  ['Scan-window center trace',number(r.window_center_trace_1based)],['Vertical samples',number(r.samples_per_trace)],
  ['Localizer shift (m)',number(r.localizer_shift_m,3)]
 ]);
 draw('fileInfo',f?[
  ['Total traces',number(f.traces)],['Samples per trace',number(f.samples_per_trace)],['Vertical extent',metadataText(f.vertical_extent)],
  ['Trace spacing (m)',number(f.spacing_m,5)],['Spacing source',metadataText(f.spacing_source)],
  ['Raw sample interval',number(f.sample_interval_raw)],['Time units','Unverified'],
  ['Scored windows',number(f.scored_windows)],['Above-threshold windows',number(f.threshold_hits)],
  ['Known-point exclusions',number(f.excluded_known_windows)],
  ['Window-center edge exclusion',Number.isFinite(f.edge_unscanned_est_m)?`No full-window centers within approx. ${number(f.edge_unscanned_est_m,1)} m of either end; edge data can still appear in nearby windows.`:'Not recorded']
 ]:[['Source metadata','Not available for this historical run']]);
}
let candidateLocationMap=null;
function renderCandidateMap(candidate){if(!candidateLocationMap)candidateLocationMap=new CandidateLocationMap($('candidateMap'));candidateLocationMap.setCandidate(candidate)}
function mountObservationCarousel(candidate){
 const jobId=active.id;
 observationCarousel=new ObservationCarousel($('candidateDetail'),candidate,{
  api:(suffix,body)=>api('/api/jobs/'+jobId+'/'+suffix,body),
  asset:path=>'/runs/'+jobId+'/'+path,esc,zoom
 });
}
function zoom(src,title){$('largeImage').src=src;$('imageTitle').textContent=title;$('imageDialog').showModal()}
async function focusCandidate(id){await saveCurrent();focused=id;const rows=filtered();page=Math.floor(Math.max(0,rows.findIndex(r=>r.candidate_id===id))/pageSize);renderQueue();renderDetail()}
async function turnPage(delta){await saveCurrent();page+=delta;const rows=filtered();focused=rows[page*pageSize]?.candidate_id||null;renderQueue();renderDetail();$('candidateList').scrollTop=0}
function markDirty(){if(!current())return;dirty=true;draftVersion++;$('saveStatus').textContent='Unsaved changes';$('saveStatus').classList.remove('error')}
function renderReviewDecision(){
 const r=current(),value=$('reviewLabel').value;
 document.querySelectorAll('[data-review-label]').forEach(button=>{
  const chosen=!!r&&button.dataset.reviewLabel===value;
  button.disabled=!r;button.classList.toggle('active',chosen);button.setAttribute('aria-pressed',String(chosen));
 });
 $('resetReview').disabled=!r||value==='unreviewed';
 $('reviewDecisionStatus').textContent=!r?'No candidate selected':value==='unreviewed'?'Pending review · No decision yet':value==='manhole'?'Legacy decision retained: possible manhole / verify. You can update the decision and add notes.':'Current decision: '+labels[value];
}
function chooseReview(label){
 if(!current())return;
 if($('reviewLabel').value!==label){$('reviewLabel').value=label;markDirty()}
 renderReviewDecision();run(saveCurrent);
}
function reviewTimeText(value){return String(value).replace('T',' ').replace(/\+08:00$/,' (Hong Kong time)')}
function renderReviewHistory(candidate){
 const history=candidate?.review_history||[];
 $('reviewHistory').hidden=!candidate;
 $('reviewHistory').querySelector('summary').textContent='Edit history'+(history.length?' · '+counted(history.filter(r=>r.origin!=='baseline').length,'save'):'');
 $('reviewHistoryList').innerHTML=history.length?[...history].reverse().map(entry=>`<div class="review-history-entry"><b>${esc(labels[entry.review_label]||entry.review_label)}</b><small>${esc(entry.reviewed_at?reviewTimeText(entry.reviewed_at):(entry.origin==='baseline'?'Initial state; time not recorded':'Time not recorded'))}${entry.origin==='baseline'?' · Previous state':entry.origin==='cleared_all'?' · Cleared all reviews':''}</small>${entry.notes?`<p>${esc(entry.notes)}</p>`:''}</div>`).join(''):'<p class="helper">No edit history yet. Each successfully saved change to the decision or notes will be retained.</p>';
}
async function saveCurrent(){
 if(saving)return saving;
 if(!dirty||!current())return;
 const r=current(),job=active;
 const task=(async()=>{
  try{
   $('saveReview').disabled=true;
   while(dirty){
    const version=draftVersion,payload={candidate_id:r.candidate_id,review_label:$('reviewLabel').value,notes:$('reviewNotes').value};
    $('saveStatus').textContent='Saving…';
    const result=await api('/api/jobs/'+job.id+'/review',payload);
    Object.assign(r,result.review||payload);
    dirty=version!==draftVersion;
    renderReviewHistory(r);
   }
   $('saveStatus').textContent='Saved to workspace ✓';renderStats();
   if(filtered().some(row=>row.candidate_id===focused))renderQueue();else renderWorkspace();
  }catch(e){$('saveStatus').textContent='Save failed. Please retry';$('saveStatus').classList.add('error');throw e}
  finally{$('saveReview').disabled=!current();renderReviewDecision()}
 })();
 saving=task;try{await task}finally{saving=null}
}
function persistSelection(){const jobId=active.id,version=++selectionVersion,body={mode:manual?'manual':'all',candidate_ids:[...selected]};selectionDirty=true;selectionQueue=selectionQueue.catch(()=>{}).then(()=>api('/api/jobs/'+jobId+'/selection',body)).then(()=>{if(version===selectionVersion)selectionDirty=false}).catch(e=>{notice('Export selection was not saved. Retry before exporting: '+e.message)});return selectionQueue}
function toggleSelection(id,value){manual=true;if(value)selected.add(id);else selected.delete(id);persistSelection();renderQueue()}
let clearingReviews=false,clearReviewsJob=null;
async function openClearReviews(){
 await saveCurrent();
 if(!active||active.status!=='done')return;
 clearReviewsJob=active.id;
 const changed=active.candidates.filter(r=>r.review_label!=='unreviewed'||r.notes||r.reviewer).length;
 $('clearReviewsScope').textContent=`Run: ${active.title}. ${counted(changed,'candidate')} with a current decision, note or reviewer will be reset across all ${active.candidates.length} candidates.`;
 $('clearReviewsError').textContent='';
 $('clearReviewsDialog').showModal();
}
async function clearAllReviews(){
 if(clearingReviews)return;
 if(!active||active.id!==clearReviewsJob){$('clearReviewsError').textContent='The active run changed. Close this dialog and try again.';return}
 clearingReviews=true;
 for(const id of ['confirmClearReviews','cancelClearReviews','closeClearReviews'])$(id).disabled=true;
 $('confirmClearReviews').textContent='Clearing…';$('clearReviewsError').textContent='';
 try{
  const result=await api('/api/jobs/'+clearReviewsJob+'/clear-reviews',{confirm_job_id:clearReviewsJob});
  const updates=new Map(result.reviews.map(r=>[r.candidate_id,r]));
  active.candidates.forEach(r=>{if(updates.has(r.candidate_id))Object.assign(r,updates.get(r.candidate_id))});
  dirty=false;draftVersion++;
  $('clearReviewsDialog').close();renderStats();renderWorkspace();
  notice(`Cleared current review results for ${counted(result.cleared_count,'candidate')} in this run. Edit history has been retained.`);
 }catch(error){$('clearReviewsError').textContent='Could not clear reviews: '+error.message}
 finally{
  clearingReviews=false;
  for(const id of ['confirmClearReviews','cancelClearReviews','closeClearReviews'])$(id).disabled=false;
  $('confirmClearReviews').textContent='Clear all reviews';
 }
}
$('clearAllReviews').onclick=()=>run(openClearReviews);
$('confirmClearReviews').onclick=clearAllReviews;
$('clearReviewsDialog').addEventListener('cancel',event=>{if(clearingReviews)event.preventDefault()});
async function applyFilters(){await saveCurrent();page=0;renderWorkspace()}
function updateExportSummary(){const target=scopeRows();$('exportTotal').textContent=target.rows.length;const names={all:'All candidates: no points are automatically removed based on expert decisions.',filtered:'All matching candidates across every page.',selected:'Manually selected candidates, including selections on other pages.'};$('exportScopeNote').textContent=names[target.scope];$('downloadExport').disabled=!target.rows.length;$('exportError').textContent=target.rows.length?'':'The current selection or filter contains 0 points. All candidates will not be exported automatically.'}
async function openExport(){await saveCurrent();$('exportScope').value='auto';$('exportError').textContent='';updateExportSummary();$('exportDialog').showModal()}
async function downloadExport(){const button=$('downloadExport');try{button.disabled=true;$('exportError').textContent='';await saveCurrent();await selectionQueue;if(selectionDirty){await persistSelection();if(selectionDirty)throw Error('Export selection is not yet saved. Please retry.')}const target=scopeRows(),formats=[...document.querySelectorAll('input[name=format]:checked')].map(x=>x.value);if(!target.rows.length)throw Error('No candidates to export. Adjust the scope.');if(!formats.length)throw Error('Select at least one output format.');const crs=$('crs').value,wkt=crs==='2326'?hkWkt:crs==='custom'?$('crsWkt').value.trim():'',name=crs==='2326'?'Hong Kong 1980 Grid System / EPSG:2326':crs==='custom'?$('crsName').value.trim():'';if(crs==='custom'&&(!name||!wkt))throw Error('Enter a CRS name and full WKT, or select an unspecified CRS.');const payload={mode:target.scope==='all'?'all':'ids',candidate_ids:target.rows.map(r=>r.candidate_id),formats,crs_name:name,crs_wkt:wkt,scope_description:target.scope};const res=await fetch('/api/jobs/'+active.id+'/export',{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':token},body:JSON.stringify(payload)});if(!res.ok){const data=await res.json();throw Error(data.error||'Export failed')}const blob=await res.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=/filename="([^"]+)"/.exec(res.headers.get('Content-Disposition')||'')?.[1]||'gpr_points.zip';document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);$('exportDialog').close();notice(`Exported ${target.rows.length} points in ${formats.map(f=>f.toUpperCase()).join(' / ')} format.`)}catch(e){$('exportError').textContent=e.message}finally{button.disabled=!scopeRows().rows.length}}
function openImport(){$('importError').textContent='';$('importDialog').showModal()}
document.querySelectorAll('[data-close]').forEach(b=>b.onclick=()=>$(b.dataset.close).close());$('menuBtn').onclick=()=>$('navDialog').showModal();$('navOverview').onclick=()=>$('navDialog').close();$('navImport').onclick=()=>{$('navDialog').close();openImport()};$('newBtn').onclick=openImport;$('emptyImport').onclick=openImport;$('refreshBtn').onclick=()=>run(refresh);$('runSelect').onchange=e=>{if(e.target.value)run(()=>loadJob(e.target.value))};$('drop').onclick=()=>$('fileInput').click();$('drop').onkeydown=e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();$('fileInput').click()}};$('fileInput').onchange=e=>addFiles(e.target.files);['dragenter','dragover'].forEach(type=>$('drop').addEventListener(type,e=>{e.preventDefault();$('drop').classList.add('drag')}));['dragleave','drop'].forEach(type=>$('drop').addEventListener(type,e=>{e.preventDefault();$('drop').classList.remove('drag')}));$('drop').addEventListener('drop',e=>addFiles(e.dataTransfer.files));window.addEventListener('dragover',e=>e.preventDefault());window.addEventListener('drop',e=>e.preventDefault());$('startBtn').onclick=()=>start();$('demoBtn').onclick=()=>start(true);$('useKnown').onchange=()=>{$('excludeKnown').disabled=!$('useKnown').checked};for(const id of ['sourceFileFilter','labelFilter','channelFilter','priorityLimit','sort'])$(id).onchange=()=>run(applyFilters);$('clearFilters').onclick=()=>run(async()=>{await saveCurrent();clearFilterValues();page=0;renderWorkspace()});$('selectFiltered').onclick=()=>{manual=true;selected=new Set([...selected,...filtered().map(r=>r.candidate_id)]);persistSelection();renderQueue()};$('clearSelection').onclick=()=>{manual=false;selected.clear();persistSelection();renderQueue()};$('reviewNotes').oninput=markDirty;$('reviewNotes').onchange=()=>run(saveCurrent);document.querySelectorAll('[data-review-label]').forEach(button=>button.onclick=()=>chooseReview(button.dataset.reviewLabel));$('resetReview').onclick=()=>chooseReview('unreviewed');$('saveReview').onclick=()=>run(saveCurrent);$('includePoint').onchange=e=>{if(focused)toggleSelection(focused,e.target.checked)};$('prevCandidate').onclick=()=>run(async()=>{const rows=filtered(),i=rows.findIndex(r=>r.candidate_id===focused);if(i>0)await focusCandidate(rows[i-1].candidate_id)});$('nextCandidate').onclick=()=>run(async()=>{const rows=filtered(),i=rows.findIndex(r=>r.candidate_id===focused);if(i+1<rows.length)await focusCandidate(rows[i+1].candidate_id)});$('exportBtn').onclick=()=>run(openExport);$('exportScope').onchange=updateExportSummary;$('downloadExport').onclick=downloadExport;$('crs').onchange=()=>{$('customCrs').hidden=$('crs').value!=='custom'};window.addEventListener('beforeunload',e=>{if(dirty||selectionDirty){e.preventDefault();e.returnValue=''}});
refresh().then(async()=>{const params=new URLSearchParams(window.location.search),id=params.get('job'),candidate=params.get('candidate');if(id&&/^[a-f0-9]{32}$/.test(id)){await loadJob(id,candidate)}}).catch(e=>notice('Cannot connect to the local detection service: '+e.message));
