(function () {
  'use strict';

  const root = document.getElementById('core-balance');
  if (!root) return;
  const el = id => document.getElementById('core-' + id);
  const data = JSON.parse(el('data').textContent);
  const isNumber = value => typeof value === 'number' && Number.isFinite(value);
  const fmt = value => isNumber(value) ? value.toFixed(2) : 'N/A';
  const style = el('style'), numa = el('numa'), min = el('min'), max = el('max');
  let rows = data.cpus;

  function node(tag, attrs, text) {
    const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.entries(attrs).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function setupPanel(section) {
    const group = section.dataset.coreGroup;
    const metrics = data.metrics.filter(metric => metric.group === group);
    const selected = new Set(metrics.map(metric => metric.key));
    const dynamic = section.querySelector('.core-dynamic');
    const buttons = dynamic.querySelector('.core-metrics');
    const stats = dynamic.querySelector('.core-stats');
    const plot = dynamic.querySelector('.core-chart-scroll');
    const tooltip = dynamic.querySelector('.core-tooltip');
    for (const metric of metrics) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'metric-toggle';
      button.textContent = metric.label;
      button.dataset.metric = metric.key;
      button.style.borderColor = metric.color;
      button.setAttribute('aria-pressed', 'true');
      button.addEventListener('click', () => {
        if (selected.has(metric.key)) selected.delete(metric.key);
        else selected.add(metric.key);
        button.setAttribute('aria-pressed', String(selected.has(metric.key)));
        draw();
      });
      buttons.appendChild(button);
    }

    function draw() {
      const active = metrics.filter(metric => selected.has(metric.key));
      const series = active.map(metric => ({
        metric,
        known: rows.map((row, i) => ({v: row[metric.key], i})).filter(point => isNumber(point.v)),
      }));
      stats.replaceChildren();
      plot.replaceChildren();
      tooltip.textContent = '';
      const largestValue = series.reduce((largest, {known}) =>
        known.reduce((value, point) => Math.max(value, point.v), largest), -Infinity);
      if (largestValue === -Infinity) {
        const message = document.createElement('p');
        message.className = 'core-summary';
        message.textContent = !rows.length ? '筛选范围内无 CPU'
          : !active.length ? '请选择至少一个指标' : '该组缺少可用数据（N/A）';
        plot.appendChild(message);
        return;
      }

      const unit = active[0].unit;
      const svg = node('svg', {
        viewBox: '0 0 1080 330', role: 'img',
        'aria-labelledby': section.getAttribute('aria-labelledby'),
        'data-cpu-count': rows.length, 'data-chart-style': style.value,
      });
      plot.appendChild(svg);
      tooltip.textContent = '悬停或键盘聚焦图中 CPU 查看数值。橙色圆点标记 CPU 利用率 ≥ ' + data.hot_threshold + '% 的核心。';

      const x0 = 65, y0 = 32, w = 980, h = 245, step = w / rows.length;
      const ymax = group === 'time' ? 100 : Math.max(1, largestValue) * 1.15;
      const Y = value => y0 + h * (1 - value / ymax);
      const X = i => x0 + (i + .5) * step;
      let band = 0;
      rows.forEach((row, i) => {
        if (i > 0 && row.numa !== rows[i - 1].numa) band++;
        svg.appendChild(node('rect', {
          x: x0 + i * step, y: y0, width: step + .2, height: h,
          fill: band % 2 ? '#192534' : '#111b27', opacity: '.6',
        }));
      });
      for (let i = 0; i <= 4; i++) {
        const v = ymax * i / 4, y = Y(v);
        svg.appendChild(node('line', {x1: x0, x2: x0 + w, y1: y, y2: y, stroke: '#354151'}));
        svg.appendChild(node('text', {x: 3, y: y + 4, fill: '#9eaec2', 'font-size': 11}, v.toFixed(group === 'time' ? 0 : 1)));
      }
      svg.appendChild(node('text', {x: 8, y: 17, fill: '#a6b4c7', 'font-size': 12}, unit));

      const barWidth = step * .8 / series.length;
      series.forEach(({metric, known}, mi) => {
        const {label, color} = metric;
        const stat = document.createElement('span');
        stat.style.color = color;
        stats.appendChild(stat);
        if (!known.length) {
          stat.textContent = label + ' · N/A';
          return;
        }

        if (style.value === 'bar') {
          known.forEach(({v, i}) => svg.appendChild(node('rect', {
            x: x0 + i * step + step * .1 + mi * barWidth, y: Y(v),
            width: barWidth, height: Math.max(0, y0 + h - Y(v)), fill: color, opacity: .85,
          })));
        } else {
          let segment = [];
          function flush() {
            if (segment.length === 1) {
              const [{v, i}] = segment;
              svg.appendChild(node('circle', {cx: X(i), cy: Y(v), r: 2.2, fill: color}));
            } else if (segment.length > 1) {
              svg.appendChild(node('polyline', {
                points: segment.map(({v, i}) => X(i) + ',' + Y(v)).join(' '),
                fill: 'none', stroke: color, 'stroke-width': 1.8,
              }));
            }
            segment = [];
          }
          known.forEach(point => {
            if (segment.length && point.i !== segment[segment.length - 1].i + 1) flush();
            segment.push(point);
          });
          flush();
        }
        known.forEach(({v, i}) => {
          if (rows[i].util >= data.hot_threshold) {
            svg.appendChild(node('circle', {cx: X(i), cy: Y(v), r: 2.6, fill: '#ff956e', 'data-hot-cpu': rows[i].cpu}));
          }
        });
        const avg = known.reduce((sum, point) => sum + point.v, 0) / known.length;
        const smallest = known.reduce((a, b) => a.v <= b.v ? a : b);
        const largest = known.reduce((a, b) => a.v >= b.v ? a : b);
        svg.appendChild(node('line', {
          x1: x0, x2: x0 + w, y1: Y(avg), y2: Y(avg), stroke: color, 'stroke-dasharray': '4 5', opacity: .7,
        }));
        [smallest, largest].forEach(({v, i}) => svg.appendChild(node('circle', {
          cx: X(i), cy: Y(v), r: 3.5, fill: 'none', stroke: color,
        })));
        stat.textContent = label + ' · 均值 ' + fmt(avg) + ' · 最小 ' + fmt(smallest.v) + ' · 最大 ' + fmt(largest.v);
      });

      rows.forEach((row, i) => {
        const text = 'CPU ' + row.cpu + ' · NUMA ' + (row.numa === null ? '未知' : row.numa)
          + ' · 观测 ' + fmt(row.observed_sec) + ' 秒\n'
          + active.map(metric => metric.label + ': ' + fmt(row[metric.key]) + ' ' + unit).join(' | ');
        const hit = node('rect', {
          x: x0 + i * step, y: y0, width: step, height: h, fill: 'transparent',
          tabindex: 0, 'aria-label': text, 'data-cpu': row.cpu,
        });
        hit.appendChild(node('title', {}, text));
        hit.addEventListener('mouseenter', () => { tooltip.textContent = text; });
        hit.addEventListener('focus', () => { tooltip.textContent = text; });
        svg.appendChild(hit);
        if (i % Math.max(1, Math.floor(rows.length / 16)) === 0 || i === rows.length - 1) {
          svg.appendChild(node('text', {x: X(i), y: 297, fill: '#a6b4c7', 'font-size': 10, 'text-anchor': 'middle'}, row.cpu));
        }
      });
      svg.appendChild(node('text', {x: 550, y: 322, fill: '#a6b4c7', 'font-size': 12, 'text-anchor': 'middle'},
        'CPU 编号 · 背景按 NUMA 分组 · 虚线为所选 CPU 的指标均值'));
    }

    return draw;
  }

  const sections = [...root.querySelectorAll('[data-core-group]')];
  const drawPanels = sections.map(setupPanel);
  function drawAll() {
    const first = min.value === '' ? -Infinity : Number(min.value);
    const last = max.value === '' ? Infinity : Number(max.value);
    rows = data.cpus.filter(row =>
      (numa.value === 'all' || String(row.numa) === numa.value) && row.cpu >= first && row.cpu <= last);
    el('summary').textContent = '显示 ' + rows.length + ' / ' + data.cpus.length + ' CPU · ' + data.note;
    drawPanels.forEach(draw => draw());
  }

  numa.addEventListener('change', () => {
    style.value = numa.value === 'all' ? 'line' : 'bar';
    drawAll();
  });
  style.addEventListener('change', drawAll);
  [min, max].forEach(input => input.addEventListener('input', drawAll));
  el('reset').addEventListener('click', () => {
    numa.value = 'all';
    min.value = '';
    max.value = '';
    style.value = 'line';
    drawAll();
  });
  drawAll();
  for (const section of sections) {
    section.querySelector('.core-static').hidden = true;
    section.querySelector('.core-dynamic').hidden = false;
  }
  root.querySelector('.core-controls').hidden = false;
})();
