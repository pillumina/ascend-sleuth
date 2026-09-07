/* ============ 30 · store：主题 / 最近浏览（localStorage） ============ */
var LS={theme:"kbexp:theme",recent:"kbexp:recent"};
function lsGet(k,d){try{var v=localStorage.getItem(k);return v==null?d:JSON.parse(v);}catch(e){return d;}}
function lsSet(k,v){try{localStorage.setItem(k,JSON.stringify(v));}catch(e){}}

/* ---------- 主题 ---------- */
function appliedTheme(){
  var st=lsGet(LS.theme,null);
  if(st==="light"||st==="dark")return st;
  return window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";
}
function applyTheme(t,persist){
  document.documentElement.setAttribute("data-theme",t);
  if(persist)lsSet(LS.theme,t);
  var ic=document.getElementById("themeIcon");
  if(ic){ic.textContent=t==="dark"?"☀":"☾";ic.setAttribute("aria-label",t==="dark"?"切换到亮色":"切换到暗色");}
}
function cycleTheme(){
  applyTheme(appliedTheme()==="dark"?"light":"dark",true);
}

/* ---------- 最近浏览 ---------- */
function recentList(){return lsGet(LS.recent,[]);}
function recentPush(e){
  var r=recentList().filter(function(x){return x.id!==e.id;});
  r.unshift({id:e.id,type:e.type,title:e.title,ts:Date.now()});
  lsSet(LS.recent,r.slice(0,8));
}
function recentRemove(id){lsSet(LS.recent,recentList().filter(function(x){return x.id!==id;}));}

/* ---------- 流程步骤进度（学习模式） ---------- */
var LS_FLOW="kbexp:flow";
function flowGet(id){return lsGet(LS_FLOW,{})[id]||{};}
function flowSet(id,step,on){var s=lsGet(LS_FLOW,{});(s[id]=s[id]||{})[step]=on;lsSet(LS_FLOW,s);}
function flowReset(id){var s=lsGet(LS_FLOW,{});delete s[id];lsSet(LS_FLOW,s);}
function flowDoneCount(id,total){var st=flowGet(id);var n=0;for(var i=0;i<total;i++)if(st[i])n++;return n;}
