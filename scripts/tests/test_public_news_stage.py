import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_public_news import select_records, merge, project, encode, sha

class NewsStageTests(unittest.TestCase):
    def setUp(self):
        self.e={"event_id":"synthetic-event","revision":1,"publication_allowed":True,"verification_status":"PASS_PRIMARY_TEXT_AND_RELEASE_TIME","data_quality":"verified_primary_text"}
        self.c={"audience":"private_public_news_candidate","public_release_enabled":False,"batch_id":"test","record_count":1,"records":[self.e]}
        self.a={"batch_id":"test","candidate_sha256":"c","review_sha256":"r","base_public_sha256":"b","reviewer":"dashboard_independent","records":[{"event_id":"synthetic-event","revision":1,"direct_source_verified":True,"rights_verified":True,"summary_reviewed":True}]}
    def select(self,a):return select_records(self.c,a,"c","r","b")
    def test_no_approval(self):self.assertEqual(self.select(None),[])
    def test_valid_approval(self):self.assertEqual(self.select(self.a),[self.e])
    def test_wrong_hash(self):
        self.a["candidate_sha256"]="wrong"
        with self.assertRaises(ValueError):self.select(self.a)
    def test_wrong_reviewer(self):
        self.a["reviewer"]="media"
        with self.assertRaises(ValueError):self.select(self.a)
    def test_source_not_verified(self):
        self.a["records"][0]["direct_source_verified"]=False
        with self.assertRaises(ValueError):self.select(self.a)
    def test_unapproved_candidate(self):
        self.e["publication_allowed"]=False
        with self.assertRaises(ValueError):self.select(self.a)
    def test_wrong_revision(self):
        self.a["records"][0]["revision"]=2
        with self.assertRaises(ValueError):self.select(self.a)
    def test_duplicate_candidate(self):
        self.c["records"].append(self.e);self.c["record_count"]=2
        with self.assertRaises(ValueError):self.select(self.a)
    def test_append_idempotent(self):
        a={"eventId":"one","revision":1,"url":"https://example.org/a"};b={"eventId":"two","revision":1,"url":"https://example.org/b"}
        base={"records":[a]}
        merged,n=merge(base,[b]);self.assertEqual((merged["records"],n),([a,b],1));self.assertEqual(base["records"],[a]);self.assertEqual(merge(merged,[b]),(merged,0))
    def test_rollback_and_conflict(self):
        a={"eventId":"one","revision":2,"url":"https://example.org/a"};base={"records":[a]}
        with self.assertRaises(ValueError):merge(base,[{**a,"revision":1}])
        with self.assertRaises(ValueError):merge(base,[{**a,"title":"changed"}])
    def test_duplicate_url(self):
        a={"eventId":"one","revision":1,"url":"https://example.org/a"}
        with self.assertRaises(ValueError):merge({"records":[a]},[{**a,"eventId":"two","url":a["url"]+"/"}])
    def test_serialization(self):self.assertEqual(sha(encode({"records":[]})),sha(encode({"records":[]})))
if __name__=="__main__":unittest.main()
