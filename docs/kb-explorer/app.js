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

/* ============ 20 · data：KB 索引 / 类型元信息 / 检索 ============ */
var TYPES=KB.types, ENTRIES=KB.entries, TRIAGE=(KB.triage&&KB.triage.branches)||[];
var byId={}, byType={};
ENTRIES.forEach(function(e){byId[e.id]=e;(byType[e.type]=byType[e.type]||[]).push(e);});
var TYPE_META={};TYPES.forEach(function(t){TYPE_META[t.type]=t;});

var CAT_LABEL={"interrupt":"中断 / 异常","precision":"精度","performance":"性能"};
var KIND_LABEL={flow:"流程",table:"表格",fact:"词条"};
var KIND_COLOR={flow:"accent",table:"info",fact:"ok"};

function typeLabel(t){var m=TYPE_META[t];return m?m.label:t;}
function kindOf(t){var m=TYPE_META[t];return m?m.kind:"fact";}
function srcLabel(type){var m=TYPE_META[type],lab=m&&m.src_label?m.src_label[type]:null;return lab||type;}

function entryUrl(e){return "#/e/"+encodeURIComponent(e.type)+"/"+encodeURIComponent(e.id);}
function typeUrl(t){return "#/browse/"+encodeURIComponent(t);}

/* 词条全文 hay（检索用，惰性） */
var _hay={};
function hay(e){
  if(_hay[e.id]!==undefined)return _hay[e.id];
  var parts=[e.title,e.id,e.summary];
  (function flat(v){if(v==null)return;if(typeof v==="string")parts.push(v);
    else if(typeof v==="number"||typeof v==="boolean")parts.push(String(v));
    else if(Array.isArray(v))v.forEach(flat);
    else if(typeof v==="object")Object.keys(v).forEach(function(k){parts.push(k);flat(v[k]);});})(e.doc);
  _hay[e.id]=parts.join("\n").toLowerCase();
  return _hay[e.id];
}

/* 词条级加权检索：title/id/summary/全文 */
function searchEntries(q){
  var terms=(q||"").toLowerCase().split(/\s+/).filter(Boolean);
  if(!terms.length)return [];
  var out=[];
  ENTRIES.forEach(function(e){
    var h=hay(e),ti=e.title.toLowerCase(),id=e.id.toLowerCase(),su=(e.summary||"").toLowerCase();
    var score=0,hitParts=[];
    terms.forEach(function(t){
      if(!t)return;
      if(ti.indexOf(t)>=0){score+=5;hitParts.push("title");}
      if(id.indexOf(t)>=0){score+=4;hitParts.push("id");}
      if(su.indexOf(t)>=0){score+=2;hitParts.push("summary");}
      if(h.indexOf(t)>=0){score+=1;if(score<=9)hitParts.push("full");}
    });
    if(score>0)out.push({e:e,score:score});
  });
  out.sort(function(a,b){return b.score-a.score||a.e.title.localeCompare(b.e.title,"zh");});
  return out;
}

/* 精确命中判断：term 出现在 title/id 任一处（供检索页结果徽标） */
function isExactHit(e,q){
  var terms=(q||"").toLowerCase().split(/\s+/).filter(Boolean);
  return terms.some(function(t){return e.title.toLowerCase().indexOf(t)>=0||e.id.toLowerCase().indexOf(t)>=0;});
}

/* 命中字段标签：title / id / summary / 全文 */
function hitModes(e,q){
  var terms=(q||"").toLowerCase().split(/\s+/).filter(Boolean);
  var t=terms.some(function(x){return e.title.toLowerCase().indexOf(x)>=0;})?"标题":"";
  var i=terms.some(function(x){return e.id.toLowerCase().indexOf(x)>=0;})?"ID":"";
  var s=terms.some(function(x){return (e.summary||"").toLowerCase().indexOf(x)>=0;})?"摘要":"";
  var f=terms.some(function(x){return hay(e).indexOf(x)>=0;})?"全文":"";
  if(!t&&!i&&!s&&!f)f="全文";
  return [t,i,s,f].filter(Boolean).join(" / ");
}

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

/* ============ 40 · dom：徽章 / chips / 命令工具卡等构件 ============ */
function typeBadge(t){var m=TYPE_META[t];var k=kindOf(t);
  return '<span class="badge b-'+esc(k)+' b-'+esc(t)+'">'+esc(m?m.label:t)+'</span>';}
function kindTag(kind){return '<span class="badge" style="background:var(--surface-2);color:var(--ink-2)">'+esc(KIND_LABEL[kind]||kind)+'</span>';}
function fileTag(f){return '<span class="file-tag">'+esc(f)+'</span>';}
function chip(txt,cls){return '<span class="chip '+(cls||"")+'">'+esc(txt)+'</span>';}
function chipHtml(inner,cls){return '<span class="chip '+(cls||"")+'">'+inner+'</span>';}
function chipLink(route,txt,cls){return '<a class="chip chip-link '+(cls||"")+'" href="'+route+'">'+esc(txt)+'</a>';}
function sourceBadge(type){
  return '<span class="badge b-src '+esc(type)+'">'+esc(srcLabel(type))+'</span>';}

var ICONS={
  copy:'<svg class="ic" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-1a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h1"/></svg>',
  check:'<svg class="ic" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m3 8.5 3.2 3.2L13 5"/></svg>',
  search:'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>',
  back:'<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5m6-7-7 7 7 7"/></svg>',
  link:'<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a5 5 0 0 0 7.07 0l3-3a5 5 0 0 0-7.07-7.07l-1.5 1.49"/><path d="M14 10a5 5 0 0 0-7.07 0l-3 3a5 5 0 0 0 7.07 7.07l1.5-1.49"/></svg>',
  ext:'<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4 11 13M20 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h5"/></svg>',
};

/* 命令拆行：按 ；/ ; / 换行 拆成单条命令 */
function splitCmds(s){return String(s==null?"":s).split(/[；;\n]+/).map(function(x){return x.trim();}).filter(Boolean);}

/* 单条命令 -> 工具卡（带复制） */
function cmdCard(cmd,label){
  label=label||"命令";
  return '<div class="cmd-card"><span class="c-label">'+esc(label)+'</span>'
    +'<span class="c-code">'+esc(cmd)+'</span>'
    +'<span class="c-act"><button class="c-copy" data-copy="'+esc(cmd)+'" title="复制命令">'+ICONS.copy+'<span>复制</span></button></span></div>';
}
/* 一组命令（拆行）*/
function cmdRows(s,label){
  var lines=splitCmds(s);
  if(!lines.length)return "";
  return '<div style="display:grid;gap:7px">'+lines.map(function(l){return cmdCard(l,label);}).join("")+'</div>';
}

/* ============ 50 · detail：词条详情内容渲染 ============ */

/* ---------- meta ---------- */
function appliesMetaHtml(doc){
  var a=doc.applies_to||{},out=[];
  if(a.platforms&&a.platforms.length)out.push(chip("平台 "+a.platforms.join(" / "),"chip-plat"));
  if(a.frameworks&&a.frameworks.length)out.push(chip("框架 "+a.frameworks.join(" / "),"chip-fw"));
  if(a.versions&&Object.keys(a.versions).length)out.push(chip("版本 "+Object.keys(a.versions).map(function(k){return k+": "+a.versions[k];}).join(" / ")));
  if(a.categories&&a.categories.length)out.push(chip("类别 "+a.categories.map(function(c){return CAT_LABEL[c]||c;}).join(" / "),"chip-cat"));
  return out.join("");
}

