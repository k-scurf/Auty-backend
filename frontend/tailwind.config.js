/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "monospace"],
      },
      colors: {
        bg: {
          DEFAULT: "#0F1923",
          surface: "#1A2736",
          elevated: "#243347",
        },
        border: "#243347",
        accent: {
          DEFAULT: "#00D4AA",
          blue: "#3B9EFF",
        },
        danger: "#FF5B5B",
        warning: "#FFB020",
        text: {
          primary: "#F0F4F8",
          secondary: "#8BA3BB",
          muted: "#4A6078",
        },
        // Legacy aliases — keep so existing code compiles during migration
        surface: "#0F1923",
        panel: "#1A2736",
        card: "#1A2736",
        inset: "#243347",
        "accent-warm": "#FFB020",
      },
      boxShadow: {
        card: "0 1px 3px rgba(0,0,0,0.3), 0 4px 16px rgba(0,0,0,0.2)",
        elevated: "0 8px 32px rgba(0,0,0,0.4)",
        glow: "0 0 24px rgba(0,212,170,0.2)",
        "glow-warm": "0 0 24px rgba(255,176,32,0.2)",
        "glow-danger": "0 0 24px rgba(255,91,91,0.2)",
      },
      borderRadius: {
        card: "8px",
        btn: "6px",
        input: "4px",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        "pulse-ring": {
          "0%, 100%": { opacity: "0.6", transform: "scale(1)" },
          "50%": { opacity: "1", transform: "scale(1.03)" },
        },
        "ring-expand": {
          "0%": { opacity: "1", transform: "scale(1)" },
          "100%": { opacity: "0", transform: "scale(1.6)" },
        },
        "slide-up": {
          "0%": { opacity: "0", transform: "translateY(24px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "countdown": {
          "0%": { width: "100%" },
          "100%": { width: "0%" },
        },
      },
      animation: {
        shimmer: "shimmer 2s linear infinite",
        "pulse-ring": "pulse-ring 3s ease-in-out infinite",
        "pulse-ring-fast": "pulse-ring 0.8s ease-in-out infinite",
        "ring-expand": "ring-expand 0.5s ease-out forwards",
        "slide-up": "slide-up 0.3s ease-out",
        "fade-in": "fade-in 0.15s ease-out",
        "countdown": "countdown 3s linear forwards",
      },
    },
  },
  plugins: [],
};
