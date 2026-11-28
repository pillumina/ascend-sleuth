(function () {
  'use strict';
  var root = document.getElementById('frequency-idle');
  if (!root) return;
  var data = JSON.parse(document.getElementById('frequency-idle-data').textContent);
  var plot = document.getElementById('fi-plot'), legend = document.getElementById('fi-series');
  var numa = document.getElementById('fi-numa'), cpu = document.getElementById('fi-cpu'), policy = document.getElementById('fi-policy');
  var tooltip = document.getElementById('fi-tooltip'), selected = {}, checks = {};
  var start = data.window[0], end = data.window[1], span = end - start || 1;
  var left = 68, right = 925, top = 26, bottom = 267, width = right - left, height = bottom - top;
  var ns = 'http://www.w3.org/2000/svg', visible = [], mhzMax = 1, cursor = start;
  function node(tag, attrs, text) {
    var item = document.createElementNS(ns, tag);
    Object.keys(attrs || {}).forEach(function (key) { item.setAttribute(key, attrs[key]); });
    if (text !== undefined) item.textContent = text;
    return item;
  }
  function defaults() {
    var count = {frequency: 0, idle: 0};
    data.series.forEach(function (series) {
      // Prefer series containing actual measurements; missing-only series stay
      // selectable without filling the initial view with empty curves.
      selected[series.id] = series.points.some(function (point) { return point[1] !== null; }) && count[series.kind] < 2;
      if (selected[series.id]) count[series.kind] += 1;
      if (checks[series.id]) checks[series.id].checked = selected[series.id];
    });
  }
  function cpuMatch(cpus) {
    var text = cpu.value.trim(); if (!text) return true;
    return text.split(',').some(function (part) {
      var match = /^(\d+)(?:-(\d+))?$/.exec(part.trim());
      return match && cpus.some(function (id) { return id >= Number(match[1]) && id <= Number(match[2] || match[1]); });
    });
  }
  function inScope(series) {
    return (numa.value === 'all' || series.numas.indexOf(Number(numa.value)) >= 0) && cpuMatch(series.cpus) && (policy.value === 'all' || series.policy === policy.value);
  }
  data.series.forEach(function (series, index) {
    series.color = 'hsl(' + ((208 + index * 137.508) % 360).toFixed(2) + ',70%,70%)';
    var label = document.createElement('label'), checkbox = document.createElement('input');
    checkbox.type = 'checkbox'; checkbox.dataset.seriesId = series.id; checks[series.id] = checkbox;
    label.style.color = series.color; label.appendChild(checkbox);
    label.appendChild(document.createTextNode(series.label + ' · CPU ' + series.cpus.join(',') + ' · ' + (series.source || 'N/A')));
    checkbox.addEventListener('change', function () { selected[series.id] = checkbox.checked; render(); });
    legend.appendChild(label);
  });
  function valueAt(series, time) {
    if (time > series.end || !series.points.length) return null;
    var value = null;
    for (var i = 0; i < series.points.length; i += 1) {
      if (series.points[i][0] > time) break;
      value = series.points[i][1];
    }
    return value;
  }
  function cpuList(values) {
    var ranges = [], lo = null, hi = null;
    values.slice().sort(function (a,b) { return a-b; }).forEach(function (value) {
      if (hi !== null && value === hi+1) hi = value;
      else { if (lo !== null) ranges.push(lo === hi ? String(lo) : lo+'-'+hi); lo = hi = value; }
    });
    if (lo !== null) ranges.push(lo === hi ? String(lo) : lo+'-'+hi);
    return ranges.join(',') || 'N/A';
  }
  function showAt(time) {
    cursor = Math.max(start, Math.min(end, time));
    var lines = ['时间 ' + (cursor - start).toFixed(3) + ' s（trace ' + cursor.toFixed(6) + '）'];
    visible.forEach(function (series) {
      var value = valueAt(series, cursor);
      lines.push(series.label + ' · CPU ' + cpuList(series.cpus) + ' · NUMA ' + (series.numas.join(',') || 'N/A') + ': ' + (value === null ? 'N/A' : value.toFixed(2) + ' ' + series.unit) + ' · 来源 ' + (series.source || 'N/A') + ' · 可靠性 ' + (series.reliability || 'UNKNOWN'));
    });
    tooltip.textContent = lines.join('\n');
    var line = plot.querySelector('[data-cursor]');
    if (line) { line.setAttribute('x1', left + width * (cursor-start)/span); line.setAttribute('x2', left + width * (cursor-start)/span); }
  }
  function render() {
    visible = data.series.filter(function (series) { return selected[series.id] && inScope(series); });
    mhzMax = Math.max.apply(Math, [1].concat(visible.filter(function (series) { return series.kind === 'frequency'; }).reduce(function (all, series) {
      return all.concat(series.points.filter(function (p) { return p[1] !== null; }).map(function (p) { return p[1]; }));
    }, []))) * 1.1;
    plot.textContent = '';
    var svg = node('svg', {viewBox: '0 0 1000 320', 'aria-label': 'CPU Frequency MHz / Idle Residency % / 时间 s'});
    for (var tick = 0; tick <= 4; tick += 1) {
      var y = bottom - height * tick / 4;
      svg.appendChild(node('line', {x1: left, x2: right, y1: y, y2: y, stroke: '#2d3742'}));
      svg.appendChild(node('text', {x: left-9, y: y+4, 'text-anchor': 'end', fill: '#8b949e', 'font-size': 11}, (mhzMax*tick/4).toFixed(0)));
      svg.appendChild(node('text', {x: right+8, y: y+4, fill: '#8b949e', 'font-size': 11}, (tick*25) + '%'));
      var x = left + width*tick/4;
      svg.appendChild(node('text', {x: x, y: bottom+22, 'text-anchor': 'middle', fill: '#8b949e', 'font-size': 11}, (span*tick/4).toFixed(2)));
    }
    svg.appendChild(node('text', {x: left, y: 15, fill: '#68b8ff', 'font-size': 12}, 'Frequency · MHz（左轴）'));
    svg.appendChild(node('text', {x: right, y: 15, 'text-anchor': 'end', fill: '#62d6a5', 'font-size': 12}, 'Idle Residency · %（右轴）'));
    svg.appendChild(node('text', {x: 500, y: 315, 'text-anchor': 'middle', fill: '#8b949e', 'font-size': 12}, '相对采集起点时间（s）'));
    visible.forEach(function (series) {
      var path = '', active = false, lastY = 0;
      series.points.forEach(function (point) {
        var x = left + width * (Math.min(point[0], series.end)-start)/span;
        if (point[1] === null) {
          if (active) path += ' H' + x.toFixed(2);
          active = false; return;
        }
        var y = bottom - height * point[1] / (series.kind === 'frequency' ? mhzMax : 100);
        if (active) path += ' H' + x.toFixed(2) + ' V' + y.toFixed(2);
        else path += ' M' + x.toFixed(2) + ',' + y.toFixed(2);
        active = true; lastY = y;
      });
      if (active) path += ' H' + (left+width*(series.end-start)/span).toFixed(2);
      svg.appendChild(node('path', {d: path, fill: 'none', stroke: series.color, 'stroke-width': 2, 'stroke-dasharray': series.kind === 'idle' ? '5 3' : '', 'data-series': series.id}));
    });
    svg.appendChild(node('line', {x1: left, x2: left, y1: top, y2: bottom, stroke: '#c9d1d9', 'stroke-dasharray': '3 3', 'data-cursor': ''}));
    if (!visible.length) svg.appendChild(node('text', {x: 500, y: 140, 'text-anchor': 'middle', fill: '#8b949e'}, '当前筛选无选中曲线 / N/A'));
    svg.addEventListener('pointermove', function (event) {
      var rect = svg.getBoundingClientRect(), x = (event.clientX-rect.left)*1000/rect.width;
      showAt(start + (x-left)/width*span);
    });
    plot.appendChild(svg);
    document.getElementById('fi-summary').textContent = '显示 ' + visible.length + ' / ' + data.series.length + ' 条曲线；实线频率MHz，虚线Idle%；缺失值断线。';
    showAt(cursor);
  }
  [numa, policy].forEach(function (el) { el.addEventListener('change', render); });
  cpu.addEventListener('input', render);
  document.getElementById('fi-reset').addEventListener('click', function () { numa.value = policy.value = 'all'; cpu.value = ''; defaults(); render(); });
  plot.addEventListener('keydown', function (event) { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); showAt(cursor + span/100*(event.key === 'ArrowRight' ? 1 : -1)); } });
  defaults(); render();
}());
