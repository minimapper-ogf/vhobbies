(function () {
  const $ = id => document.getElementById(id);
  let requestId = 0;
  async function load() {
    const id = ++requestId;
    const mode = $('mode').value;
    const style = $('ctype').value;
    $('rangeBox').hidden = $('rangeHelp').hidden = mode !== 'time';
    const p = new URLSearchParams({name: DRV.name, mode, metric: $('metric').value,
      type: $('type').value, years: mode === 'time' ? $('range').value : 'all'});
    const d = await (await fetch(DRV.chartUrl + '?' + p)).json();
    if (id !== requestId) return;
    Highcharts.chart('chart', {
      chart: {type: style, zooming: {type: mode === 'time' ? 'x' : undefined}, height: 460, borderRadius: 0, animation: false},
      title: {text: null}, credits: {enabled: false},
      xAxis: {categories: d.categories, plotLines: (d.plotLines || []).map(l => ({value: l.value, color: '#c0392b', width: 2, dashStyle: 'Dash', zIndex: 4,
              label: {text: l.text, rotation: 90, textAlign: 'left', style: {color: '#c0392b', fontSize: '11px'}}}))},
      yAxis: {title: {text: d.yTitle}, reversed: d.reversed, allowDecimals: !d.integer},
      tooltip: {shared: true, crosshairs: true, valueDecimals: d.integer ? 0 : 3},
      plotOptions: {series: {connectNulls: true, animation: false}},
      legend: {enabled: d.series.length > 1},
      series: d.series
    });
  }
  ['mode', 'metric', 'type', 'range', 'ctype'].forEach(i => $(i).addEventListener('change', load));
  load();
})();