function statusChipHtml(doc){
  var st=doc.status||"";
  if(st==="active")return '<span class="b-status active"><span class="dot"></span>active</span>';
  return '<span class="b-status"><span class="dot" style="background:var(--ink-3);box-shadow:0 0 0 4px var(--surface-2)"></span>'+esc(st)+"</span>";
}

/* ---------- provenance 摘要条 + 来源面板 ---------- */
function provBarHtml(doc){
  var srcs=doc.sources||[];
  if(!srcs.length)return "";
  var sum={};srcs.forEach(function(s){sum[s.type]=(sum[s.type]||0)+1;});
  var badges=Object.keys(sum).map(function(t){
    return '<span class="badge b-src '+esc(t)+'">'+esc(srcLabel(t))+' ×'+sum[t]+"</span>";}).join("");
  var cards=srcs.map(function(s){
    var h='<div class="s-top">'+sourceBadge(s.type);
    if(s.url){var u=s.url,isLink=/^https?:\/\//.test(u);
      h+= isLink?'<a class="s-url" href="'+esc(u)+'" target="_blank" rel="noreferrer">'+esc(trunc(u,80))+" "+ICONS.ext+"</a>"
               :'<span class="s-url">'+esc(trunc(u,80))+"</span>";}
    h+="</div>";
    var meta=[];
    if(s.version)meta.push("版本 "+esc(s.version));
    if(s.verification)meta.push("核验 "+esc(s.verification));
    if(s.fetched_at)meta.push("抓取 "+esc(s.fetched_at));
    if(s.extracted_at)meta.push("提炼 "+esc(s.extracted_at));
    if(s.extraction_method)meta.push(esc(s.extraction_method));
    if(meta.length)h+='<div class="s-meta">'+meta.join('<span style="color:var(--line-2)">·</span>')+"</div>";
    if(s.cases&&s.cases.length)h+='<div class="s-cases">'+s.cases.map(function(c){return '<span class="casechip">'+esc(c)+"</span>";}).join("")+"</div>";
    return '<div class="src">'+h+"</div>";}).join("");
  var extra=[];
  if(doc.last_verified)extra.push("最近核验 "+esc(doc.last_verified));
  if(doc.hits!=null)extra.push("诊断命中 "+doc.hits+" 次");
  if(doc.last_hit)extra.push("最近命中 "+esc(doc.last_hit));
  return '<div class="prov-bar"><div class="p-top" role="button" tabindex="0" data-prov-toggle aria-expanded="false">'
    +'<span class="p-title"><span class="tw">▸</span>来源与校验</span>'
    +'<span class="p-badges">'+badges+'</span>'
    +(extra.length?'<span class="p-extra" style="color:var(--ink-3);font-size:11px;display:inline-flex;gap:12px">'+extra.map(function(x){return "<span>"+x+"</span>";}).join("")+"</span>":"")
    +'<span class="p-toggle">展开</span></div>'
    +'<div class="prov-panel"><div class="inner">'+cards+"</div></div></div>";
}

/* ---------- 结构化块：k/v 定义列表 + 分组卡片（替代无脑递归堆叠） ---------- */
function isPathish(s){
  s=String(s);
  return (/(\$HOME|\/|\$[A-Z_]+|\{[^}]+\}|\.so\b|\.log\b|\d+x\d+)/.test(s)) && s.length<180;
}
function isFlatMap(o){
  return Object.keys(o).every(function(k){
    var v=o[k];return v==null||typeof v==="string"||typeof v==="number"||
      (Array.isArray(v)&&v.every(function(x){return typeof x==="string";}));});
}
function scalarVal(v){
  if(v==null)return "";
  if(Array.isArray(v))return '<ul class="gen-list">'+v.map(function(x){return "<li>"+rich(String(x))+"</li>";}).join("")+"</ul>";
  if(typeof v==="object")return structuredBlock(v);
  var s=String(v);
  return isPathish(s)?'<span class="pval">'+esc(s)+"</span>":'<span class="tval">'+rich(s)+"</span>";
}
function kvList(o){
  return '<div class="kvlist" role="list">'+Object.keys(o).map(function(k){
    return '<div class="kvrow" role="listitem"><span class="k">'+esc(lbl(k))+'</span>'
      +'<span class="v">'+scalarVal(o[k])+"</span></div>";}).join("")+"</div>";
}
function structuredBlock(o){
  if(isFlatMap(o))return kvList(o);
  return '<div class="gcards">'+Object.keys(o).map(function(k){
    var v=o[k];
    var body=(v&&typeof v==="object"&&!Array.isArray(v))
      ?(isFlatMap(v)?kvList(v):structuredBlock(v)):scalarVal(v);
    return '<div class="gcard"><div class="ghead">'+esc(lbl(k))+'</div><div class="gbody">'+body+"</div></div>";}).join("")+"</div>";
}

/* ---------- 泛型块渲染（v1 移植，微调） ---------- */
var LABEL={invocation:"用法",commands:"命令",level_definitions:"级别定义",pitfalls:"坑点",output_meaning:"输出解读",
  claim:"结论",evidence:"证据",locations:"路径 / 位置",command:"命令",side_effects:"副作用",rollback:"回滚方式",
  version_dependent:"版本相关",flow:"流程",action:"动作",check:"检查",when_to_use:"适用时机",name:"名称",
  errors:"错误码",patterns:"故障模式",variables:"环境变量",matrix:"配套版本",compat:"兼容矩阵",symptoms:"现象特征",
  cause:"根因",fix:"处理",meaning:"含义",related_signatures:"相关特征",source_cases:"来源案例",code:"错误码",
  description:"说明",example:"示例",url:"来源",module:"模块",solution:"处理建议",hits:"命中",last_hit:"最近命中",
  tool_name:"工具名",platform:"平台",component:"组件",version:"版本",status:"状态",summary:"摘要",
  verified_by_testing:"真机验证",test_scenarios:"测试场景",details:"详情",structure:"结构",components:"组件",
  files:"文件",categories:"类别",frameworks:"框架",platforms:"平台",versions:"版本",apply:"适用",
  locations:"日志路径",ep:"EP 形态",rc:"RC 形态",control_cpu:"Control CPU 开放形态",
  container:"容器内查看",system:"系统类",app:"应用类",diag:"维测日志",aging:"老化机制"};
