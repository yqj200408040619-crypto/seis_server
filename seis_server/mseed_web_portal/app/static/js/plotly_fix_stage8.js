(function(){
  "use strict";

  function findPlots(){
    return Array.from(document.querySelectorAll(".js-plotly-plot"));
  }

  function isWaveformPlot(gd){
    const text = (gd.parentElement ? gd.parentElement.innerText : "") + " " + (document.body ? document.body.innerText : "");
    return /BHZ|BHN|BHE|waveform|history|records=|components=/.test(text);
  }

  function fixLayout(gd){
    if (!window.Plotly || !gd || !gd.layout) return;
    if (!isWaveformPlot(gd)) return;

    const hasBHN = gd.layout.yaxis2 || (gd.data || []).length >= 2;
    const hasBHE = gd.layout.yaxis3 || (gd.data || []).length >= 3;
    const height = hasBHN || hasBHE ? 640 : 420;

    const update = {
      height: height,
      margin: {l: 70, r: 25, t: 45, b: 95},
      showlegend: true,
      legend: {
        orientation: "h",
        x: 0.02,
        y: 1.08,
        xanchor: "left",
        yanchor: "bottom"
      },
      xaxis: {
        domain: [0, 1],
        rangeslider: {visible: true, thickness: 0.08},
        title: {text: "UTC time"}
      }
    };

    if (hasBHN || hasBHE) {
      update.yaxis = {domain: [0.68, 1.0], title: {text: "BHZ"}, automargin: true};
      update.yaxis2 = {domain: [0.34, 0.64], title: {text: "BHN"}, automargin: true};
      update.yaxis3 = {domain: [0.0, 0.30], title: {text: "BHE"}, automargin: true};
      update.xaxis2 = {matches: "x", showticklabels: false, domain: [0,1]};
      update.xaxis3 = {matches: "x", showticklabels: true, domain: [0,1]};
    }

    try {
      window.Plotly.relayout(gd, update).then(() => {
        try { window.Plotly.Plots.resize(gd); } catch(e) {}
      });
    } catch(e) {
      try { window.Plotly.Plots.resize(gd); } catch(_) {}
    }
  }

  function fixAll(){
    if (!window.Plotly) return;
    findPlots().forEach(fixLayout);
  }

  function schedule(){
    clearTimeout(window.__stage8PlotTimer);
    window.__stage8PlotTimer = setTimeout(fixAll, 120);
  }

  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(fixAll, 300);
    setTimeout(fixAll, 900);
    setTimeout(fixAll, 1800);

    const mo = new MutationObserver(schedule);
    mo.observe(document.body, {childList:true, subtree:true});
  });
  window.addEventListener("resize", schedule);

  window.mseedPlotFixStage8 = { fixAll, fixLayout };
})();
