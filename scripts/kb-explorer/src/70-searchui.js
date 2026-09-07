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
