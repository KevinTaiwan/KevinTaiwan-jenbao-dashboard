"""Real public-site Chromium smoke test. No mocks, private inputs or site writes."""
import datetime, hashlib, json, os, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

URL="https://kevintaiwan.github.io/KevinTaiwan-jenbao-dashboard/"
ROOT=Path(__file__).resolve().parents[1]
checks={}
errors=[]
def check(name,fn):
    try:
        fn()
        checks[name]={"status":"PASS"}
    except Exception as e:
        checks[name]={"status":"FAIL","error":str(e)[:500]}
def require(ok,msg):
    if not ok:raise AssertionError(msg)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def run():
    feed=(ROOT/"public/public-news-events.json").read_bytes()
    records=json.loads(feed)["records"]
    marker=json.loads((ROOT/".sync/pages-deployment.json").read_text())
    require(marker["publicFileSha256"]["public-news-events.json"]==digest(feed),"local deploy fingerprint mismatch")
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            page=browser.new_page(viewport={"width":1600,"height":1000},device_scale_factor=1)
            page.set_default_timeout(12000)
            page.on("pageerror",lambda exc:errors.append(str(exc)[:300]))
            res=page.goto(URL,wait_until="domcontentloaded",timeout=30000)
            require(res is not None and res.status==200 and page.url==URL,"live navigation failed or redirected")
            require(digest(res.body())==marker["publicFileSha256"]["index.html"],"live HTML digest differs from deployment marker")
            checks["live_html"]={"status":"PASS","sha256":digest(res.body())}
            response=page.request.get(URL+"public-news-events.json",timeout=15000,max_redirects=0)
            require(response.status==200 and digest(response.body())==digest(feed),"live news bytes mismatch")
            checks["live_feed"]={"status":"PASS","count":len(records),"sha256":digest(feed)}
            host=page.locator("#marketCrossCharts")
            top=host.locator('[data-tech-field="top"]')
            top.wait_for(state="visible",timeout=30000)
            top.select_option("taiex")
            host.locator('[data-tech-field="right"]').select_option("off")
            page.locator('[data-window="60"]').click()
            list_btn=host.locator("[data-tech-news-open]")
            detail=host.locator("[data-tech-news-readout]")
            tip=host.locator("[data-tech-news-tooltip]")
            listing=host.locator("[data-tech-news-list]")
            latest=max(r["reactionDates"]["tw"] for r in records if r["reactionDates"]["tw"])
            event_rows=[r for r in records if r["reactionDates"]["tw"]==latest]
            def check_list():
                list_btn.click()
                expect(listing).to_be_visible()
                for r in records:
                    expect(listing.get_by_text(r["title"],exact=False).first).to_be_visible()
                    require(listing.locator("a").evaluate_all("(els)=>els.map(e=>e.href)").count(r["url"])==1,"missing or duplicate source link")
                expect(listing.locator("[data-tech-news-list-close]")).to_be_visible()
                listing.locator("[data-tech-news-list-close]").click()
                expect(listing).to_be_hidden()
            check("news_list_all_approved",check_list)
            def dot(day):
                return host.locator('[data-tech-news-date="'+day+'"] .tech-news-dot')
            def point(day):
                d=dot(day);d.wait_for(state="visible")
                d.scroll_into_view_if_needed()
                b=d.bounding_box();require(b is not None,"dot geometry unavailable")
                return (b["x"]+b["width"]/2,b["y"]+b["height"]/2)
            def hover():
                expect(detail).to_be_hidden()
                x,y=point(latest);page.mouse.move(x,y)
                expect(tip).to_be_visible()
                for r in event_rows:expect(tip.get_by_text(r["title"],exact=False).first).to_be_visible()
            check("taiwan_gold_dot_hover",hover)
            def click_detail():
                x,y=point(latest);page.mouse.click(x,y)
                expect(detail).to_be_visible()
                for r in event_rows:
                    expect(detail.get_by_text(r["title"],exact=False).first).to_be_visible()
                    expect(detail.get_by_text(r["summary"],exact=False).first).to_be_visible()
                    require(detail.locator("a").evaluate_all("(els)=>els.map(e=>e.href)").count(r["url"])==1,"official link missing")
                require(host.locator('[data-tech-news-date="'+latest+'"]').get_attribute("aria-pressed")=="true","dot selection missing")
            check("click_summary_and_links",click_detail)
            def drag():
                expect(detail).to_be_visible()
                h=detail.locator(".tech-news-drag-handle")
                b=h.bounding_box();before=detail.bounding_box()
                require(b is not None and before is not None,"drag geometry missing")
                dx=-180 if before["x"]>200 else 180
                dy=100 if before["y"]<500 else -100
                x=b["x"]+min(20,b["width"]/2);y=b["y"]+b["height"]/2
                page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+dx,y+dy,steps=12);page.mouse.up()
                after=detail.bounding_box()
                require(after is not None and abs(after["x"]-before["x"])+abs(after["y"]-before["y"])>50,"drag did not move")
                require(after["x"]>=-1 and after["y"]>=-1 and after["x"]+after["width"]<=1601 and after["y"]+after["height"]<=1001,"drag outside viewport")
            check("mouse_drag",drag)
            def close():
                expect(detail).to_be_visible()
                detail.locator("[data-tech-news-dismiss]").click()
                expect(detail).to_be_hidden()
            check("close_detail",close)
            def us_switch():
                if detail.is_visible():detail.locator("[data-tech-news-dismiss]").click()
                if listing.is_visible():listing.locator("[data-tech-news-list-close]").click()
                top.select_option("IXIC")
                day=max(r["reactionDates"]["us"] for r in records if r["reactionDates"]["us"])
                x,y=point(day);page.mouse.move(x,y)
                expect(tip).to_be_visible()
                for r in records:
                    if r["reactionDates"]["us"]==day:expect(tip.get_by_text(r["title"],exact=False).first).to_be_visible()
                page.mouse.click(x,y);expect(detail).to_be_visible()
                detail.locator("[data-tech-news-dismiss]").click()
            check("us_market_date_alignment",us_switch)
            check("no_page_errors",lambda:require(not errors,"; ".join(errors)))
        finally:
            browser.close()

if __name__=="__main__":
    try:run()
    except Exception as e:checks["setup"]={"status":"FAIL","error":str(e)[:600]}
    required={"live_html","live_feed","news_list_all_approved","taiwan_gold_dot_hover","click_summary_and_links","mouse_drag","close_detail","us_market_date_alignment","no_page_errors"}
    passed=required<=checks.keys() and all(v["status"]=="PASS" for v in checks.values())
    receipt={"schemaVersion":1,"status":"PASS" if passed else "WARN","runId":os.environ.get("GITHUB_RUN_ID"),"checkedAt":datetime.datetime.now(datetime.timezone.utc).isoformat(),"browser":"Chromium / Playwright","mode":"live_public_site","checks":checks}
    line=json.dumps(receipt,ensure_ascii=False,sort_keys=True)
    print("PUBLIC_NEWS_BROWSER_RECEIPT "+line,flush=True)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"],"a",encoding="utf-8") as f:f.write("### Live public news browser test\n\n"+line+"\n")
    sys.exit(0 if passed else 1)
