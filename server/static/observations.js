'use strict';

// Left means the lower channel/previous item, including a physical leftward
// drag. Lower swath browsers have independent state and never replace the top.
function wireComparisonStage(stage,image,previous,next,step,zoom){
  image.draggable=false;image.onclick=null;stage.tabIndex=0;
  previous.onclick=e=>{e.stopPropagation();step(-1)};
  next.onclick=e=>{e.stopPropagation();step(1)};
  stage.addEventListener('keydown',e=>{
    if(e.key==='ArrowLeft'||e.key==='ArrowRight'){
      e.preventDefault();e.stopPropagation();step(e.key==='ArrowLeft'?-1:1);
    }
  });
  let start=null,suppressClick=false;
  stage.addEventListener('pointerdown',e=>{
    if(e.target.closest('button')||(e.pointerType==='mouse'&&e.button!==0))return;
    start={x:e.clientX,y:e.clientY,id:e.pointerId};stage.setPointerCapture(e.pointerId);
  });
  stage.addEventListener('pointerup',e=>{
    if(!start||start.id!==e.pointerId)return;
    const dx=e.clientX-start.x,dy=e.clientY-start.y;start=null;
    if(Math.abs(dx)>45&&Math.abs(dx)>Math.abs(dy)*1.4){suppressClick=true;step(dx<0?-1:1)}
  });
  stage.addEventListener('pointercancel',()=>{start=null});
  stage.addEventListener('click',e=>{
    if(suppressClick){suppressClick=false;e.preventDefault();e.stopImmediatePropagation()}
  },true);
  stage.addEventListener('click',e=>{if(!e.target.closest('button'))zoom(image.src,image.alt)});
}

function comparisonArrows(stage,previousLabel,nextLabel){
  const previous=document.createElement('button'),next=document.createElement('button');
  previous.className='observation-arrow previous';next.className='observation-arrow next';
  previous.textContent='‹';next.textContent='›';
  previous.setAttribute('aria-label',previousLabel);next.setAttribute('aria-label',nextLabel);
  previous.disabled=next.disabled=true;stage.append(previous,next);
  return [previous,next];
}

function revealComparisonChip(strip,index){
  const chip=strip.children[index];if(!chip)return;
  const a=chip.getBoundingClientRect(),b=strip.getBoundingClientRect();
  if(strip.classList.contains('channel-strip')||a.left<b.left||a.right>b.right)strip.scrollTo({left:strip.scrollLeft+a.left-b.left-(b.width-a.width)/2,behavior:'smooth'});
}

class ObservationCarousel {
  constructor(host,candidate,options){
    this.host=host;this.candidate=candidate;this.options=options;
    this.rows=[];this.index=0;this.destroyed=false;this.timer=null;
    this.stage=host.querySelector('.candidate-image');this.image=this.stage.querySelector('img');
    this.png=host.querySelector('.image-tools a');this.context=host.querySelector('.context-images img');
    this.stage.classList.add('observation-stage');
    this.stage.setAttribute('aria-label','Primary swath channels: left for lower channel numbers, right for higher channel numbers');
    this.caption=document.createElement('div');this.caption.className='observation-current';
    this.stage.before(this.caption);
    [this.prev,this.next]=comparisonArrows(this.stage,'Previous channel','Next channel');
    wireComparisonStage(this.stage,this.image,this.prev,this.next,
      delta=>this.show(this.index+delta,true),options.zoom);
    this.panel=document.createElement('section');this.panel.className='observation-browser';
    this.panel.innerHTML=`<div class="observation-heading"><b>Primary swath · Browse by channel</b><span class="observation-counter"></span></div><div class="observation-status" role="status"></div><div class="observation-progress"><i></i></div><div class="observation-strip channel-strip" aria-label="Channels in this swath, ordered by number and aligned to the primary candidate XY"></div><p class="observation-help">Drag left / ← for a lower channel; right / → for a higher channel. The upper viewer stays on the primary swath and shows merged-hit channels only; other channels are skipped.</p>`;
    host.querySelector('.candidate-facts').after(this.panel);
    this.status=this.panel.querySelector('.observation-status');this.counter=this.panel.querySelector('.observation-counter');
    this.strip=this.panel.querySelector('.observation-strip');this.progress=this.panel.querySelector('.observation-progress');
    this.mainPicker=document.createElement('label');this.mainPicker.className='swath-observation-picker';
    this.mainPicker.hidden=true;this.mainPicker.innerHTML='Merged observations in this channel<select aria-label="Merged observations in the current primary-swath channel"></select>';
    this.strip.after(this.mainPicker);
    this.mainPicker.querySelector('select').onchange=e=>this.show(this.index,false,Number(e.target.value));
    this.lower=document.createElement('section');this.lower.className='swath-comparisons';
    host.querySelector('.context-images').after(this.lower);
    this.caption.textContent=`Primary observation · CH${candidate.channel??'—'} · ${candidate.profile}`;
    host.querySelector('#expandImage').onclick=()=>options.zoom(this.image.src,this.image.alt);
    if(candidate.observation_gallery_version===4&&candidate.channel_gallery?.length){
      this.ready({rows:candidate.observation_gallery,main_rows:candidate.channel_gallery,
        groups:candidate.swath_gallery_groups||[],warnings:candidate.channel_gallery_warnings||[]});
    }else{
      this.status.textContent='Aligning channels to the primary candidate coordinates; the initial model image is shown temporarily…';
      this.timer=setTimeout(()=>this.request(true),250);
    }
  }

