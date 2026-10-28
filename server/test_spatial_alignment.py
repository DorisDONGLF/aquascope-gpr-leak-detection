import copy
import contextlib
import shutil
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
from spatial_alignment import track_geometry, project_to_track, physical_window, build_aligned_comparison


@contextlib.contextmanager
def alignment_tempdir():
    workspace=Path(__file__).resolve().parent
    root=workspace/('test_alignment_tmp_'+uuid.uuid4().hex)
    root.mkdir()
    try:
        yield root
    finally:
        assert root.resolve().parent==workspace and root.name.startswith('test_alignment_tmp_')
        shutil.rmtree(root)


class SpatialAlignment(unittest.TestCase):
    def test_nearest_track_projection_keeps_actual_lateral_separation(self):
        track=track_geometry([0,2,4],[1,1,1])
        p=project_to_track(track,(1,0))
        np.testing.assert_allclose(p['point'],[1,1])
        self.assertEqual(p['distance_m'],1)
        self.assertAlmostEqual(p['centre_s'],1)
        self.assertFalse(p['ambiguous'])

    def test_irregular_spacing_uses_metres_and_retains_all_vertical_samples(self):
        x=np.array([0,1,2,4,5,6,8,9,10],float)
        samples=np.column_stack((x,x*2,x*3))
        track=track_geometry(x,np.zeros(len(x)))
        p=project_to_track(track,(5,0))
        view,coverage=physical_window(samples,track,p,4,width=9)
        self.assertEqual(view.shape,(3,9))
        np.testing.assert_allclose(view[0],np.arange(1,10))
        self.assertEqual(coverage,1)

    def test_reverse_acquisition_displays_the_same_left_to_right_ground_direction(self):
        x=np.arange(21,dtype=float)
        forward=track_geometry(x,np.zeros(21))
        backward=track_geometry(x[::-1],np.zeros(21))
        a,_=physical_window(x[:,None],forward,project_to_track(forward,(10,0)),4,width=9)
        b,_=physical_window(x[::-1,None],backward,project_to_track(backward,(10,0)),4,reverse=True,width=9)
        np.testing.assert_allclose(a,b)

    def test_missing_coverage_is_blank_and_never_cloned_or_bridged_across_a_jump(self):
        x=np.array([0,1,2,100,101],float)
        track=track_geometry(x,np.zeros(5))
        p=project_to_track(track,(2,0))
        view,coverage=physical_window(x[:,None],track,p,4,width=9)
        self.assertTrue(np.isnan(view[0,0]))
        self.assertTrue(np.isnan(view[0,-1]))
        self.assertLess(coverage,1)
        self.assertLessEqual(np.nanmax(view),2)

    def test_crossing_trajectory_is_flagged_unless_primary_trace_independently_resolves_it(self):
        track=track_geometry([-2,2,3,2,-2],[-2,2,2,-2,2])
        p=project_to_track(track,(0,0))
        self.assertTrue(p['ambiguous'])
        self.assertGreater(len(p['alternatives']),1)
        primary=project_to_track(track,(0,0),preferred_trace=.5)
        self.assertFalse(primary['ambiguous'])
        self.assertTrue(primary['primary_trace_resolved'])

    def test_invalid_track_does_not_fall_back_to_equal_trace_numbers(self):
        for x,y in [([0,0,0],[0,0,0]),([0,np.nan,2],[0,0,0])]:
            with self.assertRaises(ValueError):track_geometry(x,y)

    def test_gallery_preserves_detection_centres_scores_and_every_member(self):
        with alignment_tempdir() as directory:
            root=Path(directory)
            self.assertEqual(root.resolve().parent,Path(__file__).resolve().parent)
            for fid in ['main','other','reference']:(root/fid).write_bytes(b'x')
            meta=[dict(file_id='main',name='a-1.SGY',profile='a',channel=1,traces=21,samples_per_trace=3),
                  dict(file_id='other',name='b-2.SGY',profile='b',channel=2,traces=21,samples_per_trace=3),
                  dict(file_id='reference',name='b-3.SGY',profile='b',channel=3,traces=21,samples_per_trace=3)]
            rows=[]
            for fid,oid,trace,score,primary in [('main','O1',11,20,True),('main','O2',13,12,False),('other','O3',15,10,False)]:
                m=next(m for m in meta if m['file_id']==fid)
                rows.append(dict(m,observation_id=oid,trace_1based=trace,window_center_trace_1based=trace-1,
                    x=float(trace-1),y=0 if fid=='main' else 1,logit=score,primary=primary,
                    distance_to_primary_m=abs(trace-11),file=oid+'.png',context_image=oid+'_context.png'))
            candidate=dict(rows[0],candidate_id='C1',x=10.,y=0.)
            before=copy.deepcopy((candidate,rows))
            job=dict(input_files=[dict(id=m['file_id'],path=str(root/m['file_id']),size=1) for m in meta],files=meta,options={})
            def fake_read(path,fallback):
                x=np.arange(21,dtype=float)
                y=np.full(21,{'main':0,'other':1,'reference':2}[Path(path).name],dtype=float)
                return np.tile(x[:,None],(1,3)),x,y,1.,dict(coordinate_available=True,samples_per_trace=3)
            with patch('engine.read_sgy',side_effect=fake_read):
                result=build_aligned_comparison(job,candidate,rows,root,lambda *args:None)
            self.assertEqual((candidate,rows),before)
            self.assertEqual(len(result['main_rows'][0]['aligned_alternatives']),2)
            self.assertEqual(len(result['groups'][0]['rows']),2)
            other=next(r for r in result['groups'][0]['rows'] if r['view_kind']=='merged')
            self.assertEqual(other['trace_1based'],15)
            self.assertEqual(other['logit'],10)
            self.assertEqual(other['alignment_trace_1based'],11)
            self.assertEqual(other['alignment_distance_m'],1)
            self.assertEqual(other['ai_offset_from_alignment_m'],4)
            reference=next(r for r in result['groups'][0]['rows'] if r['view_kind']=='reference')
            self.assertIsNone(reference['logit'])
            self.assertEqual(reference['alignment_distance_m'],2)
            im=Image.open(root/other['file'])
            self.assertEqual(im.getpixel((550,200)),(112,185,242))
            self.assertEqual(im.size,(1100,470))
            self.assertFalse(result['alignment_audit']['missing_observation_ids'])


if __name__=='__main__':unittest.main()
