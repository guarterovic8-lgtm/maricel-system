(() => {
  "use strict";
  const SVG_NS = "http://www.w3.org/2000/svg";

  const el = (name, attrs = {}) => {
    const node = document.createElementNS(SVG_NS, name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };

  const niceStep = (max, ticks) => {
    const raw = max / ticks;
    const power = 10 ** Math.floor(Math.log10(raw));
    const fraction = raw / power;
    const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
    return nice * power;
  };

  const money = (value, prefix) =>
    `${prefix}${Number(value).toLocaleString("en-PH", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const tickFormatter = (maxTick, prefix) => {
    if (maxTick >= 10000) {
      return (value) => {
        if (value === 0) return `${prefix}0`;
        if (value >= 1e6) return `${prefix}${+(value / 1e6).toFixed(1)}M`;
        return `${prefix}${+(value / 1e3).toFixed(value % 1000 === 0 ? 0 : 1)}K`;
      };
    }
    return (value) => `${prefix}${Math.round(value).toLocaleString("en-PH")}`;
  };

  // Column with a 4px rounded data-end and a square baseline.
  const columnPath = (x, y, width, height) => {
    const r = Math.min(4, width / 2, height);
    return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
  };

  const render = (container, data) => {
    const prefix = container.dataset.prefix || "";
    container.querySelectorAll("svg, .chart-tooltip").forEach((node) => node.remove());
    const width = container.clientWidth;
    const height = container.clientHeight;
    if (!width || !height || !data.length) return;

    const maxValue = Math.max(...data.map((d) => d.value), 0);
    const step = niceStep(maxValue || 1, 4);
    const maxTick = Math.max(step * Math.ceil((maxValue || 1) / step), step);
    const format = tickFormatter(maxTick, prefix);
    const tickLabelWidth = Math.max(...[0, maxTick / 2, maxTick].map((v) => format(v).length)) * 6.6 + 10;
    const margin = { top: 22, right: 6, bottom: 28, left: Math.max(40, tickLabelWidth) };
    const plotW = width - margin.left - margin.right;
    const plotH = height - margin.top - margin.bottom;
    const band = plotW / data.length;
    const barW = Math.max(4, Math.min(24, band * 0.62));
    const y = (value) => margin.top + plotH - (value / maxTick) * plotH;

    const svg = el("svg", { viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true", focusable: "false" });
    for (let tick = 0; tick <= maxTick + step / 2; tick += step) {
      const ty = Math.round(y(tick)) + 0.5;
      svg.append(el("line", { class: tick === 0 ? "baseline" : "grid-line", x1: margin.left, x2: width - margin.right, y1: ty, y2: ty }));
      const label = el("text", { class: "axis-label", x: margin.left - 8, y: ty + 4, "text-anchor": "end" });
      label.textContent = format(tick);
      svg.append(label);
    }

    const labelEvery = Math.max(1, Math.ceil(46 / band));
    const maxIndex = data.reduce((best, d, i) => (d.value > data[best].value ? i : best), 0);
    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip";
    tooltip.hidden = true;
    const tipValue = document.createElement("strong");
    const tipLabel = document.createElement("span");
    tooltip.append(tipValue, tipLabel);

    data.forEach((point, index) => {
      const cx = margin.left + band * index + band / 2;
      const group = el("g");
      const hit = el("rect", {
        class: "hit",
        x: margin.left + band * index,
        y: margin.top,
        width: band,
        height: plotH,
        tabindex: "0",
        role: "img",
        "aria-label": `${point.weekday || ""} ${point.label}: ${money(point.value, prefix)}, ${point.count} sales`,
      });
      const barH = point.value > 0 ? Math.max(2, (point.value / maxTick) * plotH) : 0;
      const bar = el("path", {
        class: point.value > 0 ? "bar" : "bar is-zero",
        d: point.value > 0 ? columnPath(cx - barW / 2, margin.top + plotH - barH, barW, barH) : "",
      });
      group.append(hit, bar);

      if (index % labelEvery === 0 || index === data.length - 1) {
        const xLabel = el("text", { class: "axis-label", x: cx, y: height - 8, "text-anchor": "middle" });
        xLabel.textContent = data.length > 10 ? point.short : point.label;
        if (data.length > 10 && (index === 0 || point.short === "01")) xLabel.textContent = point.label;
        group.append(xLabel);
      }
      if (index === maxIndex && point.value > 0) {
        const valueLabel = el("text", { class: "value-label", x: cx, y: margin.top + plotH - barH - 7, "text-anchor": "middle" });
        valueLabel.textContent = format(point.value).replace(/\.0K$/, "K");
        if (maxTick < 10000) valueLabel.textContent = money(point.value, prefix).replace(/\.00$/, "");
        group.append(valueLabel);
      }

      const show = () => {
        bar.classList.add("is-active");
        tipValue.textContent = money(point.value, prefix);
        tipLabel.textContent = `${point.weekday ? `${point.weekday}, ` : ""}${point.label} · ${point.count} sale${point.count === 1 ? "" : "s"}`;
        tooltip.hidden = false;
        const top = margin.top + plotH - barH;
        const left = Math.min(Math.max(cx, 70), width - 70);
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${Math.max(top, 40)}px`;
      };
      const hide = () => { bar.classList.remove("is-active"); tooltip.hidden = true; };
      hit.addEventListener("pointerenter", show);
      hit.addEventListener("pointerleave", hide);
      hit.addEventListener("focus", show);
      hit.addEventListener("blur", hide);
      svg.append(group);
    });

    container.append(svg, tooltip);
  };

  document.querySelectorAll("[data-chart='columns']").forEach((container) => {
    const source = container.querySelector("script[type='application/json']");
    if (!source) return;
    const data = JSON.parse(source.textContent);
    let frame = null;
    const draw = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(() => render(container, data)); };
    draw();
    if ("ResizeObserver" in window) new ResizeObserver(draw).observe(container);
    else window.addEventListener("resize", draw);
  });
})();
