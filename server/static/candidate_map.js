'use strict';

class CandidateLocationMap {
  constructor(root){
    this.root=root;this.point=null;this.candidate=null;this.timer=null;this.requestVersion=0;
    this.satellite=true;
    try{this.satellite=localStorage.getItem('gpr-map-mode')!=='roadmap'}catch(_){}
    root.innerHTML=`<div class="candidate-map-heading"><div><span class="eyebrow">GOOGLE MAPS</span><h4 id="mapCandidateTitle">Candidate center</h4></div><div class="candidate-map-actions"><div class="map-mode"><button type="button" data-map-mode="roadmap">Map</button><button type="button" data-map-mode="satellite">Satellite</button></div><a id="openGoogleMap" class="text-button" target="_blank" rel="noopener noreferrer">Open in Google Maps ↗</a></div></div><div class="candidate-map-view"><iframe id="candidateMapFrame" title="Google Maps location of the current primary candidate" loading="lazy" referrerpolicy="strict-origin-when-cross-origin" allowfullscreen hidden></iframe><div class="map-placeholder" id="mapPlaceholder" role="status">Preparing candidate location…</div></div><div class="candidate-map-caption"><span id="mapCoordinates"></span><span>Hong Kong 1980 Grid → WGS84 · Marker: primary candidate center</span></div><div id="mapNetworkNote" class="map-network-note" hidden>Map loading is slow. Use “Open in Google Maps” to view this location.</div>`;
    this.frame=root.querySelector('iframe');this.placeholder=root.querySelector('#mapPlaceholder');
    root.querySelectorAll('[data-map-mode]').forEach(b=>b.onclick=()=>{
      this.satellite=b.dataset.mapMode==='satellite';
      try{localStorage.setItem('gpr-map-mode',this.satellite?'satellite':'roadmap')}catch(_){}
      this.loadMap();
    });
  }

  setCandidate(candidate){
    this.root.hidden=!candidate;
    if(!candidate){clearTimeout(this.timer);this.point=null;return}
    this.candidate=candidate;
    this.root.querySelector('#mapCandidateTitle').textContent='Candidate location · '+candidate.candidate_id;
    this.root.querySelector('#mapNetworkNote').hidden=true;
    try{
      this.point=GprGeo.toWgs84(candidate.x,candidate.y);
      this.root.querySelector('#mapCoordinates').textContent=`${this.point.latitude.toFixed(7)}° N, ${this.point.longitude.toFixed(7)}° E`;
      const link=this.root.querySelector('#openGoogleMap');link.href=GprGeo.googleMapsUrl(this.point);link.hidden=false;
      this.loadMap();
    }catch(error){
      clearTimeout(this.timer);this.requestVersion++;this.point=null;this.frame.hidden=true;this.frame.onload=null;this.frame.removeAttribute('src');
      this.placeholder.hidden=false;this.placeholder.textContent=error.message;
      this.root.querySelector('#mapCoordinates').textContent='Latitude/longitude unavailable';
      this.root.querySelector('#openGoogleMap').hidden=true;
    }
  }

  loadMap(){
    if(!this.point)return;
    this.root.querySelectorAll('[data-map-mode]').forEach(b=>{
      const active=b.dataset.mapMode===(this.satellite?'satellite':'roadmap');
      b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));
    });
    const url=GprGeo.googleEmbedUrl(this.point,this.satellite);
    if(this.frame.getAttribute('src')===url)return;
    clearTimeout(this.timer);const version=++this.requestVersion;
    this.placeholder.hidden=false;this.placeholder.textContent='Loading Google '+(this.satellite?'satellite imagery…':'map…');
    this.frame.hidden=false;this.root.querySelector('#mapNetworkNote').hidden=true;
    this.frame.onload=()=>{if(version===this.requestVersion){clearTimeout(this.timer);this.placeholder.hidden=true}};
    this.frame.onerror=()=>{if(version===this.requestVersion){clearTimeout(this.timer);this.placeholder.hidden=true;this.root.querySelector('#mapNetworkNote').hidden=false}};
    this.frame.src=url;
    this.timer=setTimeout(()=>{if(version===this.requestVersion){this.placeholder.hidden=true;this.root.querySelector('#mapNetworkNote').hidden=false}},15000);
  }
}
