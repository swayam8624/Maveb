#!/usr/bin/env python3
"""Generate deterministic vector figures from S1 evaluator JSON without plotting dependencies."""
from __future__ import annotations
import argparse,html,json,math
from pathlib import Path

def points(summary,w,h,pad):
    pts=[]
    for p in summary["points"]:
      x=pad+(w-2*pad)*p["changedFraction"]
      y=h-pad-(h-2*pad)*min(max(p["ulr"],0.0),1.0)
      pts.append((x,y))
    return pts

def render(result:dict)->str:
    width,height,pad=1200,760,90
    layers=list(result["layers"].items())
    palette=["#2563eb","#dc2626","#059669","#7c3aed","#d97706","#0891b2","#4f46e5","#be123c","#15803d"]
    body=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
          '<rect width="100%" height="100%" fill="white"/>',
          f'<line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="black"/>',
          f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height-pad}" stroke="black"/>',
          f'<text x="{width/2}" y="{height-20}" text-anchor="middle" font-family="sans-serif" font-size="22">Changed world fraction</text>',
          f'<text x="26" y="{height/2}" transform="rotate(-90 26 {height/2})" text-anchor="middle" font-family="sans-serif" font-size="22">Update Locality Ratio</text>']
    for tick in (0,0.25,0.5,0.75,1.0):
      x=pad+(width-2*pad)*tick; y=height-pad-(height-2*pad)*tick
      body += [f'<line x1="{x}" y1="{height-pad}" x2="{x}" y2="{height-pad+8}" stroke="black"/>',
               f'<text x="{x}" y="{height-pad+30}" text-anchor="middle" font-family="sans-serif" font-size="15">{tick:g}</text>',
               f'<line x1="{pad-8}" y1="{y}" x2="{pad}" y2="{y}" stroke="black"/>',
               f'<text x="{pad-15}" y="{y+5}" text-anchor="end" font-family="sans-serif" font-size="15">{tick:g}</text>']
    for i,(name,summary) in enumerate(layers):
      color=palette[i%len(palette)]; ps=points(summary,width,height,pad)
      poly=" ".join(f"{x:.2f},{y:.2f}" for x,y in ps)
      body.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="3"/>')
      for x,y in ps: body.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4" fill="{color}"/>')
      lx=width-300; ly=55+i*24
      body += [f'<line x1="{lx}" y1="{ly}" x2="{lx+24}" y2="{ly}" stroke="{color}" stroke-width="3"/>',
               f'<text x="{lx+32}" y="{ly+5}" font-family="sans-serif" font-size="14">{html.escape(name)}</text>']
    body.append('</svg>')
    return "\n".join(body)+"\n"

def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("input",type=Path); ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args(); result=json.loads(a.input.read_text()); svg=render(result)
    a.output.parent.mkdir(parents=True,exist_ok=True); tmp=a.output.with_suffix(a.output.suffix+".tmp"); tmp.write_text(svg); tmp.replace(a.output)
    return 0
if __name__=="__main__": raise SystemExit(main())