function lbl(k){return LABEL[k]||k.replace(/_/g," ");}
var MONO_KEYS={code:1,name:1,id:1,file:1,prefix:1,module:1,full_name:1,version:1,component:1,command:1,tool_name:1,path:1,key:1,opcode:1,event_id:1,side:1};
function cellHtml(v){
  if(v==null)return "";
  if(Array.isArray(v))return v.map(function(x){
    if(x&&typeof x==="object")return cellHtml(x);
    return '<span class="chip">'+esc(x)+"</span>";}).join(" ");
  if(typeof v==="object")return Object.keys(v).map(function(k){
    return '<div><b style="font-size:11px;color:var(--ink-3)">'+esc(lbl(k))+'</b> '+cellHtml(v[k])+"</div>";}).join("");
  return rich(String(v));
}
function genericTable(rows,spec){
  if(!rows||!rows.length)return "";
  var keys=[];
  if(spec){spec.forEach(function(s){if(s in rows[0])keys.push(s);});}
  var seen={};rows.forEach(function(r){Object.keys(r).forEach(function(k){
    if(!seen[k]){seen[k]=1;if(keys.indexOf(k)<0)keys.push(k);}});});
  var thead="<tr>"+keys.map(function(k){return "<th>"+esc(lbl(k))+"</th>";}).join("")+"</tr>";
  var body=rows.map(function(r){
    return "<tr>"+keys.map(function(k){
      var v=r[k];
      if(v==null)return "<td></td>";
      if(Array.isArray(v)){var isMono=(k==="symptoms"||k==="related_signatures"||k==="source_cases");
        return "<td>"+v.map(function(x){return isMono?'<span class="chip mono"><code>'+esc(x)+"</code></span>":'<span class="chip">'+esc(x)+"</span>";}).join(" ")+"</td>";}
      if(typeof v==="object")return "<td>"+cellHtml(v)+"</td>";
      var sv=String(v);
      if(MONO_KEYS[k])return '<td><span class="mono'+(sv.length>40?" wrap":"")+'">'+esc(sv)+"</span></td>";
      if(k==="url")return "<td>"+(/^https?:/.test(sv)?'<a href="'+esc(sv)+'" target="_blank" rel="noreferrer">'+esc(trunc(sv,44))+" ↗</a>":esc(trunc(sv,60)))+"</td>";
      if(sv==="Y"||sv==="N")return '<td><span class="yn '+sv+'">'+sv+"</span></td>";
      return '<td class="cell-main">'+rich(sv)+"</td>";
    }).join("")+"</tr>";}).join("");
  return '<div class="tblwrap"><table class="tbl"><thead>'+thead+"</thead><tbody>"+body+"</tbody></table></div>";
}
function subBlocks(obj,skip){
  var html="";
  Object.keys(obj).forEach(function(k){
    if(skip&&skip.indexOf(k)>=0)return;
    var v=obj[k];
    html+='<div class="subblock"><div class="lbl"><span class="zh">'+esc(lbl(k))+"</span></div>";
    if(typeof v==="string")html+='<p class="lead">'+rich(v)+"</p>";
    else if(Array.isArray(v)){
      if(v.length&&v.every(function(x){return typeof x==="string";}))html+='<ul class="gen-list">'+v.map(function(x){return "<li>"+rich(x)+"</li>";}).join("")+"</ul>";
      else html+=genericTable(v,null);
    }else if(typeof v==="object")html+=structuredBlock(v);
    html+="</div>";
  });
  return html;
}

/* ---------- 各 type 内容 ---------- */
function contentHtml(e){
  var d=e.doc,c=d.content||{};
  switch(e.type){
    case "methodology": return flowHtml(c,e);
    case "error-code": case "fault-pattern": case "env-var-table": return tableTypeHtml(e,c);
    case "compat-matrix": return compatHtml(c);
    case "tool": return toolHtml(c);
    case "command-side-effect": return cseHtml(c);
    default: return factHtml(c);
  }
}
function flowHtml(c,entry){
  entry=entry||{id:""};
  var steps=(c.flow||[]).slice().sort(function(a,b){return (Number(a.step)||0)-(Number(b.step)||0);});
  var total=steps.length;
  var done=flowDoneCount(entry.id,total);
  var html='<div class="flow" data-flow="'+esc(entry.id)+'">';
  if(total){
    html+='<div class="flow-prog"><div class="fp-bar"><i class="fp-fill" style="width:'+(total?(done/total*100):0)+'%"></i></div>'
      +'<span class="fp-label"><b data-fp-n>'+done+'</b> / '+total+' 完成</span>'
      +(done?'<button class="fp-reset" data-fp-reset>重置</button>':"")+"</div>";
  }
  html+='<div class="f-cap">'+total+' 步 · 按 <b style="color:var(--ink-2)">适用时机</b> 分流，逐步执行 check · 勾选记录学习进度</div><div class="steps">';
  steps.forEach(function(s,i){
    var doneI=flowGet(entry.id)[i]===true;
    html+='<div class="step'+(doneI?" done":"")+'" data-step="'+i+'"><div class="s-rail"><div class="s-num">'+(i+1)+'</div><div class="s-line"></div></div><div class="s-body">';
    html+='<div class="s-head"><span class="s-eyebrow">步骤 <i>'+esc(String(s.step||i+1))+'</i></span>'
      +'<button class="step-check" data-fp-step="'+i+'" aria-pressed="'+doneI+'" title="标记完成">'
      +(doneI?ICONS.check:"")+'<span>'+ (doneI?"完成":"标记") +'</span></button></div>';
    html+='<div class="s-name">'+esc(s.name||"")+"</div>";
    if(s.when_to_use)html+='<div class="when"><b>适用</b><span>'+rich(s.when_to_use)+"</span></div>";
    if(s.action)html+='<div class="action">'+rich(s.action)+"</div>";
    if(s.check)html+='<div class="checks"><div class="c-cap">执行检查</div>'+cmdRows(s.check,"检查")+"</div>";
    html+="</div></div>";
  });
  html+="</div>";
  if(c.verified_by_testing!=null)html+='<div class="note-box'+(c.verified_by_testing?" ok":"")+'">'
    +(c.verified_by_testing?'<b style="color:var(--ok)">✓ 已真机测试验证</b>——流程在真实环境跑通。'
      :"标注：流程来自来源核验，尚未真机验证（verified_by_testing: false）。")+"</div>";
  if(c.test_scenarios)html+='<div class="note-box">测试场景：'+esc(c.test_scenarios.join("；"))+"</div>";
  return html+"</div>";
}

