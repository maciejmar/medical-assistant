import { Chart, ChartArea, ScriptableContext } from 'chart.js';

/**
 * Paleta kategorialna wykresów – kolejność stała (kolor przypisany do serii, nie do pozycji).
 * Zweryfikowana walidatorem palet (jasność, nasycenie, rozróżnialność przy daltonizmie).
 * Bursztyn (slot 3) ma niski kontrast z tłem – wykresy z nim mają legendę i podpowiedzi.
 */
export const SERIES = ['#0d9488', '#4f7cff', '#f59e0b', '#e4572e', '#8b5cf6', '#db2777'] as const;

export const SURFACE = '#ffffff';
const GRID = '#eef1f4';
const AXIS_TEXT = '#64748b';

/** Trzeci, ciepły kolor gradientów – brąz, do którego przechodzi koniec każdej serii. */
export const ACCENT_BROWN = '#a0612f';

function rgb(hex: string): [number, number, number] {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

/** Mieszanka dwóch kolorów: amount = udział koloru `to` (0–1). */
export function mix(from: string, to: string, amount: number): string {
  const a = rgb(from);
  const b = rgb(to);
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * amount));
  return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

/** Kolor rozjaśniony w stronę bieli (0–1). */
export const tint = (hex: string, amount: number) => mix(hex, '#ffffff', amount);

/** Kolor przyciemniony w stronę czerni (0–1). */
export const shade = (hex: string, amount: number) => mix(hex, '#000000', amount);

/** Trzy barwy: ciemniejszy odcień serii → kolor serii → brąz. Koniec to brąz zmieszany z kolorem
 *  serii (nie czysty), żeby serie nie zlewały się ze sobą na końcach słupków. */
function threeStops(g: CanvasGradient, color: string): CanvasGradient {
  g.addColorStop(0, shade(color, 0.3));
  g.addColorStop(0.45, color);
  g.addColorStop(1, mix(color, ACCENT_BROWN, 0.85));
  return g;
}

/** Najwyższa wartość na wykresie (dla słupków skumulowanych – suma segmentów). */
function peakValue(chart: Chart): number {
  const datasets = chart.data.datasets;
  const length = Math.max(0, ...datasets.map((d) => d.data.length));
  let peak = 0;
  for (let i = 0; i < length; i++) {
    const values = datasets.map((d) => Number(d.data[i] ?? 0));
    const stacked = datasets.length > 1;
    peak = Math.max(peak, stacked ? values.reduce((a, b) => a + b, 0) : Math.max(...values));
  }
  return peak;
}

/** Wypełnienie słupków: gradient od osi do NAJWYŻSZEJ wartości na wykresie (nie do końca osi) –
 *  najdłuższy słupek pokazuje pełne przejście do brązu, krótkie zachowują nasycony kolor serii. */
export function barFill(color: string, direction: 'up' | 'right' = 'up') {
  return (ctx: ScriptableContext<'bar'>) => {
    const { chart } = ctx;
    const area = chart.chartArea;
    const scale = chart.scales[direction === 'up' ? 'y' : 'x'];
    if (!area || !scale) {
      return color;
    }
    const start = scale.getPixelForValue(0);
    const end = scale.getPixelForValue(peakValue(chart) || 1);
    const g =
      direction === 'up'
        ? chart.ctx.createLinearGradient(0, start, 0, Math.min(end, start - 1))
        : chart.ctx.createLinearGradient(start, 0, Math.max(end, start + 1), 0);
    return threeStops(g, color);
  };
}

function diagonal(chart: Chart, area: ChartArea, color: string): CanvasGradient {
  return threeStops(
    chart.ctx.createLinearGradient(area.left, area.top, area.right, area.bottom),
    color,
  );
}

/** Wypełnienie wycinka pierścienia: gradient w kolorze danego wycinka. */
export function arcFill(colors: readonly string[]) {
  return (ctx: ScriptableContext<'doughnut'>) => {
    const color = colors[ctx.dataIndex] ?? colors[colors.length - 1];
    const area = ctx.chart.chartArea;
    return area ? diagonal(ctx.chart, area, color) : color;
  };
}

const compact = new Intl.NumberFormat('pl-PL', { notation: 'compact', maximumFractionDigits: 1 });
const full = new Intl.NumberFormat('pl-PL');

export const formatCompact = (value: number | string) => compact.format(Number(value));
export const formatFull = (value: number | null) => full.format(value ?? 0);

/** Stonowane osie i siatka (1 px, ciągła) – dane są jedynym wyrazistym elementem. */
export function valueAxis(stacked = false) {
  return {
    stacked,
    beginAtZero: true,
    border: { display: false },
    grid: { color: GRID, lineWidth: 1 },
    ticks: { color: AXIS_TEXT, callback: formatCompact },
  };
}

export function categoryAxis(stacked = false) {
  return {
    stacked,
    border: { color: GRID },
    grid: { display: false },
    ticks: { color: AXIS_TEXT },
  };
}

export const LEGEND = {
  position: 'bottom' as const,
  labels: { usePointStyle: true, pointStyle: 'circle' as const, boxWidth: 8, color: AXIS_TEXT, padding: 16 },
};

export const TOOLTIP = {
  backgroundColor: '#0f172a',
  padding: 10,
  cornerRadius: 8,
  usePointStyle: true,
};
