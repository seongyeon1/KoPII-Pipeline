"""Score exact typed spans and label-agnostic character coverage; no threshold tuning."""
import argparse,collections,json,statistics
from pathlib import Path
from compare import load_rows,canon,LABELS,OPERATIONAL,ROOT

def prf(tp,fp,fn):
 p=tp/(tp+fp) if tp+fp else 0.;r=tp/(tp+fn) if tp+fn else 0.
 return dict(tp=tp,fp=fp,fn=fn,precision=p,recall=r,f1=2*p*r/(p+r) if p+r else 0.,f5=26*p*r/(25*p+r) if p+r else 0.)
def spans(entities,labels):return {(e['start'],e['end'],canon(e['label'])) for e in entities if canon(e['label']) in labels}
def chars(ss):return {i for a,b,_ in ss for i in range(a,b)}
def evaluate(rows,preds,labels):
 tp=fp=fn=ctp=cfp=cfn=covered=gold_n=negative_fp=0
 for row in rows:
  g=spans(row['spans'],labels);p=spans(preds[row['id']]['predictions'],labels)
  tp+=len(g&p);fp+=len(p-g);fn+=len(g-p)
  gc=chars(g);pc=chars(p);ctp+=len(gc&pc);cfp+=len(pc-gc);cfn+=len(gc-pc)
  covered+=sum(set(range(a,b))<=pc for a,b,_ in g);gold_n+=len(g)
  if not row['spans'] and p:negative_fp+=1
 return dict(n=len(rows),exact=prf(tp,fp,fn),characters=prf(ctp,cfp,cfn),fully_covered_spans=covered,gold_spans=gold_n,full_span_coverage=covered/gold_n if gold_n else None,false_positive_documents=negative_fp)
def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=ROOT.parents[1]/'data'/'ko_pii');p.add_argument('--out',type=Path,default=ROOT/'output');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 rows=load_rows(args.data);assert len({r['id'] for r in rows})==len(rows)
 report={}
 for name in ['roberta','nvidia','fastino']:
  path=args.out/f'{name}.jsonl'
  if not path.exists():continue
  pp=[json.loads(x) for x in path.open()];preds={r['id']:r for r in pp}
  assert len(pp)==len(preds)
  selected=[r for r in rows if r['id'] in preds]
  hold=[r for r in selected if r['evaluation_split']=='holdout'];neg=[r for r in selected if r['evaluation_split']=='negative']
  data=dict(completed=len(selected),expected=len(rows),holdout=evaluate(hold,preds,set(LABELS)),operational=evaluate(hold,preds,OPERATIONAL),negative=evaluate(neg,preds,set(LABELS)),per_label={lab:evaluate(hold,preds,{lab}) for lab in LABELS},by_layer={lab:evaluate([r for r in hold if r['meta']['layer']==lab],preds,set(LABELS)) for lab in ['L1','L1b']})
  meta=args.out/f'{name}.meta.json'
  if meta.exists():
   data['run']=json.loads(meta.read_text());lat=sorted(data['run']['latency_seconds']);data['latency_median_ms']=statistics.median(lat)*1000;data['latency_p95_ms']=lat[min(len(lat)-1,int(.95*len(lat)))]*1000
  report[name]=data
 (args.out/'metrics.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print(json.dumps({n:{'n':r['completed'],'exact':r['holdout']['exact'],'coverage':r['holdout']['characters']['recall'],'names':r['per_label']['PERSON_NAME']['exact'],'negative_docs':r['negative']['false_positive_documents']} for n,r in report.items()},indent=2))
if __name__=='__main__':main()
