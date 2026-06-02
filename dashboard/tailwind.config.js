/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#06090f',
        surface: '#0b1019',
        card:    '#0f1724',
        border:  '#192130',
        border2: '#253348',
        muted:   '#4b5568',
        subtle:  '#7a8499',
        text:    '#dde3ef',
        white:   '#f0f4ff',
        critical:'#f87171',
        high:    '#fb923c',
        medium:  '#fbbf24',
        low:     '#4ade80',
        accent:  '#60a5fa',
        cyan:    '#22d3ee',
        violet:  '#a78bfa',
      },
    },
  },
  plugins: [],
}
