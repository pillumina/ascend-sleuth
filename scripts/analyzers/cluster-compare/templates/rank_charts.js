(() => {
  const payload = JSON.parse(document.getElementById("rank-chart-data").textContent);
  const labels = ["总耗时", "总通信", "总 Free", "通算重合", "纯通信", "纯计算"];
  const stride = labels.length + 1;
  const ranks = payload.ranks;
  const steps = payload.steps.map(([name, a, b], id) => ({name, sides: [a, b], id}));
  const startStep = steps.find(step => step.sides.every(side => side.length)) || steps[0];
  const numberFormat = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 6});
  const format = (value, signed = false) => Number.isFinite(value)
    ? (signed && value > 0 ? "+" : "") + numberFormat.format(value) : "—";
  const stepLabel = step => payload.usesSummary || payload.pairing === "ordinal" ? step.name : "Step " + step.name;
  if (payload.pairingNote) {
    for (const node of document.querySelectorAll('[data-role="pairing-note"]')) {
      node.textContent = payload.pairingNote;
      node.hidden = false;
    }
  }

  function rankOffsets(step) {
    if (!step.offsets) {
      step.offsets = step.sides.map(side => {
        const offsets = new Int32Array(ranks.length);
        for (let i = 0; i < side.length; i += stride) offsets[side[i]] = i + 1;
        return offsets;
      });
    }
    return step.offsets;
  }

  function rawValue(step, side, rank, metric) {
    const offset = rankOffsets(step)[side][rank];
    return offset ? (step.sides[side][offset + metric] ?? NaN) : NaN;
  }

  function difference(a, b, mode) {
    if (mode === "rate") return a === 0 ? NaN : (b - a) / a * 100;
    return b - a;
  }

  // Keep the earliest/latest points and both extremes per screen column.
  // A bucket with missing ranks has isolated points so no line bridges missing measurements.
  function sampleLine(line, order, start, count, pixels) {
    const buckets = Math.min(count, Math.max(1, Math.floor(pixels)));
    const points = [];
    let lowest = Infinity, highest = -Infinity, previousGap = true;
    for (let bucket = 0; bucket < buckets; bucket++) {
      const from = start + Math.floor(bucket * count / buckets);
      const to = start + Math.floor((bucket + 1) * count / buckets);
      let min = Infinity, max = -Infinity, lo, hi, first, last, firstValue, lastValue;
      let gap = false;
      for (let pos = from; pos < to; pos++) {
        const value = line.value(order[pos]);
        if (!Number.isFinite(value)) {
          gap = true;
          continue;
        }
        if (first === undefined) { first = pos; firstValue = value; }
        last = pos; lastValue = value;
        if (value < min) { min = value; lo = pos; }
        if (value > max) { max = value; hi = pos; }
      }
      if (first !== undefined) {
        lowest = Math.min(lowest, min);
        highest = Math.max(highest, max);
        if (first === last) {
          points.push([first, firstValue, previousGap || gap]);
        } else {
          const candidates = [[first, firstValue], [lo, min], [hi, max], [last, lastValue]];
          candidates.sort((a, b) => a[0] - b[0]);
          let previous;
          for (const [pos, value] of candidates) {
            if (pos === previous) continue;
            points.push([pos, value, gap || (previous === undefined && previousGap)]);
            previous = pos;
          }
        }
      }
      previousGap = gap || first === undefined;
    }
    return {points, lowest, highest};
  }

  function mount(panel, isDiff) {
    if (!startStep) {
      const message = document.createElement("p");
      message.className = "rank-note";
      message.textContent = "暂无逐 Rank 耗时数据。";
      panel.append(message);
      return;
    }
    panel.append(document.getElementById("rank-chart-controls").content.cloneNode(true));
    const el = role => panel.querySelector('[data-role="' + role + '"]');
    const canvas = el("canvas"), plot = el("plot"), ctx = canvas.getContext("2d");
    const sort = el("sort"), sortStep = el("sort-step"), source = el("sort-source");
    const direction = el("direction"), mode = el("mode"), pan = el("pan");
    const tooltip = el("tooltip"), cursor = el("cursor"), marker = el("marker"), status = el("status");
    const legend = el("legend");
    const metricCount = labels.length - Number(isDiff);
    const stepChecks = [], metricChecks = [];
    let selectedSteps = [], lines = [], order = [], start = 0, count = 0;
    let geometry, inspected = null, frame;

    if (payload.summaryOnly.length) {
      const note = el("source-note");
      note.hidden = false;
      note.textContent = "集群 " + payload.summaryOnly.join("、") + (payload.usesSummary
        ? " 仅含跨 Step 均值。" : " 缺少逐 Step 的 Rank 明细。");
    }
    if (isDiff) {
      el("mode-label").hidden = false;
      source.value = "difference";
    } else {
      source.remove(2);
    }

    function check(parent, text, checked) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.checked = checked;
      label.append(input, text);
      parent.append(label);
      return input;
    }
    const stepHolder = document.createDocumentFragment();
    // 默认全选 Step（不缩略为单个 Step），用户可按需取消勾选
    for (const step of steps) stepChecks.push(check(stepHolder, stepLabel(step), true));
    el("steps").append(stepHolder);
    for (let metric = 0; metric < metricCount; metric++) {
      metricChecks.push(check(el("metrics"), labels[metric], metric === 0));
    }
    labels.slice(0, 5).forEach((label, metric) => sort.add(new Option(label, metric)));

    function metricValue(step, selection, rank, metric, differenceMode) {
      if (selection === "difference") {
        return difference(rawValue(step, 0, rank, metric), rawValue(step, 1, rank, metric), differenceMode);
      }
      return rawValue(step, selection === "a" ? 0 : 1, rank, metric);
    }

    function update() {
      selectedSteps = steps.filter(step => stepChecks[step.id].checked);
      const oldStep = sortStep.value;
      sortStep.replaceChildren(...selectedSteps.map(step => new Option(stepLabel(step), step.id)));
      if (selectedSteps.some(step => String(step.id) === oldStep)) sortStep.value = oldStep;
      el("step-count").textContent = "已选 " + selectedSteps.length + " / " + steps.length;
      const differenceMode = mode.value;
      const byRank = sort.value === "rank";
      sortStep.disabled = source.disabled = byRank || !selectedSteps.length;
      const included = new Uint8Array(ranks.length);
      for (const step of selectedSteps) {
        for (const side of step.sides) {
          for (let i = 0; i < side.length; i += stride) included[side[i]] = 1;
        }
      }
      order = [];
      for (let rank = 0; rank < ranks.length; rank++) if (included[rank]) order.push(rank);
      const sign = Number(direction.value);
      if (byRank) {
        if (sign < 0) order.reverse();
      } else if (order.length) {
        const step = steps[Number(sortStep.value)];
        const scores = new Float64Array(ranks.length);
        const sortSource = source.value, metric = Number(sort.value);
        for (const rank of order) scores[rank] = metricValue(step, sortSource, rank, metric, differenceMode);
        order.sort((a, b) => {
          const av = scores[a], bv = scores[b];
          const missing = Number(!Number.isFinite(av)) - Number(!Number.isFinite(bv));
          return missing || (av - bv) * sign || a - b;
        });
      }

      lines = [];
      const selections = isDiff ? ["difference"] : ["a", "b"];
      const legendItems = document.createDocumentFragment();
      for (const step of selectedSteps) {
        metricChecks.forEach((checkbox, metric) => {
          if (!checkbox.checked) return;
          const hue = (198 + step.id * 137.508 + metric * 58) % 360;
          const color = "hsl(" + hue + " 86% 69%)";
          const entry = document.createElement("span"), swatch = document.createElement("i");
          swatch.style.color = color;
          entry.append(swatch, stepLabel(step) + " · " + labels[metric]);
          legendItems.append(entry);
          for (const selection of selections) {
            const side = selection === "a" ? 0 : 1;
            if (!isDiff && !step.sides[side].length) continue;
            lines.push({step, metric, color, dashed: selection === "b",
              value: rank => metricValue(step, selection, rank, metric, differenceMode)});
          }
        });
      }
      legend.replaceChildren(legendItems);
      setWindow(0, order.length);
    }

    function hideRank() {
      inspected = null;
      tooltip.hidden = cursor.hidden = marker.hidden = true;
    }

    function setWindow(nextStart, nextCount) {
      count = Math.min(order.length, Math.max(1, nextCount));
      start = Math.max(0, Math.min(nextStart, order.length - count));
      pan.max = order.length - count;
      pan.value = start;
      pan.disabled = count === order.length;
      el("zoom-in").disabled = count < 2;
      el("zoom-out").disabled = el("zoom-reset").disabled = count === order.length;
      status.textContent = count
        ? "当前第 " + (start + 1) + "–" + (start + count) + " 张，共 " + format(order.length) + " 张卡"
          + " · Ctrl + 滚轮缩放 · 可按 Rank 编号定位"
        : "请选择至少一个有数据的 Step。";
      hideRank();
      draw();
    }

    function draw() {
      const width = canvas.clientWidth, height = canvas.clientHeight;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const left = width < 420 ? 60 : 76, right = Math.max(left + 1, width - 20);
      const top = 32, bottom = height - 40, plotWidth = right - left;
      const x = pos => count > 1 ? left + (pos - start) * plotWidth / (count - 1) : (left + right) / 2;
      const sampled = lines.map(line => sampleLine(line, order, start, count, plotWidth));
      let min = Infinity, max = -Infinity;
      for (const line of sampled) {
        min = Math.min(min, line.lowest);
        max = Math.max(max, line.highest);
      }
      geometry = {x, left, right, top, bottom};
      ctx.fillStyle = "#cbd5e1";
      ctx.font = "12px system-ui";
      ctx.textAlign = "left";
      ctx.fillText(isDiff && mode.value === "rate" ? "变化率 (%)" : isDiff ? "差值 (ms)" : "耗时 (ms)", 10, 19);
      if (!Number.isFinite(min)) {
        ctx.textAlign = "center";
        ctx.fillText("当前范围没有可绘制的数值", width / 2, height / 2);
      } else {
        if (isDiff) { min = Math.min(0, min); max = Math.max(0, max); }
        const padding = (max - min || Math.abs(max) || 1) * .05;
        min -= padding;
        max += padding;
        const y = value => bottom - (value - min) / (max - min) * (bottom - top);
        geometry.y = y;
        ctx.textAlign = "right";
        for (let i = 0; i < 5; i++) {
          const value = min + (max - min) * i / 4;
          ctx.strokeStyle = "#28364b";
          ctx.beginPath();
          ctx.moveTo(left, y(value));
          ctx.lineTo(right, y(value));
          ctx.stroke();
          ctx.fillText(format(Number(value.toPrecision(4))), left - 8, y(value) + 4, left - 10);
        }
        if (isDiff) {
          ctx.strokeStyle = "#64748b";
          ctx.beginPath();
          ctx.moveTo(left, y(0));
          ctx.lineTo(right, y(0));
          ctx.stroke();
        }
        sampled.forEach(({points}, index) => {
          const line = lines[index];
          ctx.strokeStyle = ctx.fillStyle = line.color;
          ctx.setLineDash(line.dashed ? [4, 3] : []);
          ctx.lineWidth = 1.3;
          ctx.beginPath();
          points.forEach(([position, value, move], i) => {
            const px = x(position), py = y(value);
            if (!move) ctx.lineTo(px, py);
            else {
              ctx.moveTo(px, py);
              if (!points[i + 1] || points[i + 1][2]) ctx.fillRect(px - 1, py - 1, 3, 3);
            }
          });
          ctx.stroke();
        });
        ctx.lineWidth = 1;
        ctx.setLineDash([]);
      }
      ctx.fillStyle = "#a8b6ca";
      ctx.textAlign = "center";
      const ticks = Math.min(count, Math.max(2, Math.floor(plotWidth / 92)));
      for (let i = 0; i < ticks; i++) {
        const position = start + (ticks === 1 ? 0 : Math.round(i * (count - 1) / (ticks - 1)));
        ctx.fillText(ranks[order[position]], x(position), height - 22, 64);
      }
      ctx.fillText("Rank 编号", (left + right) / 2, height - 5);
    }

    function inspect(position, mouseY) {
      const rank = order[position];
      if (rank === undefined) return;
      const width = canvas.clientWidth, height = canvas.clientHeight;
      const probeX = geometry ? geometry.x(position) : width / 2;
      let nearest = Infinity, selectedLine;
      if (mouseY !== undefined && geometry.y) {
        for (const line of lines) {
          const value = line.value(rank);
          if (!Number.isFinite(value)) continue;
          const distance = Math.abs(geometry.y(value) - mouseY);
          if (distance < nearest) { nearest = distance; selectedLine = line; }
        }
      }
      const step = selectedLine?.step || selectedSteps.find(step =>
        rankOffsets(step).some(offsets => offsets[rank]));
      if (!step) return;
      inspected = position;
      const heading = document.createElement("strong");
      heading.textContent = stepLabel(step) + " · Rank " + ranks[rank];
      const table = document.createElement("table");
      table.innerHTML = "<thead><tr><th>指标</th><th>A (ms)</th><th>B (ms)</th>"
        + (isDiff ? "<th>差值 (ms)</th><th>变化率 (%)</th>" : "") + "</tr></thead><tbody>"
        + labels.map((label, metric) => {
          const a = rawValue(step, 0, rank, metric), b = rawValue(step, 1, rank, metric);
          return "<tr" + (metric === selectedLine?.metric ? " data-active" : "") + "><th>"
            + label + "</th><td>" + format(a) + "</td><td>" + format(b) + "</td>"
            + (isDiff ? "<td>" + format(difference(a, b, "delta"), true) + "</td><td>"
              + format(difference(a, b, "rate"), true) + "</td>" : "") + "</tr>";
        }).join("") + "</tbody>";
      tooltip.replaceChildren(heading, table);
      tooltip.hidden = false;
      cursor.hidden = false;
      cursor.style.left = probeX + "px";
      cursor.style.top = (geometry?.top ?? 32) + "px";
      cursor.style.bottom = "40px";
      marker.hidden = !selectedLine;
      if (selectedLine) {
        marker.style.left = probeX + "px";
        marker.style.top = geometry.y(selectedLine.value(rank)) + "px";
        marker.style.background = selectedLine.color;
      }
      tooltip.style.left = Math.max(4, Math.min(
        probeX + 14 + tooltip.offsetWidth <= width ? probeX + 14 : probeX - tooltip.offsetWidth - 14,
        width - tooltip.offsetWidth - 4)) + "px";
      tooltip.style.top = Math.max(4, Math.min((mouseY ?? 14) + 12, height - tooltip.offsetHeight - 5)) + "px";
    }

    function positionAt(x) {
      return start + Math.round(Math.max(0, Math.min(1,
        (x - geometry.left) / (geometry.right - geometry.left))) * (count - 1));
    }

    function zoom(nextCount, anchor) {
      const ratio = count > 1 ? (anchor - start) / (count - 1) : .5;
      const target = Math.min(order.length, Math.max(1, nextCount));
      setWindow(anchor - Math.round(ratio * (target - 1)), target);
    }

    panel.addEventListener("change", event => { if (event.target !== pan) update(); });
    pan.addEventListener("input", () => setWindow(Number(pan.value), count));
    el("zoom-in").onclick = () => zoom(Math.ceil(count / 2), inspected ?? start + Math.floor(count / 2));
    el("zoom-out").onclick = () => zoom(count * 2, inspected ?? start + Math.floor(count / 2));
    el("zoom-reset").onclick = () => setWindow(0, order.length);
    el("search").addEventListener("submit", event => {
      event.preventDefault();
      const target = el("find").value.trim();
      const position = order.findIndex(rank => ranks[rank] === target);
      if (position < 0) {
        status.textContent = "所选 Step 中没有 Rank " + target + "。";
        return;
      }
      const targetCount = Math.min(count, 80);
      setWindow(position - Math.floor(targetCount / 2), targetCount);
      inspect(position);
    });
    canvas.addEventListener("pointermove", event => {
      if (!geometry || event.offsetX < geometry.left - 2 || event.offsetX > geometry.right + 2
          || event.offsetY < geometry.top || event.offsetY > geometry.bottom) hideRank();
      else inspect(positionAt(event.offsetX), event.offsetY);
    });
    canvas.addEventListener("pointerleave", hideRank);
    canvas.addEventListener("wheel", event => {
      if (!event.ctrlKey || !geometry || !count) return;
      event.preventDefault();
      zoom(event.deltaY < 0 ? Math.ceil(count / 2) : count * 2, positionAt(event.offsetX));
    }, {passive: false});
    canvas.addEventListener("keydown", event => {
      if (!count || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const position = inspected === null ? start
        : Math.max(0, Math.min(order.length - 1, inspected + direction));
      if (position < start) setWindow(position, count);
      if (position >= start + count) setWindow(position - count + 1, count);
      inspect(position);
    });
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => { hideRank(); draw(); });
    }).observe(plot);
    update();
  }

  mount(document.getElementById("rank-timing"), false);
  mount(document.getElementById("rank-difference"), true);
})();
