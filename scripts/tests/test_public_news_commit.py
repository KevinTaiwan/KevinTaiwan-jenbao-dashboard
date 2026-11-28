import json, subprocess, sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_public_news import stage, sha, MANIFEST, RELEASE_PATHS
from prepare_public_news_commit import commit_release, git
from test_public_news_stage import FullStageTests

class CommitTests(unittest.TestCase):
    def setUp(self):
        # Use the existing synthetic isolated fixture, never real private news.
        self.f=FullStageTests()
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.approve()
        self.r=self.f.repo;self.a=self.f.args
        git(self.r,"init","-q")
        git(self.r,"config","user.email","test@example.invalid")
        git(self.r,"config","user.name","Synthetic CI")
        git(self.r,"add",".");git(self.r,"commit","-qm","base")
        self.a.expected_head=git(self.r,"rev-parse","HEAD").decode().strip()
        stage(self.a)
        self.a.manifest_sha256=sha((self.f.out/MANIFEST).read_bytes())
    def test_prepare_local_commit_only(self):
        result=commit_release(self.a)
        self.assertEqual(result["status"],"COMMIT_PREPARED_NOT_PUSHED")
        self.assertFalse(result["remote_written"]);self.assertFalse(result["branch_updated"])
        self.assertEqual(git(self.r,"rev-parse","HEAD").decode().strip(),self.a.expected_head)
        self.assertFalse(git(self.r,"status","--porcelain").strip())
        self.assertEqual(set(result["changed_paths"]),set(RELEASE_PATHS.values()))
        for name,path in RELEASE_PATHS.items():
            self.assertEqual(git(self.r,"show",result["commit"]+":"+path),(self.f.out/name).read_bytes())
        self.assertNotIn(b"private-transaction.json",git(self.r,"ls-tree","-r","--name-only",result["commit"]))
    def test_stale_head(self):
        git(self.r,"commit","--allow-empty","-qm","concurrent")
        with self.assertRaises(ValueError):commit_release(self.a)
    def test_dirty_tree(self):
        (self.f.pub/"index.html").write_text("changed")
        with self.assertRaises(ValueError):commit_release(self.a)
    def test_wrong_manifest_digest(self):
        self.a.manifest_sha256="0"*64
        with self.assertRaises(ValueError):commit_release(self.a)
    def test_modified_output(self):
        (self.f.out/"index.html").write_text("tampered")
        with self.assertRaises(ValueError):commit_release(self.a)
    def test_no_approval(self):
        self.a.approval=None
        with self.assertRaises(ValueError):commit_release(self.a)
    def test_private_extra(self):
        (self.f.out/"private.json").write_text("private")
        with self.assertRaises(ValueError):commit_release(self.a)

if __name__=="__main__":unittest.main()
