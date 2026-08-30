import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "media",
  theme: {
    extend: {
      colors: {
        canvas: "var(--color-canvas)",
        surface: "var(--color-surface)",
        border: "var(--color-border)",
        ink: "var(--color-ink)",
        "ink-muted": "var(--color-ink-muted)",
        clay: "var(--color-clay)",
        "clay-hover": "var(--color-clay-hover)",
        ok: "var(--color-ok)",
        warn: "var(--color-warn)",
        err: "var(--color-err)",
      },
      fontFamily: {
        sans: [
          '"Styrene B"',
          '"Söhne"',
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          '"Segoe UI"',
          "sans-serif",
        ],
        mono: ["ui-monospace", '"SF Mono"', "Menlo", "monospace"],
      },
      borderRadius: {
        lg: "8px",
      },
      boxShadow: {
        subtle: "0 1px 2px rgba(0,0,0,.04)",
      },
    },
  },
  plugins: [],
} satisfies Config;
