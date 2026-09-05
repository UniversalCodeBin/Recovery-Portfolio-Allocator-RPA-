/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#f0f7ff',
          100: '#e0effe',
          200: '#bae0fd',
          300: '#7cc7fb',
          400: '#36aaf5',
          500: '#0c8ee9',
          600: '#0070c7',
          700: '#0159a1',
          800: '#064c84',
          900: '#0b3f6f',
          950: '#07284a',
        },
        razor: {
          blue: '#0C2340',
          navy: '#021329',
          primary: '#0C8EE9',
          accent: '#2563EB',
          surface: '#0F172A',
          card: '#1E293B',
          border: '#334155',
        },
      },
    },
  },
  plugins: [],
}
