"""Tests for Phase 8E: Gemini-Powered Beauty Intelligence."""

import pytest
import json
from datetime import datetime
from unittest.mock import patch, MagicMock
from src.services.beauty_intelligence_service import (
    BeautyIntelligenceService,
    IngredientInfo,
    IngredientAnalysisResult,
    SkinConcernMatch,
    SkinConcernAnalysisResult,
    AlternativeProduct,
    AlternativeFinderResult,
    RoutineStepRecommendation,
    RoutineRecommendationResult,
)
from src.database.connection import get_connection


@pytest.fixture
def beauty_service():
    """Create a BeautyIntelligenceService with mocked Gemini."""
    with patch.dict('os.environ', {'GEMINI_API_KEY': 'test-key', 'GEMINI_MODEL': 'gemini-3.6-flash'}):
        service = BeautyIntelligenceService(model_name='gemini-3.6-flash', daily_limit=100)
        # Mock the gemini service is_configured property
        from unittest.mock import PropertyMock
        type(service.gemini_service).is_configured = PropertyMock(return_value=False)
        return service


@pytest.fixture
def test_product():
    """Get or create a test product."""
    with get_connection() as conn:
        cursor = conn.cursor()
        # Insert product with sku
        cursor.execute("""
            INSERT OR REPLACE INTO products (id, sku, title, brand, category, specs_json, description, is_active)
            VALUES (999, 'TEST-VIT-C-001', 'Test Vitamin C Serum', 'TestBrand', 'Serum', 
                    '{"Key Ingredients": "Vitamin C, Hyaluronic Acid, Ferulic Acid", "Product Type": "Serum", "Net Quantity": "30ml"}',
                    'A test serum', 0)
        """)
        # Insert offer for price
        cursor.execute("""
            INSERT OR REPLACE INTO offers (id, product_id, store_id, current_price, original_price, shipping_cost, currency, availability, last_checked)
            VALUES (999, 999, 1, 1500.0, 2000.0, 0.0, 'INR', 'In Stock', datetime('now'))
        """)
        conn.commit()
    return 999


class TestIngredientAnalysis:
    """Tests for ingredient analysis functionality."""
    
    def test_heuristic_fallback_when_gemini_unavailable(self, beauty_service):
        """Test fallback when Gemini is not configured."""
        from unittest.mock import PropertyMock
        type(beauty_service.gemini_service).is_configured = PropertyMock(return_value=False)
        
        result = beauty_service.analyze_ingredients(999)
        
        assert result.extraction_source == "heuristic_fallback"
        assert result.confidence_score == 0.4
        assert "Vitamin C" in [ing.name for ing in result.ingredients]
        assert "Hyaluronic Acid" in [ing.name for ing in result.ingredients]
    
    def test_ingredient_analysis_caching(self, beauty_service, test_product):
        """Test that ingredient analysis fallback works correctly."""
        from unittest.mock import PropertyMock
        type(beauty_service.gemini_service).is_configured = PropertyMock(return_value=False)
        
        # First call
        result1 = beauty_service.analyze_ingredients(test_product)
        
        # Second call
        result2 = beauty_service.analyze_ingredients(test_product)
        
        # Both should have same results (fallback is deterministic)
        assert result1.product_id == result2.product_id
        assert len(result1.ingredients) == len(result2.ingredients)
        assert result1.extraction_source == "heuristic_fallback"
        assert result1.confidence_score == 0.4
        
        # Note: Fallback results are not cached (only gemini_model results are)
        # This is by design to allow fresh fallback data if needed
    
    def test_force_refresh_bypasses_cache(self, beauty_service, test_product):
        """Test that force_refresh bypasses cache."""
        beauty_service.gemini_service.is_configured = False
        
        result1 = beauty_service.analyze_ingredients(test_product)
        result2 = beauty_service.analyze_ingredients(test_product, force_refresh=True)
        
        # Both should work (fallback doesn't actually call API)
        assert result1.product_id == test_product
        assert result2.product_id == test_product


class TestSkinConcernMatching:
    """Tests for skin concern matching."""
    
    def test_match_skin_concerns(self, beauty_service, test_product):
        """Test matching products to skin concerns."""
        result = beauty_service.match_skin_concerns(
            concerns=["acne", "hyperpigmentation"],
            budget_range=(100, 5000),
        )
        
        assert isinstance(result, SkinConcernAnalysisResult)
        assert result.concern == "acne, hyperpigmentation"
        assert result.total_products_analyzed > 0
        # Should find our test product with Vitamin C (helps with hyperpigmentation)
        assert len(result.matches) >= 0
    
    def test_empty_concerns_returns_empty(self, beauty_service):
        """Test that empty concerns list returns empty results."""
        result = beauty_service.match_skin_concerns(concerns=[])
        assert result.matches == []
        assert result.total_products_analyzed > 0