/* 绑定步骤进度勾选 */
function bindFlow(scope,entryId){
  if(!entryId)return;
  var stepsEls=scope.querySelectorAll(".step-check");
  if(!stepsEls.length)return;
  function refresh(){
    var total=stepsEls.length;
    var doneN=0;
    stepsEls.forEach(function(btn){
      var i=btn.getAttribute("data-fp-step");
      var on=flowGet(entryId)[i]===true;
      if(on)doneN++;
      btn.setAttribute("aria-pressed",on?"true":"false");
      btn.classList.toggle("on",on);
      var s=btn.querySelector("span");if(s)s.textContent=on?"完成":"标记";
      var step=btn.closest(".step");if(step)step.classList.toggle("done",on);
    });
    var lbl=scope.querySelector(".flow-prog [data-fp-n]");
    if(lbl)lbl.textContent=doneN;
    var fill=scope.querySelector(".flow-prog .fp-fill");
    if(fill)fill.style.width=total?(doneN/total*100)+"%":"0%";
    var reset=scope.querySelector(".flow-prog [data-fp-reset]");
    if(reset)reset.style.display=doneN?"":"none";
  }
  stepsEls.forEach(function(btn){
    btn.addEventListener("click",function(){
      var i=btn.getAttribute("data-fp-step");
      flowSet(entryId,i,!(flowGet(entryId)[i]===true));
      refresh();
    });
  });
  var reset=scope.querySelector(".flow-prog [data-fp-reset]");
  if(reset)reset.addEventListener("click",function(){flowReset(entryId);refresh();});
  refresh();
}
function tableTypeHtml(e,c){
  var listKeys={"error-code":"errors","fault-pattern":"patterns","env-var-table":"variables"};
  var k=listKeys[e.type],rows=c[k]||[];
  var unit=e.type==="env-var-table"?"个":"条";
  var html='<div class="kbox"><div class="subblock"><div class="lbl"><span class="zh">'+esc(lbl(k))+"　"+rows.length+" "+unit+"</span></div>";
  if(e.type==="error-code")html+=genericTable(rows,["code","module","meaning","related_signatures","solution","source_cases"]);
  else if(e.type==="fault-pattern")html+=genericTable(rows,["pattern","symptoms","cause","fix"]);
  else html+=genericTable(rows,["name","description","example","url"]);
  return html+"</div></div>";
}
function compatHtml(c){
  var html='<div class="kbox">';
  var tags=[];if(c.layer)tags.push(chip("层: "+c.layer));if(c.component)tags.push(chip("主组件: "+c.component));
  if(tags.length)html+='<div style="display:flex;gap:6px;margin:12px 0 0">'+tags.join("")+"</div>";
  if(c.matrix&&c.matrix.length)html+='<div class="subblock"><div class="lbl"><span class="zh">配套版本 matrix</span></div>'+genericTable(c.matrix,["version"])+"</div>";
  if(c.compat&&c.compat.length)html+='<div class="subblock"><div class="lbl"><span class="zh">兼容矩阵（Y / N）</span></div>'+genericTable(c.compat,["component"])+"</div>";
  return html+"</div>";
}
function factHtml(c){
  var html='<div class="kbox">';
  if(c.claim)html+='<p class="claim">'+rich(c.claim)+"</p>";
  if(c.evidence)html+='<details class="ev"><summary>证据 / 出处</summary><div class="ev-body">'+rich(c.evidence)+"</div></details>";
  html+=subBlocks(c,["claim","evidence"]);
  return html+"</div>";
}
function toolHtml(c){
  var html='<div class="kbox">';
  if(c.tool_name)html+='<div class="subblock"><div class="lbl"><span class="zh">工具</span></div><p class="lead" style="font-weight:700;color:var(--ink);font-size:15px">'+rich(c.tool_name)+"</p></div>";
  if(c.invocation)html+='<div class="subblock"><div class="lbl"><span class="zh">用法</span></div><p class="lead">'+rich(c.invocation)+"</p></div>";
  if(c.commands){html+='<div class="subblock"><div class="lbl"><span class="zh">命令</span></div><div style="margin-top:8px">';
    if(c.commands instanceof Array){html+=cmdRows(c.commands.join("\n"));}
    else if(typeof c.commands==="object"){Object.keys(c.commands).forEach(function(nm){
      var cm=c.commands[nm];
      html+='<div style="display:flex;gap:8px;margin-bottom:7px;align-items:center">'
        +'<span style="font-size:11px;font-weight:700;color:var(--accent-ink);min-width:80px;text-align:right">'+esc(lbl(nm))+"</span>"
        +'<div style="flex:1;min-width:0">'+cmdCard(cm)+"</div></div>";});}
    html+="</div></div>";}
  if(c.output_meaning)html+='<div class="subblock"><div class="lbl"><span class="zh">输出解读</span></div><p class="lead">'+rich(c.output_meaning)+"</p></div>";
  if(c.level_definitions){html+='<div class="subblock"><div class="lbl"><span class="zh">级别定义</span></div>'
     +genericTable(Object.keys(c.level_definitions).map(function(k){return {level:k,meaning:c.level_definitions[k]};}),["level","meaning"])+"</div>";}
  if(c.pitfalls&&c.pitfalls.length)html+='<div class="subblock"><div class="lbl" style="color:var(--bad)"><span class="zh">坑点</span></div><ul class="gen-list">'+c.pitfalls.map(function(p){return "<li>"+rich(p)+"</li>";}).join("")+"</ul></div>";
  html+=subBlocks(c,["tool_name","invocation","commands","output_meaning","level_definitions","pitfalls"]);
  return html+"</div>";
}
function cseHtml(c){
  var html='<div class="kbox">';
  if(c.command)html+='<div class="subblock"><div class="lbl"><span class="zh">命令</span></div><div style="margin-top:8px">'+cmdCard(c.command)+"</div></div>";
  if(c.side_effects&&c.side_effects.length)html+='<div class="subblock"><div class="lbl"><span class="zh">副作用</span></div><ul class="gen-list">'+c.side_effects.map(function(p){return "<li>"+rich(p)+"</li>";}).join("")+"</ul></div>";
  if(c.rollback)html+='<div class="subblock"><div class="lbl" style="color:var(--warn)"><span class="zh">回滚方式</span></div><p class="lead">'+rich(c.rollback)+"</p></div>";
  if(c.version_dependent!=null)html+='<div style="margin-top:12px">'+chip(c.version_dependent?"版本相关行为":"与版本无关","chip-cat")+"</div>";
  html+=subBlocks(c,["command","side_effects","rollback","version_dependent"]);
  return html+"</div>";
}

/* ---------- 头部 / 工具栏 / 组装 ---------- */
function entryToolbar(e,crumb){
  var crumbHtml='<div class="crumb">'+(crumb?crumb.map(function(x){
    return x.url?'<a href="'+x.url+'">'+esc(x.label)+"</a>":'<span class="cur">'+esc(x.label)+"</span>";}).join('<span class="sep">/</span>'):"")
    +"</div>";
  return '<div class="d-toolbar">'+crumbHtml
    +'<span class="sp"></span>'
    +'<button class="mini" data-copy-link title="复制链接">'+ICONS.link+'链接</button>'
    +'<button class="mini" data-scroll-top title="回到顶部">↑ 顶部</button></div>';
}

/* 关系：related_references + 反向视图 */
function relHtml(e){
  var rel=e.doc.related_references||[];
  var refs=[];rel.forEach(function(r){var t=byId[r];
    refs.push(t?chipLink(entryUrl(t),r):'<span class="chip" title="词条不在数据中">'+esc(r)+"</span>");});
  var back=[];ENTRIES.forEach(function(x){
    var rr=x.doc.related_references||[];
    if(rr.indexOf(e.id)>=0)back.push(chipLink(entryUrl(x),x.id));});
  if(!refs.length&&!back.length)return "";
  var h='<div class="rel-box">';
  if(refs.length)h+='<div class="lbl">相关词条</div><div class="chips">'+refs.join("")+"</div>";
  if(back.length)h+='<div class="lbl" style="margin-top:10px">被以下词条引用</div><div class="chips">'+back.join("")+"</div>";
  return h+"</div>";
}
function pagerHtml(e){
  var list=byType[e.type]||[],idx=list.indexOf(e);
  var prev=list[idx-1],next=list[idx+1];
  function card(item,dir,align){
    return '<a href="'+entryUrl(item)+'" style="'+(align?"text-align:right;margin-left:auto":"")+'">'
      +'<span class="dir">'+dir+' · '+esc(typeLabel(item.type))+"</span>"
      +'<span class="pcard">'+esc(trunc(item.title,56))+"</span></a>";}
  if(!prev&&!next)return "";
  return '<div class="pager">'+(prev?card(prev,"← 上一条",""):"<span></span>")
    +(next?card(next,"下一条 →",true):"")+"</div>";
}

/* ============ 60 · views：启动台 / 双栏检索 / 词条 / triage ============ */
var $view=document.getElementById("view");

/* ---------------- 启动台 ---------------- */
var HOME_SCENES=[
  {no:"1",h:"从报错码开始",p:"现场报错数字 / 特征串 → 查含义、模块、关联特征与来源案例。",to:"打开错误码表",href:"#/browse/error-code"},
  {no:"2",h:"学一类定位流程",p:"方法论把「去哪采集 / 跑哪些命令、逐步验证」拆成可执行步骤流，按适用时机分流。",to:"浏览定位流程",href:"#/browse/methodology"},
  {no:"3",h:"日志到底在哪儿",p:"EP / RC / Control CPU 三形态的日志路径与采集工具——几乎一切定位的第一步。",to:"看日志路径词条",href:"#/e/software-fact/ascend-log-locations"},
  {no:"4",h:"现象该往哪查",p:"triage 路由：把报错关键词归到 中断 / 精度 / 性能 × 训推框架的检索入口。",to:"看症状路由图",href:"#/triage"}];

