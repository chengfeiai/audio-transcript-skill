(function(){
  var d=document, $=function(s){return d.querySelector(s);}, $$=function(s){return [].slice.call(d.querySelectorAll(s));};
  var segs=$$('.seg'), q=$('#q'), cnt=$('#cnt'), empty=$('#empty'),
      colL=$('#colL'), colR=$('#colR'),
      pgi=$('#pg').firstElementChild, tip=$('#tip'), toastEl=$('#toast'),
      rbar=$('#rbar'), rax=$('#rax'),
      au=$('#au'), auNote=$('#auNote'), player=$('.player'),
      plBtn=$('#plBtn'), plBar=$('.pl-bar'), plFill=$('#plFill'),
      plCur=$('#plCur'), plDur=$('#plDur'), plSpeed=$('#plSpeed'),
      plMute=$('#plMute'), plVol=$('#plVol'), plFile=$('#plFile'),
      plSpeedWrap=$('#plSpeedWrap'), plRateMenu=$('#plRateMenu');
  var WHOCOLORS=__WHOCOLORS__;
  var WHO='all', TOTAL=__TOTAL__, auOK=false, auerr=false;
  var ICON_PLAY='<svg viewBox="0 0 24 24"><path d="M8 5.6c0-.9 1-1.4 1.7-.9l9.1 6c.7.5.7 1.6 0 2.1l-9.1 6c-.7.5-1.7 0-1.7-.9V5.6z"/></svg>';
var ICON_VOL='<svg viewBox="0 0 24 24"><path d="M4 9h3l4-3.5c.6-.5 1.5-.1 1.5.7v11.6c0 .8-.9 1.2-1.5.7L7 15H4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zm11.5-1.6a4.5 4.5 0 0 1 0 9.2v-1.8a2.7 2.7 0 0 0 0-5.6V7.4zm0-3.4a7.9 7.9 0 0 1 0 16v-1.8a6.1 6.1 0 0 0 0-12.4V4z"/></svg>';
  var ICON_MUTE='<svg viewBox="0 0 24 24"><path d="M4 9h3l4-3.5c.6-.5 1.5-.1 1.5.7v11.6c0 .8-.9 1.2-1.5.7L7 15H4a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1zm13.4.1 1.3 1.3-2.1 2.1 2.1 2.1-1.3 1.3-2.1-2.1-2.1 2.1-1.3-1.3 2.1-2.1-2.1-2.1 1.3-1.3 2.1 2.1 2.1-2.1z"/></svg>';
  var ICON_PAUSE='<svg viewBox="0 0 24 24"><rect x="7" y="5" width="3.6" height="14" rx="1.2"/><rect x="13.4" y="5" width="3.6" height="14" rx="1.2"/></svg>';

  segs.forEach(function(s){ s.__raw=s.querySelector('.seg-x').textContent; });

  function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
  function sec2s(t){var p=t.split(':');return (+p[0])*60+(+p[1]);}
  function mmss(n){ if(!isFinite(n)||n<0) return '--:--';
    n=Math.round(n); var m=Math.floor(n/60), s=n%60;
    return (m<10?'0':'')+m+':'+(s<10?'0':'')+s; }

  var tid;
  function toast(msg){ toastEl.textContent=msg; toastEl.classList.add('on');
    clearTimeout(tid); tid=setTimeout(function(){toastEl.classList.remove('on');},2800); }

  /* ---------- 音频：如实反映状态 ---------- */
  function setNote(t,cls){ if(!auNote) return; auNote.textContent=t;
    auNote.className='pl-note'+(cls?(' '+cls):''); }
  function die(msg){ auOK=false; auerr=true; player.classList.add('dead');
    setNote(msg,'warn'); }
  function ready(){
    auOK=true; if(typeof buildAxis==='function') buildAxis(au.duration); if(typeof loadPos==='function') loadPos(); player.classList.remove('dead');
    plDur.textContent=mmss(au.duration);
    setNote('已载入 · '+mmss(au.duration)+' · 点任一时间戳可跳到该处','ok');
  }
  if(au){
    au.addEventListener('loadedmetadata',ready);
    au.addEventListener('error',function(){
      die('音频不可用：文件需与本页同目录，或浏览器限制本地读取；文字定位仍可用');
    });
    setTimeout(function(){
      if(auOK||auerr) return;
      if(au.error||au.networkState===3){ die('音频不可用：文件未找到或无法解码'); return; }
      if(au.readyState>=2){ ready(); return; }
      setNote('音频尚未就绪（文件较大/磁盘较慢），此时点时间戳只做文字定位','warn');
    },9000);
    var _last=-1;
    function syncNow(){
      if(!au.duration) return;
      var ct=au.currentTime, idx=-1;
      for(var i=0;i<segs.length;i++){ if(sec2s(segs[i].dataset.t)<=ct) idx=i; else break; }
      if(idx===_last) return;
      _last=idx;
      segs.forEach(function(s,i){ s.classList.toggle('now', i===idx); });
    }
    au.addEventListener('timeupdate',function(){
      if(!au.duration) return;
      plFill.style.width=(au.currentTime/au.duration*100)+'%';
      plCur.textContent=mmss(au.currentTime);
      syncNow();
    });
    au.addEventListener('play',function(){ plBtn.innerHTML=ICON_PAUSE; });
    au.addEventListener('pause',function(){ plBtn.innerHTML=ICON_PLAY; });
    au.addEventListener('ended',function(){ plBtn.innerHTML=ICON_PLAY; });
  }

  /* ---------- 搜索 / 筛选 ---------- */
  function mark(raw,kw){
    if(!kw) return esc(raw);
    var low=raw.toLowerCase(), k=kw.toLowerCase(), out='', i=0, p;
    while((p=low.indexOf(k,i))>-1){
      out+=esc(raw.slice(i,p))+'<mark>'+esc(raw.slice(p,p+k.length))+'</mark>';
      i=p+k.length;
    }
    return out+esc(raw.slice(i));
  }
  function apply(){
    var kw=(q.value||'').trim(), n=0;
    segs.forEach(function(s){
      var show=(WHO==='all'||s.dataset.who===WHO) && (!kw||s.__raw.toLowerCase().indexOf(kw.toLowerCase())>-1);
      s.classList.toggle('hide',!show);
      var x=s.querySelector('.seg-x');
      x.innerHTML = kw? mark(s.__raw,kw) : esc(s.__raw);
      if(show) n++;
    });
    cnt.textContent=n+' / '+segs.length+' 段';
    var ct=d.getElementById('cntTop');
    if(ct) ct.textContent=(n===segs.length)? (segs.length+' 段') : (n+' / '+segs.length+' 段');
    if(n===0){
      empty.querySelector('.empty-kw').textContent = kw ? ('「'+kw+'」') : ('「'+WHO+'」');
      empty.querySelector('.empty-sub').textContent = kw
        ? ('全文 '+segs.length+' 段中没有包含该词的内容。')
        : ('该说话人在全文 '+segs.length+' 段中没有可用段落。');
      empty.hidden=false;
    } else { empty.hidden=true; }
  }
  function syncFbtn(){ $$('.fbtn').forEach(function(b){ b.classList.toggle('on', b.dataset.who===WHO); }); }

  /* ---------- 跳转：严格匹配，不虚假跳转 ---------- */
  function jump(t){
    var target=null;
    segs.forEach(function(s){ if(s.dataset.t===t) target=s; });
    if(!target){ toast('时间点 '+t+' 在全文里没有对应段落，不可定位。'); return; }
    if(target.classList.contains('hide')){ WHO='all'; q.value=''; syncFbtn(); apply(); }
    target.classList.add('flash');
    target.scrollIntoView({behavior:'smooth',block:'center'});
    setTimeout(function(){ target.classList.remove('flash'); },2400);
    if(auOK){
      try{
        au.currentTime=sec2s(t);
        var pr=au.play();
        if(pr&&pr.catch) pr.catch(function(){
          toast('已定位到 '+t+'，浏览器阻止自动播放，请手动点播放。');
        });
      }catch(e){ toast('已定位到 '+t+'（音频跳转失败）'); }
    }
  }
  d.addEventListener('click',function(e){
    var c=e.target.closest('.cite'); if(!c) return;
    e.preventDefault(); jump(c.dataset.t);
  });
  segs.forEach(function(s){
    s.querySelector('.seg-t').addEventListener('click',function(){ jump(s.dataset.t); });
  });

  /* ---------- 节奏条 ---------- */
  if(rbar){
    segs.forEach(function(s){
      var b=d.createElement('span');
      b.style.flexGrow=String(Math.max(2,parseFloat(s.dataset.d)||5));
      b.style.flexBasis='0';
      b.style.background=WHOCOLORS[s.dataset.who]||'#9AA3B2';
      b.addEventListener('mouseenter',function(){
        tip.innerHTML='<b>'+s.dataset.t+'</b>　'+s.dataset.who+'<br>'+
          esc(s.__raw.slice(0,32))+(s.__raw.length>32?'…':'');
        tip.classList.add('on');
      });
      b.addEventListener('mousemove',function(e){
        tip.style.left=Math.min(e.clientX+14, window.innerWidth-300)+'px';
        tip.style.top=Math.min(e.clientY+18, window.innerHeight-70)+'px';
      });
      b.addEventListener('mouseleave',function(){ tip.classList.remove('on'); });
      b.addEventListener('click',function(){ jump(s.dataset.t); });
      rbar.appendChild(b);
    });
    buildAxis(TOTAL);   // 刻度按总时长动态生成，长音频不再只有前 15 分钟
  }

  /* ---------- 播放控件 ---------- */
  if(plBtn) plBtn.innerHTML=ICON_PLAY;
  if(plBtn) plBtn.addEventListener('click',function(){
    if(!auOK) return;
    if(au.paused){ var p=au.play(); if(p&&p.catch) p.catch(function(){ toast('浏览器阻止播放，请再点一次。'); }); }
    else au.pause();
  });
  if(plBar) plBar.addEventListener('click',function(e){
    if(!auOK||!au.duration) return;
    var r=plBar.getBoundingClientRect();
    au.currentTime=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width))*au.duration;
  });
  $$('.pl-skip').forEach(function(b){
    b.addEventListener('click',function(){
      if(!auOK) return;
      au.currentTime=Math.max(0,Math.min(au.duration||TOTAL, au.currentTime+(+b.dataset.d)));
    });
  });
  /* ---------- 播放速度：点开菜单选择，选中后生效（v1.4.1） ---------- */
  if(plSpeed && plRateMenu){
    var rates=[0.5,0.75,1,1.25,1.5,2], curRate=1, speedPersist=false;
    var SPEEDKEY='zcdg.rate.v1';

    function fmtRate(r){ return (r%1? r.toFixed(2).replace(/0$/,'') : r.toFixed(1))+'x'; }

    function paintMenu(){
      plRateMenu.innerHTML='';
      rates.forEach(function(r){
        var b=d.createElement('button');
        b.type='button'; b.setAttribute('role','option');
        b.setAttribute('aria-selected', r===curRate ? 'true' : 'false');
        b.textContent=fmtRate(r);
        b.addEventListener('click', function(e){ e.stopPropagation(); applyRate(r); closeMenu(); });
        plRateMenu.appendChild(b);
      });
    }
    function applyRate(r, quiet){
      curRate=r;
      plSpeed.textContent=fmtRate(r);
      if(auOK||au){ try{ au.playbackRate=r; au.defaultPlaybackRate=r; }catch(_){} }
      if(!quiet){ speedPersist=true; try{ localStorage.setItem(SPEEDKEY, String(r)); }catch(_){} }
      paintMenu();
    }
    function openMenu(){
      paintMenu();
      // #pR 带 backdrop-filter，会为 position:fixed 造包含块 ——
      // 挂到 body 才能让 fixed 相对视口定位，否则菜单会被算到面板坐标系里（跑到屏幕外）。
      if(plRateMenu.parentElement!==document.body) document.body.appendChild(plRateMenu);
      plRateMenu.hidden=false;
      plSpeed.setAttribute('aria-expanded','true');
      placeMenu();
      document.addEventListener('click', outside, true);
      document.addEventListener('keydown', escKey);
      window.addEventListener('resize', closeMenu);
      (colR||window).addEventListener('scroll', closeMenu, {passive:true});
    }
    // 菜单用 fixed 定位：按按钮实时坐标算出位置，向上弹出并做视口夹取，
    // 这样既不被 .player 的 overflow:hidden 裁掉，也不会被右栏正文盖住。
    function placeMenu(){
      var rb=plSpeed.getBoundingClientRect();
      var mw=plRateMenu.offsetWidth, mh=plRateMenu.offsetHeight;
      var left=rb.left+rb.width/2-mw/2;
      left=Math.max(8, Math.min(left, window.innerWidth-mw-8));
      // 尽量抬到整张播放卡之上，避免压住卡内的说明行；空间不够再退回贴着按钮
      var cardTop=player?player.getBoundingClientRect().top:rb.top;
      var top=cardTop-mh-8;
      if(top<8) top=rb.top-mh-8;
      if(top<8) top=rb.bottom+8;          // 上方真不够就翻到下方
      plRateMenu.style.left=left+'px';
      plRateMenu.style.top=top+'px';
    }
    function closeMenu(){
      if(plRateMenu.hidden) return;
      plRateMenu.hidden=true;
      plSpeed.setAttribute('aria-expanded','false');
      document.removeEventListener('click', outside, true);
      document.removeEventListener('keydown', escKey);
      window.removeEventListener('resize', closeMenu);
      if(colR) colR.removeEventListener('scroll', closeMenu);
    }
    function outside(e){
      if(plSpeedWrap.contains(e.target)) return;
      if(plRateMenu.contains(e.target)) return;   // 菜单在 body 下，点选项不算外部
      closeMenu();
    }
    function escKey(e){ if(e.key==='Escape'){ e.preventDefault(); closeMenu(); plSpeed.focus(); } }

    plSpeed.addEventListener('click', function(e){
      e.stopPropagation();
      if(plRateMenu.hidden) openMenu(); else closeMenu();
    });
    // 恢复上次选择（可选：只在播放器成功载入后沿用）
    try{ var sv=parseFloat(localStorage.getItem(SPEEDKEY)); if(sv>0){ curRate=sv; } }catch(_){}
    applyRate(curRate, true);
    // 换音频 / 重设 currentTime 后 playbackRate 可能被重置，加一道保险
    au && au.addEventListener('loadedmetadata', function(){ try{ au.playbackRate=curRate; au.defaultPlaybackRate=curRate; }catch(_){} });
  }

  /* ---------- 音量 / 静音 / 选本地音频 / 位置记忆（v1.2.2） ---------- */
  var VOLKEY='zcdg.vol.v2', POSKEY='zcdg.playpos.'+location.pathname, posRestored=false, lastWall=0;

  function buildAxis(dur){
    if(!rax) return;
    rax.innerHTML='';
    var total=(dur&&isFinite(dur)&&dur>0)?dur:TOTAL;
    if(!(total>0)) total=60;
    // 按总长选刻度间隔，短音频用秒级、长音频用分钟级，避免只剩一个「0′」
    var step = total>1800?300 : total>600?120 : total>240?60 : total>90?30 : 15;
    for(var m=0;m*step<=total;m++){
      var sp=d.createElement('span');
      sp.style.left=(m*step/total*100)+'%';
      sp.textContent = (step<60) ? (m*step)+'\u2033' : ((m*step/60)|0)+'\u2032';
      rax.appendChild(sp);
    }
  }

  function loadPos(){
    if(posRestored||!auOK) return; posRestored=true;
    var v=null; try{ v=localStorage.getItem(POSKEY); }catch(e){}
    var t=parseFloat(v||'0');
    if(t>5 && au.duration && t<au.duration-10){
      au.currentTime=t;
      setNote('已加载 · 从上次的 '+mmss(t)+' 续播','ok');
    }
  }
  function savePos(){
    if(!auOK) return;
    try{ localStorage.setItem(POSKEY, String(Math.floor(au.currentTime))); }catch(e){}
  }

  if(plVol){
    var v0=null; try{ v0=localStorage.getItem(VOLKEY); }catch(e){}
    if(v0!==null){ au.volume=Math.max(0,Math.min(1,parseFloat(v0))); plVol.value=au.volume; }
    plVol.addEventListener('input',function(){
      au.volume=parseFloat(plVol.value); au.muted=au.volume===0;
      try{ localStorage.setItem(VOLKEY, plVol.value); }catch(e){}
      updateMuteIcon();
    });
  }
  function updateMuteIcon(){
    if(!plMute) return;
    plMute.innerHTML=(au.muted||au.volume===0)?ICON_MUTE:ICON_VOL;
  }
  if(plMute){
    plMute.innerHTML=ICON_VOL;
    plMute.addEventListener('click',function(){
      au.muted=!au.muted;
      if(!au.muted && au.volume===0){ au.volume=0.8; if(plVol) plVol.value='0.8'; }
      updateMuteIcon();
    });
  }
  if(plFile){
    plFile.addEventListener('change',function(){
      var f=plFile.files&&plFile.files[0]; if(!f) return;
      au.src=URL.createObjectURL(f); au.load(); posRestored=false;
      setNote('已载入本地文件 · '+f.name,'ok');
    });
  }
  if(auOK || au){
    au.addEventListener('timeupdate',function(){
      var now=Date.now();
      if(now-lastWall>4000){ lastWall=now; savePos(); }
    });
    au.addEventListener('volumechange',updateMuteIcon);
    au.addEventListener('pause',savePos);
    au.addEventListener('ended',function(){ try{ localStorage.removeItem(POSKEY); }catch(e){} });
    window.addEventListener('beforeunload',savePos);
  }

  /* ---------- 滚动：进度、目录高亮 ----------
     桌面并排版式统一「双面板内滚」（见 page.css 的独立滚动层）：
       #colL 与 #colR 各滚各的，body 锁死不滚。
     窄屏单列（≤920px）仍是整页滚动，这里自动识别并切到 window 分支。 */
  var secs=$$('.sec'), links=$$('.subnav a');
  var pageScroll=false;
  function detectScrollMode(){
    var cs=getComputedStyle(colL);
    var colScrolls=(cs.overflowY==='auto'||cs.overflowY==='scroll');
    /* 只看「#colL 是不是滚动容器」。内容不足一屏时也不能误判成整页滚动：
       body 已锁死，误判会让目录跳转去滚一个滚不动的 window。 */
    pageScroll=!colScrolls;
  }
  detectScrollMode();
  onScroll();
  function onScroll(){
    var y, max;
    if(pageScroll){
      y=window.pageYOffset||d.documentElement.scrollTop||0;
      max=Math.max(0,(d.documentElement.scrollHeight||0)-window.innerHeight);
    }else{
      y=colL.scrollTop; max=colL.scrollHeight-colL.clientHeight;
    }
    pgi.style.width=(max>0?Math.min(100,y/max*100):0)+'%';
    var cur=null, probe=(pageScroll?Math.round(window.innerHeight*0.34):170);
    secs.forEach(function(s){ if(s.getBoundingClientRect().top<=probe) cur=s.id; });
    if(!cur && secs.length) cur=secs[0].id;   // 顶部未越过探测线时，仍高亮第一章
    links.forEach(function(a){ a.classList.toggle('on', !!cur && a.getAttribute('href')==='#'+cur); });
  }
  colL.addEventListener('scroll',onScroll,{passive:true});
  window.addEventListener('scroll',onScroll,{passive:true});
  window.addEventListener('resize',function(){ detectScrollMode(); onScroll(); });
  links.forEach(function(a){
    a.addEventListener('click',function(e){
      var id=a.getAttribute('href'), t=d.querySelector(id);
      if(!t) return;
      e.preventDefault();
      if(pageScroll){
        var top=t.getBoundingClientRect().top+(window.pageYOffset||0)-16;
        window.scrollTo({top:Math.max(0,top),behavior:'smooth'});
      }else{
        colL.scrollTo({top:t.offsetTop-8,behavior:'smooth'});
      }
    });
  });

  /* ---------- 顶部按钮 / 标签页 ---------- */
  var btnTop=$('#btnTop');
  if(btnTop) btnTop.addEventListener('click',function(){
    if(pageScroll){ window.scrollTo({top:0,behavior:'smooth'}); }
    else{ colL.scrollTo({top:0,behavior:'smooth'}); }
  });
  var btnPrint=$('#btnPrint');
  if(btnPrint) btnPrint.addEventListener('click',function(){ window.print(); });
  var tabL=$('#tabL'), tabR=$('#tabR');
  function setTab(which){
    tabL.classList.toggle('on',which==='L');
    tabR.classList.toggle('on',which==='R');
    if(window.matchMedia('(max-width:920px)').matches){
      (which==='L'?colL:colR).scrollIntoView({behavior:'smooth',block:'start'});
    }
  }
  if(tabL) tabL.addEventListener('click',function(){ setTab('L'); });
  if(tabR) tabR.addEventListener('click',function(){ setTab('R'); });

  /* ---------- 入场 + 票数条 ---------- */
  var bars=$$('.track i');
  function fill(){ bars.forEach(function(b){ b.style.width=b.dataset.w+'%'; }); }
  if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches && 'IntersectionObserver' in window){
    d.documentElement.classList.add('js');
    var rev=$$('.card,.step,.checks li,.duel,.verdict,.rhythm,.brief');
    rev.forEach(function(el,i){ el.classList.add('reveal'); el.style.transitionDelay=((i%4)*40)+'ms'; });
    var io=new IntersectionObserver(function(es){
      es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('in'); io.unobserve(e.target); } });
    },{threshold:.08,rootMargin:'0px 0px -24px 0px'});
    rev.forEach(function(el){ io.observe(el); });
    var io2=new IntersectionObserver(function(es){
      es.forEach(function(e){ if(e.isIntersecting){ e.target.style.width=e.target.dataset.w+'%'; io2.unobserve(e.target); } });
    },{threshold:.3});
    bars.forEach(function(b){ io2.observe(b); });
  } else { fill(); }

  /* ---------- 快捷键 ---------- */
  d.addEventListener('keydown',function(e){
    if(e.key==='/' && d.activeElement!==q){ e.preventDefault(); q.focus(); q.select(); }
    if(e.key==='Escape' && d.activeElement===q){ q.value=''; q.blur(); apply(); }
    if(e.key===' ' && d.activeElement===d.body && auOK){ e.preventDefault(); plBtn.click(); }
  });

  $$('.fbtn').forEach(function(b){
    b.addEventListener('click',function(){ WHO=b.dataset.who; syncFbtn(); apply(); });
  });
  q.addEventListener('input',apply);
  q.addEventListener('search',apply);
  var clr=$('#clr');
  if(clr) clr.addEventListener('click',function(){ q.value=''; WHO='all'; syncFbtn(); apply(); q.focus(); });
  window.addEventListener('beforeprint',fill);
  /* ---------- 分栏拖拽（仅并排版式） ---------- */
  var appEl=$('.app'), splitter=$('#splitter');
  var SPLITKEY='zcdg.split.'+(location.pathname||'page');
  var dragging=false;
  function splitTotal(){
    var l=pL.getBoundingClientRect(), r=pR.getBoundingClientRect();
    return {left:l.left, w:(r.right-l.left)};
  }
  function placeSplitter(){
    if(!splitter||!appEl) return;
    var a=appEl.getBoundingClientRect(), l=pL.getBoundingClientRect(), r=pR.getBoundingClientRect();
    splitter.style.left=((l.right+r.left)/2-a.left)+'px';
  }
  function setSplit(pct){
    pct=Math.max(26,Math.min(78,pct));
    appEl.style.setProperty('--split-w',pct.toFixed(3)+'%');
    placeSplitter();
  }
  function splitNow(){
    var v=parseFloat(appEl.style.getPropertyValue('--split-w'));
    return isNaN(v)?56.7:v;
  }
  function saveSplit(){
    try{ localStorage.setItem(SPLITKEY, appEl.style.getPropertyValue('--split-w')); }catch(e){}
  }
  function initSplit(){
    if(!appEl||!splitter) return;
    if(!window.matchMedia('(min-width:921px)').matches){
      appEl.classList.remove('app-split'); return;
    }
    // 先按皮肤自身的默认比例量一次，避免切换成变量后跳变
    var t=splitTotal(), natural=(t.w>0 ? pL.getBoundingClientRect().width/t.w*100 : 56.7);
    var saved=null;
    try{ saved=localStorage.getItem(SPLITKEY); }catch(e){}
    appEl.classList.add('app-split');
    appEl.style.setProperty('--split-w', saved || (natural.toFixed(3)+'%'));
    placeSplitter();
  }
  if(appEl && splitter){
    initSplit();
    if(window.matchMedia('(min-width:921px)').matches){ onScroll(); }

    // 按下后先按兵不动；移动超过 3px 才算真正开始拖，避免「点一下自己就动」
    var startX=0, moved=false;
    splitter.addEventListener('pointerdown',function(e){
      startX=e.clientX; moved=false;
      if(splitter.setPointerCapture){ try{ splitter.setPointerCapture(e.pointerId); }catch(err){} }
      e.preventDefault();
    });
    splitter.addEventListener('pointermove',function(e){
      if(!startX) return;
      if(!moved){
        if(Math.abs(e.clientX-startX)<3) return;
        moved=true; dragging=true; splitter.classList.add('dragging');
      }
      if(!dragging) return;
      var t=splitTotal();
      if(t.w>0) setSplit((e.clientX-t.left)/t.w*100);
    });
    function endDrag(){
      startX=0;
      if(!dragging) return;
      dragging=false; moved=false; splitter.classList.remove('dragging');
      saveSplit(); onScroll();
    }
    splitter.addEventListener('pointerup',endDrag);
    splitter.addEventListener('pointercancel',endDrag);
    splitter.addEventListener('keydown',function(e){
      var cur=splitNow();
      if(e.key==='ArrowLeft'){ setSplit(cur-2); }
      else if(e.key==='ArrowRight'){ setSplit(cur+2); }
      else return;
      e.preventDefault(); saveSplit(); onScroll();
    });
    splitter.addEventListener('dblclick',function(e){
      e.preventDefault();
      try{ localStorage.removeItem(SPLITKEY); }catch(e){}
      appEl.style.removeProperty('--split-w');
      appEl.classList.remove('app-split');
      requestAnimationFrame(function(){ initSplit(); onScroll(); });
    });
    window.addEventListener('resize',function(){
      if(!window.matchMedia('(min-width:921px)').matches){ appEl.classList.remove('app-split'); return; }
      if(!appEl.classList.contains('app-split')){ initSplit(); } else { placeSplitter(); onScroll(); }
    });
    // 字体/图片加载完再摆一次，避免初始位置偏
    window.addEventListener('load',function(){ placeSplitter(); onScroll(); });
  }

  apply(); onScroll();
})();