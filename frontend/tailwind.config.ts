import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "var(--on1y-bg)",
        foreground: "var(--on1y-fg)",
        surface: "var(--on1y-surface)",
        border: "var(--on1y-border)",
        panel: "var(--on1y-panel)",
        soft: "var(--on1y-soft)",
        inverse: {
          DEFAULT: "var(--on1y-inverse-bg)",
          foreground: "var(--on1y-inverse-fg)"
        },
        glass: "var(--on1y-glass)",
        accent: {
          DEFAULT: "var(--on1y-accent)",
          foreground: "var(--on1y-accent-fg)",
          soft: "var(--on1y-accent-soft)",
          hover: "var(--on1y-accent-hover)"
        },
        muted: "var(--on1y-muted)",
        highlight: "var(--on1y-highlight)",
        progress: "var(--on1y-progress)"
      },
      boxShadow: {
        on1y: "0 8px 32px var(--on1y-shadow)"
      }
    }
  },
  plugins: []
};

export default config;
