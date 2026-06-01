import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        border: "#e5e5e5",
        panel: "#fafafa",
        soft: "#f5f5f5",
        accent: "#111111",
        muted: "#737373"
      }
    }
  },
  plugins: []
};

export default config;
