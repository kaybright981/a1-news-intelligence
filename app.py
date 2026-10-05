from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import hashlib
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

APP_TITLE = "A1 News Intelligence API"
DB_PATH = os.getenv("A1_DB_PATH", str(Path(__file__).with_name("a1_news.db")))

app = FastAPI(title=APP_TITLE, version="1.0.0")
db_lock = threading.Lock()

# Nigeria: 36 states + FCT.
NIGERIA_STATES = [
    "Abia","Adamawa","Akwa Ibom","Anambra","Bauchi","Bayelsa","Benue","Borno",
    "Cross River","Delta","Ebonyi","Edo","Ekiti","Enugu","Gombe","Imo",
    "Jigawa","Kaduna","Kano","Katsina","Kebbi","Kogi","Kwara","Lagos",
    "Nasarawa","Niger","Ogun","Ondo","Osun","Oyo","Plateau","Rivers",
    "Sokoto","Taraba","Yobe","Zamfara","Federal Capital Territory"
]

SECURITY_TERMS = {
    "terror","terrorist","terrorism","kidnap","kidnapping","abduction","bandit",
    "banditry","attack","bomb","bombing","explosion","coup","war","military",
    "insurgency","piracy","hostage","airstrike","security alert","arms",
    "firearm","ammunition","cultism","robbery","murder","border","jihadist",
    "militant","troops","soldiers","police","dss","nafs","na","nigeria police",
    "maritime security","oil theft","pipeline vandalism"
}

HIGH_PRIORITY_TERMS = {
    "terrorist","terrorism","kidnapping","kidnap","abduction","bombing",
    "explosion","coup","airstrike","hostage","massacre","attack","war"
}

