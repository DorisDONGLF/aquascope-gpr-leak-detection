"""Portable point exports. Raw SGY XY is preserved; no depth or CRS is inferred."""
import csv
import datetime
import io
import json
import math
import struct
import zipfile

FIELDS = ['candidate_id','review_label','reviewer','notes','name','profile','channel',
          'trace_1based','window_center_trace_1based','x','y','distance_to_known_m',
          'near_known','logit','signal_score','samples_per_trace','supporting_observations',
          'supporting_channels','supporting_swaths','spacing_m','localizer_shift_m','reviewed_at']


def select_rows(job, mode='all', ids=None):
    if job.get('status') != 'done':
        raise ValueError('Export is available after detection completes.')
    rows = job['candidates']
    if mode == 'ids':
        if not isinstance(ids, list) or not ids or not all(isinstance(x, str) for x in ids):
            raise ValueError('The current selection or filter is empty. Adjust it before exporting.')
        wanted = set(ids)
        if wanted - {r['candidate_id'] for r in rows}:
            raise ValueError('The selection contains candidate IDs that do not exist.')
        rows = [r for r in rows if r['candidate_id'] in wanted]
    elif mode != 'all':
        raise ValueError('Invalid export scope.')
    if not rows:
        raise ValueError('No candidates to export.')
    return rows


def csv_bytes(rows):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=FIELDS)
    writer.writeheader()
    for row in rows:
        vals = {k: row.get(k, '') for k in FIELDS}
        vals['supporting_channels'] = ','.join(map(str, row.get('supporting_channels', [])))
        writer.writerow(vals)
    return ('\ufeff' + out.getvalue()).encode('utf-8')


def require_xy(rows):
    missing = [r['candidate_id'] for r in rows if any(
        isinstance(r.get(k), bool) or not isinstance(r.get(k), (int, float)) or
        not math.isfinite(r[k]) for k in ('x','y'))]
    if missing:
        raise ValueError(f'{len(missing)} candidates have no valid XY (e.g. {", ".join(missing[:5])}). Use CSV or filter to candidates with coordinates.')


def dxf_bytes(rows):
    require_xy(rows)
    tags = []
    def pairs(*args):
        tags.extend(str(x) for x in args)
    pairs(0,'SECTION',2,'HEADER',9,'$ACADVER',1,'AC1009',9,'$PDMODE',70,3,
          9,'$PDSIZE',40,.4,0,'ENDSEC',0,'SECTION',2,'TABLES',0,'TABLE',2,'LTYPE',70,1,
          0,'LTYPE',2,'CONTINUOUS',70,0,3,'Solid line',72,65,73,0,40,0,0,'ENDTAB',
          0,'TABLE',2,'LAYER',70,3)
    for name, color in [('0',7),('AI_CANDIDATES',1),('AI_LABELS',7)]:
        pairs(0,'LAYER',2,name,70,0,62,color,6,'CONTINUOUS')
    pairs(0,'ENDTAB',0,'TABLE',2,'STYLE',70,1,0,'STYLE',2,'STANDARD',70,0,40,0,41,1,
          50,0,71,0,42,1,3,'txt',4,'',0,'ENDTAB',0,'ENDSEC',0,'SECTION',2,'ENTITIES')
    for r in rows:
        x,y = r['x'],r['y']
        # IDs are produced by the engine; ASCII is required for this R12 interchange.
        cid = r['candidate_id']
        if not cid.isascii() or any(c in cid for c in '\r\n'):
            raise ValueError('DXF candidate IDs must be single-line ASCII.')
        pairs(0,'POINT',8,'AI_CANDIDATES',10,f'{x:.9f}',20,f'{y:.9f}',30,0)
        for a,b in [((x-.35,y),(x+.35,y)),((x,y-.35),(x,y+.35))]:
            pairs(0,'POLYLINE',8,'AI_CANDIDATES',66,1,10,0,20,0,30,0,70,0)
            for vx,vy in [a,b]:
                pairs(0,'VERTEX',8,'AI_CANDIDATES',10,f'{vx:.9f}',20,f'{vy:.9f}',30,0)
            pairs(0,'SEQEND',8,'AI_CANDIDATES')
        pairs(0,'TEXT',8,'AI_LABELS',10,f'{x+.5:.9f}',20,f'{y+.5:.9f}',30,0,
              40,.6,1,cid,50,0,7,'STANDARD')
    pairs(0,'ENDSEC',0,'EOF')
    return ('\r\n'.join(tags)+'\r\n').encode('ascii')


# DBF names are <=10 ASCII characters. Full text, without DBF byte limits,
# is also included in attributes.json in every SHP archive.
DBF = [('CAND_ID','candidate_id','C',24,0),('REVIEW','review_label','C',24,0),
       ('REVIEWER','reviewer','C',100,0),('NOTES','notes','C',254,0),
       ('SGY_NAME','name','C',254,0),('PROFILE','profile','C',254,0),
       ('CHANNEL','channel','N',8,0),('TRACE','trace_1based','N',12,0),
       ('X','x','N',24,9),('Y','y','N',24,9),('LOGIT','logit','N',20,8),
       ('SCORE','signal_score','N',20,15),('SUPPORT','supporting_observations','N',10,0),
       ('CHANNELS','supporting_channels','C',254,0),('SWATHS','supporting_swaths','N',10,0),
       ('NSAMPLES','samples_per_trace','N',10,0),('REVIEWED','reviewed_at','C',40,0)]


