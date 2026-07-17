"""LOE v2 — THE APP (final).
Every champion. Every objective. The kit-weighted Omega build.
And — on the face of it, never buried — exactly how much of each build the model actually computes.
"""
import json, os
import item_effects as IE
import rune_effects as RE
import kit_profile as KP
import core

OPT = json.load(open('optimized_v2.json'))
CH = json.load(open('champion_dna.json'))
RU = json.load(open('rune_dna.json'))
IT = json.load(open('item_dna.json'))
DEF = json.load(open('dna_defects.json'))

OBJ = ['omega', 'dps', 'burst', 'ehp', 'sustain', 'utility']
LABEL = dict(omega='Ω Maximize the champion', dps='Max DPS', burst='Max Burst',
             ehp='Max Effective HP', sustain='Max Sustain', utility='Max Utility')

champs = {}
for nm, r in OPT.items():
    c = CH[nm]; ab = c['abilities']
    kit = []
    for s in ('I', 'Q', 'W', 'E', 'R'):
        a = ab.get(s)
        if not a: continue
        bits = []
        if a.get('base'): bits.append(f"{a['base'][4]:.0f} base")
        if a.get('ap'): bits.append(f"{a['ap']:.0%} AP")
        if a.get('ad_total'): bits.append(f"{a['ad_total']:.0%} AD")
        if a.get('ad_bonus'): bits.append(f"{a['ad_bonus']:.0%} bonus AD")
        if a.get('max_hp'): bits.append(f"{a['max_hp']:.1%} max HP")
        if a.get('vamp'): bits.append(f"{a['vamp']:.0%} vamp")
        for k, v in (a.get('amps') or {}).items():
            val = v['values'][4] if isinstance(v, dict) else v
            pc = '%' if (isinstance(v, dict) and v.get('pct')) else ''
            bits.append(f"+{val:.0f}{pc} {k.upper()}")
        kit.append(dict(slot=s, name=a['name'], dtype=a.get('dtype') or '',
                        casts=a.get('casts', 1) or 1, onhit=bool(a.get('triggers_onhit')),
                        cd=(a['cd'][4] if a.get('cd') else None), math=' · '.join(bits) or '—'))
    builds = {}
    for o in OBJ:
        b = r['objectives'].get(o)
        if not b or 'items' not in b: continue
        p = RU[b['keystone']]['path']
        unmod = [it for it in b['items'] + [b['boots']]
                 if it in IT and IT[it]['effects'] and it not in IE.COMPILED]
        builds[o] = dict(items=b['items'], boots=b['boots'], swaps=b['swaps'],
                         page=dict(keystone=b['keystone'], path=p,
                                   primary=[m for m in b['minors'] if RU[m]['path'] == p],
                                   secondary=[m for m in b['minors'] if RU[m]['path'] != p],
                                   sec_path=next((RU[m]['path'] for m in b['minors'] if RU[m]['path'] != p), ''),
                                   shards=[s.replace(' Shard', '') for s in b['shards']]),
                         omega=b.get('omega', 0), dps=b['dps'], burst=b['burst'], ehp=b['ehp'],
                         sustain=b['sustain'], utility=b['utility'], targets=b['per_target'],
                         modelled=b.get('modelled', 0), unmodelled=unmod)
    prof = KP.kit_profile(nm)
    cv = r['conversion']
    champs[nm] = dict(kit=kit, builds=builds, coverage=r['coverage'],
                      auto_reliance=prof['auto_reliance'], weights=KP.omega_weights(nm),
                      conv=dict(ap=cv['ap_scaling'], ad=cv['ad_scaling'], hp=cv['hp_scaling'],
                                cd=cv['mean_basic_cd'], rng=cv['range'], res=cv['resource']))

