from pathlib import Path
import json,html
import argparse
parser=argparse.ArgumentParser(description='Build an editable, evidence-grounded Hyperframes backend demo.')
parser.add_argument('--output', type=Path, default=Path('brag-output/composition'))
args=parser.parse_args()
root=args.output.resolve()
(root/'compositions').mkdir(exist_ok=True)
css='''@font-face{font-family:"Demo Display";src:url("fonts/display.ttf")}@font-face{font-family:"Demo Body";src:url("fonts/body.ttf")}@font-face{font-family:"Demo Mono";src:url("fonts/mono.ttf")}
*{box-sizing:border-box}body{margin:0}.stage{position:absolute;inset:0;background:var(--color-ground,#111C22);color:var(--color-ink,#F4F1E9);font-family:"Demo Body";overflow:hidden}.kicker{font-family:"Demo Mono";font-size:28px;letter-spacing:2px;color:var(--color-accent,#F2C14E)}.title{font-family:"Demo Display";font-size:88px;line-height:1.12;margin:0}.sub{font-size:32px;line-height:1.4;color:#B8C5CB}.mono{font-family:"Demo Mono";font-size:28px;line-height:1.6}.head{position:absolute;left:192px;top:120px}.foot{position:absolute;left:192px;bottom:108px;font-size:28px;color:#B8C5CB}.rule{height:2px;background:#50636D}.panel{background:#1D2C34;border:2px solid #50636D;border-radius:18px}.photo{width:100%;height:100%;object-fit:contain;display:block}.amber{color:#F2C14E}.small{font-size:28px}.badge{padding:18px 24px;border:2px solid #F2C14E;color:#F2C14E;font:28px "Demo Mono";display:inline-block}.value{font:64px "Demo Display"}.p28{padding:28px}.row{margin:22px 0}.label{font:28px "Demo Mono";color:#B8C5CB}
'''
(root/'assets/theme.css').write_text(css)
base='<link rel="stylesheet" href="assets/theme.css"><style>#root{position:absolute;inset:0}</style>'
def scene(name,markup,script):
 text='<template>'+base+f'<div id="root" data-composition-id="{name}" data-width="1920" data-height="1080"><div class="stage" id="{name}-stage">'+markup+'</div></div><script>'+script+f'\nwindow.__timelines["{name}"]=tl;</script></template>'
 (root/'compositions'/f'{name}.html').write_text(text)
