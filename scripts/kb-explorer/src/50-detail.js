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
