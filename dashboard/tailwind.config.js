/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:       '#0d0d0d',
        surface:  '#141414',
        border:   '#262626',
        muted:    '#595959',
        subtle:   '#8c8c8c',
        text:     '#d9d9d9',
        critical: '#ff4d4f',
        high:     '#fa8c16',
        medium:   '#fadb14',
        low:      '#52c41a',
        accent:   '#69c0ff',
      },
    },
  },
  plugins: [],
}
