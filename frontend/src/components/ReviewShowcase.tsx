import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { Star, ShieldCheck, AlertCircle } from 'lucide-react';
import { REVIEWS_DATA } from '../data/reviews';

export const ReviewShowcase: React.FC = () => {
  const [selectedPlatform, setSelectedPlatform] = useState<string>('all');

  const filteredReviews = selectedPlatform === 'all'
    ? REVIEWS_DATA
    : REVIEWS_DATA.filter((r) => r.platform.toLowerCase().includes(selectedPlatform.toLowerCase()));

  const platforms = [
    { key: 'all', label: 'All Reviews' },
    { key: 'nykaa', label: 'Nykaa' },
    { key: 'tira', label: 'Tira' },
    { key: 'amazon', label: 'Amazon India' },
    { key: 'purplle', label: 'Purplle' },
    { key: 'myntra', label: 'Myntra' },
  ];

  return (
    <section id="reviews" className="py-20 bg-ivory border-b border-rose-100">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between mb-10 gap-4">
          <div>
            <span className="text-xs font-bold tracking-widest uppercase text-rose-500 mb-2 inline-block">
              Multi-Platform Community Consensus
            </span>
            <h2 className="font-editorial text-3xl sm:text-5xl font-bold text-espresso-800 tracking-tight">
              Cross-Platform Review Experience
            </h2>
            <p className="text-espresso-600 text-sm sm:text-base mt-2 max-w-xl">
              A demonstration of how retailer-attributed reviews are presented side by side. No retailer review feed is
              connected in this build, so every card below is marked as sample content rather than a real customer review.
            </p>
          </div>

          {/* Platform Filters */}
          <div className="flex flex-wrap gap-1.5 self-start md:self-auto">
            {platforms.map((p) => (
              <button
                key={p.key}
                onClick={() => setSelectedPlatform(p.key)}
                className={`px-3 py-1.5 rounded-full text-xs font-semibold tracking-wide transition-all ${
                  selectedPlatform === p.key
                    ? 'bg-rose-500 text-ivory shadow-xs'
                    : 'bg-white border border-rose-200/80 text-espresso-600 hover:border-rose-300'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Demo Data Disclaimer */}
        <div className="mb-6 flex items-center space-x-2 text-xs text-espresso-500 bg-white/70 p-3 rounded-xl border border-rose-100">
          <AlertCircle className="w-4 h-4 text-champagne-600 shrink-0" />
          <span>
            <strong>DEMO CONTENT &mdash; NOT REAL CUSTOMER REVIEWS:</strong> The names, ratings and comments below are
            illustrative sample content written for this academic prototype. They are not testimonials collected from
            shoppers and no retailer has supplied them. Verified retailer reviews appear here only after they are imported
            with supporting evidence. Retailer logos and marks remain property of their respective owners.
          </span>
        </div>

        {/* Reviews Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredReviews.map((rev, idx) => (
            <motion.div
              key={rev.id}
              initial={{ opacity: 0, y: 15 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ duration: 0.4, delay: idx * 0.06 }}
              className="rounded-2xl bg-white border border-rose-200/80 p-6 shadow-soft-lift flex flex-col justify-between"
            >
              <div>
                {/* Top: Stars & Platform Badge */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center space-x-1 text-champagne-500">
                    {[...Array(5)].map((_, i) => (
                      <Star
                        key={i}
                        className={`w-4 h-4 ${
                          i < rev.rating ? 'fill-champagne-500' : 'text-espresso-200'
                        }`}
                      />
                    ))}
                  </div>

                  <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-ivory-200 text-espresso-700 border border-rose-100">
                    {rev.platform}
                  </span>
                </div>

                <h4 className="font-editorial text-base sm:text-lg font-bold text-espresso-800 mb-2">
                  "{rev.title}"
                </h4>

                <p className="text-xs sm:text-sm text-espresso-600 leading-relaxed italic">
                  "{rev.comment}"
                </p>
              </div>

              {/* Bottom: Author & Verified Tag */}
              <div className="pt-4 mt-4 border-t border-rose-100 flex items-center justify-between text-xs">
                <div>
                  <span className="font-semibold text-espresso-800 block">{rev.author}</span>
                  <span className="text-[11px] text-espresso-400">{rev.date}</span>
                </div>

                {rev.dataStatus === 'demo' ? (
                  <span
                    className="flex items-center space-x-1 text-champagne-700 font-medium text-[11px]"
                    title="Sample content, not a real customer review"
                  >
                    <AlertCircle className="w-3.5 h-3.5" />
                    <span>Sample content</span>
                  </span>
                ) : rev.verifiedBuyer ? (
                  <span className="flex items-center space-x-1 text-sage-600 font-medium text-[11px]">
                    <ShieldCheck className="w-3.5 h-3.5" />
                    <span>Verified Buyer</span>
                  </span>
                ) : null}
              </div>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};
