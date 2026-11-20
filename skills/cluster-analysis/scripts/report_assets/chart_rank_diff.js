(function(){{
  var el = document.getElementById('chart-part-step');
  if (!el || typeof echarts === 'undefined') return;
  function build(){{
    if (el.__chart) {{ el.__chart.resize(); return; }}
    el.__chart = echarts.init(el);
    el.__chart.setOption({{
      tooltip: {{trigger:'axis', axisPointer:{{type:'shadow'}}}},
      legend: {{type:'scroll', textStyle:{{color:'#94a3b8'}}}},
      grid: {{left:60, right:20, top:40, bottom:30}},
      xAxis: {{type:'category', name:'部分', data:{categories},
               axisLabel:{{color:'#e2e8f0', fontSize:13, interval:0}}}},
      yAxis: {{type:'value', name:'时间(ms)', axisLabel:{{color:'#94a3b8'}}}},
      series: {series}
    }});
  }}
  // 折叠容器懒初始化：details 展开时再渲染，避免隐藏容器宽高为 0
  var host = el.closest('details');
  if (!host || host.open) build();
  else host.addEventListener('toggle', function once(ev){{
    if (!host.open) return;
    host.removeEventListener('toggle', once);
    requestAnimationFrame(build);
  }});
}})();
