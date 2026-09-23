/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#06090f',
        surface: '#0b1019',
        card:    '#0f1724',
        raised:  '#141d2c',
        border:  '#192130',
        border2: '#253348',
        // Text scale. Every step used for readable text meets WCAG AA (>= 4.5:1)
        // on both `bg` and `card`; `dim` is for decorative strokes only.
        dim:     '#4b5568',
        faint:   '#7a8499',
        muted:   '#8a94a8',
        subtle:  '#9aa3b5',
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
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      transitionTimingFunction: {
        'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)',
        spring:     'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
      keyframes: {
        'fade-up':   { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'none' } },
        'fade-in':   { from: { opacity: '0' }, to: { opacity: '1' } },
        'scale-in':  { from: { opacity: '0', transform: 'scale(0.96)' }, to: { opacity: '1', transform: 'none' } },
        'slide-in-right': { from: { opacity: '0', transform: 'translateX(24px)' }, to: { opacity: '1', transform: 'none' } },
        'slide-in-left':  { from: { transform: 'translateX(-100%)' }, to: { transform: 'none' } },
        shimmer:     { from: { backgroundPosition: '-400px 0' }, to: { backgroundPosition: '400px 0' } },
        'toast-progress': { from: { transform: 'scaleX(1)' }, to: { transform: 'scaleX(0)' } },
      },
      animation: {
        'fade-up':   'fade-up 0.35s cubic-bezier(0.16, 1, 0.3, 1) both',
        'fade-in':   'fade-in 0.2s ease-out both',
        'scale-in':  'scale-in 0.2s cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-in-right': 'slide-in-right 0.35s cubic-bezier(0.16, 1, 0.3, 1) both',
        'slide-in-left':  'slide-in-left 0.3s cubic-bezier(0.16, 1, 0.3, 1) both',
        shimmer:     'shimmer 1.4s linear infinite',
      },
    },
  },
  plugins: [],
}
