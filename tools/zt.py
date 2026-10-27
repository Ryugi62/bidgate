import json,os,sys,urllib.request
B="http://localhost:3000"
def post(p,d,h=None):
    r=urllib.request.Request(B+p,data=json.dumps(d).encode(),headers={"Content-Type":"application/json",**(h or {})})
    try: return json.loads(urllib.request.urlopen(r,timeout=120).read())
    except urllib.error.HTTPError as e: return {"HTTP":e.code,"body":e.read().decode()[:800]}
def login():
    l=post("/api/auth/login",{"username":os.environ["ZETARIS_USER"],"password":os.environ["ZETARIS_PASSWORD"]})
    return l
if __name__=="__main__":
    l=login(); print({k:(v if k=='orgId' else '<'+str(len(str(v)))+'>') for k,v in l.items()})
    tok=[v for k,v in l.items() if 'token' in k.lower()][0]
    r=post("/api/proxy/query/sql/start",{"select":sys.argv[1],"pageLimit":50},{"Authorization":"Bearer "+tok,"X-Org-ID":str(l["orgId"]),"X-Request-ID":"11111111-2222-3333-4444-555555555555"})
    print(json.dumps(r)[:1500])
