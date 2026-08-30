import { useEffect, useRef } from "react";
import * as echarts from "echarts";

// 统计图表配色，取自项目暖米色设计基调
export const CHART_COLORS = {
  text: "#6e6d68",
  axis: "#d8d3c8",
  primary: "#c65f3d",
  series: ["#c65f3d", "#8a9a5b", "#d9a441", "#6b8ba4", "#9a7aa0", "#b0785c"],
};

export function dailySeriesOption(daily, labels) {
  const dates = daily.map((row) => row.date);
  return {
    color: CHART_COLORS.series,
    tooltip: { trigger: "axis" },
    legend: { bottom: 0, textStyle: { color: CHART_COLORS.text } },
    grid: { left: 8, right: 16, top: 16, bottom: 36, containLabel: true },
    xAxis: {
      type: "category",
      data: dates,
      axisLabel: { color: CHART_COLORS.text },
      axisLine: { lineStyle: { color: CHART_COLORS.axis } },
    },
    yAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: { color: CHART_COLORS.text },
      splitLine: { lineStyle: { color: CHART_COLORS.axis, type: "dashed" } },
    },
    series: labels.map((label, index) => ({
      name: label.name,
      type: label.type || "line",
      smooth: true,
      data: daily.map((row) => row[label.key] ?? 0),
      barMaxWidth: 24,
    })),
  };
}

export function pieOption(items, { nameKey = "label", valueKey = "tasks" } = {}) {
  return {
    color: CHART_COLORS.series,
    tooltip: { trigger: "item" },
    legend: { bottom: 0, textStyle: { color: CHART_COLORS.text } },
    series: [
      {
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "44%"],
        itemStyle: { borderRadius: 6, borderColor: "#faf7f0", borderWidth: 2 },
        label: { color: CHART_COLORS.text },
        data: items.map((row) => ({ name: row[nameKey], value: row[valueKey] })),
      },
    ],
  };
}

export function barOption(items, { nameKey, series }) {
  return {
    color: CHART_COLORS.series,
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
    legend: { bottom: 0, textStyle: { color: CHART_COLORS.text } },
    grid: { left: 8, right: 24, top: 16, bottom: 36, containLabel: true },
    xAxis: {
      type: "value",
      minInterval: 1,
      axisLabel: { color: CHART_COLORS.text },
      splitLine: { lineStyle: { color: CHART_COLORS.axis, type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: items.map((row) => row[nameKey]),
      inverse: true,
      axisLabel: { color: CHART_COLORS.text },
      axisLine: { lineStyle: { color: CHART_COLORS.axis } },
    },
    series: series.map((item) => ({
      name: item.name,
      type: "bar",
      barMaxWidth: 16,
      data: items.map((row) => row[item.key] ?? 0),
    })),
  };
}

export default function EChart({ option, height = 260, style }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) return undefined;
    chartRef.current = echarts.init(containerRef.current);
    const handleResize = () => chartRef.current?.resize();
    window.addEventListener("resize", handleResize);
    const observer = new ResizeObserver(handleResize);
    observer.observe(containerRef.current);
    return () => {
      window.removeEventListener("resize", handleResize);
      observer.disconnect();
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (chartRef.current && option) {
      chartRef.current.setOption(option, true);
    }
  }, [option]);

  return <div ref={containerRef} style={{ width: "100%", height, ...style }} />;
}
