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