# Official/high-value sources. More can be added through POST /sources.
# The design intentionally stores source weight separately from the story score.
DEFAULT_SOURCES = [
    {"name":"DSS","domain":"dss.gov.ng","url":"https://dss.gov.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Nigeria Police Force","domain":"police.gov.ng","url":"https://police.gov.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Nigerian Air Force","domain":"airforce.mil.ng","url":"https://airforce.mil.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Nigerian Army","domain":"army.mil.ng","url":"https://army.mil.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Nigerian Navy","domain":"navy.mil.ng","url":"https://navy.mil.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"NEMA","domain":"nema.gov.ng","url":"https://nema.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"NiMet","domain":"nimet.gov.ng","url":"https://nimet.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"NIMASA","domain":"nimasa.gov.ng","url":"https://nimasa.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"FRSC","domain":"frsc.gov.ng","url":"https://frsc.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"NDLEA","domain":"ndlea.gov.ng","url":"https://ndlea.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"EFCC","domain":"efcc.gov.ng","url":"https://efcc.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"ICPC","domain":"icpc.gov.ng","url":"https://icpc.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"Nigeria Customs Service","domain":"customs.gov.ng","url":"https://customs.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"Nigeria Immigration Service","domain":"immigration.gov.ng","url":"https://immigration.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"Nigerian Ports Authority","domain":"nigerianports.gov.ng","url":"https://nigerianports.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"State House","domain":"statehouse.gov.ng","url":"https://statehouse.gov.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Ministry of Defence","domain":"defence.gov.ng","url":"https://defence.gov.ng/","weight":100,"official":True,"country":"Nigeria"},
    {"name":"Ministry of Foreign Affairs","domain":"foreignaffairs.gov.ng","url":"https://foreignaffairs.gov.ng/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"INEC","domain":"inecnigeria.org","url":"https://www.inecnigeria.org/","weight":95,"official":True,"country":"Nigeria"},
    {"name":"NCDC","domain":"ncdc.gov.ng","url":"https://ncdc.gov.ng/","weight":90,"official":True,"country":"Nigeria"},
    {"name":"The Presidency","domain":"president.gov.ng","url":"https://president.gov.ng/","weight":100,"official":True,"country":"Nigeria"},
]

# A broad starter registry. Each entry is deliberately labelled as media/non-official;
# official agencies above retain the highest trust tier.
MEDIA_SOURCES = [
    ("Channels Television","channelstv.com"),("Premium Times","premiumtimesng.com"),
    ("The Guardian Nigeria","guardian.ng"),("Punch","punchng.com"),("Vanguard","vanguardngr.com"),
    ("Daily Trust","dailytrust.com"),("ThisDay","thisdaylive.com"),("The Nation","thenationonlineng.net"),
    ("BusinessDay","businessday.ng"),("The Cable","thecable.ng"),("Sahara Reporters","saharareporters.com"),
    ("Daily Post","dailypost.ng"),("Leadership","leadership.ng"),("Tribune","tribuneonlineng.com"),
    ("Independent Nigeria","independent.ng"),("Blueprint","blueprint.ng"),("NAN","nannews.ng"),
    ("Arise News","arise.tv"),("TV360 Nigeria","tv360nigeria.com"),("AIT","ait.live"),
    ("BBC News","bbc.com"),("Reuters","reuters.com"),("Associated Press","apnews.com"),
    ("Al Jazeera","aljazeera.com"),("France 24","france24.com"),("DW","dw.com"),
    ("Voice of America","voanews.com"),("CNN","cnn.com"),("The Guardian","theguardian.com"),
    ("New York Times","nytimes.com"),("Washington Post","washingtonpost.com"),
    ("Financial Times","ft.com"),("Bloomberg","bloomberg.com"),("The Economist","economist.com"),
    ("Sky News","news.sky.com"),("The Telegraph","telegraph.co.uk"),("The Times","thetimes.com"),
    ("Deutsche Welle Africa","dw.com"),("Africa Report","theafricareport.com"),
    ("Africanews","africanews.com"),("AllAfrica","allafrica.com"),("African Arguments","africanarguments.org"),
    ("Jeune Afrique","jeuneafrique.com"),("The Africa Center","africacenter.org"),
    ("ISS Africa","issafrica.org"),("ACLED","acleddata.com"),("Crisis Group","crisisgroup.org"),
    ("UN News","news.un.org"),("UN Security Council","un.org"),("UN OCHA","unocha.org"),
    ("UNHCR","unhcr.org"),("WHO Africa","who.int"),("IOM","iom.int"),
    ("INTERPOL","interpol.int"),("Europol","europol.europa.eu"),("NATO","nato.int"),
    ("African Union","au.int"),("ECOWAS","ecowas.int"),("World Bank","worldbank.org"),
    ("IMF","imf.org"),("US State Department","state.gov"),("UK Government","gov.uk"),
    ("EU External Action","eeas.europa.eu"),("US AFRICOM","africom.mil"),
    ("UK FCDO","gov.uk"),("Maritime Executive","maritime-executive.com"),
    ("gCaptain","gcaptain.com"),("Lloyd's List","lloydslist.com"),("Defense News","defensenews.com"),
    ("Military Africa","military.africa"),("Defense Post","thedefensepost.com"),
    ("Janes","janes.com"),("Breaking Defense","breakingdefense.com"),
    ("War on the Rocks","warontherocks.com"),("Foreign Policy","foreignpolicy.com"),
    ("Foreign Affairs","foreignaffairs.com"),("CSIS","csis.org"),("Brookings","brookings.edu"),
    ("Chatham House","chathamhouse.org"),("RUSI","rusi.org"),("Carnegie","carnegieendowment.org"),
    ("CFR","cfr.org"),("ACSS","africacenter.org"),("ReliefWeb","reliefweb.int"),
    ("Global Initiative","globalinitiative.net"),("GI-TOC","globalinitiative.net"),
    ("Human Rights Watch","hrw.org"),("Amnesty International","amnesty.org"),
    ("International Crisis Group","crisisgroup.org"),("ISS Today","issafrica.org"),
    ("The New Humanitarian","thenewhumanitarian.org"),("Devex","devex.com"),
    ("Nature News","nature.com"),("Science","science.org"),("New Scientist","newscientist.com"),
    ("Space.com","space.com"),("NASA","nasa.gov"),("NOAA","noaa.gov"),
    ("USGS","usgs.gov"),("FAO","fao.org"),("UNDP","undp.org"),
    ("UNICEF","unicef.org"),("UNESCO","unesco.org"),("WFP","wfp.org"),
    ("ILO","ilo.org"),("ICAO","icao.int"),("IMO","imo.org"),("WTO","wto.org"),
    ("Interpol News","interpol.int"),("Frontex","frontex.europa.eu"),
    ("ACAPS","acaps.org"),("FEWS NET","fews.net"),("SIPRI","sipri.org"),
    ("Small Arms Survey","smallarmssurvey.org"),("Global Terrorism Database","umd.edu"),
    ("Our World in Data","ourworldindata.org"),("Statista","statista.com"),
]

EXTRA_OFFICIAL_SOURCES = [('Federal Road Safety Corps', 'frsc.gov.ng'), ('Nigeria Security and Civil Defence Corps', 'nscdc.gov.ng'), ('National Drug Law Enforcement Agency', 'ndlea.gov.ng'), ('National Orientation Agency', 'noa.gov.ng'), ('Office of the National Security Adviser', 'statehouse.gov.ng'), ('National Identity Management Commission', 'nimc.gov.ng'), ('Nigeria Data Protection Commission', 'ndpc.gov.ng'), ('Nigerian Communications Commission', 'ncc.gov.ng'), ('Nigerian Electricity Regulatory Commission', 'nerc.gov.ng'), ('Nigerian Upstream Regulatory Commission', 'nuprc.gov.ng'), ('Nigerian Midstream and Downstream Petroleum Regulatory Authority', 'nmdpra.gov.ng'), ('Economic and Financial Crimes Commission', 'efcc.gov.ng'), ('Code of Conduct Bureau', 'ccb.gov.ng'), ('National Agency for Food and Drug Administration and Control', 'nafdac.gov.ng'), ('Standards Organisation of Nigeria', 'son.gov.ng'), ('National Bureau of Statistics', 'nigerianstat.gov.ng'), ('National Emergency Management Agency', 'nema.gov.ng'), ('Nigerian Maritime Administration and Safety Agency', 'nimasa.gov.ng'), ('Nigerian Communications Commission News', 'ncc.gov.ng'), ('Federal Ministry of Interior', 'interior.gov.ng'), ('Federal Ministry of Justice', 'justice.gov.ng'), ('Federal Ministry of Environment', 'environment.gov.ng'), ('Federal Ministry of Aviation and Aerospace Development', 'aviation.gov.ng'), ('Federal Ministry of Marine and Blue Economy', 'marineandblue.gov.ng'), ('Federal Ministry of Agriculture', 'fmard.gov.ng'), ('Federal Ministry of Health', 'health.gov.ng'), ('Federal Ministry of Foreign Affairs', 'foreignaffairs.gov.ng'), ('National Health Insurance Authority', 'nhia.gov.ng'), ('National Agency for the Control of AIDS', 'naca.gov.ng'), ('Nigerian Export Promotion Council', 'nepc.gov.ng'), ('Nigerian Investment Promotion Commission', 'nipc.gov.ng'), ('Nigerian Content Development and Monitoring Board', 'ncdmb.gov.ng'), ('Nigerian Nuclear Regulatory Authority', 'nnra.gov.ng'), ('Nigerian Meteorological Agency', 'nimet.gov.ng'), ('Nigerian Geological Survey Agency', 'ngsa.gov.ng'), ('Nigerian Hydrological Agency', 'nihsa.gov.ng'), ('National Inland Waterways Authority', 'niwa.gov.ng'), ('Niger Delta Development Commission', 'nddc.gov.ng'), ('Nigerian Governors Forum', 'nggovernorsforum.org'), ('Association of Local Governments of Nigeria', 'algon.org.ng')]

def init_db():
    with db_lock, sqlite3.connect(DB_PATH) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS sources(
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, domain TEXT,
            url TEXT, weight INTEGER, official INTEGER, country TEXT, active INTEGER DEFAULT 1)""")
        db.execute("""CREATE TABLE IF NOT EXISTS stories(
            id INTEGER PRIMARY KEY AUTOINCREMENT, fingerprint TEXT UNIQUE,
            title TEXT, source TEXT, text TEXT, url TEXT, country TEXT,
            state TEXT, category TEXT, score INTEGER, status TEXT,
            published_at TEXT, created_at TEXT)""")
        for s in DEFAULT_SOURCES:
            db.execute("""INSERT OR IGNORE INTO sources
                (name,domain,url,weight,official,country) VALUES(?,?,?,?,?,?)""",
                (s["name"],s["domain"],s["url"],s["weight"],int(s["official"]),s["country"]))
        for name, domain in MEDIA_SOURCES:
            db.execute("""INSERT OR IGNORE INTO sources
                (name,domain,url,weight,official,country) VALUES(?,?,?,?,?,?)""",
                (name,domain,"https://"+domain,70,0,"International/Nigeria"))
        for name, domain in EXTRA_OFFICIAL_SOURCES:
            db.execute("""INSERT OR IGNORE INTO sources
                (name,domain,url,weight,official,country) VALUES(?,?,?,?,?,?)""",
                (name,domain,"https://"+domain,90,1,"Nigeria"))
        db.commit()

init_db()

class Story(BaseModel):
    title: str
    source: str
    text: str
    url: Optional[str] = None
    country: str = "Nigeria"
    state: Optional[str] = None
    category: str = "General"
    published_at: Optional[str] = None

class Source(BaseModel):
    name: str
    domain: str
    url: str
    weight: int = Field(default=70, ge=0, le=100)
    official: bool = False
    country: str = "Nigeria"
    active: bool = True

def source_info(name: str):
    with sqlite3.connect(DB_PATH) as db:
        row = db.execute("SELECT name,domain,url,weight,official,country,active FROM sources WHERE lower(name)=lower(?)", (name,)).fetchone()
    if not row:
        return {"name": name, "weight": 50, "official": False, "active": True}
    return {"name":row[0],"domain":row[1],"url":row[2],"weight":row[3],"official":bool(row[4]),"country":row[5],"active":bool(row[6])}

def classify(text: str):
    t = text.lower()
    security_hits = [x for x in SECURITY_TERMS if x in t]
    high_hits = [x for x in HIGH_PRIORITY_TERMS if x in t]
    if high_hits:
        category = "Security"
    elif security_hits:
        category = "Security"
    else:
        category = "General"
    return category, security_hits, high_hits

def score_story(story: Story):
    info = source_info(story.source)
    category, security_hits, high_hits = classify(story.title + " " + story.text)
    score = info["weight"]
    score += min(15, len(security_hits) * 2)
    score += min(10, len(high_hits) * 2)
    if story.country.lower() == "nigeria":
        score += 3
    score = min(100, score)

    # "CONFIRMED" is reserved for high-trust official sources, not keyword hits alone.
    if info["official"] and score >= 95:
        status = "CONFIRMED"
    elif score >= 85:
        status = "HIGH PRIORITY"
    elif score >= 70:
        status = "DEVELOPING"
    else:
        status = "MONITOR"

    return score, status, category, security_hits

def fingerprint(story: Story):
    raw = re.sub(r"\s+", " ", (story.title + "|" + story.source + "|" + (story.url or "")).strip().lower())
    return hashlib.sha256(raw.encode()).hexdigest()

def save_story(story: Story, score: int, status: str, category: str):
    fp = fingerprint(story)
    now = datetime.now(timezone.utc).isoformat()
    with db_lock, sqlite3.connect(DB_PATH) as db:
        cur = db.execute("""INSERT OR IGNORE INTO stories
            (fingerprint,title,source,text,url,country,state,category,score,status,published_at,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fp,story.title,story.source,story.text,story.url,story.country,story.state,
             category,score,status,story.published_at,now))
        db.commit()
        return cur.rowcount == 1

def format_whatsapp(story: Story, score: int, status: str, category: str):
    location = story.state or story.country
    return (
        f"*A1 NEWS ALERT*\n\n"
        f"*{story.title}*\n\n"
        f"Source: {story.source}\n"
        f"Location: {location}\n"
        f"Category: {category}\n"
        f"Status: {status}\n"
        f"Reliability score: {score}/100\n\n"
        f"{story.text[:900]}\n\n"
        f"{story.url or ''}"
    )

@app.get("/health")
def health():
    return {"status":"ok","service":APP_TITLE,"time":datetime.now(timezone.utc).isoformat()}

@app.get("/states")
def states():
    return {"count": len(NIGERIA_STATES), "states": NIGERIA_STATES}

@app.get("/sources")
def sources(active_only: bool = True):
    with sqlite3.connect(DB_PATH) as db:
        q = "SELECT name,domain,url,weight,official,country,active FROM sources"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY weight DESC, name"
        rows = db.execute(q).fetchall()
    return {"count":len(rows),"sources":[
        {"name":r[0],"domain":r[1],"url":r[2],"weight":r[3],"official":bool(r[4]),"country":r[5],"active":bool(r[6])}
        for r in rows]}

@app.post("/sources")
def add_source(source: Source):
    with db_lock, sqlite3.connect(DB_PATH) as db:
        db.execute("""INSERT INTO sources(name,domain,url,weight,official,country,active)
                      VALUES(?,?,?,?,?,?,?)
                      ON CONFLICT(name) DO UPDATE SET domain=excluded.domain,url=excluded.url,
                      weight=excluded.weight,official=excluded.official,country=excluded.country,
                      active=excluded.active""",
                   (source.name,source.domain,source.url,source.weight,int(source.official),
                    source.country,int(source.active)))
        db.commit()
    return {"status":"saved","source":source.model_dump()}

@app.post("/score")
def score(story: Story):
    score, status, category, hits = score_story(story)
    return {"score":score,"status":status,"category":category,"security_terms":hits,"story":story.model_dump()}

@app.post("/ingest")
def ingest(story: Story):
    score, status, category, hits = score_story(story)
    inserted = save_story(story,score,status,category)
    return {
        "inserted": inserted, "score":score, "status":status, "category":category,
        "security_terms":hits, "whatsapp_preview":format_whatsapp(story,score,status,category)
    }

@app.get("/stories")
def stories(limit: int = 50, category: Optional[str] = None, state: Optional[str] = None):
    limit = max(1, min(limit, 200))
    sql = """SELECT id,title,source,text,url,country,state,category,score,status,published_at,created_at
             FROM stories WHERE 1=1"""
    params = []
    if category:
        sql += " AND lower(category)=lower(?)"; params.append(category)
    if state:
        sql += " AND lower(state)=lower(?)"; params.append(state)
    sql += " ORDER BY score DESC, created_at DESC LIMIT ?"; params.append(limit)
    with sqlite3.connect(DB_PATH) as db:
        rows = db.execute(sql, params).fetchall()
    fields = ["id","title","source","text","url","country","state","category","score","status","published_at","created_at"]
    return {"count":len(rows),"stories":[dict(zip(fields,r)) for r in rows]}

@app.get("/whatsapp/test")
def whatsapp_test():
    configured = all(os.getenv(k) for k in [
        "WA_PHONE_NUMBER_ID","CLOUD_API_ACCESS_TOKEN","WA_RECIPIENT"
    ])
    return {
        "status":"ready" if configured else "not_configured",
        "message":"WhatsApp Cloud API credentials are required for production sending.",
        "required_env":["WA_PHONE_NUMBER_ID","CLOUD_API_ACCESS_TOKEN","WA_RECIPIENT"]
    }

@app.post("/whatsapp/send")
def whatsapp_send(story: Story):
    # Kept deliberately dependency-free. Meta Cloud API is called only when credentials exist.
    phone_id = os.getenv("WA_PHONE_NUMBER_ID")
    token = os.getenv("CLOUD_API_ACCESS_TOKEN")
    recipient = os.getenv("WA_RECIPIENT")
    if not all([phone_id,token,recipient]):
        raise HTTPException(503, "WhatsApp is not configured. Set WA_PHONE_NUMBER_ID, CLOUD_API_ACCESS_TOKEN and WA_RECIPIENT.")
    score, status, category, _ = score_story(story)
    body = format_whatsapp(story,score,status,category)
    api_version = os.getenv("CLOUD_API_VERSION","v23.0")
    url = f"https://graph.facebook.com/{api_version}/{phone_id}/messages"
    payload = ('{"messaging_product":"whatsapp","to":'+__import__("json").dumps(recipient)+
               ',"type":"text","text":{"body":'+__import__("json").dumps(body)+'}}').encode()
    req = urllib.request.Request(url,data=payload,headers={
        "Authorization":"Bearer "+token,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return {"status":"sent","meta_response":response.read().decode()}
    except Exception as e:
        raise HTTPException(502, f"WhatsApp API error: {e}")

# RSS helper for feeds you add later. It supports common RSS/Atom formats.
def fetch_rss(feed_url: str, source_name: str, max_items: int = 20):
    req = urllib.request.Request(feed_url, headers={"User-Agent":"A1-News-Intelligence/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        data = response.read()
    root = ET.fromstring(data)
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    output = []
    for item in items[:max_items]:
        def val(tags):
            for tag in tags:
                x = item.find(tag)
                if x is not None and x.text:
                    return x.text.strip()
            return ""
        title = val(["title","{http://www.w3.org/2005/Atom}title"])
        link = val(["link","{http://www.w3.org/2005/Atom}link"])
        desc = val(["description","summary","{http://www.w3.org/2005/Atom}summary","content"])
        if title:
            story = Story(title=title,source=source_name,text=re.sub("<[^>]+>"," ",desc),url=link)
            s, st, cat, _ = score_story(story)
            save_story(story,s,st,cat)
            output.append({"title":title,"score":s,"status":st,"category":cat,"url":link})
    return output

@app.post("/ingest/rss")
def ingest_rss(feed_url: str, source_name: str, max_items: int = 20):
    try:
        items = fetch_rss(feed_url, source_name, max_items)
        return {"source":source_name,"count":len(items),"items":items}
    except Exception as e:
        raise HTTPException(502, f"RSS fetch failed: {e}")
