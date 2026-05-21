/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
      },
      colors: {
        surface: "#0b0f14",
        panel: "#121820",
        card: "#1a222d",
        inset: "#0f141c",
        border: "#2a3544",
        accent: "#2dd4bf",
        "accent-warm": "#f59e0b",
      },
      boxShadow: {
        glow: "0 0 24px rgba(45, 212, 191, 0.15)",
        "glow-warm": "0 0 24px rgba(245, 158, 11, 0.2)",
      },
    },
  },
  plugins: [],
};
