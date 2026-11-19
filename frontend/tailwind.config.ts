import type { Config } from "tailwindcss";

/**
 * TrueOffer brand tokens. Only the brand palette plus cool-gray neutrals are allowed
 * (no green / yellow / orange / purple). Offer series: A = Arizona Blue, B = Arizona Red, C = Arroyo Blue.
 * Status is always icon + label + color.
 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        navy: { DEFAULT: "#0C234B", 50: "#EEF1F6", 100: "#D5DCE8", 700: "#0A1D3F", 900: "#061229" },
        brandred: { DEFAULT: "#AB0520", 50: "#FBECEE", 100: "#F5CCD2", 700: "#8B0015" },
        arroyo: { DEFAULT: "#106AB1", 50: "#EAF3FA", 100: "#CCE2F3" },
        azurite: "#1E5288",
        oasis: "#378DBD",
        sky: "#81D3EB",
        offerA: "#0C234B",
        offerB: "#AB0520",
        offerC: "#106AB1",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "Helvetica Neue", "Arial", "sans-serif"],
      },
      boxShadow: { card: "0 1px 2px rgba(12,35,75,.06), 0 4px 16px rgba(12,35,75,.06)" },
    },
  },
  plugins: [],
} satisfies Config;