scene('hook','''<div class="kicker" style="position:absolute;left:192px;top:140px">INDUSTRIAL EQUIPMENT / BACKEND DEMO</div>
<div id="hook-copy" data-hold style="position:absolute;left:192px;top:310px;width:660px"><h1 class="title">Read the plate.<br><span class="amber">Keep the evidence.</span></h1><p class="sub" style="margin-top:40px">A real photo.<br>A reviewable result.</p></div>
<div id="hook-photo" class="panel" style="position:absolute;left:940px;top:310px;width:788px;height:444px;padding:0;overflow:hidden"><img class="photo" src="assets/nameplate.jpg"></div>
<div class="foot">Presentation view · frontend in progress</div>''','''const tl=gsap.timeline({paused:true});
tl.fromTo('#hook-photo',{x:70,opacity:0.25},{x:0,opacity:1,duration:.85,ease:'power4.out'},0);
tl.fromTo('#hook-copy',{opacity:.35},{opacity:1,duration:.5,ease:'power2.out'},.15);
tl.to('#hook-photo',{scale:1.01,duration:.5,ease:'power2.inOut'},3.75);''')
case=json.loads((root/'assets/evidence.json').read_text())['case'];box=case['detections'][0]['box'];x,y,x2,y2=box
svg=f'''<svg style="position:absolute;inset:0;width:100%;height:100%" viewBox="0 0 1600 900" aria-hidden="true"><rect id="detect-box" x="{x}" y="{y}" width="{x2-x}" height="{y2-y}" fill="none" stroke="#F2C14E" stroke-width="7"/></svg>'''
markup='''<div class="head"><div class="kicker">01 / LOCATE THE NAMEPLATE</div><h1 class="title" style="font-size:70px;margin-top:20px">A region. Original-image coordinates.</h1></div>
<div class="panel" id="detect-photo" style="position:absolute;left:192px;top:300px;width:1080px;height:608px;overflow:hidden"><img class="photo" src="assets/nameplate.jpg">'''+svg+'''</div>
<div id="detect-result" class="panel p28" style="position:absolute;left:1320px;top:300px;width:408px;height:608px"><div class="label">MODEL OUTPUT</div><div class="value amber" style="font-size:46px;margin-top:42px">Nameplate</div><div class="rule" style="margin:35px 0"></div><div class="label">Detector score</div><div class="value" style="margin-top:16px">0.926</div><div class="sub" style="font-size:29px;margin-top:50px">Local ONNX<br>CPU inference</div></div>
<div class="foot" style="bottom:70px">Actual model output · presentation view</div>'''
audio=json.loads((root/'assets/music/audio-data.json').read_text())
script='''const tl=gsap.timeline({paused:true});
tl.fromTo('#detect-photo',{x:-35,opacity:0},{x:0,opacity:1,duration:.6,ease:'power4.out'},0);
tl.fromTo('#detect-result',{x:45,opacity:0},{x:0,opacity:1,duration:.65,ease:'expo.out'},.55);
// beat-locked: 8.74s global = 4.35s local. Real measured box, no simulated match.
tl.fromTo('#detect-box',{strokeDasharray:3600,strokeDashoffset:3600,opacity:0},{strokeDashoffset:0,opacity:1,duration:.7,ease:'power2.out'},3.65);
'''
# Build-time measured audio modulation: never changes text or the measured box coordinates.
for f in range(263,int(10.93*30),3):
 frame=audio['frames'][f];bands=frame.get('bands',[]);energy=max(bands[:2] or [0]);opacity=.72+min(1,energy)*.24
 script+=f"tl.to('#detect-box',{{opacity:{opacity:.4f},duration:.1,ease:'none'}},{f/30-4.39:.4f});\n"
