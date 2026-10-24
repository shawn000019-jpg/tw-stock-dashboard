import json, re, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote
import requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data/latest.json"
WATCH=[("4556","旭然"),("7556","意德士"),("5297","廣化"),("7887","宇川精材"),("3680","家登")]
UA={"User-Agent":"Mozilla/5.0 (compatible; StockDashboard/1.0)"}
TZ=timezone(timedelta(hours=8))

def get(url,timeout=25):
    r=requests.get(url,headers=UA,timeout=timeout)
    r.raise_for_status()
    return r.text

def num(x):
    try:return float(str(x).replace(",","").replace("%","").strip())
    except:return None

def statementdog(stock_id):
    url=f"https://statementdog.com/analysis/{stock_id}"
    out={"url":url}
    try:
        html=get(url); txt=BeautifulSoup(html,"html.parser").get_text(" ",strip=True)
        pats={
          "pe":r"本益比\s*\(倍\)\s*([0-9.]+)",
          "eps":r"近\s*4\s*季EPS\s*\(元\)\s*([\-0-9.]+)",
          "roe":r"近\s*4\s*季ROE\s*\(%\)\s*([\-0-9.]+)",
          "close":r"收盤價[：:]\s*([0-9.]+)"
        }
        for k,p in pats.items():
            m=re.search(p,txt,re.I)
            if m: out[k]=num(m.group(1))
    except Exception as e: out["error"]=str(e)
    return out

def cmoney(stock_id,name):
    url="https://www.cmoney.tw/forum/popular/buzz?tab=popular"
    out={"url":url,"buzz_score":None}
    try:
        html=get(url); text=BeautifulSoup(html,"html.parser").get_text(" ",strip=True)
        out["buzz_score"]=text.count(stock_id)+text.count(name)
    except Exception as e: out["error"]=str(e)
    return out

def moneydj_search(stock_id,name):
    q=quote(f"site:moneydj.com {stock_id} {name}")
    return f"https://www.google.com/search?q={q}"

def goodinfo_link(stock_id):
    return f"https://goodinfo.tw/tw/StockDetail.asp?STOCK_ID={stock_id}"

def mops_link(stock_id):
    return f"https://mops.twse.com.tw/mops/web/t05st03?TYPEK=all&co_id={stock_id}"

def calc_targets(close,eps,pe):
    if not(close and eps and pe and eps>0 and pe>0): return None,None,None,"缺 EPS/PE，暫不估值"
    low_pe=max(5,pe*0.85); base_pe=pe; high_pe=pe*1.15
    return eps*low_pe,eps*base_pe,eps*high_pe,"以近4季 EPS × 當前 PE 的 0.85 / 1.00 / 1.15 倍做情境"

def dummy_institution():
    return {"foreign":{"d1":None,"d5":None,"d20":None},
            "trust":{"d1":None,"d5":None,"d20":None},
            "dealer":{"d1":None,"d5":None,"d20":None},
            "total5":None,"signal":"待取得"}

def main():
    stocks=[]
    for sid,name in WATCH:
        sd=statementdog(sid); cm=cmoney(sid,name)
        close=sd.get("close"); eps=sd.get("eps"); pe=sd.get("pe")
        low,base,high,note=calc_targets(close,eps,pe)
        stocks.append({
          "id":sid,"name":name,"close":close,"change_pct":None,
          "eps_ttm":eps,"pe":pe,"roe":sd.get("roe"),
          "target_low":low,"target_base":base,"target_high":high,
          "valuation_note":note,"trend":"待歷史價格",
          "quarter_high":None,"quarter_low":None,
          "buzz_score":cm.get("buzz_score"),
          "institution":dummy_institution(),
          "history":[],"news":[],
          "links":{
            "財報狗":sd["url"],"CMoney":cm["url"],"MOPS":mops_link(sid),
            "Goodinfo":goodinfo_link(sid),"MoneyDJ":moneydj_search(sid,name)
          }
        })
        time.sleep(1)
    payload={
      "updated_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
      "sources":["公開資訊觀測站 MOPS","財報狗","Goodinfo","CMoney","MoneyDJ"],
      "stocks":stocks
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")

if __name__=="__main__": main()