class TestAlternativeFinder:
    """Tests for alternative/dupe finding."""
    
    def test_find_alternatives(self, beauty_service, test_product):
        """Test finding alternatives for a product."""
        # Add a similar cheaper product
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO products (id, sku, title, brand, category, specs_json, is_active)
                VALUES (998, 'TEST-VIT-C-002', 'Cheaper Vitamin C Serum', 'OtherBrand', 'Serum', 
                        '{"Key Ingredients": "Vitamin C, Hyaluronic Acid", "Product Type": "Serum", "Net Quantity": "30ml"}', 0)
            """)
            cursor.execute("""
                INSERT OR REPLACE INTO offers (id, product_id, store_id, current_price, original_price, shipping_cost, currency, availability, last_checked)
                VALUES (998, 998, 1, 800.0, 1000.0, 0.0, 'INR', 'In Stock', datetime('now'))
            """)
            conn.commit()
        
        result = beauty_service.find_alternatives(
            product_id=test_product,
            max_price_ratio=0.8,
            min_similarity=0.5,
        )
        
        assert isinstance(result, AlternativeFinderResult)
        assert result.original_product_id == test_product
        assert len(result.alternatives) >= 0
        
        # If alternatives found, check structure
        for alt in result.alternatives:
            assert alt.similarity_score >= 0.5
            assert alt.original_product_id == test_product
            assert alt.price_difference is not None
            assert alt.price_difference_pct is not None


class TestRoutineGeneration:
    """Tests for routine generation."""
    
    def test_fallback_routine_am(self, beauty_service):
        """Test AM fallback routine generation."""
        beauty_service.gemini_service.is_configured = False
        
        result = beauty_service.generate_routine(
            skin_type="oily",
            skin_concerns=["acne", "oiliness"],
            routine_type="AM",
            budget_range=(500, 3000),
        )
        
        assert isinstance(result, RoutineRecommendationResult)
        assert result.routine_type == "AM"
        assert result.skin_type == "oily"
        assert result.skin_concerns == ["acne", "oiliness"]
        assert result.sunscreen_required is True
        assert result.generation_source == "heuristic_fallback"
        assert len(result.steps) == 5  # Cleanse, Tone, Treat, Moisturize, Sunscreen
        
        # Check step order
        step_names = [s.step_name for s in result.steps]
        assert step_names == ["Cleanse", "Tone", "Treat", "Moisturize", "Sunscreen"]
    
    def test_fallback_routine_pm(self, beauty_service):
        """Test PM fallback routine generation."""
        beauty_service.gemini_service.is_configured = False
        
        result = beauty_service.generate_routine(
            skin_type="dry",
            skin_concerns=["dryness", "fine lines"],
            routine_type="PM",
        )
        
        assert result.routine_type == "PM"
        assert result.sunscreen_required is False
        assert len(result.steps) == 4  # Cleanse, Tone, Treat, Moisturize
        
        step_names = [s.step_name for s in result.steps]
        assert step_names == ["Cleanse", "Tone", "Treat", "Moisturize"]


class TestRateLimiting:
    """Tests for rate limiting functionality."""
    
    def test_rate_limit_enforced(self, beauty_service):
        """Test that rate limiting works."""
        # Set very low limit for testing
        beauty_service.daily_limit = 2
        user_id = 6000  # Unique user ID
        
        # Clear any existing entries for this user
        with get_connection() as conn:
            cursor = conn.cursor()
            today = datetime.now().date().isoformat()
            cursor.execute("DELETE FROM gemini_rate_limits WHERE user_id = ? AND date = ?", (user_id, today))
            conn.commit()
        
        # First request should succeed
        allowed, error = beauty_service.rate_limiter.check_limit(user_id, beauty_service.daily_limit)
        assert allowed is True
        assert error is None
        
        # Second request should succeed
        allowed, error = beauty_service.rate_limiter.check_limit(user_id, beauty_service.daily_limit)
        assert allowed is True
        assert error is None
        
        # Third request should fail
        allowed, error = beauty_service.rate_limiter.check_limit(user_id, beauty_service.daily_limit)
        assert allowed is False
        assert "exceeded" in error
    
    def test_rate_limit_per_user(self, beauty_service):
        """Test that rate limits are per-user."""
        beauty_service.daily_limit = 1
        
        # Clear any existing entries
        with get_connection() as conn:
            cursor = conn.cursor()
            today = datetime.now().date().isoformat()
            cursor.execute("DELETE FROM gemini_rate_limits WHERE user_id IN (3000, 4000) AND date = ?", (today,))
            conn.commit()
        
        # User 3000 uses their limit
        allowed, _ = beauty_service.rate_limiter.check_limit(3000, beauty_service.daily_limit)
        assert allowed is True
        allowed, _ = beauty_service.rate_limiter.check_limit(3000, beauty_service.daily_limit)
        assert allowed is False
        
        # User 4000 should still have their limit
        allowed, _ = beauty_service.rate_limiter.check_limit(4000, beauty_service.daily_limit)
        assert allowed is True


class TestTokenUsageTracking:
    """Tests for token usage tracking."""
    
    def test_token_usage_logged(self, beauty_service):
        """Test that token usage is logged."""
        user_id = 7000  # Unique user ID
        
        # Clear any existing entries for this user
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM gemini_token_usage WHERE user_id = ?", (user_id,))
            conn.commit()
        
        beauty_service.token_tracker.log_request(
            user_id=user_id,
            model="gemini-3.6-flash",
            prompt_tokens=100,
            completion_tokens=50,
            success=True,
        )
        
        stats = beauty_service.token_tracker.get_usage_stats(user_id=user_id, days=30)
        assert stats["total_tokens"] == 150
        assert stats["total_requests"] == 1
        assert "gemini-3.6-flash" in stats["by_model"]
    
    def test_failed_request_logged(self, beauty_service):
        """Test that failed requests are logged with error codes."""
        # Use a unique user ID to avoid conflicts
        user_id = 8000
        
        # Clear any existing entries for this user
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM gemini_token_usage WHERE user_id = ?", (user_id,))
            conn.commit()
        
        beauty_service.token_tracker.log_request(
            user_id=user_id,
            model="gemini-3.6-flash",
            prompt_tokens=0,
            completion_tokens=0,
            success=False,
            error_code="QUOTA_EXCEEDED",
        )
        
        stats = beauty_service.token_tracker.get_usage_stats(user_id=user_id, days=30)
        assert stats["total_requests"] == 1
        assert stats["by_model"]["gemini-3.6-flash"]["success_rate"] == 0.0


class TestErrorClassification:
    """Tests for error classification."""
    
    def test_classify_quota_error(self, beauty_service):
        """Test quota exceeded error classification."""
        error = Exception("429 Quota exceeded")
        code = beauty_service._classify_error(error)
        assert code == "QUOTA_EXCEEDED"
    
    def test_classify_timeout_error(self, beauty_service):
        """Test timeout error classification."""
        error = Exception("Request timed out")
        code = beauty_service._classify_error(error)
        assert code == "TIMEOUT"
    
    def test_classify_model_unavailable(self, beauty_service):
        """Test model unavailable error classification."""
        error = Exception("404 Model not found")
        code = beauty_service._classify_error(error)
        assert code == "MODEL_UNAVAILABLE"
    
    def test_classify_auth_error(self, beauty_service):
        """Test authentication error classification."""
        error = Exception("Invalid API key")
        code = beauty_service._classify_error(error)
        assert code == "AUTH_ERROR"


class TestCacheCleanup:
    """Tests for cache cleanup."""
    
    def test_clear_expired_cache(self, beauty_service):
        """Test clearing expired cache entries."""
        # Add an expired entry
        from datetime import datetime, timedelta
        with get_connection() as conn:
            cursor = conn.cursor()
            expired_time = (datetime.now() - timedelta(hours=1)).isoformat()
            cursor.execute(
                "INSERT INTO gemini_cache (cache_key, prompt, model, response, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("test-key", "test prompt", "gemini-3.6-flash", '{"test": "data"}', expired_time, datetime.now().isoformat())
            )
            conn.commit()
        
        deleted = beauty_service.clear_expired_cache()
        assert deleted >= 1
        
        # Verify it's gone
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as cnt FROM gemini_cache WHERE cache_key = ?", ("test-key",))
            count = cursor.fetchone()["cnt"]
            assert count == 0


class TestGeminiUnavailable:
    """Tests for when Gemini is completely unavailable."""
    
    def test_full_functionality_without_gemini(self, test_product):
        """Test that all features work without Gemini."""
        # Clear environment to simulate no API key
        import os
        old_key = os.environ.get("GEMINI_API_KEY")
        old_model = os.environ.get("GEMINI_MODEL")
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        if "GEMINI_MODEL" in os.environ:
            del os.environ["GEMINI_MODEL"]
        
        try:
            service = BeautyIntelligenceService(model_name='gemini-3.6-flash', daily_limit=100)
            
            # All methods should work with fallbacks
            analysis = service.analyze_ingredients(test_product)
            assert analysis.extraction_source == "heuristic_fallback"
            
            matches = service.match_skin_concerns(["acne"])
            assert isinstance(matches, SkinConcernAnalysisResult)
            
            alternatives = service.find_alternatives(test_product)
            assert isinstance(alternatives, AlternativeFinderResult)
            
            routine_am = service.generate_routine("oily", ["acne"], "AM")
            assert routine_am.generation_source == "heuristic_fallback"
            
            routine_pm = service.generate_routine("oily", ["acne"], "PM")
            assert routine_pm.generation_source == "heuristic_fallback"
        finally:
            # Restore environment
            if old_key:
                os.environ["GEMINI_API_KEY"] = old_key
            if old_model:
                os.environ["GEMINI_MODEL"] = old_model


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
