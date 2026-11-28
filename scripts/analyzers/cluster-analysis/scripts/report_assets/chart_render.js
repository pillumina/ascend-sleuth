// 通用图表渲染：由 report_generator 输出的 JSON spec 驱动，替代大部分表格。
// 支持 kind: hbar(横向条) / bar(分组柱) / stack(堆积柱) / diverge(双向条) / donut(占比环) / line(折线)
(function () {
    'use strict';
    const PALETTE = ['#38bdf8', '#34d399', '#fb923c', '#a78bfa', '#f472b6', '#22d3ee', '#facc15', '#64748b'];
    const AXIS = {axisLabel: {color: '#94a3b8', fontSize: 11}, axisLine: {lineStyle: {color: '#334155'}}, axisTick: {show: false}};
    const SPLIT = {splitLine: {lineStyle: {color: 'rgba(148,163,184,.14)', type: 'dashed'}}};
    const LABEL = {color: '#94a3b8', fontSize: 11};

    function num(v) { return (typeof v === 'number' && isFinite(v)) ? v.toFixed(2) : (v === null || v === undefined || v === '' ? '-' : String(v)); }

    function trunc(s, n) { s = String(s); return s.length > n ? s.slice(0, n - 1) + '…' : s; }

    function color(spec, i) {
        const s = spec.series[i] || {};
        return s.color || PALETTE[i % PALETTE.length];
    }

    function tooltip(spec, unit) {
        return Object.assign({
            trigger: spec.kind === 'donut' ? 'item' : 'axis',
            confine: true,
            axisPointer: spec.kind === 'bar' || spec.kind === 'stack' ? {type: 'shadow'} : undefined,
            formatter: function (params) {
                const list = Array.isArray(params) ? params : [params];
                if (!list.length) { return ''; }
                const i = spec.kind === 'donut' ? list[0].dataIndex : list[0].dataIndex;
                let html = '<div style="max-width:460px;white-space:normal">';
                if (spec.kind !== 'donut') {
                    html += '<div style="font-weight:600;margin-bottom:4px">' + String(spec.cats[i]).replace(/</g, '&lt;') + '</div>';
                }
                list.forEach(function (p) {
                    const name = spec.kind === 'donut' ? p.name : p.seriesName;
                    html += p.marker + name + '：<b>' + num(p.value) + ' ' + (unit || '') + '</b>';
                    if (spec.kind === 'donut' && p.percent !== undefined) { html += '（' + p.percent + '%）'; }
                    html += '<br/>';
                });
                const notes = spec.notes && spec.notes[i];
                if (notes) { html += '<span style="color:#94a3b8">' + String(notes).replace(/</g, '&lt;') + '</span>'; }
                return html + '</div>';
            }
        }, window.ECHARTS_TOOLTIP_STYLE);
    }

    function catAxis(spec, horizontal, wide) {
        const axis = Object.assign({type: 'category', data: spec.cats.map(function (c) { return trunc(c, wide ? 46 : 16); }), name: spec.catName}, AXIS);
        axis.nameGap = 8;
        axis.nameTextStyle = {color: '#64748b', fontSize: 11};
        if (horizontal) {
            axis.axisLabel = {color: '#cbd5e1', fontSize: 11, width: wide ? 330 : 190, overflow: 'truncate'};
            if (spec.cats.length > 12) { axis.axisLabel.interval = 0; }
        }
        return axis;
    }

    function valAxis(spec, horizontal, unit) {
        return Object.assign({type: 'value', name: spec.valName || (unit ? unit : '')}, AXIS, SPLIT,
            {nameTextStyle: {color: '#64748b', fontSize: 11}, axisLabel: {color: '#94a3b8', fontSize: 11}});
    }

    function barSeries(spec, horizontal, stacked) {
        return spec.series.map(function (s, i) {
            const out = {
                name: s.name, type: 'bar', data: s.data, barMaxWidth: stacked ? 26 : 16,
                itemStyle: {color: color(spec, i), borderRadius: stacked ? 0 : (horizontal ? [0, 3, 3, 0] : [3, 3, 0, 0])},
                emphasis: {itemStyle: {opacity: .92}}
            };
            if (stacked) { out.stack = s.stack || 'total'; }
            return out;
        });
    }

    window.renderSpec = function (spec) {
        const unit = spec.unit || '';
        let opt;
        if (spec.reverse) {   // 横向条形图从下往上绘制，反转后让最大值显示在顶部
            spec = Object.assign({}, spec, {
                cats: spec.cats.slice().reverse(),
                notes: spec.notes ? spec.notes.slice().reverse() : undefined,
                series: spec.series.map(function (s) { return Object.assign({}, s, {data: s.data.slice().reverse()}); })
            });
        }
        if (spec.kind === 'donut') {
            opt = {
                backgroundColor: 'transparent', textStyle: {color: '#cbd5e1'}, tooltip: tooltip(spec, unit),
                legend: {top: 4, textStyle: {color: '#94a3b8', fontSize: 11}, itemWidth: 12, itemHeight: 8},
                series: [{
                    type: 'pie', radius: ['44%', '68%'], center: ['50%', '56%'], avoidLabelOverlap: true,
                    itemStyle: {borderColor: '#1e293b', borderWidth: 2, borderRadius: 4},
                    label: {color: '#cbd5e1', fontSize: 11, formatter: '{b}\n{d}%'},
                    labelLine: {lineStyle: {color: '#475569'}},
                    data: spec.cats.map(function (c, i) {
                        return {name: c, value: (spec.series[0] || {}).data[i], itemStyle: {color: color(spec, i)}};
                    })
                }]
            };
        } else if (spec.kind === 'diverge') {
            const s = spec.series[0] || {};
            opt = {
                backgroundColor: 'transparent', textStyle: {color: '#cbd5e1'}, tooltip: tooltip(spec, unit),
                legend: {show: false},
                grid: {left: 8, right: 60, top: 30, bottom: 26, containLabel: true},
                xAxis: Object.assign({type: 'value', name: spec.valName || unit}, AXIS, SPLIT,
                    {nameTextStyle: {color: '#64748b', fontSize: 11}, splitLine: {lineStyle: {color: 'rgba(148,163,184,.14)', type: 'dashed'}}}),
                yAxis: catAxis(spec, true, true),
                series: [{
                    name: s.name || 'Diff', type: 'bar', data: s.data, barMaxWidth: 15,
                    label: {show: true, position: 'right', color: '#94a3b8', fontSize: 10, formatter: function (p) { return num(p.value); }},
                    itemStyle: {
                        borderRadius: [0, 3, 3, 0],
                        color: function (p) { return p.value >= 0 ? '#ef4444' : '#34d399'; }
                    }
                }]
            };
        } else if (spec.kind === 'line') {
            opt = {
                backgroundColor: 'transparent', textStyle: {color: '#cbd5e1'}, tooltip: tooltip(spec, unit),
                legend: {top: 2, textStyle: LABEL, itemWidth: 12, itemHeight: 8},
                grid: {left: 58, right: 26, top: 38, bottom: 34},
                xAxis: catAxis(spec, false),
                yAxis: valAxis(spec, false, unit),
                series: spec.series.map(function (s, i) {
                    return {
                        name: s.name, type: 'line', data: s.data, smooth: true, symbol: 'circle', symbolSize: 5,
                        lineStyle: {width: 2, type: s.dashed ? 'dashed' : 'solid'}, itemStyle: {color: color(spec, i)}
                    };
                })
            };
        } else if (spec.kind === 'hbar') {
            opt = {
                backgroundColor: 'transparent', textStyle: {color: '#cbd5e1'}, tooltip: tooltip(spec, unit),
                legend: spec.series.length > 1 ? {top: 2, textStyle: LABEL, itemWidth: 12, itemHeight: 8} : {show: false},
                grid: {left: 8, right: 56, top: spec.series.length > 1 ? 36 : 22, bottom: 26, containLabel: true},
                xAxis: valAxis(spec, true, unit),
                yAxis: catAxis(spec, true, !!spec.wide),
                series: barSeries(spec, true, !!spec.stacked).map(function (s) {
                    if (!spec.stacked && spec.series.length === 1) {
                        s.label = {show: true, position: 'right', color: '#94a3b8', fontSize: 10, formatter: function (p) { return num(p.value); }};
                    }
                    return s;
                })
            };
        } else {  // bar / stack
            const stacked = spec.kind === 'stack';
            opt = {
                backgroundColor: 'transparent', textStyle: {color: '#cbd5e1'}, tooltip: tooltip(spec, unit),
                legend: {top: 2, textStyle: LABEL, itemWidth: 12, itemHeight: 8},
                grid: {left: 58, right: 26, top: 38, bottom: 34},
                xAxis: catAxis(spec, false),
                yAxis: valAxis(spec, false, unit),
                series: barSeries(spec, false, stacked)
            };
        }
        return opt;
    };

    // ECharts 缺失时退化为表格，保证信息不丢失。
    window.specFallbackTable = function (spec) {
        const head = ['<th>' + esc(spec.catName || '项') + '</th>']
            .concat(spec.series.map(function (s) { return '<th>' + esc(s.name) + '</th>'; }));
        if (spec.notes) { head.push('<th>备注</th>'); }
        const body = spec.cats.map(function (c, i) {
            const cells = spec.series.map(function (s) { return '<td>' + esc(num(s.data[i])) + '</td>'; });
            if (spec.notes) { cells.push('<td>' + esc(spec.notes[i] || '') + '</td>'); }
            return '<tr><th>' + esc(c) + '</th>' + cells.join('') + '</tr>';
        });
        return '<div class="tw"><table class="tbl"><thead><tr>' + head.join('') + '</tr></thead><tbody>' + body.join('') + '</tbody></table></div>';
    };

    function esc(s) {
        return String(s === undefined || s === null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
})();
