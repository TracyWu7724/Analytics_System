import { AnimatePresence, motion } from "framer-motion";

export default function HeroSection() {
  return (
    <div className="text-center space-y-4">
      <AnimatePresence>
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="shimmer inline-block px-4 py-1.5 mb-6 text-sm md:text-base font-medium tracking-wider border-[3px] rounded-full shadow-glow"
          style={{
            borderColor: "rgba(17, 61, 115, 0.2)",
            backgroundColor: "rgba(17, 61, 115, 0.05)",
          }}
        >
          <svg
            className="w-4 h-4 inline mr-2"
            fill="#3070A6"
            viewBox="0 0 24 24"
          >
            <path d="M12 2L15.09 8.26L22 9L17 14L18.18 21L12 17.77L5.82 21L7 14L2 9L8.91 8.26L12 2Z" />
          </svg>
          AI Powered
        </motion.span>

        <motion.h1
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="text-2xl md:text-4xl lg:text-5xl font-bold mb-4 md:mb-6 tracking-tight text-gray-900"
          style={{ color: "#113D73" }}
        >
          Analytics System for Business Insights
        </motion.h1>
      </AnimatePresence>
    </div>
  );
}