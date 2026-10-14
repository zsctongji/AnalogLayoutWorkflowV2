"""Read normalized complex-transfer CSV; no simulator, extrapolation or signoff."""
import argparse,csv,json,math

def analyze(rows,loop_gain=False,feedback_sign_confirmed=False):
    if loop_gain and not feedback_sign_confirmed:
        raise ValueError('Loop feedback sign/probe convention must be confirmed')
    if len(rows)<2:raise ValueError('At least two samples required')
    fs=[];db=[];phase=[]
    for f,re,im in rows:
        if not all(math.isfinite(x) for x in (f,re,im)) or f<=0 or (fs and f<=fs[-1]):
            raise ValueError('Finite strictly increasing positive frequency required')
        mag=math.hypot(re,im)
        if mag==0:raise ValueError('Zero transfer magnitude has undefined phase/dB')
        p=math.degrees(math.atan2(im,re))
        if phase:
            while p-phase[-1]>180:p-=360
            while p-phase[-1]<-180:p+=360
        fs.append(f);db.append(20*math.log10(mag));phase.append(p)
    def crossings(level):
        result=[]
        for i in range(1,len(fs)):
            if db[i-1]>=level and db[i]<level:
                t=(level-db[i-1])/(db[i]-db[i-1])
                freq=math.exp(math.log(fs[i-1])+t*math.log(fs[i]/fs[i-1]))
                result.append(dict(frequency_hz=freq,phase_deg=phase[i-1]+t*(phase[i]-phase[i-1])))
        return result
    bandwidth=crossings(db[0]-3.010299956639812)
    unity=crossings(0)
    if loop_gain:
        # Canonical signed phase branch near -180 for a unity crossing;
        # margins beyond the usual +-180 branch remain ambiguous, not clipped PASS.
        for x in unity:
            p=x['phase_deg']
            while p>0:p-=360
            while p<=-360:p+=360
            x['phase_margin_deg']=180+p
    return dict(status='SAMPLED_TRANSFER_ONLY',low_frequency_sample_hz=fs[0],sampled_gain_db=db[0],relative_3db_crossings=bandwidth,descending_unity_crossings=unity,phase_margin_applicable=loop_gain,limitations=['First sample is not verified DC gain','Log-frequency linear interpolation; refine sampling if needed','Missing crossing is unbracketed, not zero','Multiple crossings/phase unwrap require stability review; no SPEC_PASS'])

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv');p.add_argument('--output',required=True);p.add_argument('--loop-gain',action='store_true');p.add_argument('--feedback-sign-confirmed',action='store_true');a=p.parse_args()
    with open(a.csv,newline='',encoding='utf-8-sig') as f:
        rows=[tuple(float(r[k]) for k in ['frequency_hz','real','imag']) for r in csv.DictReader(f)]
    out=analyze(rows,a.loop_gain,a.feedback_sign_confirmed)
    with open(a.output,'x',encoding='utf-8') as f:json.dump(out,f,indent=2,allow_nan=False)
if __name__=='__main__':main()
