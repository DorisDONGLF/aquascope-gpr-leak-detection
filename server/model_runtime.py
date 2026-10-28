"""Inference architectures and preprocessing for the original trained weights."""
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
DEVICE="cuda" if torch.cuda.is_available() else "cpu"

class PresenceCNN(nn.Module):
 def __init__(self):
  super().__init__()
  self.features=nn.Sequential(nn.Conv2d(1,12,5,padding=2),nn.GroupNorm(3,12),nn.GELU(),nn.AvgPool2d(2),nn.Conv2d(12,24,3,padding=1),nn.GroupNorm(4,24),nn.GELU(),nn.AvgPool2d(2),nn.Conv2d(24,32,3,padding=1),nn.GroupNorm(4,32),nn.GELU(),nn.AdaptiveAvgPool2d((4,8)))
  self.head=nn.Sequential(nn.Flatten(),nn.Dropout(.3),nn.Linear(1024,32),nn.GELU(),nn.Dropout(.2),nn.Linear(32,1))
 def forward(self,x): return self.head(self.features(x)).flatten()

class PooledLinear(nn.Module):
 def __init__(self):
  super().__init__();self.head=nn.Linear(8*16*2,1)
 def forward(self,x):
  z=torch.cat([F.adaptive_avg_pool2d(x,(8,16)).flatten(1),F.adaptive_avg_pool2d(x.abs(),(8,16)).flatten(1)],1)
  return self.head(z).flatten()

def preprocess(a):
 # Existing positive arrays were resized when extracted; resize raw backgrounds
 # first as well, then normalize, so preprocessing cannot encode the label.
 a=np.asarray(a,dtype=np.float32)
 a=F.interpolate(torch.from_numpy(a.copy())[None,None],size=(128,193),mode='bilinear',align_corners=False)[0]
 lim=float(torch.quantile(a.abs().flatten(),.99)) or 1
 return (a/lim).clamp(-1,1)

class Localizer(nn.Module):
 def __init__(self):
  super().__init__()
  self.visual=nn.Sequential(nn.Conv2d(1,16,5,padding=2),nn.GroupNorm(4,16),nn.GELU(),nn.AvgPool2d((2,1)),nn.Conv2d(16,24,3,padding=1),nn.GroupNorm(4,24),nn.GELU(),nn.AvgPool2d((2,1)),nn.Conv2d(24,32,3,padding=1),nn.GELU())
  layers=[]
  for d in (1,2,4,8):layers.extend([nn.Conv1d(32,32,3,padding=d,dilation=d),nn.GELU()])
  self.horizontal=nn.Sequential(*layers,nn.Conv1d(32,1,1))
 def forward(self,x):return self.horizontal(self.visual(x).mean(2)).squeeze(1)

