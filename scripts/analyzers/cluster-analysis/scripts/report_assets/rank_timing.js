(() => {
  const root = document.currentScript.parentElement;
  const control = name => root.querySelector(`[data-rts="${name}"]`);
  const canvas = root.querySelector('canvas');
  const ctx = canvas.getContext('2d');
  const source = root.querySelector('[data-rank-timing]');
  const {ranks, steps} = JSON.parse(source.textContent);
  source.remove();

  const metrics = [
    ['总耗时', '#93c5fd'], ['总通信', '#fbbf24'], ['总 Free', '#94a3b8'],
    ['通算重合', '#c4b5fd'], ['纯通信', '#fb923c'], ['纯计算', '#5eead4'],
  ];
  const dashes = [[], [7, 4], [2, 4], [10, 3, 2, 3], [12, 6], [5, 3, 2, 3]];
  const number = new Intl.NumberFormat('zh-CN', {maximumFractionDigits: 6});
  const sort = control('sort');
  const direction = control('direction');
  const zoom = control('zoom');
  const pan = control('pan');
  const cursor = control('cursor');
  const tip = control('tip');
  const bounds = {left: 67, right: 0, top: 28, bottom: 0};
  const rankIndexes = new Map(ranks.map((rank, i) => [rank, i]));
  let selectedSteps, series, order, count, start, floor, peak;
  let hoverPosition = null;
  let pendingDraw = 0;

  function checkbox(container, name, checked, color, dash) {
    const label = document.createElement('label');
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = checked;
    const swatch = document.createElement('span');
    swatch.className = 'rt-swatch';
    swatch.style.borderColor = color;
    if (dash.length) swatch.style.borderTopStyle = dash[0] === 2 ? 'dotted' : 'dashed';
    label.append(input, swatch, document.createTextNode(name));
    container.append(label);
    return input;
  }

  const stepChecks = steps.map(([step], i) => checkbox(control('step-list'), `Step ${step}`, i === 0,
    '#cbd5e1', dashes[i % dashes.length]));
  const metricChecks = metrics.map(([name, color], i) => {
    if (i < 5) sort.add(new Option(name, i));
    return checkbox(control('metrics'), name, i === 0, color, []);
  });
  const stepRows = new Map();
  const tipValues = metrics.map(([name]) => {
    const label = document.createElement('dt');
    const value = document.createElement('dd');
    label.textContent = name;
    tip.querySelector('dl').append(label, value);
    return value;
  });

  function refreshSelection(resetPan) {
    selectedSteps = stepChecks.flatMap((box, i) => box.checked ? [i] : []);
    const enabledMetrics = metricChecks.flatMap((box, i) => box.checked ? [i] : []);
    control('steps').querySelector('summary').textContent = `选择 Step（已选 ${selectedSteps.length} / ${steps.length}）`;
    for (const step of selectedSteps) {
      if (stepRows.has(step)) continue;
      stepRows.set(step, new Map(steps[step][1].map(row => [row[0], row])));
      steps[step][1] = null;
    }
    series = selectedSteps.flatMap(step => enabledMetrics.map(metric => ({
      step, metric, rows: stepRows.get(step), color: metrics[metric][1], dash: dashes[step % dashes.length],
    })));
    order = ranks.map((_, i) => i);
    const sign = Number(direction.value);
    if (sort.value === 'rank') {
      if (sign < 0) order.reverse();
    } else {
      const column = Number(sort.value) + 1;
      const means = order.map(rank => {
        let sum = 0, samples = 0;
        for (const step of selectedSteps) {
          const value = stepRows.get(step).get(rank)?.[column];
          if (value == null) continue;
          sum += value;
          samples++;
        }
        return samples ? sum / samples : null;
      });
      order.sort((a, b) => {
        if (means[a] === null) return means[b] === null ? a - b : 1;
        if (means[b] === null) return -1;
        return sign * (means[a] - means[b]) || a - b;
      });
    }
    if (resetPan) pan.value = 0;
    control('lookup-status').textContent = '';
    scheduleDraw();
  }

  function plotX(i) {
    return count === 1 ? (bounds.left + bounds.right) / 2
      : bounds.left + (i - start) * (bounds.right - bounds.left) / (count - 1);
  }

  function plotY(value) {
    return bounds.bottom - (value - floor) * (bounds.bottom - bounds.top) / (peak - floor);
  }

  function drawLine(line) {
    const column = line.metric + 1;
    ctx.strokeStyle = ctx.fillStyle = line.color;
    ctx.setLineDash(line.dash);
    ctx.lineWidth = 1.45;
    ctx.beginPath();
    let connected = false;
    let first = -1, last, low, high, pixel;
    let lowValue, highValue;

    // Keep the first, last and extreme raw samples in each pixel column.
    function flush() {
      if (first < 0) return;
      const indices = [first, low, high, last].sort((a, b) => a - b);
      let previous = -1;
      for (const i of indices) {
        if (i === previous) continue;
        const x = plotX(i), y = plotY(line.rows.get(order[i])[column]);
        if (connected) ctx.lineTo(x, y);
        else {
          ctx.moveTo(x, y);
          ctx.fillRect(x - 1, y - 1, 2, 2);
          connected = true;
        }
        previous = i;
      }
      first = -1;
    }

    for (let i = start; i < start + count; i++) {
      const value = line.rows.get(order[i])?.[column];
      if (value == null) {
        flush();
        connected = false;
        continue;
      }
      const nextPixel = Math.floor(plotX(i));
      if (nextPixel !== pixel) flush();
      if (first < 0) {
        first = low = high = i;
        lowValue = highValue = value;
        pixel = nextPixel;
      }
      if (value < lowValue) { low = i; lowValue = value; }
      if (value > highValue) { high = i; highValue = value; }
      last = i;
    }
    flush();
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function draw() {
    pendingDraw = 0;
    const width = canvas.clientWidth, height = canvas.clientHeight;
    if (width <= bounds.left + 25 || !height) return;
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * scale);
    canvas.height = Math.round(height * scale);
    ctx.setTransform(scale, 0, 0, scale, 0, 0);
    bounds.right = width - 22;
    bounds.bottom = height - 42;
    count = Math.min(Number(zoom.value) || ranks.length, ranks.length);
    pan.max = ranks.length - count;
    control('pan-label').hidden = count === ranks.length;
    start = Number(pan.value);
    hideHover();

    let min = 0, max = null;
    for (const {rows, metric} of series) {
      for (let i = start; i < start + count; i++) {
        const value = rows.get(order[i])?.[metric + 1];
        if (value == null) continue;
        if (max === null || value > max) max = value;
        if (value < min) min = value;
      }
    }
    const top = Math.max(0, max ?? 0) || (min === 0 ? 1 : 0);
    const roughStep = (top - min) / 4;
    const unit = Math.pow(10, Math.floor(Math.log10(roughStep)));
    const step = ([1, 2, 2.5, 5, 10].find(n => n * unit >= roughStep) || 10) * unit;
    const lo = Math.floor(min / step), hi = Math.ceil(top / step);
    floor = lo * step;
    peak = hi * step;
    ctx.font = '12px system-ui, sans-serif';
    ctx.fillStyle = '#cbd5e1';
    ctx.fillText('耗时 (ms)', 10, 17);
    ctx.textAlign = 'right';
    for (let i = lo; i <= hi; i++) {
      const y = plotY(i * step);
      ctx.strokeStyle = i ? '#26354a' : '#64748b';
      ctx.beginPath();
      ctx.moveTo(bounds.left, y);
      ctx.lineTo(bounds.right, y);
      ctx.stroke();
      ctx.fillText(number.format(i * step), bounds.left - 8, y + 4);
    }
    ctx.textAlign = 'center';
    const labels = Math.min(count, Math.max(2, Math.floor((bounds.right - bounds.left) / 70)));
    for (let i = 0; i < labels; i++) {
      const pos = start + (labels === 1 ? 0 : Math.round(i * (count - 1) / (labels - 1)));
      ctx.fillText(ranks[order[pos]], plotX(pos), bounds.bottom + 15, 60);
    }
    ctx.fillText('卡号（Rank）', (bounds.left + bounds.right) / 2, height - 6);
    control('status').textContent = !series.length ? '请选择至少一个 Step 和一项耗时指标。'
      : max === null ? '当前范围内没有所选指标的数据。'
      : `第 ${number.format(start + 1)}–${number.format(start + count)} 张，共 ${number.format(ranks.length)} 张卡`
        + (sort.value !== 'rank' && selectedSteps.length > 1 ? ' · 排序使用所选 Step 的同卡均值' : '');
    series.forEach(drawLine);
  }

  function scheduleDraw() {
    if (!pendingDraw) pendingDraw = requestAnimationFrame(draw);
  }

  function hideHover() {
    hoverPosition = null;
    cursor.hidden = tip.hidden = true;
  }

  function showHover(position, pointerY) {
    hideHover();
    const rank = order[position];
    let hit, closest = Infinity;
    for (const line of series) {
      const row = line.rows.get(rank);
      const value = row?.[line.metric + 1];
      if (value == null) continue;
      const distance = pointerY == null ? 0 : Math.abs(plotY(value) - pointerY);
      if (distance >= closest) continue;
      closest = distance;
      hit = {line, row};
    }
    if (!hit) return;
    hoverPosition = position;
    const x = plotX(position);
    cursor.hidden = tip.hidden = false;
    cursor.style.left = `${x}px`;
    cursor.style.top = `${bounds.top}px`;
    cursor.style.height = `${bounds.bottom - bounds.top}px`;
    tip.querySelector('strong').textContent = `Rank ${ranks[rank]} · Step ${steps[hit.line.step][0]}`;
    tipValues.forEach((element, i) => {
      element.textContent = hit.row[i + 1] == null ? '—' : `${number.format(hit.row[i + 1])} ms`;
    });
    const right = x + 14;
    tip.style.left = `${right + tip.offsetWidth <= canvas.clientWidth ? right : Math.max(0, x - tip.offsetWidth - 14)}px`;
    tip.style.top = `${Math.max(4, Math.min((pointerY ?? bounds.top) + 10, canvas.clientHeight - tip.offsetHeight - 4))}px`;
  }

  for (const input of [...stepChecks, sort, direction]) input.addEventListener('change', () => refreshSelection(true));
  for (const input of metricChecks) input.addEventListener('change', () => refreshSelection(false));
  zoom.addEventListener('change', scheduleDraw);
  pan.addEventListener('input', scheduleDraw);
  canvas.addEventListener('pointerleave', hideHover);
  canvas.addEventListener('pointermove', event => {
    if (!count || event.offsetX < bounds.left || event.offsetX > bounds.right
        || event.offsetY < bounds.top || event.offsetY > bounds.bottom) return hideHover();
    const fraction = (event.offsetX - bounds.left) / (bounds.right - bounds.left);
    showHover(start + Math.round(fraction * (count - 1)), event.offsetY);
  });
  canvas.addEventListener('keydown', event => {
    if (!count || !['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const next = hoverPosition === null ? start : hoverPosition + (event.key === 'ArrowRight' ? 1 : -1);
    showHover(Math.max(start, Math.min(start + count - 1, next)));
  });
  control('lookup').addEventListener('submit', event => {
    event.preventDefault();
    const index = rankIndexes.get(control('rank').value.trim());
    if (index === undefined) {
      control('lookup-status').textContent = '未找到该卡号。';
      return;
    }
    const position = order.indexOf(index);
    zoom.value = '20';
    pan.max = Math.max(0, ranks.length - 20);
    pan.value = Math.min(Number(pan.max), Math.max(0, position - 10));
    if (pendingDraw) cancelAnimationFrame(pendingDraw);
    draw();
    showHover(position);
    control('lookup-status').textContent = hoverPosition === null ? '已定位，当前曲线没有该卡的数据。' : '';
  });

  new ResizeObserver(scheduleDraw).observe(canvas);
  refreshSelection(false);
})();
