import sys, soundfile as sf, numpy as np
a,sr=sf.read(sys.argv[1]); m=a.mean(1) if a.ndim>1 else a
m=m[int(sr*5.1):int(sr*25)]
F=np.abs(np.fft.rfft(m))**2; f=np.fft.rfftfreq(len(m),1/sr)
tot=F.sum()
for lo,hi in [(20,120),(120,400),(400,1500),(1500,5000),(5000,11025)]:
    print(f"{lo:>5}-{hi:<5} {100*F[(f>=lo)&(f<hi)].sum()/tot:5.1f}%")
