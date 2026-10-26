/* Source XY: easting, northing in Hong Kong 1980 Grid, confirmed by the user.
 * EPSG operation 1825 uses coordinate-frame rotations. Proj4's +towgs84 uses
 * position-vector rotations, so the rotation signs below are reversed.
 * Verified against LandsD's published API manual example (2017), p.9.
 */
(function(factory){
  if(typeof module==='object'&&module.exports)module.exports=factory(require('./vendor/proj4.js'));
  else window.GprGeo=factory(window.proj4);
})(function(proj4){
  'use strict';
  const definition='+proj=tmerc +lat_0=22.3121333333333 +lon_0=114.178555555556 +k=1 +x_0=836694.05 +y_0=819069.8 +ellps=intl +towgs84=-162.619,-276.959,-161.764,0.067753,-2.243648,-1.158828,-1.094246 +units=m +no_defs';
  proj4.defs('EPSG:2326',definition);
  function toWgs84(x,y){
    if(!Number.isFinite(x)||!Number.isFinite(y))throw Error('This candidate has no reliable XY coordinates for map positioning.');
    // EPSG:2326 area of use. A wrong unit/CRS must not silently plot overseas.
    if(x<790000||x>875000||y<795000||y>855000)throw Error('XY is outside the Hong Kong 1980 Grid area of use. Check the source CRS.');
    const [longitude,latitude]=proj4('EPSG:2326','EPSG:4326',[x,y]);
    if(!Number.isFinite(latitude)||!Number.isFinite(longitude)||Math.abs(latitude)>90||Math.abs(longitude)>180)throw Error('Latitude/longitude conversion failed.');
    return {latitude,longitude};
  }
  function googleMapsUrl(point){
    return 'https://www.google.com/maps/search/?api=1&query='+encodeURIComponent(point.latitude.toFixed(7)+','+point.longitude.toFixed(7));
  }
  function googleEmbedUrl(point,satellite=true){
    const q=encodeURIComponent(point.latitude.toFixed(7)+','+point.longitude.toFixed(7));
    return 'https://maps.google.com/maps?output=embed&hl=en&q='+q+'&z=19&t='+(satellite?'k':'m');
  }
  return {sourceCrs:'EPSG:2326',definition,toWgs84,googleMapsUrl,googleEmbedUrl};
});
