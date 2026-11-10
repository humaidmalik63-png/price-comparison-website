import React from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Heart, Star, Sparkles, Scale, Info } from 'lucide-react';
import type { Product } from '../types';

interface ProductCardProps {
  product: Product;
  isWishlisted: boolean;
  onToggleWishlist: (id: string) => void;
  onViewProduct: (product: Product) => void;
  onComparePrices?: (product: Product) => void;
  onViewAlternative?: (product: Product) => void;
}

// Resilient SVG fallback image in Warm Ivory & Dusty Rose
import { ProductImage } from './ProductImage';

export const ProductCard: React.FC<ProductCardProps> = ({
  product,
  isWishlisted,
  onToggleWishlist,
  onViewProduct,
  onComparePrices,
  onViewAlternative,
}) => {
  // Find lowest price store
  const lowestOffer = product.storeOffers.reduce((min, o) => (o.price < min.price ? o : min), product.storeOffers[0]);
  const savingsAmount = product.originalPrice ? product.originalPrice - product.price : 0;
  const savingsPct = product.originalPrice ? Math.round((savingsAmount / product.originalPrice) * 100) : 0;
  const hasAlternative = Boolean(product.dupeId);
  const productUrl = `/product/${product.slug || product.id}`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true }}
      transition={{ duration: 0.4 }}
      className="group relative rounded-2xl bg-white border border-rose-100/90 hover:border-rose-300 shadow-soft-lift hover:shadow-luxury-card transition-all duration-300 flex flex-col overflow-hidden"
    >
      {/* Top Media Area */}
      <div className="relative aspect-4/3 w-full bg-ivory-100 overflow-hidden">
        <Link to={productUrl} className="block w-full h-full">
          <ProductImage
            src={product.image}
            alt={product.name}
            brand={product.brand}
            category={product.category}
            status={product.imageStatus || 'placeholder'}
            className="w-full h-full group-hover:scale-105 transition-transform duration-500"
          />
        </Link>

        {/* Top Floating Badges */}
        <div className="absolute top-3 left-3 flex flex-col gap-1 items-start">
          {product.dataStatus === 'catalog_verified' ? (
            <span className="px-2 py-0.5 rounded-full text-[9px] font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300 shadow-2xs" title="Ingredients, net volume, and manufacturer packaging verified">
              Verified Spec
            </span>
          ) : product.dataStatus === 'partially_verified' ? (
            <span className="px-2 py-0.5 rounded-full text-[9px] font-semibold bg-amber-100 text-amber-800 border border-amber-300 shadow-2xs" title="Key specifications partially verified; packaging filing pending">
              Partially Verified Specs
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded-full text-[9px] font-medium bg-white/90 backdrop-blur-xs text-espresso-600 border border-espresso-200 shadow-2xs" title="Commercial product listing available">
              Product Info Available
            </span>
          )}
          {product.dealTag && (
            <span className="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-500 text-ivory shadow-xs">
              {product.dealTag.split('•')[0]}
            </span>
          )}
          <span className="px-2 py-0.5 rounded-full text-[9px] font-semibold uppercase tracking-wider bg-white/90 backdrop-blur-xs text-espresso-700 border border-rose-100">
            {product.subcategory}
          </span>
        </div>

        {/* Wishlist Button */}
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onToggleWishlist(product.id);
          }}
          aria-label={isWishlisted ? "Remove from wishlist" : "Add to wishlist"}
          className={`absolute top-3 right-3 p-2 rounded-full backdrop-blur-md transition-all shadow-xs ${
            isWishlisted
              ? 'bg-rose-50 text-rose-500 border border-rose-300'
              : 'bg-white/80 hover:bg-white text-espresso-400 hover:text-rose-500 border border-white/60'
          }`}
        >
          <Heart className={`w-4 h-4 ${isWishlisted ? 'fill-rose-500 text-rose-500' : ''}`} />
        </button>

        {/* Brand Tier Pill & Demo Label */}
        <div className="absolute bottom-3 left-3 flex items-center space-x-1.5">
          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md ${
            product.brandTier === 'Luxury'
              ? 'bg-espresso-800 text-champagne-300'
              : product.brandTier === 'Premium'
              ? 'bg-rose-100 text-rose-700'
              : 'bg-sage-100 text-sage-700'
          }`}>
            {product.brandTier}
          </span>
          <span className="text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded-md bg-white/85 text-espresso-600 border border-rose-100">
            Demo Price
          </span>
        </div>
      </div>

      {/* Content Area */}
      <div className="p-4 sm:p-5 flex-1 flex flex-col justify-between">
        <div>
          {/* Brand & Quantity */}
          <div className="flex items-center justify-between text-xs text-espresso-400 mb-1">
            <span className="font-semibold uppercase tracking-wider text-rose-500">{product.brand}</span>
            <span>{product.quantity}</span>
          </div>

          {/* Product Name */}
          <Link
            to={productUrl}
            className="font-editorial text-lg sm:text-xl font-bold text-espresso-800 line-clamp-2 hover:text-rose-600 cursor-pointer transition-colors leading-snug block"
            title={product.name}
          >
            {product.name}
          </Link>

          {/* Skin Type or Finish Tag */}
          <p className="text-xs text-espresso-500 mt-1 line-clamp-1">
            {product.skinType ? `For: ${product.skinType}` : product.finish ? `Finish: ${product.finish}` : ''}
          </p>

          {/* Rating */}
          {product.rating && (
            <div className="flex items-center space-x-1.5 mt-2">
              <div className="flex items-center text-champagne-500">
                <Star className="w-3.5 h-3.5 fill-champagne-500" />
                <span className="text-xs font-bold text-espresso-700 ml-1">{product.rating}</span>
              </div>
              <span className="text-espresso-300 text-xs">•</span>
              <span className="text-xs text-espresso-400">({product.reviewCount?.toLocaleString('en-IN')})</span>
            </div>
          )}
        </div>

        {/* Pricing & Comparison Footer */}
        <div className="pt-3 mt-3 border-t border-rose-100/60">
          <div className="flex items-baseline justify-between">
            <div>
              <span className="text-[11px] text-espresso-400 block font-normal">Lowest Available</span>
              <div className="flex items-baseline space-x-2">
                <span className="text-xl font-extrabold text-espresso-900 font-sans">
                  ₹{product.price.toLocaleString('en-IN')}
                </span>
                {product.originalPrice && product.originalPrice > product.price && (
                  <span className="text-xs text-espresso-400 line-through">
                    ₹{product.originalPrice.toLocaleString('en-IN')}
                  </span>
                )}
              </div>
            </div>

            {/* Savings percentage */}
            {savingsPct > 0 && (
              <span className="text-xs font-bold text-rose-600 bg-rose-50 px-2 py-0.5 rounded-full border border-rose-200">
                Save {savingsPct}%
              </span>
            )}
          </div>

          {/* Retailer badge */}
          {lowestOffer && (
            <div className="mt-2 flex items-center justify-between text-[11px] text-espresso-500 bg-ivory px-2.5 py-1 rounded-md border border-rose-100">
              <span>On <strong>{lowestOffer.storeName}</strong></span>
              <span className="text-sage-600 font-medium">Free Delivery</span>
            </div>
          )}

          {/* Action Button Row: Details, Compare Prices, Cheapest Alternative */}
          <div className="mt-3 flex flex-col gap-1.5">
            <div className="grid grid-cols-2 gap-1.5">
              <Link
                to={productUrl}
                className="py-2 rounded-xl bg-ivory-200 hover:bg-ivory-300 text-espresso-800 text-xs font-semibold tracking-wide transition-all flex items-center justify-center space-x-1"
              >
                <Info className="w-3.5 h-3.5 text-espresso-600" />
                <span>Details</span>
              </Link>

              <button
                type="button"
                onClick={() => onComparePrices ? onComparePrices(product) : onViewProduct(product)}
                className="py-2 rounded-xl bg-espresso-800 hover:bg-espresso-900 text-ivory text-xs font-semibold tracking-wide transition-all flex items-center justify-center space-x-1"
              >
                <Scale className="w-3.5 h-3.5 text-champagne-300" />
                <span>Compare</span>
              </button>
            </div>

            {hasAlternative && (
              <button
                type="button"
                onClick={() => onViewAlternative ? onViewAlternative(product) : onViewProduct(product)}
                className="w-full py-1.5 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200/80 text-[11px] font-bold tracking-wide transition-all flex items-center justify-center space-x-1"
              >
                <Sparkles className="w-3 h-3 text-rose-500" />
                <span>Cheapest Alternative</span>
              </button>
            )}
          </div>
        </div>
      </div>
    </motion.div>
  );
};
