/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{html,ts}'],
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#effaf8',
          100: '#d7f3ee',
          200: '#b1e6de',
          300: '#80d2c7',
          400: '#4fb8ab',
          500: '#2f9c90',
          600: '#237d75',
          700: '#206460',
          800: '#1e514f',
          900: '#1d4442',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
