/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#16A34A",
          light: "#07C983",
          dark: "#15803D",
        },
      },
    },
  },
  plugins: [],
};
