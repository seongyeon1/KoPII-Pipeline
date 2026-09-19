"""Reproducible local PII comparison. No HR lookup, regex or external inference.

Run with --model roberta|nvidia|fastino. Predictions are resumable by document ID.
Common text windows and label mapping are fixed before inspecting test predictions.
"""
from __future__ import annotations
import argparse, collections, hashlib, json, os, platform, random, time
from pathlib import Path
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
os.environ.setdefault('TOKENIZERS_PARALLELISM','false')
import torch
from huggingface_hub import snapshot_download
from tokenizers import Tokenizer
from transformers import AutoModelForTokenClassification

ROOT=Path(__file__).resolve().parent
MODELS={
 'roberta':('seongyeon1/ko-pii-ner-roberta-base','95a3af685dccf4bb3f7fff6fc81146fed71500bb'),
 'nvidia':('nvidia/gliner-PII','bd23e8ef4425fd04e34c5204ab49ffaa706eae79'),
 'fastino':('fastino/gliner2-privacy-filter-PII-multi','c153999da5f4c509df4322b0c6a1baf3d2c284d7'),
}
LABELS={
 'PERSON_NAME':'person','PHONE_NUM':'phone_number','EMAIL':'email',
 'ADDRESS':'address','ACCOUNT_NUM':'account_number','CARD_NUM':'card_number',
 'GOV_ID':'national_id_number','PASSPORT_NUM':'passport_number',
 'DRIVER_LICENSE_NUM':'drivers_license_number','BIZ_REG_NUM':'tax_id',
 'USER_ID':'username','IP_ADDRESS':'ip_address','DOB':'date_of_birth',
}
REVERSE={v:k for k,v in LABELS.items()}
OPERATIONAL=set(LABELS)-{'ADDRESS','USER_ID','IP_ADDRESS','DOB'}
THRESHOLDS={'roberta':None,'nvidia':0.3,'fastino':0.5}

def canon(label):
 return 'GOV_ID' if label in ('RRN','FOREIGNER_REG_NUM') else label

def windows(text):
 """180-character windows, >=48 overlap; prefer whitespace boundaries, never gold."""
 out=[];start=0
 while start<len(text):
  end=min(start+180,len(text))
  if end<len(text):
   candidates=[i for i in range(start+140,end) if text[i].isspace()]
   if candidates:end=candidates[-1]+1
  out.append((start,text[start:end]))
  if end==len(text):break
  start=end-48
 return out or [(0,'')]

def merge(preds):
 # Prefer spans supported away from a window edge. Resolve flat overlapping predictions.
 selected=[]
 for p in sorted(preds,key=lambda p:(-p['context'],-p['score'],p['start'],p['end'])):
  if any(p['start']<q['end'] and q['start']<p['end'] for q in selected):continue
  selected.append(p)
 return [{k:p[k] for k in ('start','end','label','score')} for p in sorted(selected,key=lambda p:p['start'])]

def sync(device):
 if device=='mps':torch.mps.synchronize()
 if device=='cuda':torch.cuda.synchronize()

class Adapter:
 def __init__(self,name,device):
  self.name=name;self.device=device
  mid,rev=MODELS[name]
  path=snapshot_download(mid,revision=rev,local_files_only=True)
  if name=='roberta':
   self.model=AutoModelForTokenClassification.from_pretrained(path).eval().to(device)
   self.tok=Tokenizer.from_file(str(Path(path)/'tokenizer.json'))
   self.tok.enable_truncation(max_length=256,stride=32)
   self.tags=self.model.config.id2label
  elif name=='nvidia':
   from gliner import GLiNER
   self.model=GLiNER.from_pretrained(path).eval().to(device)
  else:
   from gliner2 import GLiNER2
   self.model=GLiNER2.from_pretrained(path).eval().to(device)
  print(json.dumps({'loaded':name,'device':device,'parameters':sum(p.numel() for p in self.model.parameters())}),flush=True)
 def batch(self,texts):
  with torch.inference_mode():
   if self.name=='nvidia':
    raw=self.model.inference(texts,list(LABELS.values()),threshold=THRESHOLDS[self.name],batch_size=len(texts))
    return [[dict(start=e['start'],end=e['end'],label=REVERSE[e['label']],score=float(e['score'])) for e in entities] for entities in raw]
   if self.name=='fastino':
    raw=self.model.batch_extract_entities(texts,list(LABELS.values()),batch_size=len(texts),threshold=THRESHOLDS[self.name],include_spans=True,include_confidence=True)
    return [[dict(start=e['start'],end=e['end'],label=REVERSE[label],score=float(e['confidence'])) for label,ents in r['entities'].items() for e in ents] for r in raw]
   encs=[];owners=[]
   for i,text in enumerate(texts):
    enc=self.tok.encode(text)
    for win in [enc]+enc.overflowing:encs.append(win);owners.append(i)
   length=max(len(e.ids) for e in encs)
   ids=torch.tensor([e.ids+[self.model.config.pad_token_id]*(length-len(e.ids)) for e in encs],device=self.device)
   mask=torch.tensor([[1]*len(e.ids)+[0]*(length-len(e.ids)) for e in encs],device=self.device)
   probs=self.model(input_ids=ids,attention_mask=mask).logits.softmax(-1)
   scores,tags=probs.max(-1);scores=scores.cpu().tolist();tags=tags.cpu().tolist()
   tokens=[{} for _ in texts]
   for j,(enc,owner) in enumerate(zip(encs,owners)):
    for i,((start,end),special) in enumerate(zip(enc.offsets,enc.special_tokens_mask)):
     if special or start==end:continue
     context=min(i,len(enc.ids)-1-i)
     prev=tokens[owner].get((start,end))
     if prev is None or context>prev[0]:tokens[owner][start,end]=(context,self.tags[tags[j][i]],scores[j][i])
   results=[]
   # BIO decoding accepts an orphan I tag and joins only same-line whitespace gaps.
   for text,toks in zip(texts,tokens):
    out=[];active=None
    for (start,end),(_,tag,score) in sorted(toks.items()):
     if tag=='O':
      if active:out.append(active);active=None
      continue
     prefix,label=tag.split('-',1)
     gap=text[active['end']:start] if active else ''
     if prefix=='I' and active and active['label']==label and active['end']<=start and not gap.strip() and '\n' not in gap and '\r' not in gap:
      active['end']=end;active['score']=min(active['score'],score)
     else:
      if active:out.append(active)
      active=dict(start=start,end=end,label=label,score=score)
    if active:out.append(active)
    results.append([dict(e,label=canon(e['label'])) for e in out if canon(e['label']) in LABELS])
   return results
 def documents(self,texts,batch_size):
  specs=[(i,start,part) for i,t in enumerate(texts) for start,part in windows(t)]
  result=[[] for _ in texts]
  for begin in range(0,len(specs),batch_size):
   batch=specs[begin:begin+batch_size]
   got=self.batch([s[2] for s in batch])
   assert len(got)==len(batch)
   for (i,start,part),entities in zip(batch,got):
    for e in entities:
     assert 0<=e['start']<e['end']<=len(part),(self.name,e,len(part))
     result[i].append(dict(e,context=min(e['start'],len(part)-e['end']),start=e['start']+start,end=e['end']+start))
  return [merge(r) for r in result],len(specs)

