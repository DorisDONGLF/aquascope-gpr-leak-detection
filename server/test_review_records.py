"""Review revisions must preserve prior decisions and export the latest state."""
import copy
import unittest
from review_records import updated_review, cleared_reviews


class ReviewRevisions(unittest.TestCase):
    def test_changed_decision_keeps_both_saved_results_and_notes(self):
        initial = dict(review_label='unreviewed', reviewer='', notes='')
        first = updated_review(initial, dict(review_label='similar', notes='first'), '2026-10-24T19:00:00+08:00')
        second = updated_review(first, dict(review_label='different', notes='reconsidered'), '2026-10-24T19:01:00+08:00')
        self.assertEqual(second['review_label'], 'different')
        self.assertEqual(second['notes'], 'reconsidered')
        self.assertEqual([r['review_label'] for r in second['review_history']], ['unreviewed', 'similar', 'different'])
        self.assertEqual(second['review_history'][1]['notes'], 'first')
        self.assertEqual(len(first['review_history']), 2)
        self.assertNotIn('review_history', initial)

    def test_same_save_is_idempotent_and_notes_only_edit_is_logged(self):
        a = updated_review(dict(review_label='unreviewed', notes='', reviewer=''), dict(review_label='similar', notes='a'), 't1')
        self.assertEqual(updated_review(a, dict(review_label='similar', notes='a'), 't2'), a)
        b = updated_review(a, dict(review_label='similar', notes='b'), 't3')
        self.assertEqual(b['review_history'][-1]['notes'], 'b')
        self.assertEqual(b['review_history'][-2]['notes'], 'a')

    def test_legacy_manhole_and_reviewer_are_preserved_before_new_decision(self):
        old = dict(review_label='manhole', reviewer='Legacy expert', notes='historic', reviewed_at='old time')
        new = updated_review(old, dict(review_label='uncertain', notes='new note'), 't1')
        self.assertEqual(new['reviewer'], 'Legacy expert')
        self.assertEqual(new['review_history'][0], dict(old, revision=0, origin='baseline'))
        self.assertEqual(old['review_label'], 'manhole')

    def test_withdraw_to_pending_keeps_history_and_invalid_label_changes_nothing(self):
        a = updated_review(dict(review_label='similar', notes='', reviewer=''), dict(review_label='unreviewed'), 't1')
        self.assertEqual(a['review_label'], 'unreviewed')
        self.assertEqual(a['review_history'][0]['review_label'], 'similar')
        before = copy.deepcopy(a)
        with self.assertRaises(ValueError):
            updated_review(a, dict(review_label='invalid'))
        self.assertEqual(a, before)

    def test_clear_all_keeps_history_geometry_and_input_unchanged(self):
        first=updated_review(dict(candidate_id='C1',review_label='unreviewed',notes='',reviewer='',x=100,logit=12),dict(review_label='similar',notes='expert note',reviewer='Expert A'),'t1')
        rows=[first,dict(candidate_id='C2',review_label='unreviewed',notes='note only',reviewer=''),dict(candidate_id='C3',review_label='unreviewed',notes='',reviewer='')]
        before=copy.deepcopy(rows)
        updated,count=cleared_reviews(rows,'t2')
        self.assertEqual(count,2)
        self.assertEqual(rows,before)
        self.assertEqual(updated[0]['review_history'][:-1],first['review_history'])
        self.assertEqual(updated[0]['review_history'][-1]['origin'],'cleared_all')
        self.assertEqual(updated[0]['review_history'][-2]['notes'],'expert note')
        self.assertEqual((updated[0]['x'],updated[0]['logit']),(100,12))
        self.assertTrue(all(r['review_label']=='unreviewed' and not r['notes'] and not r['reviewer'] for r in updated))
        again,count=cleared_reviews(updated,'t3')
        self.assertEqual(count,0)
        self.assertEqual(again,updated)
