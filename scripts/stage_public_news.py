"""Stage a reviewed public-news increment; never writes to GitHub or the live public tree.
Private input/approval files and staging directory must remain outside the repository.
The deployment workflow still independently pins the final approved digest.
"""
import argparse, hashlib, json, os, re, sys
from pathlib import Path
from validate_public_news import validate, sessions, reaction, stamp, require, safe_url

def sha(raw): return hashlib.sha256(raw).hexdigest()
def encode(doc): return (json.dumps(doc, ensure_ascii=False, separators=(",",":"))+"\n").encode("utf-8")
def embedded_json(doc):
    # JSON inside an inline script must not allow an HTML closing script tag.
    return encode(doc).decode("utf-8").strip().replace("<",r"\u003c").replace(">",r"\u003e").replace("&",r"\u0026").replace("\u2028",r"\u2028").replace("\u2029",r"\u2029")
def read_checked(path, expected):
    raw=path.read_bytes()
    require(re.fullmatch(r"[0-9a-f]{64}",expected) and sha(raw)==expected,"input digest mismatch")
    return raw,json.loads(raw)

def select_records(candidate, approval, candidate_sha, review_sha, base_sha):
    require(candidate.get("audience")=="private_public_news_candidate" and candidate.get("public_release_enabled") is False,"candidate audience/permission mismatch")
    rows=candidate.get("records")
    require(isinstance(rows,list) and candidate.get("record_count")==len(rows),"candidate count mismatch")
    by_id={}
    for e in rows:
        k=e["event_id"]
        require(k not in by_id,"duplicate candidate ID")
        by_id[k]=e
    if approval is None:return []
    require(set(approval)=={"batch_id","candidate_sha256","review_sha256","base_public_sha256","reviewer","records"} and approval["reviewer"]=="dashboard_independent","independent approval required")
    require(approval["batch_id"]==candidate["batch_id"] and approval["candidate_sha256"]==candidate_sha and approval["review_sha256"]==review_sha and approval["base_public_sha256"]==base_sha,"approval not bound to inputs")
    require(isinstance(approval["records"],list),"approval rows")
    selected=[];seen=set()
    for a in approval["records"]:
        require(set(a)=={"event_id","revision","direct_source_verified","rights_verified","summary_reviewed"},"approval fields")
        k=a["event_id"]
        require(k in by_id and k not in seen,"unknown/duplicate approved event");seen.add(k)
        e=by_id[k]
        require(all(a[x] is True for x in ("direct_source_verified","rights_verified","summary_reviewed")),"approval incomplete")
        require(type(a["revision"]) is int and a["revision"]==e["revision"] and e.get("publication_allowed") is True and e.get("verification_status")=="PASS_PRIMARY_TEXT_AND_RELEASE_TIME" and e.get("data_quality")=="verified_primary_text","candidate eligibility/revision")
        selected.append(e)
    return selected

def project(e,cal):
    ts=stamp(e["published_at"])
    require(safe_url(e["source_url"],e["source_name"]),"source host mismatch")
    return {"eventId":e["event_id"],"revision":e["revision"],"date":e["published_at"][:10],"kind":e["category"],"title":e["title"],"summary":e["summary"],"source":e["source_name"],"url":e["source_url"],"publishedAt":e["published_at"],"eventAt":e["event_at"],"effectiveAt":e["effective_at"],"reactionDates":{m:reaction(ts,m,cal[m]) for m in ("tw","us")},"publicationAllowed":True,"quality":"verified_public"}

def merge(base, additions):
    rows={e["eventId"]:e for e in base["records"]}
    changed=0
    for e in additions:
        old=rows.get(e["eventId"])
        if old is not None:
            require(e["revision"]>=old["revision"],"revision rollback")
            if e["revision"]==old["revision"]:
                require(e==old,"same revision changed");continue
        require(not any(x["eventId"]!=e["eventId"] and x["url"].rstrip("/")==e["url"].rstrip("/") for x in rows.values()),"duplicate source URL")
        rows[e["eventId"]]=e;changed+=1
    return {**base,"records":list(rows.values())},changed

# Only these three display files may enter a release commit.
RELEASE_PATHS={"public-news-events.json":"public/public-news-events.json","index.html":"public/index.html","pages.yml":".github/workflows/pages.yml"}
MANIFEST="private-transaction.json"

def base_fingerprints(repo):
    return {name:sha((repo/path).read_bytes()) for name,path in RELEASE_PATHS.items()}

def transaction_receipt(base, payload, args, candidate, changed):
    core={"schema_version":1,"audience":"private_release_transaction","batch_id":candidate["batch_id"],
          "candidate_sha256":args.candidate_sha256,"review_sha256":args.review_sha256,"approval_sha256":args.approval_sha256,
          "base_sha256":base,"output_sha256":{k:sha(v) for k,v in payload.items()},"changed_count":changed}
    return {**core,"transaction_id":sha(encode(core))}

def checked_bytes(path, expected):
    require(not path.is_symlink() and path.is_file() and path.read_bytes()==expected,"unknown or partial transaction bytes")

def write_once(path, data):
    # A crash may leave partial bytes; a retry then stops instead of overwriting.
    try:
        with path.open("xb") as f:
            f.write(data);f.flush();os.fsync(f.fileno())
    except FileExistsError:
        checked_bytes(path,data)
    checked_bytes(path,data)