var SAMPLE_CANDIDATES=["507903","OOM","ascend/log","msnpureport","aclrtMallocHost","HCCL_DFS_CONFIG","310P","CANN","plog"];

function homeSamplesHtml(){
  var chosen=[];
  SAMPLE_CANDIDATES.forEach(function(q){if(chosen.length>=5)return;
    if(searchEntries(q).length)chosen.push(q);});
  if(chosen.length<3){var extra=["grep","kernel log"];chosen=chosen.concat(extra).slice(0,5);}
  return chosen.map(function(q){return '<button class="sample" data-sample="'+esc(q)+'">'+esc(q)+"</button>";}).join("");
}

function viewHome(){
  var recent=recentList();
  var h='<div class="home container">';
  h+='<div class="hero">'
    +'<div class="kicker">ascend-sleuth · references 人面消费层</div>'
    +'<h1>先验知识检索<br><span class="em">像查命令一样查问题</span></h1>'
    +'<p class="lede">同一批词条既服务 diagnose（agent 按需加载），也在这里面向你：错误码、故障模式、定位流程、工具与硬事实。'
    +'每条标注<b>来源类型与核验状态</b>——官方文档交叉核验，或从真实 case 提炼的教训。</p>'
    +'<div class="hero-search" id="heroSearch"><div class="search-host"></div></div>'
    +'<div class="hero-samples">'+homeSamplesHtml()+"</div>"
    +"</div>";
  if(recent.length){
    h+='<section class="rv"><div class="sec-head"><h2><span class="zh">最近浏览</span></h2>'
      +'<span class="sub">本地记录</span></div><div class="recent">';
    recent.forEach(function(r){
      var e=byId[r.id];if(!e)return;
      h+='<span class="rchip"><a href="'+entryUrl(e)+'" style="color:inherit">'+esc(trunc(r.title,26))
        +'</a><button class="x" data-recent-rm="'+esc(r.id)+'" title="移除" aria-label="移除">×</button></span>';
    });
    h+="</div></section>";
  }
  h+='<section class="rv" data-rv-delay="40"><div class="sec-head"><h2><span class="zh">从哪开始</span></h2>'
    +'<span class="sub">按任务选入口</span></div><div class="scenes">';
  HOME_SCENES.forEach(function(s){
    var ok=true;
    if(s.href.indexOf("#/e/")===0){var sp2=s.href.split("/"),sid=decodeURIComponent(sp2[sp2.length-1]);ok=!!byId[sid];}
    if(!ok)return;
    h+='<a class="scene" href="'+s.href+'"><div class="no">'+s.no+'</div><h3>'+esc(s.h)
      +'<span class="arr">→</span></h3><p>'+esc(s.p)+'</p><span class="tick">'+esc(s.to)+"</span></a>";
  });
  h+="</div></section>";
  h+='<section class="rv" data-rv-delay="100"><div class="sec-head"><h2><span class="zh">数据域</span></h2>'
    +'<span class="sub">'+ENTRIES.length+' 词条 · 组织单元＝验证单元，一行 / 一词条独立核验</span></div><div class="domain-rows">';
  TYPES.forEach(function(t){
    var list=byType[t.type]||[];
    if(!list.length)return;
    h+='<a class="domain" href="'+typeUrl(t.type)+'"><span class="dcnt">'+list.length+"</span>"
      +'<span style="display:flex;gap:9px;align-items:center;min-width:0;flex:1">'
      +'<span class="dh">'+esc(t.label)+'</span><span class="dhint">'+esc(t.hint||"")+"</span></span>"
      +'<span class="darrow">→</span></a>';
  });
  h+="</div></section>";
  h+='<p style="color:var(--ink-3);font-size:11px;margin-top:34px;line-height:1.8">'
    +"数据源 references/ · 生成于 "+esc(KB.generated_at||"")+"<br>"
    +"demo 边界：knowledge/（case 层，含客户数据）为私有，不在本界面；case↔reference 反链随 diagnose 沉淀累积后加入。</p>";
  h+="</div>";
  $view.innerHTML=h;
  document.title="昇腾知识浏览器 · 总览";
  mountSearch(document.getElementById("heroSearch"),{big:true});
  revealScope($view);
}

/* ---------------- 双栏检索（类型目录 / 搜索结果共用） ---------------- */
/* ctl 为模块级单实例，路由重渲染时重建 */
var browseCtl=null;
function paneOfType(t){return {kind:"type",key:t};}
function paneOfQuery(q){return {kind:"q",key:q};}

function listFor(pane,ft,text){
  var base=pane.kind==="q"?(searchEntries(pane.key)||[]):(byType[pane.key]||[]).map(function(e){return {e:e,score:0};});
  if(ft&&ft!=="all")base=base.filter(function(r){return r.e.type===ft;});
  if(text){var lo=text.toLowerCase();base=base.filter(function(r){
    return r.e.title.toLowerCase().indexOf(lo)>=0||r.e.id.toLowerCase().indexOf(lo)>=0
      ||(r.e.summary||"").toLowerCase().indexOf(lo)>=0;});}
  return base;
}

function viewBrowse(pane,selId){
  var isType=pane.kind==="type";
  var headTxt=isType?typeLabel(pane.key):('“'+pane.key+'”');
  var crumb2=[{label:"总览",url:"#/"},{label:isType?typeLabel(pane.key):("搜索 “"+trunc(pane.key,22)+"”")}];
  var h='<div class="browse">';
  h+='<div class="b-listpane"><div class="b-filter">'
    +'<div class="b-search">'+ICONS.search+'<input type="search" class="bf-in" placeholder="'+esc(isType?"在"+typeLabel(pane.key)+"中过滤…":"在结果中过滤…")+'" aria-label="列表内过滤"></div>';
  if(!isType){
    var typeSet={};listFor(pane,"all",null).forEach(function(r){typeSet[r.e.type]=1;});
    var chips=['<button class="ftag on" data-ft="all">全部</button>'];
    TYPES.forEach(function(t){if(typeSet[t.type])chips.push('<button class="ftag" data-ft="'+esc(t.type)+'">'+esc(t.label)+"</button>");});
    h+='<div class="b-filters">'+chips.join("")+"</div>";
  }
  h+='</div><div class="b-head"><b>'+headTxt+'</b>'
    +(isType?esc(KIND_LABEL[kindOf(pane.key)]||""):'<span style="color:var(--ink-3)">加权 · 标题/摘要/全文</span>')
    +'<span class="cnt" data-cnt></span></div>'
    +'<div class="b-scroll" data-rows></div></div>';
  h+='<div class="b-detailpane" data-detail><div class="inner"><div class="empty"><div class="big">⌁</div>'
    +"<h3>选择左侧词条</h3><p>"+(isType?"当前目录 · "+esc(typeLabel(pane.key)):"检索结果 · 加权排序")+"</p>"
    +'<p style="font-size:11.5px">支持 <kbd style="font-family:var(--mono);border:1px solid var(--line-2);border-radius:5px;padding:0 5px">↑</kbd> <kbd style="font-family:var(--mono);border:1px solid var(--line-2);border-radius:5px;padding:0 5px">↓</kbd> 键快速切换</p>'
    +"</div></div></div></div>";
  $view.innerHTML=h;
  document.title="昇腾知识浏览器 · "+headTxt;
  browseCtl={pane:pane,ft:"all",text:"",list:null,sel:-1,crumbs:crumb2};
  renderBrowseList(browseCtl);
  var all=browseCtl.list||[];
  if(all.length){var want=selId||all[0].e.id;
    var idx=all.findIndex(function(r){return r.e.id===want;});
    browseCtl.sel=idx>=0?idx:0;
    renderBrowseDetail(browseCtl,false,true);
    markSel(browseCtl);}
  bindBrowse(browseCtl);
}