def load_rows(data):
 rows=[json.loads(line) for line in (data/'test_kdpii.jsonl').open()]
 for r in rows:r['evaluation_split']='holdout'
 negatives=[json.loads(line) for line in (data/'test.jsonl').open()]
 negatives=[r for r in negatives if r['meta']['layer']=='L4']
 for r in negatives:
  assert not r['spans'];r['evaluation_split']='negative'
 return rows+negatives

def main():
 p=argparse.ArgumentParser();p.add_argument('--model',choices=MODELS,required=True)
 p.add_argument('--data',type=Path,default=ROOT.parents[1]/'data'/'ko_pii')
 p.add_argument('--device',default='mps');p.add_argument('--batch-size',type=int,default=4)
 p.add_argument('--limit',type=int,default=0);p.add_argument('--out',type=Path,default=ROOT/'output')
 args=p.parse_args();args.out.mkdir(parents=True,exist_ok=True);torch.set_num_threads(4)
 rows=load_rows(args.data)
 if args.limit:rows=rows[:args.limit]
 fp=args.out/f'{args.model}.jsonl';done={}
 if fp.exists():done={r['id']:r for r in map(json.loads,fp.open())}
 start=time.perf_counter();adapter=Adapter(args.model,args.device);load_sec=time.perf_counter()-start
 smoke,_=adapter.documents(['Email john.smith@example.com or call +1 415 555 0199.','김하늘의 이메일은 sample@example.com입니다.'],args.batch_size)
 print('smoke',json.dumps(smoke,ensure_ascii=False),flush=True)
 assert smoke[0], 'English smoke test found no entities; inspect adapter before evaluating.'
 sync(args.device);start=time.perf_counter();new_count=0;chunk_count=0
 with fp.open('a') as f:
  remaining=[r for r in rows if r['id'] not in done]
  for at in range(0,len(remaining),16):
   group=remaining[at:at+16];sync(args.device);t=time.perf_counter()
   predictions,chunks=adapter.documents([r['text'] for r in group],args.batch_size);sync(args.device)
   elapsed=time.perf_counter()-t;chunk_count+=chunks
   for r,pred in zip(group,predictions):
    f.write(json.dumps({'id':r['id'],'predictions':pred,'group_elapsed_sec':elapsed,'group_n':len(group)},ensure_ascii=False)+'\n')
   f.flush();new_count+=len(group)
   print(json.dumps({'model':args.model,'done':len(done)+new_count,'total':len(rows),'elapsed_sec':round(time.perf_counter()-start,1),'last_group_sec':round(elapsed,2)}),flush=True)
 infer_sec=time.perf_counter()-start
 # Deterministic single-document latency, warm model; excludes loading/download.
 rng=random.Random(20260915);sample=rng.sample(rows,min(32,len(rows)));latencies=[]
 for row in sample:
  sync(args.device);t=time.perf_counter();adapter.documents([row['text']],1);sync(args.device)
  latencies.append(time.perf_counter()-t)
 meta={'model':MODELS[args.model], 'threshold':THRESHOLDS[args.model], 'device':args.device,'platform':platform.platform(),'torch':torch.__version__,'batch_size':args.batch_size,'load_sec':load_sec,'new_records':new_count,'new_chunks':chunk_count,'inference_sec':infer_sec,'latency_seconds':latencies,'latency_ids':[r['id'] for r in sample],'labels':LABELS,'window_chars':180,'overlap_chars':48,'data_hashes':{f:hashlib.sha256((args.data/f).read_bytes()).hexdigest() for f in ['test_kdpii.jsonl','test.jsonl']}}
 (args.out/f'{args.model}.meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
 print('COMPLETE',args.model,flush=True)
if __name__=='__main__':main()