def dbf_bytes(rows):
    today = datetime.date.today()
    header_len, record_len = 33 + 32*len(DBF), 1 + sum(f[3] for f in DBF)
    out = io.BytesIO()
    out.write(struct.pack('<BBBBIHH20x',3,today.year-1900,today.month,today.day,
                          len(rows),header_len,record_len))
    for name,key,kind,width,decimals in DBF:
        out.write(struct.pack('<11sc4xBB14x',name.encode('ascii'),kind.encode('ascii'),width,decimals))
    out.write(b'\r')
    for row in rows:
        out.write(b' ')
        for name,key,kind,width,decimals in DBF:
            value = row.get(key)
            if kind == 'N':
                if value is None:
                    data = b''
                else:
                    if not isinstance(value, (int,float)) or not math.isfinite(value):
                        raise ValueError(f'{row["candidate_id"]}: {key} is not a finite number.')
                    data = (f'{value:.{decimals}f}' if decimals else str(int(value))).encode('ascii')
                if len(data)>width:
                    raise ValueError(f'DBF field {key} exceeds the supported numeric width. Use CSV.')
                out.write(data.rjust(width,b' '))
            else:
                text = ','.join(map(str,value)) if isinstance(value,list) else str(value or '')
                data = text.replace('\x00','').encode('utf-8')[:width].decode('utf-8','ignore').encode('utf-8')
                out.write(data.ljust(width,b' '))
    out.write(b'\x1a')
    return out.getvalue()


def shp_files(rows):
    require_xy(rows)
    xs,ys = [r['x'] for r in rows],[r['y'] for r in rows]
    bounds = (min(xs),min(ys),max(xs),max(ys),0.,0.,0.,0.)
    def header(words):
        return struct.pack('>7i',9994,0,0,0,0,0,words)+struct.pack('<2i8d',1000,1,*bounds)
    shp,shx = io.BytesIO(),io.BytesIO()
    shp.write(header(50+14*len(rows)));shx.write(header(50+4*len(rows)))
    for i,r in enumerate(rows):
        shp.write(struct.pack('>2i',i+1,10));shp.write(struct.pack('<idd',1,r['x'],r['y']))
        shx.write(struct.pack('>2i',50+14*i,10))
    return {'candidates.shp':shp.getvalue(),'candidates.shx':shx.getvalue(),
            'candidates.dbf':dbf_bytes(rows),'candidates.cpg':b'UTF-8',
            'field_mapping.json':json.dumps({f[0]:f[1] for f in DBF},indent=2).encode('utf-8'),
            'attributes.json':json.dumps(rows,ensure_ascii=False,allow_nan=False,indent=2).encode('utf-8')}


def make_export(job, request):
    formats = request.get('formats', ['csv'])
    if not isinstance(formats,list) or not formats or any(f not in ('csv','dxf','shp') for f in formats):
        raise ValueError('Select CSV, Geolitix DXF or Shapefile.')
    formats = list(dict.fromkeys(formats))
    rows = select_rows(job, request.get('mode','all'),request.get('candidate_ids'))
    crs = str(request.get('crs_name','')).strip()[:200]
    wkt = str(request.get('crs_wkt','')).strip()
    if wkt and (len(wkt)>20000 or not wkt.startswith(('PROJCS[','GEOGCS[','PROJCRS[','GEOGCRS['))):
        raise ValueError('Invalid CRS WKT. Supply a complete projected or geographic CRS WKT.')
    stem = f'gpr_{job["id"][:8]}_{len(rows)}_points'
    if formats == ['csv']:
        return csv_bytes(rows),'text/csv; charset=utf-8',stem+'.csv'
    files = {}
    if 'csv' in formats:
        files['candidates.csv'] = csv_bytes(rows)
    if 'dxf' in formats:
        files['geolitix_candidates.dxf'] = dxf_bytes(rows)
    if 'shp' in formats:
        files.update(shp_files(rows))
        if wkt:
            files['candidates.prj'] = wkt.encode('utf-8')
    manifest = dict(job_id=job['id'],title=job['title'],point_count=len(rows),
                    candidate_ids=[r['candidate_id'] for r in rows],formats=formats,
                    exported_at=datetime.datetime.now().isoformat(timespec='seconds'),
                    model=job.get('summary',{}).get('model'),
                    checkpoint_sha256=job.get('summary',{}).get('checkpoint_sha256'),
                    source_xy_preserved=True,coordinate_transform_applied=False,
                    crs_name=crs or 'Unspecified source XY',crs_wkt=wkt or None,
                    depth_predicted=False,scope=request.get('scope_description',request.get('mode','all')))
    files['manifest.json'] = json.dumps(manifest,ensure_ascii=False,indent=2).encode('utf-8')
    files['README.txt'] = (
        f'GPR Review Studio — {len(rows)} points\nJob: {job["title"]}\n'
        f'CRS: {crs or "Unspecified source XY; confirm the source/project CRS before importing."}\n'
        'Original SGY XY is preserved. No coordinate transformation is applied.\n'
        'SHP is 2D POINT geometry. Keep .shp, .shx, .dbf, .cpg and (if provided) .prj together.\n'
        'A .prj is included only when a CRS WKT is explicitly supplied.\n'
        'DBF text is UTF-8 and may be shortened to its field byte limit; attributes.json keeps full text.\n'
        'Geolitix: import geolitix_candidates.dxf using DXF Base Maps and set the matching source CRS.\n'
        'https://docs.geolitix.com/layers/dxf.html\n'
        'DXF contains POINT, POLYLINE crosses and candidate-ID TEXT. Z=0 is a 2D placeholder, not depth.\n'
        'Cross size is only a symbol, not an anomaly boundary. No vertical target position is predicted.\n'
        'Model logit/score is for similarity ranking, not calibrated leak probability.\n'
        'Review labels describe expert assessment; unreviewed candidates are not confirmed leaks.\n'
        'manifest.json records exactly which candidates are in this export.\n').encode('utf-8')
    archive = io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():
            z.writestr(name,content)
    return archive.getvalue(),'application/zip',stem+'.zip'
