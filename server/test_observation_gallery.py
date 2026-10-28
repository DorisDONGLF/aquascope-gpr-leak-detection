"""Spatial ordering and strict historical association checks, independent of GPU."""
import copy
import unittest
from observation_gallery import distance_order,group_peaks,reconcile_members,group_remaining_observations


def observation(fid,x,y,score=10,trace=100,window=101,profile='swath-A',channel=1):
    return dict(file_id=fid,x=x,y=y,logit=score,trace_1based=trace,
                window_center_trace_1based=window,profile=profile,channel=channel,
                spacing_m=.04,samples_per_trace=286,name=f'{profile}-{channel}.SGY')


class ObservationGalleryTests(unittest.TestCase):
    def test_lower_groups_swath_first_then_nearest_channel_keep_every_merged_hit(self):
        primary=observation('p',0,0,20,profile='main',channel=5)
        same=observation('a',.5,0,19,profile='main',channel=4)
        same_extra=observation('a',2,0,10,trace=150,profile='main',channel=4)
        near_swath_near=observation('b',.1,0,9,profile='near',channel=18)
        near_swath_far=observation('c',3,0,8,profile='near',channel=1)
        far_swath=observation('d',.2,0,7,profile='far',channel=2)
        rows=distance_order(primary,[primary,same,same_extra,near_swath_near,near_swath_far,far_swath])
        main_rows=[dict(r,source_observation_id=r['observation_id']) for r in rows
                   if r['file_id']=='p' or (r['file_id']=='a' and r['trace_1based']==100)]
        groups=group_remaining_observations(primary,rows,main_rows)
        self.assertEqual([g['profile'] for g in groups],['near','far','main'])
        self.assertEqual([r['channel'] for r in groups[0]['rows']],[18,1])
        self.assertEqual(groups[0]['nearest_distance_m'],.1)
        original={r['observation_id'] for r in rows}
        shown=[r['source_observation_id'] for r in main_rows]+[r['observation_id'] for g in groups for r in g['rows']]
        self.assertEqual(set(shown),original)
        self.assertEqual(len(shown),len(original))

    def test_distance_is_xy_to_fixed_primary_not_channel_or_response_order(self):
        primary=observation('a',100,200,20,channel=9)
        far=observation('b',103,200,19,profile='swath-B',channel=1)
        near=observation('c',100,.1+200,8,profile='swath-C',channel=18)
        rows=distance_order(primary,[far,primary,near])
        self.assertEqual([r['file_id'] for r in rows],['a','c','b'])
        self.assertEqual([r['distance_kind'] for r in rows],['xy']*3)
        self.assertAlmostEqual(rows[1]['distance_to_primary_m'],.1)
        self.assertEqual(rows[-1]['distance_to_primary_m'],3)
        self.assertTrue(rows[0]['primary'])
        self.assertEqual(primary['x'],100)

    def test_equal_distances_keep_primary_first_and_keep_all_observations(self):
        p=observation('a',0,0,20,channel=9)
        # Multiple observations in a single channel must NOT silently disappear.
        same=observation('a',0,0,10,trace=101,channel=9)
        rows=distance_order(p,[same,p])
        self.assertTrue(rows[0]['primary']);self.assertEqual(len(rows),2)
        self.assertEqual([r['observation_id'] for r in rows],['O0001','O0002'])

    def test_missing_xy_is_an_explicit_along_trace_estimate_or_unknown(self):
        p=observation('a',None,None,20)
        other=observation('b',None,None,10)
        same=observation('a',None,None,9,trace=110)
        rows=distance_order(p,[other,same,p])
        self.assertEqual(rows[1]['distance_kind'],'along_track_estimate')
        self.assertAlmostEqual(rows[1]['distance_to_primary_m'],.4)
        self.assertEqual(rows[2]['distance_kind'],'unknown')
        self.assertIsNone(rows[2]['distance_to_primary_m'])

    def test_global_merge_members_preserve_cross_swath_and_strict_radius(self):
        a=observation('a',0,0,20)
        b=observation('b',6,0,19,profile='swath-B')
        between=observation('c',3.5,0,10,profile='swath-C')
        boundary=observation('d',0,4,9)
        groups=group_peaks([a,b,between,boundary],4)
        self.assertEqual(len(groups),3)
        self.assertEqual([r['file_id'] for r in groups[1]['members']],['b','c'])
        self.assertEqual(groups[2]['file_id'],'d')

    def test_reconciliation_retains_candidate_identity_and_rejects_partial_recovery(self):
        group=group_peaks([observation('a',0,0,20),observation('b',1,0,10,profile='swath-B')],4)[0]
        candidate={k:v for k,v in group.items() if k!='members'}
        candidate.update(candidate_id='C0099',supporting_observations=2,supporting_swaths=2,
                         review_label='similar',reviewer='Expert',notes='Keep this review')
        reconciled=reconcile_members([candidate],[group])
        self.assertEqual(reconciled[0]['candidate_id'],'C0099')
        self.assertEqual(reconciled[0]['notes'],'Keep this review')
        bad=copy.deepcopy(group);bad['members'].pop()
        with self.assertRaises(ValueError):reconcile_members([candidate],[bad])
        shifted=copy.deepcopy(group);shifted['trace_1based']+=1
        with self.assertRaises(ValueError):reconcile_members([candidate],[shifted])
        with self.assertRaises(ValueError):reconcile_members([candidate],[])


if __name__=='__main__':unittest.main(verbosity=2)