function renderBrowseList(ctl){
  var rowsEl=$view.querySelector("[data-rows]"),cntEl=$view.querySelector("[data-cnt]");
  var rows=listFor(ctl.pane,ctl.ft,ctl.text);
  ctl.list=rows;
  cntEl.textContent=rows.length+" 条";
  if(!rows.length){rowsEl.innerHTML='<div class="b-empty">无匹配词条</div>';return;}
  var q=ctl.pane.kind==="q"?ctl.pane.key:"";
  rowsEl.innerHTML=rows.map(function(r,i){
    var e=r.e;
    return '<div class="b-item" data-i="'+i+'" role="button" tabindex="-1">'
      +'<div class="t1"><span class="tt">'+(q?hilite(e.title,q):esc(e.title))+"</span>"
      +'<span class="tid">'+esc(e.id)+"</span></div>"
      +'<div class="marks">'+typeBadge(e.type)
      +(q?'<span class="score-tag">'+esc(hitModes(e,q))+"</span>":"")+"</div>"
      +(e.summary?'<div class="ts">'+(q?hilite(e.summary,q):esc(e.summary))+"</div>":"")
      +"</div>";}).join("");
}

function renderBrowseDetail(ctl,explicit,initial){
  var paneEl=$view.querySelector("[data-detail] .inner");
  if(!ctl.list||ctl.sel<0||ctl.sel>=ctl.list.length)return;
  var e=ctl.list[ctl.sel].e;
  var crumb=ctl.crumbs.concat([{label:e.title,url:entryUrl(e)}]);
  paneEl.innerHTML='<div class="detail-swap">'+entryToolbar(e,crumb)+'<div class="entry-page">'+entryBodyHtml(e)+"</div></div>";
  var sp=paneEl.querySelector("[data-scroll-top]");
  if(sp)sp.addEventListener("click",function(){var dp=$view.querySelector("[data-detail]");dp.scrollTo({top:0,behavior:reducedMotion()?"auto":"smooth"});});
  var cl=paneEl.querySelector("[data-copy-link]");
  if(cl)cl.addEventListener("click",function(){copyText(location.href.split("#")[0]+entryUrl(e),function(){toastCopy(e.id);});});
  var dp=$view.querySelector("[data-detail]");
  dp.scrollTop=0;
  bindProv(paneEl);
  bindFlow(paneEl,e.id);
  if(explicit)recentPush(e);
  var pager=paneEl.querySelector(".pager");
  if(pager){
    var n=ctl.list.length;
    if(n>1){
      pager.innerHTML='<button class="mini" data-inpager="prev"'+(ctl.sel===0?' disabled style="opacity:.45"':"")+'>← 上一条</button>'
        +'<button class="mini" data-inpager="next" style="margin-left:auto"'+(ctl.sel>=n-1?' disabled style="opacity:.45;margin-left:auto"':"")+'>下一条 →</button>';
    }else pager.remove();
  }
}

/* 让检索语境下的 pager 在列表内切换 */
function entryBodyHtml(e,opts){
  opts=opts||{};
  var d=e.doc;
  var h='<article class="ehead"><div class="row1">'+typeBadge(e.type)+kindTag(kindOf(e.type))+fileTag(e.file)+"</div>";
  h+="<h1>"+esc(d.title||e.id)+"</h1>";
  if(d.summary)h+='<p class="esum">'+rich(d.summary)+"</p>";
  h+='<div class="meta-row">'+statusChipHtml(d)
    +(d.last_verified?'<span class="kv"><b>核验</b>'+esc(d.last_verified)+"</span>":"")
    +(d.hits!=null?'<span class="kv"><b>命中</b>'+d.hits+"</span>":"")
    +(appliesMetaHtml(d)?'<span class="kv" style="display:inline-flex;flex-wrap:wrap;gap:4px">'+appliesMetaHtml(d)+"</span>":"")
    +"</div></article>";
  h+=provBarHtml(d);
  h+='<div class="kbox">'+contentHtml(e)+"</div>";
  h+=relHtml(e);
  h+=pagerHtml(e);
  return h;
}

function bindBrowse(ctl){
  var rowsEl=$view.querySelector("[data-rows]");
  var inp=$view.querySelector(".bf-in");
  if(inp)inp.addEventListener("input",debounce(function(){
    ctl.text=inp.value.trim();
    var keep=ctl.list&&ctl.list[ctl.sel]?ctl.list[ctl.sel].e.id:null;
    renderBrowseList(ctl);
    var rows=ctl.list||[];
    if(keep){var idx=rows.findIndex(function(r){return r.e.id===keep;});
      ctl.sel=idx>=0?idx:(rows.length?0:-1);}
    else ctl.sel=rows.length?0:-1;
    if(ctl.sel>=0){renderBrowseDetail(ctl,false,false);markSel(ctl);}
  },140));
  $view.querySelectorAll(".ftag").forEach(function(f){
    f.addEventListener("click",function(){
      $view.querySelectorAll(".ftag").forEach(function(x){x.classList.remove("on");});
      f.classList.add("on");ctl.ft=f.getAttribute("data-ft");
      ctl.text=inp?inp.value.trim():"";
      renderBrowseList(ctl);
      ctl.sel=ctl.list&&ctl.list.length?0:-1;
      if(ctl.sel>=0){renderBrowseDetail(ctl,false,false);markSel(ctl);}
    });
  });
  /* 列表点击 / hover */
  rowsEl.addEventListener("click",function(ev){
    var it=ev.target.closest(".b-item");if(!it)return;
    selectBrowse(ctl,parseInt(it.getAttribute("data-i"),10),true);
  });
  /* hover 不高亮，仅显性选择 */
  $view._browseCtl=ctl;
  /* pager 在详情中切换为列表内导航：通过事件代理 */
  var dp=$view.querySelector("[data-detail]");
  dp.addEventListener("click",function(ev){
    var pg=ev.target.closest("[data-inpager]");if(!pg)return;
    var dir=pg.getAttribute("data-inpager");
    ev.preventDefault();
    var i=dir==="next"?ctl.sel+1:ctl.sel-1;
    if(i>=0&&i<ctl.list.length){selectBrowse(ctl,i,true);}
  });
}

function markSel(ctl){
  $view.querySelectorAll(".b-item").forEach(function(el){
    el.classList.toggle("sel",parseInt(el.getAttribute("data-i"),10)===ctl.sel);
    if(parseInt(el.getAttribute("data-i"),10)===ctl.sel)el.scrollIntoView({block:"nearest",behavior:reducedMotion()?"auto":"smooth"});
  });
}
function selectBrowse(ctl,i,explicit){
  if(i<0||i>=(ctl.list||[]).length)return;
  ctl.sel=i;
  markSel(ctl);
  renderBrowseDetail(ctl,explicit,false);
}

