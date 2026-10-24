import json, math, statistics, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/latest.json"
SCORE_HISTORY=ROOT/"data/score_history.json"
TZ=timezone(timedelta(hours=8))
API="https://api.finmindtrade.com/api/v4/data"
UA={"User-Agent":"Mozilla/5.0 (compatible; StockDashboard/3.0)"}

WATCH=[
    {"id":"2330","name":"台積電","market":"TWSE","weight":True},
    {"id":"2317","name":"鴻海","market":"TWSE","weight":True},
    {"id":"2454","name":"聯發科","market":"TWSE","weight":True},
    {"id":"2308","name":"台達電","market":"TWSE","weight":True},
    {"id":"2382","name":"廣達","market":"TWSE","weight":True},
    {"id":"2881","name":"富邦金","market":"TWSE","weight":True},
    {"id":"2882","name":"國泰金","market":"TWSE","weight":True},
    {"id":"2891","name":"中信金","market":"TWSE","weight":True},
    {"id":"3711","name":"日月光投控","market":"TWSE","weight":True},
    {"id":"2412","name":"中華電","market":"TWSE","weight":True},
    {"id":"4556","name":"旭然","market":"TPEx","weight":False},
    {"id":"7556","name":"意德士","market":"TPEx","weight":False},
    {"id":"5297","name":"廣化","market":"Emerging","weight":False},
    {"id":"7887","name":"宇川精材","market":"Emerging","weight":False},
    {"id":"3680","name":"家登","market":"TPEx","weight":False},
]

POS_WORDS=["成長","創高","增加","獲利","訂單","擴產","受惠","突破","上修","看好","轉盈","合作","認證","量產"]
NEG_WORDS=["衰退","下滑","減少","虧損","下修","延後","跌","警示","裁員","停工","降評","轉虧","處分"]

def n(v):
    try:
        if v is None:return None
        return float(str(v).replace(",","").replace("%","").strip())
    except:return None

def fm(dataset, stock_id, start_date, end_date=None):
    params={"dataset":dataset,"data_id":stock_id,"start_date":start_date}
    if end_date:params["end_date"]=end_date
    r=requests.get(API,params=params,headers=UA,timeout=30)
    r.raise_for_status()
    j=r.json()
    if j.get("status") not in (None,200):
        raise RuntimeError(j.get("msg","FinMind API error"))
    return j.get("data",[])

def sma(vals,k):
    out=[]
    for i in range(len(vals)):
        chunk=[x for x in vals[max(0,i+1-k):i+1] if x is not None]
        out.append(sum(chunk)/len(chunk) if i+1>=k and len(chunk)==k else None)
    return out

def median(a):
    a=[x for x in a if x is not None and math.isfinite(x)]
    return statistics.median(a) if a else None

def quantile(a,q):
    a=sorted([x for x in a if x is not None and math.isfinite(x)])
    if not a:return None
    pos=(len(a)-1)*q
    lo=int(math.floor(pos));hi=int(math.ceil(pos))
    if lo==hi:return a[lo]
    return a[lo]+(a[hi]-a[lo])*(pos-lo)

def pct(a,b):
    return ((a/b)-1)*100 if a is not None and b not in (None,0) else None

