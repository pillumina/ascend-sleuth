/* At most 100 rendered records per table; complete evidence stays in JSON. */
(function () {
  'use strict';
  document.querySelectorAll('details.data-details').forEach(function (panel) {
    var table = panel.querySelector('table'), input = panel.querySelector('[data-table-search]');
    var select = panel.querySelector('[data-table-sort]'), direction = panel.querySelector('[data-table-direction]');
    if (!table || !input || !select) return;
    var header = table.querySelector('tr'), body = table.tBodies[0];
    if (!body || body === header.parentNode && !table.tHead) {
      body = document.createElement('tbody');
      Array.from(table.querySelectorAll('tr')).slice(1).forEach(function (row) { body.appendChild(row); });
      table.appendChild(body);
    }
    var rows = Array.from(body.rows).filter(function (row) { return row !== header; });
    Array.from(header.cells).forEach(function (cell, index) {
      var option = document.createElement('option'); option.value = index; option.textContent = cell.textContent;
      select.appendChild(option);
    });
    var ascending = true;
    function missing(text) { return !text || /^(N\/A|缺失|未知|不可用|—)/i.test(text); }
    function compare(a, b) {
      var x = a.cells[Number(select.value)].textContent.trim(), y = b.cells[Number(select.value)].textContent.trim();
      if (missing(x) || missing(y)) return missing(x) === missing(y) ? 0 : missing(x) ? 1 : -1;
      var nx = Number(x.replace(/,/g, '').replace(/\s*(%|MHz|ms|s|次\/秒)$/, ''));
      var ny = Number(y.replace(/,/g, '').replace(/\s*(%|MHz|ms|s|次\/秒)$/, ''));
      return (isFinite(nx) && isFinite(ny) ? nx - ny : x.localeCompare(y, 'zh-CN', {numeric: true})) * (ascending ? 1 : -1);
    }
    function update() {
      var query = input.value.toLowerCase().trim(), shown = 0;
      rows.sort(compare).forEach(function (row) {
        row.hidden = query && row.textContent.toLowerCase().indexOf(query) < 0;
        if (!row.hidden) shown += 1;
        body.appendChild(row);
      });
      var total = Number(table.getAttribute('data-total-rows')) || rows.length;
      panel.querySelector('[data-table-count]').textContent = '显示 ' + shown + ' / ' + total + ' 条' + (total > rows.length ? '（搜索当前前100条）' : '');
    }
    input.addEventListener('input', update); select.addEventListener('change', update);
    direction.addEventListener('click', function () { ascending = !ascending; direction.textContent = ascending ? '升序' : '降序'; update(); });
    update();
  });
}());
