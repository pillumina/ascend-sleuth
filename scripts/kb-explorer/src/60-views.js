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
