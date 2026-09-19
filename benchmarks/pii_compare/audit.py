"""Check source coordinates, full-window visibility, and default word boundaries."""
import collections,json,argparse
from pathlib import Path
from compare import load_rows,windows,canon,LABELS,ROOT
from gliner.data_processing.tokenizer import WhitespaceTokenSplitter as NvidiaSplitter
from gliner2.processing.word_splitter import WhitespaceTokenSplitter as FastinoSplitter

def main():
 p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=ROOT.parents[1]/'data'/'ko_pii');p.add_argument('--out',type=Path,default=ROOT/'output');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 rows=load_rows(args.data);totals=collections.Counter();missing=[];impossible={k:collections.Counter() for k in ['nvidia','fastino']}
 splitters={'nvidia':NvidiaSplitter(),'fastino':FastinoSplitter()}
 for row in rows:
  w=windows(row['text'])
  boundaries={name:[({a+s for _,s,e in splitter(t)},{a+e for _,s,e in splitter(t)}) for a,t in w] for name,splitter in splitters.items()}
  for s in row['spans']:
   assert 0<=s['start']<s['end']<=len(row['text'])
   lab=canon(s['label'])
   if lab not in LABELS:continue
   totals[lab]+=1
   if not any(a<=s['start'] and a+len(t)>=s['end'] for a,t in w):missing.append((row['id'],lab))
   for name,bounds in boundaries.items():
    if not any(s['start'] in starts and s['end'] in ends for starts,ends in bounds):impossible[name][lab]+=1
 report={'gold_not_in_any_window':missing,'common_gold_counts':totals,'not_representable_by_default_word_boundaries':impossible}
 (args.out/'boundary_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':main()