  destroy(){this.destroyed=true;clearTimeout(this.timer)}

  async request(start=false){
    try{
      const state=await this.options.api(start?'observations':'observations?candidate_id='+encodeURIComponent(this.candidate.candidate_id),
        start?{candidate_id:this.candidate.candidate_id}:undefined);
      if(this.destroyed)return;
      if(state.status==='done'){this.ready(state);return}
      if(state.status==='error')throw Error(state.message);
      this.status.textContent=state.message||'Preparing channel images';
      this.progress.firstElementChild.style.width=Math.round((state.progress||0)*100)+'%';
      this.timer=setTimeout(()=>this.request(false),1000);
    }catch(error){
      if(this.destroyed)return;
      this.progress.hidden=true;this.status.textContent=error.message+' ';
      const retry=document.createElement('button');retry.className='text-button';retry.textContent='Retry loading';
      retry.onclick=()=>{this.progress.hidden=false;this.request(true)};this.status.append(retry);this.status.classList.add('error');
    }
  }

  distance(row){
    if(Number.isFinite(row.alignment_distance_m))return row.alignment_distance_m.toFixed(3)+' m';
    if(!Number.isFinite(row.distance_to_primary_m))return 'Distance unavailable';
    return (row.distance_kind==='along_track_estimate'?'Approx. along track: ':'')+row.distance_to_primary_m.toFixed(3)+' m';
  }

  geometryText(row){
    if(row.alignment_version!==4)return '';
    const esc=this.options.esc;
    const offset=row.ai_offset_from_alignment_m;
    const ai=Number.isFinite(offset)?(Math.abs(offset)<1e-6?'AI center coincides with the alignment line':`AI center is ${Math.abs(offset).toFixed(2)} m ${offset<0?'left':'right'} of the alignment line${row.ai_inside_window?'':' (outside the current 8 m window)'}`):Number.isFinite(row.logit)?'AI center lies on a different discontinuous track segment and is outside this view':'No merged AI hit in this channel; alignment reference only';
    const warning=row.alignment_ambiguous?'⚠ Multiple track matches are possible. The nearest segment is shown; check the alignment.':'';
    const coverage=row.coverage_fraction<.999?` · Valid coverage ${(row.coverage_fraction*100).toFixed(0)}%; missing coverage is blank`:'';
    return `<div class="alignment-caption"><p>Nearest recorded trace ${row.alignment_trace_1based} · Track distance from primary point: ${this.distance(row)} · Relative track angle ${row.relative_track_angle_degrees.toFixed(1)}°${row.display_reversed?' · Display reversed to align left/right orientation':''}${coverage}</p><p>${ai}</p>${warning?`<p class="alignment-warning">${warning}</p>`:''}<details><summary>Spatial alignment details</summary><p>Fixed target XY: ${row.alignment_target_x.toFixed(3)}, ${row.alignment_target_y.toFixed(3)}<br>Track projection XY: ${row.alignment_x.toFixed(3)}, ${row.alignment_y.toFixed(3)}<br>Nearest recorded trace XY: ${row.alignment_sample_x.toFixed(3)}, ${row.alignment_sample_y.toFixed(3)} · Recorded-point distance ${row.alignment_sample_distance_m.toFixed(3)} m<br>8 m / 16 m valid coverage: ${(row.coverage_fraction*100).toFixed(0)}% / ${(row.context_coverage_fraction*100).toFixed(0)}%<br>Based on recorded SGY coordinates. Horizontal distance follows each track; nearby tracks do not have identical recorded XY.${row.alignment_ambiguous?'<br>Possible matching traces: '+esc(row.alignment_choices.map(c=>c.trace_1based.toFixed(1)+'('+c.distance_m.toFixed(3)+' m)').join(', ')):''}</p></details></div>`;
  }

