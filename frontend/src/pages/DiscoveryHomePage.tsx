import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, X } from 'lucide-react';

import { PRODUCTS_DATA } from '../data/products';
import { CATEGORIES_DATA } from '../data/categories';
import type { Product, ProductCategory, Subcategory } from '../types';

import { Hero } from '../components/Hero';
import { CategoryGrid } from '../components/CategoryGrid';
import { ProductCard } from '../components/ProductCard';
import { DealSection } from '../components/DealSection';
import { DupesSection } from '../components/DupesSection';
import { HowToUseSection } from '../components/HowToUseSection';
import { ReviewShowcase } from '../components/ReviewShowcase';

interface DiscoveryHomePageProps {
  wishlist?: string[];
  toggleWishlist: (id: string) => void;
  isWishlisted: (id: string) => boolean;
  onSelectProduct: (p: Product) => void;
  activeCategory: ProductCategory | 'all';
  setActiveCategory: (cat: ProductCategory | 'all') => void;
  activeSubcategory: Subcategory | 'all';
  setActiveSubcategory: (sub: Subcategory | 'all') => void;
}

export const DiscoveryHomePage: React.FC<DiscoveryHomePageProps> = ({
  toggleWishlist,
  isWishlisted,
  onSelectProduct,
  activeCategory,
  setActiveCategory,
  activeSubcategory,
  setActiveSubcategory,
}) => {
  const navigate = useNavigate();

  // Search & Filter State
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedBrand, setSelectedBrand] = useState<string | 'all'>('all');
  const [selectedSkinType, setSelectedSkinType] = useState<string | 'all'>('all');
  const [selectedBudget, setSelectedBudget] = useState<'all' | 'under-500' | '500-1000' | '1000-2500' | 'above-2500'>('all');
  const [selectedIngredient, setSelectedIngredient] = useState<string | 'all'>('all');
  const [selectedFinish, setSelectedFinish] = useState<string | 'all'>('all');
  const [sortBy, setSortBy] = useState<'featured' | 'price-asc' | 'price-desc' | 'name-asc' | 'rating' | 'best-deal'>('featured');

  // Extract all distinct brands
  const allBrands = useMemo(() => {
    const brandsSet = new Set<string>();
    PRODUCTS_DATA.forEach((p) => brandsSet.add(p.brand));
    return Array.from(brandsSet).sort();
  }, []);

  const skinTypes = [
    'All Skin Types',
    'Oily',
    'Dry',
    'Sensitive',
    'Combination',
    'Acne-Prone',
    'Normal',
  ];

  // Filter & Sort Products
  const filteredProducts = useMemo(() => {
    return PRODUCTS_DATA.filter((product) => {
      if (activeCategory !== 'all' && product.category !== activeCategory) return false;
      if (activeSubcategory !== 'all' && product.subcategory !== activeSubcategory) return false;
      if (selectedBrand !== 'all' && product.brand !== selectedBrand) return false;

      if (selectedSkinType !== 'all') {
        if (!product.skinType) return false;
        const normalized = product.skinType.toLowerCase();
        if (selectedSkinType === 'All Skin Types') {
          if (!normalized.includes('all skin')) return false;
        } else if (!normalized.includes(selectedSkinType.toLowerCase())) {
          return false;
        }
      }

      if (selectedBudget === 'under-500' && product.price > 500) return false;
      if (selectedBudget === '500-1000' && (product.price < 500 || product.price > 1000)) return false;
      if (selectedBudget === '1000-2500' && (product.price < 1000 || product.price > 2500)) return false;
      if (selectedBudget === 'above-2500' && product.price < 2500) return false;

      if (selectedIngredient !== 'all') {
        const ingMatch = product.keyIngredients.some((i) =>
          i.toLowerCase().includes(selectedIngredient.toLowerCase())
        );
        if (!ingMatch) return false;
      }

      if (selectedFinish !== 'all') {
        const finishMatch =
          product.name.toLowerCase().includes(selectedFinish.toLowerCase()) ||
          product.description.toLowerCase().includes(selectedFinish.toLowerCase());
        if (!finishMatch) return false;
      }

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchesName = product.name.toLowerCase().includes(q);
        const matchesBrand = product.brand.toLowerCase().includes(q);
        const matchesCategory = product.category.toLowerCase().includes(q);
        const matchesSubcat = product.subcategory.toLowerCase().includes(q);
        const matchesIngredients = product.keyIngredients.some((i) => i.toLowerCase().includes(q));
        const matchesSkin = product.skinType ? product.skinType.toLowerCase().includes(q) : false;
        if (!matchesName && !matchesBrand && !matchesCategory && !matchesSubcat && !matchesIngredients && !matchesSkin) {
          return false;
        }
      }
      return true;
    }).sort((a, b) => {
      if (sortBy === 'price-asc') return a.price - b.price;
      if (sortBy === 'price-desc') return b.price - a.price;
      if (sortBy === 'name-asc') return a.name.localeCompare(b.name);
      if (sortBy === 'rating') return (b.rating || 0) - (a.rating || 0);
      if (sortBy === 'best-deal') {
        const aScore = a.dealScore || (a.originalPrice ? a.originalPrice - a.price : 0);
        const bScore = b.dealScore || (b.originalPrice ? b.originalPrice - b.price : 0);
        return bScore - aScore;
      }
      return (b.isTrending ? 1 : 0) - (a.isTrending ? 1 : 0);
    });
  }, [activeCategory, activeSubcategory, selectedBrand, selectedSkinType, selectedBudget, selectedIngredient, selectedFinish, searchQuery, sortBy]);

  const bestDeals = useMemo(() => {
    return PRODUCTS_DATA.filter((p) => p.isBestDeal || (p.originalPrice && p.originalPrice > p.price));
  }, []);

  const scrollToSection = (sectionId: string) => {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  const handleResetFilters = () => {
    setActiveCategory('all');
    setActiveSubcategory('all');
    setSelectedBrand('all');
    setSelectedSkinType('all');
    setSelectedBudget('all');
    setSelectedIngredient('all');
    setSelectedFinish('all');
    setSearchQuery('');
    setSortBy('featured');
  };

  const hasActiveFilters = Boolean(
    activeCategory !== 'all' ||
    activeSubcategory !== 'all' ||
    selectedBrand !== 'all' ||
    selectedSkinType !== 'all' ||
    selectedBudget !== 'all' ||
    selectedIngredient !== 'all' ||
    selectedFinish !== 'all' ||
    searchQuery.trim() ||
    sortBy !== 'featured'
  );

  return (
    <main>
      {/* 1. Hero Campaign Section */}
      <Hero
        onSearch={(query: string) => setSearchQuery(query)}
        onExploreClick={() => scrollToSection('catalog')}
        onDupesClick={() => scrollToSection('dupes')}
      />

      {/* 2. Visual Categories Navigation */}
      <CategoryGrid
        selectedSubcategory={activeSubcategory}
        onSelectSubcategory={(sub: Subcategory) => {
          setActiveSubcategory(sub);
          const match = CATEGORIES_DATA.find((c) => c.name === sub);
          if (match) setActiveCategory(match.category);
          scrollToSection('catalog');
        }}
      />

      {/* 3. Catalog Section with Search, Multi-Filter Toolbar & Sorting */}
      <section id="catalog" className="py-20 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col lg:flex-row lg:items-end justify-between mb-8 gap-4">
          <div>
            <div className="flex items-center space-x-2 mb-1">
              <span className="text-xs font-bold tracking-widest uppercase text-rose-500">
                Indian Skincare & Makeup Discovery
              </span>
              <span className="text-espresso-300">•</span>
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-champagne-100 text-espresso-700 border border-champagne-300">
                Phase 3 Live
              </span>
            </div>
            <h2 className="font-editorial text-3xl sm:text-4xl font-bold text-espresso-800 tracking-tight">
              Product Discovery & Price Comparison
            </h2>
            <p className="text-espresso-600 text-xs sm:text-sm mt-1">
              Showing {filteredProducts.length} curated beauty products with multi-store comparison across Nykaa, Tira, Amazon, Purplle, and Myntra.
            </p>
          </div>

          {/* Quick Department Switcher */}
          <div className="flex flex-wrap items-center p-1 bg-white rounded-xl border border-rose-200/80 text-xs shadow-2xs">
            {(['all', 'skincare', 'makeup', 'haircare', 'bodycare'] as const).map((cat) => (
              <button
                key={cat}
                onClick={() => {
                  setActiveCategory(cat);
                  setActiveSubcategory('all');
                }}
                className={`px-3 py-1.5 rounded-lg font-semibold capitalize transition-colors ${
                  activeCategory === cat
                    ? 'bg-espresso-800 text-ivory'
                    : 'text-espresso-600 hover:text-espresso-900'
                }`}
              >
                {cat === 'all' ? 'All' : cat}
              </button>
            ))}
          </div>
        </div>

        {/* Phase 10: Beauty Intelligence Quick Access Suite */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3.5 mb-6">
          <button
            onClick={() => navigate('/ingredients')}
            className="p-4 rounded-2xl bg-white border border-rose-200/80 hover:border-rose-400 transition-all text-left shadow-soft-lift flex items-start space-x-3 group"
          >
            <div className="w-10 h-10 rounded-xl bg-rose-100 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform text-rose-600 font-bold text-lg">
              🧪
            </div>
            <div>
              <span className="text-[10px] uppercase font-bold tracking-wider text-rose-600 block">
                Clinical Matrix
              </span>
              <h3 className="font-serif font-bold text-sm text-espresso-900 group-hover:text-rose-600 transition-colors">
                Ingredient Safety & Clashes
              </h3>
              <p className="text-[11px] text-espresso-500 line-clamp-1 mt-0.5">
                AM/PM overload checker & Retinol/AHA conflict matrix
              </p>
            </div>
          </button>

          <button
            onClick={() => navigate('/climate-advisor')}
            className="p-4 rounded-2xl bg-white border border-rose-200/80 hover:border-rose-400 transition-all text-left shadow-soft-lift flex items-start space-x-3 group"
          >
            <div className="w-10 h-10 rounded-xl bg-blue-100 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform text-blue-600 font-bold text-lg">
              🌦️
            </div>
            <div>
              <span className="text-[10px] uppercase font-bold tracking-wider text-blue-600 block">
                Regional Care
              </span>
              <h3 className="font-serif font-bold text-sm text-espresso-900 group-hover:text-rose-600 transition-colors">
                Indian Climate Skincare
              </h3>
              <p className="text-[11px] text-espresso-500 line-clamp-1 mt-0.5">
                Humidity, winter dryness, and AC indoor texture advice
              </p>
            </div>
          </button>

          <button
            onClick={() => navigate('/shade-matcher')}
            className="p-4 rounded-2xl bg-white border border-rose-200/80 hover:border-rose-400 transition-all text-left shadow-soft-lift flex items-start space-x-3 group"
          >
            <div className="w-10 h-10 rounded-xl bg-champagne-100 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform text-champagne-700 font-bold text-lg">
              🎨
            </div>
            <div>
              <span className="text-[10px] uppercase font-bold tracking-wider text-champagne-700 block">
                South Asian Undertones
              </span>
              <h3 className="font-serif font-bold text-sm text-espresso-900 group-hover:text-rose-600 transition-colors">
                Foundation Shade Matcher
              </h3>
              <p className="text-[11px] text-espresso-500 line-clamp-1 mt-0.5">
                Olive/warm depth matching & sebum oxidation guidance
              </p>
            </div>
          </button>
        </div>

        {/* Search & Multi-Filter Control Strip */}
        <div className="bg-white p-4 sm:p-5 rounded-2xl border border-rose-200/90 shadow-soft-lift mb-6 space-y-4">
          {/* Row 1: Search Bar with Clear Button */}
          <div className="relative w-full">
            <Search className="w-4 h-4 text-espresso-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="🔍 Search product name, brand, category, or ingredients (e.g. Niacinamide, Sunscreen, Cetaphil, Ruby Woo)..."
              className="w-full pl-10 pr-10 py-2.5 rounded-xl bg-ivory-100 border border-rose-200 text-xs sm:text-sm text-espresso-800 placeholder-espresso-400 focus:outline-hidden focus:border-rose-400 focus:bg-white transition-all"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-espresso-400 hover:text-rose-500 rounded-full"
                aria-label="Clear search"
              >
                <X className="w-4 h-4" />
              </button>
            )}
          </div>

          {/* Row 2: Secondary Dropdown Filters */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 pt-1">
            {/* Brand Filter */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-espresso-400 block mb-1">
                Brand
              </label>
              <select
                value={selectedBrand}
                onChange={(e) => setSelectedBrand(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="all">All Brands</option>
                {allBrands.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>

            {/* Skin Type Filter */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-espresso-400 block mb-1">
                Skin Type
              </label>
              <select
                value={selectedSkinType}
                onChange={(e) => setSelectedSkinType(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="all">Any Skin</option>
                {skinTypes.map((st) => (
                  <option key={st} value={st}>{st}</option>
                ))}
              </select>
            </div>

            {/* Hero Ingredient Filter */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-rose-500 block mb-1">
                Active Ingredient
              </label>
              <select
                value={selectedIngredient}
                onChange={(e) => setSelectedIngredient(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="all">All Actives</option>
                <option value="niacinamide">Niacinamide</option>
                <option value="vitamin c">Vitamin C</option>
                <option value="hyaluronic">Hyaluronic Acid</option>
                <option value="salicylic">Salicylic Acid</option>
                <option value="ceramide">Ceramides</option>
                <option value="retinol">Retinol</option>
                <option value="snail">Snail Mucin</option>
              </select>
            </div>

            {/* Formulation / Finish Filter */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-espresso-400 block mb-1">
                Texture / Finish
              </label>
              <select
                value={selectedFinish}
                onChange={(e) => setSelectedFinish(e.target.value)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="all">All Finishes</option>
                <option value="matte">Matte</option>
                <option value="gel">Cooling Gel</option>
                <option value="dewy">Dewy / Hydrating</option>
                <option value="satin">Satin</option>
              </select>
            </div>

            {/* Budget Presets */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-espresso-400 block mb-1">
                Budget Range
              </label>
              <select
                value={selectedBudget}
                onChange={(e) => setSelectedBudget(e.target.value as any)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="all">Any Budget</option>
                <option value="under-500">Under ₹500</option>
                <option value="500-1000">₹500 - ₹1,000</option>
                <option value="1000-2500">₹1,000 - ₹2,500</option>
                <option value="above-2500">Luxury (₹2,500+)</option>
              </select>
            </div>

            {/* Sorting */}
            <div className="relative">
              <label className="text-[10px] font-bold uppercase tracking-wider text-espresso-400 block mb-1">
                Sort Results
              </label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as any)}
                className="w-full px-2.5 py-1.5 text-xs rounded-lg border border-rose-200 bg-ivory-50 text-espresso-800 font-medium focus:outline-hidden focus:border-rose-400 cursor-pointer"
              >
                <option value="featured">✨ Featured</option>
                <option value="price-asc">💵 Price: Low to High</option>
                <option value="price-desc">💎 Price: High to Low</option>
                <option value="name-asc">🔤 Name: A to Z</option>
                <option value="best-deal">🔥 Best Deal Score</option>
                <option value="rating">★ Highest Rated</option>
              </select>
            </div>
          </div>

          {/* Active Filter Pills & Reset Button */}
          {hasActiveFilters && (
            <div className="pt-2 border-t border-rose-100 flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-espresso-500">
                <span className="font-semibold text-espresso-700">Active Filters:</span>
                {activeCategory !== 'all' && (
                  <span className="px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 flex items-center space-x-1">
                    <span>Dept: {activeCategory}</span>
                    <button onClick={() => setActiveCategory('all')}>✕</button>
                  </span>
                )}
                {selectedBrand !== 'all' && (
                  <span className="px-2 py-0.5 rounded-full bg-rose-50 text-rose-700 border border-rose-200 flex items-center space-x-1">
                    <span>Brand: {selectedBrand}</span>
                    <button onClick={() => setSelectedBrand('all')}>✕</button>
                  </span>
                )}
                {selectedSkinType !== 'all' && (
                  <span className="px-2 py-0.5 rounded-full bg-sage-50 text-sage-800 border border-sage-200 flex items-center space-x-1">
                    <span>Skin: {selectedSkinType}</span>
                    <button onClick={() => setSelectedSkinType('all')}>✕</button>
                  </span>
                )}
                {selectedBudget !== 'all' && (
                  <span className="px-2 py-0.5 rounded-full bg-champagne-50 text-champagne-800 border border-champagne-300 flex items-center space-x-1">
                    <span>Budget: {selectedBudget}</span>
                    <button onClick={() => setSelectedBudget('all')}>✕</button>
                  </span>
                )}
                {searchQuery.trim() && (
                  <span className="px-2 py-0.5 rounded-full bg-ivory-200 text-espresso-800 border border-rose-200 flex items-center space-x-1">
                    <span>Query: "{searchQuery}"</span>
                    <button onClick={() => setSearchQuery('')}>✕</button>
                  </span>
                )}
              </div>

              <button
                type="button"
                onClick={handleResetFilters}
                className="text-xs font-bold text-rose-600 hover:text-rose-700 underline underline-offset-2 transition-colors ml-auto"
              >
                Reset All Filters
              </button>
            </div>
          )}
        </div>

        {/* Product Cards Grid or Empty State */}
        {filteredProducts.length === 0 ? (
          <div className="text-center py-20 bg-white rounded-3xl border border-rose-100 p-8 shadow-soft-lift max-w-xl mx-auto space-y-4">
            <div className="w-16 h-16 rounded-full bg-rose-50 text-rose-400 flex items-center justify-center mx-auto text-2xl font-serif">
              ✦
            </div>
            <h3 className="font-editorial text-2xl font-bold text-espresso-800">
              No matching beauty products found
            </h3>
            <p className="text-xs sm:text-sm text-espresso-500 leading-relaxed">
              We couldn't find any products matching your specific combination of filters. Try clearing your search keyword or switching to "All Brands".
            </p>
            <button
              onClick={handleResetFilters}
              className="mt-2 px-5 py-2.5 rounded-xl bg-espresso-800 text-ivory text-xs font-semibold hover:bg-espresso-900 transition-colors shadow-xs"
            >
              Reset Filters & Show Full Catalog
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6 sm:gap-7">
            {filteredProducts.map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                isWishlisted={isWishlisted(product.id)}
                onToggleWishlist={toggleWishlist}
                onViewProduct={() => navigate(`/product/${product.slug || product.id}`)}
                onComparePrices={() => onSelectProduct(product)}
                onViewAlternative={(p) => {
                  if (p.dupeId) {
                    const dupe = PRODUCTS_DATA.find((x) => x.id === p.dupeId);
                    if (dupe) navigate(`/product/${dupe.slug || dupe.id}`);
                  }
                }}
              />
            ))}
          </div>
        )}
      </section>

      {/* 4. Deals Section */}
      <DealSection
        deals={bestDeals}
        onViewProduct={(p) => navigate(`/product/${p.slug || p.id}`)}
        onToggleWishlist={toggleWishlist}
        isWishlisted={isWishlisted}
      />

      {/* 5. Affordable Alternatives */}
      <DupesSection
        onSelectAlternative={(productId) => {
          const target = PRODUCTS_DATA.find((p) => p.id === productId);
          if (target) navigate(`/product/${target.slug || target.id}`);
        }}
      />

      {/* 6. Educational How to Use / Routine Section */}
      <HowToUseSection />

      {/* 7. Multi-Platform Reviews Showcase */}
      <ReviewShowcase />
    </main>
  );
};
