/**
 * Admin Dashboard for Phase 16.4
 *
 * Main admin interface with tabs for:
 * - OBF Verification Queue
 * - Manual Price Entry
 * - Observation Dashboard
 * - Connector Health
 * - Match Correction Workflow
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
  ShieldCheck,
  Clock,
  Database,
  Wifi,
  Settings,
  Search,
  RefreshCw,
  Plus,
  Eye,
  Check,
  X,
  Filter,
  AlertTriangle,
  Zap,
  Stethoscope,
} from 'lucide-react';
import { getHealthStats, getPriceInIndiaHealth, getOBFHealth, searchPriceInIndia, findPriceInIndiaProduct, lookupOBFByBarcode, searchOBFProducts, adminCorrectMatch, expireStaleObservations } from '../../lib/api/v2-client';
import { MatchBadge } from '../MatchBadge';
import { ConnectivityStatus } from '../ErrorState';

interface AdminDashboardProps {
  onClose?: () => void;
}

export const AdminDashboard: React.FC<AdminDashboardProps> = ({ onClose }) => {
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [isLoading, setIsLoading] = useState(false);
  const [healthStats, setHealthStats] = useState<any>(null);
  const [piHealth, setPiHealth] = useState<any>(null);
  const [obfHealth, setObfHealth] = useState<any>(null);
  const [searchResults, setSearchResults] = useState<any>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchBrand, setSearchBrand] = useState('');
  const [matchCorrection, setMatchCorrection] = useState<any>(null);
  const [correctionClassification, setCorrectionClassification] = useState('');
  const [correctionNote, setCorrectionNote] = useState('');
  const [expireLoading, setExpireLoading] = useState(false);

  const tabs = [
    { id: 'overview', label: 'Overview', icon: <ShieldCheck className="w-4 h-4" /> },
    { id: 'obs-dashboard', label: 'Observations', icon: <Database className="w-4 h-4" /> },
    { id: 'connectors', label: 'Connectors', icon: <Wifi className="w-4 h-4" /> },
    { id: 'match-correction', label: 'Match Correction', icon: <AlertTriangle className="w-4 h-4" /> },
    { id: 'price-entry', label: 'Manual Price Entry', icon: <Plus className="w-4 h-4" /> },
    { id: 'obf-queue', label: 'OBF Verification', icon: <Stethoscope className="w-4 h-4" /> },
  ];

  const fetchHealth = useCallback(async () => {
    setIsLoading(true);
    try {
      const [stats, pi, obf] = await Promise.all([
        getHealthStats(),
        getPriceInIndiaHealth(),
        getOBFHealth(),
      ]);
      setHealthStats(stats);
      setPiHealth(pi);
      setObfHealth(obf);
    } catch (err) {
      console.error('Failed to fetch health stats:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const handleSearchPriceInIndia = async () => {
    if (!searchQuery.trim()) return;
    setIsLoading(true);
    try {
      const result = await searchPriceInIndia(searchQuery, searchBrand || undefined);
      setSearchResults(result);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleFindPriceInIndia = async () => {
    if (!searchQuery.trim()) return;
    setIsLoading(true);
    try {
      const result = await findPriceInIndiaProduct(searchBrand || 'Unknown', searchQuery);
      setSearchResults(result);
    } catch (err) {
      console.error('Find failed:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleLookupOBF = async () => {
    if (!searchQuery.trim()) return;
    setIsLoading(true);
    try {
      const result = await lookupOBFByBarcode(searchQuery.trim());
      setSearchResults(result);
    } catch (err) {
      console.error('OBF lookup failed:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSearchOBF = async () => {
    setIsLoading(true);
    try {
      const brands = searchBrand ? [searchBrand] : undefined;
      const result = await searchOBFProducts(brands);
      setSearchResults(result);
    } catch (err) {
      console.error('OBF search failed:', err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleExpireStale = async () => {
    setExpireLoading(true);
    try {
      const result = await expireStaleObservations(72);
      alert(`Expired ${result.expired_count} stale observations`);
      fetchHealth();
    } catch (err) {
      console.error('Expire stale failed:', err);
      alert('Failed to expire stale observations');
    } finally {
      setExpireLoading(false);
    }
  };

  const handleCorrectMatch = async () => {
    if (!matchCorrection || !correctionClassification) return;
    setIsLoading(true);
    try {
      await adminCorrectMatch({
        stored_result: matchCorrection,
        new_classification: correctionClassification,
        correction_note: correctionNote,
      });
      alert('Match correction applied successfully')
      setMatchCorrection(null);
      setCorrectionClassification('');
      setCorrectionNote('');
      fetchHealth();
    } catch (err) {
      console.error('Match correction failed:', err);
      alert('Failed to apply match correction');
    } finally {
      setIsLoading(false);
    }
  };

  const renderOverview = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-editorial text-2xl font-bold text-espresso-900">System Overview</h2>
        <button onClick={fetchHealth} disabled={isLoading} className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all disabled:opacity-50">
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      <ConnectivityStatus
        isOnline={typeof navigator !== 'undefined' ? navigator.onLine : true}
        isBackendAvailable={!!healthStats}
        lastChecked="Just now"
      />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Active Products', value: healthStats?.total_active_products || 0, icon: Database, color: 'text-sage-600', bg: 'bg-sage-50' },
          { label: 'Manufacturer Verified', value: healthStats?.manufacturer_verified || 0, icon: ShieldCheck, color: 'text-green-600', bg: 'bg-green-50' },
          { label: 'Live Observations', value: healthStats?.live_observations || 0, icon: Zap, color: 'text-rose-600', bg: 'bg-rose-50' },
          { label: 'Flagged Observations', value: healthStats?.flagged_observations || 0, icon: AlertTriangle, color: 'text-amber-600', bg: 'bg-amber-50' },
          { label: 'Expired Observations', value: healthStats?.expired_observations || 0, icon: Clock, color: 'text-gray-600', bg: 'bg-gray-50' },
          { label: 'Active Retailers', value: healthStats?.active_retailers || 0, icon: Settings, color: 'text-blue-600', bg: 'bg-blue-50' },
        ].map((stat) => (
          <div key={stat.label} className={`${stat.bg} border border-rose-100 rounded-2xl p-5`}>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-bold text-espresso-400 uppercase tracking-wider">{stat.label}</p>
                <p className="text-3xl font-extrabold text-espresso-900">{stat.value.toLocaleString()}</p>
              </div>
              <div className={`w-12 h-12 rounded-xl ${stat.bg} flex items-center justify-center`}>
                <stat.icon className={`w-6 h-6 ${stat.color}`} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white border border-rose-200 rounded-2xl p-5">
          <h3 className="font-semibold text-espresso-900 mb-3">PriceInIndia MCP Connector</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-espresso-500">Endpoint</span><span className="font-mono text-espresso-800">{piHealth?.endpoint || 'N/A'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Status</span><span className={`font-semibold ${piHealth?.is_healthy ? 'text-green-600' : 'text-rose-600'}`}>{piHealth?.is_healthy ? 'Healthy' : 'Unhealthy'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Requests</span><span className="font-mono text-espresso-800">{piHealth?.total_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Failed</span><span className="font-mono text-rose-600">{piHealth?.failed_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Avg Response</span><span className="font-mono text-espresso-800">{piHealth?.avg_response_time_ms || 0}ms</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Last Success</span><span className="font-mono text-espresso-800">{piHealth?.last_success_at || 'Never'}</span></div>
            {piHealth?.last_error && <div className="flex justify-between"><span className="text-espresso-500">Last Error</span><span className="font-mono text-rose-600 text-xs">{piHealth.last_error}</span></div>}
          </div>
        </div>

        <div className="bg-white border border-rose-200 rounded-2xl p-5">
          <h3 className="font-semibold text-espresso-900 mb-3">Open Beauty Facts Connector</h3>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between"><span className="text-espresso-500">Endpoint</span><span className="font-mono text-espresso-800">{obfHealth?.endpoint || 'N/A'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Status</span><span className={`font-semibold ${obfHealth?.is_healthy ? 'text-green-600' : 'text-rose-600'}`}>{obfHealth?.is_healthy ? 'Healthy' : 'Unhealthy'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Requests</span><span className="font-mono text-espresso-800">{obfHealth?.total_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Failed</span><span className="font-mono text-rose-600">{obfHealth?.failed_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Avg Response</span><span className="font-mono text-espresso-800">{obfHealth?.avg_response_time_ms || 0}ms</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Last Success</span><span className="font-mono text-espresso-800">{obfHealth?.last_success_at || 'Never'}</span></div>
            {obfHealth?.last_error && <div className="flex justify-between"><span className="text-espresso-500">Last Error</span><span className="font-mono text-rose-600 text-xs">{obfHealth.last_error}</span></div>}
          </div>
        </div>
      </div>
    </div>
  );

  const renderObservationsDashboard = () => (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="font-editorial text-2xl font-bold text-espresso-900">Price Observations Dashboard</h2>
        <div className="flex items-center space-x-2">
          <button onClick={handleExpireStale} disabled={expireLoading} className="px-3 py-1.5 rounded-xl border border-amber-200 bg-amber-50 hover:bg-amber-100 text-amber-700 text-xs font-semibold flex items-center space-x-1.5 transition-all disabled:opacity-50">
            <Clock className="w-3.5 h-3.5" />
            <span>Expire Stale (72h)</span>
          </button>
          <button onClick={fetchHealth} disabled={isLoading} className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all disabled:opacity-50">
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <div className="flex items-center space-x-3 mb-4">
          <input
            type="text"
            placeholder="Search observations..."
            className="flex-1 px-3 py-2 rounded-xl border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
          />
          <button className="px-4 py-2 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold flex items-center space-x-1.5">
            <Search className="w-3.5 h-3.5" />
            <span>Search</span>
          </button>
          <button className="px-4 py-2 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-bold flex items-center space-x-1.5">
            <Filter className="w-3.5 h-3.5" />
            <span>Filter</span>
          </button>
        </div>
        <div className="text-center py-8 text-espresso-500">
          <Database className="w-12 h-12 mx-auto text-espresso-300 mb-3" />
          <p>Observation dashboard with filtering, sorting, and bulk actions</p>
          <p className="text-xs text-espresso-400 mt-1">Connect to backend /api/admin/price-observations endpoint</p>
        </div>
      </div>
    </div>
  );

  const renderConnectors = () => (
    <div className="space-y-6">
      <h2 className="font-editorial text-2xl font-bold text-espresso-900">Connector Health & Management</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* PriceInIndia Connector */}
        <div className="bg-white border border-rose-200 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-espresso-900 flex items-center space-x-2">
              <Zap className="w-5 h-5 text-rose-500" />
              <span>PriceInIndia MCP</span>
            </h3>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${piHealth?.is_healthy ? 'bg-green-50 text-green-800' : 'bg-rose-50 text-rose-800'}`}>
              {piHealth?.is_healthy ? 'HEALTHY' : 'UNHEALTHY'}
            </span>
          </div>
          <div className="space-y-2 text-sm mb-4">
            <div className="flex justify-between"><span className="text-espresso-500">Endpoint</span><span className="font-mono text-espresso-800 text-xs">{piHealth?.endpoint || 'N/A'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Total Requests</span><span className="font-mono text-espresso-800">{piHealth?.total_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Failed Requests</span><span className="font-mono text-rose-600">{piHealth?.failed_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Avg Response</span><span className="font-mono text-espresso-800">{piHealth?.avg_response_time_ms || 0}ms</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Last Success</span><span className="font-mono text-espresso-800">{piHealth?.last_success_at || 'Never'}</span></div>
          </div>
          <div className="flex items-center space-x-2">
            <button className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5">
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Health Check</span>
            </button>
            <button className="px-3 py-1.5 rounded-xl bg-rose-500 hover:bg-rose-600 text-ivory text-xs font-semibold flex items-center space-x-1.5">
              <Search className="w-3.5 h-3.5" />
              <span>Test Search</span>
            </button>
          </div>
        </div>

        {/* Open Beauty Facts Connector */}
        <div className="bg-white border border-rose-200 rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="font-semibold text-espresso-900 flex items-center space-x-2">
              <Stethoscope className="w-5 h-5 text-sage-500" />
              <span>Open Beauty Facts</span>
            </h3>
            <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${obfHealth?.is_healthy ? 'bg-green-50 text-green-800' : 'bg-rose-50 text-rose-800'}`}>
              {obfHealth?.is_healthy ? 'HEALTHY' : 'UNHEALTHY'}
            </span>
          </div>
          <div className="space-y-2 text-sm mb-4">
            <div className="flex justify-between"><span className="text-espresso-500">Endpoint</span><span className="font-mono text-espresso-800 text-xs">{obfHealth?.endpoint || 'N/A'}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Total Requests</span><span className="font-mono text-espresso-800">{obfHealth?.total_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Failed Requests</span><span className="font-mono text-rose-600">{obfHealth?.failed_requests || 0}</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Avg Response</span><span className="font-mono text-espresso-800">{obfHealth?.avg_response_time_ms || 0}ms</span></div>
            <div className="flex justify-between"><span className="text-espresso-500">Last Success</span><span className="font-mono text-espresso-800">{obfHealth?.last_success_at || 'Never'}</span></div>
          </div>
          <div className="flex items-center space-x-2">
            <button className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5">
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Health Check</span>
            </button>
            <button className="px-3 py-1.5 rounded-xl bg-sage-500 hover:bg-sage-600 text-ivory text-xs font-semibold flex items-center space-x-1.5">
              <Search className="w-3.5 h-3.5" />
              <span>Test Search</span>
            </button>
          </div>
        </div>
      </div>

      {/* Connector Test Tools */}
      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Connector Test Tools</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* PriceInIndia Search */}
          <div className="border border-rose-200 rounded-xl p-4 bg-rose-50/30">
            <h4 className="font-semibold text-rose-800 mb-3 flex items-center space-x-2">
              <Zap className="w-4 h-4" />
              <span>PriceInIndia Search</span>
            </h4>
            <div className="space-y-2">
              <input
                type="text"
                placeholder="Product name to search..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
              />
              <input
                type="text"
                placeholder="Brand (optional)..."
                value={searchBrand}
                onChange={(e) => setSearchBrand(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
              />
              <div className="flex space-x-2">
                <button onClick={handleSearchPriceInIndia} disabled={isLoading} className="flex-1 px-3 py-2 rounded-lg bg-rose-500 hover:bg-rose-600 text-ivory text-xs font-bold disabled:opacity-50">
                  {isLoading ? 'Searching...' : 'Search Products'}
                </button>
                <button onClick={handleFindPriceInIndia} disabled={isLoading} className="flex-1 px-3 py-2 rounded-lg border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-bold disabled:opacity-50">
                  Find Exact Match
                </button>
              </div>
            </div>
          </div>

          {/* Open Beauty Facts Search */}
          <div className="border border-sage-200 rounded-xl p-4 bg-sage-50/30">
            <h4 className="font-semibold text-sage-800 mb-3 flex items-center space-x-2">
              <Stethoscope className="w-4 h-4" />
              <span>Open Beauty Facts</span>
            </h4>
            <div className="space-y-2">
              <input
                type="text"
                placeholder="Barcode to lookup..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-sage-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-sage-300"
              />
              <input
                type="text"
                placeholder="Brand filter (optional)..."
                value={searchBrand}
                onChange={(e) => setSearchBrand(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-sage-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-sage-300"
              />
              <div className="flex space-x-2">
                <button onClick={handleLookupOBF} disabled={isLoading} className="flex-1 px-3 py-2 rounded-lg bg-sage-500 hover:bg-sage-600 text-ivory text-xs font-bold disabled:opacity-50">
                  {isLoading ? 'Looking up...' : 'Lookup by Barcode'}
                </button>
                <button onClick={handleSearchOBF} disabled={isLoading} className="flex-1 px-3 py-2 rounded-lg border border-sage-200 bg-white hover:bg-sage-50/70 text-espresso-700 text-xs font-bold disabled:opacity-50">
                  Search by Brand
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Search Results */}
        {searchResults && (
          <div className="mt-4 p-4 bg-ivory-50 border border-rose-100 rounded-xl">
            <h4 className="font-semibold text-espresso-900 mb-2">Results</h4>
            <pre className="text-xs bg-white p-3 rounded-lg overflow-auto max-h-64 font-mono text-espresso-700">
              {JSON.stringify(searchResults, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );

  const renderMatchCorrection = () => (
    <div className="space-y-6">
      <h2 className="font-editorial text-2xl font-bold text-espresso-900">Match Classification Correction</h2>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Load Match Result for Correction</h3>
        <div className="space-y-3">
          <input
            type="text"
            placeholder="Paste match result JSON or match ID..."
            className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
          />
          <button className="px-4 py-2 rounded-lg bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold flex items-center space-x-1.5">
            <Search className="w-3.5 h-3.5" />
            <span>Load Match</span>
          </button>
        </div>
      </div>

      {matchCorrection && (
        <div className="bg-white border border-rose-200 rounded-2xl p-5">
          <h3 className="font-semibold text-espresso-900 mb-4">Current Classification</h3>
          <MatchBadge
            classification={matchCorrection.match_classification}
            confidence={matchCorrection.confidence_score}
            reasons={matchCorrection.reasons}
            flaggedReasons={matchCorrection.flagged_reasons}
            size="lg"
          />
          <div className="mt-4 p-4 bg-ivory-50 rounded-xl">
            <pre className="text-xs font-mono text-espresso-700 overflow-auto max-h-48">
              {JSON.stringify(matchCorrection, null, 2)}
            </pre>
          </div>
        </div>
      )}

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Apply Correction</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">New Classification</label>
            <select
              value={correctionClassification}
              onChange={(e) => setCorrectionClassification(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
            >
              <option value="">Select classification...</option>
              <option value="verified_match">Verified Match</option>
              <option value="possible_match">Possible Match</option>
              <option value="ambiguous_match">Ambiguous Match</option>
              <option value="incompatible_mismatch">Incompatible Mismatch</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Correction Note (required)</label>
            <textarea
              value={correctionNote}
              onChange={(e) => setCorrectionNote(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300"
              placeholder="Explain why this correction is being made..."
            />
          </div>
          <button
            onClick={handleCorrectMatch}
            disabled={isLoading || !correctionClassification || !correctionNote || !matchCorrection}
            className="w-full px-4 py-2.5 rounded-xl bg-rose-500 hover:bg-rose-600 text-ivory text-xs font-bold disabled:opacity-50 flex items-center justify-center space-x-1.5"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span>Apply Correction</span>
          </button>
        </div>
      </div>
    </div>
  );

  const renderPriceEntry = () => (
    <div className="space-y-6">
      <h2 className="font-editorial text-2xl font-bold text-espresso-900">Manual Price Entry</h2>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Enter Verified Price Observation</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Product ID / SKU</label>
            <input type="text" placeholder="prod-123 or barcode" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Retailer</label>
            <select className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300">
              <option value="">Select retailer...</option>
              <option value="nykaa">Nykaa</option>
              <option value="myntra">Myntra</option>
              <option value="purplle">Purplle</option>
              <option value="tira">Tira</option>
              <option value="amazon">Amazon India</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Listed Price (₹)</label>
            <input type="number" placeholder="599" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">MRP (₹)</label>
            <input type="number" placeholder="799" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Shipping Fee (₹)</label>
            <input type="number" placeholder="0" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Coupon Code</label>
            <input type="text" placeholder="SAVE10" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Coupon Discount (₹)</label>
            <input type="number" placeholder="50" className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Stock Status</label>
            <select className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300">
              <option value="in_stock">In Stock</option>
              <option value="out_of_stock">Out of Stock</option>
              <option value="limited">Limited Availability</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-semibold text-espresso-700 mb-1">Source Type</label>
            <select className="w-full px-3 py-2 rounded-lg border border-rose-200 bg-white text-espresso-900 text-sm focus:outline-hidden focus:ring-2 focus:ring-rose-300">
              <option value="manual">Manual Entry</option>
              <option value="verified_live">Verified Live</option>
              <option value="partner_feed">Partner Feed</option>
            </select>
          </div>
        </div>
        <div className="mt-4 flex space-x-2">
          <button className="px-4 py-2.5 rounded-xl bg-rose-500 hover:bg-rose-600 text-ivory text-xs font-bold flex items-center space-x-1.5">
            <Plus className="w-3.5 h-3.5" />
            <span>Submit Price Entry</span>
          </button>
          <button className="px-4 py-2.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-bold">
            Clear Form
          </button>
        </div>
      </div>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Recent Manual Entries</h3>
        <div className="text-center py-8 text-espresso-500">
          <Database className="w-12 h-12 mx-auto text-espresso-300 mb-3" />
          <p>Manual price entry history with edit/delete actions</p>
          <p className="text-xs text-espresso-400 mt-1">Connect to backend /api/admin/price-observations endpoint</p>
        </div>
      </div>
    </div>
  );

  const renderOBFQueue = () => (
    <div className="space-y-6">
      <h2 className="font-editorial text-2xl font-bold text-espresso-900">Open Beauty Facts Verification Queue</h2>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Products Requiring OBF Verification</h3>
        <div className="space-y-3 mb-4">
          <div className="flex items-center space-x-3 p-3 bg-ivory-50 rounded-xl border border-rose-100">
            <div className="w-10 h-10 rounded-lg bg-rose-100 flex items-center justify-center">
              <Stethoscope className="w-5 h-5 text-rose-500" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-espresso-900">Lakmé Absolute Matte Melt Liquid Lip Color - 02 Red</p>
              <p className="text-xs text-espresso-500">Barcode: 8901234567890 | Brand: Lakmé</p>
            </div>
            <MatchBadge classification="ambiguous_match" confidence={0.45} size="sm" />
            <div className="flex space-x-1">
              <button className="px-2 py-1 rounded-lg bg-sage-500 hover:bg-sage-600 text-ivory text-xs">
                <Eye className="w-3.5 h-3.5" />
              </button>
              <button className="px-2 py-1 rounded-lg bg-rose-500 hover:bg-rose-600 text-ivory text-xs">
                <Check className="w-3.5 h-3.5" />
              </button>
              <button className="px-2 py-1 rounded-lg border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div className="flex items-center space-x-3 p-3 bg-ivory-50 rounded-xl border border-rose-100">
            <div className="w-10 h-10 rounded-lg bg-rose-100 flex items-center justify-center">
              <Stethoscope className="w-5 h-5 text-rose-500" />
            </div>
            <div className="flex-1">
              <p className="font-semibold text-espresso-900">Maybelline Fit Me Foundation - 128 Warm Nude</p>
              <p className="text-xs text-espresso-500">Barcode: 3600523456789 | Brand: Maybelline</p>
            </div>
            <MatchBadge classification="possible_match" confidence={0.72} size="sm" />
            <div className="flex space-x-1">
              <button className="px-2 py-1 rounded-lg bg-sage-500 hover:bg-sage-600 text-ivory text-xs">
                <Eye className="w-3.5 h-3.5" />
              </button>
              <button className="px-2 py-1 rounded-lg bg-rose-500 hover:bg-rose-600 text-ivory text-xs">
                <Check className="w-3.5 h-3.5" />
              </button>
              <button className="px-2 py-1 rounded-lg border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-white border border-rose-200 rounded-2xl p-5">
        <h3 className="font-semibold text-espresso-900 mb-4">Bulk OBF Sync</h3>
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="space-y-2">
            <p className="text-sm text-espresso-600">Sync product catalog with Open Beauty Facts for ingredient verification and shade matching.</p>
            <div className="flex items-center space-x-2">
              <label className="flex items-center space-x-1 text-xs text-espresso-600">
                <input type="checkbox" className="rounded border-rose-300" />
                <span>Only products without OBF data</span>
              </label>
              <label className="flex items-center space-x-1 text-xs text-espresso-600">
                <input type="checkbox" className="rounded border-rose-300" />
                <span>Update ingredient lists</span>
              </label>
            </div>
          </div>
          <button className="px-4 py-2.5 rounded-xl bg-sage-500 hover:bg-sage-600 text-ivory text-xs font-bold flex items-center space-x-1.5">
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Start OBF Sync</span>
          </button>
        </div>
      </div>
    </div>
  );

  const renderTabContent = () => {
    switch (activeTab) {
      case 'overview':
        return renderOverview();
      case 'obs-dashboard':
        return renderObservationsDashboard();
      case 'connectors':
        return renderConnectors();
      case 'match-correction':
        return renderMatchCorrection();
      case 'price-entry':
        return renderPriceEntry();
      case 'obf-queue':
        return renderOBFQueue();
      default:
        return renderOverview();
    }
  };

  return (
    <div className="min-h-screen bg-ivory text-espresso-900">
      {/* Admin Header */}
      <header className="border-b border-rose-200 bg-white/80 backdrop-blur-xs sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center space-x-4">
              {onClose && (
                <button onClick={onClose} className="px-3 py-1.5 rounded-lg bg-ivory-100 hover:bg-ivory-200 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-colors">
                  <span className="hidden sm:inline">← Back to Site</span>
                </button>
              )}
              <h1 className="font-editorial text-xl font-bold text-espresso-900">Admin Dashboard</h1>
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500 text-ivory">PHASE 16.4</span>
            </div>
            <div className="flex items-center space-x-2">
              <button onClick={fetchHealth} disabled={isLoading} className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all disabled:opacity-50">
                <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? 'animate-spin' : ''}`} />
                <span>Refresh All</span>
              </button>
            </div>
          </div>

          {/* Tab Navigation */}
          <div className="border-t border-rose-100">
            <nav className="flex overflow-x-auto" aria-label="Admin sections">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center space-x-2 px-4 py-3 text-xs font-semibold uppercase tracking-wider whitespace-nowrap transition-all border-b-2 ${
                    activeTab === tab.id
                      ? 'border-rose-500 text-rose-600 bg-rose-50/30'
                      : 'border-transparent text-espresso-500 hover:text-espresso-800 hover:bg-ivory-50'
                  }`}
                >
                  {tab.icon}
                  <span>{tab.label}</span>
                </button>
              ))}
            </nav>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {renderTabContent()}
      </main>
    </div>
  );
};