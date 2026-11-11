import React, { useState, useEffect, useRef } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Sparkles, Heart, Search, Menu, X, Bell, User as UserIcon, LogOut, Settings } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useAuth } from '../context/AuthContext';

import type { ProductCategory } from '../types';

interface NavbarProps {
  wishlistCount: number;
  unreadAlertCount?: number;
  onOpenWishlist: () => void;
  onSelectCategory?: (category: ProductCategory | 'all') => void;
  onScrollToSection?: (sectionId: string) => void;
  onOpenSearch?: () => void;
  activeCategory?: ProductCategory | 'all';
}

export const Navbar: React.FC<NavbarProps> = ({
  wishlistCount,
  unreadAlertCount = 0,
  onOpenWishlist,
  onSelectCategory,
  onScrollToSection,
  onOpenSearch,
  activeCategory = 'all',
}) => {
  const [isScrolled, setIsScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userDropdownOpen, setUserDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const { user, openAuthModal, logout } = useAuth();
  const navigate = useNavigate();

  useEffect(() => {
    const handleScroll = () => {
      setIsScrolled(window.scrollY > 20);
    };
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setUserDropdownOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleNavClick = (category: ProductCategory | 'all', sectionId: string) => {
    if (onSelectCategory && onScrollToSection) {
      onSelectCategory(category);
      onScrollToSection(sectionId);
    } else {
      navigate(`/?category=${category}`);
    }
    setMobileMenuOpen(false);
  };

  return (
    <>
      <header
        className={`fixed top-0 left-0 right-0 z-40 transition-all duration-300 ${
          isScrolled
            ? 'glass-panel shadow-soft-lift py-3'
            : 'bg-ivory/80 backdrop-blur-md py-5 border-b border-rose-100/60'
        }`}
      >
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between">
            {/* Logo */}
            <Link
              to="/"
              onClick={() => {
                if (onSelectCategory && onScrollToSection) {
                  onSelectCategory('all');
                  onScrollToSection('hero');
                }
              }}
              className="text-left group flex items-center space-x-2 focus:outline-hidden"
            >
              <div className="w-8 h-8 rounded-full bg-gradient-to-br from-rose-300 to-rose-500 flex items-center justify-center text-ivory font-serif font-bold text-lg shadow-xs group-hover:scale-105 transition-transform">
                P
              </div>
              <div>
                <span className="font-editorial text-2xl sm:text-3xl font-bold tracking-tight text-espresso-700 block leading-none">
                  PriceWise <span className="font-serif italic font-normal text-rose-500">Beauty</span>
                </span>
                <span className="text-[9px] tracking-widest uppercase text-espresso-400 font-sans block mt-0.5">
                  India • Editorial Price Intelligence
                </span>
              </div>
            </Link>

            {/* Desktop Navigation */}
            <nav className="hidden md:flex items-center space-x-7">
              <button
                onClick={() => handleNavClick('all', 'catalog')}
                className={`text-sm tracking-wide font-medium transition-colors hover:text-rose-600 ${
                  activeCategory === 'all' ? 'text-rose-600 font-semibold' : 'text-espresso-600'
                }`}
              >
                Discover
              </button>

              <button
                onClick={() => handleNavClick('skincare', 'catalog')}
                className={`text-sm tracking-wide font-medium transition-colors hover:text-rose-600 flex items-center space-x-1 ${
                  activeCategory === 'skincare' ? 'text-rose-600 font-semibold' : 'text-espresso-600'
                }`}
              >
                <span>Skincare</span>
                <span className="w-1.5 h-1.5 rounded-full bg-sage-400 inline-block"></span>
              </button>

              <button
                onClick={() => handleNavClick('makeup', 'catalog')}
                className={`text-sm tracking-wide font-medium transition-colors hover:text-rose-600 flex items-center space-x-1 ${
                  activeCategory === 'makeup' ? 'text-rose-600 font-semibold' : 'text-espresso-600'
                }`}
              >
                <span>Makeup</span>
                <span className="w-1.5 h-1.5 rounded-full bg-rose-400 inline-block"></span>
              </button>

              <button
                onClick={() => onScrollToSection ? onScrollToSection('deals') : navigate('/#deals')}
                className="text-sm tracking-wide font-medium text-espresso-600 hover:text-rose-600 transition-colors"
              >
                Deals
              </button>

              <button
                onClick={() => onScrollToSection ? onScrollToSection('dupes') : navigate('/#dupes')}
                className="text-sm tracking-wide font-medium text-espresso-600 hover:text-rose-600 transition-colors flex items-center space-x-1 text-champagne-600"
              >
                <Sparkles className="w-3.5 h-3.5 text-champagne-500" />
                <span>Dupes</span>
              </button>

              <Link
                to="/routines"
                className="text-sm tracking-wide font-medium text-espresso-600 hover:text-rose-600 transition-colors"
              >
                Routines
              </Link>

              <Link
                to="/watchlist"
                className="text-sm tracking-wide font-medium text-espresso-600 hover:text-rose-600 transition-colors"
              >
                Watchlist
              </Link>
            </nav>

            {/* Actions: Search, Alerts, Wishlist, User Auth */}
            <div className="flex items-center space-x-2 sm:space-x-2.5">
              {onOpenSearch && (
                <button
                  onClick={onOpenSearch}
                  aria-label="Search beauty products"
                  className="p-2 sm:px-3 sm:py-1.5 rounded-full bg-white border border-rose-200/70 hover:border-rose-400 text-espresso-600 hover:text-rose-600 flex items-center space-x-2 transition-all shadow-xs group"
                >
                  <Search className="w-4 h-4 text-espresso-400 group-hover:text-rose-500 transition-colors" />
                  <span className="hidden lg:inline text-xs text-espresso-400 font-normal">Search...</span>
                </button>
              )}

              {/* Price Alerts Link with Badge */}
              <Link
                to="/watchlist"
                aria-label="View price alerts"
                className="relative p-2 rounded-full bg-white border border-rose-200/70 hover:border-rose-400 text-espresso-600 hover:text-rose-600 transition-all shadow-xs"
              >
                <Bell className="w-4 h-4 text-espresso-600" />
                {unreadAlertCount > 0 && (
                  <span className="absolute -top-1 -right-1 bg-rose-500 text-ivory text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center shadow-xs">
                    {unreadAlertCount}
                  </span>
                )}
              </Link>

              {/* Wishlist Drawer Button */}
              <button
                onClick={onOpenWishlist}
                aria-label="View saved wishlist"
                className="relative p-2 rounded-full bg-white border border-rose-200/70 hover:border-rose-400 text-espresso-600 hover:text-rose-600 transition-all shadow-xs"
              >
                <Heart className={`w-4 h-4 ${wishlistCount > 0 ? 'text-rose-500 fill-rose-500' : ''}`} />
                {wishlistCount > 0 && (
                  <motion.span
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    className="absolute -top-1 -right-1 bg-rose-500 text-ivory text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center shadow-xs"
                  >
                    {wishlistCount}
                  </motion.span>
                )}
              </button>

              {/* User Account Dropdown / Sign In Trigger */}
              {user ? (
                <div className="relative" ref={dropdownRef}>
                  <button
                    onClick={() => setUserDropdownOpen(!userDropdownOpen)}
                    className="flex items-center space-x-1.5 p-1 sm:px-2 sm:py-1 rounded-full bg-white border border-rose-200 hover:border-rose-400 text-espresso-700 transition-all shadow-xs"
                    aria-label="User profile menu"
                  >
                    <div className="w-6 h-6 rounded-full bg-gradient-to-br from-rose-400 to-rose-600 text-ivory text-xs font-bold flex items-center justify-center">
                      {user.name ? user.name.charAt(0).toUpperCase() : 'U'}
                    </div>
                    <span className="hidden sm:inline text-xs font-medium max-w-[85px] truncate">
                      {user.name}
                    </span>
                  </button>

                  <AnimatePresence>
                    {userDropdownOpen && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: 10 }}
                        className="absolute right-0 mt-2 w-48 bg-ivory border border-rose-200/80 rounded-2xl shadow-xl py-2 z-50 glass-panel"
                      >
                        <div className="px-4 py-2 border-b border-rose-100/60">
                          <p className="text-xs font-semibold text-espresso-900 truncate">{user.name}</p>
                          <p className="text-[10px] text-espresso-500 truncate">{user.email}</p>
                        </div>
                        <Link
                          to="/profile"
                          onClick={() => setUserDropdownOpen(false)}
                          className="flex items-center space-x-2 px-4 py-2 text-xs text-espresso-700 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                        >
                          <UserIcon className="w-3.5 h-3.5" />
                          <span>Skin Profile</span>
                        </Link>
                        <Link
                          to="/routines"
                          onClick={() => setUserDropdownOpen(false)}
                          className="flex items-center space-x-2 px-4 py-2 text-xs text-espresso-700 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                        >
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>My Routines</span>
                        </Link>
                        <Link
                          to="/watchlist"
                          onClick={() => setUserDropdownOpen(false)}
                          className="flex items-center space-x-2 px-4 py-2 text-xs text-espresso-700 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                        >
                          <Bell className="w-3.5 h-3.5" />
                          <span>Watchlist</span>
                        </Link>
                        <Link
                          to="/admin"
                          onClick={() => setUserDropdownOpen(false)}
                          className="flex items-center space-x-2 px-4 py-2 text-xs text-espresso-700 hover:bg-rose-50 hover:text-rose-600 transition-colors"
                        >
                          <Settings className="w-3.5 h-3.5" />
                          <span>Admin Dashboard</span>
                        </Link>
                        <div className="border-t border-rose-100/60 mt-1 pt-1">
                          <button
                            onClick={() => {
                              setUserDropdownOpen(false);
                              logout();
                            }}
                            className="w-full flex items-center space-x-2 px-4 py-2 text-xs text-rose-600 hover:bg-rose-50 transition-colors"
                          >
                            <LogOut className="w-3.5 h-3.5" />
                            <span>Sign Out</span>
                          </button>
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              ) : (
                <button
                  onClick={() => openAuthModal('login')}
                  className="px-3 py-1.5 rounded-full bg-gradient-to-r from-rose-500 to-rose-600 hover:from-rose-600 hover:to-rose-700 text-ivory text-xs font-semibold shadow-xs hover:shadow-md transition-all flex items-center space-x-1"
                >
                  <UserIcon className="w-3.5 h-3.5" />
                  <span>Sign In</span>
                </button>
              )}

              {/* Mobile Menu Button */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="p-2 md:hidden text-espresso-700 hover:text-rose-600 focus:outline-hidden"
                aria-label="Toggle navigation menu"
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Mobile Drawer Menu */}
      <AnimatePresence>
        {mobileMenuOpen && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="fixed inset-x-0 top-18 z-30 bg-ivory border-b border-rose-200 shadow-xl p-6 md:hidden glass-panel"
          >
            <div className="flex flex-col space-y-3.5">
              <button
                onClick={() => handleNavClick('all', 'catalog')}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1"
              >
                Discover All Products
              </button>
              <button
                onClick={() => handleNavClick('skincare', 'catalog')}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1"
              >
                Skincare Collection
              </button>
              <button
                onClick={() => handleNavClick('makeup', 'catalog')}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1"
              >
                Makeup Collection
              </button>
              <Link
                to="/routines"
                onClick={() => setMobileMenuOpen(false)}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1"
              >
                Personalized Routines (AM/PM)
              </Link>
              <Link
                to="/profile"
                onClick={() => setMobileMenuOpen(false)}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1"
              >
                Skin Profile & Preferences
              </Link>
              <Link
                to="/watchlist"
                onClick={() => setMobileMenuOpen(false)}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1 flex items-center justify-between"
              >
                <span>Watchlist & Price Alerts</span>
                {unreadAlertCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500 text-ivory">
                    {unreadAlertCount}
                  </span>
                )}
              </Link>
              <Link
                to="/admin"
                onClick={() => setMobileMenuOpen(false)}
                className="text-left font-medium text-espresso-800 hover:text-rose-600 py-1 flex items-center justify-between"
              >
                <span>Admin Dashboard</span>
              </Link>

              <div className="border-t border-rose-100 pt-3">
                {user ? (
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold text-espresso-900">{user.name}</p>
                      <p className="text-[10px] text-espresso-500">{user.email}</p>
                    </div>
                    <button
                      onClick={() => {
                        setMobileMenuOpen(false);
                        logout();
                      }}
                      className="text-xs font-semibold text-rose-600 hover:underline"
                    >
                      Sign Out
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => {
                      setMobileMenuOpen(false);
                      openAuthModal('login');
                    }}
                    className="w-full py-2.5 rounded-xl bg-rose-500 text-ivory text-xs font-semibold text-center"
                  >
                    Sign In / Register
                  </button>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
};
