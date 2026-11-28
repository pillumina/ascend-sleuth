// 集群级 Step 走势：计算/未掩盖通信/空闲 三部分 + Stage 总耗时/极差
// 单图双形态：「堆积柱状」看 Step 间结构差异，「折线走势」看趋势；指标可勾选。
// 数据由 report_generator 用 {{STEP_TREND_DATA}} 注入（JSON 对象）。
(function () {
  const D = {{STEP_TREND_DATA}};
  const steps = D.steps || [];
  if (!steps.length) return;
  const METRICS = [
    { key: 'comp', name: '计算', color: '#38bdf8', on: true, part: true },
    { key: 'comm', name: '未掩盖通信', color: '#fb923c', on: true, part: true },
    { key: 'free', name: '空闲', color: '#64748b', on: true, part: true },
    { key: 'stage', name: 'Stage 总耗时', color: '#34d399', on: false, part: false },
    { key: 'spread', name: 'Stage 极差', color: '#ef4444', on: false, part: false }
  ].filter(m => Array.isArray(D[m.key]) && D[m.key].length);
  const slowest = D.slowest || [];
  const holder = document.getElementById('chart-step-trend');
  const modeSel = document.getElementById('trend-mode');
  const boxes = Array.prototype.slice.call(document.querySelectorAll('#trend-metrics input[type=checkbox]'));
  if (!holder || !METRICS.length) return;

  function on(key) {
    const b = boxes.find(x => x.value === key);
    return b ? b.checked : true;
  }

  function option() {
    const stackMode = (modeSel ? modeSel.value : 'stack') === 'stack';
    const active = METRICS.filter(m => on(m.key));
    const series = active.map(m => {
      const base = { name: m.name, data: D[m.key], itemStyle: { color: m.color } };
      if (stackMode && m.part) {
        base.type = 'bar'; base.stack = 'part'; base.barMaxWidth = 46;
        base.itemStyle = Object.assign({ borderRadius: [3, 3, 0, 0] }, base.itemStyle);
      } else {
        base.type = 'line'; base.smooth = true; base.symbol = 'circle'; base.symbolSize = 5;
        base.lineStyle = { width: m.part ? 2 : 2.4, type: m.key === 'spread' ? 'dashed' : 'solid' };
      }
      return base;
    });
    return {
      backgroundColor: 'transparent', textStyle: { color: '#e2e8f0' },
      tooltip: Object.assign({
        trigger: 'axis', confine: true,
        axisPointer: { type: stackMode ? 'shadow' : 'line' },
        formatter(ps) {
          const i = ps[0] ? ps[0].dataIndex : 0;
          let h = '<div style="font-weight:700;margin-bottom:4px">Step ' + escapeText(steps[i]) + '</div>';
          ps.forEach(p => { h += p.marker + p.seriesName + '：<b>' + fmt(p.value) + ' ms</b><br>'; });
          if (slowest[i]) h += '<span style="color:#94a3b8">最慢组合：' + escapeText(slowest[i]) + '</span>';
          return h;
        }
      }, window.ECHARTS_TOOLTIP_STYLE),
      legend: { top: 2, textStyle: { color: '#94a3b8', fontSize: 11 }, itemWidth: 12, itemHeight: 8 },
      grid: { left: 62, right: 26, top: 40, bottom: steps.length > 14 ? 60 : 34 },
      xAxis: {
        type: 'category', data: steps, name: 'Step', nameGap: 20, nameTextStyle: { color: '#94a3b8', fontSize: 11 },
        axisLabel: { color: '#94a3b8', fontSize: 11, rotate: steps.length > 16 ? 45 : 0 },
        axisLine: { lineStyle: { color: '#334155' } }, axisTick: { show: false }
      },
      yAxis: {
        type: 'value', name: stackMode ? '组成耗时(ms)' : '耗时(ms)',
        nameTextStyle: { color: '#94a3b8', fontSize: 11 },
        axisLabel: { color: '#94a3b8', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(148,163,184,.14)', type: 'dashed' } }
      },
      series
    };
  }

  function escapeText(value) {
    return String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function fmt(v) { return (typeof v === 'number') ? v.toFixed(2) : v; }

  let chart = null;
  function render() {
    chart = chart || echarts.init(holder);
    chart.setOption(option(), true);
    holder.__chart = chart;
  }
  function refresh() {
    if (chart) { chart.setOption(option(), true); } else { render(); }
  }
  if (modeSel) modeSel.addEventListener('change', refresh);
  boxes.forEach(b => b.addEventListener('change', refresh));

  // 章节折叠时容器不可见，展开后再初始化，避免宽度为 0
  const det = holder.closest('details');
  if (det && !det.open) {
    det.addEventListener('toggle', () => { if (det.open && !chart) render(); }, { once: false });
  } else {
    render();
  }
})();
