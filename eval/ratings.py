"""Per-family, per-rung experimental ratings."""
from dataclasses import dataclass,field
@dataclass
class Ratings:
    scores:dict=field(default_factory=dict)
    def get(self,family,rung):
        return self.scores.get((family,rung),1500.)
    def update(self,a,b,rung,score_a,k=16):
        if a==b or not 0<=score_a<=1: raise ValueError("Invalid matchup")
        ra,rb=self.get(a,rung),self.get(b,rung)
        expected=1/(1+10**((rb-ra)/400))
        self.scores[(a,rung)]=ra+k*(score_a-expected)
        self.scores[(b,rung)]=rb+k*((1-score_a)-(1-expected))
    def ranked(self,rung):
        return sorted(((f,score) for (f,k),score in self.scores.items() if k==rung),
                      key=lambda x:(-x[1],x[0]))
