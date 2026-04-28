/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#fdf8ed",
          100: "#faecca",
          200: "#f4d691",
          300: "#edbb58",
          400: "#e7a232",
          500: "#d3871f",
          600: "#b06a18",
          700: "#8c4f17",
          800: "#723f1a",
          900: "#5e351a",
        },
      },
    },
  },
  plugins: [],
};
