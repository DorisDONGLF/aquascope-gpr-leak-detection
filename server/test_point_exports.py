"""Format and HTTP integration tests; fixtures never modify real review jobs."""
import copy
import csv
import io
import json
import math
import struct
import shutil
import uuid
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from point_exports import make_export

ROOT=Path(__file__).resolve().parent


def read_dbf(raw):
    count,hlen,rlen=struct.unpack_from('<IHH',raw,4)
    fields=[]
    for pos in range(32,hlen-1,32):
        name=raw[pos:pos+11].split(b'\0')[0].decode('ascii')
        fields.append((name,raw[pos+16]))
    records=[]
    for i in range(count):
        start=hlen+i*rlen
        assert raw[start:start+1]==b' '
        pos=start+1;record={}
        for name,width in fields:
            record[name]=raw[pos:pos+width].decode('utf-8').strip();pos+=width
        assert pos==start+rlen
        records.append(record)
    assert len(raw)==hlen+count*rlen+1
    return records


class Exports(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.job=dict(id='synthetic_export_fixture',title='Synthetic export fixture',status='done',summary={},files=[],candidates=[
            dict(candidate_id=f'C{i:04d}',review_label='unreviewed',reviewer='',notes='',name=f'fixture-{i}.SGY',
                 profile='synthetic-swath',channel=(i-1)%18+1,trace_1based=100+i,window_center_trace_1based=100+i,
                 x=1000.+i,y=2000.+i,logit=10.-i*.01,signal_score=.9,samples_per_trace=128,
                 distance_to_known_m=None,near_known=False,supporting_observations=1,supporting_channels=[1],
                 supporting_swaths=1,spacing_m=.04,localizer_shift_m=0.) for i in range(1,26)])
        cls.job['candidates'][0].update(notes='中文复核备注🟢'*100,reviewer='专家甲',review_label='similar')

    def test_default_csv_is_all_and_full_text(self):
        raw,ctype,name=make_export(self.job,{'formats':['csv']})
        rows=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        self.assertEqual(len(rows),25)
        self.assertEqual(rows[0]['notes'],self.job['candidates'][0]['notes'])
        self.assertTrue(name.endswith('.csv'))

    def test_selected_ids_preserve_exact_membership_across_pages(self):
        ids=['C0001','C0013','C0025']
        raw,_,_=make_export(self.job,{'formats':['csv'],'mode':'ids','candidate_ids':ids+ids})
        self.assertEqual([r['candidate_id'] for r in csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))],ids)

    def test_explicit_empty_unknown_ids_and_unknown_formats_fail(self):
        for req in [{'mode':'ids','candidate_ids':[]},{'mode':'ids','candidate_ids':['C9999']},
                    {'mode':'bogus'},{'formats':[]},{'formats':['exe']}]:
            with self.subTest(req=req),self.assertRaises(ValueError):make_export(self.job,req)

    def test_no_xy_is_csv_only_and_never_silently_dropped(self):
        job=copy.deepcopy(self.job);job['candidates'][0]['x']=None
        self.assertTrue(make_export(job,{'formats':['csv']})[0])
        for fmt in ['shp','dxf']:
            with self.assertRaises(ValueError):make_export(job,{'formats':[fmt]})

    def test_shp_shx_dbf_geometry_text_counts_and_crs(self):
        wkt='PROJCS["Explicit test CRS"]'
        raw,_,_=make_export(self.job,{'formats':['shp','csv','dxf'],'crs_name':'Test supplied CRS','crs_wkt':wkt})
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            shp,shx=z.read('candidates.shp'),z.read('candidates.shx')
            self.assertEqual(struct.unpack_from('>i',shp,0)[0],9994)
            self.assertEqual(struct.unpack_from('>i',shp,24)[0]*2,len(shp))
            self.assertEqual(struct.unpack_from('<ii',shp,28),(1000,1))
            self.assertEqual(len(shp),100+28*25);self.assertEqual(len(shx),100+8*25)
            for i,row in enumerate(self.job['candidates']):
                self.assertEqual(struct.unpack_from('>ii',shp,100+28*i),(i+1,10))
                shape,x,y=struct.unpack_from('<idd',shp,108+28*i)
                self.assertEqual(shape,1);self.assertEqual((x,y),(row['x'],row['y']))
                self.assertEqual(struct.unpack_from('>ii',shx,100+8*i),(50+14*i,10))
            dbf=read_dbf(z.read('candidates.dbf'))
            self.assertEqual(len(dbf),25);self.assertEqual(dbf[0]['REVIEWER'],'专家甲')
            self.assertEqual(dbf[0]['REVIEW'],'similar');self.assertEqual(dbf[-1]['CAND_ID'],'C0025')
            self.assertTrue(self.job['candidates'][0]['notes'].startswith(dbf[0]['NOTES']))
            self.assertEqual(json.loads(z.read('attributes.json'))[0]['notes'],self.job['candidates'][0]['notes'])
            self.assertEqual(z.read('candidates.prj').decode(),wkt)
            self.assertEqual(z.read('candidates.cpg'),b'UTF-8')
            manifest=json.loads(z.read('manifest.json'));self.assertEqual(manifest['point_count'],25)
            self.assertFalse(manifest['coordinate_transform_applied'])
            tags=z.read('geolitix_candidates.dxf').decode('ascii').splitlines()
            entities=list(zip(tags[::2],tags[1::2]))
            self.assertEqual(entities.count(('0','POINT')),25)
            self.assertEqual(entities.count(('0','TEXT')),25)
            self.assertEqual(entities.count(('0','POLYLINE')),50)
            points=[];kind=None;coords={}
            for code,value in entities:
                if code=='0':
                    if kind=='POINT':points.append(coords)
                    kind=value;coords={}
                else:coords[code]=value
            for row,point in zip(self.job['candidates'],points):
                self.assertAlmostEqual(float(point['10']),row['x'],places=8)
                self.assertAlmostEqual(float(point['20']),row['y'],places=8)
                self.assertEqual(point['30'],'0')

    def test_unknown_crs_has_no_false_prj(self):
        raw,_,_=make_export(self.job,{'formats':['shp']})
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            self.assertNotIn('candidates.prj',z.namelist())
            self.assertIsNone(json.loads(z.read('manifest.json'))['crs_wkt'])


class HTTPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.app=app;cls.temp=ROOT/('test_export_tmp_'+uuid.uuid4().hex);cls.temp.mkdir();app.STORE=cls.temp
        cls.job=copy.deepcopy(Exports.job);cls.job['id']='a'*32;app.JOBS={cls.job['id']:cls.job}
        cls.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}/api/jobs/{cls.job["id"]}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join()
        assert cls.temp.resolve().parent==ROOT.resolve() and cls.temp.name.startswith('test_export_tmp_')
        shutil.rmtree(cls.temp)

    def post(self,suffix,data,token=True):
        req=urllib.request.Request(self.base+suffix,data=json.dumps(data).encode(),headers={
            'Content-Type':'application/json','X-App-Token':self.app.TOKEN if token else 'wrong'})
        return urllib.request.urlopen(req)

    def test_export_actual_http_default_and_subset(self):
        with self.post('/export',{'formats':['csv']}) as res:
            self.assertIn('.csv',res.headers['Content-Disposition'])
            self.assertEqual(len(list(csv.DictReader(io.StringIO(res.read().decode('utf-8-sig'))))),25)
        with self.post('/export',{'formats':['shp'],'mode':'ids','candidate_ids':['C0001','C0025']}) as res:
            with zipfile.ZipFile(io.BytesIO(res.read())) as z:
                self.assertEqual(len(z.read('candidates.shp')),156)
                self.assertEqual(json.loads(z.read('manifest.json'))['candidate_ids'],['C0001','C0025'])

    def test_review_changes_are_persisted_and_export_uses_latest_result(self):
        for label,note in [('similar','first saved'),('different','changed decision')]:
            with self.post('/review',dict(candidate_id='C0003',review_label=label,notes=note)) as response:
                result=json.loads(response.read())
                self.assertEqual(result['review']['review_label'],label)
        disk=json.loads((self.temp/self.job['id']/'job.json').read_text(encoding='utf-8'))
        row=next(r for r in disk['candidates'] if r['candidate_id']=='C0003')
        self.assertEqual([r['review_label'] for r in row['review_history'][-2:]],['similar','different'])
        with self.post('/export',dict(formats=['csv'],mode='ids',candidate_ids=['C0003'])) as response:
            exported=list(csv.DictReader(io.StringIO(response.read().decode('utf-8-sig'))))[0]
            self.assertEqual(exported['review_label'],'different')
            self.assertEqual(exported['notes'],'changed decision')

    def test_review_disk_failure_does_not_replace_current_state(self):
        from unittest.mock import patch
        before=copy.deepcopy(self.job['candidates'][3])
        with patch.object(self.app,'write_job',side_effect=OSError('test write failure')):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.post('/review',dict(candidate_id='C0004',review_label='different',notes='unsaved'))
        self.assertEqual(error.exception.code,500)
        self.assertEqual(self.job['candidates'][3],before)

    def test_expert_review_and_manual_selection_persist_to_disk(self):
        with self.post('/review',dict(candidate_id='C0002',review_label='uncertain',reviewer='测试专家',notes='待回查')) as res:self.assertTrue(json.load(res)['saved'])
        with self.post('/selection',dict(mode='manual',candidate_ids=['C0002','C0025'])) as res:self.assertTrue(json.load(res)['saved'])
        saved=json.loads((self.app.STORE/self.job['id']/'job.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['candidates'][1]['review_label'],'uncertain')
        self.assertEqual(saved['candidates'][1]['notes'],'待回查')
        self.assertEqual(saved['export_selection'],dict(mode='manual',candidate_ids=['C0002','C0025']))
        with self.post('/selection',dict(mode='manual',candidate_ids=[])) as res:self.assertTrue(json.load(res)['saved'])
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/export',dict(mode='ids',candidate_ids=[],formats=['csv']))
        self.assertEqual(cm.exception.code,400)

    def test_write_requires_local_token(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:self.post('/selection',{},token=False)
        self.assertEqual(cm.exception.code,403)

    def test_clear_all_is_confirmed_atomic_and_isolated_to_one_run(self):
        from unittest.mock import patch
        isolated=copy.deepcopy(self.job)
        isolated['id']='b'*32
        isolated['candidates'][0].update(review_label='similar',notes='keep in history',reviewer='Expert A')
        self.app.JOBS[isolated['id']]=isolated
        original_base=self.base
        self.base=original_base.rsplit('/',1)[0]+'/'+isolated['id']
        original=copy.deepcopy(isolated)
        other_run=copy.deepcopy(self.job)
        try:
            for payload,token in [({},True),({'confirm_job_id':isolated['id']},False)]:
                with self.assertRaises(urllib.error.HTTPError):self.post('/clear-reviews',payload,token=token)
                self.assertEqual(isolated,original)
            with patch.object(self.app,'write_job',side_effect=OSError('test bulk write failure')):
                with self.assertRaises(urllib.error.HTTPError) as error:self.post('/clear-reviews',{'confirm_job_id':isolated['id']})
            self.assertEqual(error.exception.code,500)
            self.assertEqual(isolated,original)
            with self.post('/clear-reviews',{'confirm_job_id':isolated['id']}) as response:
                result=json.load(response)
            self.assertGreaterEqual(result['cleared_count'],1)
            self.assertEqual(self.job,other_run)
            self.assertEqual(isolated.get('export_selection'),original.get('export_selection'))
            disk=json.loads((self.temp/isolated['id']/'job.json').read_text(encoding='utf-8'))
            for old,row in zip(original['candidates'],disk['candidates']):
                self.assertEqual(row['review_label'],'unreviewed')
                self.assertEqual((row['notes'],row['reviewer']),('',''))
                for key in old.keys()-{'review_label','notes','reviewer','reviewed_at','review_history'}:self.assertEqual(row[key],old[key])
            self.assertEqual(disk['candidates'][0]['review_history'][-2]['notes'],'keep in history')
            self.assertEqual(disk['candidates'][0]['review_history'][-1]['origin'],'cleared_all')
            with self.post('/clear-reviews',{'confirm_job_id':isolated['id']}) as response:self.assertEqual(json.load(response)['cleared_count'],0)
        finally:
            self.base=original_base
            self.app.JOBS.pop(isolated['id'],None)


if __name__=='__main__':unittest.main(verbosity=2)
