(function(){
  var links = document.querySelectorAll('.sidebar nav a');
  var map = {};
  links.forEach(function(a){ map[a.getAttribute('href').slice(1)] = a; });
  var sections = [];
  Object.keys(map).forEach(function(id){
    var s = document.getElementById(id); if (s) sections.push(s);
  });
  function onScroll(){
    var cur = sections.length ? sections[0].id : null;
    for (var i=0;i<sections.length;i++){
      if (sections[i].getBoundingClientRect().top <= 90) cur = sections[i].id;
    }
    links.forEach(function(a){ a.classList.remove('active'); });
    if (cur && map[cur]) map[cur].classList.add('active');
  }
  window.addEventListener('scroll', onScroll, {passive:true});
  onScroll();
  // clicking a nav link opens its folded (details) section
  links.forEach(function(a){
    a.addEventListener('click', function(){
      var el = document.getElementById(a.getAttribute('href').slice(1));
      if (el && el.tagName === 'DETAILS') el.open = true;
    });
  });
  // anchor/hash navigation (direct URL, back/forward) also opens its section
  function openByHash(){
    var id = decodeURIComponent((location.hash || '').slice(1));
    if (!id) return;
    var el = document.getElementById(id);
    if (el && el.tagName === 'DETAILS') el.open = true;
  }
  window.addEventListener('hashchange', openByHash);
  openByHash();
  // 全部展开 / 全部收起
  var tbtn = document.getElementById('toggle-all');
  if (tbtn) tbtn.addEventListener('click', function(){
    var all = document.querySelectorAll('details.sec');
    var anyClosed = false;
    all.forEach(function(d){ if (!d.open) anyClosed = true; });
    all.forEach(function(d){ d.open = anyClosed; });
    tbtn.textContent = anyClosed ? '全部收起' : '全部展开';
  });
  // 任一 section 展开/收起后触发全局 resize，让 ECharts 实例适配新的容器尺寸
  document.querySelectorAll('details.sec').forEach(function(d){
    d.addEventListener('toggle', function(){
      requestAnimationFrame(function(){ window.dispatchEvent(new Event('resize')); });
    });
  });
})();