/* ---------------- 独立词条页 ---------------- */
function viewEntry(type,id){
  var e=byId[id];
  if(!e){viewHome();toast("未找到词条 <code>"+esc(id)+"</code>");return;}
  var m=TYPE_META[e.type]||{};
  var crumb=[{label:"总览",url:"#/"},{label:m.label,url:typeUrl(e.type)},{label:id}];
  var h='<div class="container" style="max-width:1080px"><div style="padding:6px 0 80px">'
    +entryToolbar(e,crumb)
    +'<div class="entry-page">'+entryBodyHtml(e,{})+"</div></div></div>";
  $view.innerHTML=h;
  document.title="昇腾知识浏览器 · "+e.id;
  recentPush(e);
  var sp=$view.querySelector("[data-scroll-top]");
  if(sp)sp.addEventListener("click",function(){window.scrollTo({top:0,behavior:reducedMotion()?"auto":"smooth"});});
  var cl=$view.querySelector("[data-copy-link]");
  if(cl)cl.addEventListener("click",function(){copyText(location.href.split("#")[0]+entryUrl(e),function(){toastCopy(e.id);});});
  bindProv($view);
  bindFlow($view,e.id);
  revealScope($view);
}

function bindProv(scope){
  scope.querySelectorAll("[data-prov-toggle]").forEach(function(el){
    var bar=el.closest(".prov-bar");
    var toggle=function(){var open=bar.classList.toggle("open");
      el.setAttribute("aria-expanded",open?"true":"false");
      var lbl=bar.querySelector(".p-toggle");if(lbl)lbl.textContent=open?"收起":"展开";};
    el.addEventListener("click",toggle);
    el.addEventListener("keydown",function(ev){if(ev.key==="Enter"||ev.key===" "){ev.preventDefault();toggle();}});
  });
}

/* ---------------- triage ---------------- */
var CAT_COLOR={interrupt:"var(--warn)",precision:"var(--info)",performance:"var(--ok)"};
function viewTriage(){
  var cats={};TRIAGE.forEach(function(b){var c=b.category||"other";cats[c]=(cats[c]||0)+1;});
  var total=TRIAGE.length;
  var h='<div class="triage container"><div class="triage-head">'
    +'<div class="kicker">triage-tree</div>'
    +'<h1>症状 → 检索路由图</h1>'
    +'<p>两个正交轴：<b>在哪查</b>＝训推 × 框架（→ knowledge/ 命名空间，本界面不含私有 case）；<b>什么性质</b>＝category 决定诊断路径。'
    +"把现场报错里的关键词对照下方各分支的症状词，理解「这类问题该往哪个方向查」。</p>";
  h+='<div class="triage-stats">'
    +'<div class="bar-dist" title="按 category 分布">'+Object.keys(cats).map(function(c){
      return '<i style="width:'+(cats[c]/total*100)+'%;background:'+CAT_COLOR[c]+'" data-cat="'+esc(c)+'" title="'+esc(CAT_LABEL[c]||c)+' '+cats[c]+' 条"></i>';}).join("")+"</div>"
    +'<div class="legend">'+Object.keys(cats).map(function(c){
      return '<span><i style="background:'+CAT_COLOR[c]+'"></i>'+esc(CAT_LABEL[c]||c)+" "+cats[c]+"</span>";}).join("")+"</div></div>";
  h+='<div class="b-filters" style="margin-top:14px"><button class="ftag on" data-cf="all">全部分支 '+total+"</button>"
    +Object.keys(cats).map(function(c){return '<button class="ftag" data-cf="'+esc(c)+'">'+esc(CAT_LABEL[c]||c)+" "+cats[c]+"</button>";}).join("")+"</div>";
  h+='</div><div class="branches" data-branches></div></div>';
  $view.innerHTML=h;
  document.title="昇腾知识浏览器 · 症状路由图";
  renderBranches("all");
  $view.querySelectorAll("[data-cf]").forEach(function(f){
    f.addEventListener("click",function(){
      $view.querySelectorAll("[data-cf]").forEach(function(x){x.classList.remove("on");});
      f.classList.add("on");renderBranches(f.getAttribute("data-cf"));});});
  revealScope($view);
}
function renderBranches(cf){
  var el=$view.querySelector("[data-branches]");
  el.innerHTML=TRIAGE.filter(function(b){return cf==="all"||b.category===cf;}).map(function(b){
    var syms=b.symptoms||[];
    var ns=(b.search_namespaces||[]).map(function(n){return chip(n,"chip-plat");}).join("");
    return '<div class="branch"><div class="b-head" data-branch-head>'
      +'<span class="b-id">'+esc(b.id)+"</span>"
      +chip(CAT_LABEL[b.category]||b.category||"","chip-cat")
      +'<span class="b-ns">'+ns+'</span>'
      +'<span class="b-caret">▸</span></div>'
      +'<div class="b-region"><div class="inner">'
      +'<div class="lbl" style="font-size:10px;letter-spacing:.14em;color:var(--ink-3);font-weight:700;margin-bottom:4px">症状关键词 '+syms.length+' 条 · 正则匹配（可复制单条）</div>'
      +'<div class="b-list">'+syms.map(function(s){return s;}).join("\n")+"</div>"
      +"</div></div></div>";}).join("")||'<div class="empty">该类别暂无分支</div>';
  el.querySelectorAll("[data-branch-head]").forEach(function(hd){
    hd.addEventListener("click",function(){
      var br=hd.closest(".branch");var open=br.classList.toggle("open");});
  });
}

/* ============ 70 · searchui：即时联想搜索（topbar pill / hero 大搜索共用） ============ */
var gTopInput=null, heroInput=null, lastSuggest=null;

