"""Read-only reconciliation of an independently approved release.
Use separately authenticated private manifest/receipt, fetched Git objects,
Actions run and deployment marker. Never write a remote ref.
"""
import argparse, json, re, subprocess
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from stage_public_news import RELEASE_PATHS, sha, encode, read_checked, require
from prepare_public_news_commit import git

LIVE_URL="https://kevintaiwan.github.io/KevinTaiwan-jenbao-dashboard/public-news-events.json"

def exact_commit(s):
    return isinstance(s,str) and re.fullmatch(r"[0-9a-f]{40}",s) is not None

def hashes(repo,ref):
    require(exact_commit(ref),"exact commit required")
    return {name:sha(git(repo,"show",ref+":"+path)) for name,path in RELEASE_PATHS.items()}

def ancestor(repo,a,b):
    require(exact_commit(a) and exact_commit(b),"invalid ancestry")
    p=subprocess.run(["git","-C",str(repo),"merge-base","--is-ancestor",a,b],capture_output=True)
    require(p.returncode in (0,1),"ancestry unavailable")
    return p.returncode==0

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def read_live(expected):
    try:
        with build_opener(NoRedirect()).open(Request(LIVE_URL,headers={"Cache-Control":"no-cache","Accept-Encoding":"identity"}),timeout=12) as r:
            raw=r.read(4_000_001)
            require(len(raw)<=4_000_000 and r.geturl()==LIVE_URL,"unexpected response")
            actual=sha(raw)
            return {"status":"PASS" if r.status==200 and actual==expected else "WARN","http_status":r.status,"sha256":actual}
    except Exception as e:
        return {"status":"WARN","error_type":type(e).__name__}

def reconcile(repo,m,p,remote_head,marker=None,run=None,live_reader=None):
    core={k:v for k,v in m.items() if k!="transaction_id"}
    require(m.get("audience")=="private_release_transaction" and m.get("transaction_id")==sha(encode(core)),"transaction identity mismatch")
    require(p.get("status")=="COMMIT_PREPARED_NOT_PUSHED" and p.get("transaction_id")==m["transaction_id"],"prepared receipt mismatch")
    parent,commit=p["parent"],p["commit"]
    require(exact_commit(parent) and exact_commit(commit),"invalid commit")
    require(git(repo,"rev-list","--parents","-n","1",commit).decode().split()==[commit,parent],"unexpected parent")
    paths=set(git(repo,"diff-tree","--no-commit-id","--name-only","-r",parent,commit).decode().splitlines())
    require(paths==set(RELEASE_PATHS.values()),"unexpected commit paths")
    base,expected=m["base_sha256"],m["output_sha256"]
    require(hashes(repo,parent)==base and hashes(repo,commit)==expected,"commit hash mismatch")
    actual=hashes(repo,remote_head)
    result={"transaction_id":m["transaction_id"],"commit":commit,"observed_head":remote_head,"public_sha256":expected["public-news-events.json"],"remote_written":False,"deployment_verified":False,"live_verified":False}
    def done(status,reason,**kw):return {**result,"status":status,"reason":reason,**kw}
    if remote_head==parent and actual==base:
        return done("READY_FOR_LEASED_REF_UPDATE","exact parent verified",ref_update={"branch":"main","expected_sha":parent,"sha":commit,"force":False})
    if not ancestor(repo,commit,remote_head):
        return done("CONFLICT_HOLD","prepared commit absent from main ancestry")
    if actual!=expected:
        return done("SUPERSEDED_OR_DRIFT_HOLD","release files changed; reconcile, do not retry")
    if not isinstance(run,dict):return done("REMOTE_COMMITTED_DEPLOYMENT_PENDING","Actions evidence missing")
    if run.get("status")!="completed":return done("REMOTE_COMMITTED_CI_PENDING","run incomplete")
    if run.get("conclusion")!="success":return done("REMOTE_COMMITTED_CI_FAILED","run failed; preserve last deployed version")
    if not isinstance(marker,dict) or marker.get("schemaVersion")!=1 or type(marker.get("workflowRunId")) is not int or marker["workflowRunId"]!=run.get("id"):
        return done("REMOTE_COMMITTED_DEPLOYMENT_PENDING","success not matched to deployment")
    deployed=marker.get("sourceCommit");run_head=run.get("head_sha")
    if not exact_commit(deployed) or not exact_commit(run_head) or not ancestor(repo,commit,deployed) or not ancestor(repo,deployed,remote_head) or not ancestor(repo,run_head,deployed):
        return done("DEPLOYMENT_EVIDENCE_CONFLICT","deployment ancestry mismatch")
    if run.get("path")!=".github/workflows/pages.yml" or hashes(repo,deployed)!=expected:
        return done("DEPLOYMENT_EVIDENCE_CONFLICT","workflow or deployed release mismatch")
    if any(marker.get("publicFileSha256",{}).get(n)!=expected[n] for n in ("public-news-events.json","index.html")) or not marker.get("deployedAt"):
        return done("DEPLOYMENT_EVIDENCE_CONFLICT","deployment file hashes or time missing")
    result.update(deployment_verified=True,deployment_run_id=run["id"],deployed_at=marker["deployedAt"])
    if live_reader is None:return done("DEPLOYED_LIVE_PENDING","HTTP not attempted")
    live=live_reader(expected["public-news-events.json"])
    if live.get("status")!="PASS" or live.get("http_status")!=200 or live.get("sha256")!=expected["public-news-events.json"]:
        return done("DEPLOYED_LIVE_WARN","live bytes missing or stale",live=live)
    return done("RELEASE_READBACK_PASS","remote, deployment and live feed verified",live_verified=True,live=live)

def main():
    a=argparse.ArgumentParser()
    for k in ("repo","manifest","manifest-sha256","prepared","prepared-sha256","remote-head"):a.add_argument("--"+k,required=True)
    for k in ("marker","run"):a.add_argument("--"+k)
    a.add_argument("--live",action="store_true");v=a.parse_args()
    try:
        repo=Path(v.repo).resolve()
        def private_path(s):
            p=Path(s).resolve();require(not p.is_relative_to(repo),"private evidence inside repository");return p
        _,m=read_checked(private_path(v.manifest),v.manifest_sha256)
        _,p=read_checked(private_path(v.prepared),v.prepared_sha256)
        opt=lambda s:json.loads(private_path(s).read_bytes()) if s else None
        print(json.dumps(reconcile(repo,m,p,v.remote_head,opt(v.marker),opt(v.run),read_live if v.live else None)))
    except Exception as e:
        print(json.dumps({"status":"FAIL_CLOSED","error_type":type(e).__name__}));return 1
    return 0
if __name__=="__main__":raise SystemExit(main())
