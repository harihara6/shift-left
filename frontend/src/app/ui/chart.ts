import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { ChartSpec } from '../core/models';

interface Geometry {
  grid: { y: number; ty: number; label: string }[];
  bars: { x: number; y: number; w: number; h: number; fill: string; title: string }[];
  lines: { points: string; stroke: string }[];
  dots: { cx: number; cy: number; fill: string; title: string }[];
  xlabels: { x: number; y: number; label: string }[];
}

const FRAME = { W: 640, H: 220, padL: 46, padR: 8, padT: 12, padB: 34 };

const round = (n: number) => Math.round(n * 10) / 10;

/** Rounds an axis maximum up to a readable step, so gridline labels are not noise. */
function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = Math.pow(10, Math.floor(Math.log10(value)));
  return (Math.ceil((value / magnitude) * 2) / 2) * magnitude;
}

/**
 * One chart component, two modes. Geometry is computed here, outside the template, so the
 * render stays a projection of a spec rather than a place where numbers get decided.
 */
@Component({
  selector: 'sl-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <figure class="chart">
      <figcaption class="sr-only">{{ spec().title }}. {{ spec().caption }}</figcaption>
      <div class="legend">
        @for (series of spec().series; track series.name) {
          <span class="legend-item">
            <span class="swatch" [style.background]="series.color"></span>{{ series.name }}
          </span>
        }
      </div>
      <svg viewBox="0 0 640 220" role="img" [attr.aria-label]="spec().title + '. ' + spec().caption">
        @for (line of geometry().grid; track line.y) {
          <line x1="46" x2="632" [attr.y1]="line.y" [attr.y2]="line.y" stroke="#ECEBE7" stroke-width="1" />
          <text x="40" [attr.y]="line.ty" font-size="10" fill="#9A9CA3" text-anchor="end"
                font-family="JetBrains Mono, monospace">{{ line.label }}</text>
        }
        @for (bar of geometry().bars; track $index) {
          <rect [attr.x]="bar.x" [attr.y]="bar.y" [attr.width]="bar.w" [attr.height]="bar.h" rx="2"
                [attr.fill]="bar.fill"><title>{{ bar.title }}</title></rect>
        }
        @for (line of geometry().lines; track $index) {
          <polyline fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"
                    [attr.points]="line.points" [attr.stroke]="line.stroke" />
        }
        @for (dot of geometry().dots; track $index) {
          <circle [attr.cx]="dot.cx" [attr.cy]="dot.cy" r="2.8" [attr.fill]="dot.fill">
            <title>{{ dot.title }}</title>
          </circle>
        }
        @for (label of geometry().xlabels; track $index) {
          <text [attr.x]="label.x" [attr.y]="label.y" font-size="10" fill="#8A8D95"
                text-anchor="middle">{{ label.label }}</text>
        }
      </svg>
      <!-- Every chart names its source and both axes. -->
      <p class="caption">{{ spec().caption }}</p>
    </figure>
  `,
  styles: [
    `
      .chart { margin: 0; display: flex; flex-direction: column; gap: 10px; }
      .legend { display: flex; gap: 16px; flex-wrap: wrap; font-size: 11px; color: var(--muted); }
      .legend-item { display: inline-flex; align-items: center; gap: 6px; }
      .swatch { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
      svg { width: 100%; height: auto; display: block; overflow: visible; }
      .caption { margin: 0; font-size: 11px; color: var(--faint); line-height: 1.5; }
    `,
  ],
})
export class Chart {
  readonly spec = input.required<ChartSpec>();

  readonly geometry = computed<Geometry>(() => {
    const spec = this.spec();
    const plotW = FRAME.W - FRAME.padL - FRAME.padR;
    const plotH = FRAME.H - FRAME.padT - FRAME.padB;
    const values = spec.series.flatMap((s) => s.data);
    const max = niceMax(Math.max(...values, 0));

    const grid = Array.from({ length: 5 }, (_, i) => {
      const y = round(FRAME.padT + plotH - (plotH * i) / 4);
      return { y, ty: y + 3.5, label: String(Math.round(((max * i) / 4) * 100) / 100) };
    });

    const xLabelY = FRAME.H - FRAME.padB + 18;

    if (spec.kind === 'bar') {
      const groupW = plotW / Math.max(spec.x_labels.length, 1);
      const barW = (groupW * 0.62) / Math.max(spec.series.length, 1);
      const bars: Geometry['bars'] = [];
      spec.x_labels.forEach((category, ci) => {
        const gx = FRAME.padL + groupW * ci;
        spec.series.forEach((series, si) => {
          const value = series.data[ci] ?? 0;
          const height = (value / max) * plotH;
          bars.push({
            x: round(gx + groupW * 0.19 + barW * si),
            y: round(FRAME.padT + plotH - height),
            w: round(Math.max(barW - 3, 2)),
            h: round(Math.max(height, 0)),
            fill: series.color,
            title: `${category} · ${series.name}: ${value}`,
          });
        });
      });
      return {
        grid,
        bars,
        lines: [],
        dots: [],
        xlabels: spec.x_labels.map((label, i) => ({
          x: round(FRAME.padL + groupW * i + groupW / 2),
          y: xLabelY,
          label,
        })),
      };
    }

    const step = spec.x_labels.length > 1 ? plotW / (spec.x_labels.length - 1) : 0;
    const lines: Geometry['lines'] = [];
    const dots: Geometry['dots'] = [];
    for (const series of spec.series) {
      const points = series.data.map((value, i) => ({
        x: round(FRAME.padL + step * i),
        y: round(FRAME.padT + plotH - (value / max) * plotH),
        value,
        label: spec.x_labels[i] ?? '',
      }));
      lines.push({
        points: points.map((p) => `${p.x},${p.y}`).join(' '),
        stroke: series.color,
      });
      for (const point of points) {
        dots.push({
          cx: point.x,
          cy: point.y,
          fill: series.color,
          title: `${point.label} · ${series.name}: ${point.value}`,
        });
      }
    }
    return {
      grid,
      bars: [],
      lines,
      dots,
      xlabels: spec.x_labels.map((label, i) => ({ x: round(FRAME.padL + step * i), y: xLabelY, label })),
    };
  });
}
