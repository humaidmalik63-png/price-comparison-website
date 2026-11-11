import React, { useState } from 'react';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AnimatePresence } from 'framer-motion';

import { PRODUCTS_DATA } from './data/products';
import type { Product, ProductCategory, Subcategory } from './types';

// Context
import { AuthProvider } from './context/AuthContext';

// Hooks
import { useWishlist } from './hooks/useWishlist';
import { usePriceTracker } from './hooks/usePriceTracker';

// Components & Pages
import { CustomCursor } from './components/CustomCursor';
import { Navbar } from './components/Navbar';
import { ScrollToTop } from './components/ScrollToTop';
import { WishlistDrawer } from './components/WishlistDrawer';
import { ProductDetailModal } from './components/ProductDetailModal';
import { AuthModal } from './components/AuthModal';
import { Footer } from './components/Footer';

import { DiscoveryHomePage } from './pages/DiscoveryHomePage';
import { ProductDetailPage } from './pages/ProductDetailPage';
import { WatchlistPage } from './pages/WatchlistPage';
import { ProfilePage } from './pages/ProfilePage';
import { RoutinesPage } from './pages/RoutinesPage';
import { NotFoundPage } from './pages/NotFoundPage';
import { AdminDashboard } from './components/admin/AdminDashboard';

export const AppContent: React.FC = () => {
  // Navigation & Filter State
  const [activeCategory, setActiveCategory] = useState<ProductCategory | 'all'>('all');
  const [activeSubcategory, setActiveSubcategory] = useState<Subcategory | 'all'>('all');

  // Modal & Drawer State
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [isWishlistOpen, setIsWishlistOpen] = useState(false);

  // Hooks
  const { wishlist, toggleWishlist, isWishlisted, clearWishlist, wishlistCount } = useWishlist();
  const { unreadAlertCount } = usePriceTracker();

  const handleSelectAlternativeProduct = (productId: string) => {
    const target = PRODUCTS_DATA.find((p) => p.id === productId);
    if (target) {
      setSelectedProduct(target);
    }
  };

  const scrollToSection = (sectionId: string) => {
    const el = document.getElementById(sectionId);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' });
    }
  };

  return (
    <div className="min-h-screen bg-ivory text-espresso-900 font-sans selection:bg-rose-200 selection:text-espresso-950 flex flex-col justify-between">
      {/* Editorial Custom Cursor for Desktop */}
      <CustomCursor />

      {/* Global Navigation Header */}
      <Navbar
        wishlistCount={wishlistCount}
        unreadAlertCount={unreadAlertCount}
        onOpenWishlist={() => setIsWishlistOpen(true)}
        onSelectCategory={(cat) => setActiveCategory(cat)}
        onScrollToSection={scrollToSection}
        activeCategory={activeCategory}
      />

      {/* Dynamic Route View */}
      <div className="flex-1 pt-16">
        <Routes>
          <Route
            path="/"
            element={
              <DiscoveryHomePage
                wishlist={wishlist}
                toggleWishlist={toggleWishlist}
                isWishlisted={isWishlisted}
                onSelectProduct={(p) => setSelectedProduct(p)}
                activeCategory={activeCategory}
                setActiveCategory={setActiveCategory}
                activeSubcategory={activeSubcategory}
                setActiveSubcategory={setActiveSubcategory}
              />
            }
          />

          <Route path="/product/:slugOrId" element={<ProductDetailPage />} />

          <Route path="/watchlist" element={<WatchlistPage />} />

          <Route path="/profile" element={<ProfilePage />} />

          <Route path="/routines" element={<RoutinesPage />} />

          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </div>

      {/* Slide-out Wishlist Drawer */}
      <AnimatePresence>
        {isWishlistOpen && (
          <WishlistDrawer
            isOpen={isWishlistOpen}
            onClose={() => setIsWishlistOpen(false)}
            wishlistIds={wishlist}
            allProducts={PRODUCTS_DATA}
            onRemoveFromWishlist={toggleWishlist}
            onClearWishlist={clearWishlist}
            onViewProduct={(p) => {
              setIsWishlistOpen(false);
              setSelectedProduct(p);
            }}
            onExploreProducts={() => {
              setIsWishlistOpen(false);
              scrollToSection('catalog');
            }}
          />
        )}
      </AnimatePresence>

      {/* Quick Product Detail Modal (for comparison triggers) */}
      <AnimatePresence>
        {selectedProduct && (
          <ProductDetailModal
            product={selectedProduct}
            onClose={() => setSelectedProduct(null)}
            isWishlisted={isWishlisted(selectedProduct.id)}
            onToggleWishlist={toggleWishlist}
            onSelectAlternative={handleSelectAlternativeProduct}
          />
        )}
      </AnimatePresence>

      {/* Auth Modal (Sign In / Register) */}
      <AuthModal />

      {/* Global Editorial Footer */}
      <Footer />
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <BrowserRouter>
      <ScrollToTop />
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </BrowserRouter>
  );
};

export default App;
