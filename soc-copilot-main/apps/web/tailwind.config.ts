import type { Config } from "tailwindcss";

/**
 * Paleta temática (Práctica 2 · rediseño de color).
 *
 * Cada color se resuelve con una variable CSS (`--c-<tono>-<nivel>`) que
 * cambia según `data-theme` (ver `src/app/globals.css`). El código de los
 * componentes sigue usando clases normales (`text-rose-300`,
 * `bg-emerald-900/40`…) escritas con semántica de "modo oscuro"; en modo
 * claro las variables devuelven el tono equivalente legible sobre blanco
 * (texto 300 → 700, tinte 900 → 100, borde 700 → 300…). Todas las
 * combinaciones de texto usadas cumplen WCAG AA (≥ 4.5:1) en los dos temas.
 */
const SHADES = ["50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950"];

function themed(name: string, shades: string[] = SHADES): Record<string, string> {
  return Object.fromEntries(
    shades.map((s) => [s, `rgb(var(--c-${name}-${s}) / <alpha-value>)`]),
  );
}

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      colors: {
        slate: themed("slate"),
        cyan: themed("cyan"),
        sky: themed("sky"),
        emerald: themed("emerald"),
        amber: themed("amber"),
        orange: themed("orange"),
        rose: themed("rose"),
        violet: themed("violet"),
        ink: themed("ink", ["950", "900", "850", "800", "700", "600"]),
        accent: {
          DEFAULT: "rgb(var(--c-cyan-400) / <alpha-value>)",
          soft: "rgb(var(--c-cyan-700) / <alpha-value>)",
        },
        risk: themed("risk", ["low", "medium", "high", "critical", "unknown"]),
      },
      boxShadow: {
        glow: "0 0 0 1px rgb(var(--c-cyan-400) / .25), 0 8px 30px -12px rgb(var(--c-cyan-400) / .25)",
      },
    },
  },
  plugins: [],
};

export default config;
