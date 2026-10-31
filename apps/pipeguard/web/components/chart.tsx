"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart } from "echarts/charts";
import {
  GridComponent,
  AriaComponent,
  TooltipComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
echarts.use([
  BarChart,
  GridComponent,
  AriaComponent,
  TooltipComponent,
  SVGRenderer,
]);
export default function Chart({
  option,
  label,
  onSelect,
  height = 230,
}: {
  option: EChartsCoreOption;
  label: string;
  onSelect?: (index: number) => void;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const instance = useRef<ReturnType<typeof echarts.init> | null>(null);
  const callback = useRef(onSelect);
  callback.current = onSelect;
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "svg" });
    instance.current = chart;
    chart.on("click", (params) => {
      if (
        params.seriesName !== "Offset" &&
        typeof params.dataIndex === "number"
      )
        callback.current?.(params.dataIndex);
    });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    instance.current?.setOption(
      {
        ...option,
        animation: false,
        aria: { enabled: true, description: label, decal: { show: true } },
      },
      { notMerge: true },
    );
  }, [option, label]);
  return (
    <div
      className="analytics-chart"
      ref={ref}
      style={{ height }}
      aria-label={label}
      role="img"
    />
  );
}
