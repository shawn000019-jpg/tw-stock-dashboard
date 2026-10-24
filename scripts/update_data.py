import json, math, statistics, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/latest.json"
TZ=timezone(timedelta(hours=8))
API="https://api.finmindtrade.com/api/v4/data"
UA={"User-Agent":"Mozilla/5.0 (compatible; StockDashboard/3.0)"}

WATCH=[
    {"id":"4556","name":"旭然","market":"TPEx"},
    {"id":"7556","name":"意德士","market":"TPEx"},
    {"id":"5297","name":"廣化","market":"Emerging"},
    {"id":"7887","name":"宇川精材","market":"Emerging"},
    {"id":"3680","name":"家登","market":"TPEx"},
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
    byyear={}
    for r in epsrows:
        d=datetime.fromisoformat(r["date"]);q=(d.month-1)//3+1
        byyear.setdefault(d.year,{})[q]=n(r.get("value"))
    out=[]
    for y in sorted(byyear):
        prevcum=0
        for q in range(1,5):
            if q not in byyear[y]:continue
            cum=byyear[y][q]
            standalone=cum if q==1 else (cum-prevcum if cum is not None and prevcum is not None else cum)
            out.append({"quarter":f"{y}Q{q}","eps":standalone,"reported_eps":cum})
            prevcum=cum
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

def main():
    stocks=[]
    for s in WATCH:
        sid,name,market=s["id"],s["name"],s["market"]
        try:px=get_price_data(sid)
        except:px={}
        close=px.get("close")
        try:pe,ttm,pe_hist=get_per_eps(sid,close)
        except:pe,ttm,pe_hist=None,None,[]
        try:fwd,g,yoy,mom,recent_revenue=get_revenue_metrics(sid,ttm)
        except:fwd,g,yoy,mom,recent_revenue=ttm,None,None,None,[]
        try:qeps=get_quarterly_eps(sid)
        except:qeps=[]
        lo,base,hi,note=calc_targets(fwd,pe_hist,pe)
        try:inst=get_institution(sid,market)
        except:inst={"foreign":{"d1":None,"d5":None,"d20":None},"trust":{"d1":None,"d5":None,"d20":None},"dealer":{"d1":None,"d5":None,"d20":None},"total5":None,"signal":"法人資料暫缺","streak":"—","foreign_streak":"—"}
        news=get_moneydj_news(sid,name)
        news_score=sum(1 if x["sentiment"]=="利多" else -1 if x["sentiment"]=="利空" else 0 for x in news)
        stocks.append({
          "id":sid,"name":name,"market":market,
          "close":close,"change_pct":px.get("change_pct"),
          "eps_ttm":ttm,"forward_eps":fwd,"pe":pe,
          "quarterly_eps":qeps,
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

    payload={
      "updated_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
      "sources":["FinMind（量化資料，server-side）","公開資訊觀測站 MOPS","財報狗","Goodinfo","CMoney","MoneyDJ"],
      "ranking":ranking,
      "stocks":stocks
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
