export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                bgStart: "#0A0A14",
                bgEnd: "#1A1A2E",
                surface: "rgba(255, 255, 255, 0.03)",
                surfaceHover: "rgba(255, 255, 255, 0.08)",
                borderLight: "rgba(255, 255, 255, 0.1)",
                accent: "#3B82F6",
                accentGlow: "rgba(59, 130, 246, 0.5)",
            },
            fontFamily: {
                sans: ['Inter', 'sans-serif'],
            },
            animation: {
                'fade-in': 'fadeIn 0.3s ease-out forwards',
                'slide-up': 'slideUp 0.4s ease-out forwards',
            },
            keyframes: {
                fadeIn: {
                    '0%': { opacity: '0' },
                    '100%': { opacity: '1' },
                },
                slideUp: {
                    '0%': { opacity: '0', transform: 'translateY(10px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                }
            }
        },
    },
    plugins: [],
}