  rankText(row){
    if(!Number.isFinite(row.logit))return 'Unscored reference image';
    const rows=this.rankRows||[],rank=1+rows.filter(r=>r.logit>row.logit).length;
    return `Merged-observation rank ${rank} / ${rows.length}`;
  }

  ready(gallery){
    this.rankRows=(gallery.rows||[]).filter(r=>Number.isFinite(r.logit));
    this.rows=gallery.main_rows.filter(row=>row.view_kind==='merged').map(row=>({
      ...row,aligned_alternatives:(row.aligned_alternatives||[row]).filter(view=>view.view_kind==='merged')
    }));
    this.index=Math.max(0,this.rows.findIndex(r=>r.primary));
    Object.assign(this.candidate,{observation_gallery:gallery.rows,channel_gallery:gallery.main_rows,
      swath_gallery_groups:gallery.groups,channel_gallery_warnings:gallery.warnings,observation_gallery_version:4});
    this.progress.hidden=true;this.status.classList.remove('error');
    this.status.textContent=`${this.candidate.profile} · ${this.rows.length} merged-hit channels · Only observations merged into this candidate are shown`;
    if(gallery.warnings?.length)this.status.textContent+=' · '+gallery.warnings.join(' ');
    this.strip.innerHTML=this.rows.map((r,i)=>`<button data-channel-view="${i}" aria-label="Primary swath CH${r.channel??'Unknown'}" title="${this.options.esc(r.name)}"><span><b>CH${r.channel??'—'}</b><em>${this.distance(r)}</em></span><small>${r.primary?'Primary observation':r.view_kind==='merged'?'Merged hit':'Reference · Not a merged hit'}</small><small>Aligned trace ${r.alignment_trace_1based??r.trace_1based}</small></button>`).join('');
    this.strip.querySelectorAll('[data-channel-view]').forEach(b=>b.onclick=()=>this.show(Number(b.dataset.channelView),true));
    const contextBlock=this.host.querySelector('.context-images');
    contextBlock.querySelector('summary').textContent='Approx. 16 m context for the current upper channel';
    contextBlock.querySelectorAll('h4,img').forEach(el=>{if(el!==this.context)el.hidden=true});
    this.renderLowerGroups(gallery.groups||[]);
    this.show(this.index,true);
  }

  show(index,userAction=false,variantIndex=0){
    if(index<0||index>=this.rows.length||this.destroyed)return;
    this.index=index;const base=this.rows[index],variants=base.aligned_alternatives||[base],row=variants[variantIndex],reference=row.view_kind==='reference';
    const label=row.primary?'Primary observation':reference?'Reference · Not a merged hit':'Merged observation';
    this.caption.innerHTML=`<div><b>Primary swath · CH${row.channel??'—'}</b><span class="badge ${reference?'reference-badge':''}">${label}</span><strong>Track distance from primary point: ${this.distance(row)}</strong></div><p>${this.options.esc(row.name)}${Number.isFinite(row.logit)?' · AI trace '+row.trace_1based+' · '+this.rankText(row):' · Alignment reference; no additional detection'}</p>${this.geometryText(row)}`;
    this.caption.title=Number.isFinite(row.logit)?'Raw model logit: '+row.logit.toFixed(2):'';
    this.image.src=this.options.asset(row.file);
    this.image.alt=`${this.candidate.candidate_id} Primary swath CH${row.channel??'—'} · ${label} · ${row.name}`;
    this.context.src=this.options.asset(row.context_image);this.context.alt=`Upper CH${row.channel??'—'} · ${row.profile} · 16 m context`;
    this.png.href=this.options.asset(row.file);this.png.download=`${this.candidate.candidate_id}_main_CH${row.channel??'unknown'}.png`;
    this.host.querySelector('.image-caption > span').textContent=`All ${row.samples_per_trace} vertical samples · Fixed primary XY · Horizontal −4 to +4 m`;
    const legend=this.host.querySelector('.image-caption > span:last-child');
    legend.textContent=reference?'— Blue: fixed primary point projected onto this track':'Blue: fixed primary point projected onto this track · Dashed green: AI center';
    legend.classList.remove('green');legend.classList.add('reference-line');
    this.mainPicker.hidden=variants.length<2;
    const versionSelect=this.mainPicker.querySelector('select');
    versionSelect.innerHTML=variants.map((v,i)=>`<option value="${i}">Observation ${i+1} · AI trace ${v.trace_1based} · ${this.rankText(v)}</option>`).join('');
    versionSelect.value=String(variantIndex);
    this.counter.textContent=`CH${row.channel??'—'} · ${index+1} / ${this.rows.length}`;
    this.prev.disabled=index===0;this.next.disabled=index===this.rows.length-1;
    this.prev.title=index>0?'CH'+this.rows[index-1].channel:'First available channel';
    this.next.title=index+1<this.rows.length?'CH'+this.rows[index+1].channel:'Last available channel';
    this.strip.querySelectorAll('[data-channel-view]').forEach((b,i)=>{b.classList.toggle('active',i===index);b.setAttribute('aria-pressed',String(i===index))});
    if(userAction)revealComparisonChip(this.strip,index);
  }