defect_champs = {x.split('/')[0] for v in DEF.get('defects', {}).values() for x in v}
honesty = dict(
    items_total=len(core.LEGENDARIES),
    items_modelled=sum(1 for n in core.LEGENDARIES if n in IE.COMPILED or not IT[n]['effects']),
    keystones_modelled=sum(1 for n, x in RU.items() if x['kind'] == 'KEYSTONE' and n in RE.COMPILED),
    keystones_total=sum(1 for x in RU.values() if x['kind'] == 'KEYSTONE'),
    rejected=len(IE.REJECTED), rejected_list=IE.REJECTED,
    defect_champs=len(defect_champs), unmodelled_runes=len(RE.UNMODELLED))

DATA = json.dumps(dict(champs=champs, labels=LABEL, objs=OBJ, honesty=honesty,
                       stats=dict(n=len(champs), builds=len(champs) * len(OBJ))),
                  separators=(',', ':'))

HTML = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>LOE v2 · Knowledge Output</title>
<style>
:root{--bg:#11151b;--bg2:#181e26;--panel:#212933;--line:#313b48;--fg:#e8ece9;--dim:#8b97a1;
--grn:#3f8f6d;--gold:#c99b2e;--amb:#e3bc61;--vio:#9b8ad6;--red:#c96a5a;--mono:ui-monospace,Menlo,Consolas,monospace}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--fg);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:24px 28px 16px;background:var(--bg2);border-bottom:1px solid var(--line)}
.eyebrow{font:600 11px/1 var(--mono);letter-spacing:.22em;color:var(--gold);text-transform:uppercase}
h1{font-size:26px;font-weight:800;margin:8px 0 6px;letter-spacing:-.015em}h1 span{color:var(--grn)}
.blind{font:12px/1.6 var(--mono);color:var(--dim);max-width:88ch}
.stats{display:flex;gap:24px;margin-top:12px;font:12px var(--mono);color:var(--dim);flex-wrap:wrap}
.stats b{display:block;color:var(--fg);font-size:16px;font-variant-numeric:tabular-nums}
nav{display:flex;gap:2px;padding:0 28px;background:var(--bg2);border-bottom:1px solid var(--line)}
nav button{background:none;border:0;border-bottom:2px solid transparent;color:var(--dim);font:600 13px system-ui;padding:11px 14px;cursor:pointer}
nav button.on{color:var(--fg);border-color:var(--gold)}
main{display:grid;grid-template-columns:222px 1fr;min-height:74vh}
aside{border-right:1px solid var(--line);max-height:calc(100vh - 172px);overflow:auto}
aside input{width:calc(100% - 22px);margin:11px;padding:8px 10px;background:var(--panel);border:1px solid var(--line);border-radius:6px;color:var(--fg);font:13px var(--mono)}
aside ul{list-style:none;padding:0 0 20px}
aside li{padding:6px 16px;cursor:pointer;font-size:13.5px}
aside li:hover{background:var(--panel)} aside li.on{background:var(--grn);color:#fff}
section{padding:24px 30px;max-width:1040px}
.cname{font-size:31px;font-weight:800;letter-spacing:-.02em;margin:2px 0}
.sub{font:12.5px var(--mono);color:var(--dim);margin-bottom:8px}.sub b{color:var(--amb);font-weight:600}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:16px 0 14px}
.tabs button{background:var(--panel);border:1px solid var(--line);color:var(--dim);border-radius:999px;padding:6px 13px;font:600 12px system-ui;cursor:pointer}
.tabs button.on{background:var(--gold);border-color:var(--gold);color:#1a1206}
.tabs button.om{border-color:var(--grn);color:var(--grn)} .tabs button.om.on{background:var(--grn);border-color:var(--grn);color:#fff}
.grid{display:grid;grid-template-columns:1.05fr 1fr;gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:15px 17px}
.card h3{font:700 10px var(--mono);letter-spacing:.18em;color:var(--dim);text-transform:uppercase;margin-bottom:11px}
ul.items{list-style:none;padding:0}
ul.items li{padding:5px 0;border-bottom:1px dashed var(--line);font-size:13.5px;display:flex;justify-content:space-between}
ul.items li:last-child{border:0} ul.items li.b{color:var(--dim)}
ul.items li i{font-style:normal;font:9px var(--mono);color:var(--red);align-self:center}
.nums{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;text-align:center;font-family:var(--mono)}
.nums b{display:block;font-size:17px;font-variant-numeric:tabular-nums}
.nums span{font-size:9px;letter-spacing:.1em;color:var(--dim);text-transform:uppercase}
.page{display:grid;grid-template-columns:1fr 1fr .75fr;gap:10px;font-size:12.5px;margin-top:14px}
.tree{border:1px solid var(--line);border-radius:8px;padding:9px}
.tree h4{font:700 9px var(--mono);letter-spacing:.16em;text-transform:uppercase;margin-bottom:7px;color:var(--amb)}
.tree .k{font-weight:700;padding:4px 7px;background:var(--bg2);border-radius:5px;margin-bottom:6px;border-left:3px solid var(--gold)}
.tree div.r{padding:3px 7px;color:#c8d0cc}.tree div.r::before{content:"·";color:var(--dim);margin-right:6px}
table{border-collapse:collapse;width:100%}
td,th{padding:6px 9px;font-size:12.5px;text-align:left;border-bottom:1px solid var(--line)}
th{font:700 9px var(--mono);letter-spacing:.14em;color:var(--dim);text-transform:uppercase}
td.n{font-family:var(--mono);font-variant-numeric:tabular-nums}
.kit td:first-child{font:700 11px var(--mono);color:var(--amb);width:26px}
.tag{display:inline-block;font:600 9px var(--mono);padding:2px 6px;border-radius:99px;border:1px solid var(--line);color:var(--dim);margin-left:5px}
.tag.oh{border-color:var(--gold);color:var(--amb)} .tag.mc{border-color:var(--vio);color:var(--vio)}
.seal{display:inline-flex;align-items:center;gap:6px;font:700 10px var(--mono);letter-spacing:.13em;color:#141a12;background:linear-gradient(160deg,var(--gold),var(--amb));padding:4px 10px;border-radius:99px}
.seal::before{content:"◆"}
.wbar{display:flex;height:7px;border-radius:4px;overflow:hidden;margin:8px 0 3px}
.wbar i{display:block;height:100%}
.wl{font:9px var(--mono);color:var(--dim);display:flex;gap:10px;flex-wrap:wrap}
.conf{font:11px var(--mono);color:var(--dim);margin-top:11px;padding-top:9px;border-top:1px solid var(--line)}
.conf b{color:var(--amb)} .conf .bad{color:var(--red)}
footer{padding:20px 28px;border-top:1px solid var(--line);font:11px var(--mono);color:var(--dim)}
@media(max-width:820px){main{grid-template-columns:1fr}.grid,.page{grid-template-columns:1fr}}
</style></head><body>
<header>
 <div class="eyebrow">LOE Synergy Engine v2 · patch 26.13 · wiki.leagueoflegends.com</div>
 <h1>Knowledge <span>Output</span></h1>
 <div class="blind">Pure mathematical build discovery. No meta, no win rates, no pick rates, no tier lists — ever.<br>
 <b>Ω</b> is the kit-weighted objective: the one build that lifts the most of what THIS champion actually does, with weights read from their own kit rather than chosen by hand. The five other objectives stay separate and are all reported — a champion has as many optimal builds as they have things they do. Every build is mutation-proven: no legal single swap of any item, boot, keystone, rune or shard improves it.</div>
 <div class="stats" id="st"></div>
</header>
<nav><button class="on" data-t="c">Champions</button><button data-t="h">What we do NOT model</button></nav>
<main>
 <aside id="rail"><input id="q" placeholder="Search champions…"><ul id="list"></ul></aside>
 <section id="view"></section>
</main>
<footer>The data is the referee · validate the champion, not just the build · nothing ships unproven · honest limits, published</footer>
<script>
const D=__DATA__, $=s=>document.querySelector(s);
const names=Object.keys(D.champs).sort();
let tab='c', cur=names[0], obj='omega';
const COL={dps:'#c96a5a',burst:'#c99b2e',ehp:'#3f8f6d',sustain:'#9b8ad6',utility:'#5a8fc9'};
$('#st').innerHTML=`<div><b>${D.stats.n}</b>champions</div><div><b>${D.stats.builds}</b>proven builds</div><div><b>${D.honesty.items_modelled}/${D.honesty.items_total}</b>items modelled</div><div><b>${D.honesty.keystones_modelled}/${D.honesty.keystones_total}</b>keystones modelled</div><div><b>${D.honesty.rejected}</b>parser lies rejected</div><div><b>${D.honesty.defect_champs}</b>with data defects</div>`;
function rail(){const q=$('#q').value.toLowerCase();
 $('#list').innerHTML=names.filter(n=>n.toLowerCase().includes(q)).map(n=>`<li data-n="${n}" class="${n===cur?'on':''}">${n}</li>`).join('');}
function champ(n){
 const c=D.champs[n], b=c.builds[obj];
 if(!b){$('#view').innerHTML=`<div class="cname">${n}</div><div class="sub">no proven build for this objective</div>`;return;}
 const p=b.page, W=c.weights;
 const wbar=Object.keys(W).map(k=>`<i style="width:${(W[k]*100).toFixed(1)}%;background:${COL[k]}"></i>`).join('');
 const wlab=Object.keys(W).map(k=>`<span style="color:${COL[k]}">■</span> ${k} ${(W[k]*100).toFixed(0)}%`).join(' ');
 $('#view').innerHTML=`
 <span class="seal">MUTATION PROVEN</span>
 <span class="tag">kit coverage ${c.coverage}</span>
 <span class="tag">auto-reliance ${(c.auto_reliance*100).toFixed(0)}%</span>
 <div class="cname">${n}</div>
 <div class="sub">kit converts · AP <b>${c.conv.ap.toFixed(2)}</b> · AD <b>${c.conv.ad.toFixed(2)}</b> · %HP <b>${(c.conv.hp*100).toFixed(1)}%</b> · mean CD <b>${c.conv.cd}s</b> · range <b>${c.conv.rng}</b> · ${c.conv.res}</div>
 <div class="wbar">${wbar}</div><div class="wl">Ω weights, read from this kit: ${wlab}</div>
 <div class="tabs">${D.objs.map(o=>`<button data-o="${o}" class="${o==='omega'?'om ':''}${o===obj?'on':''}">${D.labels[o]}</button>`).join('')}</div>
 <div class="grid">
  <div class="card"><h3>Proven build — ${D.labels[obj]}</h3>
   <ul class="items">${b.items.map(i=>`<li><span>${i}</span>${b.unmodelled.includes(i)?'<i>passive not modelled</i>':''}</li>`).join('')}<li class="b"><span>${b.boots}</span></li></ul>
   <div class="page">
    <div class="tree"><h4>${p.path}</h4><div class="k">${p.keystone}</div>${p.primary.map(r=>`<div class="r">${r}</div>`).join('')}</div>
    <div class="tree"><h4>${p.sec_path||'—'}</h4>${p.secondary.map(r=>`<div class="r">${r}</div>`).join('')}</div>
    <div class="tree"><h4>Shards</h4>${p.shards.map(r=>`<div class="r">${r}</div>`).join('')}</div>
   </div>
   <div class="conf">model confidence · <b>${(b.modelled*100).toFixed(0)}%</b> of this build's items have their passive computed${b.unmodelled.length?` · <span class="bad">${b.unmodelled.length} valued on raw stats alone</span>`:''}</div>
  </div>
  <div class="card"><h3>What this build produces</h3>
   <div class="nums">
    <div><b>${b.dps}</b><span>DPS</span></div><div><b>${b.burst}</b><span>Burst</span></div>
    <div><b>${b.ehp}</b><span>EHP</span></div><div><b>${b.sustain}</b><span>Sustain</span></div>
    <div><b>${b.utility}</b><span>Utility</span></div></div>
   <div style="text-align:center;margin-top:12px;font:700 22px var(--mono);color:var(--grn)">Ω ${b.omega}</div>
   <table style="margin-top:10px"><tr><th>vs target</th><th>DPS</th><th>time to kill</th></tr>
   ${b.targets.map(t=>`<tr><td>${t.t}</td><td class="n">${t.dps}</td><td class="n">${t.ttk}s</td></tr>`).join('')}</table>
   <div style="margin-top:10px;font:11px var(--mono);color:var(--dim)">mutation proof: ${b.swaps} improving swaps taken, then zero remained</div>
  </div>
 </div>
 <div class="card" style="margin-top:16px"><h3>Kit DNA — read from the wiki's current roster</h3>
  <table class="kit"><tr><th></th><th>ability</th><th>type</th><th>cd</th><th>scaling</th></tr>
  ${c.kit.map(k=>`<tr><td>${k.slot}</td><td>${k.name}${k.casts>1?`<span class="tag mc">${k.casts}x cast</span>`:''}${k.onhit?'<span class="tag oh">procs on-hit</span>':''}</td><td>${k.dtype}</td><td class="n">${k.cd?k.cd+'s':'—'}</td><td class="n">${k.math}</td></tr>`).join('')}
  </table></div>`;
}
function honesty(){
 const h=D.honesty;
 $('#view').innerHTML=`<div class="cname">What we do NOT model</div>
 <div class="sub">Published, not buried. A build resting on an unmodelled passive rests on partial information — you should be able to see that.</div>
 <div class="card"><h3>Coverage</h3><table>
 <tr><td>SR legendary items with their passive computed</td><td class="n">${h.items_modelled} / ${h.items_total}</td></tr>
 <tr><td>Keystones with their effect computed</td><td class="n">${h.keystones_modelled} / ${h.keystones_total}</td></tr>
 <tr><td>Runes contributing zero (they cannot win by default)</td><td class="n">${h.unmodelled_runes}</td></tr>
 <tr><td>Champions with published data defects</td><td class="n">${h.defect_champs}</td></tr>
 </table></div>
 <div class="card" style="margin-top:14px"><h3>Sanity gate — parser claims we refused to believe</h3>
 <table>${h.rejected_list.map(r=>`<tr><td style="font:12px var(--mono);color:var(--red)">${r}</td></tr>`).join('')}</table>
 <div style="margin-top:10px;font:11px var(--mono);color:var(--dim)">Each was a regex reading a CONDITION as a PAYLOAD — "at or below 50% of maximum health" parsed as "deals 50% of maximum health". Serylda's Grudge appeared in all 171 builds because of exactly this. They are now honestly unmodelled rather than silently believed.</div></div>`;
}
function render(){
 document.querySelectorAll('nav button').forEach(b=>b.classList.toggle('on',b.dataset.t===tab));
 $('#rail').style.display=tab==='c'?'':'none';
 if(tab==='c'){rail();champ(cur);} else {honesty();}
}
document.querySelector('nav').onclick=e=>{if(e.target.dataset.t){tab=e.target.dataset.t;render();}};
$('#list').onclick=e=>{const n=e.target.closest('li')?.dataset.n; if(n){cur=n;render();}};
$('#view').addEventListener('click',e=>{const o=e.target.dataset?.o; if(o){obj=o;champ(cur);}});
$('#q').oninput=rail;
render();
</script></body></html>"""
open('index.html', 'w').write(HTML.replace('__DATA__', DATA))
print(f'index.html: {os.path.getsize("index.html")//1024} KB · {len(champs)} champions x {len(OBJ)} objectives')
print(f"items modelled {honesty['items_modelled']}/{honesty['items_total']} · "
      f"keystones {honesty['keystones_modelled']}/{honesty['keystones_total']} · "
      f"parser lies rejected {honesty['rejected']}")
