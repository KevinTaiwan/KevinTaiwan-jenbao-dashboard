import json, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_public_news import stage, sha, MANIFEST
from prepare_public_news_commit import commit_release, git
from reconcile_public_news_release import reconcile
import test_public_news_stage as fixture

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        f=self.f=fixture.FullStageTests()
        f.setUp();self.addCleanup(f.doCleanups);f.approve()
        self.r=f.repo;self.a=f.args
        git(self.r,"init","-q");git(self.r,"config","user.email","test@example.invalid");git(self.r,"config","user.name","Synthetic CI")
        git(self.r,"add",".");git(self.r,"commit","-qm","base")
        self.a.expected_head=git(self.r,"rev-parse","HEAD").decode().strip()
        stage(self.a);self.a.manifest_sha256=sha((f.out/MANIFEST).read_bytes())
        self.m=json.loads((f.out/MANIFEST).read_bytes());self.p=commit_release(self.a)
        self.parent=self.p["parent"];self.commit=self.p["commit"]
        self.run={"id":123,"status":"completed","conclusion":"success","head_sha":self.commit,"path":".github/workflows/pages.yml"}
        self.marker={"schemaVersion":1,"workflowRunId":123,"sourceCommit":self.commit,"deployedAt":"2026-11-28T10:00:00Z","publicFileSha256":self.m["output_sha256"]}
        self.live=lambda h:{"status":"PASS","sha256":h,"http_status":200}
    def check(self,head,marker=None,run=None,live=None):
        return reconcile(self.r,self.m,self.p,head,marker,run,live)
    def test_ready_lease(self):
        x=self.check(self.parent)
        self.assertEqual(x["ref_update"],{"branch":"main","expected_sha":self.parent,"sha":self.commit,"force":False})
        self.assertFalse(x["remote_written"])
    def test_conflict(self):
        git(self.r,"commit","--allow-empty","-qm","concurrent")
        self.assertEqual(self.check(git(self.r,"rev-parse","HEAD").decode().strip())["status"],"CONFLICT_HOLD")
    def test_committed(self):
        x=self.check(self.commit);self.assertEqual(x["status"],"REMOTE_COMMITTED_DEPLOYMENT_PENDING");self.assertNotIn("ref_update",x)
    def test_ci(self):
        self.assertEqual(self.check(self.commit,self.marker,{"status":"in_progress"})["status"],"REMOTE_COMMITTED_CI_PENDING")
        self.assertEqual(self.check(self.commit,self.marker,{**self.run,"conclusion":"failure"})["status"],"REMOTE_COMMITTED_CI_FAILED")
    def test_run_mismatch(self):
        self.assertEqual(self.check(self.commit,{**self.marker,"workflowRunId":456},self.run)["status"],"REMOTE_COMMITTED_DEPLOYMENT_PENDING")
    def test_hash_mismatch(self):
        self.assertEqual(self.check(self.commit,{**self.marker,"publicFileSha256":{}},self.run)["status"],"DEPLOYMENT_EVIDENCE_CONFLICT")
    def test_lineage(self):
        self.assertEqual(self.check(self.commit,{**self.marker,"sourceCommit":self.parent},self.run)["status"],"DEPLOYMENT_EVIDENCE_CONFLICT")
    def test_wrong_workflow(self):
        self.assertEqual(self.check(self.commit,self.marker,{**self.run,"path":"other.yml"})["status"],"DEPLOYMENT_EVIDENCE_CONFLICT")
    def test_live(self):
        self.assertEqual(self.check(self.commit,self.marker,self.run)["status"],"DEPLOYED_LIVE_PENDING")
        self.assertEqual(self.check(self.commit,self.marker,self.run,lambda h:{"status":"WARN"})["status"],"DEPLOYED_LIVE_WARN")
        x=self.check(self.commit,self.marker,self.run,self.live);self.assertEqual(x["status"],"RELEASE_READBACK_PASS");self.assertTrue(x["live_verified"])
    def test_descendant_drift(self):
        git(self.r,"checkout","--detach",self.commit);git(self.r,"commit","--allow-empty","-qm","receipt")
        head=git(self.r,"rev-parse","HEAD").decode().strip()
        self.assertEqual(self.check(head,self.marker,self.run,self.live)["status"],"RELEASE_READBACK_PASS")
        (self.f.pub/"index.html").write_text("changed")
        git(self.r,"add","public/index.html");git(self.r,"commit","-qm","drift")
        self.assertEqual(self.check(git(self.r,"rev-parse","HEAD").decode().strip())["status"],"SUPERSEDED_OR_DRIFT_HOLD")
    def test_manifest_tamper(self):
        self.m["changed_count"]=999
        with self.assertRaises(ValueError):self.check(self.parent)

if __name__=="__main__":unittest.main()
