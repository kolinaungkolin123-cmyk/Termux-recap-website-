mkdir -p ~/recap
cat > ~/recap/server.py << 'EOF'
import os,re,json,math,uuid,base64,subprocess,threading,asyncio,time,requests,edge_tts
from flask import Flask,request,jsonify,send_file
ROOT=os.path.dirname(os.path.abspath(__file__));JOBS=os.path.join(ROOT,"jobs");os.makedirs(JOBS,exist_ok=True)
app=Flask(__name__);J={};DL={}
STEPS=["အသံထုတ်ယူခြင်း","စာထုတ်ခြင်း (AssemblyAI)","ဘာသာပြန်စာ ထည့်ပြီး စစ်ဆေးခြင်း","မြန်မာအသံဖန်တီးခြင်း (Edge)","ဗီဒီယိုကို အသံနဲ့ညှိခြင်း (video အမြန်/အနှေး)","ဗီဒီယိုပေါင်းစပ်ခြင်း (size/blur/စာတန်း)"]
V2={"my-MM-ThihaNeural":"my-MM-NilarNeural","my-MM-NilarNeural":"my-MM-ThihaNeural"}
PROMPT="""Translate every line below into natural spoken Burmese (Myanmar language) for movie-recap narration.
Rules:
- Keep EXACTLY the same format: number | time | translated text
- Do NOT change the numbers or the times.
- Keep every line, do not merge, skip or add lines.
- Each translation should be about the same length as the original so it fits the time.
- Output ONLY the translated lines, no explanation, no summary, no title.

"""

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"]="*";r.headers["Access-Control-Allow-Headers"]="*"
    r.headers["Access-Control-Allow-Methods"]="GET,POST,OPTIONS";return r

def sh(*a):
    p=subprocess.run(a,capture_output=True,text=True)
    if p.returncode:raise RuntimeError(p.stderr[-400:])
    return p.stdout
