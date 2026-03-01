/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './SimWorks/templates/**/*.html',
    './SimWorks/apps/**/templates/**/*.html',
    './SimWorks/apps/**/static/**/*.js',
    './SimWorks/static/**/*.js'
  ],
  important: '.tw-root',
  theme: {
    extend: {
      colors: {
        content: '#222222',
        'content-secondary': '#888888',
        'content-light': '#ffffff',
        surface: '#ffffff',
        'surface-alt': '#f5f5f5',
        border: '#dddddd',
        'jckfrt-olive': '#4B5D43',
        'jckfrt-olive-hover': '#44543C',
        'jckfrt-yellow': '#D2A640',
        'jckfrt-yellow-hover': '#BFA22D',
        'jckfrt-red': '#DA3D3D',
        'jckfrt-red-hover': '#C43737',
        'jckfrt-dark': '#2C2C2C',
        'jckfrt-less-dark': '#C5C5C5',
        'brand-apple': '#000000',
        'brand-google-text': '#1f1f1f',
        'brand-google-border': '#d9d9d9'
      }
    }
  },
  plugins: []
};
