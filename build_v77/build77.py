import numpy as np, subprocess, sys
SRC='/home/user/plato/episode1_v7.6_full.mp4'
S='/tmp/claude-0/-home-user-plato/a7ae30fd-b9bb-5de7-845c-42654b5c5f99/scratchpad'
OUT=sys.argv[1]
SR=48000; T0=0.020996; FPS=24
def ft(n): return T0+n/FPS
def load(path,ss=None,t=None):
    cmd=['ffmpeg','-v','error']+(['-ss',str(ss)] if ss is not None else [])+(['-t',str(t)] if t else [])+['-i',path,'-vn','-ac','2','-ar',str(SR),'-f','f32le','-']
    return np.frombuffer(subprocess.run(cmd,capture_output=True).stdout,np.float32).reshape(-1,2).copy()
A=load(SRC)
def S_(t): return int(round(t*SR))
def seg(t1,t2): return A[S_(t1):S_(t2)].copy()
def xcat(parts,xf=0.08):
    out=parts[0]
    for p in parts[1:]:
        k=min(int(xf*SR),len(out),len(p))
        w=np.linspace(0,1,k)[:,None]
        mid=out[-k:]*np.sqrt(1-w)+p[:k]*np.sqrt(w)
        out=np.concatenate([out[:-k],mid,p[k:]])
    return out
def filler(ranges,L,xf=0.25):
    parts=[];tot=0;i=0
    while tot<L+1:
        a,b=ranges[i%len(ranges)];parts.append(seg(a,b));tot+=b-a-xf;i+=1
    f=xcat(parts,xf);return f[:S_(L)]
def fit(x,L):  # exact length in samples
    n=S_(L)
    return x[:n] if len(x)>=n else np.concatenate([x,np.zeros((n-len(x),2),np.float32)])
rng=np.random.default_rng(7)
def clicks(L,start,end,level=0.035):
    out=np.zeros((S_(L),2),np.float32); t=start
    while t<end:
        n=int(0.012*SR); env=np.exp(-np.linspace(0,9,n))
        b=rng.standard_normal(n)*env
        b=np.convolve(b,[1,-0.85],'same')  # brighten
        g=level*rng.uniform(0.5,1.0); i=S_(t)
        if i+n<len(out): out[i:i+n,0]+=b*g*rng.uniform(.8,1); out[i:i+n,1]+=b*g*rng.uniform(.8,1)
        t+=rng.choice([0.07,0.09,0.11,0.13,0.18,0.28])
    return out
# ---- stewardess overlay on source timeline ----
def add(at,x,gain=1.0):
    i=S_(at); A[i:i+len(x)]+=x[:len(A)-i]*gain
ding=load(S+'/dl/ding.mp3'); stew=load(S+'/dl/stew.mp3')
def rms(x): return float(np.sqrt((x**2).mean())+1e-9)
ref=rms(seg(53.0,55.9))  # Zhenya dialogue level
p1=stew[:S_(1.05)]; p2=stew[S_(1.15):]
g=2.1*ref/rms(np.concatenate([p1,p2])[np.abs(np.concatenate([p1,p2])).max(1)>0.02])
for p in (p1,p2):
    k=int(0.03*SR); p[:k]*=np.linspace(0,1,k)[:,None]; p[-k:]*=np.linspace(1,0,k)[:,None]
SHOT=ft(round((169.4377-T0)*FPS))
dg=ding.copy(); dg[S_(2.2):]*=0; k=int(.3*SR); dg[S_(1.9):S_(2.2)]*=np.linspace(1,0,S_(2.2)-S_(1.9))[:,None]
add(SHOT-0.85,dg,0.9*ref/rms(ding[:S_(1.0)]))
add(SHOT+0.30,p1,g); add(SHOT+2.20,p2,g)
# ---- splice ----
F=lambda n: ft(n)
XF=0.06
def segL(t1,t2): return A[S_(t1-XF):S_(t2)].copy()   # with lead-in
def lead(x): return np.concatenate([x[:S_(XF)][::-1]*0+x[:S_(XF)],x])  # filler: reuse own start as lead
parts=[]
parts.append(seg(0,F(1534)))                                # S1 to dictionary start
L1=(74+36+43)/FPS-(1625-1534)/FPS
fill1=filler([(56.1,56.95),(57.1,57.85),(67.15,67.6)],L1)
fill1=fill1+clicks(L1,max(0.02,3.083-(67.20-F(1534))+0.05),L1-0.1)     # clicks start when typing shot starts
parts.append(segL(F(1534),67.20)); parts.append(lead(fill1)); parts.append(segL(67.20,F(2414)))
L2=110/FPS
parts.append(lead(filler([(100.15,101.4),(101.45,103.0)],L2)))
parts.append(segL(F(2414),F(11959)))
parts.append(segL(F(11978),len(A)/SR))
out=xcat(parts,XF)
out=out[S_(T0):]
np.clip(out,-1,1).astype(np.float32).tofile(OUT)
print('audio sec',len(out)/SR, 'ref',ref,'g',g)
