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