def get_price_data(stock_id):
    start=(datetime.now(TZ)-timedelta(days=1600)).strftime("%Y-%m-%d")
    rows=sorted(fm("TaiwanStockPrice",stock_id,start),key=lambda x:x.get("date",""))
    if not rows:return {}
    closes=[n(x.get("close")) for x in rows]
    if not any(x is not None for x in closes):return {}
    m20=sma(closes,20);m60=sma(closes,60);m120=sma(closes,120)
    base=max(0,len(rows)-260)
    hist=[{
        "date":r.get("date"),"close":n(r.get("close")),
        "ma20":m20[i],"ma60":m60[i],"ma120":m120[i]
    } for i,r in enumerate(rows[base:],start=base)]
    last=rows[-1];prev=rows[-2] if len(rows)>1 else rows[-1]
    close=n(last.get("close"));prevc=n(prev.get("close"))
    trend="中性";a,b,c=m20[-1],m60[-1],m120[-1]
    if None not in (close,a,b,c):
        if close>a>b>c:trend="強勢多頭"
        elif close>a>b:trend="偏多"
        elif close<a<b<c:trend="空頭"
        elif close<a:trend="偏弱"
    d=datetime.fromisoformat(last["date"])
    qstart=datetime(d.year,((d.month-1)//3)*3+1,1)
    qrows=[r for r in rows if datetime.fromisoformat(r["date"])>=qstart]
    highs=[n(r.get("max")) for r in qrows if n(r.get("max")) is not None]
    lows=[n(r.get("min")) for r in qrows if n(r.get("min")) is not None]
    return {
        "close":close,"change_pct":pct(close,prevc),"trend":trend,
        "quarter_high":max(highs) if highs else None,
        "quarter_low":min(lows) if lows else None,
        "history":hist
    }

def get_per_eps(stock_id,close):
    start=(datetime.now(TZ)-timedelta(days=1600)).strftime("%Y-%m-%d")
    try:rows=sorted(fm("TaiwanStockPER",stock_id,start),key=lambda x:x.get("date",""))
    except:rows=[]
    pes=[n(x.get("PER")) for x in rows]
    pes=[x for x in pes if x is not None and 0<x<200]
    pe=pes[-1] if pes else None
    eps=(close/pe) if close and pe else None
    return pe,eps,pes

def get_revenue_metrics(stock_id,ttm_eps):
    start=(datetime.now(TZ)-timedelta(days=900)).strftime("%Y-%m-%d")
    try:rows=sorted(fm("TaiwanStockMonthRevenue",stock_id,start),key=lambda x:x.get("date",""))
    except:rows=[]
    if not rows:return ttm_eps,None,None,None,[]
    latest=rows[-1]
    rev=n(latest.get("revenue"))
    prev=n(rows[-2].get("revenue")) if len(rows)>=2 else None
    yearago=None
    ly=int(latest.get("revenue_year",0))-1
    lm=int(latest.get("revenue_month",0))
    for r in reversed(rows):
        if int(r.get("revenue_year",0))==ly and int(r.get("revenue_month",0))==lm:
            yearago=n(r.get("revenue"));break
    mom=pct(rev,prev);yoy=pct(rev,yearago)
    growth=yoy if yoy is not None else None
    if growth is not None:g=max(-30,min(50,growth))/100
    else:g=None
    fwd=ttm_eps*(1+g) if ttm_eps is not None and g is not None else ttm_eps
    recent=[{
        "date":r.get("date"),"year":r.get("revenue_year"),"month":r.get("revenue_month"),
        "revenue":n(r.get("revenue"))
    } for r in rows[-12:]]
    return fwd,g,yoy,mom,recent

def get_quarterly_eps(stock_id):
    start=(datetime.now(TZ)-timedelta(days=1000)).strftime("%Y-%m-%d")
    try:rows=fm("TaiwanStockFinancialStatements",stock_id,start)
    except:return []
    epsrows=sorted([r for r in rows if r.get("type")=="EPS"],key=lambda x:x.get("date",""))
    byq={}
    for r in epsrows:
        d=datetime.fromisoformat(r["date"]);q=(d.month-1)//3+1
        byq[(d.year,q)]=n(r.get("value"))
    out=[]
    for (y,q),value in sorted(byq.items()):
        out.append({"quarter":f"{y}Q{q}","eps":value,"reported_eps":value})
    return out[-8:]

def classify_name(name):
    if "Foreign" in name or "外資" in name:return "foreign"
    if "Investment_Trust" in name or "投信" in name:return "trust"
    if "Dealer" in name or "自營" in name:return "dealer"
    return None

def streak_label(vals):
    vals=[v for v in vals if v is not None]
    if not vals or vals[-1]==0:return "0日"
    sign=1 if vals[-1]>0 else -1
    cnt=0
    for v in reversed(vals):
        if (v>0 and sign>0) or (v<0 and sign<0):cnt+=1
        else:break
    return ("連買" if sign>0 else "連賣")+str(cnt)+"日"

def get_institution(stock_id,market):
    start=(datetime.now(TZ)-timedelta(days=90)).strftime("%Y-%m-%d")
    try:rows=fm("TaiwanStockInstitutionalInvestorsBuySell",stock_id,start)
    except:rows=[]
    if not rows:
        return {"foreign":{"d1":None,"d5":None,"d20":None},"trust":{"d1":None,"d5":None,"d20":None},"dealer":{"d1":None,"d5":None,"d20":None},"total5":None,"signal":"法人資料暫缺","streak":"—","foreign_streak":"—"}
    dates=sorted(set(r.get("date") for r in rows if r.get("date")))
    daily={d:{"foreign":0,"trust":0,"dealer":0} for d in dates}
    for r in rows:
        key=classify_name(str(r.get("name","")))
        if not key:continue
        daily[r["date"]][key]+=((n(r.get("buy")) or 0)-(n(r.get("sell")) or 0))/1000.0
    out={"foreign":{"d1":0,"d5":0,"d20":0},"trust":{"d1":0,"d5":0,"d20":0},"dealer":{"d1":0,"d5":0,"d20":0}}
    for key in ("foreign","trust","dealer"):
        vals=[daily[d][key] for d in dates]
        out[key]["d1"]=sum(vals[-1:]);out[key]["d5"]=sum(vals[-5:]);out[key]["d20"]=sum(vals[-20:])
    totals=[sum(daily[d][k] for k in ("foreign","trust","dealer")) for d in dates]
    total5=sum(totals[-5:])
    signal="中性"
    if total5>0 and out["foreign"]["d5"]>0:signal="法人偏多"
    elif total5>0:signal="內資偏多"
    elif total5<0:signal="法人偏空"
    out["total5"]=total5;out["signal"]=signal
    out["streak"]=streak_label(totals)
    out["foreign_streak"]=streak_label([daily[d]["foreign"] for d in dates])
    out["last_date"]=dates[-1] if dates else None
    return out

def get_cmoney_buzz(stock_id,name):
    url="https://www.cmoney.tw/forum/popular/buzz?tab=popular"
    try:
        r=requests.get(url,headers=UA,timeout=20)
        text=BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)
        return text.count(stock_id)+text.count(name)
    except:return None

def news_sentiment(title):
    pos=sum(1 for w in POS_WORDS if w in title)
    neg=sum(1 for w in NEG_WORDS if w in title)
    score=pos-neg
    return "利多" if score>0 else "利空" if score<0 else "中性"

def get_moneydj_news(stock_id,name):
    q=quote(f'site:moneydj.com "{name}" {stock_id}')
    rss=f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    items=[]
    try:
        r=requests.get(rss,headers=UA,timeout=20);r.raise_for_status()
        root=ET.fromstring(r.text)
        for item in root.findall(".//item")[:6]:
            title=(item.findtext("title") or "").replace(" - MoneyDJ理財網","")
            items.append({"title":title,"url":item.findtext("link") or "","source":"MoneyDJ / Google News","date":item.findtext("pubDate") or "","sentiment":news_sentiment(title)})
    except:pass
    return items


def get_market_institution():
    """TWSE whole-market three-institution net trading value. Official summary is value, not lots."""
    url="https://www.twse.com.tw/rwd/zh/fund/BFI82U?response=json"
    out={"date":None,"foreign":None,"trust":None,"dealer":None,"total":None,"unit":"億元"}
    try:
        j=requests.get(url,headers=UA,timeout=20).json()
        out["date"]=j.get("date")
        for row in j.get("data",[]):
            label=str(row[0])
            diff=n(row[-1])
            if diff is None:continue
            val=diff/100000000
            if label.startswith("外資及陸資"): out["foreign"]=val
            elif label=="投信": out["trust"]=val
            elif label.startswith("自營商"): out["dealer"]=(out["dealer"] or 0)+val
            elif label=="合計": out["total"]=val
        if out["total"] is None:
            vals=[x for x in (out["foreign"],out["trust"],out["dealer"]) if x is not None]
            out["total"]=sum(vals) if len(vals)==3 else None
    except Exception as e:
        out["error"]=str(e)
    return out

def news_region(title):
    intl=["美國","美股","華爾街","聯準會","Fed","歐洲","歐盟","英國","德國","法國","全球","國際","美元","美債","原油","OPEC","俄羅斯","烏克蘭","中東","以色列"]
    asia=["台灣","台股","台積電","中國","大陸","香港","港股","日本","日股","韓國","韓股","新加坡","印度","亞洲","亞股","人民幣","日圓","韓元"]
    if any(w in title for w in intl): return "international"
    if any(w in title for w in asia): return "asia"
    return "asia"

def get_finance_news():
    urls=[
      ("中央社產經","https://feeds.feedburner.com/rsscna/finance"),
      ("中央社科技","https://feeds.feedburner.com/rsscna/technology")
    ]
    items=[];seen=set()
    for source,url in urls:
        try:
            r=requests.get(url,headers=UA,timeout=20);r.raise_for_status()
            root=ET.fromstring(r.text)
            for item in root.findall(".//item")[:18]:
                title=(item.findtext("title") or "").strip()
                link=(item.findtext("link") or "").strip()
                if not title or title in seen:continue
                seen.add(title)
                items.append({"title":title,"url":link,"source":source,"date":item.findtext("pubDate") or "","sentiment":news_sentiment(title),"region":news_region(title)})
        except:pass
    asia=[x for x in items if x["region"]=="asia"][:8]
    international=[x for x in items if x["region"]=="international"][:8]
    return {"asia":asia,"international":international,"all":items[:16]}

def calc_targets(fwd_eps,pe_hist,latest_pe):
    if fwd_eps is None:return None,None,None,"缺 EPS，暫不估值"
    hist=[x for x in pe_hist if x and 0<x<150]
    if len(hist)>=20:
        low=quantile(hist[-750:],.25);base=quantile(hist[-750:],.50);high=quantile(hist[-750:],.75)
        note="Forward EPS × 歷史 PE 25% / 50% / 75% 分位"
    elif latest_pe:
        low,base,high=latest_pe*.85,latest_pe,latest_pe*1.15
        note="Forward EPS × 目前 PE 的 0.85 / 1.00 / 1.15 倍"
    else:return None,None,None,"缺 PE，暫不估值"
    return fwd_eps*low,fwd_eps*base,fwd_eps*high,note

def valuation_status(close,low,base,high):
    if close is None or low is None:return "待估值"
    if close<=low:return "低於保守價"
    if base is not None and close<=base:return "合理偏低"
    if high is not None and close<=high:return "接近樂觀價"
    return "估值偏熱"

def links(sid,name):
    return {
      "財報狗":f"https://statementdog.com/analysis/{sid}",
      "CMoney":"https://www.cmoney.tw/forum/popular/buzz?tab=popular",
      "MOPS":f"https://mops.twse.com.tw/mops/web/t05st03?TYPEK=all&co_id={sid}",
      "Goodinfo":f"https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID={sid}",
      "MoneyDJ":f"https://www.google.com/search?q={quote('site:moneydj.com '+sid+' '+name)}"
    }


def score_stock(s):
    inst=s.get("institution") or {}
    fundamental=12;chip=12;technical=12;valuation=12
    yoy=s.get("revenue_yoy");mom=s.get("revenue_mom")
    if yoy is not None:
        fundamental += 9 if yoy>=20 else 7 if yoy>=10 else 4 if yoy>0 else -9 if yoy<=-20 else -7 if yoy<=-10 else -4
    if mom is not None: fundamental += 2 if mom>0 else -2
    if s.get("forward_eps") is not None and s.get("eps_ttm") is not None:
        fundamental += 2 if s["forward_eps"]>s["eps_ttm"] else 0
    total5=inst.get("total5")
    if total5 is not None: chip += 9 if total5>1000 else 6 if total5>0 else -9 if total5<-1000 else -6
    fd5=((inst.get("foreign") or {}).get("d5") or 0);td5=((inst.get("trust") or {}).get("d5") or 0)
    chip += 3 if fd5>0 else -3 if fd5<0 else 0
    chip += 2 if td5>0 else -2 if td5<0 else 0
    tr=s.get("trend")
    technical += 11 if tr=="強勢多頭" else 7 if tr=="偏多" else -7 if tr=="偏弱" else -11 if tr=="空頭" else 0
    cp=s.get("change_pct")
    if cp is not None: technical += 2 if cp>0 else -2 if cp<0 else 0
    close=s.get("close");base=s.get("target_base")
    upside=((base/close)-1)*100 if close and base else None
    if upside is not None: valuation += 11 if upside>=30 else 8 if upside>=15 else 4 if upside>=5 else -10 if upside<0 else 1
    if s.get("valuation_status")=="低於保守價": valuation+=3
    if s.get("valuation_status")=="估值偏熱": valuation-=3
    vals=[max(0,min(25,x)) for x in (fundamental,chip,technical,valuation)]
    return {"fundamental":vals[0],"chip":vals[1],"technical":vals[2],"valuation":vals[3],"total":sum(vals)}

def update_score_history(stocks):
    try: history=json.loads(SCORE_HISTORY.read_text(encoding="utf-8")) if SCORE_HISTORY.exists() else {}
    except: history={}
    day=datetime.now(TZ).strftime("%Y-%m-%d")
    for s in stocks:
        sid=s["id"];sc=score_stock(s)
        arr=history.setdefault(sid,[])
        arr=[x for x in arr if x.get("date")!=day]
        arr.append({"date":day,**sc})
        history[sid]=arr[-90:]
        s["score"]=sc
        s["score_history"]=history[sid]
        s["score_change_1d"]=sc["total"]-history[sid][-2]["total"] if len(history[sid])>=2 else None
        s["score_change_5d"]=sc["total"]-history[sid][-6]["total"] if len(history[sid])>=6 else None
    SCORE_HISTORY.write_text(json.dumps(history,ensure_ascii=False,indent=2),encoding="utf-8")
    return history


def decision_zone(s,market_label):
    sc=(s.get("score") or {}).get("total",0)
    inst=s.get("institution") or {}
    total5=inst.get("total5")
    close=s.get("close");base=s.get("target_base")
    upside=((base/close)-1)*100 if close and base else None
    trend=s.get("trend","中性")
    conf=s.get("target_confidence","低")
    reasons=[]
    if sc>=70: reasons.append(f"綜合 {sc} 分")
    elif sc<45: reasons.append(f"綜合僅 {sc} 分")
    if total5 is not None: reasons.append("法人近5日買超" if total5>0 else "法人近5日賣超")
    if trend in ("強勢多頭","偏多"): reasons.append("技術偏多")
    elif trend in ("偏弱","空頭"): reasons.append("技術偏弱")
    if upside is not None and conf!="低":
        if upside>=15: reasons.append(f"基準目標尚有 {upside:.0f}% 空間")
        elif upside<0: reasons.append("現價高於基準目標")
    if sc<45 or (total5 is not None and total5<0 and trend in ("偏弱","空頭")):
        zone="風險警戒"
    elif sc>=75 and upside is not None and upside<5:
        zone="過熱等待"
    elif sc>=70 and total5 is not None and total5>0 and trend in ("強勢多頭","偏多"):
        zone="進場觀察" if market_label!="偏空" else "強勢續追"
    elif sc>=65:
        zone="強勢續追"
    else:
        zone="中性等待"
    return {"zone":zone,"reasons":reasons[:4],"upside":upside}

def get_market_regime(market_inst,stocks):
    weights=[s for s in stocks if s.get("weight") and s.get("close") is not None]
    tech=sum(1 if s.get("trend") in ("強勢多頭","偏多") else -1 if s.get("trend") in ("偏弱","空頭") else 0 for s in weights)
    foreign=market_inst.get("foreign")
    score=tech+(2 if foreign is not None and foreign>0 else -2 if foreign is not None and foreign<0 else 0)
    label="偏多" if score>=3 else "偏空" if score<=-3 else "震盪"
    return {"label":label,"score":score,"weight_breadth":tech,"foreign":foreign,
            "note":"權值股技術廣度＋TWSE 外資當日買賣超"}

def main():
    stocks=[]
    for s in WATCH:
        sid,name,market=s["id"],s["name"],s["market"]
        try:px=get_price_data(sid)
        except:px={}
        close=px.get("close")
        try:pe,inferred_ttm,pe_hist=get_per_eps(sid,close)
        except:pe,inferred_ttm,pe_hist=None,None,[]
        try:qeps=get_quarterly_eps(sid)
        except:qeps=[]
        recent_eps=[x.get("eps") for x in qeps[-4:] if x.get("eps") is not None]
        official_ttm=sum(recent_eps) if len(recent_eps)==4 else None
        ttm=official_ttm if official_ttm is not None else inferred_ttm
        eps_source="近四季官方單季 EPS 加總" if official_ttm is not None else "股價 ÷ PE 反推（備援）"
        try:fwd,g,yoy,mom,recent_revenue=get_revenue_metrics(sid,ttm)
        except:fwd,g,yoy,mom,recent_revenue=ttm,None,None,None,[]
        lo,base,hi,note=calc_targets(fwd,pe_hist,pe)
        confidence="高" if official_ttm is not None and len(pe_hist)>=100 else "中" if official_ttm is not None and len(pe_hist)>=20 else "低"
        if close and base and (base/close<0.45 or base/close>2.5):
            confidence="低"; note += "；模型與現價差距過大，請降低權重"
        try:inst=get_institution(sid,market)
        except:inst={"foreign":{"d1":None,"d5":None,"d20":None},"trust":{"d1":None,"d5":None,"d20":None},"dealer":{"d1":None,"d5":None,"d20":None},"total5":None,"signal":"法人資料暫缺","streak":"—","foreign_streak":"—"}
        news=get_moneydj_news(sid,name)
        news_score=sum(1 if x["sentiment"]=="利多" else -1 if x["sentiment"]=="利空" else 0 for x in news)
        stocks.append({
          "id":sid,"name":name,"market":market,"weight":bool(s.get("weight")),
          "close":close,"change_pct":px.get("change_pct"),
          "eps_ttm":ttm,"eps_source":eps_source,"forward_eps":fwd,"pe":pe,
          "quarterly_eps":qeps,"target_confidence":confidence,
          "revenue_yoy":yoy,"revenue_mom":mom,"revenue_history":recent_revenue,
          "target_low":lo,"target_base":base,"target_high":hi,
          "valuation_note":note,"valuation_status":valuation_status(close,lo,base,hi),
          "trend":px.get("trend","—"),
          "quarter_high":px.get("quarter_high"),"quarter_low":px.get("quarter_low"),
          "buzz_score":get_cmoney_buzz(sid,name),
          "institution":inst,
          "history":px.get("history",[]),
          "news":news,"news_score":news_score,
          "links":links(sid,name)
        })
        time.sleep(.4)

    eligible=[s for s in stocks if s["institution"].get("total5") is not None]
    eligible=sorted(eligible,key=lambda s:s["institution"]["total5"],reverse=True)
    ranking={
      "strongest":[{"id":s["id"],"name":s["name"],"total5":s["institution"]["total5"]} for s in eligible[:3]],
      "weakest":[{"id":s["id"],"name":s["name"],"total5":s["institution"]["total5"]} for s in eligible[-3:][::-1]]
    }

    update_score_history(stocks)
    momentum=sorted([s for s in stocks if s.get("score_change_5d") is not None],key=lambda s:s["score_change_5d"],reverse=True)[:5]
    if not momentum:
        momentum=sorted(stocks,key=lambda s:(s.get("score") or {}).get("total",0),reverse=True)[:5]
    market_inst=get_market_institution()
    market_regime=get_market_regime(market_inst,stocks)
    zones={"進場觀察":[],"強勢續追":[],"過熱等待":[],"風險警戒":[],"中性等待":[]}
    for s in stocks:
        dz=decision_zone(s,market_regime["label"])
        s["decision"]=dz
        zones[dz["zone"]].append({"id":s["id"],"name":s["name"],"score":s["score"]["total"],"reasons":dz["reasons"],"upside":dz["upside"]})
    for key in zones: zones[key]=sorted(zones[key],key=lambda x:x["score"],reverse=True)

    payload={
      "updated_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
      "sources":["FinMind（量化資料，server-side）","TWSE 臺灣證券交易所","中央社財經 RSS","公開資訊觀測站 MOPS","財報狗","Goodinfo","CMoney","MoneyDJ"],
      "ranking":ranking,
      "market_institution":market_inst,
      "market_regime":market_regime,
      "decision_zones":zones,
      "momentum_top5":[{"id":s["id"],"name":s["name"],"score":s["score"]["total"],"change5":s.get("score_change_5d")} for s in momentum],
      "finance_news":get_finance_news(),
      "stocks":stocks
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
