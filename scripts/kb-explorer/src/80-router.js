/* ============ 80 · router & boot：路由过渡 / 全局事件 / 主题 ============ */
var _vtBusy=false;
function navTo(fn){
  if(document.startViewTransition&&!reducedMotion()&&!window.matchMedia("(prefers-reduced-motion: reduce)").matches){
    try{
      if(_vtBusy){fn();return;}
      _vtBusy=true;
      var vt=document.startViewTransition(function(){fn();
        return new Promise(function(res){setTimeout(res,30);});});
      vt.finished.then(function(){_vtBusy=false;},function(){_vtBusy=false;});
      return;
    }catch(e){fn();return;}
  }
  fn();
}

function route(){
  var gs=document.getElementById("gsearch");
  var h=location.hash||"#/";
  var isHome=(h==="#"||h==="#/");
  if(gs)gs.classList.toggle("hide",isHome);
  if(h.indexOf("#/e/")===0){var p=h.slice(4).split("/").filter(Boolean);
    return viewEntry(decodeURIComponent(p[0]||""),decodeURIComponent(p[1]||""));}
  if(h.indexOf("#/browse/")===0){var q=h.slice(9).split("/").filter(Boolean);
    return viewBrowse(paneOfType(decodeURIComponent(q[0])),q[1]?decodeURIComponent(q[1]):null);}
  if(h.indexOf("#/q/")===0){return viewBrowse(paneOfQuery(decodeURIComponent(h.slice(4))),null);}
  if(h.indexOf("#/d/")===0){return viewBrowse(paneOfType(decodeURIComponent(h.slice(4))),null);}
  if(h==="#/triage"){return viewTriage();}
  viewHome();
}
function go(){navTo(route);}

/* ---------- 全局事件 ---------- */
function handleCopy(btn){
  var val=btn.getAttribute("data-copy");
  if(!val)return;
  var labelEl=btn.querySelector("span");
  if(btn._ct)clearTimeout(btn._ct);
  copyText(val,function(){
    btn.classList.add("copied");
    if(labelEl)labelEl.textContent="已复制";
    btn.title="已复制";
    toastCopy(val.replace(/\s+/g," ").slice(0,44));
    btn._ct=setTimeout(function(){
      btn.classList.remove("copied");
      if(labelEl)labelEl.textContent="复制";
      btn.title="复制命令";
    },1400);
  });
}

function wire(){
  document.addEventListener("click",function(ev){
    var b=ev.target.closest("[data-copy]");
    if(b){handleCopy(b);return;}
    var smp=ev.target.closest("[data-sample]");
    if(smp){location.hash="#/q/"+encodeURIComponent(smp.getAttribute("data-sample"));return;}
    var rm=ev.target.closest("[data-recent-rm]");
    if(rm){ev.preventDefault();recentRemove(rm.getAttribute("data-recent-rm"));if((location.hash||"#/")==="#/")go();return;}
    var bg=ev.target.closest(".browse .b-item");
    if(bg){return;} /* 已在视图内绑定，这里避免重复 */
  });

  document.addEventListener("keydown",function(ev){
    var tag=(document.activeElement&&document.activeElement.tagName)||"";
    var inInput=/^(INPUT|TEXTAREA|SELECT)$/.test(tag);
    if((ev.metaKey||ev.ctrlKey)&&ev.key.toLowerCase()==="k"){ev.preventDefault();palOpen();return;}
    if(ev.key==="/"&&!inInput){ev.preventDefault();focusSearch();return;}
    if(ev.key==="Escape"&&palOpen&&window.__paletteToggler.isOpen()){ev.preventDefault();palClose();return;}
    if(inInput)return;
    /* 双栏内键盘导航 */
    if($view.querySelector(".browse")){
      if(ev.key==="ArrowDown"||ev.key==="ArrowUp"){
        var ctl=browseCtl;if(!ctl||!ctl.list||!ctl.list.length)return;
        ev.preventDefault();
        var dir=ev.key==="ArrowDown"?1:-1;
        var ni=Math.min(Math.max(ctl.sel+dir,0),ctl.list.length-1);
        if(ni!==ctl.sel){selectBrowse(ctl,ni,true);}
      }else if(ev.key==="Enter"){
        var c2=browseCtl;if(c2&&c2.list&&c2.sel>=0){
          ev.preventDefault();
          var curE=c2.list[c2.sel].e;
          location.hash=entryUrl(curE);
        }
      }
    }
  });

  window.addEventListener("hashchange",go);
  /* ⌘K 命令面板 */
  wirePalette();
  /* 顶栏常驻搜索（全局唤起）；首页由 hero 大搜索接管，这里隐藏 */
  var gs=document.getElementById("gsearch");
  if(gs){mountSearch(gs,{big:false});
    if((location.hash||"#/")==="#/")gs.classList.add("hide");}
  /* 主题 */
  applyTheme(appliedTheme(),false);
  var tt=document.getElementById("themeToggle");
  if(tt)tt.addEventListener("click",cycleTheme);
  if(!lsGet(LS.theme,null)){
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change",function(m){
      applyTheme(m.matches?"dark":"light",false);});
  }
}

/* 首次渲染 */
window.addEventListener("DOMContentLoaded",function(){
  document.getElementById("view").classList.add("vt");
  wire();
  route();
});
