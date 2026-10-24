import json, math, statistics, time, re
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
UA={"User-Agent":"Mozilla/5.0 (compatible; StockDashboard/2.0)"}

WATCH=[
    {"id":"4556","name":"旭然","market":"TPEx"},
    {"id":"7556","name":"意德士","market":"TPEx"},
    {"id":"5297","name":"廣化","market":"Emerging"},
    {"id":"7887","name":"宇川精材","market":"Emerging"},
    {"id":"3680","name":"家登","market":"TPEx"},
]

def n(v):
    try:
        if v is None: return None
        return float(str(v).replace(",","").replace("%","").strip())
    except:
        return None

def fm(dataset, stock_id, start_date, end_date=None):
    params={"dataset":dataset,"data_id":stock_id,"start_date":start_date}
    if end_date: params["end_date"]=end_date
    r=requests.get(API,params=params,headers=UA,timeout=30)
    r.raise_for_status()
    j=r.json()
    if j.get("status") not in (None,200):
        raise RuntimeError(j.get("msg","FinMind API error"))
    return j.get("data",[])

def sma(vals, k):
    out=[]
    for i in range(len(vals)):
        if i+1<k: out.append(None)
        else: out.append(sum(vals[i+1-k:i+1])/k)
    return out

def median(a):
    a=[x for x in a if x is not None and math.isfinite(x)]
    return statistics.median(a) if a else None

def quantile(a,q):
    a=sorted([x for x in a if x is not None and math.isfinite(x)])
    if not a: return None
    pos=(len(a)-1)*q
    lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    if lo==hi:return a[lo]
    return a[lo]+(a[hi]-a[lo])*(pos-lo)

def pct(a,b):
    return ((a/b)-1)*100 if a is not None and b not in (None,0) else None