def persist_transaction(out, payload, manifest):
    require(set(payload)==set(RELEASE_PATHS),"unexpected release files")
    require(not out.is_symlink(),"staging directory symlink")
    out.mkdir(parents=True,exist_ok=True)
    require(out.is_dir(),"staging path not a directory")
    wanted={**payload,MANIFEST:encode(manifest)}
    existing=set(p.name for p in out.iterdir())
    require(existing<=set(wanted),"unexpected transaction files")
    # A committed receipt must never be used to heal missing files silently.
    if MANIFEST in existing:require(existing==set(wanted),"completed transaction missing files")
    for name in existing:checked_bytes(out/name,wanted[name])
    mode="REUSED" if MANIFEST in existing else "RECOVERED" if existing else "CREATED"
    for name in payload:write_once(out/name,payload[name])
    write_once(out/MANIFEST,wanted[MANIFEST])  # commit marker last
    for name,raw in wanted.items():checked_bytes(out/name,raw)
    return mode

def verify_transaction(repo,out,expected_manifest):
    require(not out.is_symlink() and out.is_dir(),"missing stage")
    require(set(p.name for p in out.iterdir())==set(RELEASE_PATHS)|{MANIFEST},"incomplete or unexpected transaction files")
    checked_bytes(out/MANIFEST,encode(expected_manifest))
    core={k:v for k,v in expected_manifest.items() if k!="transaction_id"}
    require(expected_manifest["transaction_id"]==sha(encode(core)),"transaction fingerprint mismatch")
    require(base_fingerprints(repo)==expected_manifest["base_sha256"],"base changed; re-review and re-stage")
    for name in RELEASE_PATHS:
        path=out/name
        require(not path.is_symlink() and path.is_file() and sha(path.read_bytes())==expected_manifest["output_sha256"][name],"staged output mismatch")
    return True

def stage(args):
    repo=Path(args.repo).resolve()
    def private_path(value):
        p=Path(value).resolve()
        require(not p.is_relative_to(repo),"private inputs/output must be outside repository")
        return p
    root=repo/"public"
    base_files=base_fingerprints(repo)
    raw,base=read_checked(root/"public-news-events.json",args.base_sha256)
    require(base_files["public-news-events.json"]==args.base_sha256,"base changed during read")
    validate(raw,args.base_sha256,root)
    _,candidate=read_checked(private_path(args.candidate),args.candidate_sha256)
    _,review=read_checked(private_path(args.review),args.review_sha256)
    require(candidate.get("project_id")=="MEDIA-DASHBOARD-R10.1" and candidate.get("schema_version")=="1.0","candidate contract mismatch")
    require(review.get("project_id")==candidate["project_id"] and review.get("batch_id")==candidate.get("batch_id") and review.get("candidate_sha256")==args.candidate_sha256 and review.get("candidate_count")==candidate.get("record_count") and review.get("dashboard_public_sha256")==args.base_sha256 and review.get("public_release_enabled") is False,"review does not bind candidate and base")
    require(bool(args.approval)==bool(args.approval_sha256),"approval file and digest must be supplied together")
    approval=read_checked(private_path(args.approval),args.approval_sha256)[1] if args.approval else None
    selected=select_records(candidate,approval,args.candidate_sha256,args.review_sha256,args.base_sha256)
    if not selected:
        return {"status":"HOLD_NO_APPROVAL" if candidate["record_count"] else "NO_UPDATE","accepted_count":0,"reason":"no independently approved events","base_sha256":args.base_sha256}
    merged,changed=merge(base,[project(e,sessions(root)) for e in selected])
    if not changed:return {"status":"NO_UPDATE","accepted_count":0,"reason":"already published","base_sha256":args.base_sha256}
    output=encode(merged);digest=sha(output);validate(output,digest,root)
    html=(root/"index.html").read_text(encoding="utf-8")
    marker="const TECH_APPROVED_NEWS_SNAPSHOT="
    require(html.count(marker)==1,"snapshot marker mismatch")
    prefix,tail=html.split(marker,1)
    embedded,n=json.JSONDecoder().raw_decode(tail)
    require(embedded==base,"base fallback differs")
    html=prefix+marker+embedded_json(merged)+tail[n:]
    wf=(repo/".github/workflows/pages.yml").read_text(encoding="utf-8")
    old="'--approved-sha256', '"+args.base_sha256+"'"
    require(wf.count(old)==1,"deployment pin mismatch")
    wf=wf.replace(old,"'--approved-sha256', '"+digest+"'")
    out=private_path(args.out)
    require(base_fingerprints(repo)==base_files,"base changed during staging")
    payload={"public-news-events.json":output,"index.html":html.encode("utf-8"),"pages.yml":wf.encode("utf-8")}
    manifest=transaction_receipt(base_files,payload,args,candidate,changed)
    mode=persist_transaction(out,payload,manifest)
    verify_transaction(repo,out,manifest)
    return {"status":"STAGED_NOT_PUBLISHED","stage_mode":mode,"transaction_id":manifest["transaction_id"],"accepted_count":changed,"total_count":len(merged["records"]),"public_sha256":digest,"base_sha256":args.base_sha256}
def main():
    p=argparse.ArgumentParser()
    for k in ("repo","candidate","candidate-sha256","review","review-sha256","base-sha256","out"):p.add_argument("--"+k,required=True)
    p.add_argument("--approval");p.add_argument("--approval-sha256")
    try:print(json.dumps(stage(p.parse_args()),ensure_ascii=False))
    except Exception as e:
        print("FAIL_CLOSED: "+type(e).__name__,file=sys.stderr);return 1
    return 0
if __name__=="__main__":raise SystemExit(main())
