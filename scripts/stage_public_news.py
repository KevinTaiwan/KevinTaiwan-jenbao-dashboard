"""Stage a reviewed public-news increment; never writes to GitHub or the live public tree.
Private input/approval files and staging directory must remain outside the repository.
The deployment workflow still independently pins the final approved digest.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path
from validate_public_news import validate, sessions, reaction, stamp, require, safe_url

def sha(raw): return hashlib.sha256(raw).hexdigest()
def encode(doc): return (json.dumps(doc, ensure_ascii=False, separators=(",",":"))+"\n").encode("utf-8")
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

def stage(args):
    repo=Path(args.repo).resolve()
    def private_path(value):
        p=Path(value).resolve()
        require(not p.is_relative_to(repo),"private inputs/output must be outside repository")
        return p
    root=repo/"public"
    raw,base=read_checked(root/"public-news-events.json",args.base_sha256)
    validate(raw,args.base_sha256,root)
    _,candidate=read_checked(private_path(args.candidate),args.candidate_sha256)
    _,review=read_checked(private_path(args.review),args.review_sha256)
    require(review.get("batch_id")==candidate.get("batch_id") and review.get("candidate_sha256")==args.candidate_sha256,"review does not bind candidate")
    approval=json.loads(private_path(args.approval).read_text()) if args.approval else None
    selected=select_records(candidate,approval,args.candidate_sha256,args.review_sha256,args.base_sha256)
    if not selected:
        return {"status":"NO_UPDATE","accepted_count":0,"reason":"no independently approved events","base_sha256":args.base_sha256}
    merged,changed=merge(base,[project(e,sessions(root)) for e in selected])
    if not changed:return {"status":"NO_UPDATE","accepted_count":0,"reason":"already published","base_sha256":args.base_sha256}
    output=encode(merged);digest=sha(output);validate(output,digest,root)
    html=(root/"index.html").read_text(encoding="utf-8")
    marker="const TECH_APPROVED_NEWS_SNAPSHOT="
    require(html.count(marker)==1,"snapshot marker mismatch")
    prefix,tail=html.split(marker,1)
    embedded,n=json.JSONDecoder().raw_decode(tail)
    require(embedded==base,"base fallback differs")
    html=prefix+marker+output.decode("utf-8").strip()+tail[n:]
    wf=(repo/".github/workflows/pages.yml").read_text(encoding="utf-8")
    old="'--approved-sha256', '"+args.base_sha256+"'"
    require(wf.count(old)==1,"deployment pin mismatch")
    wf=wf.replace(old,"'--approved-sha256', '"+digest+"'")
    out=private_path(args.out);out.mkdir(parents=True,exist_ok=False)
    (out/"public-news-events.json").write_bytes(output)
    (out/"index.html").write_text(html,encoding="utf-8")
    (out/"pages.yml").write_text(wf,encoding="utf-8")
    return {"status":"STAGED_NOT_PUBLISHED","accepted_count":changed,"total_count":len(merged["records"]),"public_sha256":digest,"base_sha256":args.base_sha256}
def main():
    p=argparse.ArgumentParser()
    for k in ("repo","candidate","candidate-sha256","review","review-sha256","base-sha256","out"):p.add_argument("--"+k,required=True)
    p.add_argument("--approval")
    try:print(json.dumps(stage(p.parse_args()),ensure_ascii=False))
    except Exception as e:
        print("FAIL_CLOSED: "+type(e).__name__,file=sys.stderr);return 1
    return 0
if __name__=="__main__":raise SystemExit(main())
