/** @type {import('tailwindcss').Config} */
const textOverrides = {
  // text-slate-N on a dark page: low numbers are bright, 400-600 are muted, 700+ recede.
  50: "#f7f7fb", 100: "#f3f3f8", 200: "#dcdce8", 300: "#c4c4d4", 400: "#9a9ab2",
  500: "#a1a1b8", 600: "#8b8ba3", 700: "#71718a", 800: "#5c5c74", 900: "#f3f3f8", 950: "#ffffff",
};

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",                       // the UI is dark-only: <html class="dark"> is always set
  theme: {
    extend: {
      colors: {
        // `slate` drives SURFACES and BORDERS (bg-/border-slate-*). Text colours are
        // remapped to light values by the plugin below so text-slate-* stays readable.
        slate: {
          50: "#1a1a26", 100: "#171722", 200: "#16161f", 300: "#1d1d29", 400: "#71718a",
          500: "#a1a1b8", 600: "#b9b9cb", 700: "#2e2e3d", 800: "#23232f", 900: "#101017", 950: "#07070c",
        },
        brand: { DEFAULT: "#d7ff3f", dark: "#bde82a" },          // lime
        pink: { DEFAULT: "#ff2d95", dark: "#e01a80" },
        violet: { DEFAULT: "#a855f7", dark: "#8b3ce0" },
        sky: { DEFAULT: "#38b6ff" },
        orange: { DEFAULT: "#f97316" },
      },
      fontFamily: {
        sans: ['"Inter"', "system-ui", "sans-serif"],
        display: ['"Barlow Condensed"', '"Inter"', "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        glow: "0 10px 30px -12px rgba(215,255,63,.7)",
        "glow-pink": "0 10px 30px -12px rgba(255,45,149,.75)",
        pop: "0 24px 60px -20px rgba(0,0,0,.85)",
        card: "0 1px 0 0 rgba(255,255,255,.03) inset, 0 18px 40px -28px rgba(0,0,0,.9)",
      },
      borderRadius: { "2xl": "1rem", "3xl": "1.25rem" },
      maxWidth: { rail: "21rem" },
      keyframes: {
        "fade-up": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { "fade-up": "fade-up .3s ease both" },
    },
  },
  plugins: [
    function ({ addUtilities }) {
      addUtilities(Object.fromEntries(
        Object.entries(textOverrides).map(([k, v]) => [`.text-slate-${k}`, { color: v }]),
      ));
    },
  ],
};