function mountSearch(container,opts){
  opts=opts||{};
  var inputId="si_"+(opts.big?"hero":"top");
  var inner=(opts.big?'<div class="box">':'<div class="pill">')
    +'<svg width="'+(opts.big?18:15)+'" height="'+(opts.big?18:15)+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/></svg>'
    +'<input class="si" id="'+inputId+'" type="search" autocomplete="off" spellcheck="false" '
    +'placeholder="'+esc(opts.big?"错误码 507903 · HCCL_DFS_CONFIG · msnpureport · ascend/log …":"搜索错误码 / 命令 / 症状…")+'" '
    +'aria-label="搜索知识库" role="combobox" aria-expanded="false" aria-controls="sug_'+inputId+'">'
    +'<kbd class="'+(opts.big?"":"hidden")+'">'+(opts.big?"↵":"⌘K")+"</kbd></div>"
    +'<div class="suggest" id="sug_'+inputId+'" role="listbox"></div>';
  container.innerHTML=inner;
  var input=container.querySelector(".si");
  var sug=container.querySelector(".suggest");
  if(opts.big)heroInput=input;else gTopInput=input;
  var cur=-1,open=false;

  function rowsHtml(q){
    var res=searchEntries(q).slice(0,7);
    if(!res.length)return '<div class="sg-foot">无匹配 —— 试试错误码数字、命令关键字、日志路径或平台名</div>';
    var h='<div class="sg"><span>结果</span><span class="sg-tip">↑↓ 选择 · Enter 打开</span></div>';
    h+=res.map(function(r,i){
      var e=r.e;
      return '<div class="srow'+(i===cur?" sel":"")+'" data-i="'+i+'" role="option" aria-selected="'+(i===cur)+'">'
        +'<span class="rt">'+hilite(e.title,q)+'</span><span class="rid">'+esc(e.id)+"</span>"
        +'<span class="rtype">'+typeBadge(e.type)+"</span></div>";}).join("");
    h+='<div class="sg-foot" data-gofull>查看全部 '+searchEntries(q).length+" 条结果 →</div>";
    return h;
  }
  function show(q){sug.innerHTML=rowsHtml(q);sug.classList.add("open");
    input.setAttribute("aria-expanded","true");open=true;cur=-1;}
  function hide(){sug.classList.remove("open");input.setAttribute("aria-expanded","false");open=false;cur=-1;}
  function openSel(i){
    if(i<0||i>=7)return;
    var q=input.value.trim();
    var row=sug.querySelector('[data-i="'+i+'"]');
    var e=(searchEntries(q).slice(0,7)[i]||{}).e;
    if(e){location.hash=entryUrl(e);hide();input.blur();}
  }
  var onInput=debounce(function(){
    var q=input.value.trim();
    if(!q){hide();return;}
    show(q);
  },110);
  input.addEventListener("input",onInput);
  input.addEventListener("keydown",function(ev){
    if(ev.key==="ArrowDown"){ev.preventDefault();if(!open)show(input.value.trim());cur=Math.min(cur+1,6);sug.innerHTML=rowsHtml(input.value.trim());var r=sug.querySelector('[data-i="'+cur+'"]');if(r)r.scrollIntoView({block:"nearest"});}
    else if(ev.key==="ArrowUp"){ev.preventDefault();if(!open)show(input.value.trim());cur=Math.max(cur-1,-1);sug.innerHTML=rowsHtml(input.value.trim());}
    else if(ev.key==="Enter"){ev.preventDefault();var q=input.value.trim();if(!q)return;
      if(cur>=0&&open)openSel(cur);else{location.hash="#/q/"+encodeURIComponent(q);hide();input.blur();}}
    else if(ev.key==="Escape"){hide();input.blur();}
  });
  sug.addEventListener("mousedown",function(ev){
    var row=ev.target.closest(".srow");
    if(row){ev.preventDefault();cur=parseInt(row.getAttribute("data-i"),10);openSel(cur);return;}
    var go=ev.target.closest("[data-gofull]");
    if(go){ev.preventDefault();var q=input.value.trim();location.hash="#/q/"+encodeURIComponent(q);hide();}
  });
  input.addEventListener("focus",function(){if(input.value.trim())show(input.value.trim());});
  container.addEventListener("focusout",function(ev){
    if(!container.contains(ev.relatedTarget))setTimeout(hide,120);});
  lastSuggest={input:input,open:open,hide:hide};
}

/* 全局唤起：⌘K / Ctrl+K / '/' */
function focusSearch(){
  var t=heroInput&&document.contains(heroInput)?heroInput:(gTopInput||null);
  if(t){t.focus();t.select();}
  else{var hq=document.querySelector(".hero .si");if(hq)hq.focus();}
}

/* ============ 72 · palette：⌘K 命令面板（键盘优先） ============ */
var _palEl=null,_palQ=null,_palList=null,_palItems=[],_palSel=-1,_palOpen=false;

function paletteActions(){
  var a=[
    {kind:"action",label:"总览 / 检索",sub:"回到启动台",href:"#/"},
    {kind:"action",label:"症状路由图",sub:"triage 分流",href:"#/triage"},
  ];
  TYPES.forEach(function(t){
    var n=(byType[t.type]||[]).length;
    if(n)a.push({kind:"action",label:t.label,sub:n+" 词条 · "+esc(KIND_LABEL[kindOf(t.type)]||""),href:typeUrl(t.type)});
  });
  return a;
}
function paletteRecent(){
  return recentList().map(function(r){var e=byId[r.id];return e?{kind:"recent",label:r.title,sub:e.id,href:entryUrl(e)}:null;}).filter(Boolean);
}
function paletteRows(q){
  q=(q||"").trim();
  if(!q){
    // 无输入：动作 + 最近
    var rows=paletteActions().map(function(a){return Object.assign(a,{tag:"动作"});});
    var rec=paletteRecent().map(function(r){return Object.assign(r,{tag:"最近"});});
    return rows.concat(rec);
  }
  // 有输入：实时结果（词条）
  var res=searchEntries(q).slice(0,9).map(function(r){return {kind:"entry",label:r.e.title,sub:r.e.id+" · "+typeLabel(r.e.type),href:entryUrl(r.e)};});
  var total=searchEntries(q).length;
  if(total>9)res.push({kind:"more",label:"查看全部 "+total+" 条结果",sub:"标题 / 摘要 / 全文命中",q:q});
  if(!res.length)return [{kind:"none",label:"无匹配",sub:"试试错误码 / 命令 / 路径 / 平台名",href:null}];
  return res;
}
function palRender(){
  if(!_palList)return;
  _palList.innerHTML=_palItems.map(function(it,i){
    var h='<div class="prow'+(i===_palSel?" sel":"")+'" data-i="'+i+'" role="option" aria-selected="'+(i===_palSel)+'" tabindex="-1">'
      +(it.tag?'<span class="ptag">'+esc(it.tag)+"</span>":"")
      +'<span class="pl">'+esc(it.label)+"</span>"
      +(it.sub?'<span class="ps">'+rich(it.sub)+"</span>":"")
      +'<span class="pgo">↵</span></div>';
    return h;}).join("");
  var sel=_palList.querySelector('[data-i="'+_palSel+'"]');
  if(sel)sel.scrollIntoView({block:"nearest"});
}
function palUpdate(q){
  _palItems=paletteRows(q);
  _palSel=_palItems.length?0:-1;
  palRender();
}
function palOpen(){
  if(!_palEl)_palEl=document.getElementById("palette");
  if(!_palQ)_palQ=document.getElementById("palQ");
  if(!_palList)_palList=document.getElementById("palList");
  if(!_palEl)return;
  if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
  _palEl.hidden=false;_palOpen=true;
  _palQ.value="";palUpdate("");
  _palQ.focus();
  document.body.style.overflow="hidden";
}
function palClose(){
  if(!_palEl)_palEl=document.getElementById("palette");
  if(_palEl)_palEl.hidden=true;
  _palOpen=false;
  document.body.style.overflow="";
  var v=document.getElementById("view");
  if(v)v.focus();
}
function palSel(i){
  if(!_palItems.length)return;
  if(i<0)i=0;if(i>=_palItems.length)i=_palItems.length-1;
  _palSel=i;palRender();
}
function palOpenCurrent(){
  var it=_palItems[_palSel];
  if(!it)return;
  if(it.kind==="more"){location.hash="#/q/"+encodeURIComponent(it.q);palClose();return;}
  if(it.href){location.hash=it.href;palClose();return;}
}

function wirePalette(){
  if(!_palEl)_palEl=document.getElementById("palette");
  if(!_palList)_palList=document.getElementById("palList");
  if(!_palQ)_palQ=document.getElementById("palQ");
  if(!_palEl)return;
  _palEl.addEventListener("mousedown",function(ev){
    if(ev.target.closest("[data-pal-close]")){ev.preventDefault();palClose();}
    var row=ev.target.closest(".prow");
    if(row){ev.preventDefault();_palSel=parseInt(row.getAttribute("data-i"),10);palOpenCurrent();}
  });
  _palQ.addEventListener("input",function(){palUpdate(_palQ.value);});
  _palQ.addEventListener("keydown",function(ev){
    if(ev.key==="ArrowDown"){ev.preventDefault();palSel(_palSel+1);}
    else if(ev.key==="ArrowUp"){ev.preventDefault();palSel(_palSel-1);}
    else if(ev.key==="Enter"){ev.preventDefault();palOpenCurrent();}
    else if(ev.key==="Escape"){ev.preventDefault();palClose();}
  });
}
window.__paletteToggler=(function(){return {open:palOpen,close:palClose,isOpen:function(){return _palOpen;}};})();

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
