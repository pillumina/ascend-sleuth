// 顶部导航高亮、章节折叠联动、阅读进度、通用 spec 图表初始化
(function () {
  window.ECHARTS_TOOLTIP_STYLE = {
    backgroundColor: 'rgba(15,23,42,.96)', borderColor: '#334155', borderWidth: 1,
    textStyle: { color: '#e2e8f0', fontSize: 12 }, padding: [8, 12], extraCssText:
      'border-radius:8px;box-shadow:0 8px 24px rgba(0,0,0,.4);backdrop-filter:blur(4px)'
  };

  const links = Array.from(document.querySelectorAll('.nav-links a'));
  const sections = links
    .map(a => document.querySelector(a.getAttribute('href')))
    .filter(Boolean);

  function setActive() {
    const y = window.scrollY + 100;
    let cur = 0;
    sections.forEach((s, i) => { if (s.offsetTop <= y) cur = i; });
    links.forEach((a, i) => a.classList.toggle('active', i === cur));
    const bar = document.querySelector('.progress');
    if (bar) {
      const max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (max > 0 ? Math.min(100, window.scrollY / max * 100) : 0) + '%';
    }
  }
  window.addEventListener('scroll', setActive, { passive: true });
  setActive();

  // 点击导航时确保对应 details 展开
  links.forEach(a => a.addEventListener('click', () => {
    const d = document.querySelector(a.getAttribute('href'))?.closest('details.sec');
    if (d) d.open = true;
  }));

  const toggle = document.getElementById('toggle-all');
  if (toggle) {
    const setLabel = () => {
      const all = Array.from(document.querySelectorAll('details.sec'));
      toggle.textContent = all.every(d => !d.open) ? '全部展开' : '全部收起';
    };
    toggle.addEventListener('click', () => {
      const all = Array.from(document.querySelectorAll('details.sec'));
      const open = all.every(d => d.open);
      all.forEach(d => { d.open = !open; });
      setLabel();
    });
    document.querySelectorAll('details.sec').forEach(d => d.addEventListener('toggle', setLabel));
    setLabel();
  }

  // 直接访问 #anchor 时展开对应 details
  if (location.hash) {
    const el = document.querySelector(location.hash);
    if (el) {
      el.closest('details.sec')?.setAttribute('open', '');
      setTimeout(() => el.scrollIntoView(), 0);
    }
  }

  // 折叠时图表尺寸为 0：展开后通知 ECharts 重新计算；同时惰性初始化未渲染的 spec 图表
  document.querySelectorAll('details.sec').forEach(d => d.addEventListener('toggle', () => {
    if (!d.open) return;
    initSpecCharts(d);
    setTimeout(() => window.dispatchEvent(new Event('resize')), 60);
  }));

  function visible(el) {
    const d = el.closest('details');
    return !d || d.open;
  }

  window.initSpecCharts = function (root) {
    const scope = root || document;
    scope.querySelectorAll('div.chart[data-spec]').forEach(el => {
      if (el.__chart || el.dataset.done === '1') return;
      if (!visible(el)) return;                 // 等 details 展开时再渲染
      el.dataset.done = '1';
      let spec;
      try {
        spec = JSON.parse(el.dataset.spec);
      } catch {
        el.textContent = '图表数据格式无法读取。';
        el.style.height = 'auto';
        return;
      }
      function showTable(message) {
        el.innerHTML = '<p class="chart-warn">' + message + '</p>' + window.specFallbackTable(spec);
        el.style.height = 'auto';
      }
      if (typeof echarts === 'undefined') {
        showTable('图表库未加载，以下为对应数据表。');
        return;
      }
      let chart;
      try {
        chart = echarts.init(el);
        chart.setOption(window.renderSpec(spec));
        el.__chart = chart;
      } catch {
        chart?.dispose();
        showTable('图表渲染失败，以下为对应数据表。');
      }
    });
  };
  window.initSpecCharts(document);

  let t = null;
  window.addEventListener('resize', () => {
    clearTimeout(t);
    t = setTimeout(() => {
      document.querySelectorAll('div.chart').forEach(el => {
        if (el.__chart && el.clientWidth > 0) el.__chart.resize();
      });
    }, 160);
  });
})();
