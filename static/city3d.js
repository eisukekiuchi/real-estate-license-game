/* Dependency-free perspective city renderer. World coordinates are x/east, y/up, z/south. */
(() => {
  let active;
  const hex = (h) => { let n = parseInt(h.slice(1),16); return [(n>>16)&255,(n>>8)&255,n&255] };
  const tint = (h,f) => `rgb(${hex(h).map(v=>Math.max(0,Math.min(255,Math.round(v*f)))).join(',')})`;
  const palette = {
    house:['#eed6b5','#b77f60','#b7634f'], shop:['#eadbb5','#c98d70','#7eae96'], convenience:['#dce7e2','#6b9c9c','#5dbca5'],
    apartment:['#ccdce6','#7b9fba','#91b2ca'], tower:['#a3c9d9','#678da7','#8094b2'], castle:['#d7c8db','#a694bd','#82698d'],
    manor:['#e9d8ad','#bda882','#8d94b0'], pagoda:['#f1cf98','#b87766','#bc4a43'], shrine:['#edc498','#bd6655','#cc584e'],
    tree:['#77b773','#6b8850','#4a9563'], park:['#9bd2bb','#78a4a5','#75cabe']
  };
  function mount(stage, owner, buildings, plots, items, select, yawDeg=-37, tiltDeg=58) {
    if(active) active.dispose();
    const canvas=stage.querySelector('.city-canvas'); if(!canvas) return null;
    const ctx=canvas.getContext('2d',{alpha:false}); if(!ctx)return null;
    stage.classList.add('is-rendered');
    const slots=owner?.citySlots||12, rows=Math.ceil(slots/4), byTile=new Map(buildings.map(b=>[b.tile,b])), events=new Map((plots||[]).map(p=>[p.tile,p]));
    let yaw=yawDeg*Math.PI/180, elev=Math.max(.35,Math.min(1.35,tiltDeg*Math.PI/180)), zoom=1, width=0,height=0,dpr=1, raf=0, alive=true, night=false, lastFrame=0;
    let scale=65, pointer=null, selectedTile=-1, time=0;
    const polys=[];let currentLayer=0;
    const center=[1.5,0,(rows-1)/2], distance=12;
    function resize(){let r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;width=r.width;height=r.height;dpr=Math.min(devicePixelRatio||1,2);canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);scale=Math.min(width/(5.2+rows*.12),height/(rows*1.2+1))*zoom}
    function depth(p){let dx=p[0]-center[0],dz=p[2]-center[2];return distance-(Math.sin(yaw)*dx+Math.cos(yaw)*dz)*Math.cos(elev)-p[1]*Math.sin(elev)}
    function project(p){let dx=p[0]-center[0],dz=p[2]-center[2];let right=Math.cos(yaw)*dx-Math.sin(yaw)*dz;
      let up=-Math.sin(yaw)*Math.sin(elev)*dx+Math.cos(elev)*p[1]-Math.cos(yaw)*Math.sin(elev)*dz;
      let factor=distance/Math.max(3,depth(p));return [width/2+right*scale*factor,height*.56-up*scale*factor]}
    function polygon(verts,color,stroke=null,tile=-1,alpha=1){polys.push({verts,color,stroke,tile,alpha,layer:currentLayer,far:verts.reduce((s,v)=>s+depth(v),0)/verts.length})}
    function box(x,z,w,d,h,wall,roof,y=0,tile=-1){let a=x-w/2,b=x+w/2,c=z-d/2,e=z+d/2,t=y+h;
      polygon([[a,y,c],[b,y,c],[b,t,c],[a,t,c]],tint(wall,.84),null,tile);
      polygon([[b,y,c],[b,y,e],[b,t,e],[b,t,c]],tint(wall,.72),null,tile);
      polygon([[a,y,e],[b,y,e],[b,t,e],[a,t,e]],wall,null,tile);
      polygon([[a,y,c],[a,y,e],[a,t,e],[a,t,c]],tint(wall,.9),null,tile);
      polygon([[a,t,c],[b,t,c],[b,t,e],[a,t,e]],roof,null,tile);
    }
    function hip(x,z,w,d,y,h,roof,tile){let a=x-w/2,b=x+w/2,c=z-d/2,e=z+d/2,top=[x,y+h,z];
      for(let edge of [[[a,y,c],[b,y,c]],[[b,y,c],[b,y,e]],[[b,y,e],[a,y,e]],[[a,y,e],[a,y,c]]])polygon([...edge,top],roof,'#ffffff33',tile)}
    function windows(x,z,w,d,h,floors,bright,tile){let layers=Math.min(11,Math.max(1,floors));for(let j=0;j<layers;j++){
      let y=h*(j+.55)/(layers+0.18),half=w/2;
      for(let col of [-.24,.24]){
        let cx=x+col*w,ww=w*.13;
        polygon([[cx-ww,y-.1,z+d/2+.003],[cx+ww,y-.1,z+d/2+.003],[cx+ww,y+.09,z+d/2+.003],[cx-ww,y+.09,z+d/2+.003]],bright,null,tile)
      }
      let zz=z+d*.20;
      polygon([[x+w/2+.004,y-.09,zz-d*.11],[x+w/2+.004,y-.09,zz+d*.11],[x+w/2+.004,y+.09,zz+d*.11],[x+w/2+.004,y+.09,zz-d*.11]],bright,null,tile)
    }}
    function pane(x,z,w,h,y,tile,color='#b7dce0'){
      polygon([[x-w/2,y,z],[x+w/2,y,z],[x+w/2,y+h,z],[x-w/2,y+h,z]],color,'#edf8ef66',tile)
    }
    function rail(x,z,w,y,tile){box(x,z,w,.025,.035,'#e9e8dc','#f5f1dd',y,tile);
      for(let dx of [-w*.4,0,w*.4])box(x+dx,z,.018,.018,.13,'#d7dbd1','#e5e9dc',y-.12,tile)}
    function shrub(x,z,tile){box(x,z,.06,.06,.14,'#745a41','#745a41',0,tile);
      hip(x,z,.24,.24,.12,.23,'#4e9864',tile)}
    function lamp(x,z,tile=-1){box(x,z,.035,.035,.57,'#566e68','#728a7b',-.04,tile);
      box(x,z,.14,.14,.08,'#e1cc91','#fff1af',.52,tile);
      hip(x,z,.18,.18,.6,.11,'#395a53',tile)}
    function bench(x,z,tile){box(x,z,.28,.08,.055,'#a27352','#b98c60',.13,tile);
      box(x,z-.035,.28,.035,.19,'#996f50','#b98c60',.15,tile);
      for(let dx of [-.11,.11])box(x+dx,z,.028,.05,.13,'#576b5a','#6d826b',.02,tile)}
    function fence(x,z,tile){for(let dx of [-.3,-.15,0,.15,.3])box(x+dx,z,.018,.018,.22,'#d9d3b8','#e7e0c7',0,tile);
      box(x,z,.65,.018,.025,'#d9d3b8','#e7e0c7',.14,tile)}
    function build(item,x,z,b,tile){let [wall,trim,roof]=palette[item]||palette.house, floors=Math.max(1,b.floors||1), style=b.style||'和風';
      if(item==='tree'){box(x,z,.11,.11,.5,'#81634b','#83694d',0,tile);
        let top=.52;for(let ring=0;ring<2;ring++){let r=.38-ring*.07,y=top+ring*.2;
          let apex=[x,y+.48,z];for(let k=0;k<8;k++){let a=k*Math.PI/4,b=(k+1)*Math.PI/4;
            polygon([[x+Math.cos(a)*r,y,z+Math.sin(a)*r],[x+Math.cos(b)*r,y,z+Math.sin(b)*r],apex],ring?'#53935e':'#67ae71',null,tile)}}
        for(let dx of [-.28,.26])shrub(x+dx,z+.25,tile);return}
      if(item==='park'){box(x,z,.78,.78,.08,'#75a689','#88c4a1',0,tile);box(x,z,.4,.4,.12,'#d5e5e4','#b5d6d9',.09,tile);
        box(x,z,.28,.28,.025,'#74bfd0','#a7e4e9',.21,tile);box(x,z,.09,.09,.27,'#a4d8e8','#c7f3fa',.22,tile);
        for(let dx of [-.27,.27]){shrub(x+dx,z-.26,tile);bench(x+dx,z+.3,tile)}return}
      let h=item==='tower'?1.55:item==='apartment'?1.05:item==='castle'?1.25:item==='pagoda'?1.12:item==='shrine'?.8:.6;
      h+=Math.min(11,floors-1)*.22;
      let w=item==='tower'?.56:item==='castle'?.7:.68,d=w;
      if(style==='ヨーロッパ風')roof='#738bb4';if(style==='メルヘン')roof='#d980a9';if(style==='中華風')roof='#b24b44';if(style==='アジア風')roof='#a88762';
      polygon([[x-.42,.01,z-.38],[x+.44,.01,z-.38],[x+.49,.01,z+.44],[x-.47,.01,z+.44]],'#537b6699',null,tile,.27);
      box(x,z,.81,.81,.035,style==='ヨーロッパ風'?'#d8c9a8':'#b7bda2','#efe6d1',-.045,tile);
      box(x,z,w,d,h,wall,trim,0,tile);
      if(item==='tower'||item==='apartment'||item==='shop'||item==='convenience'){
        let levels=item==='tower'?Math.max(6,floors*2):item==='apartment'?Math.max(4,floors*2):2;
        windows(x,z,w,d,h,levels,night?'#fce5a2':'#c8e5e7',tile);
        if(item==='tower'){
          for(let j=1;j<levels;j++){let y=h*j/levels;box(x,z,w+.045,d+.045,.027,'#7b9fac','#c9e0e0',y,tile)}
          box(x,z,.22,.22,.28,'#aabfc9','#d5e6ea',h,tile);box(x,z,.025,.025,.3,'#69808b','#e0e7e0',h+.27,tile);
          box(x+.17,z+.14,.14,.12,.12,'#a3b8be','#bfd1cd',h,tile)
        }else if(item==='apartment'){
          for(let j=1;j<=Math.min(levels,9);j++){let y=h*j/(levels+1);box(x,z+d/2+.05,w*.92,.12,.035,'#c9d9db','#e6e5d8',y,tile);rail(x,z+d/2+.105,w*.92,y+.13,tile)}
          box(x-.17,z-.12,.13,.12,.14,'#99aab2','#c8d4d0',h,tile)
        }else{
          pane(x,z+d/2+.007,.45,.3,.13,tile,'#93c4c3');
          box(x,z+d/2+.12,.76,.21,.075,item==='convenience'?'#438977':'#cb866b',item==='convenience'?'#e8f1de':'#f7d9b3',.43,tile);
          if(item==='convenience'){
            for(let dx of [-.25,0,.25])box(x+dx,z+d/2+.124,.08,.215,.018,'#e9f0da','#f6faf0',.5,tile)
          }
          box(x,z-d/2,.45,.11,.16,'#e8c6a2','#f4e7c8',h,tile)
        }
      } else if(item==='castle'){
        for(let dx of [-.3,.3])for(let dz of [-.3,.3]){box(x+dx,z+dz,.19,.19,.38,wall,roof,h-.05,tile);hip(x+dx,z+dz,.23,.23,h+.32,.21,roof,tile)}
        box(x,z+d/2+.012,.22,.025,.44,'#695c6c','#8d7988',.02,tile);
        for(let dx of [-.2,0,.2])box(x+dx,z+d/2,.09,.08,.13,wall,roof,h-.02,tile)
      }else{hip(x,z,w+.09,d+.09,h,.25,roof,tile);
        box(x,z+d/2+.008,.16,.018,.31,'#926b55','#ac8a65',.02,tile);
        for(let dx of [-.22,.22])pane(x+dx,z+d/2+.015,.11,.16,.23,tile,night?'#ffe2a4':'#95b9af');
        if(item==='shrine'){
          box(x,z+d/2+.18,.7,.07,.47,'#bd4545','#c44746',0,tile);box(x,z+d/2+.18,.81,.12,.07,'#b44544','#bb4d4b',.45,tile);
          for(let dx of [-.35,.35])box(x+dx,z+d/2+.2,.11,.11,.3,'#d5b887','#f7dfaa',0,tile)
        }
        if(item==='pagoda')for(let j=0;j<3;j++){box(x,z,.55-j*.1,.55-j*.1,.14,wall,roof,h+j*.16,tile);hip(x,z,.83-j*.13,.83-j*.13,h+j*.16+.14,.14,roof,tile)}
        if(item==='manor'){
          for(let dx of [-.25,.25])box(x+dx,z+d/2+.09,.065,.065,.46,'#eee3c4','#f8efdb',0,tile);
          box(x,z+d/2+.13,.7,.18,.06,'#e5d2a4','#f2e8cd',.45,tile);
          fence(x,z-.37,tile)
        }
        if(item==='house'){
          box(x-.2,z-.12,.1,.1,.28,'#a98270','#d4a982',h,tile);
          shrub(x-.3,z+.3,tile);shrub(x+.3,z+.3,tile);fence(x,z-.41,tile)
        }
      }
    }
    function world(){polys.length=0;currentLayer=0;
      let road=owner?.roadStyle||'土の道';let soil=road==='アスファルト'?'#899b9b':road==='石畳'?'#d0d7cb':road==='レンガ'?'#c9927b':'#b8ca9e';
      polygon([[-1.1,-.12,-1],[4.2,-.12,-1],[4.2,-.12,rows+.3],[-1.1,-.12,rows+.3]],'#98bd83');
      currentLayer=1;polygon([[-.63,-.08,-.62],[3.63,-.08,-.62],[3.63,-.08,rows-.38],[-.63,-.08,rows-.38]],soil);
      currentLayer=2;
      if(road==='アスファルト'){
        for(let z=-.5;z<rows-.4;z++)for(let x=-.5;x<3.6;x+=.36)
          polygon([[x,-.067,z],[x+.18,-.067,z],[x+.18,-.067,z+.018],[x,-.067,z+.018]],'#eeeae0');
        for(let z=0;z<rows;z++)for(let x of [-.5,3.5])
          for(let k=0;k<3;k++)polygon([[x-.06,-.06,z-.2+k*.15],[x+.06,-.06,z-.2+k*.15],[x+.06,-.06,z-.12+k*.15],[x-.06,-.06,z-.12+k*.15]],'#eeeae0')
      } else if(road==='レンガ'||road==='石畳'){
        for(let z=-.5;z<rows;z+=.22)for(let x=-.5;x<3.6;x+=.34)
          polygon([[x,-.067,z],[x+.28,-.067,z],[x+.28,-.067,z+.16],[x,-.067,z+.16]],road==='レンガ'?'#dbab90':'#e1e1d5','#ffffff22')
      }
      currentLayer=3;for(let tile=0;tile<slots;tile++){let x=tile%4,z=Math.floor(tile/4),b=byTile.get(tile),hazard=events.get(tile);
        let color=hazard&&hazard.hazard!=='clear'?'#cfb98b':tile===selectedTile?'#bce58d':(x+z)%2?'#9dc98a':'#a9d095';
        polygon([[x-.44,0,z-.44],[x+.44,0,z-.44],[x+.44,0,z+.44],[x-.44,0,z+.44]],color,'#6f9c76',tile);
        if(owner?.sidewalk){polygon([[x-.47,.008,z+.43],[x+.47,.008,z+.43],[x+.47,.008,z+.48],[x-.47,.008,z+.48]],'#e4ded0')}
        if(b){currentLayer=4;build(b.item,x,z,b,tile);currentLayer=3}
      }
      currentLayer=4;
      for(let z=0;z<rows;z+=2){lamp(-.53,z);lamp(3.53,z);
        if(z<rows-1){shrub(-.83,z+.38,-1);shrub(3.83,z+.38,-1)}}
      for(let x of [-.85,3.85])for(let z of [-.7,rows-.28])shrub(x,z,-1);
      // A small vehicle crosses the boulevard and conveys activity without changing game state.
      currentLayer=5;let carX=(time*.00022%5)-.7;
      box(carX,rows-.45,.22,.13,.11,'#e1a27e','#ffe2a4',-.04,-1);
      box(carX,rows-.45,.09,.095,.095,'#6da5aa','#b7d5d6',.07,-1)
    }
    function paint(){if(!alive)return;time=performance.now();if(time-lastFrame<32){raf=requestAnimationFrame(paint);return}lastFrame=time;if(!width)resize();if(!width)return;
      let sky=ctx.createLinearGradient(0,0,0,height);sky.addColorStop(0,night?'#1b2b4a':'#b4dfe7');sky.addColorStop(.58,night?'#526582':'#e9f7d9');sky.addColorStop(1,night?'#657c7b':'#d3e8d4');ctx.fillStyle=sky;ctx.fillRect(0,0,width,height);
      let sun=ctx.createRadialGradient(width*.83,height*.15,2,width*.83,height*.15,night?31:42);sun.addColorStop(0,night?'#fcf8da':'#fff0b4');sun.addColorStop(.5,night?'#e9eddd':'#ffe7a0');sun.addColorStop(1,night?'#e4f2ef00':'#ffe7a000');ctx.fillStyle=sun;ctx.beginPath();ctx.arc(width*.83,height*.15,night?31:42,0,Math.PI*2);ctx.fill();
      if(night){ctx.fillStyle='#d8e8fa';for(let i=0;i<28;i++){let x=(i*137.37)%width,y=(i*79.19)%(height*.42);ctx.fillRect(x,y,i%4===0?2:1,i%4===0?2:1)}}
      world();polys.sort((a,b)=>a.layer-b.layer||b.far-a.far);
      for(let poly of polys){let points=poly.verts.map(project);ctx.beginPath();ctx.moveTo(...points[0]);for(let i=1;i<points.length;i++)ctx.lineTo(...points[i]);ctx.closePath();ctx.globalAlpha=poly.alpha;ctx.fillStyle=poly.color;ctx.fill();if(poly.stroke){ctx.strokeStyle=poly.stroke;ctx.lineWidth=.65;ctx.stroke()}}
      ctx.globalAlpha=1;
      if(night){ctx.fillStyle='rgba(12,27,50,.41)';ctx.fillRect(0,0,width,height);
        for(let [tile,b] of byTile){let x=tile%4,z=Math.floor(tile/4),h=b.item==='tower'?1.55:b.item==='apartment'?1.05:.65;
          h+=(b.floors-1)*.22;for(let y=.2;y<h-.1;y+=.26){let p=project([x+.06,y,z+.36]);ctx.fillStyle='#ffda91';ctx.shadowColor='#ffdf98';ctx.shadowBlur=9;ctx.fillRect(p[0]-2,p[1]-2,4,4)}ctx.shadowBlur=0}
        for(let z=0;z<rows;z+=2)for(let x of [-.53,3.53]){let p=project([x,.57,z]);let glow=ctx.createRadialGradient(p[0],p[1],1,p[0],p[1],24);glow.addColorStop(0,'#fff5bcbb');glow.addColorStop(1,'#fff5bc00');ctx.fillStyle=glow;ctx.beginPath();ctx.arc(p[0],p[1],24,0,Math.PI*2);ctx.fill()}}
      // Labels and unbuildable ground events stay legible above the scene.
      for(let tile=0;tile<slots;tile++){let x=tile%4,z=Math.floor(tile/4),b=byTile.get(tile),hazard=events.get(tile);let marker=(!b&&hazard&&hazard.hazard!=='clear')?(hazard.hazard==='underground'?'⚠':'🏺'):null;
        if(marker){let p=project([x,.07,z]);ctx.font='20px sans-serif';ctx.textAlign='center';ctx.fillText(marker,p[0],p[1]+6)}
      }
      raf=requestAnimationFrame(paint)
    }
    function pick(px,py){for(let tile=0;tile<slots;tile++){let x=tile%4,z=Math.floor(tile/4),q=[project([x-.47,0,z-.47]),project([x+.47,0,z-.47]),project([x+.47,0,z+.47]),project([x-.47,0,z+.47])];
      let inside=false;for(let i=0,j=3;i<4;j=i++){let a=q[i],b=q[j];if((a[1]>py)!==(b[1]>py)&&px<(b[0]-a[0])*(py-a[1])/(b[1]-a[1])+a[0])inside=!inside}if(inside)return tile}
      let best=-1,near=55;for(let tile=0;tile<slots;tile++){let b=byTile.get(tile),h=b?(b.item==='tower'?1.55:b.item==='apartment'?1.05:.6)+(b.floors-1)*.22:.2;let p=project([tile%4,h*.55,Math.floor(tile/4)]),dist=Math.hypot(px-p[0],py-p[1]);if(dist<near){near=dist;best=tile}}return best}
    function position(e){let r=canvas.getBoundingClientRect();return [e.clientX-r.left,e.clientY-r.top]}
    canvas.addEventListener('pointerdown',e=>{pointer={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY};canvas.setPointerCapture(e.pointerId)});
    canvas.addEventListener('pointermove',e=>{if(!pointer)return;let dx=e.clientX-pointer.x,dy=e.clientY-pointer.y;
      if(Math.abs(e.clientX-pointer.startX)+Math.abs(e.clientY-pointer.startY)>5)pointer.drag=true;
      if(pointer.drag){yaw+=dx*.008;elev=Math.max(.35,Math.min(1.35,elev+dy*.005))}pointer.x=e.clientX;pointer.y=e.clientY});
    canvas.addEventListener('pointerup',e=>{if(pointer&&!pointer.drag&&select){let [x,y]=position(e),tile=pick(x,y);if(tile>=0)select(tile)}pointer=null});
    canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.68,Math.min(1.6,zoom+(e.deltaY>0?-.08:.08)));resize()},{passive:false});
    const observer=new ResizeObserver(resize);observer.observe(stage);resize();paint();
    active={dispose(){alive=false;cancelAnimationFrame(raf);observer.disconnect();stage.classList.remove('is-rendered')},turn(d){yaw+=d*Math.PI/180},tilt(){elev=elev>.8?.59:1.02},reset(){yaw=-37*Math.PI/180;elev=58*Math.PI/180;zoom=1;resize()},toggleNight(){night=!night;return night}};
    return active
  }
  window.City3D={mount,get current(){return active}};
})();
