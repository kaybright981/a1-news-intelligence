from fastapi import FastAPI
from pydantic import BaseModel
from datetime import datetime

app = FastAPI(title="A1 News Intelligence API", version="0.1.0")

class Story(BaseModel):
    title: str
    source: str
    text: str
    url: str | None = None
    country: str = "Nigeria"
    category: str = "General"

def score_story(story: Story, source_weight: int = 90):
    text = (story.title + " " + story.text).lower()
    critical_terms = ["attack","terror","kidnap","bomb","explosion","coup","war","military",
                      "piracy","hostage","airstrike","security alert","election"]
    hits = sum(1 for x in critical_terms if x in text)
    score = min(100, source_weight + min(10, hits * 2))
    return score

@app.get("/health")
def health():
    return {"status":"ok","service":"A1 News Intelligence","time":datetime.utcnow().isoformat()+"Z"}

@app.post("/score")
def score(story: Story):
    score = score_story(story)
    status = "CONFIRMED" if score >= 95 and story.source in ["DSS","NPF","NA","NN","NAF","SH","ONSA"] else "DEVELOPING"
    return {"score":score,"status":status,"story":story.model_dump()}

@app.post("/whatsapp/test")
def whatsapp_test():
    return {"status":"ready","message":"Connect WhatsApp Business Cloud API credentials in production."}
