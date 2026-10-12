import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('intel', Path(__file__).resolve().parents[1] / 'scripts/intelligence.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = m.connect(Path(self.tmp.name))
        self.run = m.plan(self.db, '2026-10-12T00:00:00Z')
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def page(self, body='Hello', updated='2026-10-11T00:00:00Z'):
        return {'articles':[{'id':1,'title':'Policy','body':body,'html_url':'https://help.whatnot.com/example','edited_at':'2026-10-10T00:00:00Z','updated_at':updated}], 'next_page':None}
    def coverage(self, source='whatnot-help', **overrides):
        item = dict(self.run['windows'][source], status='complete', evidence='Verified test fixture')
        item.update(overrides)
        return {source:item}
    def test_initial_fifteen_days(self):
        w = self.run['windows']['industry']
        self.assertEqual((m.date(w['end'])-m.date(w['start'])).days,15)
    def test_collect_does_not_advance_or_commit_snapshot(self):
        m.collect(self.db,self.run,lambda _:self.page())
        self.assertIsNone(m.get(self.db,'progress:whatnot-help'))
        self.assertIsNone(m.get(self.db,'article:1'))
    def test_finish_snapshot_and_metadata_only_change(self):
        m.collect(self.db,self.run,lambda _:self.page())
        m.finish(self.db,self.run,self.coverage(),'report')
        run2=m.plan(self.db,'2026-10-13T00:00:00Z')
        e=m.collect(self.db,run2,lambda _:self.page(updated='2026-10-12T12:00:00Z'))
        self.assertEqual(e['candidates'],[])
        e=m.collect(self.db,run2,lambda _:self.page('Changed policy'))
        self.assertEqual(e['candidates'][0]['previous']['text'],'Hello')
    def test_partial_keeps_original_start(self):
        m.finish(self.db,self.run,{'industry':{'status':'partial','evidence':'archive unavailable'}},'report')
        run2=m.plan(self.db,'2026-10-20T00:00:00Z')
        self.assertEqual(run2['windows']['industry']['start'],self.run['windows']['industry']['start'])
    def test_completed_prefix_advances_only_that_source(self):
        m.finish(self.db,self.run,self.coverage('industry',end='2026-10-01T00:00:00Z'),'report')
        self.assertEqual(m.get(self.db,'progress:industry'),'2026-10-01T00:00:00+00:00')
        self.assertIsNone(m.get(self.db,'progress:seller-experience'))
    def test_custom_range_cannot_jump_gap(self):
        run=m.plan(self.db,'2026-10-12T00:00:00Z','2026-10-10T00:00:00Z')
        m.finish(self.db,run,{'industry':dict(run['windows']['industry'],status='complete',evidence='checked')},'report')
        self.assertIsNone(m.get(self.db,'progress:industry'))
    def test_failed_collection_cannot_finish_complete(self):
        def fail(_): raise OSError('offline')
        e=m.collect(self.db,self.run,fail)
        self.assertEqual(e['status'],'partial_or_failed')
        with self.assertRaises(ValueError):
            m.finish(self.db,self.run,self.coverage(),'report')
    def test_transaction_rolls_back_invalid_finish(self):
        self.db.commit()
        with self.assertRaises(ValueError),self.db:
            m.finish(self.db,self.run,dict(self.coverage('industry'),**{'unknown':{'status':'complete'}}),'report')
        self.assertIsNone(m.get(self.db,'progress:industry'))
    def test_empty_report_rejected(self):
        with self.assertRaises(ValueError):m.finish(self.db,self.run,{},' ')
    def test_html_normalization(self):
        self.assertEqual(m.normalized('<p>A&nbsp; B</p><script>x</script><p>C</p>'),'A B C')
    def test_pagination_failure_preserves_partial_evidence(self):
        def loader(url):
            if url.endswith('100'):
                page=self.page();page['next_page']='next';return page
            raise OSError('second page failed')
        e=m.collect(self.db,self.run,loader)
        self.assertEqual(e['articles'],1)
        self.assertEqual(e['status'],'partial_or_failed')

if __name__ == '__main__':unittest.main()
