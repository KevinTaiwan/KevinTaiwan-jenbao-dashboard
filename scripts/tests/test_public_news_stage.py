import sys, unittest, json, tempfile
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_public_news import select_records, merge, project, encode, sha, embedded_json, stage, verify_transaction, MANIFEST

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

    def test_embedded_script_safe(self):
        doc={"title":"</script><script>alert(1)</script>&\u2028\u2029"}
        encoded=embedded_json(doc)
        self.assertNotIn("<",encoded);self.assertNotIn(">",encoded);self.assertNotIn("&",encoded)
        self.assertEqual(json.loads(encoded),doc)

class FullStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.repo=self.root/"repo";self.pub=self.repo/"public";self.pub.mkdir(parents=True)
        (self.repo/".github/workflows").mkdir(parents=True)
        # Deliberately synthetic isolated sessions/events; never deploy these.
        self.base_record={"eventId":"synthetic-old","revision":1,"date":"2026-01-05","kind":"fiscal_policy","title":"Synthetic old","summary":"Fixture only","source":"US Treasury","url":"https://home.treasury.gov/news/press-releases/fixture-old","publishedAt":"2026-01-05T08:30:00-05:00","eventAt":None,"effectiveAt":None,"reactionDates":{"tw":"2026-01-06","us":"2026-01-05"},"publicationAllowed":True,"quality":"verified_public"}
        base={"schemaVersion":2,"audience":"public-market","status":"approved_public_release","records":[self.base_record]}
        self.base_raw=encode(base);self.base_sha=sha(self.base_raw)
        (self.pub/"public-news-events.json").write_bytes(self.base_raw)
        (self.pub/"index.html").write_text("<script>const TECH_APPROVED_NEWS_SNAPSHOT="+embedded_json(base)+";</script>",encoding="utf-8")
        (self.repo/".github/workflows/pages.yml").write_text("'--approved-sha256', '"+self.base_sha+"'")
        days=["2026-01-05","2026-01-06","2026-01-07"]
        (self.pub/"index-ohlc-history.json").write_bytes(encode({"series":{"taiex":{"rows":[{"date":d,"close":100,"source":"TWSE"} for d in days]},"sp500":{"rows":[{"date":d,"close":100} for d in days]}}}))
        (self.pub/"market-center-history.json").write_bytes(encode({"IXIC":[]}))
        e={"event_id":"synthetic-new","revision":1,"publication_allowed":True,"verification_status":"PASS_PRIMARY_TEXT_AND_RELEASE_TIME","data_quality":"verified_primary_text","published_at":"2026-01-06T08:30:00-05:00","source_url":"https://home.treasury.gov/news/press-releases/fixture-new","source_name":"US Treasury","category":"fiscal_policy","title":"Fixture </script>","summary":"Synthetic only","event_at":None,"effective_at":None,"private_internal_note":"NOT_PUBLIC"}
        self.c={"project_id":"MEDIA-DASHBOARD-R10.1","schema_version":"1.0","audience":"private_public_news_candidate","public_release_enabled":False,"batch_id":"fixture","record_count":1,"records":[e]}
        self.cpath=self.root/"candidate.json";self.cpath.write_bytes(encode(self.c))
        self.review={"project_id":self.c["project_id"],"batch_id":"fixture","candidate_sha256":sha(self.cpath.read_bytes()),"candidate_count":1,"dashboard_public_sha256":self.base_sha,"public_release_enabled":False}
        self.rpath=self.root/"review.json";self.rpath.write_bytes(encode(self.review))
        self.approval={"batch_id":"fixture","candidate_sha256":sha(self.cpath.read_bytes()),"review_sha256":sha(self.rpath.read_bytes()),"base_public_sha256":self.base_sha,"reviewer":"dashboard_independent","records":[{"event_id":"synthetic-new","revision":1,"direct_source_verified":True,"rights_verified":True,"summary_reviewed":True}]}
        self.apath=self.root/"approval.json";self.apath.write_bytes(encode(self.approval))
        self.out=self.root/"out"
        self.args=SimpleNamespace(repo=str(self.repo),candidate=str(self.cpath),candidate_sha256=sha(self.cpath.read_bytes()),review=str(self.rpath),review_sha256=sha(self.rpath.read_bytes()),base_sha256=self.base_sha,out=str(self.out),approval=None,approval_sha256=None)
    def approve(self):
        self.args.approval=str(self.apath);self.args.approval_sha256=sha(self.apath.read_bytes())
    def test_real_stage_no_approval_no_write(self):
        r=stage(self.args);self.assertEqual(r["status"],"HOLD_NO_APPROVAL");self.assertFalse(self.out.exists());self.assertEqual((self.pub/"public-news-events.json").read_bytes(),self.base_raw)
    def test_real_stage_isolated_success(self):
        self.approve();r=stage(self.args);self.assertEqual(r["status"],"STAGED_NOT_PUBLISHED")
        raw=(self.out/"public-news-events.json").read_bytes();d=json.loads(raw)
        self.assertEqual(r["public_sha256"],sha(raw));self.assertEqual(d["records"][0],self.base_record)
        self.assertEqual(d["records"][1]["reactionDates"],{"tw":"2026-01-07","us":"2026-01-06"})
        self.assertNotIn(b"NOT_PUBLIC",raw);self.assertNotIn(b"private_internal_note",raw)
        html=(self.out/"index.html").read_text();self.assertEqual(html.count("</script>"),1)
        embedded,_=json.JSONDecoder().raw_decode(html.split("const TECH_APPROVED_NEWS_SNAPSHOT=",1)[1]);self.assertEqual(embedded,d)
        self.assertIn(r["public_sha256"],(self.out/"pages.yml").read_text())
        self.assertEqual((self.pub/"public-news-events.json").read_bytes(),self.base_raw)
    def test_real_stage_review_base_mismatch(self):
        self.review["dashboard_public_sha256"]="0"*64;self.rpath.write_bytes(encode(self.review));self.args.review_sha256=sha(self.rpath.read_bytes())
        with self.assertRaises(ValueError):stage(self.args)
        self.assertFalse(self.out.exists())
    def test_real_stage_approval_digest_mismatch(self):
        self.approve();self.args.approval_sha256="0"*64
        with self.assertRaises(ValueError):stage(self.args)
        self.assertFalse(self.out.exists())
    def test_real_stage_approval_requires_hash(self):
        self.args.approval=str(self.apath)
        with self.assertRaises(ValueError):stage(self.args)
        self.assertFalse(self.out.exists())
    def test_real_stage_private_path_rejected(self):
        self.args.candidate=str(self.pub/"private.json")
        with self.assertRaises(ValueError):stage(self.args)
        self.assertFalse(self.out.exists())


    def test_transaction_repeat(self):
        self.approve();a=stage(self.args);b=stage(self.args)
        self.assertEqual(a["stage_mode"],"CREATED")
        self.assertEqual(b["stage_mode"],"REUSED")
        self.assertEqual(a["transaction_id"],b["transaction_id"])
    def test_transaction_recover_matching_partial(self):
        self.approve();a=stage(self.args)
        (self.out/MANIFEST).unlink();(self.out/"pages.yml").unlink()
        b=stage(self.args)
        self.assertEqual(b["stage_mode"],"RECOVERED")
        self.assertEqual(a["transaction_id"],b["transaction_id"])
    def test_transaction_conflict_preserved(self):
        self.approve();self.out.mkdir();p=self.out/"index.html";p.write_bytes(b"unknown bytes")
        with self.assertRaises(ValueError):stage(self.args)
        self.assertEqual(p.read_bytes(),b"unknown bytes")
        self.assertFalse((self.out/MANIFEST).exists())
    def test_transaction_completed_missing_file(self):
        self.approve();stage(self.args);(self.out/"pages.yml").unlink()
        with self.assertRaises(ValueError):stage(self.args)
        self.assertFalse((self.out/"pages.yml").exists())
    def test_transaction_stale_html(self):
        self.approve();stage(self.args);m=json.loads((self.out/MANIFEST).read_bytes())
        (self.pub/"index.html").write_text("new front end")
        with self.assertRaises(ValueError):verify_transaction(self.repo,self.out,m)
    def test_transaction_tampered_output(self):
        self.approve();stage(self.args);m=json.loads((self.out/MANIFEST).read_bytes())
        (self.out/"pages.yml").write_text("tampered")
        with self.assertRaises(ValueError):verify_transaction(self.repo,self.out,m)
    def test_transaction_extra_file(self):
        self.approve();stage(self.args);m=json.loads((self.out/MANIFEST).read_bytes())
        (self.out/"private-candidate.json").write_text("private")
        with self.assertRaises(ValueError):verify_transaction(self.repo,self.out,m)
    def test_transaction_manifest_private(self):
        self.approve();a=stage(self.args);m=json.loads((self.out/MANIFEST).read_bytes())
        self.assertEqual(m["audience"],"private_release_transaction")
        self.assertEqual(a["transaction_id"],m["transaction_id"])
        self.assertTrue(verify_transaction(self.repo,self.out,m))
        self.assertEqual(set(m["output_sha256"]),{"public-news-events.json","index.html","pages.yml"})

if __name__=="__main__":unittest.main()
