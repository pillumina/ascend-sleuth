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