def dur(f):return float(sh("ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f).strip())
def tts(text,voice,pitch,rate,out):
    asyncio.run(edge_tts.Communicate(text,voice,pitch="%+dHz"%pitch,rate="%+d%%"%rate).save(out))
def fmt(t):
    n=int(round(t*10));return "%d:%04.1f"%(n//600,(n%600)/10)
def jd(i):return os.path.join(JOBS,i)

@app.get("/")
def index():return "Running website"

@app.post("/api/preview")
def preview():
    d=request.json;f=os.path.join(JOBS,"pv_%s.mp3"%uuid.uuid4().hex)
    try:tts(d["text"],d["voice"],int(d["pitch"]),int(d.get("rate",0)),f)
    except Exception as e:return str(e),500
    return send_file(f,mimetype="audio/mpeg")

@app.post("/api/upload")
def upload():
    i=uuid.uuid4().hex[:10];os.makedirs(jd(i))
    request.files["file"].save(jd(i)+"/src.mp4");return jsonify(id=i)

@app.get("/api/src/<i>")
def srcv(i):return send_file(jd(i)+"/src.mp4",mimetype="video/mp4")

@app.post("/api/dl")
def dl():
    i=uuid.uuid4().hex[:10];os.makedirs(jd(i));DL[i]={"p":0,"s":"run","m":""}
    threading.Thread(target=dlwork,args=(i,request.json["url"]),daemon=True).start();return jsonify(id=i)

@app.get("/api/dl/<i>")
def dls(i):return jsonify(DL.get(i,{"p":0,"s":"err","m":"မတွေ့ပါ"}))

def dlwork(i,url):
    D=jd(i)
    def hook(d):
        if d.get("status")=="downloading":
            t=d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if t:DL[i]["p"]=min(99,int(d["downloaded_bytes"]*100/t))
    try:
        import yt_dlp
        o={"outtmpl":D+"/dl.%(ext)s","format":"bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b",
           "merge_output_format":"mp4","progress_hooks":[hook],"quiet":True,"noplaylist":True}
        with yt_dlp.YoutubeDL(o) as y:y.download([url])
        f=[x for x in os.listdir(D) if x.startswith("dl.")][0]
        if f=="dl.mp4":os.replace(D+"/dl.mp4",D+"/src.mp4")
        else:
            try:sh("ffmpeg","-y","-i",D+"/"+f,"-c","copy",D+"/src.mp4")
            except Exception:sh("ffmpeg","-y","-i",D+"/"+f,"-c:v","libx264","-preset","veryfast","-c:a","aac",D+"/src.mp4")
        DL[i]={"p":100,"s":"ok","m":""}
    except Exception as e:
        DL[i]={"p":0,"s":"err","m":str(e)[:300]}

@app.post("/api/transcribe")
def transcribe():
    d=request.json;i=d["id"]
    J[i]={"steps":[{"n":n,"s":"wait","m":""} for n in STEPS],"status":"running","error":"","text":""}
    threading.Thread(target=phase1,args=(i,d["aai"],d.get("mode","recap")),daemon=True).start();return jsonify(ok=1)

@app.get("/api/job/<i>")
def job(i):return jsonify(J.get(i,{"status":"error","error":"job မတွေ့ပါ (server ပြန်စထားလျှင် အစကပြန်လုပ်ပါ)","steps":[],"text":""}))

@app.get("/api/video/<i>")
def video(i):
    return send_file(jd(i)+"/out.mp4",mimetype="video/mp4",
        as_attachment=bool(request.args.get("dl")),download_name="recap.mp4")

@app.post("/api/subs")
def subs():
    d=request.json;i=d["id"];k=int(d["seg"]);ws=[]
    for j,p in enumerate(d["parts"]):
        open("%s/sub_%d_%d.png"%(jd(i),k,j),"wb").write(base64.b64decode(p["png"].split(",",1)[1]))
        ws.append(max(1,int(p["w"])))
    f=jd(i)+"/subs.json";m=json.load(open(f)) if os.path.exists(f) else {}
    m[str(k)]=ws;json.dump(m,open(f,"w"));return jsonify(ok=1)

@app.post("/api/wm")
def wm():
    d=request.json;open(jd(d["id"])+"/wm.png","wb").write(base64.b64decode(d["png"].split(",",1)[1]));return jsonify(ok=1)

LINE=re.compile(r"^\W*(\d+)\s*[|｜]\s*([\d:.]+)\s*[|｜]\s*(.*\S)\s*$")
def check(i,text):
    segs=json.load(open(jd(i)+"/segs.json"));n=len(segs);errs=[];warns=[];tr={};skip=0
    for l in text.splitlines():
        if not l.strip():continue
        m=LINE.match(l)
        if not m:skip+=1;continue
        k=int(m.group(1))
        if k<1 or k>n:errs.append("နံပါတ် %d မရှိပါ (1-%d သာရှိသည်)"%(k,n));continue
        if k in tr:errs.append("နံပါတ် %d ထပ်နေသည်"%k);continue
        tr[k]=m.group(3).strip()
        o=fmt(segs[k-1]["s"])
        if m.group(2)!=o:warns.append("နံပါတ် %d အချိန်ကွဲနေသည် (မူရင်း %s) – မူရင်းအချိန်ကို သုံးမည်"%(k,o))
        if not re.search("[\u1000-\u109f]",tr[k]):warns.append("နံပါတ် %d မှာ မြန်မာစာ မပါပါ"%k)
    if skip:warns.append("ပုံစံမမှန်သော စာကြောင်း %d ကြောင်းကို ကျော်ထားသည်"%skip)
    miss=[k for k in range(1,n+1) if k not in tr]
    if miss:errs.append("မပါသေးသော နံပါတ်: "+",".join(map(str,miss[:30]))+("..." if len(miss)>30 else ""))
    return errs,warns,tr,n

@app.post("/api/check")
def api_check():
    d=request.json
    try:errs,warns,tr,n=check(d["id"],d["text"])
    except Exception as e:return jsonify(ok=False,errors=[str(e)],warnings=[],count=0,total=0)
    return jsonify(ok=not errs,errors=errs,warnings=warns,count=len(tr),total=n)

@app.post("/api/continue")
def cont():
    d=request.json;i=d["id"]
    errs,warns,tr,n=check(i,d["text"])
    if errs:return jsonify(ok=False,errors=errs,warnings=warns),400
    S=J[i]["steps"];S[2]["s"]="ok";S[2]["m"]="%d ကြောင်း မှန်ပါသည်"%n;J[i]["status"]="running"
    threading.Thread(target=phase2,args=(i,d["voice"],int(d["pitch"]),int(d.get("rate",0)),tr,d.get("opts") or {}),daemon=True).start()
    return jsonify(ok=True)

def phase1(i,aai,mode):
    D=jd(i);S=J[i]["steps"];cur=0
    def st(k,s,m=""):
        nonlocal cur;cur=k;S[k]["s"]=s;S[k]["m"]=m
    try:
        src=D+"/src.mp4";dur(src)
        st(0,"run");sh("ffmpeg","-y","-i",src,"-vn","-ac","1","-ar","16000","-b:a","64k",D+"/a.mp3");st(0,"ok")
        st(1,"run","Upload လုပ်နေသည်");H={"authorization":aai};B="https://api.assemblyai.com"
        with open(D+"/a.mp3","rb") as f:
            r=requests.post(B+"/v2/upload",headers=H,data=f).json()
        if "upload_url" not in r:raise RuntimeError("AssemblyAI: "+str(r))
        body={"audio_url":r["upload_url"],"speech_models":["universal-3-pro","universal-2"],"language_detection":True}
        if mode=="dub":body["speaker_labels"]=True
        r=requests.post(B+"/v2/transcript",headers=H,json=body).json()
        if "id" not in r:raise RuntimeError("AssemblyAI: "+str(r))
        tid=r["id"]
        while True:
            t=requests.get(B+"/v2/transcript/"+tid,headers=H).json()
            if t["status"]=="completed":break
            if t["status"]=="error":raise RuntimeError("AssemblyAI: "+str(t.get("error")))
            st(1,"run","စာထုတ်နေသည်...");time.sleep(3)
        sj=requests.get(B+"/v2/transcript/%s/sentences"%tid,headers=H).json()["sentences"]
        segs=[];order={}
        for x in sj:
            tx=x["text"].strip()
            if not tx:continue
            sp=x.get("speaker")
            if sp not in order:order[sp]=len(order)
            segs.append({"s":x["start"]/1000,"t":tx,"sp":order[sp]})
        if not segs:raise RuntimeError("စကားသံ မတွေ့ပါ")
        json.dump(segs,open(D+"/segs.json","w"),ensure_ascii=False)
        J[i]["text"]=PROMPT+"\n".join("%d | %s | %s"%(k+1,fmt(x["s"]),x["t"]) for k,x in enumerate(segs))
        m="%d ကြောင်း"%len(segs)+(" · စကားပြောသူ %d ဦး"%len(order) if mode=="dub" else "")
        st(1,"ok",m);st(2,"pause","ဘာသာပြန်စာ ထည့်ပါ")
        J[i]["status"]="wait"
    except Exception as e:
        S[cur]["s"]="err";S[cur]["m"]=str(e)[:300];J[i]["status"]="error";J[i]["error"]=str(e)[:300]

def phase2(i,voice,pitch,rate,tr,o):
    D=jd(i);S=J[i]["steps"];cur=3
    def st(k,s,m=""):
        nonlocal cur;cur=k;S[k]["s"]=s;S[k]["m"]=m
    def runp(cmd,total):
        lf=open(D+"/ff.log","w")
        p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=lf,text=True)
        for ln in p.stdout:
            if ln.startswith("out_time_us="):
                try:st(5,"run","%d%%"%min(99,int(int(ln.split("=")[1])/1e6*100/max(total,0.1))))
                except Exception:pass
        p.wait();lf.close()
        if p.returncode:raise RuntimeError(open(D+"/ff.log").read()[-400:])
    try:
        segs=json.load(open(D+"/segs.json"));src=D+"/src.mp4";vd=dur(src)
        vs=[voice,V2.get(voice,voice)];dub=o.get("mode")=="dub"
        for k,x in enumerate(segs):
            st(3,"run","%d/%d"%(k+1,len(segs)))
            x["f"]="%s/s%d.mp3"%(D,k)
            tts(tr[k+1],vs[x.get("sp",0)%2] if dub else voice,pitch,rate,x["f"]);x["d"]=dur(x["f"])
        st(3,"ok")
        try:
            fr=sh("ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=avg_frame_rate","-of","csv=p=0",src).strip()
            a,b=(fr.split("/")+["1"])[:2];fps=float(a)/float(b)
        except Exception:fps=30.0
        if fps<=0 or fps>30:fps=30.0
        fs="%.5f"%fps;fps=float(fs)
        items=[];lead=0
        if segs[0]["s"]>0.05:items.append((0.0,segs[0]["s"],None,segs[0]["s"]));lead=1
        for k,x in enumerate(segs):
            nx=segs[k+1]["s"] if k+1<len(segs) else vd
            items.append((x["s"],max(nx-x["s"],1.0/fps),x["f"],x["d"]))
        vl=[];al=[];vks=[];lo=99.0;hi=0.0
        for k,(s0,W0,af,ad) in enumerate(items):
            st(4,"run","%d/%d"%(k+1,len(items)))
            n=max(1,math.ceil(ad*fps-1e-6));vk=n/fps;F=vk/W0
            lo=min(lo,F);hi=max(hi,F);vks.append(vk)
            vo="%s/v%d.mp4"%(D,k);ao="%s/a%d.wav"%(D,k)
            sh("ffmpeg","-y","-ss","%.3f"%s0,"-t","%.3f"%W0,"-i",src,"-an",
               "-vf","setpts=%.6f*(PTS-STARTPTS),fps=%s,tpad=stop_mode=clone:stop_duration=3,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p"%(F,fs),
               "-frames:v",str(n),"-c:v","libx264","-preset","ultrafast","-crf","22","-r",fs,vo)
            if af:sh("ffmpeg","-y","-i",af,"-af","apad=whole_dur=%.5f"%vk,"-t","%.5f"%vk,"-ar","24000","-ac","1",ao)
            else:sh("ffmpeg","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono","-t","%.5f"%vk,ao)
            vl.append(vo);al.append(ao)
        open(D+"/lv.txt","w").write("".join("file '%s'\n"%p for p in vl))
        open(D+"/la.txt","w").write("".join("file '%s'\n"%p for p in al))
        sh("ffmpeg","-y","-f","concat","-safe","0","-i",D+"/lv.txt","-c","copy",D+"/vall.mp4")
        sh("ffmpeg","-y","-f","concat","-safe","0","-i",D+"/la.txt","-c","copy",D+"/dub.wav")
        st(4,"ok","video အမြန်ဆုံး ×%.1f၊ အနှေးဆုံး ×%.1f"%(1/lo,1/hi))
        # ---- final render ----
        st(5,"run","0%")
        W=int(o.get("W",720))//2*2;H=int(o.get("H",1280))//2*2
        wh=sh("ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=width,height","-of","csv=p=0",D+"/vall.mp4").strip().split(",")
        VW,VH=int(wh[0]),int(wh[1])
        vf=[];c=o.get("crop") or {}
        if c.get("on"):
            cw=max(2,int(float(c["w"])*VW)//2*2);ch=max(2,int(float(c["h"])*VH)//2*2)
            cx=min(max(0,int(float(c["x"])*VW)),VW-cw);cy=min(max(0,int(float(c["y"])*VH)),VH-ch)
            vf.append("crop=%d:%d:%d:%d"%(cw,ch,cx,cy))
        if o.get("flip"):vf.append("hflip")
        f=["[0:v]%s[v0]"%(",".join(vf) or "null")]
        bgv=int(o.get("bg") or 0)
        if bgv>0:
            w8=max(2,W//8//2*2);h8=max(2,H//8//2*2);r=max(1,min(int(bgv*w8/200),min(w8,h8)//2-1))
            f.append("[v0]split[a][b];[b]scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d,scale=%d:%d,boxblur=%d:2,scale=%d:%d[bg];"
                     "[a]scale=%d:%d:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v1]"%(W,H,W,H,w8,h8,r,W,H,W,H))
        else:
            f.append("[v0]scale=%d:%d:force_original_aspect_ratio=decrease,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black[v1]"%(W,H,W,H))
        cmd=["ffmpeg","-y","-progress","pipe:1","-nostats","-i",D+"/vall.mp4","-i",D+"/dub.wav"];n=2;last="[v1]"
        bl=o.get("blur") or {}
        if bl.get("on"):
            bw=max(2,int(float(bl["w"])*W)//2*2);bh=max(2,int(float(bl["h"])*H)//2*2)
            bx=min(max(0,int(float(bl["x"])*W)),W-bw);by=min(max(0,int(float(bl["y"])*H)),H-bh)
            R=max(1,min(int(float(bl["s"])*W/720),min(bw,bh)//2-1))
            f.append("%ssplit[a2][b2];[b2]crop=%d:%d:%d:%d,boxblur=%d:3[c2];[a2][c2]overlay=%d:%d[v2]"%(last,bw,bh,bx,by,R,bx,by));last="[v2]"
        sb=o.get("sub") or {}
        if sb.get("on"):
            sby=int(sb["by"]);sbh=int(sb["bh"]);blank=D+"/blank.png"
            sh("ffmpeg","-y","-f","lavfi","-i","color=c=black@0.0:s=%dx%d,format=rgba"%(W,sbh),"-frames:v","1",blank)
            meta=json.load(open(D+"/subs.json")) if os.path.exists(D+"/subs.json") else {}
            lines=[]
            for idx,vk in enumerate(vks):
                ws=meta.get(str(idx-lead)) if idx-lead>=0 else None
                if not ws:lines.append((blank,vk));continue
                tot=sum(ws)
                for j,w in enumerate(ws):lines.append(("%s/sub_%d_%d.png"%(D,idx-lead,j),vk*w/tot))
            open(D+"/sub.txt","w").write("".join("file '%s'\nduration %.5f\n"%(p,d) for p,d in lines)+"file '%s'\n"%lines[-1][0])
            cmd+=["-f","concat","-safe","0","-i",D+"/sub.txt"]
            f.append("[%d:v]fps=%s,format=rgba[s3];%s[s3]overlay=0:%d:format=auto:eof_action=pass[v3]"%(n,fs,last,sby));last="[v3]";n+=1
        w_=o.get("wm") or {}
        if w_.get("on") and os.path.exists(D+"/wm.png"):
            cmd+=["-loop","1","-framerate",fs,"-i",D+"/wm.png"]
            f.append("[%d:v]format=rgba[w4];%s[w4]overlay=0:%d:format=auto:shortest=1[v4]"%(n,last,int(w_["by"])));last="[v4]";n+=1
        f.append("%sformat=yuv420p[vo]"%last)
        runp(cmd+["-filter_complex",";".join(f),"-map","[vo]","-map","1:a:0","-c:v","libx264","-preset","ultrafast","-crf","26",
           "-threads","3","-c:a","aac","-b:a","128k","-shortest","-movflags","+faststart",D+"/out.mp4"],sum(vks))
        st(5,"ok");J[i]["status"]="done"
    except Exception as e:
        S[cur]["s"]="err";S[cur]["m"]=str(e)[:300];J[i]["status"]="error";J[i]["error"]=str(e)[:300]

if __name__=="__main__":
    print("\n=== Running website: server စတင်ပါပြီ (port 5000) ===\n")
    app.run("127.0.0.1",5000,threaded=True)
EOF
cd ~/recap && termux-wake-lock && python server.py