scene('detect',markup,script)
raw=json.loads((root/'assets/evidence.json').read_text())['ocr']
line1=html.escape(raw[2]['text']);line2=html.escape(raw[4]['text'])
scene('evidence',f'''<div class="head"><div class="kicker">02 / KEEP THE REVIEW BOUNDARY</div><h1 class="title" style="font-size:64px;margin-top:20px">Text is evidence. Confirmation is human.</h1></div>
<div id="evidence-crop" class="panel" style="position:absolute;left:192px;top:320px;width:680px;height:440px;overflow:hidden"><img class="photo" src="assets/crop.png"></div>
<div id="evidence-card" class="panel p28" style="position:absolute;left:920px;top:320px;width:808px;height:560px"><div class="kicker" style="font-size:28px">RAW OCR · UNVERIFIED</div><div id="evidence-line1" class="mono" style="margin-top:40px;font-size:28px">{line1}</div><div id="evidence-line2" class="mono" style="margin-top:22px;font-size:28px">{line2}</div><div class="rule" style="margin:38px 0"></div><div id="evidence-status" data-hold><div class="badge">Needs human confirmation</div><div class="sub" style="margin-top:26px;font-size:30px">No verified tag or serial.</div></div></div>
<div class="foot" style="bottom:80px">8 OCR lines returned · identifiers not accepted · presentation view</div>''','''const tl=gsap.timeline({paused:true});
tl.fromTo('#evidence-crop',{opacity:0},{opacity:1,duration:.45,ease:'power2.out'},0);
tl.fromTo('#evidence-card',{x:40,opacity:0},{x:0,opacity:1,duration:.6,ease:'power4.out'},.2);
// Sequential text settles and holds; not every beat is a new sentence.
tl.fromTo('#evidence-line1',{opacity:0},{opacity:1,duration:.25},.9);
tl.fromTo('#evidence-line2',{opacity:0},{opacity:1,duration:.25},1.64);
tl.fromTo('#evidence-status',{opacity:0},{opacity:1,duration:.35},2.3);''')
scene('close','''<div class="kicker" style="position:absolute;left:192px;top:140px">LOCAL DETECTION / EVIDENCE / HUMAN REVIEW</div>
<div id="close-copy" style="position:absolute;left:192px;top:310px;width:960px"><h1 class="title">Photo → plate<br>→ <span class="amber">evidence.</span></h1><div class="sub" style="margin-top:38px">Identity confirmation stays human.</div></div>
<div id="close-metric" class="panel p28" style="position:absolute;left:1240px;top:320px;width:488px;height:320px"><div class="value amber" style="font-size:78px">72–75 ms</div><div class="sub" style="margin-top:24px">Warm CPU detector<br>4 public-image smoke cases</div></div>
<div style="position:absolute;left:192px;top:820px;font:28px 'Demo Mono';color:#B8C5CB">Backend demo · web interface in progress</div>
<div style="position:absolute;left:192px;top:895px;font-size:28px;color:#B8C5CB">Image: SAM31416 · CC BY-SA 4.0  |  Music: Sascha Ende / ende.app · CC BY 4.0</div>''','''const tl=gsap.timeline({paused:true});
// beat-locked: 17.47s global, strong cue for final reveal.
tl.fromTo('#close-copy',{opacity:0},{opacity:1,duration:.4,ease:'power2.out'},0);
tl.fromTo('#close-metric',{y:30,opacity:0},{y:0,opacity:1,duration:.65,ease:'expo.out'},.25);''')
variables=[{'id':'color-ground','type':'color','label':'Steel ground','default':'#111C22'},{'id':'color-ink','type':'color','label':'Paper ink','default':'#F4F1E9'},{'id':'color-accent','type':'color','label':'Evidence accent','default':'#F2C14E'}]
hosts=''
for n,start,dur,i in [('hook',0,4.39,1),('detect',4.39,6.54,2),('evidence',10.93,6.54,3),('close',17.47,4.53,4)]:
 hosts+=f'<div id="{n}" class="clip" data-composition-id="{n}" data-composition-src="compositions/{n}.html" data-start="{start}" data-duration="{dur}" data-track-index="{i}" data-track-kind="graphics" data-width="1920" data-height="1080"></div>\n'
(root/'index.html').write_text('''<!doctype html><html lang="en" data-composition-variables='''+"'"+json.dumps(variables)+"'"+'''><head><meta charset="utf-8"><meta name="viewport" content="width=1920,height=1080"><script src="assets/vendor/gsap.min.js"></script><style>html,body{margin:0;width:1920px;height:1080px;overflow:hidden;background:#111C22}#root{position:relative;width:100%;height:100%}.clip{position:absolute;inset:0}</style></head><body><div id="root" data-composition-id="main" data-start="0" data-duration="22" data-width="1920" data-height="1080">'''+hosts+'''<audio id="music" class="clip" data-start="0" data-duration="22" data-track-index="10" data-volume=".20" data-fade-in=".4" data-fade-out="1.5" src="assets/music/bed.mp3"></audio><audio id="click" class="clip" data-start="4.39" data-duration=".01" data-track-index="11" data-volume=".28" src="assets/sfx/click.ogg"></audio><audio id="region" class="clip" data-start="8.74" data-duration=".18" data-track-index="12" data-volume=".25" src="assets/sfx/reveal.ogg"></audio><audio id="final" class="clip" data-start="17.47" data-duration=".18" data-track-index="13" data-volume=".3" src="assets/sfx/reveal.ogg"></audio></div><script>window.__timelines=window.__timelines||{};window.__timelines.main=gsap.timeline({paused:true});</script></body></html>''')
print('Four editable scene compositions written.')

# Expose local font faces to the compiler as well as the browser stylesheet.
index=root/'index.html'
index.write_text(index.read_text().replace('</style></head>', css.split('*{')[0].replace('url("fonts/', 'url("assets/fonts/')+'</style></head>'))
