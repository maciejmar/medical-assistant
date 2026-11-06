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

/** Kolor rozjaśniony w stronę bieli (0–1) – jaśniejszy koniec gradientu tej samej barwy. */
export function tint(hex: string, amount: number): string {
  const value = parseInt(hex.slice(1), 16);
  const channel = (shift: number) => {
    const c = (value >> shift) & 0xff;
    return Math.round(c + (255 - c) * amount);
  };
  return `rgb(${channel(16)}, ${channel(8)}, ${channel(0)})`;
}

type Direction = 'up' | 'right' | 'diagonal';

function gradient(chart: Chart, area: ChartArea, color: string, direction: Direction): CanvasGradient {
  const { ctx } = chart;
  const g =
    direction === 'up'
      ? ctx.createLinearGradient(0, area.bottom, 0, area.top)
      : direction === 'right'
        ? ctx.createLinearGradient(area.left, 0, area.right, 0)
        : ctx.createLinearGradient(area.left, area.top, area.right, area.bottom);
  // Pełny kolor przy osi, rozjaśnienie ku końcowi obszaru wykresu – krótkie słupki zachowują
  // nasycony kolor serii (gradient w odwrotną stronę robiłby z nich blade, „mniej ważne” plamy).
  g.addColorStop(0, color);
  g.addColorStop(1, tint(color, 0.4));
  return g;
}

/** Wypełnienie słupków serii: gradient od pełnego koloru przy osi do jaśniejszego końca. */
export function barFill(color: string, direction: 'up' | 'right' = 'up') {
  return (ctx: ScriptableContext<'bar'>) => {
    const area = ctx.chart.chartArea;
    return area ? gradient(ctx.chart, area, color, direction) : color;
  };
}

/** Wypełnienie wycinka pierścienia: gradient w kolorze danego wycinka. */
export function arcFill(colors: readonly string[]) {
  return (ctx: ScriptableContext<'doughnut'>) => {
    const color = colors[ctx.dataIndex] ?? colors[colors.length - 1];
    const area = ctx.chart.chartArea;
    return area ? gradient(ctx.chart, area, color, 'diagonal') : color;
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
