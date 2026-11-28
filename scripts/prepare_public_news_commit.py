"""Build a guarded release commit in a local Git object database only.
No push, remote call, branch update, private manifest upload or credentials.
Caller must independently authenticate the Dashboard approval and transaction
digest from private Pages/Library, then use a non-force remote ref lease.
"""
import argparse, json, os, re, subprocess, tempfile
from pathlib import Path
from stage_public_news import RELEASE_PATHS, MANIFEST, sha, read_checked, stage, require, verify_transaction

def git(repo, *args, data=None, env=None):
    return subprocess.run(["git","-C",str(repo),*args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, env=env, check=True).stdout

def commit_release(args):
    repo=Path(args.repo).resolve()
    out=Path(args.out).resolve()
    require(not out.is_relative_to(repo),"private stage inside repository")
    require(re.fullmatch(r"[0-9a-f]{40}",args.expected_head),"exact parent required")
    require(git(repo,"rev-parse","HEAD").decode().strip()==args.expected_head,"head changed")
    require(not git(repo,"status","--porcelain", "--untracked-files=no").strip(),"tracked worktree or index dirty")
    require(bool(args.approval) and bool(args.approval_sha256),"independent approval required")
    # Trusted expected manifest digest is supplied separately, not derived from untrusted output.
    raw,manifest=read_checked(out/MANIFEST,args.manifest_sha256)
    require(manifest["approval_sha256"]==args.approval_sha256,"approval digest mismatch")
    # Re-run the stage from the original private inputs, not merely the manifest's assertions.
    result=stage(args)
    require(result["status"]=="STAGED_NOT_PUBLISHED" and result["transaction_id"]==manifest["transaction_id"],"stage does not reproduce")
    require((out/MANIFEST).read_bytes()==raw,"manifest changed")
    verify_transaction(repo,out,manifest)
    payload={name:(out/name).read_bytes() for name in RELEASE_PATHS}
    for name,path in RELEASE_PATHS.items():
        require(sha(git(repo,"show",args.expected_head+":"+path))==manifest["base_sha256"][name],"parent file changed")
        require(sha(payload[name])==manifest["output_sha256"][name],"payload changed")
        entry=git(repo,"ls-tree",args.expected_head,"--",path).decode()
        require(entry.startswith("100644 blob "),"unexpected file mode")
    require(git(repo,"rev-parse","HEAD").decode().strip()==args.expected_head,"head changed before commit")
    # Isolated index: current branch and real index remain unchanged.
    with tempfile.TemporaryDirectory() as tmp:
        env={**os.environ,"GIT_INDEX_FILE":str(Path(tmp)/"index")}
        git(repo,"read-tree",args.expected_head,env=env)
        for name,path in RELEASE_PATHS.items():
            blob=git(repo,"hash-object","-w","--stdin",data=payload[name]).decode().strip()
            git(repo,"update-index","--cacheinfo","100644,"+blob+","+path,env=env)
        tree=git(repo,"write-tree",env=env).decode().strip()
    changed=set(git(repo,"diff-tree","--no-commit-id","--name-only","-r",args.expected_head,tree).decode().splitlines())
    require(changed==set(RELEASE_PATHS.values()),"unexpected release diff")
    # No private IDs, hashes or file names in the public commit message.
    commit=git(repo,"commit-tree",tree,"-p",args.expected_head,"-m","Publish independently reviewed official market news").decode().strip()
    for name,path in RELEASE_PATHS.items():
        require(git(repo,"show",commit+":"+path)==payload[name],"commit readback mismatch")
    require(git(repo,"rev-parse","HEAD").decode().strip()==args.expected_head,"head changed; do not publish")
    return {"status":"COMMIT_PREPARED_NOT_PUSHED","parent":args.expected_head,"commit":commit,"tree":tree,
            "public_sha256":manifest["output_sha256"]["public-news-events.json"],"transaction_id":manifest["transaction_id"],
            "changed_paths":sorted(changed),"branch_updated":False,"remote_written":False}

def main():
    p=argparse.ArgumentParser()
    for k in ("repo","candidate","candidate-sha256","review","review-sha256","base-sha256","out","approval","approval-sha256","expected-head","manifest-sha256"):
        p.add_argument("--"+k,required=True)
    try: print(json.dumps(commit_release(p.parse_args())))
    except Exception as e:
        print(json.dumps({"status":"FAIL_CLOSED","error_type":type(e).__name__}))
        return 1
    return 0

if __name__=="__main__":raise SystemExit(main())
