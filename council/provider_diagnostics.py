"""Inspect one free-provider response structure without hiding empty-content failures.

Only performs live inference with --confirm-free. --raw-out stores sensitive
response data locally, mode 0600; NEVER put that file in a public repository.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from model_router import Candidate, Router, RAW_CAPTURE
from router_errors import CandidateError

def describe(body:dict)->dict:
    result={"top_level_fields":sorted(body)}
    options=body.get("choices") or []
    if options and isinstance(options[0],dict):
        item=options[0]
        message=item.get("message") or {}
        if isinstance(message,dict):
            result["message_fields"]=sorted(message)
            for field in ("content","reasoning_content","reasoning"):
                value=message.get(field)
                result[field+"_present"]=bool(value)
                result[field+"_characters"]=len(value) if isinstance(value,str) else None
        result["finish_reason"]=item.get("finish_reason")
    result["model"]=body.get("model")
    result["usage"]=body.get("usage")
    return result

def sample(provider:str,model:str,prompt:str,*,max_tokens:int=3500):
    router=Router(timeout=35)
    candidate=Candidate(provider,model)
    router.expand(candidate,set())
    observed=[]
    token=RAW_CAPTURE.set(observed)
    try:
        try:
            answer=router.generate(candidate,prompt,max_output_tokens=max_tokens)
            error=None
        except CandidateError as exc:
            error={"category":exc.kind,"description":str(exc)}
            answer=None
        captured=observed[-1] if observed else None
    finally:
        RAW_CAPTURE.reset(token)
    return {"model":model,"provider":provider,"answer":answer,
            "error":error,"captured":captured,
            "diagnosis":describe(captured["body"]) if captured else None}

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--provider",default="LLM7.io")
    p.add_argument("--model",default="minimax-m2.7")
    p.add_argument("--max-tokens",type=int,default=3500)
    p.add_argument("--confirm-free",action="store_true")
    p.add_argument("--raw-out",type=Path)
    args=p.parse_args(argv)
    if not args.confirm_free:
        print("No API request. Check the free allowance, then use --confirm-free.")
        return
    output=sample(args.provider,args.model,
                  "What is 12 multiplied by 13? Give only the final integer.",
                  max_tokens=args.max_tokens)
    public={k:v for k,v in output.items() if k!="captured"}
    print(json.dumps(public,indent=2,ensure_ascii=False))
    if args.raw_out and output["captured"] is not None:
        args.raw_out.parent.mkdir(parents=True,exist_ok=True)
        descriptor=os.open(args.raw_out,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(descriptor,"w",encoding="utf-8") as file:
            json.dump(output["captured"],file,indent=2,ensure_ascii=False)
        os.chmod(args.raw_out,0o600)

if __name__=="__main__":
    main()
