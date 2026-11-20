(function(){{
  var el = document.getElementById('chart-cluster');
  if (!el || typeof echarts === 'undefined') return;
  function build(){{
    if (el.__chart) {{ el.__chart.resize(); return; }}
    el.__chart = echarts.init(el);
    el.__chart.setOption({{
      tooltip: {{trigger:'axis'}}, legend: {{textStyle:{{color:'#94a3b8'}}}},
      grid: {{left:50, right:20, top:40, bottom:30}},
      xAxis: {{type:'category', data:{steps}, axisLabel:{{color:'#94a3b8'}}}},
      yAxis: {{type:'value', axisLabel:{{color:'#94a3b8'}}}},
      series: [
        {{name:'计算', type:'bar', stack:'t', data:{comp}, itemStyle:{{color:'#34d399'}}}},
        {{name:'未掩盖通信', type:'bar', stack:'t', data:{comm}, itemStyle:{{color:'#fb923c'}}}},
        {{name:'空闲', type:'bar', stack:'t', data:{free}, itemStyle:{{color:'#64748b'}}}}
      ]}});
  }}
  // 容器位于折叠 details 内时不能在加载即初始化（零尺寸画布会得到空白图），
  // 必须等 section 首次展开、布局完成后再建图
  var host = el.closest('details');
  if (!host || host.open) build();
  else host.addEventListener('toggle', function once(ev){{
    if (!host.open) return;
    host.removeEventListener('toggle', once);
    requestAnimationFrame(build);
  }});
}})();