  renderLowerGroups(groups){
    const esc=this.options.esc;
    groups=groups.map(group=>{
      const rows=group.rows.filter(row=>row.view_kind==='merged');
      const distances=rows.map(row=>row.alignment_distance_m).filter(Number.isFinite);
      return {...group,rows,nearest_distance_m:distances.length?Math.min(...distances):null};
    }).filter(group=>group.rows.length).sort((a,b)=>Number(a.primary_swath)-Number(b.primary_swath)||
      (a.nearest_distance_m??Infinity)-(b.nearest_distance_m??Infinity)||a.profile.localeCompare(b.profile));
    const other=groups.filter(g=>!g.primary_swath),count=other.reduce((sum,g)=>sum+g.rows.filter(r=>r.view_kind==='merged').length,0);
    this.lower.innerHTML=`<div class="lower-swath-heading"><h4>Other swaths · Fixed primary-point comparison</h4><p>${other.length} associated nearby swaths · ${count} merged observations. Only merged-hit channels are shown. Swaths are ordered by the nearest visible hit-track distance; channels are ordered numerically, starting with the nearest hit channel. Blue marks the fixed primary point projected onto the track; dashed green marks the selected observation's AI center. Browsing here does not replace the upper image.</p><p>Merged-observation ranks compare all ${this.rankRows.length} merged observations for this candidate. Switching observations in the same channel keeps the aligned window fixed and changes the AI center marker. Scores come from the scan windows; aligned windows are not rescored.</p></div>`;
    if(!groups.length){this.lower.innerHTML+='<p class="observation-help">No other merged observations are available for this candidate.</p>';return}
    groups.forEach((group,groupIndex)=>{
      // Sort at display time too, so existing cached galleries get the new order.
      // Keep every merged observation, including multiple observations in one CH.
      const distanceKey=row=>Number.isFinite(row.alignment_distance_m)?row.alignment_distance_m:Infinity;
      const channelKey=row=>Number.isFinite(row.channel)?row.channel:Infinity;
      const ordered=[...group.rows].sort((a,b)=>channelKey(a)-channelKey(b)||distanceKey(a)-distanceKey(b)||(a.distance_to_primary_m??Infinity)-(b.distance_to_primary_m??Infinity)||a.trace_1based-b.trace_1based||String(a.observation_id).localeCompare(String(b.observation_id)));
      const byChannel=new Map();
      ordered.forEach(row=>{
        const key=Number.isFinite(row.channel)?'CH'+row.channel:'file:'+(row.file_id||row.name);
        if(!byChannel.has(key))byChannel.set(key,{channel:row.channel,rows:[]});
        byChannel.get(key).rows.push(row);
      });
      const channels=[...byChannel.values()];
      if(!channels.length)return;
      const section=document.createElement('section');section.className='swath-comparison';
      section.dataset.profile=group.profile;
      section.innerHTML=`<div class="swath-comparison-heading"><div><span class="eyebrow">${group.primary_swath?'PRIMARY SWATH · EXTRA OBSERVATIONS':'NEARBY SWATH '+(groupIndex+1)}</span><h4>${esc(group.profile)}</h4></div><span class="badge">${channels.length} channels · ${group.rows.filter(r=>r.view_kind==='merged').length} merged observations</span></div><p class="swath-group-distance">Nearest track in this swath: ${Number.isFinite(group.nearest_distance_m)?group.nearest_distance_m.toFixed(3)+' m':'Unknown'} · Browse by channel number</p><div class="swath-view-current"></div><div class="observation-stage swath-image-stage" aria-label="Swath channels: left for lower channel numbers, right for higher channel numbers"><img loading="lazy" alt="Merged observation from a nearby swath"></div><div class="swath-view-tools"><span class="swath-view-counter"></span><a class="text-button" download>PNG ↓</a></div><div class="observation-strip swath-chip-strip channel-strip" aria-label="Channels in this swath, ordered numerically"></div><label class="swath-observation-picker" hidden>Merged observations in this channel<select aria-label="Merged observations in this channel"></select></label><p class="observation-help">Drag left / ← for a lower channel; right / → for a higher channel. Only channels with hits merged into this candidate are shown; other channels are skipped.</p><details class="swath-view-context"><summary>Approx. 16 m context for this observation</summary><img loading="lazy" alt="16 m context from a nearby swath"></details>`;
      this.lower.append(section);
      const image=section.querySelector('.swath-image-stage img'),stage=section.querySelector('.swath-image-stage');
      const context=section.querySelector('.swath-view-context img'),png=section.querySelector('.swath-view-tools a');
      const caption=section.querySelector('.swath-view-current'),counter=section.querySelector('.swath-view-counter');
      const strip=section.querySelector('.swath-chip-strip');
      const picker=section.querySelector('.swath-observation-picker'),observationSelect=picker.querySelector('select');
      const [previous,next]=comparisonArrows(stage,'Previous channel in this swath','Next channel in this swath');
      strip.innerHTML=channels.map((channel,i)=>{const r=channel.rows[0],hits=channel.rows.filter(v=>v.view_kind==='merged').length;return `<button data-swath-view="${i}" title="${esc(r.name)} · ${hits} merged observations"><span><b>CH${channel.channel??'—'}</b><em>${this.distance(r)}</em></span><small>${hits?hits+' merged observations':'Reference channel · No merged hit'}</small><small>Aligned trace ${r.alignment_trace_1based}</small></button>`}).join('');
      let index=0;
      const show=(nextIndex,user=false,observationIndex=0)=>{
        if(nextIndex<0||nextIndex>=channels.length)return;
        index=nextIndex;const channel=channels[index],row=channel.rows[observationIndex];
        caption.innerHTML=`<b>CH${row.channel??'—'}</b><span>${row.view_kind==='merged'?'AI trace '+row.trace_1based+' · '+this.rankText(row):'Reference channel · No additional detection'} · ${row.samples_per_trace} vertical samples</span>${this.geometryText(row)}`;
        caption.title=Number.isFinite(row.logit)?'Raw model logit: '+row.logit.toFixed(2):'Unscored spatial alignment reference';
        image.src=this.options.asset(row.file);image.alt=`Nearby swath ${group.profile} · CH${row.channel??'—'} · ${this.distance(row)}`;
        context.src=this.options.asset(row.context_image);context.alt=`${group.profile} · CH${row.channel??'—'} · 16 m context`;
        png.href=this.options.asset(row.file);png.download=`${this.candidate.candidate_id}_${row.observation_id}_CH${row.channel??'unknown'}.png`;
        counter.textContent=`CH${row.channel??'—'} · ${index+1} / ${channels.length} channels · ${row.view_kind==='merged'?'Observation '+(observationIndex+1)+' / '+channel.rows.length:'Reference image'} · Blue: fixed alignment / dashed green: AI center`;
        previous.disabled=index===0;next.disabled=index===channels.length-1;
        previous.title=index>0?'CH'+channels[index-1].channel:'First available channel';
        next.title=index+1<channels.length?'CH'+channels[index+1].channel:'Last available channel';
        picker.hidden=channel.rows.length<2;
        observationSelect.innerHTML=channel.rows.map((r,i)=>`<option value="${i}">Observation ${i+1} · Trace ${r.trace_1based} · ${this.distance(r)} · ${this.rankText(r)}</option>`).join('');
        observationSelect.value=String(observationIndex);
        strip.querySelectorAll('[data-swath-view]').forEach((b,i)=>{b.classList.toggle('active',i===index);b.setAttribute('aria-pressed',String(i===index))});
        if(user)revealComparisonChip(strip,index);
      };
      strip.querySelectorAll('[data-swath-view]').forEach(b=>b.onclick=()=>show(Number(b.dataset.swathView),true));
      observationSelect.onchange=()=>show(index,false,Number(observationSelect.value));
      wireComparisonStage(stage,image,previous,next,delta=>show(index+delta,true),this.options.zoom);
      const nearestIndex=channels.reduce((best,channel,i)=>distanceKey(channel.rows[0])<distanceKey(channels[best].rows[0])?i:best,0);
      show(nearestIndex,true);
    });
  }
}
