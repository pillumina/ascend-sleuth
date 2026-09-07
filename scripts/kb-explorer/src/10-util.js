/* ============ 10 · util：转义 / 富文本 / 复制 / toast / 通用 ============ */
"use strict";

function esc(s){return String(s==null?"":s).replace(/[&<>"']/g,function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];});}

/* 反引号 -> 行内 code；换行 -> br */
function rich(s){return esc(s).replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\n/g,"<br>");}

/* 高亮（search 用） */
function hilite(s,q){
  var t=esc(s);q=(q||"").trim();if(!q)return t;
  try{return t.replace(new RegExp("("+q.split(/\s+/).map(function(w){
    return w.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");}).join("|")+")","gi"),"<mark>$1</mark>");}
  catch(e){return t;}
}

function trunc(s,n){s=String(s==null?"":s);return s.length>n?s.slice(0,n-1)+"…":s;}

function debounce(fn,ms){var t=null;return function(){var a=arguments,c=this;
  clearTimeout(t);t=setTimeout(function(){fn.apply(c,a);},ms);};}

var _reducedMotion=null;
function reducedMotion(){if(_reducedMotion==null)_reducedMotion=window.matchMedia("(prefers-reduced-motion: reduce)").matches;return _reducedMotion;}

/* ---------- 复制 ---------- */
function copyText(txt,cb){
  function ok(){if(cb)cb();}
  if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(txt).then(ok,function(){fb();});}
  else fb();
  function fb(){var ta=document.createElement("textarea");ta.value=txt;
    ta.style.cssText="position:fixed;top:-999px;opacity:0";document.body.appendChild(ta);
    ta.select();try{document.execCommand("copy");ok();}catch(e){}document.body.removeChild(ta);}
}

/* ---------- toast ---------- */
var _toastsEl=null;
function toast(msg,ms){
  if(!_toastsEl)_toastsEl=document.getElementById("toasts");
  if(!_toastsEl)return;
  var d=document.createElement("div");d.className="toast";d.innerHTML=msg;
  _toastsEl.appendChild(d);
  while(_toastsEl.children.length>3)_toastsEl.firstChild.remove();
  setTimeout(function(){d.classList.add("out");setTimeout(function(){d.remove();},240);},ms||2000);
}
function toastCopy(label){toast('已复制 <code>'+esc(label)+'</code>');}

/* 局部 reveal（scroll 一次触发，尊重 reduced-motion） */
function revealScope(root){
  if(reducedMotion()){root.querySelectorAll(".rv").forEach(function(el){el.classList.add("in");});return;}
  var els=root.querySelectorAll(".rv");
  var io=new IntersectionObserver(function(entries){
    entries.forEach(function(en){if(en.isIntersecting){
      var el=en.target;var delay=parseFloat(el.getAttribute("data-rv-delay")||"0");
      if(delay)el.style.transitionDelay=delay+"ms";
      el.classList.add("in");io.unobserve(el);}});
  },{threshold:.12,rootMargin:"0px 0px -8% 0px"});
  els.forEach(function(el,i){if(!el.getAttribute("data-rv-delay")&&i<10)el.setAttribute("data-rv-delay",(i%5)*40);io.observe(el);});
}