def get_price_data(stock_id):
    start=(datetime.now(TZ)-timedelta(days=1600)).strftime("%Y-%m-%d")
    rows=fm("TaiwanStockPrice",stock_id,start)
    rows=sorted(rows,key=lambda x:x.get("date",""))
    if not rows:return {}
    closes=[n(x.get("close")) for x in rows]
    valid=[x for x in closes if x is not None]
    if not valid:return {}
    m20=sma(closes,20);m60=sma(closes,60);m120=sma(closes,120)
    hist=[]
    for i,r in enumerate(rows[-260:]):
        src_i=len(rows)-len(rows[-260:])+i
        hist.append({
            "date":r.get("date"),
            "close":n(r.get("close")),
            "ma20":m20[src_i],
            "ma60":m60[src_i],
            "ma120":m120[src_i],
        })
    last=rows[-1]; prev=rows[-2] if len(rows)>1 else rows[-1]
    close=n(last.get("close")); prevc=n(prev.get("close"))
    trend="中性"
    a,b,c=m20[-1],m60[-1],m120[-1]
    if None not in (close,a,b,c):
        if close>a>b>c: trend="強勢多頭"
        elif close>a>b: trend="偏多"
        elif close<a<b<c: trend="空頭"
        elif close<a: trend="偏弱"
    # current quarter
    d=datetime.fromisoformat(last["date"])
    qstart_month=((d.month-1)//3)*3+1
    qstart=datetime(d.year,qstart_month,1)
    qrows=[r for r in rows if datetime.fromisoformat(r["date"])>=qstart]
    highs=[n(r.get("max")) for r in qrows if n(r.get("max")) is not None]
    lows=[n(r.get("min")) for r in qrows if n(r.get("min")) is not None]
    return {
        "close":close,
        "change_pct":pct(close,prevc),
        "trend":trend,
        "quarter_high":max(highs) if highs else None,
        "quarter_low":min(lows) if lows else None,
        "history":hist,
    }

def get_per_eps(stock_id, close):
    start=(datetime.now(TZ)-timedelta(days=1600)).strftime("%Y-%m-%d")
    try: rows=fm("TaiwanStockPER",stock_id,start)
    except: rows=[]
    rows=sorted(rows,key=lambda x:x.get("date",""))
    pes=[n(x.get("PER")) for x in rows]
    pes=[x for x in pes if x is not None and 0<x<200]
    pe=pes[-1] if pes else None
    eps=(close/pe) if close and pe else None
    return pe,eps,pes

def get_forward_eps(stock_id, ttm_eps):
    start=(datetime.now(TZ)-timedelta(days=900)).strftime("%Y-%m-%d")
    try: rows=fm("TaiwanStockMonthRevenue",stock_id,start)
    except: rows=[]
    growth=[]
    for r in rows[-6:]:
        for k in ("revenue_year_growth_rate","revenue_year_growth"):
            v=n(r.get(k))
            if v is not None:
                growth.append(v);break
    g=median(growth[-3:]) if growth else None
    if g is not None:g=max(-30,min(50,g))/100
    fwd=ttm_eps*(1+g) if ttm_eps is not None and g is not None else ttm_eps
    return fwd,g

def get_institution(stock_id, market):
    if market=="Emerging":
        return {
          "foreign":{"d1":None,"d5":None,"d20":None},
          "trust":{"d1":None,"d5":None,"d20":None},
          "dealer":{"d1":None,"d5":None,"d20":None},
          "total5":None,"signal":"興櫃無標準三大法人日表"
        }
    start=(datetime.now(TZ)-timedelta(days=60)).strftime("%Y-%m-%d")
    try: rows=fm("TaiwanStockInstitutionalInvestorsBuySell",stock_id,start)
    except: rows=[]
    if not rows:
        return {
          "foreign":{"d1":None,"d5":None,"d20":None},
          "trust":{"d1":None,"d5":None,"d20":None},
          "dealer":{"d1":None,"d5":None,"d20":None},
          "total5":None,"signal":"法人資料暫缺"
        }
    dates=sorted(set(r.get("date") for r in rows if r.get("date")))
    last=dates[-1]
    pos={d:i for i,d in enumerate(dates)}
    out={"foreign":{"d1":0,"d5":0,"d20":0},"trust":{"d1":0,"d5":0,"d20":0},"dealer":{"d1":0,"d5":0,"d20":0}}
    for r in rows:
        name=str(r.get("name",""))
        if "Foreign" in name or "外資" in name: key="foreign"
        elif "Investment_Trust" in name or "投信" in name: key="trust"
        elif "Dealer" in name or "自營" in name: key="dealer"
        else: continue
        buy=n(r.get("buy")) or 0
        sell=n(r.get("sell")) or 0
        net=(buy-sell)/1000.0  # shares -> lots
        idx=pos[r["date"]]; li=len(dates)-1
        if idx==li: out[key]["d1"]+=net
        if idx>=li-4: out[key]["d5"]+=net
        if idx>=li-19: out[key]["d20"]+=net
    total5=sum(out[k]["d5"] for k in ("foreign","trust","dealer"))
    if total5>0 and out["foreign"]["d5"]>0: signal="法人偏多"
    elif total5>0: signal="內資偏多"
    elif total5<0: signal="法人偏空"
    else: signal="中性"
    out["total5"]=total5;out["signal"]=signal
    return out

def get_cmoney_buzz(stock_id,name):
    url="https://www.cmoney.tw/forum/popular/buzz?tab=popular"
    try:
        r=requests.get(url,headers=UA,timeout=20)
        text=BeautifulSoup(r.text,"html.parser").get_text(" ",strip=True)
        return text.count(stock_id)+text.count(name)
    except:
        return None

def get_moneydj_news(stock_id,name):
    q=quote(f'site:moneydj.com "{name}" {stock_id}')
    rss=f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    items=[]
    try:
        r=requests.get(rss,headers=UA,timeout=20);r.raise_for_status()
        root=ET.fromstring(r.text)
        for item in root.findall(".//item")[:5]:
            items.append({
              "title":(item.findtext("title") or "").replace(" - MoneyDJ理財網",""),
              "url":item.findtext("link") or "",
              "source":"MoneyDJ / Google News",
              "date":item.findtext("pubDate") or ""
            })
    except: pass
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
    else:
        return None,None,None,"缺 PE，暫不估值"
    return fwd_eps*low,fwd_eps*base,fwd_eps*high,note

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
        try: px=get_price_data(sid)
        except Exception as e: px={}
        close=px.get("close")
        try: pe,ttm,pe_hist=get_per_eps(sid,close)
        except: pe,ttm,pe_hist=None,None,[]
        try: fwd,g=get_forward_eps(sid,ttm)
        except: fwd,g=ttm,None
        lo,base,hi,note=calc_targets(fwd,pe_hist,pe)
        try: inst=get_institution(sid,market)
        except: inst={"foreign":{"d1":None,"d5":None,"d20":None},"trust":{"d1":None,"d5":None,"d20":None},"dealer":{"d1":None,"d5":None,"d20":None},"total5":None,"signal":"法人資料暫缺"}
        stocks.append({
          "id":sid,"name":name,"market":market,
          "close":close,"change_pct":px.get("change_pct"),
          "eps_ttm":ttm,"forward_eps":fwd,"pe":pe,
          "target_low":lo,"target_base":base,"target_high":hi,
          "valuation_note":note,
          "trend":px.get("trend","—"),
          "quarter_high":px.get("quarter_high"),"quarter_low":px.get("quarter_low"),
          "buzz_score":get_cmoney_buzz(sid,name),
          "institution":inst,
          "history":px.get("history",[]),
          "news":get_moneydj_news(sid,name),
          "links":links(sid,name)
        })
        time.sleep(.5)
    payload={
      "updated_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
      "sources":["FinMind（量化資料，server-side）","公開資訊觀測站 MOPS","財報狗","Goodinfo","CMoney","MoneyDJ"],
      "stocks":stocks
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
