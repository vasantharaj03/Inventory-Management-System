/* Visual effects for the classic pages (same settings as the React app: localStorage "stk_fx2") */
(()=>{
const RM=matchMedia('(prefers-reduced-motion:reduce)').matches,D={glow:!RM,glitter:!RM,particles:!RM,parallax:!RM,magnetic:!RM};
let S;try{S={...D,...JSON.parse(localStorage.getItem('stk_fx2')||'{}')}}catch(e){S={...D}}
const css=document.createElement('style');css.textContent=`
main{position:relative;z-index:1}aside{z-index:2}.card{position:relative}
.glit{position:fixed;inset:0;pointer-events:none;z-index:9999}.ptc{position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.8}
.bgfx{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden}.blob{position:absolute;border-radius:50%;filter:blur(90px);opacity:.2;transition:transform .5s ease-out;transform:translate(calc(var(--px,0)*var(--f)*1px),calc(var(--py,0)*var(--f)*1px))}
[data-theme=dark] .blob{opacity:.4}.b1{--f:-70;width:520px;height:520px;left:-6%;top:-10%;background:#3B82F6}.b2{--f:110;width:460px;height:460px;right:-8%;top:10%;background:#8B5CF6}.b3{--f:-150;width:520px;height:520px;left:35%;bottom:-25%;background:#22D3EE}[data-theme=dark]:before{display:none}
.orb{position:fixed;left:0;top:0;width:300px;height:300px;border-radius:50%;pointer-events:none;z-index:9998;background:radial-gradient(circle,#7C8CFF45,#0000 65%);mix-blend-mode:screen;will-change:transform}[data-theme=light] .orb{mix-blend-mode:multiply;background:radial-gradient(circle,#5B5BF52e,#0000 65%)}
.card:not(.bz)::before{content:"";position:absolute;inset:0;border-radius:inherit;padding:1.5px;background:radial-gradient(220px circle at var(--mx,50%) var(--my,50%),#7C8CFF,#0000 70%);-webkit-mask:linear-gradient(#000 0 0) content-box,linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;opacity:0;transition:.3s;pointer-events:none}.card:not(.bz):hover::before{opacity:1}
.card:not(.pc):not(.bz)::after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:.3s;background:radial-gradient(300px circle at var(--mx,50%) var(--my,50%),#7C8CFF14,#0000 60%)}.card:not(.pc):not(.bz):hover::after{opacity:1}
.pc,.bz{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg));transition:transform .18s ease-out,box-shadow .3s,opacity .3s,filter .3s;will-change:transform}
.pc:hover,.bz:hover{transform:perspective(900px) rotateX(var(--rx,0deg)) rotateY(var(--ry,0deg)) translateY(-8px) scale(1.015);box-shadow:0 30px 50px -24px #5B5BF5aa,0 0 0 1px #5B5BF566}
.pc:after,.bz:after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;opacity:0;transition:.25s;background:radial-gradient(260px circle at var(--mx,50%) var(--my,50%),#ffffff30,#0000 60%)}.pc:hover:after,.bz:hover:after{opacity:1}
.items:hover .pc:not(:hover){opacity:.5;filter:saturate(.6)}.pc .tile .pi{transition:transform .4s cubic-bezier(.2,.8,.2,1)}.pc:hover .tile .pi{transform:scale(1.14) rotate(-4deg) translateY(-4px)}
.btn,.ch,.pager button,.seg button{transform:translate(var(--tx,0px),var(--ty,0px));transition:transform .2s ease-out,box-shadow .2s,background .2s}.btn:hover{transform:translate(var(--tx,0px),calc(var(--ty,0px) - 1px))}.btn:active{transform:translate(var(--tx,0px),var(--ty,0px)) scale(.96)}
.fxb{position:fixed;right:22px;bottom:84px;z-index:10000;width:46px;height:46px;border-radius:50%;border:1px solid var(--line);background:var(--card);color:var(--ink);font-size:20px;cursor:pointer;box-shadow:0 10px 30px -10px #0008}
.fxp{position:fixed;right:22px;bottom:140px;z-index:10000;width:270px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:16px;padding:14px 16px;box-shadow:0 20px 50px -16px #000a}.fxp[hidden]{display:none}.fxp label{display:flex;justify-content:space-between;align-items:center;padding:8px 0;cursor:pointer;margin:0}.fxp input{width:auto;accent-color:#5B5BF5}
`;document.head.appendChild(css);
const mk=(t,c,p)=>{const e=document.createElement(t);e.className=c;(p||document.body).appendChild(e);return e};
const bg=mk('div','bgfx');bg.innerHTML='<i class="blob b1"></i><i class="blob b2"></i><i class="blob b3"></i>';
const orb=mk('div','orb'),gl=mk('canvas','glit'),pt=mk('canvas','ptc'),gx=gl.getContext('2d'),px=pt.getContext('2d');
let W,H,P=[],G=[],tx=innerWidth/2,ty=innerHeight/2,ox=tx,oy=ty;const COLS=['#FFD700','#FFF3B0','#7DD3FC','#F9A8D4','#C4B5FD','#FFFFFF'];
const rs=()=>{W=gl.width=pt.width=innerWidth;H=gl.height=pt.height=innerHeight;P=[...Array(Math.min(70,Math.round(W*H/26000)))].map(()=>({x:Math.random()*W,y:Math.random()*H,vx:(Math.random()-.5)*.35,vy:(Math.random()-.5)*.35}))};rs();addEventListener('resize',rs);
const L=[['glow','Glow cursor & card glow'],['glitter','Glitter trail'],['particles','Particle background'],['parallax','Parallax background'],['magnetic','Magnetic buttons']];
const btn=mk('button','fxb');btn.textContent='✨';btn.title='Visual effects';const pn=mk('div','fxp');pn.hidden=true;
pn.innerHTML='<b>Visual effects</b>'+L.map(l=>`<label><span>${l[1]}</span><input type="checkbox" data-k="${l[0]}"></label>`).join('');
btn.onclick=()=>{pn.hidden=!pn.hidden};
const apply=()=>{pn.querySelectorAll('input').forEach(i=>{i.checked=!!S[i.dataset.k]});orb.style.display=S.glow?'':'none';gl.style.display=S.glitter?'':'none';pt.style.display=S.particles?'':'none';if(!S.glitter)G.length=0};
pn.onchange=e=>{const k=e.target.dataset.k;if(k){S[k]=e.target.checked;localStorage.setItem('stk_fx2',JSON.stringify(S));apply()}};apply();
const MG='.btn,.ch,.pager button,.seg button',TL='.pc,.bz';
addEventListener('mousemove',e=>{tx=e.clientX;ty=e.clientY;
 if(S.glitter){for(let i=0;i<2;i++)G.push({x:e.clientX+(Math.random()-.5)*10,y:e.clientY+(Math.random()-.5)*10,vx:(Math.random()-.5)*1.6,vy:Math.random()*1.2-.3,s:Math.random()*5+3,l:1,c:COLS[Math.random()*COLS.length|0],r:Math.random()*6,vr:(Math.random()-.5)*.2});if(G.length>240)G.splice(0,G.length-240)}
 if(S.parallax){const o=document.documentElement.style;o.setProperty('--px',(e.clientX/innerWidth-.5).toFixed(3));o.setProperty('--py',(e.clientY/innerHeight-.5).toFixed(3))}
 const t=e.target;if(!t.closest)return;
 const c=t.closest('.card');if(c&&S.glow){const r=c.getBoundingClientRect();c.style.setProperty('--mx',((e.clientX-r.left)/r.width*100).toFixed(0)+'%');c.style.setProperty('--my',((e.clientY-r.top)/r.height*100).toFixed(0)+'%')}
 const k=t.closest(TL);if(k){const r=k.getBoundingClientRect(),x=(e.clientX-r.left)/r.width,y=(e.clientY-r.top)/r.height,o=k.style;o.setProperty('--rx',((.5-y)*10).toFixed(2)+'deg');o.setProperty('--ry',((x-.5)*12).toFixed(2)+'deg');o.setProperty('--mx',(x*100).toFixed(0)+'%');o.setProperty('--my',(y*100).toFixed(0)+'%')}
 if(S.magnetic){const m=t.closest(MG);if(m){const r=m.getBoundingClientRect();m.style.setProperty('--tx',((e.clientX-r.left-r.width/2)*.22).toFixed(1)+'px');m.style.setProperty('--ty',((e.clientY-r.top-r.height/2)*.3).toFixed(1)+'px')}}});
addEventListener('mouseout',e=>{const t=e.target;if(!t.closest)return;const k=t.closest(TL);if(k&&!k.contains(e.relatedTarget)){k.style.setProperty('--rx','0deg');k.style.setProperty('--ry','0deg')}
 const m=t.closest(MG);if(m&&!m.contains(e.relatedTarget)){m.style.setProperty('--tx','0px');m.style.setProperty('--ty','0px')}});
const star=s=>{gx.beginPath();for(let i=0;i<8;i++){const a=i*Math.PI/4,r=i%2?s*.28:s;gx.lineTo(Math.cos(a)*r,Math.sin(a)*r)}gx.closePath();gx.fill()};
(function loop(){ox+=(tx-ox)*.15;oy+=(ty-oy)*.15;if(S.glow)orb.style.transform=`translate(${ox-150}px,${oy-150}px)`;
 if(S.glitter){gx.clearRect(0,0,W,H);for(let i=G.length-1;i>=0;i--){const p=G[i];p.x+=p.vx;p.y+=p.vy;p.vy+=.03;p.l-=.022;p.r+=p.vr;if(p.l<=0){G.splice(i,1);continue}gx.save();gx.globalAlpha=p.l;gx.translate(p.x,p.y);gx.rotate(p.r);gx.fillStyle=p.c;gx.shadowColor=p.c;gx.shadowBlur=10;star(p.s*(.5+p.l/2));gx.restore()}}
 if(S.particles){px.clearRect(0,0,W,H);const col=document.documentElement.dataset.theme==='dark'?'140,160,255':'91,91,245';
  for(const p of P){p.x+=p.vx;p.y+=p.vy;if(p.x<0||p.x>W)p.vx*=-1;if(p.y<0||p.y>H)p.vy*=-1;px.fillStyle=`rgba(${col},.55)`;px.beginPath();px.arc(p.x,p.y,1.6,0,7);px.fill()}
  for(let i=0;i<P.length;i++)for(let j=i+1;j<P.length;j++){const d=Math.hypot(P[i].x-P[j].x,P[i].y-P[j].y);if(d<120){px.strokeStyle=`rgba(${col},${((1-d/120)*.25).toFixed(3)})`;px.beginPath();px.moveTo(P[i].x,P[i].y);px.lineTo(P[j].x,P[j].y);px.stroke()}}}
 requestAnimationFrame(loop)})();
})();