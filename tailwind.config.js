/** Design tokens live here, not scattered across templates. See CLAUDE.md.
 *
 * Values come from the "Organic" design system in the Villa Dashboard handoff
 * (New UI mockups/design_handoff_villa_dashboard/README.md) - those are final
 * design-system values, so change them there first, not here.
 *
 * The token *names* (sand/ink/teal) are the original ones, kept on purpose so
 * every existing template keeps working unchanged:
 *   sand  = warm cream ground + neutral ramp (bg #f5ead8, surface #ebddc5)
 *   ink   = the same neutral ramp, used for text
 *   teal  = the terracotta primary accent ramp
 *   accent2 = the sage secondary accent ramp
 */
module.exports = {
  content: ["./templates/**/*.html", "./apps/**/*.py", "./static/js/**/*.js"],
  // Component classes defined in src.css (@layer components) are purged the
  // same way utilities are - safelisted so they survive regardless of which
  // templates have adopted them yet.
  safelist: [
    "btn", "btn-primary", "btn-secondary", "btn-ghost", "btn-icon",
    "input", "tag", "tag-accent", "tag-accent-2", "tag-neutral", "tag-toggle",
    "seg", "seg-opt", "seg-opt-active", "card", "field", "title-input",
    "elev-sm", "guest-scroll", "detail-card-fade", "cal-search-focus",
  ],
  theme: {
    extend: {
      colors: {
        sand: {
          50: "#f5ead8",   // page background
          100: "#ebddc5",  // surface: cards, header bar, table
          200: "#eee7db",
          300: "#dcd3c4",
          400: "#c0b6a5",
          500: "#a19786",
          600: "#82796a",
          700: "#645c50",
          800: "#474238",
          900: "#2e2b25",
        },
        ink: {
          50: "#f9f4ed", 100: "#eee7db", 200: "#dcd3c4", 300: "#c0b6a5", 400: "#a19786",
          500: "#a19786", 600: "#82796a", 700: "#645c50", 800: "#474238", 900: "#201e1d",
        },
        teal: {
          50: "#fff2eb", 100: "#ffe1d0", 200: "#ffc6a5", 300: "#ffc6a5", 400: "#f6a06b",
          500: "#d67f48", 600: "#c67139", 700: "#b2622d", 800: "#643312", 900: "#402310",
        },
        accent2: {
          100: "#f0fae1", 200: "#e1eecc", 300: "#ccdbb2", 400: "#aebf92",
          500: "#8fa073", 600: "#728157", 700: "#56633f", 800: "#3d472b", 900: "#272e1b",
        },
      },
      fontFamily: {
        sans: ["Figtree", "system-ui", "sans-serif"],
        display: ["Caprasimo", "Georgia", "serif"],
      },
      // The handoff's spacing scale, in its own keys so Tailwind's default
      // numeric spacing (p-4 etc.) keeps working everywhere else.
      spacing: {
        s1: "4.4px", s2: "8.8px", s3: "13.2px", s4: "17.6px", s6: "26.4px", s8: "35.2px",
      },
      borderRadius: { sm: "8px", md: "16px", lg: "28px", card: "32px" },
      boxShadow: {
        sm: "0 1px 2px rgba(46,43,37,.14)",
        md: "0 3px 10px rgba(46,43,37,.16)",
        lg: "0 12px 32px rgba(46,43,37,.22)",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
