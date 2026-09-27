"""Analytic statistical edge cases that can otherwise create false discoveries."""
import math
import os
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from experiments.reserve_holdout_v2 import effect,holm32

assert os.environ.get('GITHUB_ACTIONS')=='true'
indices=np.random.Generator(np.random.PCG64(19)).integers(0,1000,size=(10000,1000),dtype=np.uint16)
zero=effect(np.zeros(1000),indices)
assert zero['p_raw']==1 and zero['ci95']==[0.,0.] and zero['degenerate']
positive=effect(np.full(1000,.01),indices)
assert positive['degenerate'] and abs(positive['p_raw']-math.exp(-.05))<1e-14
negative=effect(np.full(1000,-.01),indices);assert negative['p_raw']==1
symmetric=effect(np.tile([-.1,.1],500),indices);assert abs(symmetric['p_raw']-.5)<1e-14
adjusted=holm32([.001,.01]+[1.]*30)
assert adjusted[:2]==[.032,.31] and all(p==1 for p in adjusted[2:])
assert holm32([1.]*32)==[1.]*32
print('PASS: zero, constant positive/negative, centered pairing and fixed 32-member Holm family')
