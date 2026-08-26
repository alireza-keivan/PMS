/** Design tokens live here, not scattered across templates. See CLAUDE.md. */
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/*.py"],
  theme: {
    extend: {
      colors: {
        sand: { 50: "#faf8f5", 100: "#f2ede5", 200: "#e4dbcd", 600: "#8a7f6d" },
        ink:  { 600: "#5c5851", 900: "#1f1d1a" },
        teal: { 500: "#2f8f83", 600: "#256f66" },
      },
      fontFamily: { sans: ["Inter", "system-ui", "sans-serif"] },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
