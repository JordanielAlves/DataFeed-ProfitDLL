/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: {
          darkest: '#090b10',
          darker: '#0e131b',
          card: '#131b26',
          panel: '#182232',
          border: '#223044'
        },
        trade: {
          buy: '#10b981',
          buyGlow: '#059669',
          sell: '#ef4444',
          sellGlow: '#dc2626',
          sniper: '#00f59b',
          neutral: '#94a3b8',
          warn: '#f59e0b',
          accent: '#38bdf8'
        }
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Courier New', 'monospace'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      }
    },
  },
  plugins: [],
}
